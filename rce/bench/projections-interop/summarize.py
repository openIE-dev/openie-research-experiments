#!/usr/bin/env python3
"""Tables of the registered run from results/ (loc.json, bench-*.json)."""
import json, os, sys

R = sys.argv[1]
NAMES = ["counter", "bank", "multi_region", "traffic_light", "door", "inventory", "rcedb", "float_keys"]
LANGS = ["python", "js", "rust"]
loc = json.load(open(os.path.join(R, "loc.json")))
o = []
o.append("## M1 lines of code (counted lines: not blank, not only a comment)\n")
o.append("| program | " + " | ".join(f"{l} emitted total / runtime / program / driver | {l} hand | {l} ratio program:hand" for l in LANGS) + " |")
o.append("|---" * (1 + 3 * len(LANGS)) + "|")
tot = {l: [0, 0] for l in LANGS}
for n in NAMES:
    row = [n]
    for l in LANGS:
        e, h = loc["emitted"][l][n], loc["hand"][l][n]
        tot[l][0] += e["program"]; tot[l][1] += h
        row += [f"{e['total']} / {e['runtime']} / {e['program']} / {e['driver']}", str(h), f"{e['program'] / h:.1f}"]
    o.append("| " + " | ".join(row) + " |")
o.append("| all eight | " + " | ".join(f"program {tot[l][0]} | {tot[l][1]} | {tot[l][0] / tot[l][1]:.1f}" for l in LANGS) + " |")
o.append("")
o.append("Hand-written shared lines (preamble + tail of programs file): " + ", ".join(f"{l} {loc['hand'][l]['preamble'] + loc['hand'][l]['tail']}" for l in LANGS) + ".")
o.append("")
o.append("## M2 glue (counted lines)\n")
o.append("| language | file | lines |")
o.append("|---|---|---|")
for l in LANGS:
    for f, c in loc["glue"][l].items():
        o.append(f"| {l} | examples/interop/{f} | {c} |")
    for f, c in loc["hand_glue"][l].items():
        o.append(f"| {l} (hand) | examples/interop/{f} | {c} |")
o.append("")
o.append("Glue lines that name one of the eight programs: " + ", ".join(f"{l} {c}" for l, c in loc["glue_per_program_lines"].items()) + ".")
o.append("")
o.append("## M3 per-call cost (ns, median of the repetitions of the mean per call)\n")
for l in LANGS:
    b = json.load(open(os.path.join(R, f"bench-{l}.json")))
    o.append(f"### {l} ({b['version']}, {b['passes']} passes x {b['reps']} repetitions)\n")
    o.append("| program | emitted decode | emitted step | emitted encode | boundary share | hand decode | hand step | hand encode | step ratio emitted:hand |")
    o.append("|---|---|---|---|---|---|---|---|---|")
    for n in NAMES:
        e, h = b["results"]["emitted"][n], b["results"]["hand"][n]
        share = (e["decode_ns"] + e["encode_ns"]) / (e["decode_ns"] + e["step_ns"] + e["encode_ns"])
        o.append(f"| {n} | {e['decode_ns']} | {e['step_ns']} | {e['encode_ns']} | {share:.0%} | {h['decode_ns']} | {h['step_ns']} | {h['encode_ns']} | {e['step_ns'] / max(h['step_ns'], 1):.1f} |")
    o.append("")
print("\n".join(o))
