# SPDX-License-Identifier: Apache-2.0
"""Standalone BLAKE3, RFC-8032 Ed25519 receipts, Physical DC Shunt (`measured_j`) &
Linux RAPL (`reported_j`) metering, and strict privacy/path sanitization.

Provenance tier: `Signed Provenance · Self-Checked` (never self-labeled `Verified`).
Energy classes (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`) are strictly orthogonal and never mixed.
"""

from __future__ import annotations

import datetime as dt
import getpass
import hashlib
import json
import math
import os
import platform
import re
import resource
import shutil
import socket
import statistics
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

# ── 1. Reference BLAKE3 (pure Python, zero external dependencies) ────────────

_IV = [
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
]
_PERM = [2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8]
_CHUNK_START = 1
_CHUNK_END = 2
_PARENT = 4
_ROOT = 8
_DERIVE_KEY_CONTEXT = 32
_DERIVE_KEY_MATERIAL = 64


def _rotr32(x: int, n: int) -> int:
    return ((x >> n) | ((x << (32 - n)) & 0xFFFFFFFF)) & 0xFFFFFFFF


def _g(s: list[int], a: int, b: int, c: int, d: int, mx: int, my: int) -> None:
    s[a] = (s[a] + s[b] + mx) & 0xFFFFFFFF
    s[d] = _rotr32(s[d] ^ s[a], 16)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotr32(s[b] ^ s[c], 12)
    s[a] = (s[a] + s[b] + my) & 0xFFFFFFFF
    s[d] = _rotr32(s[d] ^ s[a], 8)
    s[c] = (s[c] + s[d]) & 0xFFFFFFFF
    s[b] = _rotr32(s[b] ^ s[c], 7)


def _compress(cv: list[int], block_words: list[int], counter: int, block_len: int, flags: int) -> list[int]:
    s = list(cv) + _IV[:4] + [counter & 0xFFFFFFFF, (counter >> 32) & 0xFFFFFFFF, block_len, flags]
    m = list(block_words)
    for rnd in range(7):
        _g(s, 0, 4, 8, 12, m[0], m[1])
        _g(s, 1, 5, 9, 13, m[2], m[3])
        _g(s, 2, 6, 10, 14, m[4], m[5])
        _g(s, 3, 7, 11, 15, m[6], m[7])
        _g(s, 0, 5, 10, 15, m[8], m[9])
        _g(s, 1, 6, 11, 12, m[10], m[11])
        _g(s, 2, 7, 8, 13, m[12], m[13])
        _g(s, 3, 4, 9, 14, m[14], m[15])
        if rnd < 6:
            m = [m[p] for p in _PERM]
    for i in range(8):
        s[i] ^= s[i + 8]
        s[i + 8] ^= cv[i]
    return s


def _words64(chunk_bytes: bytes) -> list[int]:
    padded = chunk_bytes[:64].ljust(64, b"\x00")
    return list(struct.unpack("<16I", padded))


def _blake3_hash_with(data: bytes, key: list[int], flags: int) -> bytes:
    stack: list[list[int]] = []
    chunk = 0
    pos = 0
    while len(data) - pos > 1024:
        cv = list(key)
        for b in range(16):
            st = pos + b * 64
            f = flags | (_CHUNK_START if b == 0 else 0) | (_CHUNK_END if b == 15 else 0)
            cv = _compress(cv, _words64(data[st : st + 64]), chunk, 64, f)[:8]
        chunk += 1
        total = chunk
        node = cv
        while (total & 1) == 0:
            left = stack.pop()
            node = _compress(key, left + node, 0, 64, flags | _PARENT)[:8]
            total >>= 1
        stack.append(node)
        pos += 1024

    rest = data[pos:]
    blocks = max(1, (len(rest) + 63) // 64)
    cv = list(key)
    for b in range(blocks - 1):
        f = flags | (_CHUNK_START if b == 0 else 0)
        cv = _compress(cv, _words64(rest[b * 64 : (b + 1) * 64]), chunk, 64, f)[:8]
    last = rest[(blocks - 1) * 64 :]
    out_cv, out_block, out_counter, out_len, out_flags = (
        cv,
        _words64(last),
        chunk,
        len(last),
        flags | (_CHUNK_START if blocks == 1 else 0) | _CHUNK_END,
    )
    while stack:
        left = stack.pop()
        right_cv = _compress(out_cv, out_block, out_counter, out_len, out_flags)[:8]
        out_cv, out_block, out_counter, out_len, out_flags = key, left + right_cv, 0, 64, flags | _PARENT
    root = _compress(out_cv, out_block, out_counter, out_len, out_flags | _ROOT)
    return struct.pack("<8I", *root[:8])


def blake3_hex(data: bytes) -> str:
    return _blake3_hash_with(data, _IV, 0).hex()


def blake3_derive_key_hex(context: str, data: bytes) -> str:
    ctx_bytes = _blake3_hash_with(context.encode("utf-8"), _IV, _DERIVE_KEY_CONTEXT)
    ctx_words = list(struct.unpack("<8I", ctx_bytes))
    return _blake3_hash_with(data, ctx_words, _DERIVE_KEY_MATERIAL).hex()


# ── 2. Pure-Python RFC-8032 Ed25519 ──────────────────────────────────────────

_P = (1 << 255) - 19
_L = (1 << 252) + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_BY = 4 * pow(5, _P - 2, _P) % _P
_BX = _xrecover(_BY)
_B_EXT = (_BX, _BY, 1, (_BX * _BY) % _P)
_ID_EXT = (0, 1, 1, 0)


def _ed_add(p: tuple[int, int, int, int], q: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = p
    x2, y2, z2, t2 = q
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (2 * t1 * t2 * _D) % _P
    d = (2 * z1 * z2) % _P
    e = (b - a) % _P
    f = (d - c) % _P
    g = (d + c) % _P
    h = (b + a) % _P
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _ed_double(p: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, _ = p
    a = (x1 * x1) % _P
    b = (y1 * y1) % _P
    c = (2 * z1 * z1) % _P
    h = (a + b) % _P
    xy = (x1 + y1) % _P
    e = (h - xy * xy) % _P
    g = (a - b) % _P
    f = (c + g) % _P
    return ((e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P)


def _scalarmult(p: tuple[int, int, int, int], e: int) -> tuple[int, int, int, int]:
    res = _ID_EXT
    cur = p
    k = e
    while k > 0:
        if k & 1:
            res = _ed_add(res, cur)
        cur = _ed_double(cur)
        k >>= 1
    return res


def _encodepoint(p: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = p
    zi = pow(z, _P - 2, _P)
    xp = (x * zi) % _P
    yp = (y * zi) % _P
    val = yp | ((xp & 1) << 255)
    return val.to_bytes(32, "little")


def _decodepoint(s: bytes) -> tuple[int, int, int, int]:
    if len(s) != 32:
        raise ValueError("Invalid point length")
    val = int.from_bytes(s, "little")
    y = val & ((1 << 255) - 1)
    xsgn = (val >> 255) & 1
    if y >= _P:
        raise ValueError("Point y out of range")
    xx = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("Point not on curve")
    if x == 0 and xsgn == 1:
        raise ValueError("Invalid negative zero x")
    if (x & 1) != xsgn:
        x = _P - x
    return (x, y, 1, (x * y) % _P)


def ed25519_pubkey_pure(seed32: bytes) -> bytes:
    if len(seed32) != 32:
        raise ValueError("Ed25519 seed must be 32 bytes")
    h = hashlib.sha512(seed32).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return _encodepoint(_scalarmult(_B_EXT, a))


def ed25519_sign_pure(seed32: bytes, msg: bytes) -> bytes:
    h = hashlib.sha512(seed32).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    prefix = h[32:]
    pub = _encodepoint(_scalarmult(_B_EXT, a))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _L
    r_pt = _encodepoint(_scalarmult(_B_EXT, r))
    k = int.from_bytes(hashlib.sha512(r_pt + pub + msg).digest(), "little") % _L
    s = (r + k * a) % _L
    return r_pt + s.to_bytes(32, "little")


def ed25519_verify_pure(pubkey32: bytes, msg: bytes, sig64: bytes) -> bool:
    if len(pubkey32) != 32 or len(sig64) != 64:
        return False
    try:
        a_pt = _decodepoint(pubkey32)
        r_pt = _decodepoint(sig64[:32])
        s = int.from_bytes(sig64[32:], "little")
        if s >= _L:
            return False
        k = int.from_bytes(hashlib.sha512(sig64[:32] + pubkey32 + msg).digest(), "little") % _L
        lhs = _encodepoint(_scalarmult(_B_EXT, s))
        rhs = _encodepoint(_ed_add(r_pt, _scalarmult(a_pt, k)))
        return lhs == rhs
    except Exception:
        return False


def seal_signed_receipt(
    kit_id: str,
    payload: dict[str, Any],
    domain_context: str,
    seed32: bytes | None = None,
) -> dict[str, Any]:
    """Create an offline-verifiable BLAKE3 + Ed25519 receipt (`Signed Provenance · Self-Checked`)."""
    ephemeral_seed = seed32 if seed32 is not None else os.urandom(32)
    pubkey = ed25519_pubkey_pure(ephemeral_seed)
    body = {
        "schema": "openie.signed_provenance_receipt.v1",
        "provenance_tier": "Signed Provenance · Self-Checked",
        "self_attested_not_third_party_verified": True,
        "kit_id": kit_id,
        "domain_context": domain_context,
        "issued_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "payload": payload,
    }
    canonical_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
    body_blake3 = blake3_derive_key_hex(domain_context, canonical_bytes)
    msg_to_sign = f"{domain_context}:{body_blake3}".encode("ascii")
    sig = ed25519_sign_pure(ephemeral_seed, msg_to_sign)
    return {
        "body": body,
        "body_blake3": body_blake3,
        "ed25519_public_key_hex": pubkey.hex(),
        "ed25519_signature_hex": sig.hex(),
    }


def verify_signed_receipt(receipt: dict[str, Any]) -> bool:
    try:
        body = receipt["body"]
        domain_context = str(body["domain_context"])
        pub = bytes.fromhex(receipt["ed25519_public_key_hex"])
        sig = bytes.fromhex(receipt["ed25519_signature_hex"])
        for ensure_asc in (True, False):
            canonical_bytes = json.dumps(
                body, sort_keys=True, separators=(",", ":"), ensure_ascii=ensure_asc
            ).encode("utf-8")
            expected_b3 = blake3_derive_key_hex(domain_context, canonical_bytes)
            if expected_b3 == receipt.get("body_blake3"):
                msg_v2 = f"{domain_context}:{expected_b3}".encode("ascii")
                if ed25519_verify_pure(pub, msg_v2, sig) or ed25519_verify_pure(pub, canonical_bytes, sig):
                    return True
        return False
    except Exception:
        return False


# ── 3. Statistics: IQR & Exact Clopper-Pearson Bounds ────────────────────────

def _percentile(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return sorted_vals[0]
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_vals[lo]
    frac = pos - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def iqr_stats(vals: list[float], ndigits: int = 4) -> dict[str, float]:
    if not vals:
        return {"n": 0, "median": 0.0, "p25": 0.0, "p75": 0.0, "iqr": 0.0, "min": 0.0, "max": 0.0}
    s = sorted(float(v) for v in vals)
    p25 = _percentile(s, 0.25)
    med = _percentile(s, 0.50)
    p75 = _percentile(s, 0.75)
    return {
        "n": len(s),
        "median": round(med, ndigits),
        "p25": round(p25, ndigits),
        "p75": round(p75, ndigits),
        "iqr": round(p75 - p25, ndigits),
        "min": round(s[0], ndigits),
        "max": round(s[-1], ndigits),
    }


def trimmed_mean(vals: list[float], trim_frac: float = 0.10) -> float:
    if not vals:
        return 0.0
    s = sorted(float(v) for v in vals)
    k = int(len(s) * trim_frac)
    core = s[k : len(s) - k] if len(s) > 2 * k else s
    return float(sum(core) / len(core))


def _binom_cdf_le(k: int, n: int, p: float) -> float:
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    log_p = math.log(p)
    log_q = math.log1p(-p)
    lg_n1 = math.lgamma(n + 1)
    total = 0.0
    for j in range(0, k + 1):
        log_pmf = lg_n1 - math.lgamma(j + 1) - math.lgamma(n - j + 1) + j * log_p + (n - j) * log_q
        total += math.exp(log_pmf)
    return min(1.0, max(0.0, total))


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05, two_sided: bool = False) -> float:
    """Exact Clopper-Pearson upper confidence bound for k disagreements in n trials."""
    if n <= 0 or k >= n:
        return 1.0
    tail = (alpha / 2.0) if two_sided else alpha
    if k == 0:
        return 1.0 - (tail ** (1.0 / n))
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = 0.5 * (lo + hi)
        if _binom_cdf_le(k, n, mid) > tail:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ── 4. Physical DC Shunt (`measured_j`) & Linux RAPL (`reported_j`) Meter ────

def _pread_int(fd: int, fallback_path: Path) -> int:
    try:
        return int(os.pread(fd, 32, 0).strip())
    except OSError:
        return int(fallback_path.read_text(encoding="ascii").strip())


class ShuntRailBackend:
    """Dynamic rootless Linux hwmon current-shunt reader (`ina3221` / `ina260*` / `ina238`)."""

    def __init__(
        self,
        substrate_id: str,
        primary_sensor: str,
        primary_rail: str,
        primary_mode: str,  # "mv_ma" or "uw"
        pri_paths: tuple[Path, ...],
        secondary_sensor: str | None = None,
        secondary_rail: str | None = None,
        sec_power_path: Path | None = None,
        sibling_rails: list[tuple[str, str, Path, Path]] | None = None,
        vi_aux_paths: tuple[Path, Path] | None = None,
    ) -> None:
        self.substrate_id = substrate_id
        self.primary_sensor = primary_sensor
        self.primary_rail = primary_rail
        self.primary_mode = primary_mode
        self.pri_paths = pri_paths
        self.secondary_sensor = secondary_sensor
        self.secondary_rail = secondary_rail
        self.sec_power_path = sec_power_path
        self.sibling_rails = sibling_rails or []
        self.vi_aux_paths = vi_aux_paths
        self._pri_fds = [os.open(str(p), os.O_RDONLY) for p in pri_paths]
        self._sec_fd = os.open(str(sec_power_path), os.O_RDONLY) if sec_power_path else None

    def close(self) -> None:
        for fd in self._pri_fds:
            try:
                os.close(fd)
            except OSError:
                pass
        self._pri_fds.clear()
        if self._sec_fd is not None:
            try:
                os.close(self._sec_fd)
            except OSError:
                pass
            self._sec_fd = None

    def sample_now(self) -> tuple[int, float, float | None]:
        t_ns = time.perf_counter_ns()
        if self.primary_mode == "mv_ma":
            mv = _pread_int(self._pri_fds[0], self.pri_paths[0])
            ma = _pread_int(self._pri_fds[1], self.pri_paths[1])
            pri_w = (mv * ma) * 1e-6
        else:
            uw = _pread_int(self._pri_fds[0], self.pri_paths[0])
            pri_w = uw * 1e-6
        sec_w = None
        if self._sec_fd is not None and self.sec_power_path is not None:
            sec_w = _pread_int(self._sec_fd, self.sec_power_path) * 1e-6
        return (t_ns, pri_w, sec_w)

    def snapshot_rail_breakdown_w(self) -> dict[str, Any]:
        _, pri_w, sec_w = self.sample_now()
        out: dict[str, Any] = {self.primary_rail: round(pri_w, 4)}
        if self.secondary_rail and sec_w is not None:
            out[self.secondary_rail] = round(sec_w, 4)
        for chip, label, v_p, c_p in self.sibling_rails:
            try:
                mv = int(v_p.read_text().strip())
                ma = int(c_p.read_text().strip())
                out[label] = round((mv * ma) * 1e-6, 4)
            except Exception:
                continue
        if self.vi_aux_paths is not None:
            try:
                out["bus_mv"] = int(self.vi_aux_paths[0].read_text().strip())
                out["shunt_ma"] = int(self.vi_aux_paths[1].read_text().strip())
            except Exception:
                pass
        return out


class ShuntWindowSession:
    """Continuous ~150-230 Hz background sysfs shunt sampler with trapezoidal integration."""

    def __init__(self, backend: ShuntRailBackend, poll_interval_s: float = 0.004) -> None:
        self.backend = backend
        self.poll_interval_s = poll_interval_s
        self.samples: list[tuple[int, float, float | None]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self.samples.append(self.backend.sample_now())
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        wait_fn = self._stop.wait
        interval = self.poll_interval_s
        sample_fn = self.backend.sample_now
        append_fn = self.samples.append
        while not wait_fn(interval):
            try:
                append_fn(sample_fn())
            except Exception:
                continue

    def stop_and_integrate(self) -> dict[str, Any]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=0.25)
        self.samples.append(self.backend.sample_now())
        pts = sorted(self.samples, key=lambda item: item[0])
        if len(pts) < 2:
            return {
                "primary_measured_j": 0.0,
                "secondary_measured_j": None,
                "shunt_samples": len(pts),
                "sample_rate_hz": 0.0,
                "mean_primary_w": 0.0,
                "trimmed_mean_primary_w": 0.0,
                "mean_secondary_w": None,
                "trimmed_mean_secondary_w": None,
            }
        pri_j = 0.0
        sec_j = 0.0
        has_sec = all(p[2] is not None for p in pts)
        for i in range(1, len(pts)):
            dt_s = max(0.0, (pts[i][0] - pts[i - 1][0]) * 1e-9)
            pri_j += 0.5 * (pts[i - 1][1] + pts[i][1]) * dt_s
            if has_sec:
                sec_j += 0.5 * (float(pts[i - 1][2]) + float(pts[i][2])) * dt_s  # type: ignore[arg-type]
        tot_s = max(1e-9, (pts[-1][0] - pts[0][0]) * 1e-9)
        pri_vals = [p[1] for p in pts]
        sec_vals = [float(p[2]) for p in pts if p[2] is not None]
        return {
            "primary_measured_j": pri_j,
            "secondary_measured_j": sec_j if has_sec else None,
            "shunt_samples": len(pts),
            "sample_rate_hz": round((len(pts) - 1) / tot_s, 1),
            "mean_primary_w": round(pri_j / tot_s, 4),
            "trimmed_mean_primary_w": round(trimmed_mean(pri_vals, 0.10), 4),
            "mean_secondary_w": round(sec_j / tot_s, 4) if has_sec else None,
            "trimmed_mean_secondary_w": round(trimmed_mean(sec_vals, 0.10), 4) if has_sec else None,
        }


def _discover_shunt_backend() -> ShuntRailBackend | None:
    hw_root = Path("/sys/class/hwmon")
    if platform.system() != "Linux" or not hw_root.is_dir():
        return None

    ina3221_dir: Path | None = None
    ina238_dir: Path | None = None
    ina260_dir: Path | None = None
    ina260_name = "ina260"

    for hw in sorted(hw_root.glob("hwmon*")):
        n_file = hw / "name"
        if not (n_file.is_file() and os.access(n_file, os.R_OK)):
            continue
        try:
            nm = n_file.read_text().strip()
        except Exception:
            continue
        if nm == "ina3221":
            ina3221_dir = hw
        elif nm == "ina238":
            ina238_dir = hw
        elif nm.startswith("ina260"):
            ina260_dir = hw
            ina260_name = nm

    # 1. Tegra INA3221 (`VDD_CPU_SOC_MSS`) + optional INA238 (`VIN`)
    if ina3221_dir is not None:
        pri_pair: tuple[Path, Path] | None = None
        siblings: list[tuple[str, str, Path, Path]] = []
        for lbl_file in sorted(ina3221_dir.glob("in*_label")):
            if not os.access(lbl_file, os.R_OK):
                continue
            try:
                lbl = lbl_file.read_text().strip()
            except Exception:
                continue
            m = re.match(r"^in(\d+)_label$", lbl_file.name)
            if not m:
                continue
            idx = m.group(1)
            v_p = ina3221_dir / f"in{idx}_input"
            c_p = ina3221_dir / f"curr{idx}_input"
            if not (v_p.is_file() and c_p.is_file() and os.access(v_p, os.R_OK) and os.access(c_p, os.R_OK)):
                continue
            if lbl == "VDD_CPU_SOC_MSS":
                pri_pair = (v_p, c_p)
            elif lbl in ("VDD_GPU", "VIN_SYS_5V0"):
                siblings.append(("ina3221", lbl, v_p, c_p))
        if pri_pair is not None:
            sec_p: Path | None = None
            if ina238_dir is not None:
                cand = ina238_dir / "power1_input"
                if cand.is_file() and os.access(cand, os.R_OK):
                    sec_p = cand
            try:
                backend = ShuntRailBackend(
                    substrate_id="jetson_agx_thor_ina3221",
                    primary_sensor="TI INA3221",
                    primary_rail="VDD_CPU_SOC_MSS",
                    primary_mode="mv_ma",
                    pri_paths=pri_pair,
                    secondary_sensor="TI INA238" if sec_p else None,
                    secondary_rail="VIN_CARRIER" if sec_p else None,
                    sec_power_path=sec_p,
                    sibling_rails=siblings,
                )
                _ = backend.sample_now()
                return backend
            except Exception:
                pass

    # 2. AMD Kria KV260 INA260 (`ina260_u14` SOM 5V DC rail)
    if ina260_dir is not None:
        p_path = ina260_dir / "power1_input"
        v_path = ina260_dir / "in1_input"
        c_path = ina260_dir / "curr1_input"
        if p_path.is_file() and os.access(p_path, os.R_OK):
            vi_aux = (v_path, c_path) if (v_path.is_file() and c_path.is_file()) else None
            try:
                backend = ShuntRailBackend(
                    substrate_id="amd_kria_kv260_ina260",
                    primary_sensor=f"TI INA260 ({ina260_name})",
                    primary_rail="SOM_5V_DC",
                    primary_mode="uw",
                    pri_paths=(p_path,),
                    vi_aux_paths=vi_aux,
                )
                _ = backend.sample_now()
                return backend
            except Exception:
                pass

    # 3. Standalone INA238 fallback
    if ina238_dir is not None:
        p_path = ina238_dir / "power1_input"
        if p_path.is_file() and os.access(p_path, os.R_OK):
            try:
                backend = ShuntRailBackend(
                    substrate_id="board_ina238",
                    primary_sensor="TI INA238",
                    primary_rail="VIN",
                    primary_mode="uw",
                    pri_paths=(p_path,),
                )
                _ = backend.sample_now()
                return backend
            except Exception:
                pass

    return None


class RaplDomain:
    def __init__(self, label: str, energy_path: Path, max_range_path: Path | None):
        self.label = label
        self.energy_path = energy_path
        self.max_range_uj: int | None = None
        if max_range_path and max_range_path.is_file() and os.access(max_range_path, os.R_OK):
            try:
                self.max_range_uj = int(max_range_path.read_text().strip())
            except Exception:
                self.max_range_uj = None

    def read_uj(self) -> int:
        return int(self.energy_path.read_text().strip())

    def delta_uj(self, start_uj: int, end_uj: int) -> int:
        if end_uj >= start_uj:
            return end_uj - start_uj
        if self.max_range_uj and self.max_range_uj > start_uj:
            return (self.max_range_uj - start_uj) + end_uj
        return 0


class EnergyMeter:
    """Priority-ordered hardware meter:
      1. Physical TI current-shunt sysfs (`ina3221` / `ina260*` / `ina238`) -> `measured_j` (`board_metered=True`)
      2. Rootless Linux `powercap/*rapl*` -> `reported_j` (`board_metered=False`)
      3. Fallback -> `unmetered` (`board_metered=False`)
    Never mixes `measured_j`, `reported_j`, `est_j`, and `unmetered`.
    """

    def __init__(self, poll_interval_s: float = 0.004) -> None:
        self.poll_interval_s = poll_interval_s
        self.shunt: ShuntRailBackend | None = _discover_shunt_backend()
        self.pkg_domain: RaplDomain | None = None
        self.core_domain: RaplDomain | None = None
        if self.shunt is None:
            self._discover_rapl()

    def _discover_rapl(self) -> None:
        base = Path("/sys/class/powercap")
        if not base.is_dir():
            return
        for p_name in ("intel-rapl:0", "intel-rapl:0:0"):
            d = base / p_name
            e_path = d / "energy_uj"
            n_path = d / "name"
            m_path = d / "max_energy_range_uj"
            if e_path.is_file() and os.access(e_path, os.R_OK):
                try:
                    _ = int(e_path.read_text().strip())
                    label = n_path.read_text().strip() if (n_path.is_file() and os.access(n_path, os.R_OK)) else p_name
                    dom = RaplDomain(label, e_path, m_path)
                    if p_name == "intel-rapl:0":
                        self.pkg_domain = dom
                    elif p_name == "intel-rapl:0:0":
                        self.core_domain = dom
                except Exception:
                    continue
        if self.pkg_domain is None:
            for entry in sorted(base.iterdir()):
                if "rapl" not in entry.name:
                    continue
                e_path = entry / "energy_uj"
                n_path = entry / "name"
                m_path = entry / "max_energy_range_uj"
                if e_path.is_file() and os.access(e_path, os.R_OK):
                    try:
                        _ = int(e_path.read_text().strip())
                        label = n_path.read_text().strip() if (n_path.is_file() and os.access(n_path, os.R_OK)) else entry.name
                        self.pkg_domain = RaplDomain(label, e_path, m_path)
                        break
                    except Exception:
                        continue

    @property
    def board_metered(self) -> bool:
        return self.shunt is not None

    @property
    def available(self) -> bool:
        return (self.shunt is not None) or (self.pkg_domain is not None)

    @property
    def evidence_class(self) -> str:
        if self.shunt is not None:
            return "measured_j"
        if self.pkg_domain is not None:
            return "reported_j"
        return "unmetered"

    @property
    def substrate_id(self) -> str:
        if self.shunt is not None:
            return self.shunt.substrate_id
        if self.pkg_domain is not None:
            return "x86_rapl"
        return "unmetered_host"

    def close(self) -> None:
        if self.shunt is not None:
            self.shunt.close()

    def sample_idle_baseline(self, window_s: float | None = None) -> dict[str, Any] | None:
        if self.shunt is not None:
            dur = window_s if window_s is not None else 1.0
            sess = ShuntWindowSession(self.shunt, self.poll_interval_s)
            sess.start()
            time.sleep(dur)
            integ = sess.stop_and_integrate()
            return {
                "window_s": dur,
                "raw_mean_w": integ["mean_primary_w"],
                "trimmed_mean_w": integ["trimmed_mean_primary_w"],
                "secondary_raw_mean_w": integ["mean_secondary_w"],
                "secondary_trimmed_mean_w": integ["trimmed_mean_secondary_w"],
                "shunt_samples": integ["shunt_samples"],
                "sample_rate_hz": integ["sample_rate_hz"],
                "rail_breakdown_w": self.shunt.snapshot_rail_breakdown_w(),
            }
        if self.pkg_domain is not None:
            dur = window_s if window_s is not None else 0.15
            try:
                e0 = self.pkg_domain.read_uj()
                t0 = time.perf_counter_ns()
                time.sleep(dur)
                e1 = self.pkg_domain.read_uj()
                dt_s = (time.perf_counter_ns() - t0) * 1e-9
                pw = round((self.pkg_domain.delta_uj(e0, e1) / 1e6) / max(dt_s, 1e-9), 4)
                return {"window_s": dur, "raw_mean_w": pw, "trimmed_mean_w": pw}
            except Exception:
                return None
        return None

    def sample_idle_power_w(self, window_s: float = 0.25) -> float | None:
        b = self.sample_idle_baseline(window_s)
        return float(b["trimmed_mean_w"]) if b is not None else None

    def calibrate_reps(
        self,
        probe_one_rep_fn: Callable[[], Any],
        default_reps: int,
        quick_reps: int,
        quick: bool = False,
        target_shunt_s: float = 0.78,
    ) -> int:
        if not self.board_metered:
            return quick_reps if quick else default_reps
        target_s = 0.14 if quick else target_shunt_s
        t0 = time.perf_counter_ns()
        probe_one_rep_fn()
        dt_s = max(1e-7, (time.perf_counter_ns() - t0) * 1e-9)
        if dt_s >= target_s:
            return 1
        reps = int(math.ceil(target_s / dt_s))
        return max(1, min(reps, 25000))

    def snapshot(self) -> dict[str, Any]:
        ru_s = resource.getrusage(resource.RUSAGE_SELF)
        ru_c = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_s = ru_s.ru_utime + ru_s.ru_stime + ru_c.ru_utime + ru_c.ru_stime
        shunt_sess: ShuntWindowSession | None = None
        if self.shunt is not None:
            shunt_sess = ShuntWindowSession(self.shunt, self.poll_interval_s)
            shunt_sess.start()
        return {
            "wall_ns": time.perf_counter_ns(),
            "cpu_s": cpu_s,
            "shunt_sess": shunt_sess,
            "pkg_uj": self.pkg_domain.read_uj() if (self.shunt is None and self.pkg_domain) else None,
            "core_uj": self.core_domain.read_uj() if (self.shunt is None and self.core_domain) else None,
        }

    def diff(self, s0: dict[str, Any], s1: dict[str, Any] | None = None) -> dict[str, Any]:
        wall_end = s1["wall_ns"] if s1 is not None else time.perf_counter_ns()
        if s1 is not None:
            cpu_end = s1["cpu_s"]
            if s1.get("shunt_sess") is not None:
                s1["shunt_sess"].stop_and_integrate()
        else:
            ru_s = resource.getrusage(resource.RUSAGE_SELF)
            ru_c = resource.getrusage(resource.RUSAGE_CHILDREN)
            cpu_end = ru_s.ru_utime + ru_s.ru_stime + ru_c.ru_utime + ru_c.ru_stime

        wall_ns = max(1, int(wall_end - s0["wall_ns"]))
        wall_s = wall_ns * 1e-9
        cpu_ms = max(0.0, float(cpu_end - s0["cpu_s"])) * 1e3

        if s0.get("shunt_sess") is not None:
            integ = s0["shunt_sess"].stop_and_integrate()
            return {
                "wall_ns": wall_ns,
                "wall_s": round(wall_s, 6),
                "wall_ms": round(wall_ns / 1e6, 4),
                "cpu_user_sys_ms": round(cpu_ms, 4),
                "evidence_class": "measured_j",
                "board_metered": True,
                "primary_measured_j": round(integ["primary_measured_j"], 6),
                "secondary_measured_j": (
                    round(integ["secondary_measured_j"], 6) if integ["secondary_measured_j"] is not None else None
                ),
                "shunt_samples": integ["shunt_samples"],
                "sample_rate_hz": integ["sample_rate_hz"],
                "mean_primary_w": integ["mean_primary_w"],
                "mean_secondary_w": integ["mean_secondary_w"],
                "pkg_reported_j": None,
                "core_reported_j": None,
            }

        pkg_j = (
            self.pkg_domain.delta_uj(s0["pkg_uj"], s1["pkg_uj"]) / 1e6
            if (s1 is not None and self.pkg_domain and s0["pkg_uj"] is not None and s1["pkg_uj"] is not None)
            else None
        )
        core_j = (
            self.core_domain.delta_uj(s0["core_uj"], s1["core_uj"]) / 1e6
            if (s1 is not None and self.core_domain and s0["core_uj"] is not None and s1["core_uj"] is not None)
            else None
        )
        return {
            "wall_ns": wall_ns,
            "wall_s": round(wall_s, 6),
            "wall_ms": round(wall_ns / 1e6, 4),
            "cpu_user_sys_ms": round(cpu_ms, 4),
            "evidence_class": "reported_j" if pkg_j is not None else "unmetered",
            "board_metered": False,
            "primary_measured_j": None,
            "secondary_measured_j": None,
            "shunt_samples": 0,
            "sample_rate_hz": 0.0,
            "pkg_reported_j": round(pkg_j, 6) if pkg_j is not None else None,
            "core_reported_j": round(core_j, 6) if core_j is not None else None,
        }

    def metadata(
        self,
        idle_pre: dict[str, Any] | None = None,
        idle_post: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.shunt is not None:
            meta: dict[str, Any] = {
                "evidence_class": "measured_j",
                "board_metered": True,
                "substrate_id": self.shunt.substrate_id,
                "primary_sensor": self.shunt.primary_sensor,
                "primary_rail": self.shunt.primary_rail,
                "primary_sysfs_paths": [str(p) for p in self.shunt.pri_paths],
                "secondary_sensor": self.shunt.secondary_sensor,
                "secondary_rail": self.shunt.secondary_rail,
                "secondary_sysfs_path": str(self.shunt.sec_power_path) if self.shunt.sec_power_path else None,
                "reported_j_available": False,
                "est_j_mixed": False,
            }
            if idle_pre is not None and idle_post is not None:
                w1 = float(idle_pre["trimmed_mean_w"])
                w2 = float(idle_post["trimmed_mean_w"])
                mean_idle = 0.5 * (w1 + w2)
                drift_pct = round(100.0 * abs(w2 - w1) / max(mean_idle, 1e-9), 2)
                meta["idle_a1_pre"] = idle_pre
                meta["idle_a2_post"] = idle_post
                meta["idle_trimmed_mean_w"] = round(mean_idle, 4)
                meta["idle_drift_pct"] = drift_pct
                meta["falsifier_6_idle_drift_threshold_pct"] = 5.0
                meta["falsifier_6_idle_drift_flag"] = bool(drift_pct > 5.0)
            return meta

        if self.pkg_domain is not None:
            meta = {
                "evidence_class": "reported_j",
                "board_metered": False,
                "substrate_id": "x86_rapl",
                "measured_j": None,
                "reported_j_available": True,
                "est_j_mixed": False,
                "package_counter": str(self.pkg_domain.energy_path),
                "package_domain": self.pkg_domain.label,
                "core_counter": str(self.core_domain.energy_path) if self.core_domain else None,
                "core_domain": self.core_domain.label if self.core_domain else None,
            }
            if idle_pre is not None and idle_post is not None:
                w1 = float(idle_pre["trimmed_mean_w"])
                w2 = float(idle_post["trimmed_mean_w"])
                mean_idle = 0.5 * (w1 + w2)
                meta["idle_pkg_w_pre"] = w1
                meta["idle_pkg_w_post"] = w2
                meta["idle_drift_pct"] = round(100.0 * abs(w2 - w1) / max(mean_idle, 1e-9), 2)
            return meta

        return {
            "evidence_class": "unmetered",
            "board_metered": False,
            "substrate_id": "unmetered_host",
            "measured_j": None,
            "reported_j_available": False,
            "est_j_mixed": False,
            "package_counter": None,
            "core_counter": None,
        }


def sanitized_host_info() -> dict[str, Any]:
    u = os.uname() if hasattr(os, "uname") else None
    os_kernel = (
        f"{u.sysname} {u.release} {u.machine}"
        if u is not None
        else f"{platform.system()} {platform.release()} {platform.machine()}"
    )
    cpu_model = ""
    dt_model = ""
    if platform.system() == "Linux":
        dt_path = Path("/proc/device-tree/model")
        if dt_path.is_file() and os.access(dt_path, os.R_OK):
            try:
                dt_model = dt_path.read_bytes().replace(b"\x00", b"").decode("utf-8", errors="ignore").strip()
            except Exception:
                dt_model = ""
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("model name") and ":" in line:
                    cand = line.split(":", 1)[1].strip()
                    if cand and cand != "-":
                        cpu_model = cand
                        break
        except OSError:
            pass
        if not cpu_model:
            try:
                lscpu_out = subprocess.check_output(["lscpu"], text=True, timeout=3)
                for line in lscpu_out.splitlines():
                    if line.startswith("Model name:"):
                        cand = line.split(":", 1)[1].strip()
                        if cand and cand != "-":
                            cpu_model = cand
                            break
            except Exception:
                pass
        if dt_model and cpu_model:
            cpu_model = f"{dt_model} ({cpu_model}, {platform.machine()})"
        elif dt_model:
            cpu_model = f"{dt_model} ({os.cpu_count() or 1}-core {platform.machine()})"
    elif platform.system() == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=3).strip()
            if out:
                cpu_model = out
        except Exception:
            pass

    if not cpu_model:
        cpu_model = platform.processor() or platform.machine()

    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    cc_ver = "not_installed"
    if cc_bin:
        try:
            raw = subprocess.check_output([cc_bin, "--version"], stderr=subprocess.STDOUT, text=True, timeout=5)
            first = raw.splitlines()[0].strip()
            # Strip vendor/distro parentheses (e.g. "(Ubuntu 13.3.0-...)") to avoid OS user substring leaks
            cleaned = re.sub(r"\s*\([^)]*\)", "", first)
            cleaned = re.sub(r"/(?:Users|home|tmp|var|opt|private)/[^\s)]+", "<path>", cleaned)
            m_ver = re.search(r"(clang|gcc|cc)[^\d]*(\d+\.\d+(?:\.\d+)?)", cleaned, flags=re.IGNORECASE)
            if m_ver:
                fam = "Clang" if "clang" in first.lower() else "GCC"
                cc_ver = f"{fam} {m_ver.group(2)}"
            else:
                cc_ver = cleaned.strip()
        except Exception:
            cc_ver = "unavailable"

    ram_gib = None
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            ram_gib = round((os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")) / (1024 ** 3), 2)
    except Exception:
        pass

    return {
        "cpu_model": cpu_model,
        "logical_cpus": os.cpu_count() or 1,
        "ram_gib": ram_gib,
        "os_kernel": os_kernel,
        "python_version": platform.python_version(),
        "cc_version": cc_ver,
        "recorded_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def assert_sanitized(text: str) -> None:
    """Fail closed on private IPs, home paths, hostnames, usernames, or banned terms."""
    patterns = [
        (r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b", "RFC6598 CGNAT IP"),
        (r"\b10(?:\.\d{1,3}){3}\b", "RFC1918 class-A private IP"),
        (r"\b192\.168(?:\.\d{1,3}){2}\b", "RFC1918 class-C private IP"),
        (r"\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b", "RFC1918 class-B private IP"),
        (r"/(?:Users|home)/[A-Za-z0-9._-]+", "local user home path"),
        (r"(?i)landauer\s+bit[- ]equivalents", "retired thermodynamic bit-ratio metric"),
    ]
    host = socket.gethostname().strip()
    if host and host.lower() not in ("localhost", "buildkitsandbox", "kria") and len(host) >= 4:
        patterns.append((re.escape(host), "local hostname"))
    try:
        user = getpass.getuser().strip()
        if user and user.lower() not in ("root", "nobody", "replicator", "runner") and len(user) >= 4:
            patterns.append((rf"\b{re.escape(user)}\b", "local OS username"))
    except Exception:
        pass
    for pat, label in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raise RuntimeError(f"Sanitization guard triggered ({label}): {m.group(0)!r}")
