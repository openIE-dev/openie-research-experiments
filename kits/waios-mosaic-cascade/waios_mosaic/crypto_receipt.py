# SPDX-License-Identifier: Apache-2.0
"""Standalone BLAKE3, RFC-8032 Ed25519 receipts, Linux RAPL `reported_j` metering, and sanitization.

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
import struct
import subprocess
import time
from pathlib import Path
from typing import Any

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


# ── 2. Pure-Python RFC-8032 Ed25519 (+ OpenSSL/cryptography cross-compat) ────

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
_B = (_BX, _BY, 1, (_BX * _BY) % _P)
_IDENT = (0, 1, 1, 0)


def _ed_add(p1: tuple[int, int, int, int], p2: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = p1
    x2, y2, z2, t2 = p2
    a = ((y1 - x1) * (y2 - x2)) % _P
    b = ((y1 + x1) * (y2 + x2)) % _P
    c = (t1 * 2 * _D * t2) % _P
    d = (z1 * 2 * z2) % _P
    e = (b - a) % _P
    f = (d - c) % _P
    g = (d + c) % _P
    h = (b + a) % _P
    return (e * f) % _P, (g * h) % _P, (f * g) % _P, (e * h) % _P


def _ed_mul(pt: tuple[int, int, int, int], scalar: int) -> tuple[int, int, int, int]:
    res = _IDENT
    cur = pt
    n = scalar
    while n > 0:
        if n & 1:
            res = _ed_add(res, cur)
        cur = _ed_add(cur, cur)
        n >>= 1
    return res


def _encode_point(pt: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = pt
    zi = pow(z, _P - 2, _P)
    xp = (x * zi) % _P
    yp = (y * zi) % _P
    out = bytearray(yp.to_bytes(32, "little"))
    out[31] |= (xp & 1) << 7
    return bytes(out)


def _decode_point(enc: bytes) -> tuple[int, int, int, int]:
    if len(enc) != 32:
        raise ValueError("Invalid Ed25519 point length")
    y = int.from_bytes(enc, "little") & ((1 << 255) - 1)
    if y >= _P:
        raise ValueError("Ed25519 y out of range")
    x_sign = (enc[31] >> 7) & 1
    u = (y * y - 1) % _P
    v = (_D * y * y + 1) % _P
    if v == 0:
        raise ValueError("Invalid Ed25519 point denominator")
    xx = (u * pow(v, _P - 2, _P)) % _P
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if (x * x - xx) % _P != 0:
        raise ValueError("Point not on Ed25519 curve")
    if x == 0 and x_sign == 1:
        raise ValueError("Invalid x=0 with sign=1")
    if (x & 1) != x_sign:
        x = _P - x
    return x, y, 1, (x * y) % _P


def ed25519_pubkey_pure(seed32: bytes) -> bytes:
    assert len(seed32) == 32
    h = hashlib.sha512(seed32).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return _encode_point(_ed_mul(_B, a))


def ed25519_sign_pure(seed32: bytes, msg: bytes) -> bytes:
    assert len(seed32) == 32
    h = hashlib.sha512(seed32).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    prefix = h[32:]
    pub = _encode_point(_ed_mul(_B, a))
    r = int.from_bytes(hashlib.sha512(prefix + msg).digest(), "little") % _L
    r_bytes = _encode_point(_ed_mul(_B, r))
    k = int.from_bytes(hashlib.sha512(r_bytes + pub + msg).digest(), "little") % _L
    s = (r + k * a) % _L
    return r_bytes + s.to_bytes(32, "little")


def ed25519_verify_pure(pubkey32: bytes, msg: bytes, sig64: bytes) -> bool:
    if len(pubkey32) != 32 or len(sig64) != 64:
        return False
    s = int.from_bytes(sig64[32:], "little")
    if s >= _L:
        return False
    try:
        a_pt = _decode_point(pubkey32)
        r_pt = _decode_point(sig64[:32])
    except ValueError:
        return False
    k = int.from_bytes(hashlib.sha512(sig64[:32] + pubkey32 + msg).digest(), "little") % _L
    lhs = _ed_mul(_B, s)
    neg_a = ((-a_pt[0]) % _P, a_pt[1], a_pt[2], (-a_pt[3]) % _P)
    # Verify [s]B == R + [k]A
    rhs = _ed_add(r_pt, _ed_mul(a_pt, k))
    return _encode_point(lhs) == _encode_point(rhs)


def canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def seal_signed_receipt(
    kit_id: str,
    payload: dict[str, Any],
    domain_context: str,
    key_seed_domain: str = "openie.self_checked.audit_key.v1",
) -> dict[str, Any]:
    """Create a deterministic BLAKE3 + Ed25519 self-checked provenance receipt."""
    seed32 = bytes.fromhex(blake3_derive_key_hex(key_seed_domain, kit_id.encode("utf-8")))
    body = {
        "schema": "openie.signed_provenance_receipt.v1",
        "kit_id": kit_id,
        "provenance_tier": "Signed Provenance · Self-Checked",
        "provenance_note": (
            "Self-checked cryptographic receipt: proves post-hoc integrity of the body under the "
            "embedded deterministic audit keypair; does not claim external third-party hardware attestation."
        ),
        "domain_context": domain_context,
        "payload": payload,
    }
    body_bytes = canonical_json_bytes(body)
    body_blake3 = blake3_derive_key_hex(domain_context, body_bytes)
    sig = ed25519_sign_pure(seed32, body_bytes)
    pub = ed25519_pubkey_pure(seed32)
    return {
        "body": body,
        "body_blake3": body_blake3,
        "ed25519_public_key_hex": pub.hex(),
        "ed25519_signature_hex": sig.hex(),
    }


def verify_signed_receipt(receipt: dict[str, Any]) -> bool:
    """Offline independent verification of both BLAKE3 body digest and Ed25519 signature."""
    try:
        body = receipt["body"]
        domain_context = body["domain_context"]
        body_bytes = canonical_json_bytes(body)
        if blake3_derive_key_hex(domain_context, body_bytes) != receipt["body_blake3"]:
            return False
        pub = bytes.fromhex(receipt["ed25519_public_key_hex"])
        sig = bytes.fromhex(receipt["ed25519_signature_hex"])
        return ed25519_verify_pure(pub, body_bytes, sig)
    except Exception:
        return False


# ── 3. Statistics, Linux RAPL Metering & Strict Sanitization ─────────────────


def percentile_sorted(sorted_vals: list[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = q * (len(sorted_vals) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    frac = pos - lo
    return float(sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac)


def iqr_stats(values: list[float], digits: int = 4) -> dict[str, Any]:
    if not values:
        return {"n": 0, "median": None, "p25": None, "p75": None, "iqr": None, "min": None, "max": None}
    s = sorted(float(v) for v in values)
    med = percentile_sorted(s, 0.50)
    p25 = percentile_sorted(s, 0.25)
    p75 = percentile_sorted(s, 0.75)
    return {
        "n": len(s),
        "median": round(med, digits),
        "p25": round(p25, digits),
        "p75": round(p75, digits),
        "iqr": round(p75 - p25, digits),
        "min": round(s[0], digits),
        "max": round(s[-1], digits),
    }


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
    """Rootless Linux powercap/RAPL meter (`reported_j`) with clean fallback to `unmetered`."""

    def __init__(self) -> None:
        self.pkg_domain: RaplDomain | None = None
        self.core_domain: RaplDomain | None = None
        self._discover()

    def _discover(self) -> None:
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
    def available(self) -> bool:
        return self.pkg_domain is not None

    @property
    def evidence_class(self) -> str:
        return "reported_j" if self.available else "unmetered"

    def sample_idle_power_w(self, window_s: float = 0.15) -> float | None:
        if not self.pkg_domain:
            return None
        try:
            e0 = self.pkg_domain.read_uj()
            t0 = time.perf_counter_ns()
            time.sleep(window_s)
            e1 = self.pkg_domain.read_uj()
            dt_s = (time.perf_counter_ns() - t0) / 1e9
            return round((self.pkg_domain.delta_uj(e0, e1) / 1e6) / dt_s, 4) if dt_s > 0 else None
        except Exception:
            return None

    def snapshot(self) -> dict[str, Any]:
        ru_s = resource.getrusage(resource.RUSAGE_SELF)
        ru_c = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_s = ru_s.ru_utime + ru_s.ru_stime + ru_c.ru_utime + ru_c.ru_stime
        return {
            "wall_ns": time.perf_counter_ns(),
            "cpu_s": cpu_s,
            "pkg_uj": self.pkg_domain.read_uj() if self.pkg_domain else None,
            "core_uj": self.core_domain.read_uj() if self.core_domain else None,
        }

    def diff(self, s0: dict[str, Any], s1: dict[str, Any]) -> dict[str, Any]:
        wall_ns = max(0, int(s1["wall_ns"] - s0["wall_ns"]))
        cpu_ms = max(0.0, float(s1["cpu_s"] - s0["cpu_s"])) * 1e3
        pkg_j = (
            self.pkg_domain.delta_uj(s0["pkg_uj"], s1["pkg_uj"]) / 1e6
            if (self.pkg_domain and s0["pkg_uj"] is not None and s1["pkg_uj"] is not None)
            else None
        )
        core_j = (
            self.core_domain.delta_uj(s0["core_uj"], s1["core_uj"]) / 1e6
            if (self.core_domain and s0["core_uj"] is not None and s1["core_uj"] is not None)
            else None
        )
        return {
            "wall_ns": wall_ns,
            "wall_ms": round(wall_ns / 1e6, 4),
            "cpu_user_sys_ms": round(cpu_ms, 4),
            "evidence_class": "reported_j" if pkg_j is not None else "unmetered",
            "pkg_reported_j": round(pkg_j, 6) if pkg_j is not None else None,
            "core_reported_j": round(core_j, 6) if core_j is not None else None,
        }

    def metadata(self) -> dict[str, Any]:
        if not self.available:
            return {
                "evidence_class": "unmetered",
                "measured_j": None,
                "reported_j_available": False,
                "est_j_mixed": False,
                "package_counter": None,
                "core_counter": None,
            }
        return {
            "evidence_class": "reported_j",
            "measured_j": None,
            "reported_j_available": True,
            "est_j_mixed": False,
            "package_counter": str(self.pkg_domain.energy_path) if self.pkg_domain else None,
            "package_domain": self.pkg_domain.label if self.pkg_domain else None,
            "core_counter": str(self.core_domain.energy_path) if self.core_domain else None,
            "core_domain": self.core_domain.label if self.core_domain else None,
        }


def sanitized_host_info() -> dict[str, Any]:
    u = os.uname() if hasattr(os, "uname") else None
    os_kernel = (
        f"{u.sysname} {u.release} {u.machine}"
        if u is not None
        else f"{platform.system()} {platform.release()} {platform.machine()}"
    )
    cpu_model = platform.processor() or platform.machine()
    if platform.system() == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("model name") and ":" in line:
                    cpu_model = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
    elif platform.system() == "Darwin":
        try:
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True, timeout=3).strip()
            if out:
                cpu_model = out
        except Exception:
            pass

    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    cc_ver = "not_installed"
    if cc_bin:
        try:
            raw = subprocess.check_output([cc_bin, "--version"], stderr=subprocess.STDOUT, text=True, timeout=5)
            cc_ver = re.sub(r"/(?:Users|home|tmp|var|opt|private)/[^\s)]+", "<path>", raw.splitlines()[0].strip())
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
        (r"/(?:Users|home)/[A-Za-z0-9._-]+", "local user home path"),
        (r"(?i)landauer\s+bit[- ]equivalents", "retired thermodynamic bit-ratio metric"),
    ]
    host = socket.gethostname().strip()
    if host and host.lower() not in ("localhost", "buildkitsandbox") and len(host) >= 4:
        patterns.append((re.escape(host), "local hostname"))
    try:
        user = getpass.getuser().strip()
        if user and user.lower() not in ("root", "nobody", "replicator", "ubuntu", "runner") and len(user) >= 4:
            patterns.append((re.escape(user), "local OS username"))
    except Exception:
        pass
    for pat, label in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raise RuntimeError(f"Sanitization guard triggered ({label}): {m.group(0)!r}")
