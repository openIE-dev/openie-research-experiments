"""Joule meter for the agent process on Apple silicon.

Reads ri_energy_nj from proc_pid_rusage(RUSAGE_INFO_V6) for this process.
The kernel reports this figure from its energy model. It is an estimate made
by the operating system, so every value read here is labeled reported_j.
It is never measured_j. No privileges are needed.

Offsets of struct rusage_info_v6 were checked with offsetof() against the
macOS SDK header on the run machine: ri_instructions 248, ri_cycles 256,
ri_energy_nj 336, struct size 464.
"""
import ctypes
import os
import time

_lib = ctypes.CDLL('/usr/lib/libSystem.B.dylib')
_buf = ctypes.create_string_buffer(464)
_PID = os.getpid()
RUSAGE_INFO_V6 = 6
OFF_INSTR, OFF_CYCLES, OFF_ENERGY = 248, 256, 336
LABEL = 'reported_j'
METER = 'macOS proc_pid_rusage ri_energy_nj, per process, CPU, kernel energy model'


def read():
    """Return (energy_nj, cycles, instructions, t_ns).

    A 10 microsecond sleep forces a context switch first. The kernel folds
    pending energy into the counter at a context switch; without it the
    counter moves in coarse steps of several milliseconds.
    """
    time.sleep(1e-5)
    rc = _lib.proc_pid_rusage(_PID, RUSAGE_INFO_V6, _buf)
    if rc != 0:
        raise OSError('proc_pid_rusage failed')
    b = _buf.raw
    return (int.from_bytes(b[OFF_ENERGY:OFF_ENERGY + 8], 'little'),
            int.from_bytes(b[OFF_CYCLES:OFF_CYCLES + 8], 'little'),
            int.from_bytes(b[OFF_INSTR:OFF_INSTR + 8], 'little'),
            time.perf_counter_ns())


def joules(a, b):
    return (b[0] - a[0]) / 1e9
