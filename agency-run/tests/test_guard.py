"""Unit tests for the v2 budget guard. Run: python3 -m unittest tests.test_guard -v

1. Property: an agent that obeys guard_ok() and whose steps and close stay
   within the bounds the guard assumes never ends above its budget.
2. Integration: episode2() on every test task, every arm, tiny to generous
   budgets, under a fake meter whose energy jumps by a random amount up to a
   fixed step bound at every read (the adversarial case: each jump lands just
   before a check). No episode, including goal-blind cuts and the final
   comparison and read, ends above its budget.
"""
import json, os, random, sys, types, unittest

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


class FakeMeter(types.ModuleType):
    """Energy advances only at reads, by U(0, step) nJ. Same interface as meter."""
    def __init__(self, step_nj, seed):
        super().__init__('agency_run.meter')
        self.e = 0; self.c = 0; self.step = step_nj; self.r = random.Random(seed)
        self.LABEL = 'reported_j'

    def read(self):
        self.e += self.r.randint(0, self.step); self.c += 1000
        return (self.e, self.c, self.c, self.c)

    @staticmethod
    def joules(a, b):
        return (b[0] - a[0]) / 1e9


def load_agents(fake):
    import agency_run
    sys.modules['agency_run.meter'] = fake; agency_run.meter = fake
    for m in ('agency_run.agents', 'agency_run.agents2'):
        sys.modules.pop(m, None)
    import agency_run.agents2 as a2
    return a2


class TestGuardProperty(unittest.TestCase):
    def test_invariant(self):
        from agency_run.agents2 import guard_ok
        r = random.Random(7)
        for trial in range(20000):
            B = r.uniform(1e-4, 1.0)
            max_step = r.uniform(1e-7, B / 2)
            close = r.uniform(0, B / 4)
            spent = 0.0
            # each interval between checks costs <= 2 * max_step
            while guard_ok(spent, max_step, close, B):
                spent += r.uniform(0, 2 * max_step)
            spent += r.uniform(0, close)                  # the close
            self.assertLessEqual(spent, B, (trial, B, max_step, close))

    def test_refuses_when_close_does_not_fit(self):
        from agency_run.agents2 import guard_ok
        self.assertFalse(guard_ok(0.0, 0.0, 1.0, 1.0))
        self.assertFalse(guard_ok(0.5, 0.25, 0.0, 1.0))
        self.assertTrue(guard_ok(0.0, 0.1, 0.1, 1.0))


class TestEpisodeNeverOverspends(unittest.TestCase):
    def test_all_arms_all_tasks(self):
        step_nj = 20_000                                    # 20 microjoules per read at most
        fake = FakeMeter(step_nj, 11)
        a2 = load_agents(fake)
        with open(os.path.join(HERE, 'tasks', 'test.json')) as f:
            tasks = json.load(f)
        # a calibration table with plausible costs; values do not affect the invariant
        cost = {b: {'g0': 2e-4, 'g1': 6e-4, 'g2': 3e-3} for b in (0, 1, 2)}
        passes = {b: [{'g0': 0, 'g1': 1, 'g2': 1}, {'g0': 0, 'g1': 0, 'g2': 1}] for b in (0, 1, 2)}
        cal = a2.Calib2({'cost': cost, 'passes': passes, 'cost_q': cost})
        n = over = cuts = refusals = closed = 0
        worst = 0.0
        for seed in range(3):
            for B in (2e-5, 3e-5, 5e-5, 7e-5, 1e-4, 3e-4, 1e-3, 3e-3, 1e-2, 1e-1):
                for arm in ('sigma', 'mol', 'blind'):
                    G = {'step_floor': step_nj / 1e9, 'close_reserve': step_nj / 1e9}
                    rng = random.Random(seed)
                    for t in tasks:
                        ep = a2.episode2(t, arm, B, rng, cal, {}, G)
                        n += 1; over += ep['overspend']; cuts += ep['cut']
                        refusals += ep['refused']; closed += ep['passed']
                        worst = max(worst, ep['reported_j'] / B)
                        self.assertLessEqual(ep['reported_j'], B, (arm, B, t['id']))
        print(f'\n  episodes={n} overspends={over} cuts={cuts} refusals={refusals} closed={closed} max J/B={worst:.4f}')
        self.assertEqual(over, 0)
        self.assertGreater(cuts, 0)          # goal-blind cuts were exercised
        self.assertGreater(refusals, 0)      # refusals were exercised
        self.assertGreater(closed, 0)        # closes were exercised


class TestV1OverspendIsDetected(unittest.TestCase):
    """The same harness finds the v1 overspends (close outside the guard,
    goal-blind cuts with no first-step bound). Shows the test has teeth."""
    def test_v1_overspends(self):
        fake = FakeMeter(20_000, 5)
        load_agents(fake)
        import agency_run.agents as a1
        with open(os.path.join(HERE, 'tasks', 'test.json')) as f:
            tasks = json.load(f)
        cost = {b: {'g0': 2e-4, 'g1': 6e-4, 'g2': 3e-3} for b in (0, 1, 2)}
        passes = {b: [{'g0': 0, 'g1': 1, 'g2': 1}, {'g0': 0, 'g1': 0, 'g2': 1}] for b in (0, 1, 2)}
        cal = a1.Calib({'cost': cost, 'passes': passes})
        over = 0
        for B in (5e-5, 1e-4, 3e-4, 1e-3):
            for arm in ('sigma', 'mol', 'blind'):
                rng = random.Random(1)
                for t in tasks:
                    ep = a1.episode(t, arm, B, rng, cal, {})
                    over += ep['reported_j'] > B
        print(f'\n  v1 overspends under the same fake meter: {over}')
        self.assertGreater(over, 0)


if __name__ == '__main__':
    unittest.main(verbosity=2)
