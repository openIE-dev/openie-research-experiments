# Deviations from PREREG.json

## 2026-11-02

No deviation in procedure: both arms ran once each, in the registered order,
with the registered binary (SHA-256 `f7a8f301...43d1`), runner, cap and task
set (`tasks.jsonl` rebuilt by `frozen.py`, SHA-256 `6ae255a3...af50`). No
task ended by a signal and none reached the 900 s cap, so the rerun rule was
not used.

Location of files only: `tasks.jsonl` and the output directories of
`run.py` were written in a scratch directory outside this repository
(`run.py RCE tasks.jsonl SCRATCH/results/plain plain 900`, then the same for
`known`), and `summary.json`, `runs.compact.tsv` and the console output of
each arm were copied unchanged into `results/ARM/`; `runs.jsonl` was
compressed with `gzip -n -9` into `results/ARM/runs.jsonl.gz`. `report.py`
then ran in this directory as registered.
