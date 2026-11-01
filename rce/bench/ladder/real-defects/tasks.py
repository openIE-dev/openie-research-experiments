#!/usr/bin/env python3
"""The task set of the second registered ladder run: real defects.

    python3 tasks.py RCE RCE_REPO BASE OUT.jsonl

RCE is the `rce` binary of the ladder commit, RCE_REPO a clone of
openIE-dev/rce and BASE the commit whose history and corpus are used.
Three sources, and no operator or literal mutation:

  history   every commit reachable from BASE (no merges, full history) that
            modifies an .rce file under spec/examples, programs or stdlib;
            the pair (parent text, child text) of that file is a task when
            `rce check` (of the ladder binary, standalone) reports the
            parent as requiring change and admits the child. The task's
            mutant is the parent text and its original the child text. The
            source is `history-fix` when the commit subject names a fix
            (the word fix, fixes, fixed or bug), else `history-admit`.
  guard     one condition negated: on a line that is not an intent,
            example or check line, the condition of an `if`, `elif` or
            `while` (C of `while C bound N`), or the guard of a step or arm
            (`... if C ->`), C becomes `not (C)`.
  rename    one use of a value name replaced by another: inside one
            definition, an occurrence of a parameter or a `let`/`var`/`for`
            binding (not after `.`, not a label, not where it is bound) on a
            line that is not an intent, example or check line becomes the
            name of another parameter or binding of the same definition
            bound on an earlier line and in scope there (its block has not
            closed; the fields of a step's state count as bound).

The guard and rename population is that of scripts/ladder-tasks.py: every
.rce file under spec/examples, programs and stdlib/tests of BASE (not under
refused/ or change/, not a _FIXTURE) that `rce check` admits standalone and
that has an intent, example or check line and a definition outside them.
For each program, every guard site and every rename site is listed in text
order; at most K = 2 of each are drawn with the seeded generator of
scripts/corpus.py (seed 0x5EED_C0DE_0002), each draw taking the site at
index next() mod (sites left). A guard or rename mutant is a task when
`rce check` reports it as requiring change and, when the only rule reported
is W-INT-1, `rce equiv fuel 2000` does not judge it behaviour-equal to the
original (exit 0). Unlike the first run, a mutant that requires change under
a static rule (for example W-TY-1 or W-UNUSED-1) is a task too.

Each line of OUT.jsonl is one task; the last line printed is the SHA-256 of
OUT.jsonl. The run is a pure function of RCE, BASE and the seed.
"""
import hashlib, json, re, subprocess, sys, tempfile
from pathlib import Path

SEED = 0x5EED_C0DE_0002
K = 2
DEFS = ("fn ", "pub fn ", "step ", "actor ", "const ", "pub const ", "state ", "impl ")
FIX = re.compile(r"\b(fix|fixes|fixed|bug)\b", re.I)
KEYWORDS = set("""fn pub let var if elif else while for in return match step on state actor const impl struct enum
use as and or not true false some none ok err intent example check requires ensures self emit module type trait
linear extern spawn send recv loop break continue bound kind where""".split())


class Rng:
    """The splitmix64 generator of scripts/corpus.py."""

    def __init__(self, s):
        self.s = s & ((1 << 64) - 1)

    def next(self):
        self.s = (self.s + 0x9E3779B97F4A7C15) & ((1 << 64) - 1)
        z = self.s
        z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & ((1 << 64) - 1)
        z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & ((1 << 64) - 1)
        return z ^ (z >> 31)


def sha(t):
    return hashlib.sha256(t.encode()).hexdigest()


def git(repo, *a):
    r = subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else None


def spec_lines(src):
    """0-based indices of intent, example and check lines (as scripts/ladder-tasks.py)."""
    out, in_intent = set(), False
    for i, l in enumerate(src.split("\n")):
        s = l.strip()
        if l.startswith("intent "):
            in_intent = True
            out.add(i)
            continue
        if in_intent and (l.startswith(" ") or s == ""):
            out.add(i)
            continue
        in_intent = False
        if s.startswith(("check ", "example ")):
            out.add(i)
    return out


def changed_lines(a, b):
    x, y = a.split("\n"), b.split("\n")
    if len(x) != len(y):
        p = 0
        while p < min(len(x), len(y)) and x[p] == y[p]:
            p += 1
        return {p}
    return {i for i in range(len(x)) if x[i] != y[i]}


def codes(msg):
    body = msg.split(": ", 1)[1] if ": " in msg else msg
    return sorted(set(re.findall(r"\bW-[A-Z0-9]+(?:-\d+)?\b", body)))


class Checker:
    def __init__(self, rce):
        self.rce = rce
        self.tmp = Path(tempfile.mkdtemp(prefix="ladder-real-"))

    def check(self, text, name):
        f = self.tmp / name
        f.write_text(text, encoding="utf-8")
        r = subprocess.run([self.rce, "check", str(f)], capture_output=True, text=True)
        return r.returncode, (r.stdout + r.stderr).strip()

    def equiv(self, a, b, name):
        fa, fb = self.tmp / ("a-" + name), self.tmp / ("b-" + name)
        fa.write_text(a, encoding="utf-8")
        fb.write_text(b, encoding="utf-8")
        return subprocess.run([self.rce, "equiv", "fuel", "2000", str(fa), str(fb)], capture_output=True, text=True).returncode


def strip_strings(line):
    """The line with string contents and a trailing comment blanked (same length)."""
    out, i, q = [], 0, False
    while i < len(line):
        c = line[i]
        if q:
            if c == "\\" and i + 1 < len(line):
                out.append("  ")
                i += 2
                continue
            if c == '"':
                q = False
                out.append(c)
            else:
                out.append(" ")
        elif c == '"':
            q = True
            out.append(c)
        elif c == "#":
            out.append(" " * (len(line) - i))
            break
        else:
            out.append(c)
        i += 1
    return "".join(out)


GUARD_LINE = re.compile(r"^(\s*)(if|elif|while)\s+(.*\S)\s*$")
ARM_GUARD = re.compile(r"\sif\s+(.*?)\s*->")


def guard_sites(src, sl):
    """(line index, new line) for every condition that can be negated, in text order."""
    out = []
    for i, l in enumerate(src.split("\n")):
        if i in sl:
            continue
        s = strip_strings(l)
        m = GUARD_LINE.match(s)
        if m and not s.rstrip().endswith("->"):
            a, b = m.start(3), m.end(3)
            # `while C bound N`: the condition is C
            k = s.rfind(" bound ", a, b)
            if m.group(2) == "while" and k >= 0:
                b = k
            out.append((i, l[:a] + "not (" + l[a:b] + ")" + l[b:]))
            continue
        m = ARM_GUARD.search(s)
        if m:
            a, b = m.start(1), m.end(1)
            out.append((i, l[:a] + "not (" + l[a:b] + ")" + l[b:]))
    return out


IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def definitions(lines):
    """(first, last) line indices of each top-level definition block."""
    out, start = [], None
    for i, l in enumerate(lines):
        top = l and not l[0].isspace() and not l.startswith("#")
        if top:
            if start is not None:
                out.append((start, i - 1))
                start = None
            if l.startswith(DEFS):
                start = i
    if start is not None:
        out.append((start, len(lines) - 1))
    return out


def binders(line, first):
    """Names a line binds: parameters on the first line of a definition,
    `let`/`var` names and `for` variables."""
    s = strip_strings(line)
    names = []
    if first and s.startswith("step "):
        # a step's event pattern binds the names after `field:`
        p, q = s.find("("), s.find(")")
        if p >= 0 and q > p:
            for m in re.finditer(r":\s*([a-z_][A-Za-z0-9_]*)\s*(?=[,)])", s[p:q + 1]):
                names.append(m.group(1))
    elif first:
        p = s.find("(")
        q = s.rfind(")")
        if p >= 0 and q > p:
            for m in re.finditer(r"(?:^|[(,])\s*(?:mut\s+)?([a-z_][A-Za-z0-9_]*)\s*:", s[p:q + 1]):
                names.append(m.group(1))
    for m in re.finditer(r"\b(?:let|var)\s+(?:mut\s+)?([a-z_][A-Za-z0-9_]*)\b", s):
        names.append(m.group(1))
    for m in re.finditer(r"\bfor\s+([a-z_][A-Za-z0-9_]*)\s+in\b", s):
        names.append(m.group(1))
    return [n for n in names if n not in KEYWORDS and n != "_"]


def state_fields(lines):
    """The field names of each `state NAME` declaration."""
    out, cur = {}, None
    for l in lines:
        m = re.match(r"state\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", l)
        if m:
            cur = out.setdefault(m.group(1), [])
            continue
        if cur is not None and l.startswith((" ", "\t")):
            f = re.match(r"\s+([a-z_][A-Za-z0-9_]*)\s*:", l)
            if f:
                cur.append(f.group(1))
            continue
        if l.strip():
            cur = None
    return out


def indent(l):
    return len(l) - len(l.lstrip(" "))


def visible(lines, at, i, first):
    """Whether a name bound on line `at` is in scope on line `i`: bound on
    the definition's first line (or before it, a state field), or on a line
    whose block has not closed before `i` (no line between them with less
    indentation, blank lines aside)."""
    if at <= first:
        return True
    d = indent(lines[at])
    if indent(lines[i]) < d:
        return False
    return all(indent(lines[k]) >= d for k in range(at + 1, i) if lines[k].strip())


def rename_sites(src, sl):
    """(line index, new line) for every use of a bound value name replaced by
    another name bound earlier in the same definition, in text order."""
    lines = src.split("\n")
    fields = state_fields(lines)
    out = []
    for a, b in definitions(lines):
        bound = []  # (name, line it is bound on)
        m = re.match(r"step\s+([A-Za-z_][A-Za-z0-9_]*)\s+on\b", lines[a])
        if m:
            # a step reads the fields of its state as names
            bound += [(f, a - 1) for f in fields.get(m.group(1), [])]
        for i in range(a, b + 1):
            here = binders(lines[i], i == a)
            if i not in sl and i > a:
                s = strip_strings(lines[i])
                for m in IDENT.finditer(s):
                    n = m.group(0)
                    known = [x for x, at in bound if at < i and visible(lines, at, i, a)]
                    if n not in known:
                        continue
                    if m.start() > 0 and s[m.start() - 1] == ".":
                        continue
                    rest = s[m.end():].lstrip()
                    if rest.startswith(":") and not rest.startswith("::"):
                        continue
                    if n in here and re.search(r"\b(let|var|for)\s+(mut\s+)?" + re.escape(n) + r"\b", s[:m.end()]):
                        continue
                    for o in sorted(set(known)):
                        if o != n:
                            out.append((i, lines[i][:m.start()] + o + lines[i][m.end():]))
            for n in here:
                if all(n != x for x, _ in bound):
                    bound.append((n, i))
    return out


def draw(sites, rng, k):
    left = list(sites)
    got = []
    while left and len(got) < k:
        got.append(left.pop(rng.next() % len(left)))
    return got


def main(argv):
    if len(argv) != 4:
        sys.exit("usage: tasks.py RCE RCE_REPO BASE OUT.jsonl")
    rce, repo, base, out = argv[0], argv[1], argv[2], Path(argv[3])
    ck = Checker(rce)
    tasks, stats = [], {"history": {}, "guard": {}, "rename": {}}

    def bump(src, k):
        stats[src][k] = stats[src].get(k, 0) + 1

    # ---- history
    commits = git(repo, "rev-list", "--no-merges", "--full-history", base, "--", "spec/examples", "programs", "stdlib").split()
    for c in reversed(commits):
        subject = git(repo, "log", "-1", "--format=%s", c).strip()
        st = git(repo, "diff-tree", "--no-commit-id", "-r", "--name-status", c, "--", "spec/examples", "programs", "stdlib")
        for row in st.splitlines():
            parts = row.split("\t")
            if parts[0] != "M" or not parts[1].endswith(".rce"):
                continue
            p = parts[1]
            bump("history", "pairs")
            par, chi = git(repo, "show", f"{c}^:{p}"), git(repo, "show", f"{c}:{p}")
            if par is None or chi is None or par == chi:
                bump("history", "unreadable_or_equal")
                continue
            name = Path(p).name
            rp, mp = ck.check(par, name)
            rc, _ = ck.check(chi, name)
            if rp == 0:
                bump("history", "parent_admitted")
                continue
            if rc != 0:
                bump("history", "child_requires_change")
                continue
            src = "history-fix" if FIX.search(subject) else "history-admit"
            bump("history", src)
            tasks.append({"id": f"{p}@{c[:8]}", "source": src, "operator": src, "path": p, "commit": c, "subject": subject,
                          "original": chi, "mutant": par, "original_sha256": sha(chi), "mutant_sha256": sha(par),
                          "mutant_rules": codes(mp), "line": sorted(changed_lines(chi, par))[0] + 1})

    # ---- guard and rename
    rng = Rng(SEED)
    pop = []
    for d in ("spec/examples", "programs", "stdlib/tests"):
        names = git(repo, "ls-tree", "-r", "--name-only", base, "--", d).split()
        for p in sorted(n for n in names if n.endswith(".rce")):
            if "/refused/" in p or "/change/" in p or "_FIXTURE" in Path(p).name:
                continue
            pop.append(p)
    for p in pop:
        src = git(repo, "show", f"{base}:{p}")
        sl = spec_lines(src)
        if not sl or not any(l.lstrip().startswith(DEFS) for k, l in enumerate(src.split("\n")) if k not in sl):
            continue
        name = Path(p).name
        if ck.check(src, name)[0] != 0:
            continue
        lines = src.split("\n")
        for op, sites in (("guard", guard_sites(src, sl)), ("rename", rename_sites(src, sl))):
            for i, new in draw(sites, rng, K):
                bump(op, "drawn")
                t = "\n".join(lines[:i] + [new] + lines[i + 1:])
                if t == src or changed_lines(src, t) & sl:
                    bump(op, "spec_line_or_equal")
                    continue
                code, msg = ck.check(t, "mut-" + name)
                if code == 0:
                    bump(op, "admitted")
                    continue
                rules = codes(msg)
                if rules == ["W-INT-1"] and ck.equiv(src, t, name) == 0:
                    bump(op, "equivalent")
                    continue
                bump(op, "tasks")
                n = sum(1 for x in tasks if x["path"] == p and x["source"] == op)
                tasks.append({"id": f"{p}#{op}{n}", "source": op, "operator": op, "path": p, "commit": base,
                              "original": src, "mutant": t, "original_sha256": sha(src), "mutant_sha256": sha(t),
                              "mutant_rules": rules, "line": i + 1})
    seen, uniq = set(), []
    for t in tasks:
        key = (t["original_sha256"], t["mutant_sha256"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(t)
    with open(out, "w", encoding="utf-8") as fh:
        for t in uniq:
            fh.write(json.dumps(t, sort_keys=True, ensure_ascii=False) + "\n")
    by = {}
    for t in uniq:
        by[t["source"]] = by.get(t["source"], 0) + 1
    summary = {"base": base, "seed": hex(SEED), "per_op": K, "tasks": len(uniq), "by_source": by, "generator_counts": stats,
               "duplicates_dropped": len(tasks) - len(uniq)}
    print(json.dumps(summary, indent=1, sort_keys=True))
    print(hashlib.sha256(out.read_bytes()).hexdigest())


if __name__ == "__main__":
    main(sys.argv[1:])
