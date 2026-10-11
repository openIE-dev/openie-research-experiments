"""Generate b3full-enrollment.fit.json: Enrollment's transition methods
over every field they write, as one Form rule that reads the stored row
(fit "reads": del_D1 by id into `prev`). Run: python3 gen_b3full.py"""
import json

N = "role_R1"
FIRST = "00000000-0000-0000-0000-000000000000"


def const(v): return {"t": "const", "value": v}
def proj(f): return {"t": "proj", "node": N, "field": f}
def pipe(a, b): return {"t": "pipe", "first": a, "then": b}
def obj(**kw): return {"t": "obj", "fields": [[k, v] for k, v in kw.items()]}
def ifeq(f, v, a, b): return {"t": "if_eq", "field": f, "value": v, "then": a, "otherwise": b}


# Stage 1: a flat record of the payload and the stored row (a new
# enrollment when there is none: Enrollment::new with a first step).
INITIAL = {"status": "Active", "current_step_id": FIRST, "next_step_at": None, "history_len": 0}
prev = ifeq("prev", None, const(INITIAL), proj("prev"))
flat = obj(id=proj("id"), op=proj("op"), nsid=proj("next_step_id"), nat=proj("next_at"),
           status=pipe(prev, proj("status")), cur=pipe(prev, proj("current_step_id")),
           nxt=pipe(prev, proj("next_step_at")), len=pipe(prev, proj("history_len")))


def row(status=None, cur=None, nxt=None, length=None, updated=True):
    return obj(id=proj("id"), status=status or proj("status"), current_step_id=cur or proj("cur"),
               next_step_at=nxt or proj("nxt"), history_len=length or proj("len"), updated=const(updated))


NULL = const(None)
ops = [
    ("pause", ifeq("status", "Active", row(status=const("Paused")), row(updated=False))),
    ("resume", ifeq("status", "Paused", row(status=const("Active")), row(updated=False))),
    ("complete", row(status=const("Completed"), cur=NULL, nxt=NULL)),
    ("mark_replied", row(status=const("Replied"), nxt=NULL)),
    ("mark_bounced", row(status=const("Bounced"), nxt=NULL)),
    ("mark_unsubscribed", row(status=const("Unsubscribed"), nxt=NULL)),
    ("manual_exit", row(status=const("ManualExit"), cur=NULL, nxt=NULL)),
    ("advance_to", ifeq("nsid", None, row(status=const("Completed"), cur=NULL, nxt=NULL),
                        row(cur=proj("nsid"), nxt=proj("nat")))),
    ("record_step", row(length={"t": "arith", "node": N, "op": "add", "a": proj("len"), "b": const(1)})),
]
body = {"t": "esc", "node": N, "reason": "unknown op"}
for name, t in reversed(ops):
    body = ifeq("op", name, t, body)

fit = {
    "handlers": {"dep_DEP1": {"kind": "passthrough"}, "del_D1": {"kind": "passthrough"}, N: {"kind": "term", "term": pipe(flat, body)}},
    "types": {"dep_DEP1": {"id": "text", "op": "text", "next_step_id": "json", "next_at": "json"}},
    "keys": {"del_D1": ["id"]},
    "reads": {"del_D1": {"key": ["id"], "into": "prev"}},
}
with open("b3full-enrollment.fit.json", "w") as f:
    json.dump(fit, f, indent=1)
    f.write("\n")
