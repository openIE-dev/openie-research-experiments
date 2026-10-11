# agency-run

A small, reproducible benchmark for the Universal Law of Agency paper (`src/content/papers/agency.md`). An acceptor agent closes Sudoku tasks under binding joule budgets, with a predicted result fixed before each act, a comparison after it and refusal with a receipt. The selectors are the sigma-law rule and the Mixture of Limits cheapest-sufficient rule, with a goal-blind baseline.

Read `PREREGISTRATION.md` first. It was committed before any run.

```
python3 gen_tasks.py         # tasks/calib.json, tasks/test.json (deterministic)
python3 run.py pilot         # pilot/pilot_rows.jsonl, pilot/locked.json
python3 run.py main          # results/episodes.jsonl (receipts), results/runs.json
python3 run.py crosscheck    # powermetrics windows (needs sudo -n; skipped if absent)
python3 analyze.py           # results/summary.json, results/summary.md
```

Energy labels: every joule here is `reported_j`. The per-act figure is the kernel's per-process energy estimate (`ri_energy_nj`). The cross-check is `powermetrics`, which Apple describes as estimated. `measured_j` is empty: no wall meter was attached.
