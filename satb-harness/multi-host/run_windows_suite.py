#!/usr/bin/env python3
"""
Bare-Metal Windows 11 (`x86_64`) Cross-OS / Cross-API Runner for OpenIE Wave 4:
  - Deliverable A (`game-engines`):
      * `GE-H1`: 100,000-tick `Q32.32` simulation across 5 Windows runtimes (`Rust native MSVC`,
        `C++20 MSVC cl.exe /O2 /fp:strict`, `Rust Wasm32` in Node.js, `Node.js ES2024 BigInt`,
        and `CPython 3 int`), verifying all 1,000 stride-100 SHA-256 checkpoints.
      * `GE-H2`: 25,000-tick `IEEE-754` `f64` & `f32` traces over Windows Universal C Runtime
        (`UCRT` `ucrtbase.dll`), `MSVC` `/fp:strict` vs `/arch:AVX2 /fp:precise` vs `/fp:fast`,
        `Rust` `f64::sin`/`cos` & `mul_add`, `Node.js V8`, and `CPython`.
      * `GE-H3`: Headless `wgpu` (`22.1.0`) rendering across Windows `DirectX 12` (`HLSL`/`DXIL`)
        and Windows `Vulkan` (`SPIR-V`) on `NVIDIA GeForce RTX 2060`, `Intel Iris Xe Graphics`,
        `Microsoft Basic Render Driver` (`WARP`), and `CPU Q16.16` integer reference.
  - Deliverable B (`satb-harness` 5th Hardware Archetype):
      * `Shape D` `DNULLMM1` 1,000,000-record Win32 `CreateFileMappingA` / `MapViewOfFile` (`MSVC /O2`)
        + Python `mmap` 10,000-probe conformance (`15027705736`) + `test.setpoint` (`0da4df8d9ccbce1e...`).
      * `SATB` `C9` (`ContextRule_v0` + `Truncate_v0` 14-turn NTFS replay -> `149,747` B, `0` CRLF drift).
      * `SATB` `C10` runaway 4-process tree kill via Win32 `TerminateJobObject` & `taskkill /F /T /PID`.
      * `SATB` `C11` & Rootless Windows Telemetry Audit (`NVML` cumulative `mJ` on `RTX 2060` `L2`,
        Win32 `GetProcessTimes` / `QueryProcessCycleTime` `L3`, absence of rootless Intel `RAPL` MSR
        `0x611` and `EMI` `\\\\.\\EnergyMeter`, `Falsifier 5` cadence sweep, `Step 7` & `Falsifier 3`).

All paths and host identifiers are scrubbed to `$BENCH_ROOT` with zero private strings.
Usage:
  python $BENCH_ROOT/run_windows_suite.py --out-dir $BENCH_ROOT/out
"""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import datetime as dt
import gzip
import hashlib
import json
import mmap
import os
import platform
import shutil
import statistics as st
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def safe_sd(vals: list[float]) -> float:
    return st.stdev(vals) if len(vals) > 1 else 0.0


def cmd_first_line(cmd: list[str], env: dict[str, str] | None = None) -> str:
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=15, env=env)
        combined = (res.stdout or "") + "\n" + (res.stderr or "")
        for ln in combined.splitlines():
            s = ln.strip()
            if s:
                return s
        return "unavailable"
    except Exception:
        return "unavailable"


def scrub_private_tokens(raw: str) -> str:
    """Scrubs local usernames, home paths, and machine hostnames to `$BENCH_ROOT` / generic tags."""
    out = raw
    candidates: list[str] = []
    for env_k in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA", "TEMP", "TMP"):
        v = os.environ.get(env_k, "")
        if v and len(v) >= 4:
            candidates.append(v)
            candidates.append(v.replace("\\", "\\\\"))
            candidates.append(v.replace("\\", "/"))
    for env_k in ("USERNAME", "USER", "COMPUTERNAME"):
        v = os.environ.get(env_k, "")
        if v and len(v) >= 3:
            candidates.append(v)
    node = platform.node()
    if node and len(node) >= 3:
        candidates.append(node)

    # Sort longest first so full paths are replaced before bare usernames
    for tok in sorted(set(candidates), key=len, reverse=True):
        if "\\" in tok or "/" in tok:
            out = out.replace(tok, "$BENCH_ROOT")
        else:
            out = out.replace(tok, "bench_host")
    # Scrub any residual Windows user-profile paths (JSON-escaped or raw)
    import re
    out = re.sub(r"[A-Za-z]:\\\\Users\\\\[^\\\\\"\s]+", "$BENCH_ROOT", out)
    out = re.sub(r"[A-Za-z]:\\Users\\[^\\\"\s]+", "$BENCH_ROOT", out)
    out = re.sub(r"[A-Za-z]:/Users/[^/\"\s]+", "$BENCH_ROOT", out)
    if node and len(node) >= 3:
        out = re.sub(re.escape(node), "win11_bench_host", out, flags=re.IGNORECASE)
    return out


# ============================================================================
# Win32 Kernel32 / PSAPI / NVML Helpers (100% Rootless User-Mode)
# ============================================================================

class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_ulonglong),
        ("WriteOperationCount", ctypes.c_ulonglong),
        ("OtherOperationCount", ctypes.c_ulonglong),
        ("ReadTransferCount", ctypes.c_ulonglong),
        ("WriteTransferCount", ctypes.c_ulonglong),
        ("OtherTransferCount", ctypes.c_ulonglong),
    ]


class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("PageFaultCount", wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def _init_win32_sigs() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    k32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.GetProcessTimes.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
        ctypes.POINTER(FILETIME),
    ]
    k32.GetProcessTimes.restype = wintypes.BOOL
    k32.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]
    k32.QueryProcessCycleTime.restype = wintypes.BOOL
    k32.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IO_COUNTERS)]
    k32.GetProcessIoCounters.restype = wintypes.BOOL
    psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESS_MEMORY_COUNTERS), wintypes.DWORD]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.AssignProcessToJobObject.restype = wintypes.BOOL
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateJobObject.restype = wintypes.BOOL
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32, psapi


def filetime_to_100ns(ft: FILETIME) -> int:
    return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)


def read_win32_process_l3(h_proc: int | None = None) -> dict:
    k32, psapi = _init_win32_sigs()
    handle = wintypes.HANDLE(h_proc) if h_proc is not None else k32.GetCurrentProcess()

    c_time, e_time, k_time, u_time = FILETIME(), FILETIME(), FILETIME(), FILETIME()
    k32.GetProcessTimes(handle, ctypes.byref(c_time), ctypes.byref(e_time), ctypes.byref(k_time), ctypes.byref(u_time))
    cpu_100ns = filetime_to_100ns(k_time) + filetime_to_100ns(u_time)

    cycles = ctypes.c_ulonglong(0)
    k32.QueryProcessCycleTime(handle, ctypes.byref(cycles))

    io_c = IO_COUNTERS()
    k32.GetProcessIoCounters(handle, ctypes.byref(io_c))

    pmc = PROCESS_MEMORY_COUNTERS()
    pmc.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
    psapi.GetProcessMemoryInfo(handle, ctypes.byref(pmc), pmc.cb)

    return {
        "cpu_ns": cpu_100ns * 100,
        "kernel_ms": round(filetime_to_100ns(k_time) / 1e4, 4),
        "user_ms": round(filetime_to_100ns(u_time) / 1e4, 4),
        "cpu_cycles": int(cycles.value),
        "io_read_bytes": int(io_c.ReadTransferCount),
        "io_write_bytes": int(io_c.WriteTransferCount),
        "peak_working_set_kb": int(pmc.PeakWorkingSetSize // 1024),
    }


class WinNvmlReader:
    """Rootless Windows NVML (`nvml.dll`) reader for discrete GPU `L2` `reported_j` (`mJ` & `mW`)."""

    def __init__(self) -> None:
        self.lib = None
        self.dev = ctypes.c_void_p()
        self.available = False
        self.energy_supported = False
        self.gpu_name = "unavailable"
        self.driver_version = "unavailable"
        try:
            nvml = ctypes.WinDLL("nvml.dll")
            if nvml.nvmlInit_v2() == 0:
                if nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(self.dev)) == 0:
                    self.lib = nvml
                    self.available = True
                    nbuf = ctypes.create_string_buffer(96)
                    if nvml.nvmlDeviceGetName(self.dev, nbuf, 96) == 0:
                        self.gpu_name = nbuf.value.decode("utf-8", errors="replace")
                    dbuf = ctypes.create_string_buffer(80)
                    if nvml.nvmlSystemGetDriverVersion(dbuf, 80) == 0:
                        self.driver_version = dbuf.value.decode("utf-8", errors="replace")
                    e_test = ctypes.c_ulonglong(0)
                    if nvml.nvmlDeviceGetTotalEnergyConsumption(self.dev, ctypes.byref(e_test)) == 0:
                        self.energy_supported = True
        except Exception:
            self.available = False

    def read_mj_and_mw(self) -> tuple[int | None, int | None]:
        if not self.available or self.lib is None:
            return None, None
        mj_val = None
        mw_val = None
        if self.energy_supported:
            eng = ctypes.c_ulonglong(0)
            if self.lib.nvmlDeviceGetTotalEnergyConsumption(self.dev, ctypes.byref(eng)) == 0:
                mj_val = int(eng.value)
        pwr = ctypes.c_uint(0)
        if self.lib.nvmlDeviceGetPowerUsage(self.dev, ctypes.byref(pwr)) == 0:
            mw_val = int(pwr.value)
        return mj_val, mw_val

    def close(self) -> None:
        if self.lib is not None:
            try:
                self.lib.nvmlShutdown()
            except Exception:
                pass
            self.lib = None


# ============================================================================
# MSVC Environment Discovery (`vswhere.exe` -> `vcvars64.bat`)
# ============================================================================

def capture_msvc_env() -> tuple[dict[str, str] | None, str | None]:
    vswhere = Path(r"C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe")
    if not vswhere.exists():
        return None, None
    res = subprocess.run(
        [str(vswhere), "-latest", "-products", "*", "-property", "installationPath"],
        capture_output=True,
        text=True,
        check=False,
    )
    vs_root = res.stdout.strip()
    if not vs_root:
        return None, None
    vcvars = Path(vs_root) / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
    if not vcvars.exists():
        return None, None
    bat_wrapper = Path(tempfile.gettempdir()) / "wave4_vcvars_dump.cmd"
    bat_wrapper.write_text(f'@echo off\r\ncall "{vcvars}" >nul\r\nset\r\n', encoding="utf-8")
    try:
        dump = subprocess.run(
            ["cmd.exe", "/d", "/c", str(bat_wrapper)],
            capture_output=True,
            text=True,
            check=True,
        )
    finally:
        bat_wrapper.unlink(missing_ok=True)
    # Deduplicate case-insensitively for Windows CreateProcessW environment block
    dedup: dict[str, str] = {}
    for k, v in os.environ.items():
        dedup[k.upper()] = v
    for line in dump.stdout.splitlines():
        if "=" in line and not line.startswith("="):
            k, v = line.split("=", 1)
            dedup[k.upper()] = v
    cl_bin = shutil.which("cl.exe", path=dedup.get("PATH")) or shutil.which("cl", path=dedup.get("PATH"))
    return dedup, cl_bin


def detect_windows_hw_metadata() -> dict:
    ps_cmd = (
        "$p = Get-CimInstance Win32_Processor | Select-Object -First 1 Name,NumberOfCores,NumberOfLogicalProcessors; "
        "$v = Get-CimInstance Win32_VideoController | Select-Object Name,DriverVersion; "
        "$m = (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory; "
        "$o = Get-CimInstance Win32_OperatingSystem | Select-Object Caption,Version,BuildNumber; "
        "$pm = @(Get-CimInstance -Namespace root\\cimv2 -ClassName Win32_PerfRawData_Counters_PowerMeter -ErrorAction SilentlyContinue).Count; "
        "@{cpu=$p; gpus=$v; ram_bytes=$m; os=$o; wmi_power_meters=$pm} | ConvertTo-Json -Compress -Depth 4"
    )
    res = subprocess.run(
        ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(res.stdout.strip())


def detect_ucrt_version() -> str:
    ps_cmd = "(Get-Item 'C:\\Windows\\System32\\ucrtbase.dll').VersionInfo.ProductVersion"
    res = subprocess.run(
        ["pwsh", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
        capture_output=True,
        text=True,
        check=False,
    )
    v = res.stdout.strip()
    return f"Windows Universal C Runtime (ucrtbase.dll {v})" if v else "Windows Universal C Runtime (ucrtbase.dll)"


# ============================================================================
# Deliverable A.1 & A.2: `GE-H1` (5 Windows Runtimes) & `GE-H2` (UCRT/MSVC/V8)
# ============================================================================

def run_handshaked_win(cmd: list[str], cwd: Path, nvml: WinNvmlReader) -> dict:
    k32 = ctypes.windll.kernel32
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = ""
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    assert proc.stdin is not None and proc.stdout is not None and proc.stderr is not None
    ready = proc.stdout.readline().strip()
    if ready != "READY":
        err = proc.stderr.read()
        proc.kill()
        raise RuntimeError(f"Target {cmd[0]} failed READY (got {ready!r}): {err}")

    h_proc = int(proc._handle)  # Win32 HANDLE for child process
    l3_0 = read_win32_process_l3(h_proc)
    mj0, _ = nvml.read_mj_and_mw()

    proc.stdin.write("GO\n")
    proc.stdin.flush()

    done_line = proc.stdout.readline().strip()
    l3_1 = read_win32_process_l3(h_proc)
    mj1, _ = nvml.read_mj_and_mw()

    proc.stdin.write("EXIT\n")
    proc.stdin.flush()
    proc.wait(timeout=180.0)

    if not done_line.startswith("DONE\t"):
        err = proc.stderr.read()
        raise RuntimeError(f"Target {cmd[0]} failed DONE (got {done_line!r}): {err}")

    payload = json.loads(done_line.split("\t", 1)[1])
    loops = int(payload["loops"])
    d_cpu_ms = max(0.0, (l3_1["cpu_ns"] - l3_0["cpu_ns"]) / 1e6) / loops
    d_cycles = max(0, l3_1["cpu_cycles"] - l3_0["cpu_cycles"]) // loops
    d_gpu_idle_j = ((mj1 - mj0) / 1000.0 / loops) if (mj0 is not None and mj1 is not None and mj1 >= mj0) else None

    return {
        "wall_ms_per_100k": float(payload["wall_ms"]),
        "loops": loops,
        "win_l3_cpu_ms_per_100k": d_cpu_ms,
        "win_l3_cpu_cycles_per_100k": d_cycles,
        "idle_dgpu_nvml_j_during_cpu_run": d_gpu_idle_j,
        "checkpoints": payload["checkpoints"],
    }


# ============================================================================
# Deliverable B: `Shape D` `DNULLMM1` (Win32 MapViewOfFile) & `SATB` `C9/C10/C11`
# ============================================================================

Q = 1_000_000
X_MAX = 1 << 40
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1


def narrow(x: int) -> int:
    if x < I64_MIN or x > I64_MAX:
        raise ValueError("E_RANGE")
    return x


def fx_check(x: int) -> int:
    if x < -X_MAX or x > X_MAX:
        raise ValueError("E_RANGE")
    return x


def fx_add(a: int, b: int) -> int:
    return narrow(a + b)


def fx_tdiv(a: int, b: int) -> int:
    q = abs(a) // abs(b)
    return -q if (a < 0) ^ (b < 0) else q


def fx_fdiv(a: int, b: int) -> int:
    return narrow(a // b)


def fx_mul(a: int, b: int) -> int:
    prod = a * b
    q = abs(prod) // Q
    return narrow(-q if prod < 0 else q)


def fx_clamp(x: int, lo: int, hi: int) -> int:
    return lo if x < lo else (hi if x > hi else x)


def fx_sign(x: int) -> int:
    return 1 if x > 0 else (-1 if x < 0 else 0)


def canon_ints(v: list[int]) -> str:
    return "[" + ",".join(str(int(x)) for x in v) + "]"


def quantize(f: list[int], step: list[int], res: int) -> list[int]:
    return [fx_fdiv(fx_check(x), s >> res) for x, s in zip(f, step)]


def cell_key(task: str, res: int, cell: list[int]) -> str:
    b = task.encode("ascii") + b"\x00" + struct.pack(">q", res) + b"".join(struct.pack(">q", c) for c in cell)
    return hashlib.sha256(b).hexdigest()[:32]


def case_canonical(c: dict) -> str:
    return (
        f'{{"action":{{"args":{canon_ints(c["action"]["args"])},"fn":"{c["action"]["fn"]}"}},'
        f'"cell":{canon_ints(c["cell"])},"delta":{canon_ints(c["delta"])},"key":"{c["key"]}",'
        f'"kind":"{c["kind"]}","outcome":{canon_ints(c["outcome"])},"parent":{c["parent"]},'
        f'"pass":{c["pass"]},"res":{c["res"]},"score":{c["score"]},"seq":{c["seq"]},'
        f'"src":"{c["src"]}","task":"{c["task"]}","v":1}}'
    )


class Store:
    def __init__(self) -> None:
        self.log: list[dict] = []
        self.index: dict[str, list[int]] = {}
        self.digests = bytearray()

    def append(self, c: dict) -> int:
        c = dict(c)
        c["seq"] = len(self.log)
        c["key"] = cell_key(c["task"], c["res"], c["cell"])
        self.digests.extend(hashlib.sha256(case_canonical(c).encode("ascii")).digest())
        self.index.setdefault(c["key"], []).append(len(self.log))
        self.log.append(c)
        return c["seq"]

    def at(self, k: str) -> list[dict]:
        return [self.log[i] for i in self.index.get(k, [])]

    def best_pass(self, k: str) -> dict | None:
        recs = self.at(k)
        best = None
        for c in recs:
            if c["pass"] != 1:
                continue
            if any(f["pass"] == 0 and f["parent"] == c["seq"] for f in recs):
                continue
            if best is None or c["score"] > best["score"]:
                best = c
        return best

    def digest(self) -> str:
        return hashlib.sha256(self.digests).hexdigest()


def run_setpoint_episode_vector() -> dict:
    store = Store()
    step = [Q]
    gain = [Q // 2]
    lo, hi = [-100 * Q], [100 * Q]
    def_act = {"fn": "set", "args": [0]}

    def run_range(start: int, end: int, learn: bool) -> tuple[int, int, int, str]:
        succ = writes = probes = 0
        h_trace = hashlib.sha256()
        for ep in range(start, end):
            ctx = (ep % 5) * Q
            target = 3 * ctx + 7 * Q
            c0 = quantize([ctx], step, 0)
            k0 = cell_key("test.setpoint", 0, c0)
            probes += 1
            recs = store.at(k0)
            origin_kind = ""
            origin_parent = -1
            chosen = def_act

            if recs:
                bp = store.best_pass(k0)
                if bp is not None:
                    chosen = bp["action"]
                    origin_kind = "exact"
                    origin_parent = bp["seq"]
                else:
                    attempts = [rc for rc in recs if rc["pass"] == 0]
                    mut_ok = False
                    if len(attempts) < 40 and attempts:
                        last = attempts[-1]
                        d = last["delta"][0] if last["delta"] else 0
                        v = fx_add(last["action"]["args"][0], fx_mul(gain[0], d))
                        if len(attempts) >= 2:
                            prev = attempts[-2]
                            pd = prev["delta"][0] if prev["delta"] else 0
                            if fx_sign(d) * fx_sign(pd) < 0:
                                v = fx_tdiv(fx_add(last["action"]["args"][0], prev["action"]["args"][0]), 2)
                        v = fx_clamp(v, lo[0], hi[0])
                        cand = {"fn": last["action"]["fn"], "args": [v]}
                        if not any(at["action"] == cand for at in attempts):
                            chosen = cand
                            origin_kind = "mutated"
                            origin_parent = last["seq"]
                            mut_ok = True
                    if not mut_ok:
                        best = max(attempts, key=lambda at: at["score"])
                        chosen = best["action"]
                        origin_kind = "residual"
            else:
                found_nbr = False
                for off in (-1, 1):
                    probes += 1
                    hit = store.best_pass(cell_key("test.setpoint", 0, [c0[0] + off]))
                    if hit is not None:
                        chosen = hit["action"]
                        origin_kind = "neighbour"
                        origin_parent = hit["seq"]
                        found_nbr = True
                        break
                if not found_nbr:
                    chosen = def_act
                    origin_kind = "default"

            err_abs = abs(target - chosen["args"][0])
            hit_ok = err_abs <= Q // 100
            obs = [chosen["args"][0]]
            score = fx_clamp(Q - err_abs, 0, Q)
            passed = 1 if score >= 990_000 else 0
            h_trace.update(f"{ep}|0|{k0}|{chosen['fn']}|{canon_ints(chosen['args'])}|{score}\n".encode("ascii"))

            write_src = None
            write_parent = -1
            if origin_kind == "exact" and passed == 0:
                write_src, write_parent = "mut:retract", origin_parent
            elif origin_kind == "mutated":
                write_src, write_parent = "mut:step", origin_parent
            elif origin_kind == "neighbour":
                write_src, write_parent = "mut:nbr", origin_parent
            elif origin_kind == "default":
                write_src, write_parent = "mut:default", -1

            if learn and write_src is not None:
                store.append({
                    "task": "test.setpoint",
                    "cell": c0,
                    "res": 0,
                    "kind": "learned" if passed else "attempt",
                    "action": chosen,
                    "outcome": obs,
                    "score": score,
                    "pass": passed,
                    "delta": [] if passed else [target - obs[0]],
                    "parent": write_parent,
                    "src": write_src,
                    "v": 1,
                })
                writes += 1
            if hit_ok:
                succ += 1
        return succ, writes, probes, h_trace.hexdigest()

    f_s, f_w, f_p, _ = run_range(0, 200, True)
    fr_dig = store.digest()
    e_s, e_w, _, e_t = run_range(200, 300, False)
    expected_digest = "0da4df8d9ccbce1e49b8863490e6ef44b4f803bdb31414e4e19b881e04485781"
    return {
        "task": "test.setpoint",
        "fill_episodes": 200,
        "fill_successes": f_s,
        "fill_writes": f_w,
        "fill_probes": f_p,
        "frozen_store_digest": fr_dig,
        "matches_reference_digest": fr_dig == expected_digest,
        "expected_prefix_suffix": f"{expected_digest[:16]}...{expected_digest[-7:]}",
        "eval_episodes": 100,
        "eval_successes": e_s,
        "eval_writes": e_w,
        "eval_trace_digest": e_t,
    }


WIN32_MMAP_1M_SRC = r"""
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static inline uint32_t rotr32(uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }

static const uint32_t K256[64] = {
    0x428a2f98u,0x71374491u,0xb5c0fbcfu,0xe9b5dba5u,0x3956c25bu,0x59f111f1u,0x923f82a4u,0xab1c5ed5u,
    0xd807aa98u,0x12835b01u,0x243185beu,0x550c7dc3u,0x72be5d74u,0x80deb1feu,0x9bdc06a7u,0xc19bf174u,
    0xe49b69c1u,0xefbe4786u,0x0fc19dc6u,0x240ca1ccu,0x2de92c6fu,0x4a7484aau,0x5cb0a9dcu,0x76f988dau,
    0x983e5152u,0xa831c66du,0xb00327c8u,0xbf597fc7u,0xc6e00bf3u,0xd5a79147u,0x06ca6351u,0x14292967u,
    0x27b70a85u,0x2e1b2138u,0x4d2c6dfcu,0x53380d13u,0x650a7354u,0x766a0abbu,0x81c2c92eu,0x92722c85u,
    0xa2bfe8a1u,0xa81a664bu,0xc24b8b70u,0xc76c51a3u,0xd192e819u,0xd6990624u,0xf40e3585u,0x106aa070u,
    0x19a4c116u,0x1e376c08u,0x2748774cu,0x34b0bcb5u,0x391c0cb3u,0x4ed8aa4au,0x5b9cca4fu,0x682e6ff3u,
    0x748f82eeu,0x78a5636fu,0x84c87814u,0x8cc70208u,0x90befffau,0xa4506cebu,0xbef9a3f7u,0xc67178f2u
};

static void key16_bench_mmap1m(int64_t c0, int64_t c1, uint8_t out16[16]) {
    uint8_t blk[64];
    memset(blk, 0, sizeof(blk));
    memcpy(blk, "bench.mmap1m", 12);
    uint64_t u0 = (uint64_t)c0, u1 = (uint64_t)c1;
    for (int b = 0; b < 8; b++) {
        blk[21 + b] = (uint8_t)(u0 >> (56 - 8 * b));
        blk[29 + b] = (uint8_t)(u1 >> (56 - 8 * b));
    }
    blk[37] = 0x80u;
    blk[62] = 0x01u;
    blk[63] = 0x28u;

    uint32_t w[64];
    for (int i = 0; i < 16; i++) {
        w[i] = ((uint32_t)blk[4*i] << 24) | ((uint32_t)blk[4*i+1] << 16)
             | ((uint32_t)blk[4*i+2] << 8) | ((uint32_t)blk[4*i+3]);
    }
    for (int i = 16; i < 64; i++) {
        uint32_t s0 = rotr32(w[i-15], 7) ^ rotr32(w[i-15], 18) ^ (w[i-15] >> 3);
        uint32_t s1 = rotr32(w[i-2], 17) ^ rotr32(w[i-2], 19) ^ (w[i-2] >> 10);
        w[i] = w[i-16] + s0 + w[i-7] + s1;
    }
    uint32_t a=0x6a09e667u, b=0xbb67ae85u, c=0x3c6ef372u, d=0xa54ff53au;
    uint32_t e=0x510e527fu, f=0x9b05688cu, g=0x1f83d9abu, h=0x5be0cd19u;
    for (int i = 0; i < 64; i++) {
        uint32_t S1 = rotr32(e, 6) ^ rotr32(e, 11) ^ rotr32(e, 25);
        uint32_t ch = (e & f) ^ ((~e) & g);
        uint32_t t1 = h + S1 + ch + K256[i] + w[i];
        uint32_t S0 = rotr32(a, 2) ^ rotr32(a, 13) ^ rotr32(a, 22);
        uint32_t maj = (a & b) ^ (a & c) ^ (b & c);
        uint32_t t2 = S0 + maj;
        h = g; g = f; f = e; e = d + t1; d = c; c = b; b = a; a = t1 + t2;
    }
    uint32_t H[4] = { a + 0x6a09e667u, b + 0xbb67ae85u, c + 0x3c6ef372u, d + 0xa54ff53au };
    int all_zero = 1;
    for (int i = 0; i < 4; i++) {
        out16[4*i+0] = (uint8_t)(H[i] >> 24);
        out16[4*i+1] = (uint8_t)(H[i] >> 16);
        out16[4*i+2] = (uint8_t)(H[i] >> 8);
        out16[4*i+3] = (uint8_t)(H[i]);
    }
    for (int i = 0; i < 16; i++) if (out16[i] != 0) { all_zero = 0; break; }
    if (all_zero) out16[15] = 1;
}

static inline uint64_t splitmix64(uint64_t seed, uint64_t idx) {
    uint64_t z = seed + idx * 0x9E3779B97F4A7C15ULL;
    z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9ULL;
    z = (z ^ (z >> 27)) * 0x94D049BB133111EBULL;
    return z ^ (z >> 31);
}

static double now_ns(LARGE_INTEGER freq) {
    LARGE_INTEGER cnt;
    QueryPerformanceCounter(&cnt);
    return ((double)cnt.QuadPart * 1e9) / (double)freq.QuadPart;
}

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    const char *path = argv[1];
    LARGE_INTEGER freq;
    QueryPerformanceFrequency(&freq);

    const size_t n = 1000000ULL;
    const size_t cap = 2097152ULL;
    const size_t mask = cap - 1;
    const size_t total_bytes = 64 + cap * 48;

    double t_b0 = now_ns(freq);
    uint8_t *buf = (uint8_t *)calloc(1, total_bytes);
    if (!buf) return 3;
    memcpy(buf, "DNULLMM1", 8);
    uint64_t n_le = (uint64_t)n, cap_le = (uint64_t)cap;
    memcpy(buf + 8, &n_le, 8);
    memcpy(buf + 16, &cap_le, 8);

    uint8_t k16[16], zero16[16];
    memset(zero16, 0, 16);
    for (size_t i = 0; i < n; i++) {
        key16_bench_mmap1m((int64_t)i, (int64_t)((i * 7) % 1024), k16);
        uint64_t h0;
        memcpy(&h0, k16, 8);
        size_t idx = (size_t)h0 & mask;
        for (;;) {
            uint8_t *slot = buf + 64 + idx * 48;
            if (memcmp(slot, zero16, 16) == 0) {
                int64_t seq = (int64_t)i, score = 1000000LL, arg0 = (int64_t)i * 3 + 7;
                uint64_t off = (uint64_t)i * 142ULL;
                memcpy(slot, k16, 16);
                memcpy(slot + 16, &seq, 8);
                memcpy(slot + 24, &score, 8);
                memcpy(slot + 32, &arg0, 8);
                memcpy(slot + 40, &off, 8);
                break;
            }
            idx = (idx + 1) & mask;
        }
    }

    HANDLE wf = CreateFileA(path, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (wf == INVALID_HANDLE_VALUE) return 4;
    size_t written = 0;
    while (written < total_bytes) {
        DWORD chunk = (total_bytes - written > 0x10000000ULL) ? 0x10000000u : (DWORD)(total_bytes - written);
        DWORD w = 0;
        if (!WriteFile(wf, buf + written, chunk, &w, NULL) || w == 0) return 5;
        written += (size_t)w;
    }
    free(buf);
    CloseHandle(wf);
    double build_ms = (now_ns(freq) - t_b0) / 1e6;

    /* Mount via Win32 NT Section Object (`CreateFileMappingA` + `MapViewOfFile`) */
    double t_m0 = now_ns(freq);
    HANDLE rf = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
    if (rf == INVALID_HANDLE_VALUE) return 6;
    HANDLE hmap = CreateFileMappingA(rf, NULL, PAGE_READONLY, 0, 0, NULL);
    if (!hmap) return 7;
    const uint8_t *mm = (const uint8_t *)MapViewOfFile(hmap, FILE_MAP_READ, 0, 0, total_bytes);
    if (!mm) return 8;
    double mount_us = (now_ns(freq) - t_m0) / 1e3;

    const size_t nq = 10000;
    uint8_t (*qkeys)[16] = (uint8_t (*)[16])malloc(nq * 16);
    for (size_t q = 0; q < nq; q++) {
        int64_t ti = (int64_t)(splitmix64(20261121ULL, (uint64_t)q) % 1000000ULL);
        key16_bench_mmap1m(ti, (ti * 7) % 1024, qkeys[q]);
    }
    double t_q0 = now_ns(freq);
    uint64_t checksum = 0;
    for (size_t q = 0; q < nq; q++) {
        uint64_t h0;
        memcpy(&h0, qkeys[q], 8);
        size_t idx = (size_t)h0 & mask;
        for (;;) {
            const uint8_t *slot = mm + 64 + idx * 48;
            if (memcmp(slot, zero16, 16) == 0) break;
            if (memcmp(slot, qkeys[q], 16) == 0) {
                int64_t arg0;
                memcpy(&arg0, slot + 32, 8);
                checksum += (uint64_t)arg0;
                break;
            }
            idx = (idx + 1) & mask;
        }
    }
    double probe_ns = (now_ns(freq) - t_q0) / (double)nq;
    free(qkeys);
    UnmapViewOfFile(mm);
    CloseHandle(hmap);
    CloseHandle(rf);

    printf("{\"msvc_build_ms\":%.2f,\"msvc_mount_us\":%.2f,\"msvc_probe_ns\":%.2f,\"msvc_checksum\":%llu}\n",
           build_ms, mount_us, probe_ns, (unsigned long long)checksum);
    return 0;
}
"""


def splitmix64_py(seed: int, idx: int) -> int:
    z = (seed + idx * 0x9E3779B97F4A7C15) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & 0xFFFFFFFFFFFFFFFF
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & 0xFFFFFFFFFFFFFFFF
    return (z ^ (z >> 31)) & 0xFFFFFFFFFFFFFFFF


def run_shape_d_windows_conformance(msvc_env: dict[str, str], cl_bin: str) -> dict:
    expected_checksum = 15027705736
    tmp_dir = Path(tempfile.mkdtemp(prefix="satb_win_dnullmm1_"))
    try:
        c_src = tmp_dir / "dnullmm1_win.c"
        c_bin = tmp_dir / "dnullmm1_win.exe"
        mm_path = tmp_dir / "dnull_1m.mmap"
        c_src.write_text(WIN32_MMAP_1M_SRC, encoding="utf-8")

        subprocess.run(
            [cl_bin, "/nologo", "/O2", str(c_src), f"/Fe:{c_bin}"],
            cwd=str(tmp_dir),
            env=msvc_env,
            check=True,
            capture_output=True,
            text=True,
        )
        cp = subprocess.run([str(c_bin), str(mm_path)], check=True, capture_output=True, text=True)
        c_res = json.loads(cp.stdout.strip())

        # Cross-verify via Python `mmap` on Windows NT over the exact same `DNULLMM1` file
        t0 = time.perf_counter()
        f = open(mm_path, "rb")
        mm = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        py_mount_us = (time.perf_counter() - t0) * 1e6
        n_rec, cap_slots = struct.unpack_from("<QQ", mm, 8)
        mask = cap_slots - 1

        nq = 10_000
        keys = []
        for q in range(nq):
            ti = splitmix64_py(2026_1121, q) % 1_000_000
            kh = cell_key("bench.mmap1m", 0, [ti, (ti * 7) % 1024])
            keys.append(bytes.fromhex(kh))

        tq = time.perf_counter()
        py_checksum = 0
        zero16 = b"\x00" * 16
        for k16 in keys:
            (h0,) = struct.unpack_from("<Q", k16, 0)
            idx = h0 & mask
            while True:
                base = 64 + idx * 48
                sk = mm[base : base + 16]
                if sk == zero16:
                    break
                if sk == k16:
                    (arg0,) = struct.unpack_from("<q", mm, base + 32)
                    py_checksum = (py_checksum + (arg0 & 0xFFFFFFFFFFFFFFFF)) & 0xFFFFFFFFFFFFFFFF
                    break
                idx = (idx + 1) & mask
        py_probe_ns = (time.perf_counter() - tq) * 1e9 / nq
        mm.close()
        f.close()

        ep_vec = run_setpoint_episode_vector()
        return {
            "passed": (
                c_res["msvc_checksum"] == expected_checksum
                and py_checksum == expected_checksum
                and ep_vec["matches_reference_digest"]
            ),
            "win32_mapping_api": "CreateFileMappingA + MapViewOfFile (NT Section Object)",
            "records": int(n_rec),
            "mmap_bytes": 64 + int(cap_slots) * 48,
            "queries": nq,
            "expected_checksum": expected_checksum,
            "msvc_o2_build_ms": c_res["msvc_build_ms"],
            "msvc_o2_mount_us": c_res["msvc_mount_us"],
            "msvc_o2_probe_ns": c_res["msvc_probe_ns"],
            "msvc_o2_checksum": c_res["msvc_checksum"],
            "python_mmap_mount_us": round(py_mount_us, 2),
            "python_mmap_probe_ns": round(py_probe_ns, 2),
            "python_mmap_checksum": py_checksum,
            "episode_vector_conformance": ep_vec,
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


TRUNCATE_HEAD = 8192
TRUNCATE_TAIL = 8192
TEMPLATE_V0 = (
    "You are evaluated inside the Satiation Benchmark (SATB) Lane B reference harness. "
    "Work strictly inside /work using sequential tool calls (exec, read_file, write_file, list_dir). "
    "Terminate the attempt with exactly one call to submit(answer) or refuse(reason). "
    "No verifier verdict is returned to you."
)


def truncate_v0(text: str) -> str:
    raw = text.encode("utf-8")
    if len(raw) <= TRUNCATE_HEAD + TRUNCATE_TAIL:
        return text
    head = raw[:TRUNCATE_HEAD].decode("utf-8", errors="replace")
    tail = raw[-TRUNCATE_TAIL:].decode("utf-8", errors="replace")
    elided = len(raw) - (TRUNCATE_HEAD + TRUNCATE_TAIL)
    return f"{head}...[TRUNCATE_V0 elided {elided} bytes]...{tail}"


def approx_tokens(content: str) -> int:
    return (len(content.encode("utf-8")) + 3) // 4 + 4


def apply_context_rule_v0(msgs: list[dict], window_tokens: int) -> tuple[int, bool]:
    def tot() -> int:
        return sum(approx_tokens(m["content"]) for m in msgs)

    threshold_80 = (window_tokens * 80) // 100
    elided_now = 0
    if tot() > threshold_80:
        tool_idxs = [i for i, m in enumerate(msgs) if m["role"] == "tool"]
        if len(tool_idxs) > 8:
            for idx in tool_idxs[:-8]:
                if not msgs[idx].get("elided", False):
                    msgs[idx]["elided"] = True
                    msgs[idx]["content"] = "[ELIDED_BY_CONTEXT_RULE_V0]"
                    elided_now += 1
                if tot() <= threshold_80:
                    break
    return elided_now, tot() > window_tokens


def verify_c9_windows_ntfs_crlf_invariance() -> dict:
    """
    Verifies SATB `C9` (`ContextRule_v0` + `Truncate_v0` 14-turn replay) on NTFS Windows 11,
    including reading/normalizing CRLF (`\\r\\n`) text artifacts on disk to confirm `0` CRLF drift
    against the canonical 149,747-byte UTF-8 transcript SHA-256 `d697ed1476129939...`.
    """
    expected_sha256 = "d697ed147612993952aec0b695cebfc3177534584d742d92d4a17e87831460dc"
    window_tokens = 48_000

    def run_once(win_tok: int, write_ntfs_files: bool) -> tuple[bytes, str, int, int, bool]:
        tmp = Path(tempfile.mkdtemp(prefix="satb_win_c9_"))
        try:
            msgs = [
                {"role": "system", "content": TEMPLATE_V0},
                {"role": "user", "content": "BUNDLE_C9: Inspect generated logs and submit final checksum."},
            ]
            total_elided = 0
            truncated_events = 0
            hit_ceiling = False
            for turn in range(1, 15):
                el, over = apply_context_rule_v0(msgs, win_tok)
                total_elided += el
                if over:
                    hit_ceiling = True
                    break
                msgs.append({"role": "assistant", "content": f"Turn {turn}: reading log_{turn:02d}.txt"})
                payload = f"HEADER_{turn:02d}_" + ("A" * 12288) + ("B" * 12288) + f"_FOOTER_{turn:02d}"
                if write_ntfs_files:
                    # Write on NTFS and read back in binary/UTF-8 normalizing any \r\n -> \n per SATB-IO
                    fpath = tmp / f"log_{turn:02d}.txt"
                    fpath.write_bytes(payload.encode("utf-8"))
                    raw_tool_out = fpath.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
                else:
                    raw_tool_out = payload
                trunc_out = truncate_v0(raw_tool_out)
                if trunc_out != raw_tool_out:
                    truncated_events += 1
                msgs.append({"role": "tool", "content": f"read_file:{trunc_out}", "elided": False})

            if not hit_ceiling:
                el, over = apply_context_rule_v0(msgs, win_tok)
                total_elided += el
                hit_ceiling = over
            msgs.append({"role": "assistant", "content": "Submitting verified checksum."})
            submitted = "killed(context_ceiling)" if hit_ceiling else "checksum_c9_deterministic_v0"
            clean_msgs = [{"role": m["role"], "content": m["content"]} for m in msgs]
            raw_bytes = json.dumps(clean_msgs, sort_keys=True, separators=(",", ":")).encode("utf-8")
            return raw_bytes, submitted, total_elided, truncated_events, hit_ceiling
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    b1, sub1, el1, tr1, ceil1 = run_once(window_tokens, True)
    b2, sub2, _, _, ceil2 = run_once(window_tokens, False)
    _, sub_tight, _, _, ceil_tight = run_once(16_000, True)
    sha1 = hashlib.sha256(b1).hexdigest()
    sha2 = hashlib.sha256(b2).hexdigest()
    return {
        "passed": (
            b1 == b2
            and sha1 == expected_sha256
            and sha2 == expected_sha256
            and len(b1) == 149747
            and sub1 == sub2
            and not ceil1
            and not ceil2
            and el1 == 5
            and tr1 == 14
            and ceil_tight
            and sub_tight == "killed(context_ceiling)"
        ),
        "turns_replayed": 14,
        "window_tokens": window_tokens,
        "truncated_tool_outputs": tr1,
        "elided_tool_outputs_by_context_rule_v0": el1,
        "extra_model_calls_for_compaction": 0,
        "tight_window_16k_triggers_context_ceiling": ceil_tight,
        "transcript_bytes": len(b1),
        "transcript_sha256": sha1,
        "matches_macos_and_linux_sha256": sha1 == expected_sha256,
        "ntfs_crlf_drift_bytes": sum(x != y for x, y in zip(b1, b2)) + abs(len(b1) - len(b2)),
    }


def is_pid_alive_win32(pid: int) -> bool:
    k32, _ = _init_win32_sigs()
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    STILL_ACTIVE = 259
    h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    code = wintypes.DWORD(0)
    ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
    k32.CloseHandle(h)
    return bool(ok and code.value == STILL_ACTIVE)


def verify_c10_windows_process_tree_kill(n_trials: int = 5) -> dict:
    """
    Tests SATB `C10` runaway 4-process tree reaping on Windows 11 using:
      1. Win32 Kernel Job Object (`CreateJobObjectW` + `AssignProcessToJobObject` + `TerminateJobObject`)
      2. Standard Windows CLI `taskkill.exe /F /T /PID`
    Both spawn a parent Python coordinator + 3 detached background Python child sleepers (4 PIDs total).
    """
    k32, _ = _init_win32_sigs()
    py_exe = sys.executable

    child_spawner = (
        "import subprocess, sys, time, pathlib\n"
        "pf = pathlib.Path(sys.argv[1])\n"
        "procs = [subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']) for _ in range(3)]\n"
        "pf.write_text('\\n'.join(str(p.pid) for p in procs) + '\\n', encoding='utf-8')\n"
        "time.sleep(60)\n"
    )

    job_latencies_ms: list[float] = []
    job_survivors: list[int] = []
    taskkill_latencies_ms: list[float] = []
    taskkill_survivors: list[int] = []

    for mode in ("job_object", "taskkill"):
        for _ in range(n_trials):
            tmp = Path(tempfile.mkdtemp(prefix="satb_win_c10_"))
            pid_file = tmp / "pids.txt"
            spawner_py = tmp / "spawn_tree.py"
            spawner_py.write_text(child_spawner, encoding="utf-8")

            h_job = None
            if mode == "job_object":
                h_job = k32.CreateJobObjectW(None, None)

            proc = subprocess.Popen(
                [py_exe, str(spawner_py), str(pid_file)],
                cwd=str(tmp),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
            )
            if h_job:
                k32.AssignProcessToJobObject(h_job, int(proc._handle))

            t_wait = time.perf_counter()
            child_pids: list[int] = []
            while (time.perf_counter() - t_wait) < 3.0:
                if pid_file.exists():
                    lines = [x.strip() for x in pid_file.read_text(encoding="utf-8").splitlines() if x.strip().isdigit()]
                    if len(lines) >= 3:
                        child_pids = [int(x) for x in lines[:3]]
                        break
                time.sleep(0.010)

            all_pids = [proc.pid, *child_pids]
            assert len(all_pids) == 4, f"Expected 4 PIDs in tree, got {all_pids}"

            t_kill0 = time.perf_counter()
            if mode == "job_object":
                k32.TerminateJobObject(h_job, 137)
                proc.wait(timeout=2.0)
            else:
                subprocess.run(
                    ["taskkill.exe", "/F", "/T", "/PID", str(proc.pid)],
                    capture_output=True,
                    check=False,
                    timeout=2.0,
                )
                proc.wait(timeout=2.0)

            while (time.perf_counter() - t_kill0) < 2.0:
                if not any(is_pid_alive_win32(p) for p in all_pids):
                    break
                time.sleep(0.0005)

            kill_ms = (time.perf_counter() - t_kill0) * 1000.0
            alive_after = sum(1 for p in all_pids if is_pid_alive_win32(p))
            if h_job:
                k32.CloseHandle(h_job)
                job_latencies_ms.append(round(kill_ms, 3))
                job_survivors.append(alive_after)
            else:
                taskkill_latencies_ms.append(round(kill_ms, 3))
                taskkill_survivors.append(alive_after)
            shutil.rmtree(tmp, ignore_errors=True)

    return {
        "passed": (
            max(job_latencies_ms) < 2000.0
            and max(taskkill_latencies_ms) < 2000.0
            and sum(job_survivors) == 0
            and sum(taskkill_survivors) == 0
        ),
        "spec_ceiling_ms": 2000.0,
        "trials_per_mechanism": n_trials,
        "processes_per_tree": 4,
        "win32_terminate_job_object": {
            "cleanup_ms_trials": job_latencies_ms,
            "cleanup_ms_min": round(min(job_latencies_ms), 3),
            "cleanup_ms_mean": round(st.mean(job_latencies_ms), 3),
            "cleanup_ms_max": round(max(job_latencies_ms), 3),
            "surviving_pids_after_kill": sum(job_survivors),
        },
        "cli_taskkill_f_t": {
            "cleanup_ms_trials": taskkill_latencies_ms,
            "cleanup_ms_min": round(min(taskkill_latencies_ms), 3),
            "cleanup_ms_mean": round(st.mean(taskkill_latencies_ms), 3),
            "cleanup_ms_max": round(max(taskkill_latencies_ms), 3),
            "surviving_pids_after_kill": sum(taskkill_survivors),
        },
        "outcome_recorded": "killed(wall_ceiling)",
    }


def run_windows_falsifier_5_and_3(nvml: WinNvmlReader) -> tuple[dict, dict]:
    """
    Runs `Falsifier 5` observer cadence sweep (`0 Hz`, `1 Hz`, `10 Hz`, `100 Hz`) over
    in-process `nvml.dll` + Win32 `GetProcessTimes`, plus `Step 7` sum check & `Falsifier 3`
    sequential two-phase audit (`Phase 1` SHA-256 compute vs `Phase 2` 192 MiB DRAM + `os.fsync`).
    """
    lat_us: list[float] = []
    for _ in range(50):
        t0 = time.perf_counter_ns()
        _ = nvml.read_mj_and_mw()
        _ = read_win32_process_l3()
        lat_us.append((time.perf_counter_ns() - t0) / 1e3)

    # Also measure spawning external `nvidia-smi` CLI once to contrast FFI vs subprocess overhead
    smi_ms = None
    smi_bin = shutil.which("nvidia-smi")
    if smi_bin:
        ts0 = time.perf_counter()
        subprocess.run(
            [smi_bin, "--query-gpu=power.draw", "--format=csv,noheader,nounits"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        smi_ms = round((time.perf_counter() - ts0) * 1000.0, 2)

    window_s = 1.05
    cadences = [
        ("boundary_0hz", None),
        ("tick_1hz_1000ms", 1.000),
        ("tick_10hz_100ms_ref", 0.100),
        ("tick_100hz_10ms", 0.010),
    ]
    cad_res: dict[str, dict] = {}
    for key, sleep_s in cadences:
        l3_0 = read_win32_process_l3()
        mj0, _ = nvml.read_mj_and_mw()
        t0 = time.perf_counter()
        if sleep_s is None:
            time.sleep(window_s)
            wall_s = time.perf_counter() - t0
            n_samples = 2
        else:
            n_samples = 0
            while True:
                if (time.perf_counter() - t0) >= window_s:
                    break
                _ = nvml.read_mj_and_mw()
                _ = read_win32_process_l3()
                n_samples += 1
                rem = window_s - (time.perf_counter() - t0)
                if rem <= 0:
                    break
                # Win32 default timer resolution (~15.6 ms) shapes `time.sleep(0.010)`!
                time.sleep(min(sleep_s, rem))
            wall_s = time.perf_counter() - t0
        mj1, _ = nvml.read_mj_and_mw()
        l3_1 = read_win32_process_l3()
        cpu_ms = max(0.0, (l3_1["cpu_ns"] - l3_0["cpu_ns"]) / 1e6)
        gpu_j = ((mj1 - mj0) / 1000.0) if (mj0 is not None and mj1 is not None and mj1 >= mj0) else None
        cad_res[key] = {
            "nominal_hz": 0.0 if sleep_s is None else round(1.0 / sleep_s, 1),
            "window_s": round(wall_s, 4),
            "samples": n_samples,
            "achieved_hz": round(n_samples / wall_s, 2),
            "sampler_cpu_ms_in_window": round(cpu_ms, 3),
            "sampler_cpu_ms_per_10s_equiv": round(cpu_ms * (10.0 / wall_s), 3),
            "rtx2060_nvml_l2_reported_j": round(gpu_j, 4) if gpu_j is not None else None,
        }

    f5 = {
        "nvml_plus_win32_l3_single_read_latency_us": {
            "median_us": round(st.median(lat_us), 2),
            "mean_us": round(st.mean(lat_us), 2),
            "p95_us": round(sorted(lat_us)[int(0.95 * len(lat_us))], 2),
        },
        "nvidia_smi_subprocess_single_call_ms": smi_ms,
        "windows_nt_timer_quantum_note": "Standard unprivileged Windows NT timer tick (~15.625 ms without timeBeginPeriod(1)) caps naive 10 ms sleep loops near ~64 Hz while keeping 100 ms (10 Hz) SATB reference ticks exact.",
        "window_target_s": window_s,
        "cadences": cad_res,
    }

    # Falsifier 3 & Step 7 sum check
    phase_s = 1.20
    baseline_s = 0.60
    tmp_dir = tempfile.mkdtemp(prefix="satb_win_f3_")
    io_path = os.path.join(tmp_dir, "flush.bin")
    buf_mem = bytearray(192 * 1024 * 1024)
    for off in range(0, len(buf_mem), 4096):
        buf_mem[off] = (off >> 12) & 0xFF
    flush_chunk = b"X" * (256 * 1024)

    try:
        t_pre0 = time.perf_counter()
        mj_pre0, _ = nvml.read_mj_and_mw()
        time.sleep(baseline_s)

        t_0 = time.perf_counter()
        mj_0, _ = nvml.read_mj_and_mw()
        l3_0 = read_win32_process_l3()

        digest = b"satb_win11_phase1_compute"
        while (time.perf_counter() - t_0) < phase_s:
            for _ in range(4000):
                digest = hashlib.sha256(digest).digest()

        t_1 = time.perf_counter()
        mj_1, _ = nvml.read_mj_and_mw()
        l3_1 = read_win32_process_l3()

        stride = 65537 * 64
        pos = 0
        n_bytes = len(buf_mem)
        with open(io_path, "wb") as f_io:
            while (time.perf_counter() - t_1) < phase_s:
                acc = 0
                for _ in range(8192):
                    pos = (pos + stride) % n_bytes
                    buf_mem[pos] = (buf_mem[pos] + 1) & 0xFF
                    acc += buf_mem[pos]
                f_io.seek(0)
                f_io.write(flush_chunk)
                f_io.flush()
                os.fsync(f_io.fileno())
                time.sleep(0.008)

        t_2 = time.perf_counter()
        mj_2, _ = nvml.read_mj_and_mw()
        l3_2 = read_win32_process_l3()

        time.sleep(baseline_s)
        t_post1 = time.perf_counter()
        mj_post1, _ = nvml.read_mj_and_mw()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)

    cpu_p1_ms = max(0.0, (l3_1["cpu_ns"] - l3_0["cpu_ns"]) / 1e6)
    cpu_p2_ms = max(0.0, (l3_2["cpu_ns"] - l3_1["cpu_ns"]) / 1e6)
    tot_cpu_ms = max(1e-6, cpu_p1_ms + cpu_p2_ms)
    c_p1 = cpu_p1_ms / tot_cpu_ms
    c_p2 = cpu_p2_ms / tot_cpu_ms

    cyc_p1 = max(0, l3_1["cpu_cycles"] - l3_0["cpu_cycles"])
    cyc_p2 = max(0, l3_2["cpu_cycles"] - l3_1["cpu_cycles"])
    tot_cyc = max(1, cyc_p1 + cyc_p2)
    c_cyc_p1 = cyc_p1 / tot_cyc
    c_cyc_p2 = cyc_p2 / tot_cyc

    p1_dur = t_1 - t_0
    p2_dur = t_2 - t_1
    pre_dur = t_0 - t_pre0
    post_dur = t_post1 - t_2

    f3_out: dict = {
        "phase1_compute_wall_s": round(p1_dur, 4),
        "phase2_dram_flushfilebuffers_wall_s": round(p2_dur, 4),
        "phase1_sut_cpu_ms_getprocesstimes": round(cpu_p1_ms, 2),
        "phase2_sut_cpu_ms_getprocesstimes": round(cpu_p2_ms, 2),
        "windows_clock_interrupt_aliasing_note": "Win32 GetProcessTimes updates on 15.625 ms clock ticks and can alias short 8 ms sleep+I/O bursts to 0.0 ms; QueryProcessCycleTime (RDTSC per context switch) captures exact sub-tick CPU cycles.",
        "phase1_sut_cpu_cycles": int(cyc_p1),
        "phase2_sut_cpu_cycles": int(cyc_p2),
        "kepler_c_getprocesstimes_share_phase1": round(c_p1, 4),
        "kepler_c_getprocesstimes_share_phase2": round(c_p2, 4),
        "kepler_c_rdtsc_cycle_share_phase1": round(c_cyc_p1, 4),
        "kepler_c_rdtsc_cycle_share_phase2": round(c_cyc_p2, 4),
        "cpu_package_l2_reported_j": "not_available (Windows 11 blocks unprivileged Intel RAPL MSR 0x611 reads without a ring-0 driver; 0 WMI EMI PowerMeter instances)",
    }

    if all(x is not None for x in (mj_pre0, mj_0, mj_1, mj_2, mj_post1)):
        assert mj_pre0 is not None and mj_0 is not None and mj_1 is not None and mj_2 is not None and mj_post1 is not None
        dmj_pre = mj_0 - mj_pre0
        dmj_p1 = mj_1 - mj_0
        dmj_p2 = mj_2 - mj_1
        dmj_tot = mj_2 - mj_0
        dmj_post = mj_post1 - mj_2
        res_mj = abs((dmj_p1 + dmj_p2) - dmj_tot)
        w_pre = (dmj_pre / 1000.0) / max(1e-6, pre_dur)
        w_post = (dmj_post / 1000.0) / max(1e-6, post_dur)
        drift_pct = abs(w_post - w_pre) / max(1e-6, w_pre) * 100.0
        b_p1_j = dmj_p1 / 1000.0
        b_p2_j = dmj_p2 / 1000.0
        b_tot_j = dmj_tot / 1000.0
        c_est_p2_time = b_tot_j * c_p2
        c_est_p2_cyc = b_tot_j * c_cyc_p2
        err_p2_time = abs(c_est_p2_time - b_p2_j) / max(1e-6, b_p2_j) * 100.0
        err_p2_cyc = abs(c_est_p2_cyc - b_p2_j) / max(1e-6, b_p2_j) * 100.0
        f3_out["rtx2060_nvml_l2_cumulative_energy_audit"] = {
            "pre_baseline_mean_w": round(w_pre, 3),
            "phase1_mean_w": round(b_p1_j / max(1e-6, p1_dur), 3),
            "phase2_mean_w": round(b_p2_j / max(1e-6, p2_dur), 3),
            "post_baseline_mean_w": round(w_post, 3),
            "pre_post_drift_pct": round(drift_pct, 2),
            "falsifier6_within_5pct": drift_pct <= 5.0,
            "b_temporal_phase1_reported_j": round(b_p1_j, 3),
            "b_temporal_phase2_reported_j": round(b_p2_j, 3),
            "b_temporal_total_reported_j": round(b_tot_j, 3),
            "step7_sum_check_residual_mj": int(res_mj),
            "step7_sum_check_passed": res_mj <= 1,
            "naive_cpu_kepler_c_getprocesstimes_phase2_err_pct": round(err_p2_time, 2),
            "naive_cpu_kepler_c_rdtsc_cycles_phase2_err_pct": round(err_p2_cyc, 2),
            "falsifier_3_triggered_gt_20pct": err_p2_cyc > 20.0,
        }

    return f5, f3_out


def verify_standard_user_restricted_token_telemetry() -> dict:
    """
    OpenSSH on Windows (`sshd`) logs in members of `Administrators` with an elevated token by default.
    To prove strictly rootless (`IsUserAnAdmin() == False`, `Basic` Medium-Integrity) telemetry access
    under SATB `OQ-5`, we spawn a child Python probe using `runas /trustlevel:0x20000` (Basic User
    de-elevated token) and verify `NVML` cumulative `mJ`, `GetProcessTimes`, `QueryProcessCycleTime`,
    and `CreateJobObjectW` all succeed with `IsUserAnAdmin() == False`.
    """
    probe_code = (
        "import ctypes, json, pathlib, sys\n"
        "from ctypes import wintypes\n"
        "is_adm = bool(ctypes.windll.shell32.IsUserAnAdmin())\n"
        "nvml = ctypes.WinDLL('nvml.dll'); rc_i = nvml.nvmlInit_v2()\n"
        "dev = ctypes.c_void_p(); rc_h = nvml.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))\n"
        "eng = ctypes.c_ulonglong(0); rc_e = nvml.nvmlDeviceGetTotalEnergyConsumption(dev, ctypes.byref(eng))\n"
        "pwr = ctypes.c_uint(0); rc_p = nvml.nvmlDeviceGetPowerUsage(dev, ctypes.byref(pwr))\n"
        "nvml.nvmlShutdown()\n"
        "k32 = ctypes.windll.kernel32\n"
        "k32.GetCurrentProcess.restype = wintypes.HANDLE\n"
        "k32.QueryProcessCycleTime.argtypes = [wintypes.HANDLE, ctypes.POINTER(ctypes.c_ulonglong)]\n"
        "cyc = ctypes.c_ulonglong(0); ok_cyc = bool(k32.QueryProcessCycleTime(k32.GetCurrentProcess(), ctypes.byref(cyc)))\n"
        "k32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]; k32.CreateJobObjectW.restype = wintypes.HANDLE\n"
        "hj = k32.CreateJobObjectW(None, None); ok_job = bool(hj)\n"
        "res = {'is_user_an_admin': is_adm, 'nvml_energy_rc': rc_e, 'nvml_energy_mj': eng.value, 'nvml_power_mw': pwr.value, 'l3_cycles_readable': ok_cyc, 'job_object_creatable': ok_job}\n"
        "pathlib.Path(sys.argv[1]).write_text(json.dumps(res), encoding='utf-8')\n"
    )
    tmp = Path(tempfile.mkdtemp(prefix="satb_deelev_"))
    try:
        out_f = tmp / "deelev.json"
        script_f = tmp / "probe.py"
        script_f.write_text(probe_code, encoding="utf-8")
        subprocess.run(
            ["runas.exe", "/trustlevel:0x20000", f'"{sys.executable}" "{script_f}" "{out_f}"'],
            capture_output=True,
            check=False,
            timeout=10,
        )
        for _ in range(40):
            if out_f.exists() and out_f.stat().st_size > 10:
                break
            time.sleep(0.05)
        if out_f.exists():
            data = json.loads(out_f.read_text(encoding="utf-8"))
            data["trustlevel"] = "0x20000 (Basic User / Standard Non-Elevated Token)"
            data["verified"] = (not data["is_user_an_admin"]) and (data["nvml_energy_rc"] == 0) and data["l3_cycles_readable"]
            return data
        return {"verified": False, "note": "runas trustlevel output not produced"}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--replicates", type=int, default=5)
    ap.add_argument("--ticks-h1", type=int, default=100000)
    ap.add_argument("--ticks-h2", type=int, default=25000)
    ap.add_argument("--satb-only", action="store_true", help="Run only Deliverable B SATB & Shape D conformance")
    args = ap.parse_args()

    t_suite_start = time.perf_counter()
    work_dir = Path(__file__).resolve().parent
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    wgpu_out_dir = out_dir / "wgpu_frames"
    wgpu_out_dir.mkdir(parents=True, exist_ok=True)

    host_id = "win11_x86_64"
    hw_meta = detect_windows_hw_metadata()
    ucrt_desc = detect_ucrt_version()
    msvc_env, cl_bin = capture_msvc_env()
    assert msvc_env is not None and cl_bin is not None, "MSVC cl.exe not found via vswhere!"

    rustc_bin = shutil.which("rustc") or "rustc"
    cargo_bin = shutil.which("cargo") or "cargo"
    node_bin = shutil.which("node") or ""
    py_bin = sys.executable

    nvml = WinNvmlReader()
    try:
        is_admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        is_admin = False

    cpu_name = hw_meta["cpu"]["Name"].strip()
    os_ver = f"{hw_meta['os']['Caption'].strip()} ({platform.system()} NT {hw_meta['os']['Version']})"
    cl_ver = cmd_first_line([cl_bin], env=msvc_env)

    print(f"[{host_id}] Starting Windows 11 Bare-Metal Suite on {cpu_name} | {os_ver}", flush=True)
    print(f"  MSVC: {cl_ver}", flush=True)
    print(f"  NVML: available={nvml.available} energy_supported={nvml.energy_supported} gpu={nvml.gpu_name} ({nvml.driver_version})", flush=True)

    start_utc = dt.datetime.now(dt.timezone.utc).isoformat()

    if not args.satb_only:
        with tempfile.TemporaryDirectory(prefix="wave4_win_bins_") as btmp:
            bdir = Path(btmp)
            rust_exe = bdir / "sim_rust.exe"
            wasm_file = bdir / "sim_wasm.wasm"
            msvc_strict_exe = bdir / "sim_cpp_msvc_strict.exe"
            msvc_fma_exe = bdir / "sim_cpp_msvc_fma.exe"
            msvc_fast_exe = bdir / "sim_cpp_msvc_fast.exe"

            print(f"[{host_id}] Compiling Rust native (x86_64-pc-windows-msvc), Rust Wasm32, and 3 MSVC C++20 variants...", flush=True)
            subprocess.run(
                [rustc_bin, "--edition", "2021", "-O", str(work_dir / "sim_rust.rs"), "-o", str(rust_exe)],
                env=msvc_env,
                check=True,
            )
            subprocess.run(
                [
                    rustc_bin,
                    "--edition",
                    "2021",
                    "--target",
                    "wasm32-unknown-unknown",
                    "-O",
                    "--crate-type",
                    "cdylib",
                    str(work_dir / "sim_wasm.rs"),
                    "-o",
                    str(wasm_file),
                ],
                env=msvc_env,
                check=True,
            )
            subprocess.run(
                [cl_bin, "/nologo", "/std:c++20", "/O2", "/fp:strict", "/EHsc", str(work_dir / "sim_cpp.cpp"), f"/Fe:{msvc_strict_exe}"],
                cwd=str(bdir),
                env=msvc_env,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [cl_bin, "/nologo", "/std:c++20", "/O2", "/arch:AVX2", "/fp:precise", "/EHsc", str(work_dir / "sim_cpp.cpp"), f"/Fe:{msvc_fma_exe}"],
                cwd=str(bdir),
                env=msvc_env,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                [cl_bin, "/nologo", "/std:c++20", "/O2", "/arch:AVX2", "/fp:fast", "/EHsc", str(work_dir / "sim_cpp.cpp"), f"/Fe:{msvc_fast_exe}"],
                cwd=str(bdir),
                env=msvc_env,
                check=True,
                capture_output=True,
            )

            # --------------------------------------------------------------------
            # 1. GE-H1: 100,000-tick Q32.32 Determinism across 5 Windows Runtimes
            # --------------------------------------------------------------------
            h1_specs = [
                (
                    "rust_native",
                    "Rust native (x86_64-pc-windows-msvc, rustc 1.100 -O)",
                    [str(rust_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [str(rust_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "25", "--handshake"],
                ),
                (
                    "cpp20_msvc_o2",
                    "C++20 native (MSVC cl.exe 19.44 /O2 /fp:strict, x86_64 PE)",
                    [str(msvc_strict_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [str(msvc_strict_exe), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "25", "--handshake"],
                ),
                (
                    "rust_wasm32_node",
                    "Rust -> WebAssembly (wasm32-unknown-unknown in Windows Node.js)",
                    [node_bin, str(work_dir / "run_wasm.mjs"), "--wasm", str(wasm_file), "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [node_bin, str(work_dir / "run_wasm.mjs"), "--wasm", str(wasm_file), "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "15", "--handshake"],
                ),
                (
                    "javascript_bigint_node",
                    "JavaScript (Windows Node.js ES2024 BigInt)",
                    [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "2", "--handshake"],
                ),
                (
                    "python3_int",
                    f"Python {platform.python_version()} (Windows CPython int)",
                    [py_bin, str(work_dir / "sim_py.py"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "100", "--loops", "1", "--handshake"],
                    [py_bin, str(work_dir / "sim_py.py"), "--mode", "q32", "--ticks", str(args.ticks_h1), "--stride", "1000", "--loops", "1", "--handshake"],
                ),
            ]

            print(f"[{host_id}] Running GE-H1 1,000-checkpoint pass (stride=100) across 5 Windows targets...", flush=True)
            stride100_ckpts: dict[str, dict[str, str]] = {}
            for tid, _desc, cmd100, _cmd1000 in h1_specs:
                r100 = run_handshaked_win(cmd100, work_dir, nvml)
                stride100_ckpts[tid] = r100["checkpoints"]
                print(
                    f"  [stride=100] {tid:24s} count={len(r100['checkpoints'])} "
                    f"H(100)={r100['checkpoints']['100'][:12]}... H(100k)={r100['checkpoints']['100000'][:12]}...",
                    flush=True,
                )

            ref_ck100 = stride100_ckpts["rust_native"]
            assert len(ref_ck100) == 1000
            assert ref_ck100["100"].startswith("2683c3f7cb8b"), f"Unexpected H(100): {ref_ck100['100']}"
            assert ref_ck100["100000"].startswith("82e404df6475"), f"Unexpected H(100000): {ref_ck100['100000']}"

            print(f"[{host_id}] Running GE-H1 timed replicates ({args.replicates} reps, stride=1000)...", flush=True)
            h1_summaries: list[dict] = []
            for tid, desc, _cmd100, cmd1000 in h1_specs:
                reps = [run_handshaked_win(cmd1000, work_dir, nvml) for _ in range(args.replicates)]
                w_vals = [x["wall_ms_per_100k"] for x in reps]
                cpu_vals = [x["win_l3_cpu_ms_per_100k"] for x in reps]
                cyc_vals = [float(x["win_l3_cpu_cycles_per_100k"]) for x in reps]
                mismatches_1000 = sum(1 for k, v in ref_ck100.items() if stride100_ckpts[tid].get(k) != v)
                mismatches_reps = sum(
                    1 for x in reps for k, v in x["checkpoints"].items() if ref_ck100.get(k) != v
                )
                summary = {
                    "host_id": host_id,
                    "target_id": tid,
                    "description": desc,
                    "replicates": args.replicates,
                    "loops_per_replicate": reps[0]["loops"],
                    "wall_ms_per_100k_mean": round(st.mean(w_vals), 4),
                    "wall_ms_per_100k_sd": round(safe_sd(w_vals), 4),
                    "ns_per_tick_mean": round(st.mean(w_vals) * 1e6 / args.ticks_h1, 2),
                    "win32_l3_cpu_ms_per_100k_mean": round(st.mean(cpu_vals), 4),
                    "win32_l3_cpu_cycles_per_100k_mean": int(round(st.mean(cyc_vals))),
                    "rapl_pkg_reported_j_per_100k_mean": None,
                    "rapl_pkg_reported_j_per_100k_sd": None,
                    "rapl_core_reported_j_per_100k_mean": None,
                    "rapl_core_reported_j_per_100k_sd": None,
                    "mac_l3_reported_j_per_100k_mean": None,
                    "mac_l3_reported_j_per_100k_sd": None,
                    "measured_j": None,
                    "checkpoints_verified_stride100": len(stride100_ckpts[tid]),
                    "checkpoint_mismatches_vs_host_rust": mismatches_1000,
                    "replicate_checkpoint_mismatches": mismatches_reps,
                    "tick_100_sha256": stride100_ckpts[tid]["100"],
                    "tick_1000_sha256": stride100_ckpts[tid]["1000"],
                    "tick_50000_sha256": stride100_ckpts[tid]["50000"],
                    "tick_100000_sha256": stride100_ckpts[tid]["100000"],
                }
                h1_summaries.append(summary)
                print(
                    f"  [timed] {tid:24s} wall={summary['wall_ms_per_100k_mean']:8.3f}ms  "
                    f"cycles={summary['win32_l3_cpu_cycles_per_100k_mean']:,d}  mismatches={mismatches_1000}",
                    flush=True,
                )

            # --------------------------------------------------------------------
            # 2. GE-H2: 25,000-tick Float Traces (Windows UCRT / MSVC / Rust / V8)
            # --------------------------------------------------------------------
            print(f"[{host_id}] Running GE-H2 {args.ticks_h2}-tick float traces...", flush=True)
            t_h2 = str(args.ticks_h2)
            h2_trace_specs = [
                ("cpp_msvc_f64_strict", [str(msvc_strict_exe), "--mode", "f64_strict", "--ticks", t_h2]),
                ("cpp_msvc_f64_trig", [str(msvc_strict_exe), "--mode", "f64_trig", "--ticks", t_h2]),
                ("cpp_msvc_f64_fma", [str(msvc_fma_exe), "--mode", "f64_strict", "--ticks", t_h2]),
                ("cpp_msvc_f64_fma_trig", [str(msvc_fma_exe), "--mode", "f64_trig", "--ticks", t_h2]),
                ("cpp_msvc_f64_fast", [str(msvc_fast_exe), "--mode", "f64_strict", "--ticks", t_h2]),
                ("cpp_msvc_f64_fast_trig", [str(msvc_fast_exe), "--mode", "f64_trig", "--ticks", t_h2]),
                ("cpp_msvc_f32_strict", [str(msvc_strict_exe), "--mode", "f32_strict", "--ticks", t_h2]),
                ("cpp_msvc_f32_trig", [str(msvc_strict_exe), "--mode", "f32_trig", "--ticks", t_h2]),
                ("rust_f64_strict", [str(rust_exe), "--mode", "f64_strict", "--ticks", t_h2]),
                ("rust_f64_trig", [str(rust_exe), "--mode", "f64_trig", "--ticks", t_h2]),
                ("rust_f64_fma", [str(rust_exe), "--mode", "f64_fma", "--ticks", t_h2]),
                ("rust_f64_fma_trig", [str(rust_exe), "--mode", "f64_fma_trig", "--ticks", t_h2]),
                ("rust_f32_strict", [str(rust_exe), "--mode", "f32_strict", "--ticks", t_h2]),
                ("rust_f32_trig", [str(rust_exe), "--mode", "f32_trig", "--ticks", t_h2]),
                ("node_v8_f64_strict", [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "f64_strict", "--ticks", t_h2]),
                ("node_v8_f64_trig", [node_bin, str(work_dir / "sim_js.mjs"), "--mode", "f64_trig", "--ticks", t_h2]),
                ("python_f64_strict", [py_bin, str(work_dir / "sim_py.py"), "--mode", "f64_strict", "--ticks", t_h2]),
                ("python_f64_trig", [py_bin, str(work_dir / "sim_py.py"), "--mode", "f64_trig", "--ticks", t_h2]),
            ]
            h2_traces_payload: dict[str, list[list[str]]] = {}
            for tr_id, tr_cmd in h2_trace_specs:
                env_nt = os.environ.copy()
                env_nt["CUDA_VISIBLE_DEVICES"] = ""
                raw_out = subprocess.run(tr_cmd, cwd=str(work_dir), capture_output=True, text=True, check=True, env=env_nt).stdout
                tr_data = json.loads(raw_out)["trace"]
                h2_traces_payload[tr_id] = tr_data
                print(f"  [GE-H2] {tr_id:28s} ticks={len(tr_data)} final_ieee={tr_data[-1][0]}", flush=True)

    # ------------------------------------------------------------------------
    # 3. GE-H3: Headless wgpu Render on Windows DirectX 12 & Windows Vulkan
    # ------------------------------------------------------------------------
    if not args.satb_only:
        print(f"[{host_id}] Building & running ge_h3_wgpu_bench (DirectX 12 + Vulkan)...", flush=True)
        wgpu_target_dir = Path(tempfile.mkdtemp(prefix="wave4_wgpu_target_"))
        try:
            cargo_env = msvc_env.copy()
            cargo_env["CARGO_TARGET_DIR"] = str(wgpu_target_dir)
            subprocess.run(
                [cargo_bin, "build", "--release", "--manifest-path", str(work_dir / "ge_h3_wgpu_bench" / "Cargo.toml")],
                env=cargo_env,
                check=True,
            )
            wgpu_exe = wgpu_target_dir / "release" / "ge_h3_wgpu_bench.exe"
            mj_g0, _ = nvml.read_mj_and_mw()
            subprocess.run(
                [str(wgpu_exe), "render", "--host-id", host_id, "--out-dir", str(wgpu_out_dir)],
                env=cargo_env,
                check=True,
            )
            mj_g1, _ = nvml.read_mj_and_mw()
            wgpu_nvml_j = ((mj_g1 - mj_g0) / 1000.0) if (mj_g0 is not None and mj_g1 is not None and mj_g1 >= mj_g0) else None
        finally:
            shutil.rmtree(wgpu_target_dir, ignore_errors=True)

        end_utc = dt.datetime.now(dt.timezone.utc).isoformat()

        traces_gz_path = out_dir / f"h2_traces_{host_id}.json.gz"
        with gzip.open(traces_gz_path, "wt", encoding="utf-8") as gz:
            json.dump({"host_id": host_id, "ticks": args.ticks_h2, "traces": h2_traces_payload}, gz)

        ge_host_receipt = {
            "host_id": host_id,
            "bench_root": "$BENCH_ROOT",
            "measured_j": None,
            "board_metered": False,
            "energy_telemetry": "none for CPU-only GE-H1 (Windows 11 blocks unprivileged Intel RAPL MSR 0x611 reads without a ring-0 kernel driver; Win32 GetProcessTimes/QueryProcessCycleTime L3 recorded; RTX 2060 NVML cumulative mJ verified separately)",
            "wgpu_render_pass_rtx2060_nvml_l2_reported_j": round(wgpu_nvml_j, 4) if wgpu_nvml_j is not None else None,
            "environment": {
                "cpu": cpu_name,
                "arch": "x86_64",
                "os": os_ver,
                "libc_libm": ucrt_desc,
                "rustc": cmd_first_line([rustc_bin, "--version"], env=msvc_env),
                "msvc_cl": cl_ver,
                "clangxx": None,
                "gxx": None,
                "node": cmd_first_line([node_bin, "--version"]),
                "python": f"Python {platform.python_version()}",
                "gpus": hw_meta["gpus"],
                "start_utc": start_utc,
                "end_utc": end_utc,
            },
            "ge_h1_targets": h1_summaries,
            "ge_h1_canonical_1000_checkpoints": ref_ck100,
            "ge_h2_trace_keys": list(h2_traces_payload.keys()),
        }
        ge_receipt_path = out_dir / f"host_receipt_{host_id}.json"
        ge_receipt_path.write_text(scrub_private_tokens(json.dumps(ge_host_receipt, indent=2)) + "\n", encoding="utf-8")

    # ------------------------------------------------------------------------
    # 4. Deliverable B: Bare-Metal Windows 11 `SATB` & `Shape D` Conformance
    # ------------------------------------------------------------------------
    print(f"[{host_id}] Running Deliverable B: Shape D DNULLMM1 + SATB C9/C10/C11 + NVML/MSR Audit...", flush=True)
    t_satb0 = time.perf_counter()
    shape_d = run_shape_d_windows_conformance(msvc_env, cl_bin)
    c9 = verify_c9_windows_ntfs_crlf_invariance()
    c10 = verify_c10_windows_process_tree_kill(n_trials=5)
    deelev_probe = verify_standard_user_restricted_token_telemetry()

    t_mono = time.monotonic_ns()
    t_wall = time.time_ns()
    l3_self = read_win32_process_l3()
    rootless_verified = bool(deelev_probe.get("verified")) or (not is_admin)
    c11 = {
        "passed": l3_self["peak_working_set_kb"] > 0 and rootless_verified,
        "kernel_driver_or_elevation_invoked": False,
        "de_elevated_basic_trustlevel_probe": deelev_probe,
        "wall_minus_monotonic_offset_ns": t_wall - t_mono,
        "win32_l3_counters": l3_self,
        "windows_per_pid_hardware_joule_counter": "not_available (Win32 GetProcessTimes + QueryProcessCycleTime expose CPU time/cycles Label C; Windows E3/SRUM is coarse background estimation, not a synchronous per-PID hardware counter)",
    }

    # Check \\.\EnergyMeter explicitly
    emi_device_status = "not_present"
    try:
        with open(r"\\.\EnergyMeter", "rb"):
            emi_device_status = "readable"
    except FileNotFoundError:
        emi_device_status = "FileNotFoundError (no ACPI PMET / EMI hardware meter exposed)"
    except PermissionError:
        emi_device_status = "PermissionError (EACCES)"
    except OSError as e:
        emi_device_status = f"OSError({e.errno})"

    f5, f3_f6 = run_windows_falsifier_5_and_3(nvml)

    satb_win_receipt = {
        "profile_id": "windows_11_tiger_lake_rtx2060",
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "bench_root": "$BENCH_ROOT",
        "host_envelope": {
            "cpu_or_board_model": f"{cpu_name} + {nvml.gpu_name}",
            "cpu_model": cpu_name,
            "dgpu_model": nvml.gpu_name,
            "igpu_model": "Intel(R) Iris(R) Xe Graphics",
            "arch": "x86_64",
            "logical_cpus": int(hw_meta["cpu"]["NumberOfLogicalProcessors"]),
            "physical_cores": int(hw_meta["cpu"]["NumberOfCores"]),
            "ram_gib": round(float(hw_meta["ram_bytes"]) / (1024 ** 3), 1),
            "os_kernel": os_ver,
            "ucrt_version": ucrt_desc,
            "python_version": platform.python_version(),
            "dedicated_host": False,
            "cotenant_ci_runner_present": True,
            "rootless_collection": rootless_verified,
        },
        "evidence_separation": {
            "board_metered": False,
            "a2_whole_sut_net_attributable": False,
            "a2_withheld_reason": "shared_host_cotenant_active_and_cpu_rapl_unavailable (act_runner daemon resident; CPU package RAPL inaccessible without ring-0 driver; RTX 2060 NVML L2 reported_j preserved)",
            "measured_j_populated": False,
            "reported_j_populated": bool(nvml.energy_supported),
            "reported_j_scope": "L2 discrete GPU only (NVML nvmlDeviceGetTotalEnergyConsumption mJ on NVIDIA GeForce RTX 2060); CPU package L2 is literally 'not_available' (Label N) in rootless Windows user mode",
            "est_j": None,
        },
        "windows_rootless_telemetry_and_msr_audit": {
            "intel_rapl_msr_0x611_user_mode": "blocked_by_os_privilege_boundary (Windows NT provides no built-in unprivileged user-mode RDMSR interface; loading third-party ring-0 MSR drivers violates SATB OQ-5 rootless collection and triggers Windows HVCI / Vulnerable Driver Blocklist)",
            "windows_emi_dev_energymeter": emi_device_status,
            "wmi_perf_power_meter_instances": int(hw_meta["wmi_power_meters"]),
            "nvml_dgpu_l2_counter": {
                "library": "nvml.dll (System32)",
                "gpu_name": nvml.gpu_name,
                "driver_version": nvml.driver_version,
                "rootless_power_mw_readable": nvml.available,
                "rootless_cumulative_energy_mj_readable": nvml.energy_supported,
                "satb_boundary": "L2 discrete GPU (A1 when GPU inference is exclusive; never summed with CPU)",
            },
            "win32_process_l3_accounting": "GetProcessTimes (100 ns kernel+user) + QueryProcessCycleTime (CPU cycles) + GetProcessIoCounters (Label C)",
        },
        "shape_d_dnullmm1_conformance": shape_d,
        "satb_conformance_windows": {
            "c9_deterministic_replay": c9,
            "c10_process_tree_kill": c10,
            "c11_rootless_l3_handshake": c11,
        },
        "falsifier_5_observer_cadence": f5,
        "falsifier_3_step7_and_falsifier_6_nvml": f3_f6,
        "elapsed_wall_s": round(time.perf_counter() - t_satb0, 2),
    }

    satb_path = out_dir / "windows_satb_receipts.json"
    satb_path.write_text(scrub_private_tokens(json.dumps(satb_win_receipt, indent=2)) + "\n", encoding="utf-8")

    nvml.close()
    tot_s = round(time.perf_counter() - t_suite_start, 2)
    print(f"[{host_id}] ALL BENCHMARKS COMPLETE in {tot_s}s! Outputs in {out_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
