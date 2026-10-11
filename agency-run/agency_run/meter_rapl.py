"""Joule meter for the agent on Linux/Intel: RAPL package-0, idle-subtracted.

Backend for the jetson-hub run (PREREGISTRATION_v2_jetson.md). Same interface
as agency_run/meter.py (read() -> (energy_nj, cycles, instructions, t_ns),
joules(a, b)); the selection code is not changed. run2_jetson.py binds this
module as agency_run.meter before any agent module is imported, the same way
tests/test_guard.py binds its fake meter.

Energy: /sys/class/powercap/intel-rapl:0/energy_uj (package-0). The counter is
the processor's on-chip energy model/sensor, updated about every 1 ms. It is
package-level: it includes every process on the chip. Attribution to the
agent: one episode at a time, agent pinned to one core with taskset, and

    joules(a, b) = (E_b - E_a) - P_idle * (t_b - t_a)

where P_idle is the package power measured over the idle baseline taken just
before the current block (set_baseline()). Values are reported_j, never
measured_j. Below about 1 ms the counter is quantised: an interval may read 0
or one whole update; the idle-subtracted value of a short interval can be
negative. Wraparound: the raw counter wraps at max_energy_range_uj; read()
accumulates deltas modulo that range (one wrap at most between two reads; at
65 W a wrap takes over an hour).

Cycles: user-space core cycles of the calling thread from perf_event_open on
the cpu_core PMU (raw event 0x3c), which needs root on this box
(perf_event_paranoid = 4). If perf is unavailable the cycle field falls back
to thread CPU time x pinned frequency, and CYCLES_SOURCE says so.
"""
import ctypes, os, struct, time

LABEL = 'reported_j'
METER = 'Linux powercap intel-rapl:0 (package-0) energy_uj, idle-subtracted (P_idle x dt), agent pinned'
_BASE = '/sys/class/powercap/'
_fd = os.open(_BASE + 'intel-rapl:0/energy_uj', os.O_RDONLY)
_RANGE = int(open(_BASE + 'intel-rapl:0/max_energy_range_uj').read())
_SUB = {}
for _n in ('intel-rapl:0:0', 'intel-rapl:0:1', 'intel-rapl:1'):
    try:
        _nm = open(_BASE + _n + '/name').read().strip()
        _SUB[_nm] = (os.open(_BASE + _n + '/energy_uj', os.O_RDONLY), int(open(_BASE + _n + '/max_energy_range_uj').read()))
    except OSError:
        pass
_state = {'raw': None, 'acc': 0, 'sub_raw': {}, 'sub_acc': {}}
P_IDLE_W = 0.0                      # set per block by set_baseline()
PINNED_HZ = None
# Part B of the jetson addendum (amendment 1): MODE = 'cyc' makes read()/joules()
# return est_j = cycles x C_J_PER_CYCLE, C calibrated on RAPL over a long window.
MODE = 'rapl'
C_J_PER_CYCLE = None


def set_baseline(watts):
    global P_IDLE_W
    P_IDLE_W = float(watts)


def _raw():
    return int(os.pread(_fd, 32, 0))


def _energy_uj():
    r = _raw()
    if _state['raw'] is not None:
        d = r - _state['raw']
        if d < 0:
            d += _RANGE + 1
        _state['acc'] += d
    _state['raw'] = r
    return _state['acc']


# ---- cycles
_perf_fd = -1
CYCLES_SOURCE = 'thread_time_x_pinned_hz'
try:
    _libc = ctypes.CDLL(None, use_errno=True)
    _typ = int(open('/sys/bus/event_source/devices/cpu_core/type').read())
    _attr = bytearray(128)
    struct.pack_into('IIQ', _attr, 0, _typ, 128, 0x3c)
    struct.pack_into('Q', _attr, 40, (1 << 5) | (1 << 6))      # exclude_kernel, exclude_hv
    _ab = ctypes.create_string_buffer(bytes(_attr), 128)
    _perf_fd = _libc.syscall(298, _ab, 0, -1, -1, 0)            # perf_event_open, this thread
    if _perf_fd >= 0:
        CYCLES_SOURCE = 'perf cpu_core raw 0x3c user cycles, this thread'
except Exception:
    _perf_fd = -1


def _cycles():
    if _perf_fd >= 0:
        return struct.unpack('q', os.read(_perf_fd, 8))[0]
    hz = PINNED_HZ or 2.6e9
    return int(time.thread_time_ns() * hz / 1e9)


def read():
    """Return (energy_nj, cycles, 0, t_ns). rapl: accumulated package energy.
    cyc: cycles x C_J_PER_CYCLE (est_j, RAPL-calibrated)."""
    if MODE == 'cyc':
        c = _cycles()
        return (c * C_J_PER_CYCLE * 1e9, c, 0, time.perf_counter_ns())
    e = _energy_uj()
    return (e * 1000, _cycles(), 0, time.perf_counter_ns())


def joules(a, b):
    """rapl: idle-subtracted package joules (reported_j). cyc: est_j."""
    if MODE == 'cyc':
        return (b[0] - a[0]) / 1e9
    return (b[0] - a[0]) / 1e9 - P_IDLE_W * (b[3] - a[3]) / 1e9


def gross_joules(a, b):
    return (b[0] - a[0]) / 1e9


def read_all():
    """Package and subdomains (core, uncore if present, psys), accumulated uJ, plus t_ns."""
    out = {'package-0': _energy_uj()}
    for nm, (fd, rng) in _SUB.items():
        r = int(os.pread(fd, 32, 0)); last = _state['sub_raw'].get(nm)
        if last is not None:
            d = r - last
            if d < 0:
                d += rng + 1
            _state['sub_acc'][nm] = _state['sub_acc'].get(nm, 0) + d
        else:
            _state['sub_acc'][nm] = 0
        _state['sub_raw'][nm] = r
        out[nm] = _state['sub_acc'][nm]
    out['t_ns'] = time.perf_counter_ns()
    return out


def diff_all(a, b):
    dt = (b['t_ns'] - a['t_ns']) / 1e9
    return {'seconds': dt, **{f'{k}_j': (b[k] - a[k]) / 1e6 for k in a if k != 't_ns'}}
