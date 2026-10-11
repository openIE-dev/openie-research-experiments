"""Generates the benchmark Forms (spec + fit) next to this file.
The fits are written by this script, not by hand."""
import json, os
os.chdir(os.path.dirname(os.path.abspath(__file__)))
N='role_R1'
def P(f): return {"t":"proj","node":N,"field":f}
def C(v): return {"t":"const","value":v}
def A(op,a,b): return {"t":"arith","node":N,"op":op,"a":a,"b":b}
def IFEQ(f,v,t,o): return {"t":"if_eq","field":f,"value":v,"then":t,"otherwise":o}
def OBJ(*fs): return {"t":"obj","fields":[[k,v] for k,v in fs]}
def ESC(r): return {"t":"esc","node":N,"reason":r}

def spec(name, reason, schema, role, dep):
    return f'''spec "{name}" v0.1.0
reason "{reason}" by "david"
currency max_age=24h

objective O1 "Re-express"
  metric agreement target 1
  reason "frozen benchmark: original code re-expressed as a Form" by "david"

acceptance A1 validates O1
  property "for all recorded inputs: the Form's output equals the original program's"
  reason "trace equivalence" by "david"

deliverable D1 fulfills O1
  schema "{schema}"
  reason "results" by "david"

role R1 "{role}" execution_node
  reason "computes {role}" by "david"

dependency DEP1 crate "{dep}"
  reason "inputs" by "david"

flow F1 from DEP1 to R1
  reason "inputs to {role}" by "david"

flow G1 from R1 to D1
  reason "results recorded" by "david"

change_control approvers ["david"] review_period 24h
'''

def fit(term, types):
    return {"handlers":{"dep_DEP1":{"kind":"passthrough"},N:{"kind":"term","term":term},"del_D1":{"kind":"passthrough"}},"types":{"dep_DEP1":types}}

# B1: SequenceMetrics::{open,click,reply,bounce,unsubscribe}_rate
def rate(f):
    # if total_sent == 0 { 0.0 } else { (f as f64 / total_sent as f64) * 100.0 }
    return IFEQ("total_sent",0,C(0),A("fmul",A("fdiv",P(f),P("total_sent")),C(100)))
b1=OBJ(("open_rate",rate("total_opens")),("click_rate",rate("total_clicks")),("reply_rate",rate("total_replies")),
       ("bounce_rate",rate("total_bounces")),("unsubscribe_rate",rate("total_unsubscribes")))
b1t={k:"int" for k in ["total_sent","total_opens","total_clicks","total_replies","total_bounces","total_unsubscribes"]}

# B2: SenderHealth::recalculate_reputation (with bounce_rate, complaint_rate)
def pct(f): return A("fmul",A("fdiv",P(f),P("total_sent")),C(100))
raw=A("fsub",A("fsub",A("fsub",C(100),A("fmul",pct("total_bounces"),C(10))),A("fmul",pct("total_complaints"),C(50))),A("fmul",pct("total_unsubscribes"),C(5)))
b2=IFEQ("total_sent",0,OBJ(("reputation_score",C(100))),OBJ(("reputation_score",A("max",C(0),A("min",C(100),raw)))))
b2t={k:"int" for k in ["total_sent","total_bounces","total_complaints","total_unsubscribes"]}

# B3: Enrollment status transitions (pause, resume, complete, mark_*, manual_exit, advance_to)
keep=OBJ(("status",P("status")))
def to(s): return C({"status":s})
chain=[("pause",IFEQ("status","Active",to("Paused"),keep)),
       ("resume",IFEQ("status","Paused",to("Active"),keep)),
       ("complete",to("Completed")),("mark_replied",to("Replied")),("mark_bounced",to("Bounced")),
       ("mark_unsubscribed",to("Unsubscribed")),("manual_exit",to("ManualExit")),
       ("advance_to",IFEQ("next_step_id",None,to("Completed"),keep))]
b3=ESC("unknown method")
for op,t in reversed(chain): b3=IFEQ("op",op,t,b3)
b3t={"status":"text","op":"text","next_step_id":"json"}

for name,reason,schema,role,dep,term,types in [
  ("b1-sequence-rates","joule-sales-outreach analytics.rs SequenceMetrics rates","Rates","rates","sequence-metrics",b1,b1t),
  ("b2-sender-reputation","joule-sales-outreach analytics.rs SenderHealth::recalculate_reputation","Reputation","reputation","sender-health",b2,b2t),
  ("b3-enrollment-status","joule-sales-outreach enrollment.rs Enrollment status transitions","Status","transition","enrollment",b3,b3t)]:
    open(name+".rce","w").write(spec(name,reason,schema,role,dep))
    open(name+".fit.json","w").write(json.dumps(fit(term,types),indent=1)+"\n")
