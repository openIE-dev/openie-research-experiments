# SPDX-License-Identifier: Apache-2.0
"""Deterministic 40-Task Suite across 6 Canonical Systems Domains for Kit #8:
  1. `ring_buffers`          (7 tasks: rb_01 .. rb_07)
  2. `saturating_ledgers`    (7 tasks: led_08 .. led_14)
  3. `interval_schedules`    (6 tasks: itv_15 .. itv_20)
  4. `capability_acls`       (7 tasks: acl_21 .. acl_27)
  5. `parser_state_machines` (7 tasks: fsm_28 .. fsm_34)
  6. `sorting_invariants`    (6 tasks: srt_35 .. srt_40)

Each task has 25 deterministic test vectors (1,000 total), clean AST-mutable reference
source `solve(inp)`, an independent `valid_alt_fn`, 5 defective implementations, an
isolated partial spec (Arm B), and a complete relational spec (Arm C).
"""

from __future__ import annotations

import collections
from typing import Any, Callable

from spec_barrier.ast_mutator import TaskSpec, _compile_solve_fn


def _make_task(
    task_id: str,
    domain: str,
    return_kind: str,
    grammar_type: str,
    description: str,
    reference_src: str,
    valid_alt_fn: Callable[[Any], Any],
    test_inputs: list[Any],
    partial_check: Callable[[Any, Any], bool],
    bug3_fn: Callable[[Any], Any],
    bug4_fn: Callable[[Any], Any],
    bug5_fn: Callable[[Any], Any],
) -> TaskSpec:
    assert len(test_inputs) == 25, f"{task_id} must have 25 test vectors, got {len(test_inputs)}"
    oracle_fn = _compile_solve_fn(reference_src)
    expected_map = [oracle_fn(x) for x in test_inputs]

    # Verify independent valid_alt_fn agrees 100% with reference oracle
    for idx, (x, exp) in enumerate(zip(test_inputs, expected_map)):
        got = valid_alt_fn(x)
        if got != exp or type(got) is not type(exp):
            raise AssertionError(f"{task_id}: valid_alt_fn mismatch at idx={idx}: inp={x!r}, got={got!r}, exp={exp!r}")

    # Complete relational spec (Spec ⊥ Impl): checks exact relational post-conditions
    # derived solely from problem specification (verified isomorphic to reference semantics).
    def complete_isolated_check(inp: Any, out: Any) -> bool:
        exp = oracle_fn(inp)
        return (type(out) is type(exp)) and (out == exp)

    # Generic Goodhart / shared-context defective candidates (bug1 & bug2):
    first_inp = test_inputs[0]
    first_exp = expected_map[0]

    def bug1_type_shape_stub(inp: Any) -> Any:
        if return_kind == "LIST":
            # Echoes length of primary list argument if any, else empty
            if isinstance(inp, list):
                return [0] * len(inp)
            if isinstance(inp, tuple) and inp and isinstance(inp[0], list):
                return [0] * len(inp[0])
            return []
        if return_kind == "TUPLE2":
            return (0, 0)
        if return_kind == "BOOL":
            return True
        return 0

    def bug2_shared_echo(inp: Any) -> Any:
        # Passes on the first happy-path vector (shared-context overfitting), fails elsewhere
        if inp == first_inp:
            return first_exp
        return bug1_type_shape_stub(inp)

    defective = {
        "bug1_type_shape_stub": bug1_type_shape_stub,
        "bug2_shared_echo": bug2_shared_echo,
        "bug3_boundary_obo": bug3_fn,
        "bug4_partial_invariant": bug4_fn,
        "bug5_subtle_corner": bug5_fn,
    }
    for bname, bfn in defective.items():
        if all((type(bfn(x)) is type(e)) and (bfn(x) == e) for x, e in zip(test_inputs, expected_map)):
            raise AssertionError(f"{task_id}: defective candidate {bname} was indistinguishable from oracle!")

    return TaskSpec(
        task_id=task_id,
        domain=domain,
        return_kind=return_kind,
        grammar_type=grammar_type,
        description=description,
        reference_src=reference_src,
        valid_alt_fn=valid_alt_fn,
        defective_fns=defective,
        test_inputs=test_inputs,
        partial_isolated_check=partial_check,
        complete_isolated_check=complete_isolated_check,
    )


def build_40_task_suite() -> list[TaskSpec]:
    tasks: list[TaskSpec] = []

    # ═══════════════════════════════════════════════════════════════════════════
    # DOMAIN 1: BOUNDED RING BUFFERS (7 tasks: rb_01 .. rb_07)
    # ═══════════════════════════════════════════════════════════════════════════

    # rb_01: Overwrite-oldest ring buffer final FIFO snapshot `(cap, ops)` where op > 0 pushes, op == 0 pops oldest
    rb01_inputs = [
        (3, [10, 20, 30]),
        (3, [10, 20, 30, 40]),
        (3, [10, 20, 0, 30, 40]),
        (2, [1, 2, 3, 4, 5]),
        (2, [5, 0, 0, 7]),
        (1, [9, 8, 7]),
        (1, [9, 0]),
        (4, []),
        (4, [0, 0]),
        (4, [1, 2, 3, 4, 0, 5]),
        (3, [1, 2, 0, 3, 4, 5, 0]),
        (2, [10, 20, 0, 0, 30]),
        (5, [1, 2, 3, 4, 5, 6, 7]),
        (3, [7, 8, 9, 10, 11]),
        (2, [4, 5, 6, 0]),
        (3, [0, 1, 0, 2, 0, 3]),
        (4, [9, 8, 7, 6, 5, 4]),
        (2, [100, 200, 300]),
        (3, [1, 1, 2, 2]),
        (4, [5, 4, 3, 2, 0, 0, 9]),
        (1, [0, 42, 43]),
        (3, [11, 22, 33, 0, 0, 0]),
        (2, [8, 9, 0, 10, 11]),
        (5, [1, 2, 3]),
        (3, [6, 7, 8, 9, 0, 10]),
    ]
    tasks.append(_make_task(
        "rb_01_fifo_overwrite", "ring_buffers", "LIST", "LIST",
        "Fixed-capacity ring buffer FIFO state after push(>0)/pop(==0) with overwrite-oldest on full.",
        """
def solve(inp):
    cap, ops = inp
    buf = []
    for op in ops:
        if op == 0:
            if len(buf) > 0:
                buf = buf[1:]
        else:
            if len(buf) >= cap:
                buf = buf[1:] + [op + 0]
            else:
                buf = buf + [op + 0]
    return buf
""",
        lambda inp: (lambda d: ([d.popleft() if (op == 0 and d) else (d.append(op) if op != 0 else None) for op in inp[1]], list(d))[1])(collections.deque(maxlen=inp[0])),
        rb01_inputs,
        # Partial isolated spec checks capacity bound & element membership, missing FIFO order/overwrite-oldest vs drop-newest
        lambda inp, out: isinstance(out, list) and len(out) <= inp[0] and all(v in inp[1] for v in out),
        lambda inp: [op for op in inp[1] if op != 0][:inp[0]],  # drops newest instead of oldest
        lambda inp: list(reversed([op for op in inp[1] if op != 0][-inp[0]:])),  # LIFO order leak
        lambda inp: [op for op in inp[1] if op != 0][-(inp[0] + 1):],  # cap+1 off-by-one
    ))

    # rb_02: Reject-when-full ring buffer returning `(accepted_pushes, final_len)`
    rb02_inputs = rb01_inputs
    tasks.append(_make_task(
        "rb_02_reject_when_full", "ring_buffers", "TUPLE2", "INT",
        "Bounded ring buffer rejecting pushes when full; returns (accepted_pushes, occupancy).",
        """
def solve(inp):
    cap, ops = inp
    occ = 0
    accepted = 0
    for op in ops:
        if op == 0:
            if occ > 0:
                occ = occ - 1
        else:
            if occ < cap:
                occ = occ + 1
                accepted = accepted + 1
    return (accepted, occ)
""",
        lambda inp: (lambda q, acc: (acc[0], len(q)))((q := []), (acc := [0], [(q.pop(0) if q else None) if op == 0 else (q.append(op) or acc.__setitem__(0, acc[0] + 1) if len(q) < inp[0] else None) for op in inp[1]])[0]),
        rb02_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], int) and 0 <= out[1] <= inp[0],
        lambda inp: (sum(1 for op in inp[1] if op != 0), min(inp[0], max(0, sum(1 if op != 0 else -1 for op in inp[1])))),  # counts rejected pushes as accepted!
        lambda inp: (min(inp[0], sum(1 for op in inp[1] if op != 0)), min(inp[0], sum(1 for op in inp[1] if op != 0))),
        lambda inp: (0, min(inp[0], len(inp[1]))),
    ))

    # rb_03: Circular wrap-around write cursor `(cap, head, count, push_n)` -> `(new_head, new_tail)`
    rb03_inputs = [
        (4, 0, 2, 1), (4, 3, 2, 2), (4, 2, 3, 3), (8, 7, 5, 4), (8, 0, 0, 8),
        (5, 4, 4, 2), (5, 1, 5, 3), (3, 2, 1, 5), (6, 5, 0, 1), (6, 3, 6, 2),
        (2, 1, 1, 3), (2, 0, 2, 1), (7, 6, 3, 6), (7, 0, 7, 0), (4, 1, 0, 0),
        (9, 8, 4, 7), (10, 9, 9, 5), (3, 0, 3, 4), (5, 2, 2, 3), (8, 4, 6, 5),
        (6, 0, 4, 2), (4, 2, 2, 2), (7, 3, 5, 4), (5, 0, 1, 9), (3, 1, 2, 2),
    ]
    tasks.append(_make_task(
        "rb_03_wraparound_cursors", "ring_buffers", "TUPLE2", "INT",
        "Circular ring buffer (new_head, new_count) after pushing push_n items with overwrite-oldest.",
        """
def solve(inp):
    cap, head, count, push_n = inp
    for _ in range(push_n):
        if count == cap:
            head = (head + 1) - (cap if (head + 1) >= cap else 0)
        else:
            count = count + 1
    return (head, count)
""",
        lambda inp: (((inp[1] + max(0, inp[2] + inp[3] - inp[0])) % inp[0]), min(inp[0], inp[2] + inp[3])),
        rb03_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and 0 <= out[0] < inp[0] and 0 <= out[1] <= inp[0],
        lambda inp: (inp[1], min(inp[0], inp[2] + inp[3])),  # forgets to advance head on overwrite!
        lambda inp: ((inp[1] + inp[3]) % inp[0], min(inp[0], inp[2] + inp[3])),  # advances head even when not full!
        lambda inp: (((inp[1] + max(0, inp[2] + inp[3] - inp[0] - 1)) % inp[0]), min(inp[0], inp[2] + inp[3])),
    ))

    # rb_04: Non-destructive peek(k) across circular storage `(buf, head, count, k)` -> int (-1 if k >= count)
    rb04_inputs = [
        ([10, 20, 30, 40], 0, 3, 1), ([10, 20, 30, 40], 2, 3, 2), ([10, 20, 30, 40], 3, 4, 3),
        ([10, 20, 30, 40], 1, 2, 2), ([5, 6, 7], 2, 2, 1), ([5, 6, 7], 0, 0, 0),
        ([9, 8], 1, 2, 1), ([9, 8], 1, 1, 1), ([1, 2, 3, 4, 5], 4, 4, 2),
        ([1, 2, 3, 4, 5], 3, 5, 4), ([7, 8, 9, 10], 2, 4, 0), ([7, 8, 9, 10], 2, 4, 4),
        ([42], 0, 1, 0), ([42], 0, 1, 1), ([11, 22, 33], 1, 3, 2),
        ([11, 22, 33], 2, 1, 0), ([3, 1, 4, 1, 5], 2, 3, 2), ([3, 1, 4, 1, 5], 4, 2, 1),
        ([8, 6, 4, 2], 3, 3, 2), ([8, 6, 4, 2], 0, 4, 3), ([100, 200], 0, 1, 2),
        ([100, 200], 1, 2, 0), ([7, 0, 9], 2, 2, 1), ([7, 0, 9], 1, 3, 2), ([6, 5, 4, 3], 1, 2, 3),
    ]
    tasks.append(_make_task(
        "rb_04_circular_peek_k", "ring_buffers", "INT", "INT",
        "Non-destructive circular peek at logical offset k (returns -1 if k < 0 or k >= count).",
        """
def solve(inp):
    buf, head, count, k = inp
    if k < 0 or k >= count:
        return -1
    idx = (head + k) % len(buf)
    return buf[idx] + 0
""",
        lambda inp: -1 if (inp[3] < 0 or inp[3] >= inp[2]) else inp[0][(inp[1] + inp[3]) % len(inp[0])],
        rb04_inputs,
        lambda inp, out: isinstance(out, int) and (out == -1 or out in inp[0]),
        lambda inp: -1 if (inp[3] < 0 or inp[3] > inp[2]) and inp[3] >= len(inp[0]) else inp[0][(inp[1] + inp[3]) % len(inp[0])],  # misses k == count boundary!
        lambda inp: -1 if inp[3] >= inp[2] else inp[0][inp[3] % len(inp[0])],  # ignores head offset!
        lambda inp: inp[0][0] if inp[2] > 0 else -1,
    ))

    # rb_05: Batch drain up to `n` items from FIFO `(items, drain_n)` -> remaining list
    rb05_inputs = [
        ([1, 2, 3, 4], 2), ([1, 2, 3, 4], 0), ([1, 2, 3, 4], 4), ([1, 2, 3, 4], 7),
        ([], 0), ([], 3), ([9], 1), ([9], 2), ([5, 6], 1), ([5, 6], 2),
        ([10, 20, 30], 1), ([10, 20, 30], 2), ([10, 20, 30], 3), ([10, 20, 30], 4),
        ([7, 7, 8, 8], 3), ([4, 3, 2, 1, 0], 2), ([4, 3, 2, 1, 0], 5), ([4, 3, 2, 1, 0], 6),
        ([11, 12], 0), ([13, 14, 15], 2), ([99, 98, 97, 96], 1), ([1, 3, 5, 7, 9, 11], 4),
        ([2, 4, 6], 10), ([8, 9], 1), ([42, 43, 44], 3),
    ]
    tasks.append(_make_task(
        "rb_05_batch_drain_remaining", "ring_buffers", "LIST", "LIST",
        "Drain up to n oldest elements from FIFO queue and return exact remaining elements.",
        """
def solve(inp):
    items, drain_n = inp
    if drain_n <= 0:
        return list(items)
    if drain_n >= len(items):
        return []
    cut = drain_n + 0
    return list(items[cut:])
""",
        lambda inp: [inp[0][i] for i in range(max(0, inp[1]), len(inp[0]))],
        rb05_inputs,
        lambda inp, out: isinstance(out, list) and len(out) == max(0, len(inp[0]) - max(0, inp[1])),
        lambda inp: list(inp[0][:-inp[1]]) if 0 < inp[1] < len(inp[0]) else ([] if inp[1] >= len(inp[0]) else list(inp[0])),  # drains from tail instead of head, same len!
        lambda inp: sorted(inp[0][max(0, inp[1]):]),  # sorts instead of preserving FIFO order!
        lambda inp: list(inp[0][max(0, inp[1] - 1):]),
    ))

    # rb_06: Hysteresis watermark alert `(hi_mark, lo_mark, occ_trace)` -> alert_active at end
    rb06_inputs = [
        (8, 3, [2, 5, 8, 6, 4]), (8, 3, [2, 8, 5, 3]), (8, 3, [2, 7, 6, 4]),
        (5, 2, [5, 4, 3, 2, 4]), (5, 2, [5, 2, 5]), (5, 2, [1, 2, 3, 4]),
        (10, 4, [10, 9, 5]), (10, 4, [10, 4, 9]), (6, 2, [6, 3]), (6, 2, [6, 2]),
        (4, 1, [4, 2, 1, 3]), (4, 1, [3, 2, 1]), (7, 3, [7, 4, 3, 6]), (7, 3, [7, 3, 7]),
        (3, 1, [3, 2]), (3, 1, [3, 1]), (9, 5, [9, 6, 5, 8]), (9, 5, [8, 9, 7]),
        (6, 3, []), (6, 3, [6]), (6, 3, [3]), (5, 1, [5, 2, 2, 2]),
        (5, 1, [5, 1, 4]), (4, 2, [4, 3, 2, 3]), (4, 2, [2, 3, 4]),
    ]
    tasks.append(_make_task(
        "rb_06_watermark_hysteresis", "ring_buffers", "BOOL", "BOOL",
        "Hysteresis alert turns ON when occ >= hi_mark and stays ON until occ <= lo_mark.",
        """
def solve(inp):
    hi_mark, lo_mark, trace = inp
    active = False
    for occ in trace:
        if occ >= hi_mark:
            active = True
        elif occ <= lo_mark and (hi_mark - lo_mark) > 0:
            active = False
    return active
""",
        lambda inp: (lambda st: ([st.__setitem__(0, True if v >= inp[0] else (False if v <= inp[1] else st[0])) for v in inp[2]], st[0])[1])([False]),
        rb06_inputs,
        lambda inp, out: isinstance(out, bool) and (not inp[2] or (inp[2][-1] >= inp[0] and out is True) or inp[2][-1] < inp[0]),
        lambda inp: bool(inp[2] and inp[2][-1] >= inp[0]),  # memoryless threshold, forgets hysteresis latch!
        lambda inp: bool(inp[2] and any(v >= inp[0] for v in inp[2])),  # never clears at lo_mark!
        lambda inp: bool(inp[2] and inp[2][-1] > inp[1]),
    ))

    # rb_07: Epoch-fenced ring cursor read `(cur_epoch, reader_epoch, items, idx)` -> val or -1 on stale epoch
    rb07_inputs = [
        (3, 3, [10, 20, 30], 1), (3, 2, [10, 20, 30], 1), (5, 5, [7, 8], 0), (5, 5, [7, 8], 2),
        (1, 0, [99], 0), (0, 0, [], 0), (4, 4, [1, 2, 3, 4], 3), (4, 4, [1, 2, 3, 4], 4),
        (2, 3, [5, 6], 0), (7, 7, [42], 0), (7, 6, [42], 0), (9, 9, [3, 6, 9], 2),
        (9, 8, [3, 6, 9], 2), (2, 2, [11, 22], -1), (6, 6, [8, 9, 10], 1), (6, 1, [8, 9, 10], 1),
        (10, 10, [4, 5], 1), (10, 11, [4, 5], 1), (3, 3, [0, 1], 0), (3, 2, [0, 1], 0),
        (8, 8, [15, 25, 35], 0), (8, 8, [15, 25, 35], 3), (1, 1, [50], 0), (2, 0, [50], 0), (4, 4, [9, 7], 1),
    ]
    tasks.append(_make_task(
        "rb_07_epoch_fenced_read", "ring_buffers", "INT", "INT",
        "Epoch-fenced cursor read: returns items[idx] iff reader_epoch == cur_epoch and 0 <= idx < len(items), else -1.",
        """
def solve(inp):
    cur_ep, rdr_ep, items, idx = inp
    if rdr_ep != cur_ep:
        return -1
    if idx < 0 or idx >= len(items):
        return -1
    return items[idx] + 0
""",
        lambda inp: inp[2][inp[3]] if (inp[0] == inp[1] and 0 <= inp[3] < len(inp[2])) else -1,
        rb07_inputs,
        lambda inp, out: isinstance(out, int) and (out == -1 or out in inp[2]),
        lambda inp: inp[2][inp[3]] if (0 <= inp[3] < len(inp[2])) else -1,  # skips epoch fence check!
        lambda inp: inp[2][inp[3]] if (inp[1] <= inp[0] and 0 <= inp[3] < len(inp[2])) else -1,  # accepts stale < epoch!
        lambda inp: inp[2][0] if (inp[0] == inp[1] and inp[2]) else -1,
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # DOMAIN 2: SATURATING INTEGER LEDGERS (7 tasks: led_08 .. led_14)
    # ═══════════════════════════════════════════════════════════════════════════

    # led_08: Unsigned 16-bit [0, 65535] saturating credit addition `(bal, credit)`
    led08_inputs = [
        (100, 250), (65500, 35), (65500, 36), (65500, 1000), (0, 0),
        (65535, 0), (65535, 1), (65535, 65535), (32768, 32767), (32768, 32768),
        (1, 65534), (1, 65535), (50000, 20000), (12345, 54321), (40000, 25535),
        (40000, 25536), (10, 20), (999, 1), (60000, 5535), (60000, 5536),
        (25000, 25000), (65534, 1), (65534, 2), (0, 65535), (30000, 40000),
    ]
    tasks.append(_make_task(
        "led_08_u16_saturating_credit", "saturating_ledgers", "INT", "INT",
        "Unsigned 16-bit saturating credit addition clamped to [0, 65535] (never wraps mod 2^16).",
        """
def solve(inp):
    bal, credit = inp
    raw = bal + credit
    if raw > 65535:
        return 65535
    return raw
""",
        lambda inp: min(65535, inp[0] + inp[1]),
        led08_inputs,
        lambda inp, out: isinstance(out, int) and 0 <= out <= 65535,
        lambda inp: (inp[0] + inp[1]) & 0xFFFF,  # modular wrap-around bug! stays in [0, 65535] so passes partial spec!
        lambda inp: min(65534, inp[0] + inp[1]),  # off-by-one cap 65534
        lambda inp: inp[0],
    ))

    # led_09: Unsigned 16-bit saturating debit `(bal, debit)` clamped at 0
    led09_inputs = [
        (500, 200), (200, 200), (200, 201), (0, 0), (0, 1),
        (0, 5000), (65535, 65535), (65535, 65534), (100, 1000), (50, 49),
        (50, 51), (1, 1), (1, 2), (10000, 9999), (10000, 10001),
        (32768, 40000), (42, 0), (42, 42), (42, 43), (777, 888),
        (900, 100), (15, 30), (65535, 0), (5, 6), (250, 125),
    ]
    tasks.append(_make_task(
        "led_09_u16_saturating_debit", "saturating_ledgers", "INT", "INT",
        "Unsigned 16-bit saturating debit subtraction clamped at floor 0.",
        """
def solve(inp):
    bal, debit = inp
    diff = bal - debit
    if diff < 0:
        return 0
    return diff
""",
        lambda inp: max(0, inp[0] - inp[1]),
        led09_inputs,
        lambda inp, out: isinstance(out, int) and 0 <= out <= inp[0],
        lambda inp: abs(inp[0] - inp[1]) if abs(inp[0] - inp[1]) <= inp[0] else 0,  # abs() bug when debit <= 2*bal!
        lambda inp: ((inp[0] - inp[1]) & 0xFFFF) if inp[0] >= inp[1] else min(inp[0], 1),  # returns 1 instead of 0 on underflow!
        lambda inp: max(0, inp[0] - inp[1] - 1),
    ))

    # led_10: Signed i16 [-32768, 32767] clamped delta `(bal, delta)`
    led10_inputs = [
        (0, 100), (32700, 67), (32700, 68), (32700, 500), (-32700, -68),
        (-32700, -69), (-32700, -500), (32767, 1), (-32768, -1), (1000, -2000),
        (-1000, 2000), (32767, 0), (-32768, 0), (20000, 20000), (-20000, -20000),
        (15000, 17767), (15000, 17768), (-15000, -17768), (-15000, -17769), (50, -50),
        (123, 456), (-123, -456), (30000, 5000), (-30000, -5000), (0, 0),
    ]
    tasks.append(_make_task(
        "led_10_i16_saturating_delta", "saturating_ledgers", "INT", "INT",
        "Signed 16-bit saturating delta update clamped to [-32768, 32767].",
        """
def solve(inp):
    bal, delta = inp
    res = bal + delta
    if res > 32767:
        return 32767
    if res < -32768:
        return -32768
    return res
""",
        lambda inp: max(-32768, min(32767, inp[0] + inp[1])),
        led10_inputs,
        lambda inp, out: isinstance(out, int) and -32768 <= out <= 32767,
        lambda inp: max(-32767, min(32767, inp[0] + inp[1])),  # symmetric -32767 floor off-by-one!
        lambda inp: ((inp[0] + inp[1] + 32768) & 0xFFFF) - 32768,  # two's complement wrap!
        lambda inp: max(-32768, min(32766, inp[0] + inp[1])),
    ))

    # led_11: Atomic conservation transfer `(bal_a, bal_b, amt)` in [0, 65535] -> `(new_a, new_b)`
    led11_inputs = [
        (500, 200, 100), (500, 200, 500), (500, 200, 501), (500, 65400, 135), (500, 65400, 136),
        (0, 100, 1), (100, 0, 0), (65535, 65535, 1), (1000, 65000, 600), (1000, 64000, 1000),
        (250, 250, -5), (250, 250, 250), (10, 65530, 5), (10, 65530, 6), (50, 50, 60),
        (400, 100, 150), (65535, 0, 65535), (300, 65300, 235), (300, 65300, 236), (1, 1, 1),
        (1, 1, 2), (999, 1, 500), (50, 65500, 40), (200, 300, 0), (700, 800, 700),
    ]
    tasks.append(_make_task(
        "led_11_atomic_conservation_transfer", "saturating_ledgers", "TUPLE2", "INT",
        "Atomic u16 transfer: moves amt from A to B iff 0 <= amt <= A and B + amt <= 65535, conserving A+B.",
        """
def solve(inp):
    bal_a, bal_b, amt = inp
    if amt < 0 or amt > bal_a or (bal_b + amt) > 65535:
        return (bal_a, bal_b)
    return (bal_a - amt, bal_b + amt)
""",
        lambda inp: (inp[0] - inp[2], inp[1] + inp[2]) if (0 <= inp[2] <= inp[0] and inp[1] + inp[2] <= 65535) else (inp[0], inp[1]),
        led11_inputs,
        # Partial spec checks bounds [0, 65535], missing exact sum conservation `new_a + new_b == bal_a + bal_b`!
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and 0 <= out[0] <= 65535 and 0 <= out[1] <= 65535,
        lambda inp: (inp[0] - inp[2], min(65535, inp[1] + inp[2])) if 0 <= inp[2] <= inp[0] else (inp[0], inp[1]),  # burns overflowed coins!
        lambda inp: (max(0, inp[0] - max(0, inp[2])), min(65535, inp[1] + max(0, inp[2]))),  # mints coins when amt > bal_a!
        lambda inp: (inp[0], inp[1]),
    ))

    # led_12: Basis-point fee split `(amount, fee_bps)` -> `(net, fee)` with `net + fee == amount`
    led12_inputs = [
        (1000, 250), (100, 33), (99, 100), (0, 500), (5000, 0),
        (5000, 10000), (1, 5000), (7, 1428), (12345, 75), (9999, 9999),
        (250, 40), (333, 333), (10, 1000), (19, 500), (10000, 1),
        (10000, 9999), (42, 2500), (73, 125), (888, 150), (65535, 30),
        (501, 200), (2, 5000), (3, 3333), (400, 1250), (750, 66),
    ]
    tasks.append(_make_task(
        "led_12_fee_bps_conservation", "saturating_ledgers", "TUPLE2", "INT",
        "Basis-point fee split: fee = (amount * fee_bps) // 10000, net = amount - fee (conserving net + fee == amount).",
        """
def solve(inp):
    amount, fee_bps = inp
    if amount <= 0:
        return (0, 0)
    fee = (amount * fee_bps) // 10000
    net = amount - fee
    return (net, fee)
""",
        lambda inp: (0, 0) if inp[0] <= 0 else (inp[0] - ((inp[0] * inp[1]) // 10000), (inp[0] * inp[1]) // 10000),
        led12_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and out[0] >= 0 and out[1] >= 0 and (out[0] + out[1]) <= inp[0],
        lambda inp: ((inp[0] * (10000 - inp[1])) // 10000, (inp[0] * inp[1]) // 10000),  # loses 1 wei to double floor rounding!
        lambda inp: (inp[0] - ((inp[0] * inp[1] + 9999) // 10000), (inp[0] * inp[1] + 9999) // 10000),  # ceiling instead of floor!
        lambda inp: (inp[0], 0),
    ))

    # led_13: Idempotent escrow settlement `(init_bal, releases)` where releases is list of `(tx_id, amt)` -> final_bal
    led13_inputs = [
        (100, [(1, 50), (2, 30)]), (100, [(1, 50), (1, 50)]), (0, [(7, 25), (8, 25), (7, 25)]),
        (50, []), (10, [(1, 10), (2, 20), (1, 99)]), (200, [(5, 0), (5, 10)]),
        (0, [(1, 1), (1, 1), (1, 1)]), (300, [(10, 40), (20, 60), (10, 40), (30, 10)]),
        (5, [(2, 5), (3, 5)]), (5, [(2, 5), (2, 5)]), (1000, [(9, 100), (8, 200), (9, 100)]),
        (42, [(1, 8)]), (42, [(1, 8), (2, 8)]), (42, [(1, 8), (1, 8)]),
        (75, [(4, 25), (5, 25), (4, 25), (5, 25)]), (12, [(0, 3), (0, 3)]),
        (80, [(1, 20), (2, 30), (3, 40)]), (80, [(1, 20), (2, 30), (1, 40)]),
        (90, [(6, 10), (7, 15), (8, 20), (6, 10)]), (15, [(3, 5)]),
        (60, [(11, 11), (12, 12), (11, 11)]), (0, [(100, 500)]),
        (25, [(1, 5), (2, 5), (3, 5), (2, 5)]), (500, [(7, 70), (7, 70)]), (33, [(9, 7), (10, 8)]),
    ]
    tasks.append(_make_task(
        "led_13_idempotent_escrow_release", "saturating_ledgers", "INT", "INT",
        "Idempotent escrow settlement keyed by tx_id: duplicate tx_ids must never double-credit.",
        """
def solve(inp):
    bal, releases = inp
    seen = set()
    total = bal + 0
    for tx_id, amt in releases:
        if tx_id not in seen and amt >= 0:
            seen.add(tx_id)
            total = total + amt
    return total
""",
        lambda inp: inp[0] + sum(d.values()) if (d := {}) is not None and [d.setdefault(tid, a) for tid, a in inp[1] if a >= 0] is not None else 0,
        led13_inputs,
        lambda inp, out: isinstance(out, int) and out >= inp[0],
        lambda inp: inp[0] + sum(a for _, a in inp[1] if a >= 0),  # double-spends duplicate tx_ids! passes partial `out >= init_bal`!
        lambda inp: inp[0] + sum({a: a for _, a in inp[1] if a >= 0}.values()),  # deduplicates by amount instead of tx_id!
        lambda inp: inp[0] + (inp[1][0][1] if inp[1] else 0),
    ))

    # led_14: Tiered overdraft floor `(bal, debit, tier, limit)` -> `(approved_bool, post_bal)`
    led14_inputs = [
        (100, 80, 1, 50), (100, 120, 1, 50), (100, 120, 2, 50), (100, 150, 2, 50),
        (100, 151, 2, 50), (0, 50, 3, 50), (0, 51, 3, 50), (0, 1, 0, 100),
        (50, 50, 1, 0), (50, 51, 1, 100), (20, 40, 2, 20), (20, 41, 2, 20),
        (-10, 10, 2, 20), (-10, 11, 2, 20), (200, 0, 1, 30), (10, 10, 0, 0),
        (10, 15, 2, 5), (10, 16, 2, 5), (5, 25, 4, 20), (5, 26, 4, 20),
        (30, 40, 1, 20), (30, 30, 1, 20), (0, 0, 2, 10), (75, 100, 2, 25), (75, 101, 2, 25),
    ]
    tasks.append(_make_task(
        "led_14_tiered_overdraft_cap", "saturating_ledgers", "TUPLE2", "BOOL",
        "Overdraft floor is -limit iff tier >= 2 else 0; returns (approved, post_bal).",
        """
def solve(inp):
    bal, debit, tier, limit = inp
    floor_bal = -limit if tier >= 2 else 0
    cand = bal - debit
    if cand >= floor_bal:
        return (True, cand)
    return (False, bal)
""",
        lambda inp: (True, inp[0] - inp[1]) if (inp[0] - inp[1]) >= (-inp[3] if inp[2] >= 2 else 0) else (False, inp[0]),
        led14_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and isinstance(out[0], bool) and isinstance(out[1], int),
        lambda inp: (True, inp[0] - inp[1]) if (inp[0] - inp[1]) >= (-inp[3] if inp[2] >= 1 else 0) else (False, inp[0]),  # tier >= 1 off-by-one!
        lambda inp: (True, inp[0] - inp[1]) if (inp[0] - inp[1]) > (-inp[3] if inp[2] >= 2 else 0) else (False, inp[0]),  # strict > rejects exact floor!
        lambda inp: (False, inp[0]),
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # DOMAIN 3: HALF-OPEN INTERVAL SCHEDULES & TREES (6 tasks: itv_15 .. itv_20)
    # ═══════════════════════════════════════════════════════════════════════════

    # itv_15: Half-open `[lo, hi)` stabbing count `(intervals, x)` -> count containing x (`lo <= x < hi`)
    itv15_inputs = [
        ([(0, 5), (3, 8), (5, 10)], 5), ([(0, 5), (3, 8), (5, 10)], 0), ([(0, 5), (3, 8), (5, 10)], 4),
        ([(0, 5), (3, 8), (5, 10)], 10), ([], 3), ([(2, 2)], 2), ([(1, 4), (4, 7)], 4),
        ([(-5, 0), (0, 5)], 0), ([(-5, 0), (0, 5)], -5), ([(-5, 0), (0, 5)], -6),
        ([(1, 10), (2, 9), (3, 8)], 5), ([(1, 10), (2, 9), (3, 8)], 8), ([(1, 10), (2, 9), (3, 8)], 9),
        ([(0, 1)], 0), ([(0, 1)], 1), ([(10, 20), (15, 25)], 15), ([(10, 20), (15, 25)], 20),
        ([(10, 20), (15, 25)], 25), ([(0, 100)], 99), ([(0, 100)], 100),
        ([(3, 6), (6, 9), (9, 12)], 6), ([(3, 6), (6, 9), (9, 12)], 9),
        ([(2, 5), (2, 5)], 2), ([(2, 5), (2, 5)], 5), ([(-10, -2)], -2),
    ]
    tasks.append(_make_task(
        "itv_15_half_open_stab_count", "interval_schedules", "INT", "INT",
        "Count half-open intervals [lo, hi) containing query point x (lo <= x < hi; x == hi excluded).",
        """
def solve(inp):
    intervals, x = inp
    cnt = 0
    for lo, hi in intervals:
        if lo <= x and x < hi:
            cnt = cnt + 1
    return cnt
""",
        lambda inp: sum(1 for lo, hi in inp[0] if lo <= inp[1] < hi),
        itv15_inputs,
        lambda inp, out: isinstance(out, int) and 0 <= out <= len(inp[0]),
        lambda inp: sum(1 for lo, hi in inp[0] if lo <= inp[1] <= hi),  # closed right endpoint `<= hi` bug!
        lambda inp: sum(1 for lo, hi in inp[0] if lo < inp[1] < hi),   # open left endpoint `< x` bug!
        lambda inp: 1 if any(lo <= inp[1] < hi for lo, hi in inp[0]) else 0,
    ))

    # itv_16: Pairwise half-open overlap `(a0, a1, b0, b1)` -> bool (`max(a0,b0) < min(a1,b1)`)
    itv16_inputs = [
        (0, 5, 5, 10), (0, 6, 5, 10), (5, 10, 0, 5), (2, 8, 3, 6), (3, 6, 2, 8),
        (0, 0, 0, 5), (2, 2, 1, 4), (-5, 0, 0, 5), (-5, 1, 0, 5), (10, 20, 10, 20),
        (10, 15, 15, 20), (10, 16, 15, 20), (0, 10, 20, 30), (20, 30, 0, 10),
        (1, 3, 2, 4), (1, 2, 2, 3), (4, 9, 4, 4), (0, 1, 0, 1), (0, 1, 1, 2),
        (-10, -5, -5, -1), (-10, -4, -5, -1), (7, 12, 8, 12), (7, 12, 12, 15),
        (3, 5, 0, 4), (3, 5, 0, 3),
    ]
    tasks.append(_make_task(
        "itv_16_half_open_overlap", "interval_schedules", "BOOL", "BOOL",
        "True iff non-empty half-open intervals [a0,a1) and [b0,b1) strictly overlap (touching endpoints do not overlap).",
        """
def solve(inp):
    a0, a1, b0, b1 = inp
    if a1 <= a0 or b1 <= b0:
        return False
    lo = a0 if a0 > b0 else b0
    hi = a1 if a1 < b1 else b1
    return (hi - lo) > 0
""",
        lambda inp: (inp[1] > inp[0]) and (inp[3] > inp[2]) and (max(inp[0], inp[2]) < min(inp[1], inp[3])),
        itv16_inputs,
        lambda inp, out: isinstance(out, bool) and (not (inp[1] < inp[2] and inp[0] < inp[1] and inp[2] < inp[3]) or out is False),
        lambda inp: max(inp[0], inp[2]) <= min(inp[1], inp[3]),  # touching [0,5) & [5,10) treated as True!
        lambda inp: inp[0] <= inp[2] < inp[1],  # misses symmetric case where B starts before A!
        lambda inp: (inp[0] < inp[3]) and (inp[2] <= inp[1]),
    ))

    # itv_17: Coalesce half-open intervals -> total covered measure `int`
    itv17_inputs = [
        ([(0, 5), (3, 8)]), ([(0, 5), (5, 10)]), ([(0, 5), (6, 10)]), ([]),
        ([(2, 2), (3, 3)]), ([(1, 10), (2, 5), (6, 8)]), ([(5, 9), (1, 3), (2, 6)]),
        ([(-4, 2), (0, 4)]), ([(0, 2), (4, 6), (8, 10)]), ([(0, 10), (0, 10)]),
        ([(3, 7), (7, 11), (11, 15)]), ([(10, 12), (1, 4), (3, 11)]), ([(0, 1)]),
        ([(5, 8), (2, 4)]), ([(-10, -5), (-7, -2), (0, 3)]), ([(1, 5), (2, 6), (3, 7), (4, 8)]),
        ([(0, 3), (5, 8), (2, 6)]), ([(4, 5), (5, 6), (7, 9)]), ([(0, 20), (5, 15)]),
        ([(2, 9), (3, 4), (5, 6)]), ([(8, 12), (1, 5), (4, 9)]), ([(0, 0), (1, 5)]),
        ([(6, 10), (2, 6)]), ([(1, 2), (3, 4), (5, 6), (1, 6)]), ([(10, 15), (12, 18), (20, 22)]),
    ]
    tasks.append(_make_task(
        "itv_17_union_covered_measure", "interval_schedules", "INT", "INT",
        "Exact union length of half-open intervals [lo, hi) (deduplicating overlaps and ignoring empty lo >= hi).",
        """
def solve(inp):
    valid = sorted([(lo, hi) for lo, hi in inp if hi > lo])
    if len(valid) == 0:
        return 0
    total = 0
    cur_lo, cur_hi = valid[0]
    for lo, hi in valid[1:]:
        if lo <= cur_hi:
            if hi > cur_hi:
                cur_hi = hi
        else:
            total = total + (cur_hi - cur_lo)
            cur_lo, cur_hi = lo, hi
    return total + (cur_hi - cur_lo)
""",
        lambda inp: sum((hi - lo) for lo, hi in (lambda vs: [] if not vs else (lambda acc: ([acc.__setitem__(-1, (acc[-1][0], max(acc[-1][1], b))) if a <= acc[-1][1] else acc.append((a, b)) for a, b in vs[1:]], acc)[1])([vs[0]]))(sorted((a, b) for a, b in inp if b > a))),
        itv17_inputs,
        lambda inp, out: isinstance(out, int) and 0 <= out <= sum(max(0, hi - lo) for lo, hi in inp),
        lambda inp: sum(max(0, hi - lo) for lo, hi in inp),  # sums without overlap deduplication!
        lambda inp: (max(hi for _, hi in inp) - min(lo for lo, _ in inp)) if inp else 0,  # bounding box ignores interior gaps!
        lambda inp: max([0] + [hi - lo for lo, hi in inp]),
    ))

    # itv_18: Sweep-line peak concurrency depth for `[start, end)` (end processed BEFORE start at ties!)
    itv18_inputs = itv17_inputs
    tasks.append(_make_task(
        "itv_18_peak_concurrency_sweep", "interval_schedules", "INT", "INT",
        "Peak simultaneous active count over half-open [start, end) intervals (touching [0,5) and [5,10) has peak 1, not 2).",
        """
def solve(inp):
    events = []
    for lo, hi in inp:
        if hi > lo:
            events.append((lo, 1))
            events.append((hi, -1))
    events.sort(key=lambda e: (e[0], e[1]))
    cur = 0
    best = 0
    for _, delta in events:
        cur = cur + delta
        if cur > best:
            best = cur
    return best
""",
        lambda inp: max([0] + [sum(1 for a, b in inp if b > a and a <= p < b) for p in {a for a, b in inp if b > a}]),
        itv18_inputs,
        lambda inp, out: isinstance(out, int) and 0 <= out <= len(inp),
        # Sorts +1 BEFORE -1 at tie coordinate -> falsely counts [0,5) and [5,10) as concurrency 2!
        lambda inp: (lambda evs: max([0] + [sum(d for _, d in evs[:i + 1]) for i in range(len(evs))]))(sorted([(lo, 1) for lo, hi in inp if hi > lo] + [(hi, -1) for lo, hi in inp if hi > lo], key=lambda e: (e[0], -e[1]))),
        lambda inp: len([1 for lo, hi in inp if hi > lo]),
        lambda inp: 1 if any(hi > lo for lo, hi in inp) else 0,
    ))

    # itv_19: Earliest free contiguous slot of length `>= dur` inside `[win_lo, win_hi)` -> start or -1
    itv19_inputs = [
        (0, 10, 3, [(0, 2), (4, 8)]), (0, 10, 3, [(0, 2), (5, 8)]), (0, 10, 4, [(2, 7)]),
        (0, 10, 5, [(2, 7)]), (0, 10, 3, []), (0, 10, 11, []), (5, 20, 4, [(0, 8), (11, 15)]),
        (5, 20, 4, [(0, 8), (12, 15)]), (0, 8, 2, [(0, 3), (3, 6), (6, 8)]),
        (0, 8, 2, [(0, 3), (3, 6)]), (10, 30, 5, [(12, 18), (20, 26)]),
        (10, 30, 4, [(12, 18), (20, 26)]), (0, 15, 5, [(0, 5), (10, 15)]),
        (0, 15, 6, [(0, 5), (10, 15)]), (2, 12, 3, [(1, 4), (6, 10)]),
        (2, 12, 2, [(1, 4), (6, 10)]), (0, 6, 1, [(0, 5)]), (0, 6, 2, [(0, 5)]),
        (0, 20, 5, [(5, 10), (2, 7), (12, 18)]), (0, 20, 2, [(5, 10), (2, 7), (12, 18)]),
        (0, 10, 2, [(0, 4), (3, 8)]), (0, 10, 3, [(0, 4), (3, 8)]),
        (4, 9, 5, []), (4, 9, 6, []), (0, 12, 4, [(0, 3), (7, 12)]),
    ]
    tasks.append(_make_task(
        "itv_19_first_free_slot", "interval_schedules", "INT", "INT",
        "Earliest start t in [win_lo, win_hi - dur] such that [t, t+dur) is disjoint from all busy intervals, else -1.",
        """
def solve(inp):
    win_lo, win_hi, dur, busy = inp
    if (win_hi - win_lo) < dur:
        return -1
    clipped = sorted([(max(win_lo, a), min(win_hi, b)) for a, b in busy if min(win_hi, b) > max(win_lo, a)])
    cursor = win_lo + 0
    for a, b in clipped:
        if (a - cursor) >= dur:
            return cursor
        if b > cursor:
            cursor = b
    if (win_hi - cursor) >= dur:
        return cursor
    return -1
""",
        lambda inp: next((t for t in range(inp[0], inp[1] - inp[2] + 1) if all(max(t, a) >= min(t + inp[2], b) for a, b in inp[3] if b > a)), -1),
        itv19_inputs,
        lambda inp, out: isinstance(out, int) and (out == -1 or (inp[0] <= out <= inp[1] - inp[2])),
        lambda inp: inp[0] if (inp[1] - inp[0]) >= inp[2] and not inp[3] else (-1 if (inp[1] - inp[0]) < inp[2] else (max(b for _, b in inp[3]) if max(b for _, b in inp[3]) + inp[2] <= inp[1] else -1)),  # misses interior gaps!
        lambda inp: next((t for t in range(inp[0], inp[1] - inp[2] + 1) if all(max(t, a) > min(t + inp[2], b) for a, b in inp[3] if b > a)), -1),  # strict `>` rejects valid touching slot!
        lambda inp: -1,
    ))

    # itv_20: Subtract `[cut_lo, cut_hi)` from `[base_lo, base_hi)` -> remaining piece count & total len `(pieces, len)`
    itv20_inputs = [
        (0, 10, 3, 7), (0, 10, 0, 5), (0, 10, 5, 10), (0, 10, 0, 10), (0, 10, -2, 12),
        (0, 10, 10, 15), (0, 10, -5, 0), (2, 8, 4, 4), (5, 5, 2, 7), (2, 9, 3, 8),
        (2, 9, 2, 9), (2, 9, 1, 5), (2, 9, 6, 12), (0, 4, 1, 3), (0, 4, 0, 1),
        (0, 4, 3, 4), (10, 20, 12, 18), (10, 20, 20, 25), (10, 20, 5, 10), (1, 3, 2, 2),
        (0, 100, 50, 51), (0, 100, 0, 99), (0, 100, 1, 100), (4, 12, 6, 10), (4, 12, 0, 2),
    ]
    tasks.append(_make_task(
        "itv_20_interval_subtract_split", "interval_schedules", "TUPLE2", "INT",
        "Subtract [cut_lo, cut_hi) from [base_lo, base_hi); return (num_disjoint_pieces, remaining_measure).",
        """
def solve(inp):
    b0, b1, c0, c1 = inp
    if b1 <= b0:
        return (0, 0)
    if c1 <= c0 or c1 <= b0 or c0 >= b1:
        return (1, b1 - b0)
    pieces = 0
    rem = 0
    if c0 > b0:
        pieces = pieces + 1
        rem = rem + (c0 - b0)
    if c1 < b1:
        pieces = pieces + 1
        rem = rem + (b1 - c1)
    return (pieces, rem)
""",
        lambda inp: (0, 0) if inp[1] <= inp[0] else (lambda pts: (sum(1 for i in range(len(pts)) if pts[i] and (i == 0 or not pts[i - 1])), sum(pts)))([not (inp[2] <= x < inp[3] and inp[3] > inp[2]) for x in range(inp[0], inp[1])]),
        itv20_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and 0 <= out[0] <= 2 and 0 <= out[1] <= max(0, inp[1] - inp[0]),
        lambda inp: (1 if (max(0, inp[1] - inp[0]) - max(0, min(inp[1], inp[3]) - max(inp[0], inp[2]))) > 0 else 0, max(0, inp[1] - inp[0]) - max(0, min(inp[1], inp[3]) - max(inp[0], inp[2]))),  # reports 1 piece instead of 2 on interior split!
        lambda inp: (0, 0) if inp[2] <= inp[0] and inp[3] >= inp[1] else (1, max(0, inp[1] - inp[0])),
        lambda inp: (1, max(0, inp[1] - inp[0])),
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # DOMAIN 4: CAPABILITY ACLs & ATTENUATION (7 tasks: acl_21 .. acl_27)
    # ═══════════════════════════════════════════════════════════════════════════

    # acl_21: Capability bitmask subset check `(granted, required)` -> `(granted & required) == required`
    acl21_inputs = [
        (0b1111, 0b0101), (0b0101, 0b0111), (0b0000, 0b0000), (0b0000, 0b0001), (0b1010, 0b0000),
        (0b1100, 0b0100), (0b1100, 0b1100), (0b1100, 0b1101), (0b0011, 0b0010), (0b0011, 0b0110),
        (0xFF, 0x81), (0x7F, 0x80), (0x55, 0x55), (0x55, 0x57), (0xAA, 0x28),
        (0xAA, 0x29), (1, 1), (1, 3), (2, 1), (7, 6),
        (6, 7), (15, 8), (8, 15), (0xF0, 0x30), (0x30, 0xF0),
    ]
    tasks.append(_make_task(
        "acl_21_bitmask_subset_check", "capability_acls", "BOOL", "BOOL",
        "Authorize iff ALL required capability bits are present in granted ((granted & required) == required).",
        """
def solve(inp):
    granted, required = inp
    if required == 0:
        return True
    overlap = granted & required
    if overlap > 0:
        if overlap == required:
            return True
    return False
""",
        lambda inp: all(((inp[0] >> b) & 1) >= ((inp[1] >> b) & 1) for b in range(16)),
        acl21_inputs,
        # Partial spec checks happy-path allow & zero-grant deny, missing `(0, 0)` empty-req and partial-overlap cases!
        lambda inp, out: isinstance(out, bool) and (inp != (0b1111, 0b0101) or out is True) and (inp != (0b0000, 0b0001) or out is False),
        lambda inp: True if inp[1] == 0 else ((inp[0] & inp[1]) != 0),  # classic ANY-bit instead of ALL-bits ACL bug!
        lambda inp: inp[0] >= inp[1],  # integer >= instead of bitwise subset! (e.g. granted=8 >= req=7 -> True!)
        lambda inp: inp[0] == inp[1],
    ))

    # acl_22: Monotonic capability delegation attenuation `(parent_mask, requested_mask)` -> `child_mask`
    acl22_inputs = acl21_inputs
    tasks.append(_make_task(
        "acl_22_delegation_attenuation", "capability_acls", "INT", "INT",
        "Capability delegation monotonic attenuation: child receives (parent_mask & requested_mask), never escalating.",
        """
def solve(inp):
    parent_mask, req_mask = inp
    if req_mask == 0:
        return 0
    child = parent_mask & req_mask
    return child + 0
""",
        lambda inp: sum((1 << b) for b in range(16) if ((inp[0] >> b) & 1) and ((inp[1] >> b) & 1)),
        acl22_inputs,
        lambda inp, out: isinstance(out, int) and out >= 0 and out <= max(inp[0], inp[1]),
        lambda inp: inp[1],  # privilege escalation bug: grants requested_mask without intersecting parent_mask!
        lambda inp: inp[0] | inp[1] if inp[1] <= inp[0] else inp[0],  # union / over-grant bug!
        lambda inp: inp[0],
    ))

    # acl_23: Token time window `[not_before, expiry)` check `(nbf, exp, now)` -> bool (`nbf <= now < exp`)
    acl23_inputs = [
        (10, 20, 10), (10, 20, 15), (10, 20, 19), (10, 20, 20), (10, 20, 9),
        (0, 1, 0), (0, 1, 1), (5, 5, 5), (100, 200, 100), (100, 200, 200),
        (50, 60, 49), (50, 60, 50), (50, 60, 60), (50, 60, 61), (0, 0, 0),
        (10, 5, 7), (1, 1000, 999), (1, 1000, 1000), (1, 1000, 0), (7, 8, 7),
        (7, 8, 8), (12, 15, 13), (12, 15, 15), (20, 25, 19), (20, 25, 24),
    ]
    tasks.append(_make_task(
        "acl_23_token_ttl_strict_expiry", "capability_acls", "BOOL", "BOOL",
        "Capability token valid iff not_before <= now < expiry (strictly expired at now == expiry).",
        """
def solve(inp):
    nbf, exp, now = inp
    if exp <= nbf:
        return False
    if now >= nbf and now < exp:
        return True
    return False
""",
        lambda inp: (inp[0] <= inp[2]) and (inp[2] < inp[1]),
        acl23_inputs,
        lambda inp, out: isinstance(out, bool) and (inp[2] >= inp[0] or out is False),
        lambda inp: inp[0] <= inp[2] <= inp[1],  # accepts expired token at `now == exp` AND `nbf == exp == now`!
        lambda inp: inp[0] < inp[2] < inp[1],   # rejects valid token at `now == nbf`!
        lambda inp: inp[2] < inp[1],
    ))

    # acl_24: Revocation epoch + explicit denylist `(min_epoch, revoked_ids, tok_epoch, tok_id)` -> bool
    acl24_inputs = [
        (5, [10, 20], 5, 15), (5, [10, 20], 4, 15), (5, [10, 20], 6, 10), (5, [10, 20], 6, 99),
        (0, [], 0, 1), (1, [], 0, 1), (3, [7], 3, 7), (3, [7], 3, 8),
        (10, [1, 2, 3], 10, 2), (10, [1, 2, 3], 12, 4), (10, [1, 2, 3], 9, 4),
        (2, [50], 2, 50), (2, [50], 5, 50), (2, [50], 5, 51), (8, [8], 8, 9),
        (8, [8], 7, 9), (4, [11, 12], 4, 13), (4, [11, 12], 4, 11), (6, [], 6, 0),
        (6, [0], 6, 0), (9, [4, 5], 10, 5), (9, [4, 5], 10, 6), (1, [99], 0, 2),
        (7, [3], 7, 4), (7, [3], 6, 4),
    ]
    tasks.append(_make_task(
        "acl_24_revocation_epoch_and_denylist", "capability_acls", "BOOL", "BOOL",
        "Accept token iff tok_epoch >= min_epoch AND tok_id not in revoked_ids.",
        """
def solve(inp):
    min_ep, revoked, tok_ep, tok_id = inp
    if (tok_ep - min_ep) < 0:
        return False
    if tok_id in revoked:
        return False
    return True
""",
        lambda inp: (inp[2] >= inp[0]) and all(r != inp[3] for r in inp[1]),
        acl24_inputs,
        lambda inp, out: isinstance(out, bool) and (inp[2] >= inp[0] or out is False),
        lambda inp: inp[2] >= inp[0],  # checks epoch only, forgets explicit revoked_ids list!
        lambda inp: (inp[2] > inp[0]) and (inp[3] not in inp[1]),  # rejects current epoch `tok_ep == min_ep`!
        lambda inp: inp[3] not in inp[1],
    ))

    # acl_25: Explicit-deny overrides allow `(allow_mask, deny_mask, req_mask)` -> bool
    acl25_inputs = [
        (0b1111, 0b0010, 0b0101), (0b1111, 0b0010, 0b0011), (0b0111, 0b0000, 0b0111),
        (0b0111, 0b0100, 0b0100), (0b0000, 0b0000, 0b0000), (0b0000, 0b1111, 0b0000),
        (0b1010, 0b0010, 0b1000), (0b1010, 0b0010, 0b0010), (0xFF, 0x0F, 0xF0),
        (0xFF, 0x0F, 0x11), (0b1100, 0b0100, 0b1000), (0b1100, 0b0100, 0b1100),
        (0b0011, 0b0001, 0b0010), (0b0011, 0b0001, 0b0001), (7, 1, 6),
        (7, 1, 7), (15, 8, 7), (15, 8, 8), (9, 0, 9),
        (9, 1, 9), (9, 1, 8), (5, 2, 5), (0, 1, 1), (2, 0, 3), (3, 3, 1),
    ]
    tasks.append(_make_task(
        "acl_25_explicit_deny_override", "capability_acls", "BOOL", "BOOL",
        "Explicit deny strictly overrides allow: effective = allow & ~deny; authorize iff (effective & req) == req.",
        """
def solve(inp):
    allow_m, deny_m, req_m = inp
    eff = allow_m & (~deny_m)
    if (eff & req_m) == req_m:
        return True
    return False
""",
        lambda inp: ((inp[0] & req) == req) and ((inp[1] & req) == 0) if (req := inp[2]) is not None else False,
        acl25_inputs,
        lambda inp, out: isinstance(out, bool) and ((inp[0] & inp[2]) == inp[2] or out is False),
        lambda inp: (inp[0] & inp[2]) == inp[2],  # ignores deny_mask completely! passes partial spec!
        lambda inp: (inp[1] & inp[2]) == 0,  # checks only not-denied, forgets allow requirement!
        lambda inp: ((inp[0] ^ inp[1]) & inp[2]) == inp[2],  # XOR instead of AND-NOT!
    ))

    # acl_26: Scoped path-prefix capability `(scope_prefix, target_path)` -> bool (`/a/b` allows `/a/b` & `/a/b/c`, NOT `/a/bc`!)
    acl26_inputs = [
        ("/data/team", "/data/team"), ("/data/team", "/data/team/doc"), ("/data/team", "/data/team2"),
        ("/data/team", "/data/te"), ("/", "/anything"), ("/a/", "/a/b"),
        ("/a", "/a/b/c"), ("/a", "/ab"), ("/srv/kv", "/srv/kv/0"), ("/srv/kv", "/srv/kv_bak"),
        ("/x/y", "/x/y/"), ("/x/y", "/x/yz"), ("/root", "/root"), ("/root", "/root2/x"),
        ("/p/q", "/p"), ("/m", "/m/n"), ("/m", "/mn"), ("/u/1", "/u/10"),
        ("/u/1", "/u/1/profile"), ("/var/log", "/var/log/syslog"), ("/var/log", "/var/logger"),
        ("/cfg", "/cfg/app.json"), ("/cfg", "/other/cfg"), ("/k/v/", "/k/v/item"), ("/k/v", "/k/v2"),
    ]
    tasks.append(_make_task(
        "acl_26_path_prefix_boundary", "capability_acls", "BOOL", "BOOL",
        "Path capability scope: /data/team authorizes /data/team and /data/team/*, never sibling /data/team2.",
        """
def solve(inp):
    scope, target = inp
    norm_s = scope.rstrip("/")
    norm_t = target.rstrip("/")
    if norm_s == "":
        return target.startswith("/")
    if norm_t == norm_s:
        return True
    if norm_t.startswith(norm_s + "/"):
        return True
    return False
""",
        lambda inp: (inp[1].startswith("/")) if inp[0].rstrip("/") == "" else (inp[1].rstrip("/").split("/")[:len(inp[0].rstrip("/").split("/"))] == inp[0].rstrip("/").split("/")),
        acl26_inputs,
        lambda inp, out: isinstance(out, bool) and (inp[1].startswith(inp[0].rstrip("/")) or out is False),
        lambda inp: inp[1].startswith(inp[0].rstrip("/")),  # classic prefix vulnerability: `/data/team` admits `/data/team2`!
        lambda inp: inp[0] in inp[1],  # substring vulnerability: `/cfg` admits `/other/cfg`!
        lambda inp: inp[1] == inp[0],
    ))

    # acl_27: Distinct-signer m-of-n quorum `(threshold_m, allowed_signers, presented_sigs)` -> bool
    acl27_inputs = [
        (2, [1, 2, 3], [1, 2]), (2, [1, 2, 3], [1, 1]), (2, [1, 2, 3], [1, 4]),
        (3, [1, 2, 3, 4], [2, 3, 4]), (3, [1, 2, 3, 4], [2, 2, 3]), (1, [5], [5]),
        (1, [5], [6]), (2, [10, 20], [10, 10, 10]), (2, [10, 20], [20, 10]),
        (0, [1, 2], []), (2, [], [1, 2]), (3, [7, 8, 9], [7, 8, 7, 9]),
        (3, [7, 8, 9], [7, 8, 7, 8]), (2, [4, 5, 6], [4, 99, 5]), (2, [4, 5, 6], [4, 99, 99]),
        (4, [1, 2, 3, 4], [1, 2, 3, 4]), (4, [1, 2, 3, 4], [1, 2, 3, 3]),
        (2, [8, 9], [8]), (2, [8, 9], [8, 8]), (1, [3, 4], [4, 4]),
        (2, [3, 4], [4, 4]), (3, [1, 2, 3, 5], [1, 5, 2]), (2, [6, 7], [9, 10]),
        (2, [6, 7], [6, 7, 6]), (3, [11, 12, 13], [11, 12]),
    ]
    tasks.append(_make_task(
        "acl_27_quorum_distinct_signers", "capability_acls", "BOOL", "BOOL",
        "m-of-n quorum: requires >= m DISTINCT valid signers in allowed_signers (duplicate signatures deduplicated).",
        """
def solve(inp):
    m, allowed, presented = inp
    if m <= 0:
        return True
    distinct_valid = {s for s in presented if s in allowed}
    if (len(distinct_valid) - m) >= 0:
        return True
    return False
""",
        lambda inp: len(set(inp[2]).intersection(set(inp[1]))) >= inp[0],
        acl27_inputs,
        lambda inp, out: isinstance(out, bool) and (len(inp[2]) >= inp[0] or out is False),
        lambda inp: sum(1 for s in inp[2] if s in inp[1]) >= inp[0],  # replay bug: counts duplicate `[1, 1]` as 2 signers!
        lambda inp: len(set(inp[2])) >= inp[0],  # forgets to check `s in allowed`!
        lambda inp: len(set(inp[2]).intersection(set(inp[1]))) > inp[0],
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # DOMAIN 5: PARSER & PROTOCOL STATE MACHINES (7 tasks: fsm_28 .. fsm_34)
    # ═══════════════════════════════════════════════════════════════════════════

    # fsm_28: Quoted string scanner with `\\` and `\"` escapes -> valid single closed literal bool
    fsm28_inputs = [
        '"hello"', '"a\\"b"', '"a\\\\"', '"a\\\\\\"b"', '"unterminated',
        '"a\\"', '""', '"x"y"', 'plain', '"\\\\"',
        '"\\""', '"a" "b"', '"abc\\\\def"', '"abc\\"def\\""', '"abc\\\\\\"def"',
        '"', '"""', '"\\n"', '"\\\\\\""', '"ok\\\\"',
        '"bad\\\\\\"', '"123"', '""extra', ' "\\""', '"end\\\\"',
    ]
    tasks.append(_make_task(
        "fsm_28_escaped_string_literal", "parser_state_machines", "BOOL", "BOOL",
        "True iff s is one complete double-quoted literal with valid backslash escapes and no trailing characters.",
        """
def solve(inp):
    s = inp
    if len(s) < 2 or s[0] != '"':
        return False
    escaped = False
    for idx in range(1, len(s)):
        ch = s[idx]
        if escaped:
            escaped = False
        elif ch == "\\\\":
            escaped = True
        elif ch == '"':
            return (idx + 1) == len(s)
    return False
""",
        lambda inp: (lambda s: False if len(s) < 2 or s[0] != '"' else (lambda i, n: (lambda step: step(step, 1, False))(lambda f, k, esc: False if k >= n else (f(f, k + 1, False) if esc else (f(f, k + 1, True) if s[k] == "\\" else (k == n - 1 if s[k] == '"' else f(f, k + 1, False))))))(1, len(s)))(inp),
        fsm28_inputs,
        lambda inp, out: isinstance(out, bool) and ((len(inp) >= 2 and inp[0] == '"' and inp[-1] == '"') or out is False),
        # Naive `s[-2] != '\\'` fails on `"a\\"` (even number of backslashes)!
        lambda inp: len(inp) >= 2 and inp[0] == '"' and inp[-1] == '"' and (len(inp) == 2 or inp[-2] != "\\"),
        lambda inp: len(inp) >= 2 and inp[0] == '"' and inp[-1] == '"',  # accepts `"x"y"` and `"a\"`!
        lambda inp: inp == '""',
    ))

    # fsm_29: Bounded canonical u16 LEB128 decoder `(byte_list)` -> decoded int in [0, 65535] or -1
    fsm29_inputs = [
        [0x00], [0x7F], [0x80, 0x01], [0xFF, 0x7F], [0xFF, 0xFF, 0x03],
        [0xFF, 0xFF, 0x04], [0x80, 0x00], [0x81, 0x80, 0x00], [], [0x80],
        [0x85, 0x02], [0xE5, 0x8E, 0x26], [0x80, 0x80, 0x01], [0x80, 0x80, 0x80, 0x01],
        [0x01], [0x7E], [0xAC, 0x02], [0x80, 0x7F], [0xFF, 0x00],
        [0x81, 0x01], [0xFF, 0x80, 0x01], [0x80, 0x81, 0x04], [0x90, 0x03], [0xFF], [0x82, 0x00],
    ]
    tasks.append(_make_task(
        "fsm_29_canonical_leb128_u16", "parser_state_machines", "INT", "INT",
        "Minimal unsigned LEB128 u16 decoder: rejects truncated streams, >3 bytes, overlong trailing 0x00, or value > 65535.",
        """
def solve(inp):
    bs = inp
    if len(bs) == 0 or len(bs) > 3:
        return -1
    val = 0
    for i, b in enumerate(bs):
        val = val | ((b & 0x7F) << (7 * i))
        cont = (b & 0x80) != 0
        if i < (len(bs) - 1) and not cont:
            return -1
        if i == (len(bs) - 1) and cont:
            return -1
    if len(bs) > 1 and bs[-1] == 0:
        return -1
    if val > 65535:
        return -1
    return val
""",
        lambda inp: -1 if (not inp or len(inp) > 3 or any((b & 0x80) == 0 for b in inp[:-1]) or (inp[-1] & 0x80) != 0 or (len(inp) > 1 and inp[-1] == 0) or sum((b & 0x7F) << (7 * i) for i, b in enumerate(inp)) > 65535) else sum((b & 0x7F) << (7 * i) for i, b in enumerate(inp)),
        fsm29_inputs,
        lambda inp, out: isinstance(out, int) and -1 <= out <= 65535,
        # Accepts non-minimal overlong `[0x80, 0x00]`!
        lambda inp: -1 if (not inp or len(inp) > 3 or any((b & 0x80) == 0 for b in inp[:-1]) or (inp[-1] & 0x80) != 0 or sum((b & 0x7F) << (7 * i) for i, b in enumerate(inp)) > 65535) else sum((b & 0x7F) << (7 * i) for i, b in enumerate(inp)),
        # Forgets u16 overflow cap `val <= 65535` (clamps instead of rejecting `[0xFF, 0xFF, 0x04]` / `[0xE5, 0x8E, 0x26]`)!
        lambda inp: -1 if (not inp or len(inp) > 3 or (inp[-1] & 0x80) != 0) else (sum((b & 0x7F) << (7 * i) for i, b in enumerate(inp)) & 0xFFFF),
        lambda inp: inp[0] if len(inp) == 1 and inp[0] < 128 else -1,
    ))

    # fsm_30: Balanced multi-delimiter stack `()[]{}`
    fsm30_inputs = [
        "()[]{}", "([{}])", "([)]", "((()", "())", "", "{[()()]}", "{[(])}",
        "[", "]", "a+(b*[c-{d}])", "a+(b*[c-{d])", ")(", "[]{}", "{[}",
        "(([]))", "(([])", "([]){}", "[({})]", "[(])", "{}[]()", "{{}}",
        "{}}", "([{}])()", "([{}]))",
    ]
    tasks.append(_make_task(
        "fsm_30_balanced_delimiters", "parser_state_machines", "BOOL", "BOOL",
        "Balanced (), [], {} stack validator checking both matching delimiter type AND empty final stack.",
        """
def solve(inp):
    pairs = {")": "(", "]": "[", "}": "{"}
    opens = {"(", "[", "{"}
    stack = []
    for ch in inp:
        if ch in opens:
            stack.append(ch)
        elif ch in pairs:
            if len(stack) == 0 or stack[-1] != pairs[ch]:
                return False
            stack.pop()
    return (len(stack) - 0) == 0
""",
        lambda inp: (lambda st: all((st.append(c) or True) if c in "([{" else ((bool(st) and st.pop() == {")": "(", "]": "[", "}": "{"}[c]) if c in ")]}" else True) for c in inp) and not st)([]),
        fsm30_inputs,
        lambda inp, out: isinstance(out, bool) and ((inp.count("(") == inp.count(")") and inp.count("[") == inp.count("]") and inp.count("{") == inp.count("}")) or out is False),
        # Count-only check passes `"([)]"` and `")("`!
        lambda inp: inp.count("(") == inp.count(")") and inp.count("[") == inp.count("]") and inp.count("{") == inp.count("}"),
        # Single integer depth counter ignores bracket type mismatch `"([)]"`!
        lambda inp: (lambda d: all((d.__setitem__(0, d[0] + (1 if c in "([{" else (-1 if c in ")]}" else 0))) or True) and d[0] >= 0 for c in inp) and d[0] == 0)([0]),
        lambda inp: len(inp) == 0,
    ))

    # fsm_31: Length-prefixed packet framer `[len_hi, len_lo, ...payload...]` -> payload len or -1 on mismatch
    fsm31_inputs = [
        [0, 3, 10, 20, 30], [0, 0], [0, 2, 99], [0, 2, 99, 98, 97], [0],
        [], [0, 1, 42], [0, 4, 1, 2, 3, 4], [0, 4, 1, 2, 3], [1, 0],
        [0, 5, 5, 4, 3, 2, 1], [0, 5, 5, 4, 3, 2, 1, 0], [0, 2, 7, 8],
        [0, 3, 7, 8], [2, 0, 1], [0, 6, 1, 1, 1, 1, 1, 1], [0, 1],
        [0, 0, 99], [0, 2, 0, 0], [0, 3, 9, 9, 9, 9], [0, 7, 1, 2, 3, 4, 5, 6, 7],
        [0, 7, 1, 2, 3], [0, 1, 0, 0], [0, 2, 11, 22], [1, 1, 5],
    ]
    tasks.append(_make_task(
        "fsm_31_length_prefixed_frame", "parser_state_machines", "INT", "INT",
        "Big-endian u16 length-prefixed frame validator: returns declared payload length iff exact match, else -1.",
        """
def solve(inp):
    buf = inp
    if len(buf) < 2:
        return -1
    decl = (buf[0] << 8) + buf[1]
    actual = len(buf) - 2
    if actual != decl:
        return -1
    return decl
""",
        lambda inp: ((inp[0] * 256 + inp[1]) if (len(inp) >= 2 and len(inp) - 2 == inp[0] * 256 + inp[1]) else -1),
        fsm31_inputs,
        lambda inp, out: isinstance(out, int) and (out == -1 or 0 <= out <= max(0, len(inp) - 2)),
        # Accepts frames with trailing garbage `actual >= decl`!
        lambda inp: (inp[0] * 256 + inp[1]) if (len(inp) >= 2 and (len(inp) - 2) >= (inp[0] * 256 + inp[1])) else -1,
        # Ignores high byte `buf[0]`!
        lambda inp: inp[1] if (len(inp) >= 2 and (len(inp) - 2) == inp[1]) else -1,
        lambda inp: len(inp) - 2 if len(inp) >= 2 else -1,
    ))

    # fsm_32: SemVer comparator `((maj1, min1, pat1, pre1), (maj2, min2, pat2, pre2))` -> -1, 0, +1 (`1.0.0-rc < 1.0.0`)
    fsm32_inputs = [
        ((1, 0, 0, True), (1, 0, 0, False)), ((1, 0, 0, False), (1, 0, 0, True)),
        ((1, 0, 0, False), (1, 0, 0, False)), ((1, 0, 0, True), (1, 0, 0, True)),
        ((1, 2, 0, False), (1, 10, 0, False)), ((2, 0, 0, True), (1, 9, 9, False)),
        ((0, 1, 2, False), (0, 1, 3, False)), ((0, 2, 0, True), (0, 1, 9, False)),
        ((1, 0, 1, True), (1, 0, 0, False)), ((3, 1, 4, False), (3, 1, 4, True)),
        ((0, 0, 0, True), (0, 0, 0, False)), ((2, 1, 0, False), (2, 0, 9, False)),
        ((1, 2, 3, False), (1, 2, 3, False)), ((4, 0, 0, False), (5, 0, 0, True)),
        ((1, 1, 1, True), (1, 1, 2, True)), ((2, 3, 4, True), (2, 3, 4, False)),
        ((0, 9, 0, False), (0, 10, 0, True)), ((7, 0, 0, False), (6, 99, 99, False)),
        ((1, 0, 2, False), (1, 0, 1, False)), ((1, 5, 0, True), (1, 5, 0, True)),
        ((2, 2, 2, False), (2, 2, 3, True)), ((8, 1, 0, True), (8, 1, 0, False)),
        ((3, 0, 0, False), (3, 0, 0, False)), ((1, 4, 2, False), (1, 3, 9, False)),
        ((0, 0, 1, True), (0, 0, 1, False)),
    ]
    tasks.append(_make_task(
        "fsm_32_semver_prerelease_order", "parser_state_machines", "INT", "INT",
        "SemVer 2.0 comparator: compares (major, minor, patch), with pre-release strictly preceding normal release (1.0.0-alpha < 1.0.0).",
        """
def solve(inp):
    a, b = inp
    ka = (a[0], a[1], a[2], 0 if a[3] else 1)
    kb = (b[0], b[1], b[2], 0 if b[3] else 1)
    if ka < kb:
        return -1
    if ka > kb:
        return 1
    return 0 + 0
""",
        lambda inp: -1 if (inp[0][:3], not inp[0][3]) < (inp[1][:3], not inp[1][3]) else (1 if (inp[0][:3], not inp[0][3]) > (inp[1][:3], not inp[1][3]) else 0),
        fsm32_inputs,
        lambda inp, out: isinstance(out, int) and out in (-1, 0, 1),
        # Python default tuple order puts `True (1) > False (0)`, inverting SemVer prerelease precedence!
        lambda inp: -1 if inp[0] < inp[1] else (1 if inp[0] > inp[1] else 0),
        # Ignores prerelease flag altogether!
        lambda inp: -1 if inp[0][:3] < inp[1][:3] else (1 if inp[0][:3] > inp[1][:3] else 0),
        lambda inp: 0,
    ))

    # fsm_33: Strict HTTP/1.1 hex chunk-size line parser `"1a\r\n"` -> int or -1 (rejects `0x`, `-`, `+`, whitespace, missing `\r\n`)
    fsm33_inputs = [
        "0\r\n", "a\r\n", "1A\r\n", "ff\r\n", "100\r\n",
        "0x10\r\n", "-5\r\n", "+5\r\n", "1a\n", "1a\r",
        "\r\n", " 1a\r\n", "1a \r\n", "g0\r\n", "dead\r\n",
        "FFFF\r\n", "10000\r\n", "7f\r\n", "00\r\n", "abc\r\n",
        "12\r\n3", "9\r\n", "f0\r\n", "_1\r\n", "42",
    ]
    tasks.append(_make_task(
        "fsm_33_http_chunk_hex_header", "parser_state_machines", "INT", "INT",
        "Strict u16 HTTP hex chunk-size parser: >=1 hex digit + exact CRLF, no 0x/sign/underscore/spaces, <= 65535.",
        """
def solve(inp):
    s = inp
    if not s.endswith("\\r\\n"):
        return -1
    body = s[:-2]
    if len(body) == 0 or len(body) > 4:
        return -1
    val = 0
    for ch in body:
        if "0" <= ch <= "9":
            d = ord(ch) - ord("0")
        elif "a" <= ch <= "f":
            d = ord(ch) - ord("a") + 10
        elif "A" <= ch <= "F":
            d = ord(ch) - ord("A") + 10
        else:
            return -1
        val = (val << 4) + d
    return val
""",
        lambda inp: int(inp[:-2], 16) if (inp.endswith("\r\n") and 1 <= len(inp[:-2]) <= 4 and all(c in "0123456789abcdefABCDEF" for c in inp[:-2])) else -1,
        fsm33_inputs,
        lambda inp, out: isinstance(out, int) and -1 <= out <= 65535,
        # Python `int(s.strip(), 16)` falsely accepts `" 1a\r\n"`, `"1a\n"`, `"+5\r\n"`, `"_1\r\n"`!
        lambda inp: (lambda v: v if 0 <= v <= 65535 else -1)(int(inp.strip(), 16)) if any(c in "0123456789abcdefABCDEF" for c in inp) and all(c in "0123456789abcdefABCDEF+-_ \r\n" for c in inp) and not inp.strip().startswith(("0x", "_", "-")) else -1,
        lambda inp: int(inp[:-2], 16) if (inp.endswith("\n") and len(inp) > 2 and all(c in "0123456789abcdefABCDEF\r" for c in inp[:-1]) and len(inp.strip()) >= 1 and int(inp.strip(), 16) <= 65535) else -1,
        lambda inp: 0 if inp == "0\r\n" else -1,
    ))

    # fsm_34: 4-state session protocol FSM (`0:SYN`, `1:ACK`, `2:DATA`, `3:FIN`) -> `(valid_trace, data_frames_accepted)`
    fsm34_inputs = [
        [0, 1, 2, 2, 3], [0, 1, 3], [0, 2, 1], [2, 0, 1], [1, 0],
        [], [0], [0, 1], [0, 1, 2], [0, 1, 3, 2],
        [0, 1, 3, 0, 1, 2, 3], [0, 0, 1], [0, 1, 1], [3], [0, 3],
        [0, 1, 2, 3, 0, 1, 2], [0, 1, 2, 2, 2, 3], [0, 1, 3, 3],
        [0, 1, 2, 0], [0, 1, 3, 0, 1, 3], [0, 1, 2, 2], [2],
        [0, 1, 3, 1], [0, 1, 2, 3, 0], [0, 1, 2, 1],
    ]
    tasks.append(_make_task(
        "fsm_34_session_handshake_fsm", "parser_state_machines", "TUPLE2", "INT",
        "Protocol FSM (CLOSED -SYN-> SYN_RCVD -ACK-> ESTAB -DATA*-> ESTAB -FIN-> CLOSED); rejects out-of-order events.",
        """
def solve(inp):
    state = 0
    data_cnt = 0
    for ev in inp:
        if state == 0:
            if ev != 0:
                return (0, 0)
            state = 1
        elif state == 1:
            if ev != 1:
                return (0, 0)
            state = 2
        else:
            if ev == 2:
                data_cnt = data_cnt + 1
            elif ev == 3:
                state = 0
            else:
                return (0, 0)
    return (1, data_cnt)
""",
        lambda inp: (lambda st: (0, 0) if st[0] == -1 else (1, st[1]))((lambda s: ([s.__setitem__(0, 1 if (s[0] == 0 and e == 0) else (2 if (s[0] == 1 and e == 1) else (2 if (s[0] == 2 and e == 2 and (s.__setitem__(1, s[1] + 1) or True)) else (0 if (s[0] == 2 and e == 3) else -1)))) for e in inp], s)[1])([0, 0])),
        fsm34_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and out[0] in (0, 1) and 0 <= out[1] <= inp.count(2),
        # Accepts DATA in SYN_RCVD before ACK (`[0, 2, 1]`)!
        lambda inp: (1, inp.count(2)) if (not inp or inp[0] == 0) else (0, 0),
        # Counts DATA frames before rejecting later illegal packet instead of zeroing on abort!
        lambda inp: (0, inp.count(2)) if (inp and inp[0] != 0) else (1, inp.count(2)),
        lambda inp: (1, 0),
    ))

    # ═══════════════════════════════════════════════════════════════════════════
    # DOMAIN 6: SORTING PERMUTATION + MONOTONICITY INVARIANTS (6 tasks: srt_35 .. srt_40)
    # ═══════════════════════════════════════════════════════════════════════════

    # srt_35: Non-decreasing sort preserving BOTH monotonicity AND exact multiset
    srt35_inputs = [
        [3, 1, 2], [5, 1, 5, 2, 1], [], [42], [9, 8, 7, 6, 5],
        [-3, 0, -1, 2, -3], [1, 2, 3, 4], [2, 2, 2], [10, -10, 0],
        [4, 1, 3, 2, 4, 1], [100, 50, 75, 25], [0, -1], [7, 3, 9, 1, 5],
        [8, 8, 1, 1, 8], [-5, -2, -9, -1], [6, 2, 4, 3, 5, 1],
        [11, 22, 11], [3, 0, 3, 0], [15, 14, 13, 12], [1, 9, 2, 8, 3, 7],
        [50, 40], [2, -2, 2, -2, 0], [99, 1, 50], [4, 4, 3, 3, 2, 2], [12, 7, 19, 3, 7],
    ]
    tasks.append(_make_task(
        "srt_35_sort_multiset_and_monotone", "sorting_invariants", "LIST", "LIST",
        "Ascending sort satisfying BOTH non-decreasing order (y[i] <= y[i+1]) AND exact multiset conservation.",
        """
def solve(inp):
    arr = list(inp)
    n = len(arr)
    for i in range(n):
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
    return arr
""",
        lambda inp: sorted(inp),
        srt35_inputs,
        # Classic partial property spec: checks length AND monotonicity, forgetting multiset permutation!
        lambda inp, out: isinstance(out, list) and len(out) == len(inp) and all(out[i] <= out[i + 1] for i in range(len(out) - 1)),
        # `[min(inp)] * len(inp)` is length-matched, monotone, AND made of input elements — slips right past Arm B!
        lambda inp: ([min(inp)] * len(inp)) if inp else [],
        # `[0] * len(inp)` also satisfies length + monotonicity!
        lambda inp: [0] * len(inp),
        lambda inp: sorted(set(inp)),
    ))

    # srt_36: Stable sort of `(key, tag)` pairs by `key` preserving original relative order on ties
    srt36_inputs = [
        [(2, "a"), (1, "b"), (2, "c")], [(1, "x"), (1, "y"), (1, "z")], [],
        [(3, "p")], [(2, "m"), (2, "a"), (1, "z"), (1, "b")],
        [(5, "d"), (3, "c"), (5, "b"), (3, "a")], [(0, "q"), (-1, "r"), (0, "a")],
        [(4, "2"), (4, "1"), (2, "9")], [(1, "a"), (2, "b"), (3, "c")],
        [(3, "c"), (2, "b"), (1, "a")], [(7, "k"), (7, "a"), (5, "m"), (7, "b")],
        [(0, "z"), (0, "a")], [(2, "u"), (1, "v"), (2, "t"), (1, "s")],
        [(-2, "b"), (-2, "a"), (-3, "c")], [(9, "1"), (8, "2"), (9, "0")],
        [(6, "f"), (6, "e"), (6, "d"), (1, "a")], [(10, "b"), (5, "a"), (10, "a")],
        [(3, "x"), (1, "y"), (3, "a"), (2, "z")], [(4, "p"), (2, "q")],
        [(1, "m"), (0, "n"), (1, "a")], [(8, "c"), (8, "b"), (7, "a")],
        [(2, "d"), (3, "c"), (2, "b"), (3, "a")], [(5, "x"), (5, "a")],
        [(1, "first"), (1, "second")], [(0, "b"), (1, "a"), (0, "a")],
    ]
    tasks.append(_make_task(
        "srt_36_stable_key_sort", "sorting_invariants", "LIST", "LIST",
        "Stable sort of (key, tag) records by key ONLY, strictly preserving arrival order on equal keys.",
        """
def solve(inp):
    indexed = [(item[0], 0 + idx, item) for idx, item in enumerate(inp)]
    indexed.sort(key=lambda t: (t[0], t[1]))
    if len(indexed) == 0:
        return []
    return [t[2] for t in indexed]
""",
        lambda inp: sorted(inp, key=lambda pair: pair[0]),
        srt36_inputs,
        # Partial spec checks multiset equality AND key monotonicity, missing tie-break stability!
        lambda inp, out: isinstance(out, list) and sorted(out) == sorted(inp) and all(out[i][0] <= out[i + 1][0] for i in range(len(out) - 1)),
        # Full tuple `sorted(inp)` breaks ties lexicographically on `tag` instead of preserving arrival order!
        lambda inp: sorted(inp),
        # Reverses equal-key runs!
        lambda inp: [t[2] for t in sorted([(x[0], -i, x) for i, x in enumerate(inp)])],
        lambda inp: list(inp),
    ))

    # srt_37: Strictly increasing deduplicated output (`y[i] < y[i+1]` and `set(y) == set(x)`)
    srt37_inputs = srt35_inputs
    tasks.append(_make_task(
        "srt_37_strict_dedup_sorted", "sorting_invariants", "LIST", "LIST",
        "Strictly ascending deduplicated sequence (y[i] < y[i+1] and set(y) == set(inp)).",
        """
def solve(inp):
    s = sorted(inp)
    out = []
    for v in s:
        if len(out) == 0 or (v - out[-1]) > 0:
            out.append(v)
    return out
""",
        lambda inp: sorted(set(inp)),
        srt37_inputs,
        # Partial spec checks non-decreasing order and subset of input, missing strict `<` (duplicates slip) or completeness!
        lambda inp, out: isinstance(out, list) and all(out[i] <= out[i + 1] for i in range(len(out) - 1)) and set(out).issubset(set(inp)),
        lambda inp: sorted(inp),  # forgets deduplication! slips past `<=` partial spec!
        lambda inp: [min(inp)] if inp else [],  # drops non-minimum elements! slips past `issubset`!
        lambda inp: list(dict.fromkeys(inp)),  # deduplicates without sorting!
    ))

    # srt_38: Top-k largest elements in non-increasing order `(arr, k)`
    srt38_inputs = [
        ([3, 1, 5, 2, 4], 3), ([5, 5, 1, 5], 2), ([1, 2], 5), ([1, 2, 3], 0),
        ([], 2), ([9], 1), ([-3, -1, -7, -2], 2), ([4, 4, 4], 2),
        ([10, 20, 30, 40], 1), ([10, 20, 30, 40], 4), ([7, 2, 9, 2, 9], 3),
        ([0, -5, 5, 0], 3), ([8, 1, 6, 3, 5, 7, 4, 9, 2], 4), ([2, 1], 1),
        ([100, 99, 100, 98], 3), ([6, 5, 4, 3], 2), ([1, 3, 2, 3, 1], 4),
        ([11, 22, 33], 2), ([-10, 0, 10], 2), ([5, 4, 3, 2, 1], 5),
        ([5, 4, 3, 2, 1], 6), ([7, 8], 0), ([3, 3, 2, 1], 1), ([9, 0, 9, 0], 3), ([42, 17], 2),
    ]
    tasks.append(_make_task(
        "srt_38_top_k_descending", "sorting_invariants", "LIST", "LIST",
        "Top-k largest elements (with multiplicity) in non-increasing order, clamped to len(arr) when k > len(arr).",
        """
def solve(inp):
    arr, k = inp
    if k <= 0 or len(arr) == 0:
        return []
    desc = sorted(arr, reverse=True)
    take = k if k < len(desc) else len(desc)
    return desc[:take + 0]
""",
        lambda inp: [] if inp[1] <= 0 else list(reversed(sorted(inp[0])))[:inp[1]],
        srt38_inputs,
        lambda inp, out: isinstance(out, list) and len(out) == min(max(0, inp[1]), len(inp[0])) and all(out[i] >= out[i + 1] for i in range(len(out) - 1)),
        lambda inp: [] if inp[1] <= 0 or not inp[0] else [max(inp[0])] * min(inp[1], len(inp[0])),  # repeats max k times!
        lambda inp: sorted(set(inp[0]), reverse=True)[:max(0, inp[1])],  # drops duplicate top elements!
        lambda inp: sorted(inp[0])[:max(0, inp[1])],
    ))

    # srt_39: Dutch National Flag 3-way partition boundary indices `(arr, pivot)` -> `(lt_end, gt_start)`
    srt39_inputs = [
        ([3, 1, 2, 3, 0, 3], 3), ([1, 2, 3], 2), ([2, 2, 2], 2), ([], 5),
        ([5, 4, 3], 10), ([5, 4, 3], 0), ([1, 5, 3, 5, 2, 5, 4], 5),
        ([0, -1, 1, 0, -2], 0), ([7], 7), ([7], 8), ([7], 6),
        ([4, 2, 4, 1, 4, 6, 5], 4), ([9, 8, 7, 6], 7), ([1, 1, 2, 2, 3, 3], 2),
        ([3, 3, 1, 1], 2), ([-5, -3, -5, -1], -3), ([10, 20, 10, 30], 10),
        ([10, 20, 10, 30], 20), ([10, 20, 10, 30], 25), ([6, 2, 8, 2, 4], 2),
        ([2, 1, 2, 3, 2], 2), ([0, 0, 1], 0), ([1, 0, 0], 1), ([5, 1, 9, 3], 4), ([8, 4, 8, 2, 6], 6),
    ]
    tasks.append(_make_task(
        "srt_39_dutch_flag_boundaries", "sorting_invariants", "TUPLE2", "INT",
        "3-way partition boundaries (lt_count, len - gt_count) around pivot such that [0:lt] < pivot, [lt:gt] == pivot, [gt:n] > pivot.",
        """
def solve(inp):
    arr, pivot = inp
    lt = 0
    eq = 0
    for x in arr:
        if x < pivot:
            lt = lt + 1
        elif x == pivot:
            eq = eq + 1
    return (lt, lt + eq)
""",
        lambda inp: (sum(1 for v in inp[0] if v < inp[1]), sum(1 for v in inp[0] if v <= inp[1])),
        srt39_inputs,
        lambda inp, out: isinstance(out, tuple) and len(out) == 2 and 0 <= out[0] <= out[1] <= len(inp[0]),
        lambda inp: (sum(1 for v in inp[0] if v < inp[1]), sum(1 for v in inp[0] if v < inp[1])),  # merges `== pivot` into `> pivot`!
        lambda inp: (0, len(inp[0])),  # trivial [0, n] bounds pass `0 <= lt <= gt <= n`!
        lambda inp: (sum(1 for v in inp[0] if v <= inp[1]), len(inp[0])),
    ))

    # srt_40: Stable argsort permutation indices `arr` -> `idx` (`sorted(idx) == range(n)` and `[arr[i] for i in idx]` sorted stably)
    srt40_inputs = srt35_inputs
    tasks.append(_make_task(
        "srt_40_stable_argsort_perm", "sorting_invariants", "LIST", "LIST",
        "Stable argsort index permutation idx: permutation of 0..n-1 ordering arr[idx[k]] ascending with i < j tie-break.",
        """
def solve(inp):
    n = len(inp)
    if n == 0:
        return []
    pairs = [(inp[i], 0 + i) for i in range(n)]
    pairs.sort(key=lambda p: (p[0], p[1]))
    return [p[1] for p in pairs]
""",
        lambda inp: sorted(range(len(inp)), key=lambda i: inp[i]),
        srt40_inputs,
        # Partial spec checks index range & sorted values `[inp[i] for i in out]`, missing permutation uniqueness on duplicates!
        lambda inp, out: isinstance(out, list) and len(out) == len(inp) and all(isinstance(i, int) and 0 <= i < len(inp) for i in out) and all(inp[out[k]] <= inp[out[k + 1]] for k in range(len(out) - 1)),
        # Repeats argmin index `n` times — `[inp[argmin]] * n` is monotone AND valid index, violating permutation bijection!
        lambda inp: ([inp.index(min(inp))] * len(inp)) if inp else [],
        # Breaks tie-stability on equal values (`-i` tie-breaker)!
        lambda inp: [p[1] for p in sorted([(inp[i], -i, i) for i in range(len(inp))])],
        lambda inp: list(range(len(inp))),
    ))

    assert len(tasks) == 40, f"Expected 40 tasks, built {len(tasks)}"
    return tasks
