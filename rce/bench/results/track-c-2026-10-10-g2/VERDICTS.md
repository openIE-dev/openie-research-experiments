# track-c-2026-10-10-g2: hypotheses against the run

Written after the run; REPORT.md is the generated record.

- H1 (G2 fires on soak-g2-schemas under geared; zero on the five earlier specs): **holds.** soak-g2-schemas/geared: G0 2, G1 2, G2 4. G2 is 0 in every other run.
- H2 (G3, G4, G5 zero): **holds** in all 12 runs.
- H3 (every run quiet before round 20): **fails for one run.** soak-g2-schemas/mock never goes quiet: the mock foreman installs handlers that fail the output-schema gate (41 attempts, 0 promotions survive), all 100 tasks close escalated. The other 11 runs are quiet by round 4 to 7; soak-g2-schemas/geared by round 5.
- H4 (measured_j empty): **holds.**
