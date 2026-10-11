"""Sudoku world, completeness predicate and three gears.

g0: naked singles only. g1: naked and hidden singles. g2: g1 plus
depth-first search on the cell with fewest candidates. Each gear calls
check() between steps; check() returning False aborts the act.
"""
import math

ALL = 0x1FF
ROW = [i // 9 for i in range(81)]
COL = [i % 9 for i in range(81)]
BOX = [(i // 27) * 3 + (i % 9) // 3 for i in range(81)]
UNITS = ([[r * 9 + c for c in range(9)] for r in range(9)] +
         [[r * 9 + c for r in range(9)] for c in range(9)] +
         [[(b // 3) * 27 + (b % 3) * 3 + (k // 3) * 9 + k % 3 for k in range(9)] for b in range(9)])
POP = [bin(m).count('1') for m in range(512)]
BITS = {1 << d: d + 1 for d in range(9)}
LOG2_9 = math.log2(9)


class Abort(Exception):
    pass


def _masks(g):
    rm, cm, bm = [0] * 9, [0] * 9, [0] * 9
    for i, v in enumerate(g):
        if v:
            bit = 1 << (v - 1)
            if (rm[ROW[i]] | cm[COL[i]] | bm[BOX[i]]) & bit:
                return None
            rm[ROW[i]] |= bit; cm[COL[i]] |= bit; bm[BOX[i]] |= bit
    return rm, cm, bm


def _place(g, M, i, v):
    bit = 1 << (v - 1)
    g[i] = v
    M[0][ROW[i]] |= bit; M[1][COL[i]] |= bit; M[2][BOX[i]] |= bit


def _cand(M, i):
    return ALL & ~(M[0][ROW[i]] | M[1][COL[i]] | M[2][BOX[i]])


def _naked(g, M, check):
    """One sweep. Returns (progress, ok). Checks the budget three times per sweep."""
    prog = False
    for i in range(81):
        if i % 27 == 26 and not check():
            raise Abort()
        if g[i] == 0:
            c = _cand(M, i)
            if c == 0:
                return prog, False
            if POP[c] == 1:
                _place(g, M, i, BITS[c]); prog = True
    return prog, True


def _hidden(g, M, check):
    prog = False
    for ui, u in enumerate(UNITS):
        if ui % 9 == 8 and not check():
            raise Abort()
        for d in range(9):
            bit = 1 << d
            spot, n = -1, 0
            placed = False
            for i in u:
                if g[i] == d + 1:
                    placed = True; break
                if g[i] == 0 and _cand(M, i) & bit:
                    n += 1; spot = i
            if placed:
                continue
            if n == 0:
                return prog, False
            if n == 1:
                _place(g, M, spot, d + 1); prog = True
    return prog, True


def _propagate(g, M, hidden, check):
    while True:
        if not check():
            raise Abort()
        p1, ok = _naked(g, M, check)
        if not ok:
            return False
        p2 = False
        if hidden:
            p2, ok = _hidden(g, M, check)
            if not ok:
                return False
        if not (p1 or p2):
            return True


def _ok(check):
    return check if check else (lambda: True)


def gear0(grid, rng=None, check=None):
    g = list(grid); M = _masks(g)
    if M is None:
        return g, 0
    _propagate(g, M, False, _ok(check))
    return g, 0


def gear1(grid, rng=None, check=None):
    g = list(grid); M = _masks(g)
    if M is None:
        return g, 0
    _propagate(g, M, True, _ok(check))
    return g, 0


def gear2(grid, rng=None, check=None, limit=2, count_only=False):
    """Search. Returns (grid, nodes). With count_only, returns (n_solutions, nodes)."""
    chk = _ok(check)
    nodes = [0]
    sols = []

    def rec(g, M):
        nodes[0] += 1
        if not _propagate(g, M, True, chk):
            return False
        best, bc = -1, 10
        for i in range(81):
            if g[i] == 0:
                c = POP[_cand(M, i)]
                if c < bc:
                    best, bc = i, c
                    if c == 2:
                        break
        if best < 0:
            sols.append(list(g))
            return len(sols) >= (limit if count_only else 1)
        c = _cand(M, best)
        vals = [d + 1 for d in range(9) if c & (1 << d)]
        if rng is not None:
            rng.shuffle(vals)
        for v in vals:
            g2 = list(g); M2 = ([*M[0]], [*M[1]], [*M[2]])
            _place(g2, M2, best, v)
            if rec(g2, M2):
                return True
        return False

    g = list(grid); M = _masks(g)
    if M is not None:
        rec(g, M)
    if count_only:
        return len(sols), nodes[0]
    return (sols[0] if sols else g), nodes[0]


GEARS = {'g0': gear0, 'g1': gear1, 'g2': gear2}
ORDER = ['g0', 'g1', 'g2']


def complete(z, givens):
    """Completeness predicate C(z): full, valid, givens kept."""
    if any(v == 0 for v in z):
        return False
    if any(givens[i] and givens[i] != z[i] for i in range(81)):
        return False
    for u in UNITS:
        if sorted(z[i] for i in u) != list(range(1, 10)):
            return False
    return True


def bits(grid):
    """Coupled bits of a confirmed fill: empty cells times log2 9.

    This is log2 of the number of fills the act chooses among, the capacity
    bound of Definition 1 for an actuator that can write any fill."""
    return sum(1 for v in grid if v == 0) * LOG2_9


def feature(grid):
    """Fraction of empty cells with exactly one candidate at the start."""
    M = _masks(list(grid))
    e = [i for i in range(81) if grid[i] == 0]
    if not e or M is None:
        return 0.0
    return sum(1 for i in e if POP[_cand(M, i)] == 1) / len(e)
