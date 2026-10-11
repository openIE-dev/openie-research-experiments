# track-c-2026-10-10-live2: hypotheses against the run

Written after the run; REPORT.md is the generated record. Rerun of
track-c-2026-10-10-live (whose verdicts stay as the record) after per-shape
shadow candidates, distinct-sample counting, exhaustive finite shapes,
shadow-serving and distinct {round, n} schemaless traffic.

- H1 (every one of the 12 runs reaches a quiet round before round 20): **holds.** First quiet rounds: web-api 4, joule-db-core 7, follow-bible-ingest 6, follow-bible-ingest-schemas 8, ask-server 5, soak-g2-schemas 5, the same for both foremen.
- H2 (every run closes tasks ok): **holds.** Closed ok: web-api 170, joule-db-core 70, follow-bible-ingest 330, follow-bible-ingest-schemas 316, ask-server 435, soak-g2-schemas 80 (the old live run: 0, 0, 35, 20, 70, 0).
- H3 (no run fails): **holds.** Every exit code is 0.
- H4 (measured_j empty): **holds.**

Note: closed-esc counts (20 to 84 per run) are the first rounds' tasks,
before a candidate existed to shadow-serve them.
