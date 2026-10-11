# Pinned corpora (not vendored)

Large raw corpora are referenced, not copied. Pin these exact versions to reproduce.

| Corpus | Version | Where | Used by |
|---|---|---|---|
| Defects4J | the release checked out by `d4j_tbar.py`; 100-bug subset listed in `rce/bench/defects4j/tbar-ref/` | https://github.com/rjust/defects4j | RCE §8.1, `rce/bench/defects4j/` |
| TBar results | Results/PerfectFL/TBar, 2019-07-10 update | https://github.com/TruX-DTF/TBar | `rce/bench/defects4j/METHOD-tbar.md` |
| TSSB-3M | v1.0.0 (CC BY 4.0) | https://doi.org/10.5281/zenodo.5845439 | `rce/bench/ladder/` (L1) |
| ManySStuBs4J | 2.0 (CC BY 4.0) | https://doi.org/10.5281/zenodo.3653444 | `rce/bench/ladder/` (L1) |
| Track A sources | strsim 0.11.1, heck 0.5.0, shlex 2.0.1 (crates.io); packaging 25.0, idna 3.10 (PyPI) | crates.io, pypi.org | `rce/bench/track-a/` |
| SWE-bench Lite | 300 tasks | https://www.swebench.com | RCE §8.2 (protocol) |
