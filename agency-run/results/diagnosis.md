# Diagnosis (post hoc, written after the main run)

These notes explain preregistered outcomes. They change no outcome.

## R-F2 fired: 36 of 5,400 episodes ended above budget

- 16 law-arm episodes (sigma 9, Mixture of Limits 7, all at B = 1.0 x J_g2, all easy tasks closed by g0) closed 0.07% to 3.6% above B. The act passed its last in-act budget check. The comparison C(z), the receipt entry and the final meter read then ran outside the guard.
- 20 goal-blind cut episodes at B = 0.5 x J_g2 overran by up to 33% (median 2.2% over all 36). Their budgets were 0.13 to 0.30 mJ, a few meter checks wide, so one step between checks was a large share of B.
- Fix for the next version: put the comparison and the receipt write inside the guarded region, and charge a measured closing cost before the act starts.

## Package cross-check could not resolve the agent

powermetrics read about 12.1 W CPU and 13.6 W GPU (window means) with the agent idle, from other work on the machine. The agent added about 0.6 W (17.5 to 17.9 reported joules per 30 s window, per-process meter). Background CPU power moved by about 0.5 W between windows, so idle-subtracted package joules came out negative. The per-process meter is the run's meter. A wall meter on an otherwise idle machine is needed for measured_j.

## Selectors

Post hoc, paired by seed (`results/posthoc.json`): at B = 1.0 x J_g2 the sigma-law selector closed 2.65 more tasks per run than Mixture of Limits (95% bootstrap interval 1.5 to 3.8) and had higher run iota by 10,650 bits per joule (4,747 to 16,592). On tasks both closed, J* did not differ (R-F1). The sigma-law rule moves straight to the gear that suffices, so the joules of failed light attempts stay in the budget.
