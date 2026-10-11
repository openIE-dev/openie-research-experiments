"""Acceptor agents: sigma-law selector, Mixture of Limits cheapest-sufficient
selector, and a goal-blind baseline. One episode closes one task.

Law-abiding arms (sigma, mol):
  before each act, fix the predicted result R* and hash it (prediction first);
  act with one gear; compare the outcome with R* (m = 1 when C(z) passes);
  m changes what happens next (escalate, stop, or refuse);
  refuse with a receipt when no act fits the joule budget.
Goal-blind arm: one gear drawn uniformly at random, no R*, no comparison,
no escalation, no refusal. The budget is a hard cutoff for it too. Its
outcome is scored by C(z) after the episode, outside its joules.
"""
import hashlib, json, time
from . import meter
from .sudoku import GEARS, ORDER, Abort, complete, bits, feature

E_BINS = (50, 55)          # preregistered: bin by empty-cell count
THETA = 0.5                # preregistered: sufficiency threshold for mol
RESERVE = 0.05             # preregistered: share of B kept for closing the act


def ebin(grid):
    e = sum(1 for v in grid if v == 0)
    return 0 if e <= E_BINS[0] else (1 if e <= E_BINS[1] else 2)


class Calib:
    """Calibration table from the pilot: per bin, gear cost and pass record."""
    def __init__(self, d):
        self.cost = {int(k): v for k, v in d['cost'].items()}      # bin -> gear -> median J
        self.rec = {int(k): v for k, v in d['passes'].items()}     # bin -> list of {gear: 0/1}

    def p(self, b, g, tried):
        rows = [r for r in self.rec[b] if all(r[t] == 0 for t in tried)]
        k = sum(r[g] for r in rows)
        return (k + 1) / (len(rows) + 2)                           # Laplace rule

    def c(self, b, g):
        return self.cost[b][g]


def select(arm, calib, b, tried, rem, bits_q, lam):
    """Return (gear, None) or (None, refuse_reason)."""
    left = [g for g in ORDER if g not in tried]
    if not left:
        return None, 'all gears tried and failed'
    if arm == 'mol':
        pick = None
        for g in left:                       # cheapest first
            if calib.p(b, g, tried) >= THETA:
                pick = g; break
        if pick is None:
            pick = max(left, key=lambda g: calib.p(b, g, tried))
        if calib.c(b, pick) > rem:
            return None, f'next gear {pick} would break the budget'
        return pick, None
    if arm == 'sigma':
        fit = [g for g in left if calib.c(b, g) <= rem]
        if not fit:
            return None, 'no gear fits the remaining budget'
        val = {g: calib.p(b, g, tried) * bits_q - lam * calib.c(b, g) for g in fit}
        g = max(fit, key=lambda g: val[g])
        if val[g] <= 0:
            return None, 'no act has positive value H(a) - lambda J(a)'
        return g, None
    raise ValueError(arm)


def episode(task, arm, budget, rng, calib, run_meta):
    grid = task['grid']; bq = bits(grid)
    lam = bq / budget if budget else 0.0      # preregistered: lambda = b_q / B
    acts = []
    t0 = meter.read()
    b = ebin(grid)
    tried, passed, refused, cut, reason = [], False, False, False, None
    out = None
    while True:
        now = meter.read()
        rem = (budget - meter.joules(t0, now)) if budget else float('inf')
        rstar, h, ts = None, None, None
        if arm == 'blind':
            if acts:
                break
            g = rng.choice(ORDER)
        else:
            g, why = select(arm, calib, b, tried, rem, bq, lam)
            if g is None:
                refused, reason = True, why
                break
            rstar = {'task': task['id'], 'gear': g, 'predict': 'C(z)=1',
                     'predicted_j': calib.c(b, g), 'budget_left_j': rem}
            h = hashlib.sha256(json.dumps(rstar, sort_keys=True).encode()).hexdigest()
            ts = time.time_ns()
        a0 = meter.read()
        guard = [0.0, a0]

        def check():
            if not budget:
                return True
            x = meter.read()
            step = meter.joules(guard[1], x); guard[1] = x
            guard[0] = max(guard[0], step)
            return meter.joules(t0, x) + 2 * guard[0] + RESERVE * budget < budget

        aborted = False
        try:
            out, nodes = GEARS[g](grid, rng=rng, check=check)
        except Abort:
            aborted, nodes, out = True, None, None
        m = None
        if arm != 'blind' and not aborted:
            m = 1 if complete(out, grid) else 0
        a1 = meter.read()
        acts.append({'gear': g, 'prediction_hash': h, 'prediction_ts': ts,
                     'outcome_hash': hashlib.sha256(bytes(out)).hexdigest() if out else None,
                     'm': m, 'aborted': aborted, 'nodes': nodes,
                     'reported_j': meter.joules(a0, a1), 'cycles': a1[1] - a0[1],
                     'instructions': a1[2] - a0[2], 'wall_s': (a1[3] - a0[3]) / 1e9})
        if aborted:
            if arm == 'blind':
                cut = True
            else:
                refused, reason = True, 'budget would break during the act'
            break
        if m == 1:
            passed = True
            break
        tried.append(g)
        if arm == 'blind':
            break
    t1 = meter.read()
    J = meter.joules(t0, t1)
    if arm == 'blind':
        passed = bool(out) and complete(out, grid)      # scored outside its joules
    X = bq if passed else 0.0
    for a in acts:
        a['b_bits'] = bq if (a['m'] == 1 or (arm == 'blind' and passed)) else 0.0
    return {**run_meta, 'task': task['id'], 'stratum': task['stratum'], 'bin': b,
            'budget_j': budget, 'b_task_bits': bq, 'passed': passed, 'X_bits': X,
            'reported_j': J, 'cycles': t1[1] - t0[1], 'refused': refused,
            'refuse_reason': reason, 'cut': cut,
            'overspend': bool(budget) and J > budget, 'acts': acts}
