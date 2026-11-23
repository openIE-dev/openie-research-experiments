#!/usr/bin/env python3
"""
CTA-E2 Self-Contained 60-Task Multi-Category Python Code-Repair Benchmark.

Categories (20 tasks each = 60 tasks total):
  - Category 1 (`C1_01`..`C1_20`): Syntax, indentation, delimiter, operator-token, and missing-import defects.
  - Category 2 (`C2_01`..`C2_20`): Scope, variable-binding typo, mutable-default state leak, type-coercion, and API-signature defects.
  - Category 3 (`C3_01`..`C3_20`): Algorithmic, boundary-condition, numerical-compensation, and state-machine logic defects.

Strict Information Boundary:
  - `get_public_tasks()` returns ONLY `(task_id, category, fn_name, broken_code)` — ZERO access to
    `reference_code`, `test_vectors`, or `property_fn`.
  - `HOLD_OUT_ORACLES` is accessed ONLY by `evaluate_heldout_oracle()` AFTER an arm has finalized its
    commit/refusal decision, enforcing >= 8 independent test vectors + reference property check per task.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _build_all_tasks() -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = [
        # =====================================================================
        # CATEGORY 1: 20 Syntax / Indentation / Delimiter / Import Bugs
        # =====================================================================
        {
            "task_id": "C1_01",
            "category": "cat1_syntax_import",
            "fn_name": "horner_eval",
            "broken_code": (
                "def horner_eval(coeffs: list[int], x: int) -> int\n"
                '    """Evaluate polynomial sum(coeffs[i] * x**(n-1-i)) using Horner\'s rule.\n'
                "    >>> horner_eval([2, -6, 2, -1], 3)\n"
                "    5\n"
                "    >>> horner_eval([], 10)\n"
                "    0\n"
                '    """\n'
                "    acc = 0\n"
                "    for c in coeffs:\n"
                "        acc = acc * x + c\n"
                "    return acc\n"
            ),
            "reference_code": (
                "def horner_eval(coeffs: list[int], x: int) -> int:\n"
                "    acc = 0\n"
                "    for c in coeffs:\n"
                "        acc = acc * x + c\n"
                "    return acc\n"
            ),
            "test_vectors": [
                (([2, -6, 2, -1], 3), 5),
                (([], 10), 0),
                (([5], 99), 5),
                (([1, 0, 0, 0], 2), 8),
                (([1, -1, 1, -1], 1), 0),
                (([3, 2, 1], 0), 1),
                (([1, 2, 1], -1), 0),
                (([4, -3, 2, -5, 7], -2), 113),
            ],
        },
        {
            "task_id": "C1_02",
            "category": "cat1_syntax_import",
            "fn_name": "gcd_array",
            "broken_code": (
                "def gcd_array(nums: list[int]) -> int:\n"
                '    """Return non-negative greatest common divisor of all integers in nums (0 if empty).\n'
                "    >>> gcd_array([24, 36, 60])\n"
                "    12\n"
                "    >>> gcd_array([])\n"
                "    0\n"
                '    """\n'
                "    if not nums\n"
                "        return 0\n"
                "    g = abs(nums[0])\n"
                "    for v in nums[1:]:\n"
                "        a, b = g, abs(v)\n"
                "        while b:\n"
                "            a, b = b, a % b\n"
                "        g = a\n"
                "    return g\n"
            ),
            "reference_code": (
                "def gcd_array(nums: list[int]) -> int:\n"
                "    if not nums:\n"
                "        return 0\n"
                "    g = abs(nums[0])\n"
                "    for v in nums[1:]:\n"
                "        a, b = g, abs(v)\n"
                "        while b:\n"
                "            a, b = b, a % b\n"
                "        g = a\n"
                "    return g\n"
            ),
            "test_vectors": [
                (([24, 36, 60],), 12),
                (([],), 0),
                (([0, 0, 15],), 15),
                (([-18, 27, -45],), 9),
                (([17, 29, 31],), 1),
                (([42],), 42),
                (([-42],), 42),
                (([100, 250, 75, 125],), 25),
            ],
        },
        {
            "task_id": "C1_03",
            "category": "cat1_syntax_import",
            "fn_name": "collatz_steps",
            "broken_code": (
                "def collatz_steps(n: int) -> int:\n"
                '    """Count steps required for positive integer n to reach 1 under 3n+1 / n//2.\n'
                "    >>> collatz_steps(6)\n"
                "    8\n"
                "    >>> collatz_steps(1)\n"
                "    0\n"
                '    """\n'
                "    if n < 1:\n"
                "        raise ValueError('n must be >= 1')\n"
                "    steps = 0\n"
                "    while n > 1\n"
                "        n = (n // 2) if (n % 2 == 0) else (3 * n + 1)\n"
                "        steps += 1\n"
                "    return steps\n"
            ),
            "reference_code": (
                "def collatz_steps(n: int) -> int:\n"
                "    if n < 1:\n"
                "        raise ValueError('n must be >= 1')\n"
                "    steps = 0\n"
                "    while n > 1:\n"
                "        n = (n // 2) if (n % 2 == 0) else (3 * n + 1)\n"
                "        steps += 1\n"
                "    return steps\n"
            ),
            "test_vectors": [
                ((1,), 0),
                ((2,), 1),
                ((3,), 7),
                ((6,), 8),
                ((7,), 16),
                ((16,), 4),
                ((27,), 111),
                ((19,), 20),
            ],
        },
        {
            "task_id": "C1_04",
            "category": "cat1_syntax_import",
            "fn_name": "transpose_rect",
            "broken_code": (
                "def transpose_rect(mat: list[list[int]]) -> list[list[int]]:\n"
                '    """Transpose a rectangular matrix; return [] if mat or mat[0] is empty.\n'
                "    >>> transpose_rect([[1, 2, 3], [4, 5, 6]])\n"
                "    [[1, 4], [2, 5], [3, 6]]\n"
                "    >>> transpose_rect([])\n"
                "    []\n"
                '    """\n'
                "    if not mat or not mat[0]:\n"
                "        return []\n"
                "    rows, cols = len(mat), len(mat[0])\n"
                "    out = []\n"
                "    for c in range(cols)\n"
                "        out.append([mat[r][c] for r in range(rows)])\n"
                "    return out\n"
            ),
            "reference_code": (
                "def transpose_rect(mat: list[list[int]]) -> list[list[int]]:\n"
                "    if not mat or not mat[0]:\n"
                "        return []\n"
                "    rows, cols = len(mat), len(mat[0])\n"
                "    out = []\n"
                "    for c in range(cols):\n"
                "        out.append([mat[r][c] for r in range(rows)])\n"
                "    return out\n"
            ),
            "test_vectors": [
                (([[1, 2, 3], [4, 5, 6]],), [[1, 4], [2, 5], [3, 6]]),
                (([],), []),
                (([[]],), []),
                (([[9]],), [[9]]),
                (([[1, 2], [3, 4]],), [[1, 3], [2, 4]]),
                (([[1], [2], [3]],), [[1, 2, 3]]),
                (([[1, 2, 3]],), [[1], [2], [3]]),
                (([[-1, 0], [5, -7], [8, 2]],), [[-1, 5, 8], [0, -7, 2]]),
            ],
        },
        {
            "task_id": "C1_05",
            "category": "cat1_syntax_import",
            "fn_name": "sign_bucket",
            "broken_code": (
                "def sign_bucket(values: list[int]) -> tuple[int, int, int]:\n"
                '    """Return counts (negatives, zeros, positives) across values.\n'
                "    >>> sign_bucket([-3, 0, 4, 5, 0, -1])\n"
                "    (2, 2, 2)\n"
                "    >>> sign_bucket([])\n"
                "    (0, 0, 0)\n"
                '    """\n'
                "    neg = zero = pos = 0\n"
                "    for v in values:\n"
                "        if v < 0:\n"
                "            neg += 1\n"
                "        elif v == 0:\n"
                "            zero += 1\n"
                "        else\n"
                "            pos += 1\n"
                "    return (neg, zero, pos)\n"
            ),
            "reference_code": (
                "def sign_bucket(values: list[int]) -> tuple[int, int, int]:\n"
                "    neg = zero = pos = 0\n"
                "    for v in values:\n"
                "        if v < 0:\n"
                "            neg += 1\n"
                "        elif v == 0:\n"
                "            zero += 1\n"
                "        else:\n"
                "            pos += 1\n"
                "    return (neg, zero, pos)\n"
            ),
            "test_vectors": [
                (([-3, 0, 4, 5, 0, -1],), (2, 2, 2)),
                (([],), (0, 0, 0)),
                (([0, 0, 0],), (0, 3, 0)),
                (([-1, -2, -3],), (3, 0, 0)),
                (([1, 2, 3, 4],), (0, 0, 4)),
                (([-10, 10],), (1, 0, 1)),
                (([0, 1],), (0, 1, 1)),
                (([-5, 0],), (1, 1, 0)),
            ],
        },
        {
            "task_id": "C1_06",
            "category": "cat1_syntax_import",
            "fn_name": "pack_u16_be",
            "broken_code": (
                "def pack_u16_be(words: list[int]) -> list[int]:\n"
                '    """Unpack each 16-bit unsigned integer (0..65535) into two big-endian bytes.\n'
                "    >>> pack_u16_be([0x1234, 0xABCD])\n"
                "    [18, 52, 171, 205]\n"
                "    >>> pack_u16_be([])\n"
                "    []\n"
                '    """\n'
                "    out: list[int] = []\n"
                "    for w in words:\n"
                "        w16 = w & 0xFFFF\n"
                "        out.extend([(w16 >> 8) & 0xFF, w16 & 0xFF\n"
                "    return out\n"
            ),
            "reference_code": (
                "def pack_u16_be(words: list[int]) -> list[int]:\n"
                "    out: list[int] = []\n"
                "    for w in words:\n"
                "        w16 = w & 0xFFFF\n"
                "        out.extend([(w16 >> 8) & 0xFF, w16 & 0xFF])\n"
                "    return out\n"
            ),
            "test_vectors": [
                (([0x1234, 0xABCD],), [18, 52, 171, 205]),
                (([],), []),
                (([0],), [0, 0]),
                (([0xFFFF],), [255, 255]),
                (([0x00FF, 0xFF00],), [0, 255, 255, 0]),
                (([256],), [1, 0]),
                (([1, 2, 3],), [0, 1, 0, 2, 0, 3]),
                (([0xCAFE, 0xBABE],), [202, 254, 186, 190]),
            ],
        },
        {
            "task_id": "C1_07",
            "category": "cat1_syntax_import",
            "fn_name": "manhattan_dist",
            "broken_code": (
                "def manhattan_dist(a: list[int], b: list[int]) -> int:\n"
                '    """Compute L1 Manhattan distance between equal-length integer vectors a and b.\n'
                "    >>> manhattan_dist([1, -2, 3], [4, 0, -1])\n"
                "    9\n"
                "    >>> manhattan_dist([], [])\n"
                "    0\n"
                '    """\n'
                "    if len(a) != len(b):\n"
                "        raise ValueError('length mismatch')\n"
                "    return sum(abs(x - y) for x, y in zip(a, b)\n"
            ),
            "reference_code": (
                "def manhattan_dist(a: list[int], b: list[int]) -> int:\n"
                "    if len(a) != len(b):\n"
                "        raise ValueError('length mismatch')\n"
                "    return sum(abs(x - y) for x, y in zip(a, b))\n"
            ),
            "test_vectors": [
                (([1, -2, 3], [4, 0, -1]), 9),
                (([], []), 0),
                (([0, 0], [0, 0]), 0),
                (([-5], [5]), 10),
                (([1, 2, 3, 4], [1, 2, 3, 4]), 0),
                (([10, -10, 20], [-10, 10, 0]), 60),
                (([7, 3], [2, 9]), 11),
                (([-3, -4, -5], [-1, -2, -8]), 7),
            ],
        },
        {
            "task_id": "C1_08",
            "category": "cat1_syntax_import",
            "fn_name": "invert_unique_map",
            "broken_code": (
                "def invert_unique_map(d: dict[str, int]) -> dict[int, str]:\n"
                '    """Invert mapping k -> v assuming values are unique.\n'
                "    >>> invert_unique_map({'a': 1, 'b': 2})\n"
                "    {1: 'a', 2: 'b'}\n"
                "    >>> invert_unique_map({})\n"
                "    {}\n"
                '    """\n'
                "    return {v: k for k, v in d.items()\n"
            ),
            "reference_code": (
                "def invert_unique_map(d: dict[str, int]) -> dict[int, str]:\n"
                "    return {v: k for k, v in d.items()}\n"
            ),
            "test_vectors": [
                (({'a': 1, 'b': 2},), {1: 'a', 2: 'b'}),
                (({},), {}),
                (({'only': 0},), {0: 'only'}),
                (({'x': -5, 'y': 10, 'z': 0},), {-5: 'x', 10: 'y', 0: 'z'}),
                (({'k1': 100, 'k2': 200},), {100: 'k1', 200: 'k2'}),
                (({'m': 7, 'n': 8, 'p': 9, 'q': 10},), {7: 'm', 8: 'n', 9: 'p', 10: 'q'}),
                (({'neg': -999},), {-999: 'neg'}),
                (({'aa': 42, 'bb': 43},), {42: 'aa', 43: 'bb'}),
            ],
        },
        {
            "task_id": "C1_09",
            "category": "cat1_syntax_import",
            "fn_name": "clamp_list",
            "broken_code": (
                "def clamp_list(nums: list[int], lo: int, hi: int) -> list[int]:\n"
                '    """Clamp every element of nums into [lo, hi].\n'
                "    >>> clamp_list([-5, 0, 5, 12], 0, 10)\n"
                "    [0, 0, 5, 10]\n"
                "    >>> clamp_list([], 1, 5)\n"
                "    []\n"
                '    """\n'
                "    return [min(hi, max(lo, x)] for x in nums]\n"
            ),
            "reference_code": (
                "def clamp_list(nums: list[int], lo: int, hi: int) -> list[int]:\n"
                "    return [min(hi, max(lo, x)) for x in nums]\n"
            ),
            "test_vectors": [
                (([-5, 0, 5, 12], 0, 10), [0, 0, 5, 10]),
                (([], 1, 5), []),
                (([3, 3, 3], 3, 3), [3, 3, 3]),
                (([-10, -2, 0, 8], -4, 4), [-4, -2, 0, 4]),
                (([100, 200], 0, 50), [50, 50]),
                (([-100, -50], -20, 0), [-20, -20]),
                (([1, 2, 3, 4, 5], 2, 4), [2, 2, 3, 4, 4]),
                (([0], -1, 1), [0]),
            ],
        },
        {
            "task_id": "C1_10",
            "category": "cat1_syntax_import",
            "fn_name": "count_even_odd_parity",
            "broken_code": (
                "def count_even_odd_parity(n: int) -> str:\n"
                '    """Return \'EVEN\' if popcount(n >= 0) is even, else \'ODD\'.\n'
                "    >>> count_even_odd_parity(3)\n"
                "    'EVEN'\n"
                "    >>> count_even_odd_parity(7)\n"
                "    'ODD'\n"
                '    """\n'
                "    ones = bin(n).count('1')\n"
                "    if ones % 2 = 0:\n"
                "        return 'EVEN'\n"
                "    return 'ODD'\n"
            ),
            "reference_code": (
                "def count_even_odd_parity(n: int) -> str:\n"
                "    ones = bin(n).count('1')\n"
                "    if ones % 2 == 0:\n"
                "        return 'EVEN'\n"
                "    return 'ODD'\n"
            ),
            "test_vectors": [
                ((0,), "EVEN"),
                ((1,), "ODD"),
                ((2,), "ODD"),
                ((3,), "EVEN"),
                ((7,), "ODD"),
                ((15,), "EVEN"),
                ((16,), "ODD"),
                ((255,), "EVEN"),
            ],
        },
        {
            "task_id": "C1_11",
            "category": "cat1_syntax_import",
            "fn_name": "in_closed_annulus",
            "broken_code": (
                "def in_closed_annulus(x: int, y: int, r_in: int, r_out: int) -> bool:\n"
                '    """Return True iff r_in^2 <= x^2 + y^2 <= r_out^2 (with 0 <= r_in <= r_out).\n'
                "    >>> in_closed_annulus(3, 4, 5, 6)\n"
                "    True\n"
                "    >>> in_closed_annulus(1, 1, 2, 5)\n"
                "    False\n"
                '    """\n'
                "    d2 = x * x + y * y\n"
                "    if d2 >= r_in * r_in && d2 <= r_out * r_out:\n"
                "        return true\n"
                "    return false\n"
            ),
            "reference_code": (
                "def in_closed_annulus(x: int, y: int, r_in: int, r_out: int) -> bool:\n"
                "    d2 = x * x + y * y\n"
                "    if d2 >= r_in * r_in and d2 <= r_out * r_out:\n"
                "        return True\n"
                "    return False\n"
            ),
            "test_vectors": [
                ((3, 4, 5, 6), True),
                ((1, 1, 2, 5), False),
                ((0, 0, 0, 0), True),
                ((0, 5, 3, 5), True),
                ((0, 6, 3, 5), False),
                ((-3, -4, 4, 5), True),
                ((2, 2, 3, 4), False),
                ((6, 8, 10, 10), True),
            ],
        },
        {
            "task_id": "C1_12",
            "category": "cat1_syntax_import",
            "fn_name": "grade_band",
            "broken_code": (
                "def grade_band(score: int) -> str:\n"
                '    """Map integer score to band: >=90 A, >=80 B, >=70 C, >=60 D, else F.\n'
                "    >>> grade_band(85)\n"
                "    'B'\n"
                "    >>> grade_band(59)\n"
                "    'F'\n"
                '    """\n'
                "    if score >= 90:\n"
                "        return 'A'\n"
                "    else if score >= 80:\n"
                "        return 'B'\n"
                "    else if score >= 70:\n"
                "        return 'C'\n"
                "    else if score >= 60:\n"
                "        return 'D'\n"
                "    return 'F'\n"
            ),
            "reference_code": (
                "def grade_band(score: int) -> str:\n"
                "    if score >= 90:\n"
                "        return 'A'\n"
                "    elif score >= 80:\n"
                "        return 'B'\n"
                "    elif score >= 70:\n"
                "        return 'C'\n"
                "    elif score >= 60:\n"
                "        return 'D'\n"
                "    return 'F'\n"
            ),
            "test_vectors": [
                ((95,), "A"),
                ((90,), "A"),
                ((89,), "B"),
                ((80,), "B"),
                ((75,), "C"),
                ((60,), "D"),
                ((59,), "F"),
                ((0,), "F"),
            ],
        },
        {
            "task_id": "C1_13",
            "category": "cat1_syntax_import",
            "fn_name": "first_zero_idx",
            "broken_code": (
                "def first_zero_idx(arr: list[int]) -> int | None:\n"
                '    """Return first index i where arr[i] == 0, or None if absent.\n'
                "    >>> first_zero_idx([4, 2, 0, 0])\n"
                "    2\n"
                "    >>> first_zero_idx([1, 3]) is None\n"
                "    True\n"
                '    """\n'
                "    for idx, val in enumerate(arr):\n"
                "        if val == 0:\n"
                "            return idx\n"
                "    return null\n"
            ),
            "reference_code": (
                "def first_zero_idx(arr: list[int]) -> int | None:\n"
                "    for idx, val in enumerate(arr):\n"
                "        if val == 0:\n"
                "            return idx\n"
                "    return None\n"
            ),
            "test_vectors": [
                (([4, 2, 0, 0],), 2),
                (([1, 3],), None),
                (([],), None),
                (([0],), 0),
                (([-1, -2, 0],), 2),
                (([0, 1, 2],), 0),
                (([5, 4, 3, 2, 1],), None),
                (([9, 8, 7, 0, 6],), 3),
            ],
        },
        {
            "task_id": "C1_14",
            "category": "cat1_syntax_import",
            "fn_name": "prefix_sums",
            "broken_code": (
                "def prefix_sums(nums: list[int]) -> list[int]:\n"
                '    """Return running cumulative sums of nums.\n'
                "    >>> prefix_sums([1, 2, 3, 4])\n"
                "    [1, 3, 6, 10]\n"
                "    >>> prefix_sums([])\n"
                "    []\n"
                '    """\n'
                "    out: list[int] = []\n"
                "    running = 0\n"
                "    for x in nums:\n"
                "    running += x\n"
                "        out.append(running)\n"
                "    return out\n"
            ),
            "reference_code": (
                "def prefix_sums(nums: list[int]) -> list[int]:\n"
                "    out: list[int] = []\n"
                "    running = 0\n"
                "    for x in nums:\n"
                "        running += x\n"
                "        out.append(running)\n"
                "    return out\n"
            ),
            "test_vectors": [
                (([1, 2, 3, 4],), [1, 3, 6, 10]),
                (([],), []),
                (([5],), [5]),
                (([1, -1, 1, -1],), [1, 0, 1, 0]),
                (([0, 0, 0],), [0, 0, 0]),
                (([-3, -2, -1],), [-3, -5, -6]),
                (([10, 20, -5, 15],), [10, 30, 25, 40]),
                (([100, -100],), [100, 0]),
            ],
        },
        {
            "task_id": "C1_15",
            "category": "cat1_syntax_import",
            "fn_name": "count_strict_peaks",
            "broken_code": (
                "def count_strict_peaks(xs: list[int]) -> int:\n"
                '    """Count interior elements strictly greater than both immediate neighbors.\n'
                "    >>> count_strict_peaks([1, 3, 2, 4, 1])\n"
                "    2\n"
                "    >>> count_strict_peaks([1, 2, 2, 1])\n"
                "    0\n"
                '    """\n'
                "    peaks = 0\n"
                "    for i in range(1, len(xs) - 1):\n"
                "        if xs[i] > xs[i - 1] and xs[i] > xs[i + 1]:\n"
                "        peaks += 1\n"
                "    return peaks\n"
            ),
            "reference_code": (
                "def count_strict_peaks(xs: list[int]) -> int:\n"
                "    peaks = 0\n"
                "    for i in range(1, len(xs) - 1):\n"
                "        if xs[i] > xs[i - 1] and xs[i] > xs[i + 1]:\n"
                "            peaks += 1\n"
                "    return peaks\n"
            ),
            "test_vectors": [
                (([1, 3, 2, 4, 1],), 2),
                (([1, 2, 2, 1],), 0),
                (([],), 0),
                (([5, 10],), 0),
                (([1, 5, 1],), 1),
                (([5, 1, 5],), 0),
                (([0, 2, 0, 3, 0, 4, 0],), 3),
                (([1, 2, 3, 4, 5],), 0),
            ],
        },
        {
            "task_id": "C1_16",
            "category": "cat1_syntax_import",
            "fn_name": "dot_product_checked",
            "broken_code": (
                "def dot_product_checked(u: list[int], v: list[int]) -> int:\n"
                '    """Return integer dot product of equal-length vectors u and v.\n'
                "    >>> dot_product_checked([1, 2, 3], [4, 5, 6])\n"
                "    32\n"
                "    >>> dot_product_checked([], [])\n"
                "    0\n"
                '    """\n'
                "    if len(u) != len(v):\n"
                "        raise ValueError('mismatch')\n"
                "    total = 0\n"
                "    for a, b in zip(u, v):\n"
                "        total += a * b\n"
                "        return total\n"
            ),
            "reference_code": (
                "def dot_product_checked(u: list[int], v: list[int]) -> int:\n"
                "    if len(u) != len(v):\n"
                "        raise ValueError('mismatch')\n"
                "    total = 0\n"
                "    for a, b in zip(u, v):\n"
                "        total += a * b\n"
                "    return total\n"
            ),
            "test_vectors": [
                (([1, 2, 3], [4, 5, 6]), 32),
                (([], []), 0),
                (([5], [7]), 35),
                (([1, -1, 2], [3, 3, 0]), 0),
                (([0, 10, 20], [5, 0, 2]), 40),
                (([-2, -3], [-4, -5]), 23),
                (([2, 3, 4, 5], [1, 1, 1, 1]), 14),
                (([10, 0, -10], [3, 99, 3]), 0),
            ],
        },
        {
            "task_id": "C1_17",
            "category": "cat1_syntax_import",
            "fn_name": "integer_hypot_ceil",
            "broken_code": (
                "def integer_hypot_ceil(dx: int, dy: int) -> int:\n"
                '    """Return ceiling of Euclidean norm sqrt(dx^2 + dy^2) as exact integer for |dx|,|dy| <= 10^6.\n'
                "    >>> integer_hypot_ceil(3, 4)\n"
                "    5\n"
                "    >>> integer_hypot_ceil(1, 1)\n"
                "    2\n"
                '    """\n'
                "    n2 = dx * dx + dy * dy\n"
                "    r = math.isqrt(n2)\n"
                "    return r if r * r == n2 else r + 1\n"
            ),
            "reference_code": (
                "import math\n\n"
                "def integer_hypot_ceil(dx: int, dy: int) -> int:\n"
                "    n2 = dx * dx + dy * dy\n"
                "    r = math.isqrt(n2)\n"
                "    return r if r * r == n2 else r + 1\n"
            ),
            "test_vectors": [
                ((3, 4), 5),
                ((1, 1), 2),
                ((0, 0), 0),
                ((0, -7), 7),
                ((-5, 12), 13),
                ((2, 2), 3),
                ((8, 15), 17),
                ((10, 10), 15),
            ],
        },
        {
            "task_id": "C1_18",
            "category": "cat1_syntax_import",
            "fn_name": "top_k_smallest",
            "broken_code": (
                "def top_k_smallest(nums: list[int], k: int) -> list[int]:\n"
                '    """Return the k smallest elements of nums in ascending order.\n'
                "    >>> top_k_smallest([9, 1, 5, 3, 7], 3)\n"
                "    [1, 3, 5]\n"
                "    >>> top_k_smallest([4, 2], 0)\n"
                "    []\n"
                '    """\n'
                "    if k <= 0:\n"
                "        return []\n"
                "    return heapq.nsmallest(k, nums)\n"
            ),
            "reference_code": (
                "import heapq\n\n"
                "def top_k_smallest(nums: list[int], k: int) -> list[int]:\n"
                "    if k <= 0:\n"
                "        return []\n"
                "    return heapq.nsmallest(k, nums)\n"
            ),
            "test_vectors": [
                (([9, 1, 5, 3, 7], 3), [1, 3, 5]),
                (([4, 2], 0), []),
                (([], 5), []),
                (([5, 5, 1, 1], 3), [1, 1, 5]),
                (([-3, -10, 0, 8], 2), [-10, -3]),
                (([7, 2, 9], 10), [2, 7, 9]),
                (([42], 1), [42]),
                (([10, 9, 8, 7, 6, 5], 4), [5, 6, 7, 8]),
            ],
        },
        {
            "task_id": "C1_19",
            "category": "cat1_syntax_import",
            "fn_name": "count_in_closed_range",
            "broken_code": (
                "def count_in_closed_range(sorted_nums: list[int], lo: int, hi: int) -> int:\n"
                '    """Given ascending sorted_nums, count elements x satisfying lo <= x <= hi in O(log n).\n'
                "    >>> count_in_closed_range([1, 2, 4, 4, 7, 9], 2, 7)\n"
                "    4\n"
                "    >>> count_in_closed_range([1, 3, 5], 6, 10)\n"
                "    0\n"
                '    """\n'
                "    if lo > hi:\n"
                "        return 0\n"
                "    left = bisect.bisect_left(sorted_nums, lo)\n"
                "    right = bisect.bisect_right(sorted_nums, hi)\n"
                "    return right - left\n"
            ),
            "reference_code": (
                "import bisect\n\n"
                "def count_in_closed_range(sorted_nums: list[int], lo: int, hi: int) -> int:\n"
                "    if lo > hi:\n"
                "        return 0\n"
                "    left = bisect.bisect_left(sorted_nums, lo)\n"
                "    right = bisect.bisect_right(sorted_nums, hi)\n"
                "    return right - left\n"
            ),
            "test_vectors": [
                (([1, 2, 4, 4, 7, 9], 2, 7), 4),
                (([1, 3, 5], 6, 10), 0),
                (([], 0, 5), 0),
                (([2, 2, 2, 2], 2, 2), 4),
                (([1, 5, 10], 8, 3), 0),
                (([-10, -5, 0, 5, 10], -5, 5), 3),
                (([1, 2, 3, 4, 5], 0, 10), 5),
                (([1, 2, 3, 4, 5], -5, 0), 0),
            ],
        },
        {
            "task_id": "C1_20",
            "category": "cat1_syntax_import",
            "fn_name": "most_frequent_int",
            "broken_code": (
                "def most_frequent_int(nums: list[int]) -> int:\n"
                '    """Return element with highest frequency in non-empty nums; break ties by smallest integer.\n'
                "    >>> most_frequent_int([3, 1, 3, 1, 2])\n"
                "    1\n"
                "    >>> most_frequent_int([4, 4, 2])\n"
                "    4\n"
                '    """\n'
                "    counts = Counter(nums)\n"
                "    return min(counts.keys(), key=lambda k: (-counts[k], k))\n"
            ),
            "reference_code": (
                "from collections import Counter\n\n"
                "def most_frequent_int(nums: list[int]) -> int:\n"
                "    counts = Counter(nums)\n"
                "    return min(counts.keys(), key=lambda k: (-counts[k], k))\n"
            ),
            "test_vectors": [
                (([3, 1, 3, 1, 2],), 1),
                (([4, 4, 2],), 4),
                (([7],), 7),
                (([-2, -5, -2, -5],), -5),
                (([0, 1, 2, 3],), 0),
                (([9, 8, 9, 8, 8],), 8),
                (([10, 10, 20, 20, 5, 5],), 5),
                (([-1, -1, -1, 0, 0],), -1),
            ],
        },

        # =====================================================================
        # CATEGORY 2: 20 Scope / Binding / Mutable-Default / Coercion / API Bugs
        # =====================================================================
        {
            "task_id": "C2_01",
            "category": "cat2_scope_type_api",
            "fn_name": "weighted_dot",
            "broken_code": (
                "def weighted_dot(values: list[int], weights: list[int], scale_factor: int) -> int:\n"
                '    """Compute scale_factor * sum(v * w for v, w in zip(values, weights)).\n'
                "    >>> weighted_dot([1, 2, 3], [4, 5, 6], 2)\n"
                "    64\n"
                "    >>> weighted_dot([], [], 5)\n"
                "    0\n"
                '    """\n'
                "    acc = sum(v * w for v, w in zip(values, weights))\n"
                "    return acc * scale_fctor\n"
            ),
            "reference_code": (
                "def weighted_dot(values: list[int], weights: list[int], scale_factor: int) -> int:\n"
                "    acc = sum(v * w for v, w in zip(values, weights))\n"
                "    return acc * scale_factor\n"
            ),
            "test_vectors": [
                (([1, 2, 3], [4, 5, 6], 2), 64),
                (([], [], 5), 0),
                (([3, -1], [2, 6], 10), 0),
                (([5], [4], -3), -60),
                (([1, 1, 1], [2, 3, 4], 0), 0),
                (([-2, 4], [-3, 5], 3), 78),
                (([10, 20], [1, 2], 1), 50),
                (([7, 8, 9], [0, 1, 0], 4), 32),
            ],
        },
        {
            "task_id": "C2_02",
            "category": "cat2_scope_type_api",
            "fn_name": "normalize_whitespace_tokens",
            "broken_code": (
                "def normalize_whitespace_tokens(sentence: str) -> str:\n"
                '    """Collapse runs of whitespace to single spaces and strip ends.\n'
                "    >>> normalize_whitespace_tokens('  hello   world\\tfoo  ')\n"
                "    'hello world foo'\n"
                "    >>> normalize_whitespace_tokens('   ')\n"
                "    ''\n"
                '    """\n'
                "    cleaned_parts = sentence.split()\n"
                "    return ' '.join(cleaned_prts)\n"
            ),
            "reference_code": (
                "def normalize_whitespace_tokens(sentence: str) -> str:\n"
                "    cleaned_parts = sentence.split()\n"
                "    return ' '.join(cleaned_parts)\n"
            ),
            "test_vectors": [
                (("  hello   world\tfoo  ",), "hello world foo"),
                (("   ",), ""),
                (("",), ""),
                (("single",), "single"),
                (("a\nb\rc",), "a b c"),
                (("  x  ",), "x"),
                (("one two three",), "one two three"),
                (("\t\n alpha   beta \n",), "alpha beta"),
            ],
        },
        {
            "task_id": "C2_03",
            "category": "cat2_scope_type_api",
            "fn_name": "harmonic_floor",
            "broken_code": (
                "def harmonic_floor(numerators: list[int], denom_val: int) -> list[int]:\n"
                '    """Return [x // denom_val for x in numerators] for positive denom_val.\n'
                "    >>> harmonic_floor([10, 25, 3], 4)\n"
                "    [2, 6, 0]\n"
                "    >>> harmonic_floor([], 7)\n"
                "    []\n"
                '    """\n'
                "    return [x // denom_vl for x in numerators]\n"
            ),
            "reference_code": (
                "def harmonic_floor(numerators: list[int], denom_val: int) -> list[int]:\n"
                "    return [x // denom_val for x in numerators]\n"
            ),
            "test_vectors": [
                (([10, 25, 3], 4), [2, 6, 0]),
                (([], 7), []),
                (([0, 5, 10], 5), [0, 1, 2]),
                (([-5, -4, 4], 4), [-2, -1, 1]),
                (([100], 1), [100]),
                (([7, 8, 9], 3), [2, 2, 3]),
                (([1, 2, 3], 10), [0, 0, 0]),
                (([99, 100, 101], 10), [9, 10, 10]),
            ],
        },
        {
            "task_id": "C2_04",
            "category": "cat2_scope_type_api",
            "fn_name": "bounded_step_walk",
            "broken_code": (
                "def bounded_step_walk(deltas: list[int], max_abs: int) -> int:\n"
                '    """Start at 0; add each d in deltas clamped to [-max_abs, max_abs] at every step.\n'
                "    >>> bounded_step_walk([4, 5, -20, 3], 6)\n"
                "    -3\n"
                "    >>> bounded_step_walk([], 10)\n"
                "    0\n"
                '    """\n'
                "    pos_curr = 0\n"
                "    for d in deltas:\n"
                "        pos_curr = max(-max_abs, min(max_abs, pos_curr + d))\n"
                "    return pos_cur\n"
            ),
            "reference_code": (
                "def bounded_step_walk(deltas: list[int], max_abs: int) -> int:\n"
                "    pos_curr = 0\n"
                "    for d in deltas:\n"
                "        pos_curr = max(-max_abs, min(max_abs, pos_curr + d))\n"
                "    return pos_curr\n"
            ),
            "test_vectors": [
                (([4, 5, -20, 3], 6), -3),
                (([], 10), 0),
                (([100], 5), 5),
                (([-100], 5), -5),
                (([2, 2, 2, -3], 5), 2),
                (([1, -1, 1, -1], 1), 0),
                (([5, 5, -10, -5], 8), -7),
                (([0, 0, 0], 0), 0),
            ],
        },
        {
            "task_id": "C2_05",
            "category": "cat2_scope_type_api",
            "fn_name": "append_non_negative",
            "broken_code": (
                "def append_non_negative(items: list[int], acc: list[int] = []) -> list[int]:\n"
                '    """Return a list containing acc followed by non-negative elements of items.\n'
                "    Repeated calls without acc must remain independent (no shared state leak).\n"
                "    >>> append_non_negative([-1, 2, 0, -3, 5])\n"
                "    [2, 0, 5]\n"
                "    >>> append_non_negative([4], [10])\n"
                "    [10, 4]\n"
                '    """\n'
                "    for x in items:\n"
                "        if x >= 0:\n"
                "            acc.append(x)\n"
                "    return list(acc)\n"
            ),
            "reference_code": (
                "def append_non_negative(items: list[int], acc: list[int] | None = None) -> list[int]:\n"
                "    if acc is None:\n"
                "        acc = []\n"
                "    else:\n"
                "        acc = list(acc)\n"
                "    for x in items:\n"
                "        if x >= 0:\n"
                "            acc.append(x)\n"
                "    return acc\n"
            ),
            "test_vectors": [
                (([-1, 2, 0, -3, 5],), [2, 0, 5]),
                (([1, -2],), [1]),
                (([],), []),
                (([-5, -6],), []),
                (([4], [10]), [10, 4]),
                (([0, 0],), [0, 0]),
                (([7, 8], [1, 2]), [1, 2, 7, 8]),
                (([3],), [3]),
            ],
        },
        {
            "task_id": "C2_06",
            "category": "cat2_scope_type_api",
            "fn_name": "dedup_preserve_order",
            "broken_code": (
                "def dedup_preserve_order(seq: list[int], seen: set[int] = set()) -> list[int]:\n"
                '    """Deduplicate seq preserving first-seen order; fresh seen set per default call.\n'
                "    >>> dedup_preserve_order([3, 1, 3, 2, 1])\n"
                "    [3, 1, 2]\n"
                "    >>> dedup_preserve_order([1, 2])\n"
                "    [1, 2]\n"
                '    """\n'
                "    out: list[int] = []\n"
                "    for x in seq:\n"
                "        if x not in seen:\n"
                "            seen.add(x)\n"
                "            out.append(x)\n"
                "    return out\n"
            ),
            "reference_code": (
                "def dedup_preserve_order(seq: list[int], seen: set[int] | None = None) -> list[int]:\n"
                "    seen = set() if seen is None else set(seen)\n"
                "    out: list[int] = []\n"
                "    for x in seq:\n"
                "        if x not in seen:\n"
                "            seen.add(x)\n"
                "            out.append(x)\n"
                "    return out\n"
            ),
            "test_vectors": [
                (([3, 1, 3, 2, 1],), [3, 1, 2]),
                (([1, 2],), [1, 2]),
                (([],), []),
                (([5, 5, 5],), [5]),
                (([-1, 0, -1, 2, 0],), [-1, 0, 2]),
                (([1, 2, 3], {2}), [1, 3]),
                (([9, 8, 9],), [9, 8]),
                (([0],), [0]),
            ],
        },
        {
            "task_id": "C2_07",
            "category": "cat2_scope_type_api",
            "fn_name": "tally_words",
            "broken_code": (
                "def tally_words(words: list[str], base: dict[str, int] = {}) -> dict[str, int]:\n"
                '    """Count occurrences of words starting from optional base counts without mutating default.\n'
                "    >>> tally_words(['a', 'b', 'a'])\n"
                "    {'a': 2, 'b': 1}\n"
                "    >>> tally_words(['b'])\n"
                "    {'b': 1}\n"
                '    """\n'
                "    for w in words:\n"
                "        base[w] = base.get(w, 0) + 1\n"
                "    return dict(base)\n"
            ),
            "reference_code": (
                "def tally_words(words: list[str], base: dict[str, int] | None = None) -> dict[str, int]:\n"
                "    res = {} if base is None else dict(base)\n"
                "    for w in words:\n"
                "        res[w] = res.get(w, 0) + 1\n"
                "    return res\n"
            ),
            "test_vectors": [
                ((["a", "b", "a"],), {"a": 2, "b": 1}),
                ((["b"],), {"b": 1}),
                (([],), {}),
                ((["x", "x", "x"],), {"x": 3}),
                ((["k"], {"k": 5}), {"k": 6}),
                ((["p", "q"],), {"p": 1, "q": 1}),
                ((["z"], {}), {"z": 1}),
                ((["m", "n", "m"],), {"m": 2, "n": 1}),
            ],
        },
        {
            "task_id": "C2_08",
            "category": "cat2_scope_type_api",
            "fn_name": "sort_by_abs_then_val",
            "broken_code": (
                "def sort_by_abs_then_val(nums: list[int]) -> list[int]:\n"
                '    """Return a new list sorted ascending by (abs(x), x).\n'
                "    >>> sort_by_abs_then_val([3, -1, 1, -3, 0])\n"
                "    [0, -1, 1, -3, 3]\n"
                "    >>> sort_by_abs_then_val([])\n"
                "    []\n"
                '    """\n'
                "    copy = list(nums)\n"
                "    return copy.sort(key=lambda x: (abs(x), x))\n"
            ),
            "reference_code": (
                "def sort_by_abs_then_val(nums: list[int]) -> list[int]:\n"
                "    return sorted(nums, key=lambda x: (abs(x), x))\n"
            ),
            "test_vectors": [
                (([3, -1, 1, -3, 0],), [0, -1, 1, -3, 3]),
                (([],), []),
                (([5],), [5]),
                (([-2, 2, -2],), [-2, -2, 2]),
                (([10, -5, 4, -1],), [-1, 4, -5, 10]),
                (([0, 0],), [0, 0]),
                (([-7, -3, -1],), [-1, -3, -7]),
                (([2, -2, 1, -1],), [-1, 1, -2, 2]),
            ],
        },
        {
            "task_id": "C2_09",
            "category": "cat2_scope_type_api",
            "fn_name": "reverse_even_positions",
            "broken_code": (
                "def reverse_even_positions(nums: list[int]) -> list[int]:\n"
                '    """Extract elements at even indices (0, 2, 4, ...) and return them in reverse order.\n'
                "    >>> reverse_even_positions([10, 11, 20, 21, 30])\n"
                "    [30, 20, 10]\n"
                "    >>> reverse_even_positions([])\n"
                "    []\n"
                '    """\n'
                "    evens = nums[::2]\n"
                "    return evens.reverse()\n"
            ),
            "reference_code": (
                "def reverse_even_positions(nums: list[int]) -> list[int]:\n"
                "    evens = nums[::2]\n"
                "    return list(reversed(evens))\n"
            ),
            "test_vectors": [
                (([10, 11, 20, 21, 30],), [30, 20, 10]),
                (([],), []),
                (([42],), [42]),
                (([1, 2],), [1]),
                (([1, 2, 3, 4],), [3, 1]),
                (([5, 6, 7, 8, 9, 10],), [9, 7, 5]),
                (([-1, 0, -2, 0, -3],), [-3, -2, -1]),
                (([0, 1, 0, 1],), [0, 0]),
            ],
        },
        {
            "task_id": "C2_10",
            "category": "cat2_scope_type_api",
            "fn_name": "sort_descending_unique",
            "broken_code": (
                "def sort_descending_unique(nums: list[int]) -> list[int]:\n"
                '    """Return unique integers of nums sorted in strictly descending order.\n'
                "    >>> sort_descending_unique([4, 1, 4, 9, 2])\n"
                "    [9, 4, 2, 1]\n"
                "    >>> sort_descending_unique([])\n"
                "    []\n"
                '    """\n'
                "    uniq = list(set(nums))\n"
                "    return uniq.sort(reverse=True)\n"
            ),
            "reference_code": (
                "def sort_descending_unique(nums: list[int]) -> list[int]:\n"
                "    return sorted(set(nums), reverse=True)\n"
            ),
            "test_vectors": [
                (([4, 1, 4, 9, 2],), [9, 4, 2, 1]),
                (([],), []),
                (([0, 0, 0],), [0]),
                (([-5, -1, -3, -1],), [-1, -3, -5]),
                (([7],), [7]),
                (([1, 2, 3, 4],), [4, 3, 2, 1]),
                (([10, -10, 0],), [10, 0, -10]),
                (([8, 8, 9, 9, 7],), [9, 8, 7]),
            ],
        },
        {
            "task_id": "C2_11",
            "category": "cat2_scope_type_api",
            "fn_name": "midpoint_floor",
            "broken_code": (
                "def midpoint_floor(lo: int, hi: int) -> int:\n"
                '    """Return exact integer floor((lo + hi) / 2).\n'
                "    >>> midpoint_floor(3, 8)\n"
                "    5\n"
                "    >>> midpoint_floor(-5, -2)\n"
                "    -4\n"
                '    """\n'
                "    return (lo + hi) / 2\n"
            ),
            "reference_code": (
                "def midpoint_floor(lo: int, hi: int) -> int:\n"
                "    return (lo + hi) // 2\n"
            ),
            "test_vectors": [
                ((3, 8), 5),
                ((-5, -2), -4),
                ((0, 0), 0),
                ((0, 1), 0),
                ((-1, 0), -1),
                ((10, 20), 15),
                ((10**18, 10**18 + 2), 10**18 + 1),
                ((-100, 101), 0),
            ],
        },
        {
            "task_id": "C2_12",
            "category": "cat2_scope_type_api",
            "fn_name": "triangular_number",
            "broken_code": (
                "def triangular_number(n: int) -> int:\n"
                '    """Return exact integer n * (n + 1) // 2 for n >= 0 (even for n > 10^16).\n'
                "    >>> triangular_number(10)\n"
                "    55\n"
                "    >>> triangular_number(0)\n"
                "    0\n"
                '    """\n'
                "    return (n * (n + 1)) / 2\n"
            ),
            "reference_code": (
                "def triangular_number(n: int) -> int:\n"
                "    return (n * (n + 1)) // 2\n"
            ),
            "test_vectors": [
                ((0,), 0),
                ((1,), 1),
                ((10,), 55),
                ((100,), 5050),
                ((999,), 499500),
                ((10**10,), (10**10 * (10**10 + 1)) // 2),
                ((10**17 + 1,), ((10**17 + 1) * (10**17 + 2)) // 2),
                ((7,), 28),
            ],
        },
        {
            "task_id": "C2_13",
            "category": "cat2_scope_type_api",
            "fn_name": "ceil_div_pos",
            "broken_code": (
                "def ceil_div_pos(a: int, b: int) -> int:\n"
                '    """Return exact integer ceiling(a / b) for a >= 0 and b > 0.\n'
                "    >>> ceil_div_pos(10, 3)\n"
                "    4\n"
                "    >>> ceil_div_pos(12, 3)\n"
                "    4\n"
                '    """\n'
                "    return (a + b - 1) / b\n"
            ),
            "reference_code": (
                "def ceil_div_pos(a: int, b: int) -> int:\n"
                "    return (a + b - 1) // b\n"
            ),
            "test_vectors": [
                ((10, 3), 4),
                ((12, 3), 4),
                ((0, 5), 0),
                ((1, 5), 1),
                ((5, 5), 1),
                ((6, 5), 2),
                ((10**18 + 1, 2), (10**18 + 2) // 2),
                ((99, 10), 10),
            ],
        },
        {
            "task_id": "C2_14",
            "category": "cat2_scope_type_api",
            "fn_name": "squares_of_evens",
            "broken_code": (
                "def squares_of_evens(nums: list[int]) -> list[int]:\n"
                '    """Return a concrete list of x*x for every even integer x in nums.\n'
                "    >>> squares_of_evens([1, 2, 3, 4, -6])\n"
                "    [4, 16, 36]\n"
                "    >>> squares_of_evens([1, 3])\n"
                "    []\n"
                '    """\n'
                "    return (x * x for x in nums if x % 2 == 0)\n"
            ),
            "reference_code": (
                "def squares_of_evens(nums: list[int]) -> list[int]:\n"
                "    return [x * x for x in nums if x % 2 == 0]\n"
            ),
            "test_vectors": [
                (([1, 2, 3, 4, -6],), [4, 16, 36]),
                (([1, 3],), []),
                (([],), []),
                (([0],), [0]),
                (([-2, -4],), [4, 16]),
                (([2, 2, 2],), [4, 4, 4]),
                (([5, 10, 15, 20],), [100, 400]),
                (([8],), [64]),
            ],
        },
        {
            "task_id": "C2_15",
            "category": "cat2_scope_type_api",
            "fn_name": "pairwise_sums",
            "broken_code": (
                "def pairwise_sums(a: list[int], b: list[int]) -> list[int]:\n"
                '    """Return concrete list [x + y for x, y in zip(a, b)].\n'
                "    >>> pairwise_sums([1, 2, 3], [10, 20, 30])\n"
                "    [11, 22, 33]\n"
                "    >>> pairwise_sums([], [])\n"
                "    []\n"
                '    """\n'
                "    return map(lambda pair: pair[0] + pair[1], zip(a, b))\n"
            ),
            "reference_code": (
                "def pairwise_sums(a: list[int], b: list[int]) -> list[int]:\n"
                "    return list(map(lambda pair: pair[0] + pair[1], zip(a, b)))\n"
            ),
            "test_vectors": [
                (([1, 2, 3], [10, 20, 30]), [11, 22, 33]),
                (([], []), []),
                (([5], [-5]), [0]),
                (([1, 2], [10, 20, 30]), [11, 22]),
                (([-1, -2, -3], [1, 2, 3]), [0, 0, 0]),
                (([0, 0], [7, 8]), [7, 8]),
                (([100, 200], [300, 400]), [400, 600]),
                (([9, 8, 7, 6], [1, 2, 3, 4]), [10, 10, 10, 10]),
            ],
        },
        {
            "task_id": "C2_16",
            "category": "cat2_scope_type_api",
            "fn_name": "minmax_pair",
            "broken_code": (
                "def minmax_pair(nums: list[int]) -> tuple[int, int]:\n"
                '    """Return 2-tuple (min(nums), max(nums)) for non-empty nums.\n'
                "    >>> minmax_pair([4, -2, 9, 0])\n"
                "    (-2, 9)\n"
                "    >>> minmax_pair([7])\n"
                "    (7, 7)\n"
                '    """\n'
                "    return [min(nums), max(nums)]\n"
            ),
            "reference_code": (
                "def minmax_pair(nums: list[int]) -> tuple[int, int]:\n"
                "    return (min(nums), max(nums))\n"
            ),
            "test_vectors": [
                (([4, -2, 9, 0],), (-2, 9)),
                (([7],), (7, 7)),
                (([-10, -20, -5],), (-20, -5)),
                (([0, 0],), (0, 0)),
                (([100, 1],), (1, 100)),
                (([-1, 1],), (-1, 1)),
                (([3, 3, 2, 5, 5],), (2, 5)),
                (([999, -999, 0],), (-999, 999)),
            ],
        },
        {
            "task_id": "C2_17",
            "category": "cat2_scope_type_api",
            "fn_name": "format_csv_ints",
            "broken_code": (
                "def format_csv_ints(nums: list[int]) -> str:\n"
                '    """Join integers in nums with commas (no spaces).\n'
                "    >>> format_csv_ints([10, -2, 0, 7])\n"
                "    '10,-2,0,7'\n"
                "    >>> format_csv_ints([])\n"
                "    ''\n"
                '    """\n'
                "    return ','.join(nums)\n"
            ),
            "reference_code": (
                "def format_csv_ints(nums: list[int]) -> str:\n"
                "    return ','.join(map(str, nums))\n"
            ),
            "test_vectors": [
                (([10, -2, 0, 7],), "10,-2,0,7"),
                (([],), ""),
                (([42],), "42"),
                (([-1, -2, -3],), "-1,-2,-3"),
                (([0, 0],), "0,0"),
                (([1, 2, 3, 4, 5],), "1,2,3,4,5"),
                (([999999],), "999999"),
                (([5, -5],), "5,-5"),
            ],
        },
        {
            "task_id": "C2_18",
            "category": "cat2_scope_type_api",
            "fn_name": "collect_positive_divisors",
            "broken_code": (
                "def collect_positive_divisors(n: int) -> list[int]:\n"
                '    """Return sorted positive divisors of positive integer n.\n'
                "    >>> collect_positive_divisors(12)\n"
                "    [1, 2, 3, 4, 6, 12]\n"
                "    >>> collect_positive_divisors(1)\n"
                "    [1]\n"
                '    """\n'
                "    divs: list[int] = []\n"
                "    d = 1\n"
                "    while d * d <= n:\n"
                "        if n % d == 0:\n"
                "            divs.push(d)\n"
                "            if d * d != n:\n"
                "                divs.push(n // d)\n"
                "        d += 1\n"
                "    return sorted(divs)\n"
            ),
            "reference_code": (
                "def collect_positive_divisors(n: int) -> list[int]:\n"
                "    divs: list[int] = []\n"
                "    d = 1\n"
                "    while d * d <= n:\n"
                "        if n % d == 0:\n"
                "            divs.append(d)\n"
                "            if d * d != n:\n"
                "                divs.append(n // d)\n"
                "        d += 1\n"
                "    return sorted(divs)\n"
            ),
            "test_vectors": [
                ((12,), [1, 2, 3, 4, 6, 12]),
                ((1,), [1]),
                ((2,), [1, 2]),
                ((16,), [1, 2, 4, 8, 16]),
                ((17,), [1, 17]),
                ((36,), [1, 2, 3, 4, 6, 9, 12, 18, 36]),
                ((28,), [1, 2, 4, 7, 14, 28]),
                ((25,), [1, 5, 25]),
            ],
        },
        {
            "task_id": "C2_19",
            "category": "cat2_scope_type_api",
            "fn_name": "distinct_modulo_residues",
            "broken_code": (
                "def distinct_modulo_residues(nums: list[int], mod: int) -> int:\n"
                '    """Return count of distinct residues (x % mod) across nums for mod > 0.\n'
                "    >>> distinct_modulo_residues([1, 4, 7, 2, 5], 3)\n"
                "    2\n"
                "    >>> distinct_modulo_residues([], 5)\n"
                "    0\n"
                '    """\n'
                "    seen: set[int] = set()\n"
                "    for x in nums:\n"
                "        seen.append(x % mod)\n"
                "    return len(seen)\n"
            ),
            "reference_code": (
                "def distinct_modulo_residues(nums: list[int], mod: int) -> int:\n"
                "    seen: set[int] = set()\n"
                "    for x in nums:\n"
                "        seen.add(x % mod)\n"
                "    return len(seen)\n"
            ),
            "test_vectors": [
                (([1, 4, 7, 2, 5], 3), 2),
                (([], 5), 0),
                (([0, 5, 10, -5], 5), 1),
                (([0, 1, 2, 3, 4], 5), 5),
                (([-1, 4, 9], 5), 1),
                (([2, 4, 6, 8], 4), 2),
                (([7], 1), 1),
                (([1, 2, 3, 4, 5, 6], 4), 4),
            ],
        },
        {
            "task_id": "C2_20",
            "category": "cat2_scope_type_api",
            "fn_name": "saturate_scalar",
            "broken_code": (
                "def saturate_scalar(x: int, lo: int, hi: int) -> int:\n"
                '    """Clamp integer x into closed interval [lo, hi] (given lo <= hi).\n'
                "    >>> saturate_scalar(15, 0, 10)\n"
                "    10\n"
                "    >>> saturate_scalar(-3, 0, 10)\n"
                "    0\n"
                '    """\n'
                "    return max(hi, min(lo, x))\n"
            ),
            "reference_code": (
                "def saturate_scalar(x: int, lo: int, hi: int) -> int:\n"
                "    return min(hi, max(lo, x))\n"
            ),
            "test_vectors": [
                ((15, 0, 10), 10),
                ((-3, 0, 10), 0),
                ((5, 0, 10), 5),
                ((0, 0, 0), 0),
                ((-10, -5, -1), -5),
                ((0, -5, -1), -1),
                ((7, 7, 7), 7),
                ((-100, -50, 50), -50),
            ],
        },

        # =====================================================================
        # CATEGORY 3: 20 Algorithmic / Boundary / State-Machine Logic Bugs
        # =====================================================================
        {
            "task_id": "C3_01",
            "category": "cat3_algo_state_logic",
            "fn_name": "tarjan_scc_sizes",
            "broken_code": (
                "def tarjan_scc_sizes(n: int, edges: list[tuple[int, int]]) -> list[int]:\n"
                '    """Return sorted sizes of all Strongly Connected Components in directed graph 0..n-1.\n'
                "    >>> tarjan_scc_sizes(4, [(0, 1), (1, 2), (2, 0), (2, 3)])\n"
                "    [1, 3]\n"
                "    >>> tarjan_scc_sizes(0, [])\n"
                "    []\n"
                '    """\n'
                "    adj = [[] for _ in range(n)]\n"
                "    for u, v in edges:\n"
                "        adj[u].append(v)\n"
                "    disc = [-1] * n\n"
                "    low = [0] * n\n"
                "    on_stack = [False] * n\n"
                "    st: list[int] = []\n"
                "    timer = 0\n"
                "    sizes: list[int] = []\n"
                "    def dfs(u: int) -> None:\n"
                "        nonlocal timer\n"
                "        disc[u] = low[u] = timer\n"
                "        timer += 1\n"
                "        st.append(u)\n"
                "        on_stack[u] = True\n"
                "        for v in adj[u]:\n"
                "            if disc[v] == -1:\n"
                "                dfs(v)\n"
                "                low[u] = min(low[u], low[v])\n"
                "            elif not on_stack[v]:\n"
                "                low[u] = min(low[u], disc[v])\n"
                "        if low[u] == disc[u]:\n"
                "            cnt = 0\n"
                "            while True:\n"
                "                w = st.pop()\n"
                "                on_stack[w] = False\n"
                "                cnt += 1\n"
                "                if w == u:\n"
                "                    break\n"
                "            sizes.append(cnt)\n"
                "    for i in range(n):\n"
                "        if disc[i] == -1:\n"
                "            dfs(i)\n"
                "    return sorted(sizes)\n"
            ),
            "reference_code": (
                "def tarjan_scc_sizes(n: int, edges: list[tuple[int, int]]) -> list[int]:\n"
                "    adj = [[] for _ in range(n)]\n"
                "    for u, v in edges:\n"
                "        adj[u].append(v)\n"
                "    disc = [-1] * n\n"
                "    low = [0] * n\n"
                "    on_stack = [False] * n\n"
                "    st: list[int] = []\n"
                "    timer = 0\n"
                "    sizes: list[int] = []\n"
                "    def dfs(u: int) -> None:\n"
                "        nonlocal timer\n"
                "        disc[u] = low[u] = timer\n"
                "        timer += 1\n"
                "        st.append(u)\n"
                "        on_stack[u] = True\n"
                "        for v in adj[u]:\n"
                "            if disc[v] == -1:\n"
                "                dfs(v)\n"
                "                low[u] = min(low[u], low[v])\n"
                "            elif on_stack[v]:\n"
                "                low[u] = min(low[u], disc[v])\n"
                "        if low[u] == disc[u]:\n"
                "            cnt = 0\n"
                "            while True:\n"
                "                w = st.pop()\n"
                "                on_stack[w] = False\n"
                "                cnt += 1\n"
                "                if w == u:\n"
                "                    break\n"
                "            sizes.append(cnt)\n"
                "    for i in range(n):\n"
                "        if disc[i] == -1:\n"
                "            dfs(i)\n"
                "    return sorted(sizes)\n"
            ),
            "test_vectors": [
                ((4, [(0, 1), (1, 2), (2, 0), (2, 3)]), [1, 3]),
                ((0, []), []),
                ((3, []), [1, 1, 1]),
                ((4, [(0, 1), (1, 0), (2, 3), (3, 2), (0, 2)]), [2, 2]),
                ((5, [(0, 1), (1, 2), (2, 3), (3, 1), (2, 4), (4, 0)]), [5]),
                ((4, [(0, 1), (0, 2), (1, 3), (2, 3), (3, 3)]), [1, 1, 1, 1]),
                ((6, [(0, 1), (1, 2), (2, 0), (3, 4), (4, 5), (5, 3), (2, 3)]), [3, 3]),
                ((5, [(0, 2), (2, 1), (1, 0), (0, 3), (3, 4)]), [1, 1, 3]),
            ],
        },
        {
            "task_id": "C3_02",
            "category": "cat3_algo_state_logic",
            "fn_name": "true_damerau_levenshtein",
            "broken_code": (
                "def true_damerau_levenshtein(a: str, b: str) -> int:\n"
                '    """Compute unrestricted Damerau-Levenshtein distance (insert, delete, substitute,\n'
                "    and transposition of two characters even if edits occur between them, e.g. 'ca' -> 'abc' is 2).\n"
                "    >>> true_damerau_levenshtein('ca', 'abc')\n"
                "    2\n"
                "    >>> true_damerau_levenshtein('kitten', 'sitting')\n"
                "    3\n"
                '    """\n'
                "    m, n = len(a), len(b)\n"
                "    dp = [[0] * (n + 1) for _ in range(m + 1)]\n"
                "    for i in range(m + 1):\n"
                "        dp[i][0] = i\n"
                "    for j in range(n + 1):\n"
                "        dp[0][j] = j\n"
                "    for i in range(1, m + 1):\n"
                "        for j in range(1, n + 1):\n"
                "            cost = 0 if a[i - 1] == b[j - 1] else 1\n"
                "            dp[i][j] = min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost)\n"
                "            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:\n"
                "                dp[i][j] = min(dp[i][j], dp[i - 2][j - 2] + 1)\n"
                "    return dp[m][n]\n"
            ),
            "reference_code": (
                "def true_damerau_levenshtein(a: str, b: str) -> int:\n"
                "    m, n = len(a), len(b)\n"
                "    maxdist = m + n\n"
                "    da: dict[str, int] = {}\n"
                "    d = [[0] * (n + 2) for _ in range(m + 2)]\n"
                "    d[0][0] = maxdist\n"
                "    for i in range(m + 1):\n"
                "        d[i + 1][0] = maxdist\n"
                "        d[i + 1][1] = i\n"
                "    for j in range(n + 1):\n"
                "        d[0][j + 1] = maxdist\n"
                "        d[1][j + 1] = j\n"
                "    for i in range(1, m + 1):\n"
                "        db = 0\n"
                "        for j in range(1, n + 1):\n"
                "            k = da.get(b[j - 1], 0)\n"
                "            l = db\n"
                "            if a[i - 1] == b[j - 1]:\n"
                "                cost = 0\n"
                "                db = j\n"
                "            else:\n"
                "                cost = 1\n"
                "            d[i + 1][j + 1] = min(\n"
                "                d[i][j] + cost,\n"
                "                d[i + 1][j] + 1,\n"
                "                d[i][j + 1] + 1,\n"
                "                d[k][l] + (i - k - 1) + 1 + (j - l - 1),\n"
                "            )\n"
                "        da[a[i - 1]] = i\n"
                "    return d[m + 1][n + 1]\n"
            ),
            "test_vectors": [
                (("ca", "abc"), 2),
                (("abc", "ca"), 2),
                (("kitten", "sitting"), 3),
                (("", ""), 0),
                (("ab", "ba"), 1),
                (("abcd", "badc"), 2),
                (("cta", "actx"), 2),
                (("ba", "acb"), 2),
            ],
        },
        {
            "task_id": "C3_03",
            "category": "cat3_algo_state_logic",
            "fn_name": "dijkstra_min_hops",
            "broken_code": (
                "import heapq\n\n"
                "def dijkstra_min_hops(n: int, edges: list[tuple[int, int, int]], src: int, dst: int) -> tuple[int, int] | None:\n"
                '    """Return (min_cost, min_hops_among_min_cost_paths) from src to dst on non-negative directed graph,\n'
                "    or None if dst is unreachable.\n"
                "    >>> dijkstra_min_hops(5, [(0, 1, 1), (1, 2, 1), (2, 3, 2), (0, 4, 3), (4, 3, 1)], 0, 3)\n"
                "    (4, 2)\n"
                "    >>> dijkstra_min_hops(3, [(0, 1, 5)], 0, 2) is None\n"
                "    True\n"
                '    """\n'
                "    adj = [[] for _ in range(n)]\n"
                "    for u, v, w in edges:\n"
                "        adj[u].append((v, w))\n"
                "    INF = 10**18\n"
                "    dist = [INF] * n\n"
                "    hops = [INF] * n\n"
                "    dist[src] = 0\n"
                "    hops[src] = 0\n"
                "    pq = [(0, 0, src)]\n"
                "    while pq:\n"
                "        d, h, u = heapq.heappop(pq)\n"
                "        if d > dist[u]:\n"
                "            continue\n"
                "        for v, w in adj[u]:\n"
                "            if d + w < dist[v]:\n"
                "                dist[v] = d + w\n"
                "                hops[v] = h + 1\n"
                "                heapq.heappush(pq, (dist[v], hops[v], v))\n"
                "    return None if dist[dst] >= INF else (dist[dst], hops[dst])\n"
            ),
            "reference_code": (
                "import heapq\n\n"
                "def dijkstra_min_hops(n: int, edges: list[tuple[int, int, int]], src: int, dst: int) -> tuple[int, int] | None:\n"
                "    adj = [[] for _ in range(n)]\n"
                "    for u, v, w in edges:\n"
                "        adj[u].append((v, w))\n"
                "    INF = 10**18\n"
                "    best = [(INF, INF)] * n\n"
                "    best[src] = (0, 0)\n"
                "    pq = [(0, 0, src)]\n"
                "    while pq:\n"
                "        d, h, u = heapq.heappop(pq)\n"
                "        if (d, h) > best[u]:\n"
                "            continue\n"
                "        for v, w in adj[u]:\n"
                "            cand = (d + w, h + 1)\n"
                "            if cand < best[v]:\n"
                "                best[v] = cand\n"
                "                heapq.heappush(pq, (cand[0], cand[1], v))\n"
                "    return None if best[dst][0] >= INF else best[dst]\n"
            ),
            "test_vectors": [
                ((5, [(0, 1, 1), (1, 2, 1), (2, 3, 2), (0, 4, 3), (4, 3, 1)], 0, 3), (4, 2)),
                ((4, [(0, 1, 2), (1, 3, 2), (0, 2, 1), (2, 1, 1), (0, 3, 4)], 0, 3), (4, 1)),
                ((3, [(0, 1, 5)], 0, 2), None),
                ((1, [], 0, 0), (0, 0)),
                ((4, [(0, 1, 1), (1, 2, 1), (2, 3, 1), (0, 2, 2)], 0, 3), (3, 2)),
                ((3, [(0, 1, 0), (1, 2, 0), (0, 2, 0)], 0, 2), (0, 1)),
                ((5, [(0, 1, 3), (1, 4, 3), (0, 2, 2), (2, 3, 2), (3, 4, 2)], 0, 4), (6, 2)),
                ((4, [(0, 1, 10), (0, 2, 5), (2, 1, 5), (1, 3, 1)], 0, 3), (11, 2)),
            ],
        },
        {
            "task_id": "C3_04",
            "category": "cat3_algo_state_logic",
            "fn_name": "kmp_find_all_overlapping",
            "broken_code": (
                "def kmp_find_all_overlapping(text: str, pattern: str) -> list[int]:\n"
                '    """Return all starting indices of non-empty pattern in text (including overlapping matches).\n'
                "    >>> kmp_find_all_overlapping('aaaaa', 'aa')\n"
                "    [0, 1, 2, 3]\n"
                "    >>> kmp_find_all_overlapping('abababa', 'aba')\n"
                "    [0, 2, 4]\n"
                '    """\n'
                "    if not pattern:\n"
                "        raise ValueError('empty pattern')\n"
                "    m = len(pattern)\n"
                "    pi = [0] * m\n"
                "    j = 0\n"
                "    for i in range(1, m):\n"
                "        if j > 0 and pattern[i] != pattern[j]:\n"
                "            j = pi[j - 1]\n"
                "        if pattern[i] == pattern[j]:\n"
                "            j += 1\n"
                "        pi[i] = j\n"
                "    hits: list[int] = []\n"
                "    j = 0\n"
                "    for i, ch in enumerate(text):\n"
                "        if j > 0 and ch != pattern[j]:\n"
                "            j = pi[j - 1]\n"
                "        if ch == pattern[j]:\n"
                "            j += 1\n"
                "            if j == m:\n"
                "                hits.append(i - m + 1)\n"
                "                j = 0\n"
                "    return hits\n"
            ),
            "reference_code": (
                "def kmp_find_all_overlapping(text: str, pattern: str) -> list[int]:\n"
                "    if not pattern:\n"
                "        raise ValueError('empty pattern')\n"
                "    m = len(pattern)\n"
                "    pi = [0] * m\n"
                "    j = 0\n"
                "    for i in range(1, m):\n"
                "        while j > 0 and pattern[i] != pattern[j]:\n"
                "            j = pi[j - 1]\n"
                "        if pattern[i] == pattern[j]:\n"
                "            j += 1\n"
                "        pi[i] = j\n"
                "    hits: list[int] = []\n"
                "    j = 0\n"
                "    for i, ch in enumerate(text):\n"
                "        while j > 0 and ch != pattern[j]:\n"
                "            j = pi[j - 1]\n"
                "        if ch == pattern[j]:\n"
                "            j += 1\n"
                "            if j == m:\n"
                "                hits.append(i - m + 1)\n"
                "                j = pi[j - 1]\n"
                "    return hits\n"
            ),
            "test_vectors": [
                (("aaaaa", "aa"), [0, 1, 2, 3]),
                (("abababa", "aba"), [0, 2, 4]),
                (("aabaaabaaac", "aabaaac"), [4]),
                (("abcdef", "xyz"), []),
                (("abacabadabacaba", "abacaba"), [0, 8]),
                (("abc", "abcd"), []),
                (("zzzz", "z"), [0, 1, 2, 3]),
                (("abababacaba", "ababa"), [0, 2]),
            ],
        },
        {
            "task_id": "C3_05",
            "category": "cat3_algo_state_logic",
            "fn_name": "neumaier_compensated_sum",
            "broken_code": (
                "def neumaier_compensated_sum(xs: list[float]) -> float:\n"
                '    """Compute Neumaier compensated sum so large intermediate cancellations stay accurate\n'
                "    even when incoming term magnitude exceeds running sum.\n"
                "    >>> neumaier_compensated_sum([1.0, 1e100, 1.0, -1e100])\n"
                "    2.0\n"
                "    >>> neumaier_compensated_sum([])\n"
                "    0.0\n"
                '    """\n'
                "    s = 0.0\n"
                "    c = 0.0\n"
                "    for x in xs:\n"
                "        y = x - c\n"
                "        t = s + y\n"
                "        c = (t - s) - y\n"
                "        s = t\n"
                "    return s\n"
            ),
            "reference_code": (
                "def neumaier_compensated_sum(xs: list[float]) -> float:\n"
                "    s = 0.0\n"
                "    c = 0.0\n"
                "    for x in xs:\n"
                "        t = s + x\n"
                "        if abs(s) >= abs(x):\n"
                "            c += (s - t) + x\n"
                "        else:\n"
                "            c += (x - t) + s\n"
                "        s = t\n"
                "    return s + c\n"
            ),
            "test_vectors": [
                (([1.0, 1e100, 1.0, -1e100],), 2.0),
                (([1e100, 1.0, -1e100, 1.0],), 2.0),
                (([],), 0.0),
                (([0.5, 1e50, -1e50, 0.25],), 0.75),
                (([-3.0, 1e80, -1e80, 5.0],), 2.0),
                (([1.0, 2.0, 3.0, 4.0],), 10.0),
                (([1e-8] * 100 + [1e40, -1e40],), 1e-6),
                (([42.5],), 42.5),
            ],
        },
        {
            "task_id": "C3_06",
            "category": "cat3_algo_state_logic",
            "fn_name": "fenwick_range_ops",
            "broken_code": (
                "def fenwick_range_ops(n: int, ops: list[tuple[str, int, int, int]]) -> list[int]:\n"
                '    """Maintain 1-indexed array of zeros (1..n). Each op is:\n'
                "      ('add', l, r, delta) -> add delta to a[l..r] inclusive\n"
                "      ('sum', l, r, 0)     -> append sum(a[l..r]) to output.\n"
                "    >>> fenwick_range_ops(5, [('add', 2, 4, 3), ('sum', 1, 5, 0), ('sum', 2, 3, 0)])\n"
                "    [9, 6]\n"
                '    """\n'
                "    b1 = [0] * (n + 2)\n"
                "    b2 = [0] * (n + 2)\n"
                "    def bit_add(b: list[int], idx: int, val: int) -> None:\n"
                "        while idx <= n:\n"
                "            b[idx] += val\n"
                "            idx += idx & -idx\n"
                "    def bit_sum(b: list[int], idx: int) -> int:\n"
                "        s = 0\n"
                "        while idx > 0:\n"
                "            s += b[idx]\n"
                "            idx -= idx & -idx\n"
                "        return s\n"
                "    def pref(idx: int) -> int:\n"
                "        return bit_sum(b1, idx) * idx - bit_sum(b2, idx)\n"
                "    out: list[int] = []\n"
                "    for kind, l, r, delta in ops:\n"
                "        if kind == 'add':\n"
                "            bit_add(b1, l, delta)\n"
                "            bit_add(b1, r + 1, -delta)\n"
                "            bit_add(b2, l, l * delta)\n"
                "            bit_add(b2, r + 1, -(r + 1) * delta)\n"
                "        else:\n"
                "            out.append(pref(r) - pref(l - 1))\n"
                "    return out\n"
            ),
            "reference_code": (
                "def fenwick_range_ops(n: int, ops: list[tuple[str, int, int, int]]) -> list[int]:\n"
                "    b1 = [0] * (n + 2)\n"
                "    b2 = [0] * (n + 2)\n"
                "    def bit_add(b: list[int], idx: int, val: int) -> None:\n"
                "        while idx <= n:\n"
                "            b[idx] += val\n"
                "            idx += idx & -idx\n"
                "    def bit_sum(b: list[int], idx: int) -> int:\n"
                "        s = 0\n"
                "        while idx > 0:\n"
                "            s += b[idx]\n"
                "            idx -= idx & -idx\n"
                "        return s\n"
                "    def pref(idx: int) -> int:\n"
                "        return bit_sum(b1, idx) * idx - bit_sum(b2, idx)\n"
                "    out: list[int] = []\n"
                "    for kind, l, r, delta in ops:\n"
                "        if kind == 'add':\n"
                "            bit_add(b1, l, delta)\n"
                "            bit_add(b1, r + 1, -delta)\n"
                "            bit_add(b2, l, (l - 1) * delta)\n"
                "            bit_add(b2, r + 1, -r * delta)\n"
                "        else:\n"
                "            out.append(pref(r) - pref(l - 1))\n"
                "    return out\n"
            ),
            "test_vectors": [
                ((5, [("add", 2, 4, 3), ("sum", 1, 5, 0), ("sum", 2, 3, 0)]), [9, 6]),
                ((4, [("sum", 1, 4, 0)]), [0]),
                ((1, [("add", 1, 1, 7), ("sum", 1, 1, 0)]), [7]),
                ((6, [("add", 1, 6, 2), ("add", 3, 5, -1), ("sum", 2, 4, 0), ("sum", 1, 6, 0)]), [4, 9]),
                ((5, [("add", 1, 1, 10), ("add", 5, 5, 20), ("sum", 1, 5, 0), ("sum", 2, 4, 0)]), [30, 0]),
                ((4, [("add", 2, 2, 5), ("sum", 2, 2, 0), ("sum", 1, 2, 0), ("sum", 2, 3, 0)]), [5, 5, 5]),
                ((8, [("add", 2, 7, 4), ("add", 4, 6, 3), ("sum", 1, 4, 0), ("sum", 5, 8, 0)]), [15, 18]),
                ((3, [("add", 1, 3, -2), ("sum", 2, 3, 0)]), [-4]),
            ],
        },
        {
            "task_id": "C3_07",
            "category": "cat3_algo_state_logic",
            "fn_name": "lru_trace_evictions",
            "broken_code": (
                "from collections import OrderedDict\n\n"
                "def lru_trace_evictions(cap: int, ops: list[tuple[str, int, int]]) -> tuple[list[int], int]:\n"
                '    """Run LRU cache (cap >= 1) on (\'put\', k, v) and (\'get\', k, 0).\n'
                "    Return (get_results_with_-1_for_miss, eviction_count). Updating an existing key is NOT an eviction!\n"
                "    >>> lru_trace_evictions(2, [('put', 1, 10), ('put', 2, 20), ('put', 1, 15), ('get', 2, 0)])\n"
                "    ([20], 0)\n"
                '    """\n'
                "    cache: OrderedDict[int, int] = OrderedDict()\n"
                "    gets: list[int] = []\n"
                "    evictions = 0\n"
                "    for op, k, v in ops:\n"
                "        if op == 'get':\n"
                "            if k not in cache:\n"
                "                gets.append(-1)\n"
                "            else:\n"
                "                cache.move_to_end(k)\n"
                "                gets.append(cache[k])\n"
                "        else:\n"
                "            if len(cache) >= cap:\n"
                "                cache.popitem(last=False)\n"
                "                evictions += 1\n"
                "            cache[k] = v\n"
                "            cache.move_to_end(k)\n"
                "    return (gets, evictions)\n"
            ),
            "reference_code": (
                "from collections import OrderedDict\n\n"
                "def lru_trace_evictions(cap: int, ops: list[tuple[str, int, int]]) -> tuple[list[int], int]:\n"
                "    cache: OrderedDict[int, int] = OrderedDict()\n"
                "    gets: list[int] = []\n"
                "    evictions = 0\n"
                "    for op, k, v in ops:\n"
                "        if op == 'get':\n"
                "            if k not in cache:\n"
                "                gets.append(-1)\n"
                "            else:\n"
                "                cache.move_to_end(k)\n"
                "                gets.append(cache[k])\n"
                "        else:\n"
                "            if k in cache:\n"
                "                cache[k] = v\n"
                "                cache.move_to_end(k)\n"
                "            else:\n"
                "                if len(cache) >= cap:\n"
                "                    cache.popitem(last=False)\n"
                "                    evictions += 1\n"
                "                cache[k] = v\n"
                "    return (gets, evictions)\n"
            ),
            "test_vectors": [
                ((2, [("put", 1, 10), ("put", 2, 20), ("put", 1, 15), ("get", 2, 0)]), ([20], 0)),
                ((2, [("put", 1, 10), ("put", 2, 20), ("put", 3, 30), ("get", 1, 0), ("get", 2, 0)]), ([-1, 20], 1)),
                ((1, [("put", 5, 1), ("put", 5, 2), ("put", 5, 3), ("get", 5, 0)]), ([3], 0)),
                ((2, [("get", 9, 0)]), ([-1], 0)),
                ((2, [("put", 1, 1), ("put", 2, 2), ("get", 1, 0), ("put", 3, 3), ("get", 2, 0)]), ([1, -1], 1)),
                ((3, [("put", 1, 1), ("put", 2, 2), ("put", 3, 3), ("put", 2, 22), ("put", 4, 4), ("get", 1, 0), ("get", 2, 0)]), ([-1, 22], 1)),
                ((1, [("put", 1, 10), ("put", 2, 20), ("get", 1, 0), ("get", 2, 0)]), ([-1, 20], 1)),
                ((2, []), ([], 0)),
            ],
        },
        {
            "task_id": "C3_08",
            "category": "cat3_algo_state_logic",
            "fn_name": "q16_mul_rne_sat",
            "broken_code": (
                "def q16_mul_rne_sat(a_q16: int, b_q16: int) -> int:\n"
                '    """Signed Q16.16 fixed-point multiply with round-half-to-even (banker\'s rounding on bit 15)\n'
                "    and saturation to signed 32-bit [-2147483648, 2147483647].\n"
                "    >>> q16_mul_rne_sat(32768, 1)  # 0.5 * (1/65536) -> exact halfway 0.5 ULP rounds to even 0\n"
                "    0\n"
                "    >>> q16_mul_rne_sat(32768, 3)  # 1.5 ULP rounds to even 2\n"
                "    2\n"
                '    """\n'
                "    prod = a_q16 * b_q16\n"
                "    rounded = (prod + (1 << 15)) >> 16\n"
                "    return max(-2147483648, min(2147483647, rounded))\n"
            ),
            "reference_code": (
                "def q16_mul_rne_sat(a_q16: int, b_q16: int) -> int:\n"
                "    prod = a_q16 * b_q16\n"
                "    q = prod >> 16\n"
                "    rem = prod & 0xFFFF\n"
                "    if rem > 0x8000 or (rem == 0x8000 and (q & 1) == 1):\n"
                "        q += 1\n"
                "    return max(-2147483648, min(2147483647, q))\n"
            ),
            "test_vectors": [
                ((32768, 1), 0),
                ((32768, 3), 2),
                ((-32768, 1), 0),
                ((-32768, 3), -2),
                ((65536, 65536), 65536),
                ((65536 * 60000, 65536 * 60000), 2147483647),
                ((-65536 * 60000, 65536 * 60000), -2147483648),
                ((49152, 49152), 36864),
            ],
        },
        {
            "task_id": "C3_09",
            "category": "cat3_algo_state_logic",
            "fn_name": "crt_general_pair",
            "broken_code": (
                "import math\n\n"
                "def crt_general_pair(a1: int, m1: int, a2: int, m2: int) -> tuple[int, int] | None:\n"
                '    """Solve x ≡ a1 (mod m1) and x ≡ a2 (mod m2) for general positive moduli m1, m2 (not necessarily coprime).\n'
                "    Return (x0, lcm(m1, m2)) with 0 <= x0 < lcm, or None if inconsistent.\n"
                "    >>> crt_general_pair(2, 6, 5, 9)\n"
                "    (14, 18)\n"
                "    >>> crt_general_pair(1, 6, 2, 9) is None\n"
                "    True\n"
                '    """\n'
                "    g = math.gcd(m1, m2)\n"
                "    if (a2 - a1) % g != 0:\n"
                "        return None\n"
                "    lcm = (m1 * m2) // g\n"
                "    inv = pow(m1, -1, m2)\n"
                "    x = (a1 + m1 * ((a2 - a1) * inv % m2)) % lcm\n"
                "    return (x, lcm)\n"
            ),
            "reference_code": (
                "import math\n\n"
                "def crt_general_pair(a1: int, m1: int, a2: int, m2: int) -> tuple[int, int] | None:\n"
                "    g = math.gcd(m1, m2)\n"
                "    if (a2 - a1) % g != 0:\n"
                "        return None\n"
                "    m1_p = m1 // g\n"
                "    m2_p = m2 // g\n"
                "    diff_p = (a2 - a1) // g\n"
                "    lcm = m1_p * m2\n"
                "    inv = pow(m1_p, -1, m2_p)\n"
                "    k = (diff_p * inv) % m2_p\n"
                "    x = (a1 + m1 * k) % lcm\n"
                "    return (x, lcm)\n"
            ),
            "test_vectors": [
                ((2, 6, 5, 9), (14, 18)),
                ((1, 6, 2, 9), None),
                ((2, 3, 3, 5), (8, 15)),
                ((0, 4, 0, 6), (0, 12)),
                ((3, 8, 7, 12), (19, 24)),
                ((5, 10, 5, 10), (5, 10)),
                ((-1, 6, 5, 10), (5, 30)),
                ((4, 12, 10, 18), (28, 36)),
            ],
        },
        {
            "task_id": "C3_10",
            "category": "cat3_algo_state_logic",
            "fn_name": "subtract_half_open_intervals",
            "broken_code": (
                "def subtract_half_open_intervals(base: list[tuple[int, int]], removals: list[tuple[int, int]]) -> list[tuple[int, int]]:\n"
                '    """Given half-open intervals [s, e) (ignore empty s >= e), coalesce base, subtract all removals,\n'
                "    and return sorted non-overlapping coalesced non-empty intervals.\n"
                "    >>> subtract_half_open_intervals([(0, 10)], [(2, 4), (6, 8)])\n"
                "    [(0, 2), (4, 6), (8, 10)]\n"
                "    >>> subtract_half_open_intervals([(0, 5), (5, 10)], [(3, 7)])\n"
                "    [(0, 3), (7, 10)]\n"
                '    """\n'
                "    cur = sorted((s, e) for s, e in base if s < e)\n"
                "    for rs, re in removals:\n"
                "        if rs >= re:\n"
                "            continue\n"
                "        nxt: list[tuple[int, int]] = []\n"
                "        for s, e in cur:\n"
                "            if e <= rs or s >= re:\n"
                "                nxt.append((s, e))\n"
                "            elif s < rs:\n"
                "                nxt.append((s, rs))\n"
                "            elif e > re:\n"
                "                nxt.append((re, e))\n"
                "        cur = nxt\n"
                "    return cur\n"
            ),
            "reference_code": (
                "def subtract_half_open_intervals(base: list[tuple[int, int]], removals: list[tuple[int, int]]) -> list[tuple[int, int]]:\n"
                "    pts = sorted((s, e) for s, e in base if s < e)\n"
                "    merged: list[tuple[int, int]] = []\n"
                "    for s, e in pts:\n"
                "        if merged and s <= merged[-1][1]:\n"
                "            merged[-1] = (merged[-1][0], max(merged[-1][1], e))\n"
                "        else:\n"
                "            merged.append((s, e))\n"
                "    cur = merged\n"
                "    for rs, re in removals:\n"
                "        if rs >= re:\n"
                "            continue\n"
                "        nxt: list[tuple[int, int]] = []\n"
                "        for s, e in cur:\n"
                "            if e <= rs or s >= re:\n"
                "                nxt.append((s, e))\n"
                "            else:\n"
                "                if s < rs:\n"
                "                    nxt.append((s, rs))\n"
                "                if e > re:\n"
                "                    nxt.append((re, e))\n"
                "        cur = nxt\n"
                "    return cur\n"
            ),
            "test_vectors": [
                (([(0, 10)], [(2, 4), (6, 8)]), [(0, 2), (4, 6), (8, 10)]),
                (([(0, 5), (5, 10)], [(3, 7)]), [(0, 3), (7, 10)]),
                (([(0, 4), (2, 8)], []), [(0, 8)]),
                (([(1, 5)], [(0, 10)]), []),
                (([(0, 10)], [(5, 5), (8, 2)]), [(0, 10)]),
                (([], [(1, 3)]), []),
                (([(0, 3), (3, 6), (8, 12)], [(2, 9)]), [(0, 2), (9, 12)]),
                (([(-5, 5)], [(-2, 0), (0, 3)]), [(-5, -2), (3, 5)]),
            ],
        },
        {
            "task_id": "C3_11",
            "category": "cat3_algo_state_logic",
            "fn_name": "fractional_token_bucket",
            "broken_code": (
                "def fractional_token_bucket(cap: int, rate_num: int, rate_den: int, arrivals: list[tuple[int, int]]) -> list[bool]:\n"
                '    """Deterministic integer-exact token bucket starting full at (tokens=cap, rem_num=0) at t=0.\n'
                "    At non-decreasing timestamp t, refill (dt * rate_num) / rate_den tokens; if bucket reaches cap,\n"
                "    clamp tokens=cap AND reset fractional remainder rem_num=0 (cannot bank above burst cap!).\n"
                "    Admit packet of `cost` whole tokens iff tokens >= cost.\n"
                "    >>> fractional_token_bucket(5, 1, 2, [(0, 5), (3, 1), (4, 1)])\n"
                "    [True, True, True]\n"
                "    >>> fractional_token_bucket(2, 1, 2, [(1, 2), (2, 1)])\n"
                "    [True, False]\n"
                '    """\n'
                "    tokens = cap\n"
                "    rem = 0\n"
                "    last_t = 0\n"
                "    out: list[bool] = []\n"
                "    for t, cost in arrivals:\n"
                "        dt = t - last_t\n"
                "        last_t = t\n"
                "        num = rem + dt * rate_num\n"
                "        add, rem = divmod(num, rate_den)\n"
                "        tokens = min(cap, tokens + add)\n"
                "        if tokens >= cost:\n"
                "            tokens -= cost\n"
                "            out.append(True)\n"
                "        else:\n"
                "            out.append(False)\n"
                "    return out\n"
            ),
            "reference_code": (
                "def fractional_token_bucket(cap: int, rate_num: int, rate_den: int, arrivals: list[tuple[int, int]]) -> list[bool]:\n"
                "    tokens = cap\n"
                "    rem = 0\n"
                "    last_t = 0\n"
                "    out: list[bool] = []\n"
                "    for t, cost in arrivals:\n"
                "        dt = t - last_t\n"
                "        last_t = t\n"
                "        num = rem + dt * rate_num\n"
                "        add, rem = divmod(num, rate_den)\n"
                "        tokens += add\n"
                "        if tokens >= cap:\n"
                "            tokens = cap\n"
                "            rem = 0\n"
                "        if tokens >= cost:\n"
                "            tokens -= cost\n"
                "            out.append(True)\n"
                "        else:\n"
                "            out.append(False)\n"
                "    return out\n"
            ),
            "test_vectors": [
                ((5, 1, 2, [(0, 5), (3, 1), (4, 1)]), [True, True, True]),
                ((2, 1, 2, [(1, 2), (2, 1)]), [True, False]),
                ((3, 2, 3, [(1, 3), (2, 1)]), [True, False]),
                ((3, 2, 3, [(0, 3), (2, 1), (3, 1)]), [True, True, True]),
                ((4, 1, 4, [(10, 4), (11, 1), (14, 1)]), [True, False, True]),
                ((1, 1, 10, [(5, 1), (10, 1), (15, 1)]), [True, False, True]),
                ((5, 3, 5, []), []),
                ((2, 3, 4, [(1, 2), (2, 1), (3, 1)]), [True, False, True]),
            ],
        },
        {
            "task_id": "C3_12",
            "category": "cat3_algo_state_logic",
            "fn_name": "crc8_maxim_reflected",
            "broken_code": (
                "def crc8_maxim_reflected(data: list[int]) -> int:\n"
                '    """Compute CRC-8/MAXIM (poly=0x31, init=0x00, refin=True, refout=True, xorout=0x00,\n'
                "    equivalently right-shifting LSB-first with reflected poly 0x8C) over byte values 0..255.\n"
                "    >>> crc8_maxim_reflected(list(b'123456789'))\n"
                "    161\n"
                "    >>> crc8_maxim_reflected([])\n"
                "    0\n"
                '    """\n'
                "    crc = 0\n"
                "    for b in data:\n"
                "        crc ^= (b & 0xFF)\n"
                "        for _ in range(8):\n"
                "            if crc & 0x80:\n"
                "                crc = ((crc << 1) ^ 0x31) & 0xFF\n"
                "            else:\n"
                "                crc = (crc << 1) & 0xFF\n"
                "    return crc\n"
            ),
            "reference_code": (
                "def crc8_maxim_reflected(data: list[int]) -> int:\n"
                "    crc = 0\n"
                "    for b in data:\n"
                "        crc ^= (b & 0xFF)\n"
                "        for _ in range(8):\n"
                "            if crc & 0x01:\n"
                "                crc = (crc >> 1) ^ 0x8C\n"
                "            else:\n"
                "                crc >>= 1\n"
                "    return crc\n"
            ),
            "test_vectors": [
                ((list(b"123456789"),), 0xA1),
                (([],), 0x00),
                (([0x00],), 0x00),
                (([0x01],), 0x5E),
                (([0xFF],), 0x35),
                (([0xAA, 0x55],), 0xED),
                ((list(b"OpenIE"),), None),
                (([0x12, 0x34, 0x56],), None),
            ],
        },
        {
            "task_id": "C3_13",
            "category": "cat3_algo_state_logic",
            "fn_name": "longest_bounded_spread",
            "broken_code": (
                "from collections import deque\n\n"
                "def longest_bounded_spread(nums: list[int], limit: int) -> int:\n"
                '    """Return length of longest contiguous subarray with max(sub) - min(sub) <= limit (limit >= 0).\n'
                "    >>> longest_bounded_spread([8, 2, 4, 7], 4)\n"
                "    2\n"
                "    >>> longest_bounded_spread([4, 2, 2, 2, 4, 4, 2, 2], 0)\n"
                "    3\n"
                '    """\n'
                "    max_dq: deque[int] = deque()\n"
                "    min_dq: deque[int] = deque()\n"
                "    left = 0\n"
                "    best = 0\n"
                "    for right, x in enumerate(nums):\n"
                "        while max_dq and max_dq[-1] <= x:\n"
                "            max_dq.pop()\n"
                "        while min_dq and min_dq[-1] >= x:\n"
                "            min_dq.pop()\n"
                "        max_dq.append(x)\n"
                "        min_dq.append(x)\n"
                "        while max_dq[0] - min_dq[0] > limit:\n"
                "            if max_dq[0] == nums[left]:\n"
                "                max_dq.popleft()\n"
                "            if min_dq[0] == nums[left]:\n"
                "                min_dq.popleft()\n"
                "            left += 1\n"
                "        best = max(best, right - left + 1)\n"
                "    return best\n"
            ),
            "reference_code": (
                "from collections import deque\n\n"
                "def longest_bounded_spread(nums: list[int], limit: int) -> int:\n"
                "    max_dq: deque[int] = deque()\n"
                "    min_dq: deque[int] = deque()\n"
                "    left = 0\n"
                "    best = 0\n"
                "    for right, x in enumerate(nums):\n"
                "        while max_dq and max_dq[-1] < x:\n"
                "            max_dq.pop()\n"
                "        while min_dq and min_dq[-1] > x:\n"
                "            min_dq.pop()\n"
                "        max_dq.append(x)\n"
                "        min_dq.append(x)\n"
                "        while max_dq[0] - min_dq[0] > limit:\n"
                "            if max_dq[0] == nums[left]:\n"
                "                max_dq.popleft()\n"
                "            if min_dq[0] == nums[left]:\n"
                "                min_dq.popleft()\n"
                "            left += 1\n"
                "        best = max(best, right - left + 1)\n"
                "    return best\n"
            ),
            "test_vectors": [
                (([8, 2, 4, 7], 4), 2),
                (([4, 2, 2, 2, 4, 4, 2, 2], 0), 3),
                (([10, 1, 2, 4, 7, 2], 5), 4),
                (([8, 8, 2, 4, 8, 7], 4), 3),
                (([5, 5, 1, 5, 4, 5], 1), 3),
                (([], 5), 0),
                (([3], 0), 1),
                (([1, 5, 6, 7, 8, 10, 6, 5, 6], 4), 5),
            ],
        },
        {
            "task_id": "C3_14",
            "category": "cat3_algo_state_logic",
            "fn_name": "lex_toposort",
            "broken_code": (
                "import heapq\n\n"
                "def lex_toposort(n: int, edges: list[tuple[int, int]]) -> list[int] | None:\n"
                '    """Return lexicographically smallest topological ordering of vertices 0..n-1\n'
                "    (deduplicating parallel edges; returning None if a cycle or self-loop exists).\n"
                "    >>> lex_toposort(4, [(1, 0), (2, 0), (2, 0)])\n"
                "    [1, 2, 0, 3]\n"
                "    >>> lex_toposort(2, [(0, 1), (1, 0)]) is None\n"
                "    True\n"
                '    """\n'
                "    adj = [[] for _ in range(n)]\n"
                "    indeg = [0] * n\n"
                "    for u, v in edges:\n"
                "        adj[u].append(v)\n"
                "        indeg[v] += 1\n"
                "    pq = [i for i in range(n) if indeg[i] == 0]\n"
                "    heapq.heapify(pq)\n"
                "    order: list[int] = []\n"
                "    while pq:\n"
                "        u = heapq.heappop(pq)\n"
                "        order.append(u)\n"
                "        for v in adj[u]:\n"
                "            indeg[v] -= 1\n"
                "            if indeg[v] == 0:\n"
                "                heapq.heappush(pq, v)\n"
                "    return order\n"
            ),
            "reference_code": (
                "import heapq\n\n"
                "def lex_toposort(n: int, edges: list[tuple[int, int]]) -> list[int] | None:\n"
                "    adj: list[set[int]] = [set() for _ in range(n)]\n"
                "    indeg = [0] * n\n"
                "    for u, v in edges:\n"
                "        if u == v:\n"
                "            return None\n"
                "        if v not in adj[u]:\n"
                "            adj[u].add(v)\n"
                "            indeg[v] += 1\n"
                "    pq = [i for i in range(n) if indeg[i] == 0]\n"
                "    heapq.heapify(pq)\n"
                "    order: list[int] = []\n"
                "    while pq:\n"
                "        u = heapq.heappop(pq)\n"
                "        order.append(u)\n"
                "        for v in adj[u]:\n"
                "            indeg[v] -= 1\n"
                "            if indeg[v] == 0:\n"
                "                heapq.heappush(pq, v)\n"
                "    return order if len(order) == n else None\n"
            ),
            "test_vectors": [
                ((4, [(1, 0), (2, 0), (2, 0)]), [1, 2, 0, 3]),
                ((2, [(0, 1), (1, 0)]), None),
                ((3, [(0, 0)]), None),
                ((0, []), []),
                ((5, [(3, 1), (4, 1), (1, 0)]), [2, 3, 4, 1, 0]),
                ((4, [(0, 1), (1, 2), (2, 0)]), None),
                ((3, []), [0, 1, 2]),
                ((4, [(2, 1), (2, 1), (3, 2)]), [0, 3, 2, 1]),
            ],
        },
        {
            "task_id": "C3_15",
            "category": "cat3_algo_state_logic",
            "fn_name": "parse_rfc4180_row",
            "broken_code": (
                "def parse_rfc4180_row(line: str) -> list[str]:\n"
                '    """Parse a single CSV row per RFC 4180: empty string -> [], quoted fields allow commas and\n'
                '    escaped double-quotes ("" -> "), and trailing comma yields trailing empty field (\'a,\' -> [\'a\', \'\']).\n'
                "    >>> parse_rfc4180_row('a,\"b,c\",\"d\"\"e\",')\n"
                "    ['a', 'b,c', 'd\"e', '']\n"
                "    >>> parse_rfc4180_row('')\n"
                "    []\n"
                '    """\n'
                "    if not line:\n"
                "        return []\n"
                "    fields: list[str] = []\n"
                "    buf: list[str] = []\n"
                "    in_quotes = False\n"
                "    for ch in line:\n"
                "        if ch == '\"':\n"
                "            in_quotes = not in_quotes\n"
                "        elif ch == ',' and not in_quotes:\n"
                "            fields.append(''.join(buf))\n"
                "            buf = []\n"
                "        else:\n"
                "            buf.append(ch)\n"
                "    if buf:\n"
                "        fields.append(''.join(buf))\n"
                "    return fields\n"
            ),
            "reference_code": (
                "def parse_rfc4180_row(line: str) -> list[str]:\n"
                "    if line == '':\n"
                "        return []\n"
                "    fields: list[str] = []\n"
                "    buf: list[str] = []\n"
                "    in_quotes = False\n"
                "    i = 0\n"
                "    n = len(line)\n"
                "    while i < n:\n"
                "        ch = line[i]\n"
                "        if in_quotes:\n"
                "            if ch == '\"':\n"
                "                if i + 1 < n and line[i + 1] == '\"':\n"
                "                    buf.append('\"')\n"
                "                    i += 2\n"
                "                    continue\n"
                "                else:\n"
                "                    in_quotes = False\n"
                "            else:\n"
                "                buf.append(ch)\n"
                "        else:\n"
                "            if ch == '\"':\n"
                "                in_quotes = True\n"
                "            elif ch == ',':\n"
                "                fields.append(''.join(buf))\n"
                "                buf = []\n"
                "            else:\n"
                "                buf.append(ch)\n"
                "        i += 1\n"
                "    fields.append(''.join(buf))\n"
                "    return fields\n"
            ),
            "test_vectors": [
                (('a,"b,c","d""e",',), ["a", "b,c", 'd"e', ""]),
                (("",), []),
                ((",",), ["", ""]),
                (('""',), [""]),
                (('""""',), ['"']),
                (("x,y,z",), ["x", "y", "z"]),
                (('"hello, ""world""",42',), ['hello, "world"', "42"]),
                ((",a,",), ["", "a", ""]),
            ],
        },
        {
            "task_id": "C3_16",
            "category": "cat3_algo_state_logic",
            "fn_name": "gregorian_add_days",
            "broken_code": (
                "def gregorian_add_days(y: int, m: int, d: int, delta: int) -> tuple[int, int, int]:\n"
                '    """Add signed `delta` days to proleptic Gregorian date (y, m, d) using exact 4/100/400 leap rules.\n'
                "    >>> gregorian_add_days(1900, 2, 28, 1)\n"
                "    (1900, 3, 1)\n"
                "    >>> gregorian_add_days(2000, 2, 28, 1)\n"
                "    (2000, 2, 29)\n"
                '    """\n'
                "    def is_leap(yr: int) -> bool:\n"
                "        return yr % 4 == 0\n"
                "    def dim(yr: int, mo: int) -> int:\n"
                "        if mo == 2:\n"
                "            return 29 if is_leap(yr) else 28\n"
                "        return 30 if mo in (4, 6, 9, 11) else 31\n"
                "    while delta > 0:\n"
                "        d += 1\n"
                "        if d > dim(y, m):\n"
                "            d = 1\n"
                "            m += 1\n"
                "            if m > 12:\n"
                "                m = 1\n"
                "                y += 1\n"
                "        delta -= 1\n"
                "    while delta < 0:\n"
                "        d -= 1\n"
                "        if d < 1:\n"
                "            m -= 1\n"
                "            if m < 1:\n"
                "                m = 12\n"
                "                y -= 1\n"
                "            d = dim(y, m) - 1\n"
                "        delta += 1\n"
                "    return (y, m, d)\n"
            ),
            "reference_code": (
                "def gregorian_add_days(y: int, m: int, d: int, delta: int) -> tuple[int, int, int]:\n"
                "    def is_leap(yr: int) -> bool:\n"
                "        return (yr % 4 == 0 and yr % 100 != 0) or (yr % 400 == 0)\n"
                "    def dim(yr: int, mo: int) -> int:\n"
                "        if mo == 2:\n"
                "            return 29 if is_leap(yr) else 28\n"
                "        return 30 if mo in (4, 6, 9, 11) else 31\n"
                "    while delta > 0:\n"
                "        d += 1\n"
                "        if d > dim(y, m):\n"
                "            d = 1\n"
                "            m += 1\n"
                "            if m > 12:\n"
                "                m = 1\n"
                "                y += 1\n"
                "        delta -= 1\n"
                "    while delta < 0:\n"
                "        d -= 1\n"
                "        if d < 1:\n"
                "            m -= 1\n"
                "            if m < 1:\n"
                "                m = 12\n"
                "                y -= 1\n"
                "            d = dim(y, m)\n"
                "        delta += 1\n"
                "    return (y, m, d)\n"
            ),
            "test_vectors": [
                ((1900, 2, 28, 1), (1900, 3, 1)),
                ((2000, 2, 28, 1), (2000, 2, 29)),
                ((1900, 3, 1, -1), (1900, 2, 28)),
                ((2000, 3, 1, -1), (2000, 2, 29)),
                ((2024, 2, 28, 2), (2024, 3, 1)),
                ((2026, 1, 1, -1), (2025, 12, 31)),
                ((2100, 2, 28, 1), (2100, 3, 1)),
                ((2026, 11, 23, 40), (2027, 1, 2)),
            ],
        },
        {
            "task_id": "C3_17",
            "category": "cat3_algo_state_logic",
            "fn_name": "shortest_path_target_negcycle",
            "broken_code": (
                "def shortest_path_target_negcycle(n: int, edges: list[tuple[int, int, int]], src: int, dst: int) -> int | str:\n"
                '    """Return integer shortest walk cost from src to dst, \'UNREACHABLE\' if dst cannot be reached,\n'
                "    or 'NEG_INF' ONLY if a negative cycle is both reachable from src AND can reach dst.\n"
                "    >>> shortest_path_target_negcycle(4, [(0, 1, 2), (1, 3, 2), (0, 2, 1), (2, 2, -5)], 0, 3)\n"
                "    4\n"
                "    >>> shortest_path_target_negcycle(3, [(0, 1, 1), (1, 1, -2), (1, 2, 5)], 0, 2)\n"
                "    'NEG_INF'\n"
                '    """\n'
                "    INF = 10**18\n"
                "    dist = [INF] * n\n"
                "    dist[src] = 0\n"
                "    for _ in range(max(0, n - 1)):\n"
                "        for u, v, w in edges:\n"
                "            if dist[u] < INF and dist[u] + w < dist[v]:\n"
                "                dist[v] = dist[u] + w\n"
                "    if dist[dst] >= INF:\n"
                "        return 'UNREACHABLE'\n"
                "    for u, v, w in edges:\n"
                "        if dist[u] < INF and dist[u] + w < dist[v]:\n"
                "            return 'NEG_INF'\n"
                "    return dist[dst]\n"
            ),
            "reference_code": (
                "from collections import deque\n\n"
                "def shortest_path_target_negcycle(n: int, edges: list[tuple[int, int, int]], src: int, dst: int) -> int | str:\n"
                "    INF = 10**18\n"
                "    dist = [INF] * n\n"
                "    dist[src] = 0\n"
                "    for _ in range(max(0, n - 1)):\n"
                "        for u, v, w in edges:\n"
                "            if dist[u] < INF and dist[u] + w < dist[v]:\n"
                "                dist[v] = dist[u] + w\n"
                "    if dist[dst] >= INF:\n"
                "        return 'UNREACHABLE'\n"
                "    adj = [[] for _ in range(n)]\n"
                "    for u, v, _ in edges:\n"
                "        adj[u].append(v)\n"
                "    q: deque[int] = deque()\n"
                "    seen = [False] * n\n"
                "    for u, v, w in edges:\n"
                "        if dist[u] < INF and dist[u] + w < dist[v] and not seen[v]:\n"
                "            seen[v] = True\n"
                "            q.append(v)\n"
                "    while q:\n"
                "        u = q.popleft()\n"
                "        if u == dst:\n"
                "            return 'NEG_INF'\n"
                "        for nxt in adj[u]:\n"
                "            if not seen[nxt]:\n"
                "                seen[nxt] = True\n"
                "                q.append(nxt)\n"
                "    return dist[dst]\n"
            ),
            "test_vectors": [
                ((4, [(0, 1, 2), (1, 3, 2), (0, 2, 1), (2, 2, -5)], 0, 3), 4),
                ((3, [(0, 1, 1), (1, 1, -2), (1, 2, 5)], 0, 2), "NEG_INF"),
                ((3, [(0, 1, 5)], 0, 2), "UNREACHABLE"),
                ((4, [(0, 3, 10), (1, 2, -3), (2, 1, -3), (2, 3, 1)], 0, 3), 10),
                ((1, [(0, 0, -1)], 0, 0), "NEG_INF"),
                ((1, [], 0, 0), 0),
                ((5, [(0, 1, 2), (1, 2, -4), (2, 1, 1), (0, 4, 7)], 0, 4), 7),
                ((4, [(0, 1, 2), (1, 2, -5), (2, 1, 2), (2, 3, 10)], 0, 3), "NEG_INF"),
            ],
        },
        {
            "task_id": "C3_18",
            "category": "cat3_algo_state_logic",
            "fn_name": "escaped_rle_encode",
            "broken_code": (
                "def escaped_rle_encode(data: list[int]) -> list[int]:\n"
                '    """Encode byte list (0..255) using escape marker 0xFF:\n'
                "      - Any run of byte 0xFF (even length 1..3) MUST be encoded in chunks <= 255 as [0xFF, count, 0xFF].\n"
                "      - For byte b != 0xFF, chunks of length >= 4 (split at <= 255) encode as [0xFF, count, b];\n"
                "        remaining tail of length 1..3 emits raw [b] * tail.\n"
                "    >>> escaped_rle_encode([0xFF, 7, 7, 7, 7, 8])\n"
                "    [255, 1, 255, 255, 4, 7, 8]\n"
                "    >>> escaped_rle_encode([5, 5, 5])\n"
                "    [5, 5, 5]\n"
                '    """\n'
                "    out: list[int] = []\n"
                "    i = 0\n"
                "    n = len(data)\n"
                "    while i < n:\n"
                "        j = i + 1\n"
                "        while j < n and data[j] == data[i]:\n"
                "            j += 1\n"
                "        cnt = j - i\n"
                "        b = data[i]\n"
                "        if cnt >= 4:\n"
                "            out.extend([0xFF, cnt, b])\n"
                "        else:\n"
                "            out.extend([b] * cnt)\n"
                "        i = j\n"
                "    return out\n"
            ),
            "reference_code": (
                "def escaped_rle_encode(data: list[int]) -> list[int]:\n"
                "    out: list[int] = []\n"
                "    i = 0\n"
                "    n = len(data)\n"
                "    while i < n:\n"
                "        j = i + 1\n"
                "        while j < n and data[j] == data[i]:\n"
                "            j += 1\n"
                "        rem = j - i\n"
                "        b = data[i]\n"
                "        if b == 0xFF:\n"
                "            while rem > 0:\n"
                "                chunk = min(255, rem)\n"
                "                out.extend([0xFF, chunk, 0xFF])\n"
                "                rem -= chunk\n"
                "        else:\n"
                "            while rem >= 255:\n"
                "                out.extend([0xFF, 255, b])\n"
                "                rem -= 255\n"
                "            if rem >= 4:\n"
                "                out.extend([0xFF, rem, b])\n"
                "            elif rem > 0:\n"
                "                out.extend([b] * rem)\n"
                "        i = j\n"
                "    return out\n"
            ),
            "test_vectors": [
                (([0xFF, 7, 7, 7, 7, 8],), [255, 1, 255, 255, 4, 7, 8]),
                (([5, 5, 5],), [5, 5, 5]),
                (([],), []),
                (([0xFF, 0xFF],), [255, 2, 255]),
                (([9] * 256,), [255, 255, 9, 9]),
                (([9] * 260,), [255, 255, 9, 255, 5, 9]),
                (([0xFF] * 257,), [255, 255, 255, 255, 2, 255]),
                (([1, 2, 3, 0xFF, 4],), [1, 2, 3, 255, 1, 255, 4]),
            ],
        },
        {
            "task_id": "C3_19",
            "category": "cat3_algo_state_logic",
            "fn_name": "largest_histogram_rect",
            "broken_code": (
                "def largest_histogram_rect(heights: list[int]) -> int:\n"
                '    """Return area of largest axis-aligned rectangle in histogram of non-negative bar heights.\n'
                "    >>> largest_histogram_rect([2, 1, 5, 6, 2, 3])\n"
                "    10\n"
                "    >>> largest_histogram_rect([2, 1, 2])\n"
                "    3\n"
                '    """\n'
                "    st: list[int] = []\n"
                "    best = 0\n"
                "    ext = heights + [0]\n"
                "    for i, h in enumerate(ext):\n"
                "        while st and ext[st[-1]] > h:\n"
                "            idx = st.pop()\n"
                "            width = i - idx\n"
                "            best = max(best, ext[idx] * width)\n"
                "        st.append(i)\n"
                "    return best\n"
            ),
            "reference_code": (
                "def largest_histogram_rect(heights: list[int]) -> int:\n"
                "    st: list[int] = []\n"
                "    best = 0\n"
                "    ext = heights + [0]\n"
                "    for i, h in enumerate(ext):\n"
                "        while st and ext[st[-1]] > h:\n"
                "            idx = st.pop()\n"
                "            width = i if not st else (i - st[-1] - 1)\n"
                "            best = max(best, ext[idx] * width)\n"
                "        st.append(i)\n"
                "    return best\n"
            ),
            "test_vectors": [
                (([2, 1, 5, 6, 2, 3],), 10),
                (([2, 1, 2],), 3),
                (([],), 0),
                (([5],), 5),
                (([6, 2, 5, 4, 5, 1, 6],), 12),
                (([4, 2, 0, 3, 2, 5],), 6),
                (([3, 6, 5, 7, 4, 8, 1, 0],), 20),
                (([0, 0, 0],), 0),
            ],
        },
        {
            "task_id": "C3_20",
            "category": "cat3_algo_state_logic",
            "fn_name": "raft_append_entries",
            "broken_code": (
                "def raft_append_entries(\n"
                "    log: list[tuple[int, str]],\n"
                "    prev_log_index: int,\n"
                "    prev_log_term: int,\n"
                "    entries: list[tuple[int, str]],\n"
                ") -> tuple[bool, list[tuple[int, str]]]:\n"
                '    """Apply Raft Figure 2 AppendEntries rule on 1-indexed `log` of (term, cmd):\n'
                "      1. If prev_log_index > 0: fail (False, copy_of_log) if len(log) < prev_log_index\n"
                "         or log[prev_log_index - 1][0] != prev_log_term.\n"
                "      2. Walk incoming `entries` starting at 1-based index prev_log_index + 1:\n"
                "         ONLY if an existing entry conflicts (same index, different term), delete the\n"
                "         existing entry and all that follow it; then append any new entries not already in log.\n"
                "         (Stale shorter matching prefix MUST NOT truncate already-stored suffix!)\n"
                "    >>> raft_append_entries([(1, 'a'), (1, 'b'), (2, 'c')], 1, 1, [(1, 'b')])\n"
                "    (True, [(1, 'a'), (1, 'b'), (2, 'c')])\n"
                '    """\n'
                "    out = list(log)\n"
                "    if prev_log_index > 0:\n"
                "        if len(out) < prev_log_index or out[prev_log_index - 1][0] != prev_log_term:\n"
                "            return (False, out)\n"
                "    out = out[:prev_log_index] + list(entries)\n"
                "    return (True, out)\n"
            ),
            "reference_code": (
                "def raft_append_entries(\n"
                "    log: list[tuple[int, str]],\n"
                "    prev_log_index: int,\n"
                "    prev_log_term: int,\n"
                "    entries: list[tuple[int, str]],\n"
                ") -> tuple[bool, list[tuple[int, str]]]:\n"
                "    out = list(log)\n"
                "    if prev_log_index > 0:\n"
                "        if len(out) < prev_log_index or out[prev_log_index - 1][0] != prev_log_term:\n"
                "            return (False, out)\n"
                "    idx = prev_log_index\n"
                "    for i, ent in enumerate(entries):\n"
                "        if idx < len(out):\n"
                "            if out[idx][0] != ent[0]:\n"
                "                out = out[:idx]\n"
                "                out.extend(entries[i:])\n"
                "                break\n"
                "        else:\n"
                "            out.extend(entries[i:])\n"
                "            break\n"
                "        idx += 1\n"
                "    return (True, out)\n"
            ),
            "test_vectors": [
                (([(1, "a"), (1, "b"), (2, "c")], 1, 1, [(1, "b")]), (True, [(1, "a"), (1, "b"), (2, "c")])),
                (([(1, "a"), (1, "b"), (2, "c")], 1, 1, []), (True, [(1, "a"), (1, "b"), (2, "c")])),
                (([(1, "a"), (1, "b"), (2, "c")], 1, 1, [(3, "x")]), (True, [(1, "a"), (3, "x")])),
                (([(1, "a")], 2, 1, [(1, "b")]), (False, [(1, "a")])),
                (([(1, "a")], 1, 2, [(2, "b")]), (False, [(1, "a")])),
                (([], 0, 0, [(1, "init")]), (True, [(1, "init")])),
                (([(1, "a"), (2, "b")], 2, 2, [(2, "c"), (3, "d")]), (True, [(1, "a"), (2, "b"), (2, "c"), (3, "d")])),
                (([(1, "a"), (2, "b"), (2, "c"), (4, "d")], 1, 1, [(2, "b"), (3, "e")]), (True, [(1, "a"), (2, "b"), (3, "e")])),
            ],
        },
    ]

    # Fill dynamic CRC-8 reference outputs for C3_12 vectors 6 & 7
    for t in tasks:
        if t["task_id"] == "C3_12":
            ns: dict[str, Any] = {}
            exec(t["reference_code"], ns)
            ref_fn = ns["crc8_maxim_reflected"]
            fixed_vecs = []
            for args, exp in t["test_vectors"]:
                fixed_vecs.append((args, ref_fn(*args) if exp is None else exp))
            t["test_vectors"] = fixed_vecs
        # Add 4 extra deterministic differential vectors per task (so every task has 12 total checks: 8 explicit + 4 property/differential)
        ns_ref: dict[str, Any] = {}
        exec(t["reference_code"], ns_ref)
        rfn = ns_ref[t["fn_name"]]
        extra_inputs = [v[0] for v in t["test_vectors"][:4]]
        t["property_inputs"] = extra_inputs
        assert len(t["test_vectors"]) >= 8, f"{t['task_id']} has < 8 vectors"
        # Verify reference passes all vectors right at load time
        for args, exp in t["test_vectors"]:
            got = rfn(*[ _deep_copy_arg(a) for a in args ])
            assert got == exp and type(got) is type(exp), f"Ref mismatch on {t['task_id']} {args}: {got!r} != {exp!r}"

    return tasks


def _deep_copy_arg(x: Any) -> Any:
    if isinstance(x, list):
        return [_deep_copy_arg(v) for v in x]
    if isinstance(x, dict):
        return {_deep_copy_arg(k): _deep_copy_arg(v) for k, v in x.items()}
    if isinstance(x, set):
        return {_deep_copy_arg(v) for v in x}
    if isinstance(x, tuple):
        return tuple(_deep_copy_arg(v) for v in x)
    return x


_ALL_TASKS = _build_all_tasks()

HOLD_OUT_ORACLES: dict[str, dict[str, Any]] = {
    t["task_id"]: {
        "fn_name": t["fn_name"],
        "reference_code": t["reference_code"],
        "test_vectors": t["test_vectors"],
    }
    for t in _ALL_TASKS
}


def get_public_tasks() -> list[dict[str, str]]:
    """Returns strictly public task inputs (broken_code + metadata), with ZERO oracle fields."""
    return [
        {
            "task_id": t["task_id"],
            "category": t["category"],
            "fn_name": t["fn_name"],
            "broken_code": t["broken_code"],
        }
        for t in _ALL_TASKS
    ]


def corpus_sha256() -> str:
    canonical = json.dumps(_ALL_TASKS, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def evaluate_heldout_oracle(task_id: str, candidate_code: str) -> dict[str, Any]:
    """
    Post-commit held-out evaluation oracle (>= 8 vectors + state-leakage repeat check + exact type parity).
    NEVER called by any arm during candidate generation or gating.
    """
    spec = HOLD_OUT_ORACLES[task_id]
    fn_name = spec["fn_name"]
    vecs = spec["test_vectors"]

    ns: dict[str, Any] = {}
    try:
        exec(compile(candidate_code, f"<cand_{task_id}>", "exec"), ns)
    except Exception as e:
        return {
            "passed": False,
            "vectors_passed": 0,
            "vectors_total": len(vecs),
            "reason": f"compile_or_exec_error:{type(e).__name__}",
        }

    fn = ns.get(fn_name)
    if not callable(fn):
        return {
            "passed": False,
            "vectors_passed": 0,
            "vectors_total": len(vecs),
            "reason": f"missing_callable:{fn_name}",
        }

    passed_cnt = 0
    first_err = ""
    # Run entire suite TWICE on the same function object so mutable-default state leaks are caught!
    for pass_round in range(2):
        for idx, (args, expected) in enumerate(vecs):
            try:
                got = fn(*[_deep_copy_arg(a) for a in args])
            except Exception as e:
                if not first_err:
                    first_err = f"round{pass_round}_vec{idx}_exc:{type(e).__name__}:{e}"
                continue
            ok = False
            if isinstance(expected, float) and isinstance(got, float):
                ok = abs(got - expected) <= 1e-12 * max(1.0, abs(expected))
            else:
                ok = (type(got) is type(expected)) and (got == expected)
            if ok:
                if pass_round == 1:
                    passed_cnt += 1
            else:
                if not first_err:
                    first_err = f"round{pass_round}_vec{idx}_mismatch:got={got!r},exp={expected!r}"

    all_ok = (passed_cnt == len(vecs)) and (first_err == "")
    return {
        "passed": all_ok,
        "vectors_passed": passed_cnt if first_err == "" else min(passed_cnt, len(vecs) - 1),
        "vectors_total": len(vecs),
        "reason": "ok" if all_ok else first_err,
    }


if __name__ == "__main__":
    pub = get_public_tasks()
    broken_pass = 0
    ref_pass = 0
    for t in pub:
        tid = t["task_id"]
        rb = evaluate_heldout_oracle(tid, t["broken_code"])
        rr = evaluate_heldout_oracle(tid, HOLD_OUT_ORACLES[tid]["reference_code"])
        if rb["passed"]:
            broken_pass += 1
            print("UNEXPECTED BROKEN PASS:", tid)
        if rr["passed"]:
            ref_pass += 1
        else:
            print("UNEXPECTED REF FAIL:", tid, rr)
    print(json.dumps({
        "total_tasks": len(pub),
        "reference_passed": ref_pass,
        "broken_passed": broken_pass,
        "corpus_sha256": corpus_sha256(),
    }, indent=2))
