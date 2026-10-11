#!/usr/bin/env python3
"""G5-E: Form/spec synthesis with no model. The spec is the task's examples (input tuple -> output).
Bottom-up enumeration over a library of indexed handlers (Python builtins and string/list methods,
arithmetic, comparisons, map/filter/reduce comprehensions), with observational equivalence: two
expressions that give the same outputs on every example are one. The first expression whose outputs
match the spec on all examples is returned as `def f(args): return <expr>`. Deterministic: fixed
enumeration order, no randomness, no model."""
import itertools, math, sys, json, signal
BIG = 10**12
def ok(v):
    if isinstance(v, (int, float)) and not isinstance(v, bool): return abs(v) < BIG if not (isinstance(v, float) and math.isnan(v)) else False
    if isinstance(v, (str, list, tuple, set, dict)): return len(v) < 2000
    return isinstance(v, (bool, type(None)))
def key(vs):
    try: return repr(vs)
    except Exception: return None
UN = [("len({})", len), ("sum({})", sum), ("sorted({})", sorted), ("max({})", max), ("min({})", min), ("abs({})", abs),
      ("list({})", list), ("sorted(set({}))", lambda x: sorted(set(x))), ("len(set({}))", lambda x: len(set(x))), ("str({})", str), ("int({})", int),
      ("{}[::-1]", lambda x: x[::-1]), ("{}.lower()", lambda x: x.lower()), ("{}.upper()", lambda x: x.upper()), ("{}.split()", lambda x: x.split()),
      ("{}.strip()", lambda x: x.strip()), ("' '.join({})", lambda x: " ".join(x)), ("''.join({})", lambda x: "".join(x)),
      ("(not {})", lambda x: not x), ("(-{})", lambda x: -x), ("{}[0]", lambda x: x[0]), ("{}[-1]", lambda x: x[-1]),
      ("sorted({}, reverse=True)", lambda x: sorted(x, reverse=True)), ("tuple({})", tuple), ("set({})", set), ("bool({})", bool),
      ("float({})", float), ("math.sqrt({})", math.sqrt), ("math.factorial({})", math.factorial), ("{}.title()", lambda x: x.title()),
      ("{}.swapcase()", lambda x: x.swapcase()), ("{}.isupper()", lambda x: x.isupper()), ("{}.isdigit()", lambda x: x.isdigit()),
      ("len(str({}))", lambda x: len(str(x))), ("sum(int(c) for c in str({}))", lambda x: sum(int(c) for c in str(x))),
      ("bin({})[2:]", lambda x: bin(x)[2:]), ("math.prod({})", math.prod), ("any({})", any), ("all({})", all), ("{}[1:]", lambda x: x[1:]), ("{}[:-1]", lambda x: x[:-1])]
BIN = [("({} + {})", lambda a, b: a + b), ("({} - {})", lambda a, b: a - b), ("({} * {})", lambda a, b: a * b), ("({} // {})", lambda a, b: a // b),
       ("({} % {})", lambda a, b: a % b), ("({} / {})", lambda a, b: a / b), ("({} ** {})", lambda a, b: a ** b if abs(b) < 64 else None),
       ("({} == {})", lambda a, b: a == b), ("({} < {})", lambda a, b: a < b), ("({} > {})", lambda a, b: a > b), ("({} <= {})", lambda a, b: a <= b),
       ("({} >= {})", lambda a, b: a >= b), ("({} != {})", lambda a, b: a != b), ("({} and {})", lambda a, b: a and b), ("({} or {})", lambda a, b: a or b),
       ("{}.count({})", lambda a, b: a.count(b)), ("({} in {})", lambda a, b: a in b), ("{}[{}]", lambda a, b: a[b]), ("max({}, {})", max), ("min({}, {})", min),
       ("round({}, {})", round), ("{}.split({})", lambda a, b: a.split(b)), ("{}.join({})", lambda a, b: a.join(b)), ("{}[:{}]", lambda a, b: a[:b]),
       ("{}[{}:]", lambda a, b: a[b:]), ("math.gcd({}, {})", math.gcd), ("{}.startswith({})", lambda a, b: a.startswith(b)), ("{}.endswith({})", lambda a, b: a.endswith(b)),
       ("{}.index({})", lambda a, b: a.index(b)), ("{}.find({})", lambda a, b: a.find(b)), ("sorted({}, key={})", None)]
TRI = [("{}.replace({}, {})", lambda a, b, c: a.replace(b, c)), ("({} if {} else {})", lambda a, b, c: a if b else c), ("{}[{}:{}]", lambda a, b, c: a[b:c])]
COMP_EL = [("e", lambda e: e), ("e * e", lambda e: e * e), ("e * 2", lambda e: e * 2), ("e + 1", lambda e: e + 1), ("-e", lambda e: -e), ("abs(e)", abs),
           ("len(e)", len), ("str(e)", str), ("int(e)", int), ("e[0]", lambda e: e[0]), ("e[-1]", lambda e: e[-1]), ("e[1]", lambda e: e[1]), ("e[::-1]", lambda e: e[::-1]),
           ("e.lower()", lambda e: e.lower()), ("e.upper()", lambda e: e.upper()), ("e ** 3", lambda e: e ** 3), ("e.swapcase()", lambda e: e.swapcase()), ("sum(e)", sum), ("max(e)", max), ("min(e)", min)]
COMP_P = [("e % 2 == 0", lambda e: e % 2 == 0), ("e % 2 == 1", lambda e: e % 2 == 1), ("e > 0", lambda e: e > 0), ("e < 0", lambda e: e < 0), ("e != 0", lambda e: e != 0),
          ("e.isupper()", lambda e: e.isupper()), ("e.islower()", lambda e: e.islower()), ("e.isdigit()", lambda e: e.isdigit()), ("e.isalpha()", lambda e: e.isalpha()),
          ("e in 'aeiouAEIOU'", lambda e: e in "aeiouAEIOU"), ("e not in 'aeiouAEIOU'", lambda e: e not in "aeiouAEIOU"), ("e", bool), ("e != ' '", lambda e: e != " "),
          ("len(e) % 2 == 0", lambda e: len(e) % 2 == 0), ("e % 3 == 0", lambda e: e % 3 == 0), ("e % 5 == 0", lambda e: e % 5 == 0)]
def run1(f, *xs):
    try:
        v = f(*xs); return v if ok(v) else _BAD
    except Exception: return _BAD
_BAD = object()
def synth(params, examples, budget=60000, depth=3):
    """examples: list of (args tuple, expected). Returns expr string or None."""
    target = key([e[1] for e in examples]); n = len(examples)
    pool = {}  # key -> (code, values, size)
    def add(code, vals, size):
        if any(v is _BAD for v in vals): return None
        k = key(vals)
        if k is None or k in pool: return None
        pool[k] = (code, vals, size)
        if k == target: return code
        return None
    for i, p in enumerate(params):
        r = add(p, [e[0][i] for e in examples], 1)
        if r: return r
    for c in [0, 1, 2, -1, 10, "''", "' '", "True", "False", "[]"]:
        v = eval(str(c)); r = add(str(c), [v] * n, 1)
        if r: return r
    # comprehension templates over each list/str-valued parameter
    for i, p in enumerate(params):
        xs = [e[0][i] for e in examples]
        if not all(isinstance(x, (list, str, tuple)) for x in xs): continue
        for ec, ef in COMP_EL:
            for pc, pf in [("", None)] + COMP_P:
                cond = f" if {pc}" if pc else ""
                def mk(x, ef=ef, pf=pf): return [ef(e) for e in x if (pf is None or pf(e))]
                vals = [run1(mk, x) for x in xs]
                for wrap, wf in [("[{}]", lambda l: l), ("sum({})", sum), ("len({})", len), ("''.join({})", lambda l: "".join(l)), ("max({})", max), ("min({})", min), ("any({})", any), ("all({})", all)]:
                    v2 = [run1(wf, v) if v is not _BAD else _BAD for v in vals]
                    body = f"{ec} for e in {p}{cond}"
                    r = add(wrap.format(body) if wrap != "[{}]" else f"[{body}]", v2, 3)
                    if r: return r
    for d in range(2, depth + 1):
        items = list(pool.values())
        if len(pool) > budget: break
        new = []
        for code, vals, size in items:
            for fc, f in UN:
                new.append((fc.format(code), [run1(f, v) for v in vals], size + 1))
        for (c1, v1, s1), (c2, v2, s2) in itertools.product(items, repeat=2):
            if s1 + s2 + 1 > d + 1: continue
            for fc, f in BIN:
                if f is None: continue
                new.append((fc.format(c1, c2), [run1(f, a, b) for a, b in zip(v1, v2)], s1 + s2 + 1))
            if len(new) > budget * 4: break
        for code, vals, size in new:
            r = add(code, vals, size)
            if r: return r
            if len(pool) > budget: break
        if d == depth and len(items) < 400:
            for (c1, v1, _), (c2, v2, _), (c3, v3, _) in itertools.product(items[:120], repeat=3):
                for fc, f in TRI:
                    r = add(fc.format(c1, c2, c3), [run1(f, a, b, c) for a, b, c in zip(v1, v2, v3)], 4)
                    if r: return r
    return None
if __name__ == "__main__":
    t = json.loads(sys.stdin.read())
    signal.alarm(int(t.get("timeout", 30)))
    print(json.dumps({"expr": synth(t["params"], [(tuple(a), o) for a, o in t["examples"]])}))
