# SPDX-License-Identifier: Apache-2.0
"""Sanitized host fingerprinting, orthogonal 4-class energy metering, and exact statistics.

Energy taxonomy (strictly orthogonal; never summed or converted across classes):
  - measured_j  : External physical inline shunt or wall power meter on a named rail.
  - reported_j  : OS or on-chip hardware energy counter (e.g., Linux powercap/RAPL).
  - est_j       : Analytical model estimate (never produced by this live harness).
  - unmetered   : Timing-only run when no hardware counter is readable without root.
"""

from __future__ import annotations

import getpass
import math
import os
import platform
import re
import resource
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any


def percentile_sorted(sorted_vals: list[float], q: float) -> float:
    """Linear-interpolated percentile (q in [0.0, 1.0]) over pre-sorted values."""
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
    """Return median, p25, p75, IQR, min, max, and sample count N."""
    if not values:
        return {
            "n": 0,
            "median": None,
            "p25": None,
            "p75": None,
            "iqr": None,
            "min": None,
            "max": None,
        }
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
    """Exact binomial CDF P(X <= k) for X ~ Binomial(n, p) using log-gamma."""
    if p <= 0.0:
        return 1.0
    if p >= 1.0:
        return 1.0 if k >= n else 0.0
    log_p = math.log(p)
    log_q = math.log1p(-p)
    lg_n1 = math.lgamma(n + 1)
    total = 0.0
    for j in range(0, k + 1):
        log_pmf = (
            lg_n1
            - math.lgamma(j + 1)
            - math.lgamma(n - j + 1)
            + j * log_p
            + (n - j) * log_q
        )
        total += math.exp(log_pmf)
    return min(1.0, max(0.0, total))


def clopper_pearson_upper(k: int, n: int, alpha: float = 0.05, two_sided: bool = False) -> float:
    """Exact Clopper-Pearson upper confidence bound for k events in n Bernoulli trials."""
    if n <= 0:
        return 1.0
    if k >= n:
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


def _scrub_version_line(raw: str) -> str:
    """Strip any filesystem paths, usernames, or hostnames from a compiler version line."""
    line = raw.strip().splitlines()[0] if raw.strip() else "unavailable"
    line = re.sub(r"/(?:Users|home|tmp|var|opt|private)/[^\s)]+", "<path>", line)
    user = os.environ.get("USER") or os.environ.get("USERNAME") or ""
    if user and len(user) >= 3:
        line = re.sub(re.escape(user), "<user>", line, flags=re.IGNORECASE)
    host = socket.gethostname()
    if host and len(host) >= 3:
        line = re.sub(re.escape(host), "<host>", line, flags=re.IGNORECASE)
    return line


def _detect_cpu_model() -> str:
    sysname = platform.system()
    if sysname == "Linux":
        try:
            for line in Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="ignore").splitlines():
                if line.lower().startswith("model name") and ":" in line:
                    return line.split(":", 1)[1].strip()
                if line.lower().startswith("hardware") and ":" in line:
                    return line.split(":", 1)[1].strip()
        except OSError:
            pass
    elif sysname == "Darwin":
        try:
            out = subprocess.check_output(
                ["sysctl", "-n", "machdep.cpu.brand_string"],
                stderr=subprocess.DEVNULL,
                text=True,
                timeout=3,
            ).strip()
            if out:
                return out
        except Exception:
            pass
    proc = platform.processor().strip()
    return proc if proc else platform.machine()


def _detect_ram_gib() -> float | None:
    try:
        if hasattr(os, "sysconf") and "SC_PAGE_SIZE" in os.sysconf_names and "SC_PHYS_PAGES" in os.sysconf_names:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_sz = os.sysconf("SC_PAGE_SIZE")
            if pages > 0 and page_sz > 0:
                return round((pages * page_sz) / (1024 ** 3), 2)
    except Exception:
        pass
    return None


def collect_sanitized_host_info(skip_native: bool = False) -> dict[str, Any]:
    """Collect hardware & toolchain metadata without hostname, username, or local paths."""
    u = os.uname() if hasattr(os, "uname") else None
    os_kernel = (
        f"{u.sysname} {u.release} {u.machine}"
        if u is not None
        else f"{platform.system()} {platform.release()} {platform.machine()}"
    )

    rustc_bin = None if skip_native else shutil.which("rustc")
    cargo_bin = None if skip_native else shutil.which("cargo")
    cc_bin = None if skip_native else (shutil.which("cc") or shutil.which("gcc") or shutil.which("clang"))

    def _ver(cmd: list[str]) -> str:
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True, timeout=5)
            return _scrub_version_line(out)
        except Exception:
            return "unavailable"

    return {
        "cpu_model": _detect_cpu_model(),
        "logical_cpus": os.cpu_count() or 1,
        "ram_gib": _detect_ram_gib(),
        "os_kernel": os_kernel,
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "rustc_version": _ver([rustc_bin, "--version"]) if rustc_bin else "not_installed",
        "cargo_version": _ver([cargo_bin, "--version"]) if cargo_bin else "not_installed",
        "cc_version": _ver([cc_bin, "--version"]) if cc_bin else "not_installed",
        "native_toolchains_enabled": not skip_native,
    }


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
    """Non-root Linux powercap/RAPL reader with clean fallback to `unmetered`."""

    def __init__(self) -> None:
        self.pkg_domain: RaplDomain | None = None
        self.core_domain: RaplDomain | None = None
        self._discover_linux_rapl()

    def _discover_linux_rapl(self) -> None:
        base = Path("/sys/class/powercap")
        if not base.is_dir():
            return
        candidates: list[tuple[str, Path, Path | None]] = []
        for entry in sorted(base.iterdir()):
            if "rapl" not in entry.name:
                continue
            e_path = entry / "energy_uj"
            n_path = entry / "name"
            m_path = entry / "max_energy_range_uj"
            if not (e_path.is_file() and os.access(e_path, os.R_OK)):
                continue
            try:
                _ = int(e_path.read_text().strip())
                dom_name = n_path.read_text().strip() if (n_path.is_file() and os.access(n_path, os.R_OK)) else entry.name
                candidates.append((dom_name, e_path, m_path))
            except Exception:
                continue

        for dom_name, e_path, m_path in candidates:
            low = dom_name.lower()
            if self.pkg_domain is None and (low.startswith("package") or e_path.parent.name == "intel-rapl:0"):
                self.pkg_domain = RaplDomain(dom_name, e_path, m_path)
            elif self.core_domain is None and ("core" in low or e_path.parent.name == "intel-rapl:0:0"):
                self.core_domain = RaplDomain(dom_name, e_path, m_path)

        if self.pkg_domain is None and candidates:
            dom_name, e_path, m_path = candidates[0]
            self.pkg_domain = RaplDomain(dom_name, e_path, m_path)

    @property
    def available(self) -> bool:
        return self.pkg_domain is not None

    @property
    def evidence_class(self) -> str:
        return "reported_j" if self.available else "unmetered"

    def metadata(self) -> dict[str, Any]:
        if not self.available:
            return {
                "evidence_class": "unmetered",
                "measured_j": None,
                "reported_j_available": False,
                "est_j": None,
                "counter_source": None,
                "note": "No unprivileged hardware energy counter readable; reporting exact wall-clock ns, CPU time, and byte counts only.",
            }
        return {
            "evidence_class": "reported_j",
            "measured_j": None,
            "reported_j_available": True,
            "est_j": None,
            "package_counter": str(self.pkg_domain.energy_path) if self.pkg_domain else None,
            "package_domain_name": self.pkg_domain.label if self.pkg_domain else None,
            "core_counter": str(self.core_domain.energy_path) if self.core_domain else None,
            "core_domain_name": self.core_domain.label if self.core_domain else None,
            "note": "On-chip hardware counter via Linux powercap/RAPL (reported_j; never mixed with wall-shunt measured_j or analytical est_j).",
        }

    def sample_idle_power(self, window_s: float = 0.15) -> float | None:
        if not self.pkg_domain:
            return None
        try:
            e0 = self.pkg_domain.read_uj()
            t0 = time.perf_counter_ns()
            time.sleep(window_s)
            e1 = self.pkg_domain.read_uj()
            dt_s = (time.perf_counter_ns() - t0) / 1e9
            if dt_s <= 0:
                return None
            return round((self.pkg_domain.delta_uj(e0, e1) / 1e6) / dt_s, 4)
        except Exception:
            return None

    def snapshot(self) -> dict[str, Any]:
        ru_self = resource.getrusage(resource.RUSAGE_SELF)
        ru_child = resource.getrusage(resource.RUSAGE_CHILDREN)
        cpu_s = (
            ru_self.ru_utime
            + ru_self.ru_stime
            + ru_child.ru_utime
            + ru_child.ru_stime
        )
        pkg_uj = None
        core_uj = None
        if self.pkg_domain is not None:
            try:
                pkg_uj = self.pkg_domain.read_uj()
            except Exception:
                pkg_uj = None
        if self.core_domain is not None:
            try:
                core_uj = self.core_domain.read_uj()
            except Exception:
                core_uj = None
        return {
            "wall_ns": time.perf_counter_ns(),
            "cpu_s": cpu_s,
            "pkg_uj": pkg_uj,
            "core_uj": core_uj,
        }

    def diff(self, start: dict[str, Any], end: dict[str, Any]) -> dict[str, Any]:
        wall_ns = max(0, int(end["wall_ns"] - start["wall_ns"]))
        cpu_s = max(0.0, float(end["cpu_s"] - start["cpu_s"]))
        pkg_j: float | None = None
        core_j: float | None = None
        if self.pkg_domain is not None and start["pkg_uj"] is not None and end["pkg_uj"] is not None:
            pkg_j = self.pkg_domain.delta_uj(start["pkg_uj"], end["pkg_uj"]) / 1e6
        if self.core_domain is not None and start["core_uj"] is not None and end["core_uj"] is not None:
            core_j = self.core_domain.delta_uj(start["core_uj"], end["core_uj"]) / 1e6

        has_energy = pkg_j is not None
        return {
            "wall_ns": wall_ns,
            "wall_ms": round(wall_ns / 1e6, 4),
            "cpu_user_sys_ms": round(cpu_s * 1e3, 4),
            "evidence_class": "reported_j" if has_energy else "unmetered",
            "joules": round(pkg_j, 6) if pkg_j is not None else None,
            "core_reported_j": round(core_j, 6) if core_j is not None else None,
        }


def assert_sanitized(text: str) -> None:
    """Fail closed if any private IP, local home path, hostname, or OS username leaks."""
    patterns = [
        (r"\b100\.(?:6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.\d{1,3}\.\d{1,3}\b", "RFC6598 CGNAT IP"),
        (r"\b10(?:\.\d{1,3}){3}\b", "RFC1918 class-A private IP"),
        (r"\b192\.168(?:\.\d{1,3}){2}\b", "RFC1918 class-C private IP"),
        (r"/(?:Users|home)/[A-Za-z0-9._-]+", "local user home path"),
    ]
    host = socket.gethostname().strip()
    if host and host.lower() not in ("localhost", "buildkitsandbox") and len(host) >= 4:
        patterns.append((re.escape(host), "local machine hostname"))
    try:
        user = getpass.getuser().strip()
        if user and user.lower() not in ("root", "nobody", "replicator", "ubuntu", "runner") and len(user) >= 4:
            patterns.append((re.escape(user), "local OS username"))
    except Exception:
        pass

    for pat, desc in patterns:
        m = re.search(pat, text, flags=re.IGNORECASE)
        if m:
            raise RuntimeError(f"Sanitization check failed ({desc}): matched {m.group(0)!r}")
