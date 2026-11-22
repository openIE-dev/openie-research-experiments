//! Empirical measurement falsifier gates from SATB-IO enforced before sealing
//! derived metrics into `JCR-1`:
//! - **Falsifier 6 (`<= 5.00%` baseline-drift gate)**: when pre/post idle power
//!   drifts by more than `500` basis points (`5.00%`), `derived_marginal_uj` is
//!   dropped (`None`) while `raw_counter_uj` remains sealed in `JCR-1`.
//! - **Step 7 (`<= 1 uJ` sequential sum check)**: sequential sub-phases inside an
//!   accounting window must sum to the enclosing window within `1 uJ`.

use serde::{Deserialize, Serialize};

/// Maximum baseline drift allowed before Falsifier 6 drops `derived_marginal_uj`.
pub const FALSIFIER_6_MAX_DRIFT_BPS: u64 = 500;

/// Maximum phase-sum residual allowed by Step 7 (`1 uJ`).
pub const STEP_7_MAX_RESIDUAL_UJ: u64 = 1;

/// Evaluated SATB Falsifier 6 pre/post idle baseline check.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Falsifier6Gate {
    pub raw_counter_uj: u64,
    pub window_us: u64,
    pub pre_idle_uw: u64,
    pub post_idle_uw: u64,
    pub drift_bps: u64,
    pub passed: bool,
    pub derived_marginal_uj: Option<u64>,
}

impl Falsifier6Gate {
    pub fn evaluate(
        raw_counter_uj: u64,
        window_us: u64,
        pre_idle_uw: u64,
        post_idle_uw: u64,
    ) -> Self {
        let denom = pre_idle_uw.max(1);
        let diff = post_idle_uw.abs_diff(pre_idle_uw);
        let drift_bps = (u128::from(diff) * 10_000 / u128::from(denom)) as u64;
        let passed = drift_bps <= FALSIFIER_6_MAX_DRIFT_BPS;
        let derived_marginal_uj = if passed {
            let mean_idle_uw = (u128::from(pre_idle_uw) + u128::from(post_idle_uw)) / 2;
            let baseline_uj = (mean_idle_uw * u128::from(window_us) / 1_000_000) as u64;
            Some(raw_counter_uj.saturating_sub(baseline_uj))
        } else {
            None
        };
        Self {
            raw_counter_uj,
            window_us,
            pre_idle_uw,
            post_idle_uw,
            drift_bps,
            passed,
            derived_marginal_uj,
        }
    }
}

/// Evaluated SATB Step 7 sequential phase conservation check.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub struct Step7SumGate {
    pub sum_phases_uj: u64,
    pub window_uj: u64,
    pub residual_uj: u64,
    pub passed: bool,
}

impl Step7SumGate {
    pub fn evaluate(phase_ujs: &[u64], window_uj: u64) -> Self {
        let sum_phases_uj = phase_ujs
            .iter()
            .copied()
            .fold(0u64, |acc, v| acc.saturating_add(v));
        let residual_uj = sum_phases_uj.abs_diff(window_uj);
        Self {
            sum_phases_uj,
            window_uj,
            residual_uj,
            passed: residual_uj <= STEP_7_MAX_RESIDUAL_UJ,
        }
    }
}
