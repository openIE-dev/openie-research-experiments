#!/usr/bin/env python3
"""L5 local-model arm, reported separately: Qwen2.5-Coder-1.5B (Q4 GGUF) behind llama-server, greedy, 1 sample (pass@1).
Every accepted program is written to INDEX.jsonl keyed by task spec: the model's contribution compiled out. A rerun
of l5_run.py with --index then solves those tasks with 0 calls (it only helps when the same spec recurs).
Usage: l5_model.py mbpp|humaneval DATA OUT.jsonl INDEX.jsonl [--ids LO-HI] [--url http://127.0.0.1:8091]"""
import json, os, sys, re, gzip, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import l5_run as R
def complete(url, prompt, n=384):
    body = json.dumps({"prompt": prompt, "n_predict": n, "temperature": 0, "top_k": 1, "stop": ["\ndef ", "\nclass ", "\nif __name__", "\nprint(", "\n#", "\nassert", "```"]}).encode()
    r = json.loads(urllib.request.urlopen(urllib.request.Request(url + "/completion", body, {"Content-Type": "application/json"}), timeout=600).read())
    return r["content"], r.get("timings", {})
if __name__ == "__main__":
    kind, data, out, idx = sys.argv[1:5]; a = sys.argv[5:]
    g = lambda k, d: a[a.index(k) + 1] if k in a else d
    url = g("--url", "http://127.0.0.1:8091")
    ts = [json.loads(l) for l in (gzip.open(data, "rt") if data.endswith(".gz") else open(data))]
    if kind == "mbpp" and "--ids" in a:
        lo, hi = map(int, g("--ids", "").split("-")); ts = [t for t in ts if lo <= t["task_id"] <= hi]
    done = set(json.loads(l)["id"] for l in open(out)) if os.path.exists(out) else set()
    with open(out, "a") as fo, open(idx, "a") as fi:
        for t in ts:
            tid = f"{kind}/{t['task_id']}"
            if tid in done: continue
            if kind == "humaneval":
                prompt = t["prompt"]; tests = t["test"] + f"\ncheck({t['entry_point']})\n"
                text, tm = complete(url, prompt); prog = prompt + text
            else:
                prompt = '"""\n' + t["text"] + "\nYour code should pass these tests:\n" + "\n".join(t["test_list"]) + '\n"""\n'
                text, tm = complete(url, prompt); prog = (t.get("test_setup_code") or "") + "\n" + text; tests = "\n".join(t["test_list"])
            ok = R.gate(prog, tests)
            rec = {"id": tid, "rung": "L5", "arm": "local-model", "model": "Qwen2.5-Coder-1.5B-Q4 (cc324af0)", "llm_calls": 1, "solved": ok,
                   "tokens": tm.get("predicted_n"), "gen_ms": tm.get("predicted_ms")}
            fo.write(json.dumps(rec) + "\n"); fo.flush()
            if ok: fi.write(json.dumps({"spec": R.spec_hash(kind, t), "id": tid, "program": prog}) + "\n"); fi.flush()
