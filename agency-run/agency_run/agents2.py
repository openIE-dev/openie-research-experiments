"""v2 acceptor agents. Same arms, same H(a) as v1 (agents.py). Two changes, both
preregistered in PREREGISTRATION_v2.md:

1. Budget guard. Every joule of an episode is charged inside the guard: the
   selection, the predicted result, every gear step, the comparison C(z), the
   receipt entry and the final meter read. The agent may start any further
   work only while
       spent + 2 * max_step + close_reserve < B,
   where max_step is the largest metered step so far in the episode (floored
   by the largest step seen in the v2 pilot) and close_reserve bounds the cost
   of closing an episode (comparison, receipt, final read); it starts at the
   largest close seen in the v2 pilot and rises to 1.5 times any larger close. Goal-blind cuts obey the same
   rule. The opening decision is made at t0 without a further read. The
   bound holds whenever B >= close_reserve, since opening and closing an
   episode cost one interval. guard_ok() is the rule; tests/test_guard.py
   proves the invariant.
2. Refusal threshold. The budget-fit test uses the r-quantile of calibrated
   gear cost in the task's bin, with r chosen on the calibration split by the
   replay in run2.py. The sigma-law value H(a) - lambda J(a) is unchanged.
"""
import hashlib, json, time
from . import meter
from .sudoku import GEARS, ORDER, Abort, complete, bits
from .agents import Calib, ebin, THETA


def guard_ok(spent, max_step, close_reserve, budget):
    """True when one more step of cost <= max_step, then a close of cost
    <= close_reserve, keeps the episode within budget, with a factor 2 margin
    on the step."""
    return spent + 2.0 * max_step + close_reserve < budget


class Calib2(Calib):
    def __init__(self, d):
        super().__init__(d)
        self.costq = {int(k): v for k, v in d['cost_q'].items()}

    def cq(self, b, g):
        return self.costq[b][g]


def select2(arm, calib, b, tried, rem, bits_q, lam):
    left = [g for g in ORDER if g not in tried]
    if not left:
        return None, 'all gears tried and failed'
    if arm == 'mol':
        pick = None
        for g in left:
            if calib.p(b, g, tried) >= THETA:
                pick = g; break
        if pick is None:
            pick = max(left, key=lambda g: calib.p(b, g, tried))
        if calib.cq(b, pick) > rem:
            return None, f'next gear {pick} would break the budget'
        return pick, None
    if arm == 'sigma':
        fit = [g for g in left if calib.cq(b, g) <= rem]
        if not fit:
            return None, 'no gear fits the remaining budget'
        val = {g: calib.p(b, g, tried) * bits_q - lam * calib.c(b, g) for g in fit}   # H(a) - lambda J(a), as v1
        g = max(fit, key=lambda g: val[g])
        if val[g] <= 0:
            return None, 'no act has positive value H(a) - lambda J(a)'
        return g, None
    raise ValueError(arm)


def episode2(task, arm, budget, rng, calib, run_meta, G):
    """G: {'step_floor': J, 'close_reserve': J} (close_reserve adapts upward)."""
    grid = task['grid']; bq = bits(grid)
    lam = bq / budget
    st = {'max_step': G['step_floor']}
    t0 = meter.read(); st['last'] = t0

    def check():
        x = meter.read()
        step = meter.joules(st['last'], x); st['last'] = x
        if step > st['max_step']:
            st['max_step'] = step
        return guard_ok(meter.joules(t0, x), st['max_step'], G['close_reserve'], budget)

    b = ebin(grid)
    acts, tried = [], []
    passed = refused = cut = False
    reason, out = None, None
    first = True
    while True:
        # the opening decision uses no meter read: spent is zero at t0
        ok = guard_ok(0.0, st['max_step'], G['close_reserve'], budget) if first else check()
        first = False
        if not ok:
            if arm == 'blind':
                cut = True
            else:
                refused, reason = True, 'no room for another step and a close'
            break
        rem = budget - meter.joules(t0, st['last']) - G['close_reserve']
        rstar = h = ts = None
        if arm == 'blind':
            if acts:
                break
            g = rng.choice(ORDER)
        else:
            g, why = select2(arm, calib, b, tried, rem, bq, lam)
            if g is None:
                refused, reason = True, why
                break
            rstar = {'task': task['id'], 'gear': g, 'predict': 'C(z)=1',
                     'predicted_j': calib.c(b, g), 'budget_left_j': rem}
            h = hashlib.sha256(json.dumps(rstar, sort_keys=True).encode()).hexdigest()
            ts = time.time_ns()
        a0 = st['last']
        aborted = False
        try:
            out, nodes = GEARS[g](grid, rng=rng, check=check)
        except Abort:
            aborted, nodes, out = True, None, None
        g_end = meter.read(); st['last'] = g_end
        m = None
        if arm != 'blind' and not aborted:
            m = 1 if complete(out, grid) else 0          # comparison, inside the guard
        acts.append({'gear': g, 'prediction_hash': h, 'prediction_ts': ts,
                     'outcome_hash': hashlib.sha256(bytes(out)).hexdigest() if out else None,
                     'm': m, 'aborted': aborted, 'nodes': nodes,
                     'reported_j': meter.joules(a0, g_end), 'cycles': g_end[1] - a0[1]})
        if aborted:
            if arm == 'blind':
                cut = True
            else:
                refused, reason = True, 'budget guard stopped the act'
            break
        if m == 1:
            passed = True
            break
        tried.append(g)
        if arm == 'blind':
            break
    t_close0 = st['last']
    t1 = meter.read()                                     # final read closes the episode
    close_j = meter.joules(t_close0, t1)
    if 1.5 * close_j > G['close_reserve']:                # preregistered upward adaptation
        G['close_reserve'] = 1.5 * close_j
    J = meter.joules(t0, t1)
    if arm == 'blind':
        passed = bool(out) and complete(out, grid)        # scored outside its joules
    X = bq if passed else 0.0
    for a in acts:
        a['b_bits'] = bq if (a['m'] == 1 or (arm == 'blind' and passed)) else 0.0
    return {**run_meta, 'task': task['id'], 'stratum': task['stratum'], 'bin': b,
            'budget_j': budget, 'b_task_bits': bq, 'passed': passed, 'X_bits': X,
            'reported_j': J, 'cycles': t1[1] - t0[1], 'refused': refused,
            'refuse_reason': reason, 'cut': cut, 'overspend': J > budget,
            'close_j': close_j, 'acts': acts}
