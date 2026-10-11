# track-c-2026-10-10-live: hypotheses against the run

Written after the run; REPORT.md is the generated record. Same
registration as track-c-2026-10-10-g2 except `--live-coverage`.

- H1 (no run fails, every run reaches a quiet round before round 20): **fails.** No run exits non-zero, but no run of the 12 reaches a quiet round. With live traffic only, the coverage bound (60 clean samples per shape, error budget 0.05) is not met within 20 rounds, so promoted handlers stay on probation and escalations keep arriving. Closed-ok counts fall sharply: web-api 170 → 0, joule-db-core 70 → 0, follow-bible-ingest 330 → 35, follow-bible-ingest-schemas 330 → 20, ask-server 435 → 70, soak-g2-schemas/geared 80 → 0.
- H2 (first quiet round same or later than in the g2 run): **holds trivially** (never quiet is later than any round). The finding is stronger than the hypothesis: under this traffic, synthetic same-shape samples are what lets the soak converge at all.
- H3 (same gear mix as the g2 run): **fails.** Fewer resolutions at every gear (e.g. web-api/geared G0+G1 8 → 6; follow-bible-ingest-schemas/geared G1 15 → 8; soak-g2-schemas/geared G1+G2 6 → 4, G0 2 → 0), because fewer rounds produce a new escalation that reaches the foreman.
- H4 (measured_j empty): **holds.**
