//! Lossless provenance meet-semilattice mapping SATB-IO (`L0..L4` x `A1..N`)
//! <-> JCP (`HwShunt Whole|Partial`, vendor-opaque `HwShunt`, `ModelBased`,
//! `Estimator`, `NotAvailable`) <-> `openie-cad` (`Material`, `SupplyChain`,
//! `Compute` tracts + `measured_j` / `reported_j` / `est_j`).

use jcp_schema::{Coverage, Energy, Provenance};
use serde::{Deserialize, Serialize};

/// Accounting tract within an `openie-cad` session.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CadTract {
    Material,
    SupplyChain,
    Compute,
}

impl CadTract {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Material => "material",
            Self::SupplyChain => "supply_chain",
            Self::Compute => "compute",
        }
    }
}

/// SATB-IO physical / logical measurement boundary (`L0..L4`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
pub enum SatbBoundary {
    /// External inline DC shunt or calibrated wall-plug power analyzer.
    L0,
    /// Board-level sense resistor or SoC register (`INA238`, `IOReport`, `RAPL`).
    L1,
    /// Host OS process or subtree (`ri_energy_nj`, cgroup counter).
    L2,
    /// Container, VM, or multi-tenant slice.
    L3,
    /// Remote uninstrumented API endpoint.
    L4,
}

impl SatbBoundary {
    pub const ALL: [Self; 5] = [Self::L0, Self::L1, Self::L2, Self::L3, Self::L4];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::L0 => "L0",
            Self::L1 => "L1",
            Self::L2 => "L2",
            Self::L3 => "L3",
            Self::L4 => "L4",
        }
    }

    /// Coarser boundary wins under meet (`L0 ^ L2 = L2`, `L1 ^ L4 = L4`).
    pub fn meet(self, other: Self) -> Self {
        self.max(other)
    }
}

/// SATB-IO workload attribution discipline (`A1..N`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum SatbAttribution {
    /// Dedicated single-workload physical rail or isolated bench.
    A1,
    /// Single-process run bracketed by pre/post idle baseline checks.
    A2,
    /// Shared-host hardware counter without per-process rail isolation.
    B,
    /// Model-allocated share (for example Kepler CPU-share).
    C,
    /// Deterministic analytical model (`wall_s * W_est` or operation counter).
    D,
    /// Non-energy proxy only (latency, tokens, FLOPs).
    P,
    /// Unattested closed API or unavailable counter.
    N,
}

impl SatbAttribution {
    pub const ALL: [Self; 7] = [
        Self::A1,
        Self::A2,
        Self::B,
        Self::C,
        Self::D,
        Self::P,
        Self::N,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            Self::A1 => "A1",
            Self::A2 => "A2",
            Self::B => "B",
            Self::C => "C",
            Self::D => "D",
            Self::P => "P",
            Self::N => "N",
        }
    }

    pub fn strength_rank(self) -> u8 {
        match self {
            Self::A1 => 6,
            Self::A2 => 5,
            Self::B => 4,
            Self::C => 3,
            Self::D => 2,
            Self::P => 1,
            Self::N => 0,
        }
    }

    /// Weaker attribution wins under meet (`A1 ^ B = B`, `C ^ D = D`).
    pub fn meet(self, other: Self) -> Self {
        if self.strength_rank() <= other.strength_rank() {
            self
        } else {
            other
        }
    }
}

/// Physical or analytical mechanism that produced a reading.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum CounterMechanism {
    /// Physical inline sense resistor across the complete task boundary.
    RailShuntWhole,
    /// Physical inline sense resistor covering a strict subset of rails.
    RailShuntPartial,
    /// Vendor-opaque SoC/GPU counter (`IOReport`, `RAPL`, `NVML`, `ri_energy_nj`).
    VendorOpaqueCounter { whole_board: bool },
    /// Utilization-share model (`Kepler` CPU-share).
    CpuShareModel { whole_scope: bool },
    /// Analytical `wall_s * W_est`, datasheet integral, or operation counter.
    AnalyticalEstimator { whole_scope: bool },
    /// Closed remote API or missing counter.
    UnattestedOrMissing,
}

impl CounterMechanism {
    pub const ALL: [Self; 8] = [
        Self::RailShuntWhole,
        Self::RailShuntPartial,
        Self::VendorOpaqueCounter { whole_board: true },
        Self::VendorOpaqueCounter { whole_board: false },
        Self::CpuShareModel { whole_scope: true },
        Self::CpuShareModel { whole_scope: false },
        Self::AnalyticalEstimator { whole_scope: true },
        Self::UnattestedOrMissing,
    ];

    pub fn rank(self) -> u8 {
        match self {
            Self::RailShuntWhole => 5,
            Self::RailShuntPartial => 4,
            Self::VendorOpaqueCounter { .. } => 3,
            Self::CpuShareModel { .. } => 2,
            Self::AnalyticalEstimator { .. } => 1,
            Self::UnattestedOrMissing => 0,
        }
    }

    pub fn is_whole(self) -> bool {
        match self {
            Self::RailShuntWhole => true,
            Self::RailShuntPartial => false,
            Self::VendorOpaqueCounter { whole_board } => whole_board,
            Self::CpuShareModel { whole_scope } => whole_scope,
            Self::AnalyticalEstimator { whole_scope } => whole_scope,
            Self::UnattestedOrMissing => false,
        }
    }

    pub fn meet(self, other: Self) -> Self {
        let both_whole = self.is_whole() && other.is_whole();
        match self.rank().min(other.rank()) {
            5 => Self::RailShuntWhole,
            4 => Self::RailShuntPartial,
            3 => Self::VendorOpaqueCounter {
                whole_board: both_whole,
            },
            2 => Self::CpuShareModel {
                whole_scope: both_whole,
            },
            1 => Self::AnalyticalEstimator {
                whole_scope: both_whole,
            },
            _ => Self::UnattestedOrMissing,
        }
    }
}

/// Strictly separated three-tier evidence classification (`measured_j`, `reported_j`, `est_j`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum EvidenceTier {
    NotAvailable = 0,
    EstJ = 1,
    ReportedJ = 2,
    MeasuredJ = 3,
}

impl EvidenceTier {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::MeasuredJ => "measured_j",
            Self::ReportedJ => "reported_j",
            Self::EstJ => "est_j",
            Self::NotAvailable => "not_available",
        }
    }

    pub fn meet(self, other: Self) -> Self {
        self.min(other)
    }
}

/// Canonical JCP provenance rung paired with `Coverage` and vendor-opacity bit.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(tag = "rung", rename_all = "snake_case")]
pub enum JcpLatticeRung {
    HwShunt {
        coverage: Coverage,
        vendor_opaque: bool,
    },
    ModelBased {
        coverage: Coverage,
    },
    Estimator {
        coverage: Coverage,
    },
    NotAvailable,
}

impl JcpLatticeRung {
    pub fn rank(self) -> u8 {
        match self {
            Self::NotAvailable => 0,
            Self::Estimator { .. } => 1,
            Self::ModelBased { .. } => 2,
            Self::HwShunt {
                vendor_opaque: true,
                ..
            } => 3,
            Self::HwShunt {
                vendor_opaque: false,
                ..
            } => 4,
        }
    }

    pub fn coverage(self) -> Option<Coverage> {
        match self {
            Self::HwShunt { coverage, .. }
            | Self::ModelBased { coverage }
            | Self::Estimator { coverage } => Some(coverage),
            Self::NotAvailable => None,
        }
    }

    pub fn evidence_tier(self) -> EvidenceTier {
        match self {
            Self::HwShunt {
                vendor_opaque: false,
                ..
            } => EvidenceTier::MeasuredJ,
            Self::HwShunt {
                vendor_opaque: true,
                ..
            }
            | Self::ModelBased { .. } => EvidenceTier::ReportedJ,
            Self::Estimator { .. } => EvidenceTier::EstJ,
            Self::NotAvailable => EvidenceTier::NotAvailable,
        }
    }

    /// Convert into `jcp_schema::Energy` (`None` when `NotAvailable`), satisfying
    /// `Energy::check_provenance()`.
    pub fn to_jcp_energy(self, uj: u64) -> Option<Energy> {
        match self {
            Self::HwShunt {
                coverage: Coverage::Whole,
                ..
            } => Some(Energy::measured(uj)),
            Self::HwShunt {
                coverage: Coverage::Partial,
                ..
            } => Some(Energy::measured_partial(uj)),
            Self::ModelBased { coverage } => {
                let mut e = Energy::modeled(uj);
                e.coverage = coverage;
                Some(e)
            }
            Self::Estimator { coverage } => {
                let mut e = Energy::estimator(uj);
                e.coverage = coverage;
                Some(e)
            }
            Self::NotAvailable => None,
        }
    }

    /// Lift `jcp_schema::Energy` + vendor-opacity flag back into `JcpLatticeRung`.
    pub fn from_jcp_energy(energy: Energy, vendor_opaque: bool) -> Self {
        match energy.provenance {
            Provenance::HwShunt => Self::HwShunt {
                coverage: energy.coverage,
                vendor_opaque,
            },
            Provenance::ModelBased => Self::ModelBased {
                coverage: energy.coverage,
            },
            Provenance::Estimator => Self::Estimator {
                coverage: energy.coverage,
            },
        }
    }

    pub fn meet(self, other: Self) -> Self {
        let cov = match (self.coverage(), other.coverage()) {
            (Some(Coverage::Whole), Some(Coverage::Whole)) => Coverage::Whole,
            (Some(_), Some(_)) => Coverage::Partial,
            _ => return Self::NotAvailable,
        };
        match self.rank().min(other.rank()) {
            4 => Self::HwShunt {
                coverage: cov,
                vendor_opaque: false,
            },
            3 => Self::HwShunt {
                coverage: cov,
                vendor_opaque: true,
            },
            2 => Self::ModelBased { coverage: cov },
            1 => Self::Estimator { coverage: cov },
            _ => Self::NotAvailable,
        }
    }
}

/// Unified SATB-IO provenance coordinate (`boundary x attribution x mechanism`).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub struct SatbProvenance {
    pub boundary: SatbBoundary,
    pub attribution: SatbAttribution,
    pub mechanism: CounterMechanism,
}

impl SatbProvenance {
    pub fn rail_shunt(boundary: SatbBoundary, attribution: SatbAttribution, whole: bool) -> Self {
        Self {
            boundary,
            attribution,
            mechanism: if whole {
                CounterMechanism::RailShuntWhole
            } else {
                CounterMechanism::RailShuntPartial
            },
        }
    }

    pub fn vendor_counter(
        boundary: SatbBoundary,
        attribution: SatbAttribution,
        whole_board: bool,
    ) -> Self {
        Self {
            boundary,
            attribution,
            mechanism: CounterMechanism::VendorOpaqueCounter { whole_board },
        }
    }

    pub fn kepler_cpu_share(boundary: SatbBoundary) -> Self {
        Self {
            boundary,
            attribution: SatbAttribution::C,
            mechanism: CounterMechanism::CpuShareModel { whole_scope: false },
        }
    }

    pub fn estimator(boundary: SatbBoundary) -> Self {
        Self {
            boundary,
            attribution: SatbAttribution::D,
            mechanism: CounterMechanism::AnalyticalEstimator { whole_scope: true },
        }
    }

    pub fn unattested_api() -> Self {
        Self {
            boundary: SatbBoundary::L4,
            attribution: SatbAttribution::N,
            mechanism: CounterMechanism::UnattestedOrMissing,
        }
    }

    /// Project SATB coordinate onto JCP rung + rail coverage + evidence tier.
    pub fn to_jcp_rung(self) -> JcpLatticeRung {
        if self.boundary == SatbBoundary::L4
            || matches!(self.attribution, SatbAttribution::P | SatbAttribution::N)
            || self.mechanism == CounterMechanism::UnattestedOrMissing
        {
            return JcpLatticeRung::NotAvailable;
        }

        let scope_cov = if self.mechanism.is_whole() && self.boundary != SatbBoundary::L3 {
            Coverage::Whole
        } else {
            Coverage::Partial
        };

        match (self.boundary, self.attribution, self.mechanism) {
            (
                SatbBoundary::L0 | SatbBoundary::L1 | SatbBoundary::L2,
                SatbAttribution::A1 | SatbAttribution::A2 | SatbAttribution::B,
                CounterMechanism::RailShuntWhole,
            ) => JcpLatticeRung::HwShunt {
                coverage: Coverage::Whole,
                vendor_opaque: false,
            },
            (
                SatbBoundary::L0 | SatbBoundary::L1 | SatbBoundary::L2,
                SatbAttribution::A1 | SatbAttribution::A2 | SatbAttribution::B,
                CounterMechanism::RailShuntPartial,
            ) => JcpLatticeRung::HwShunt {
                coverage: Coverage::Partial,
                vendor_opaque: false,
            },
            (
                SatbBoundary::L3,
                SatbAttribution::A1 | SatbAttribution::A2 | SatbAttribution::B,
                CounterMechanism::RailShuntWhole | CounterMechanism::RailShuntPartial,
            ) => JcpLatticeRung::HwShunt {
                coverage: Coverage::Partial,
                vendor_opaque: true,
            },
            (
                SatbBoundary::L0 | SatbBoundary::L1 | SatbBoundary::L2 | SatbBoundary::L3,
                SatbAttribution::A1 | SatbAttribution::A2 | SatbAttribution::B,
                CounterMechanism::VendorOpaqueCounter { .. },
            ) => JcpLatticeRung::HwShunt {
                coverage: scope_cov,
                vendor_opaque: true,
            },
            (
                SatbBoundary::L0 | SatbBoundary::L1 | SatbBoundary::L2 | SatbBoundary::L3,
                SatbAttribution::C,
                CounterMechanism::CpuShareModel { .. }
                | CounterMechanism::VendorOpaqueCounter { .. }
                | CounterMechanism::RailShuntWhole
                | CounterMechanism::RailShuntPartial,
            ) => JcpLatticeRung::ModelBased {
                coverage: scope_cov,
            },
            (
                SatbBoundary::L0 | SatbBoundary::L1 | SatbBoundary::L2 | SatbBoundary::L3,
                _,
                CounterMechanism::CpuShareModel { .. },
            ) if self.attribution != SatbAttribution::D => JcpLatticeRung::ModelBased {
                coverage: scope_cov,
            },
            (_, SatbAttribution::D, _) | (_, _, CounterMechanism::AnalyticalEstimator { .. }) => {
                JcpLatticeRung::Estimator {
                    coverage: scope_cov,
                }
            }
            _ => JcpLatticeRung::NotAvailable,
        }
    }

    pub fn evidence_tier(self) -> EvidenceTier {
        self.to_jcp_rung().evidence_tier()
    }

    pub fn to_jcp_energy(self, uj: u64) -> Option<Energy> {
        self.to_jcp_rung().to_jcp_energy(uj)
    }

    /// Canonical representative of a `JcpLatticeRung` in SATB coordinates.
    pub fn from_jcp_rung(rung: JcpLatticeRung) -> Self {
        match rung {
            JcpLatticeRung::HwShunt {
                coverage: Coverage::Whole,
                vendor_opaque: false,
            } => Self::rail_shunt(SatbBoundary::L1, SatbAttribution::A1, true),
            JcpLatticeRung::HwShunt {
                coverage: Coverage::Partial,
                vendor_opaque: false,
            } => Self::rail_shunt(SatbBoundary::L1, SatbAttribution::B, false),
            JcpLatticeRung::HwShunt {
                coverage,
                vendor_opaque: true,
            } => Self::vendor_counter(
                SatbBoundary::L1,
                SatbAttribution::A2,
                coverage == Coverage::Whole,
            ),
            JcpLatticeRung::ModelBased { coverage } => Self {
                boundary: SatbBoundary::L2,
                attribution: SatbAttribution::C,
                mechanism: CounterMechanism::CpuShareModel {
                    whole_scope: coverage == Coverage::Whole,
                },
            },
            JcpLatticeRung::Estimator { coverage } => Self {
                boundary: SatbBoundary::L2,
                attribution: SatbAttribution::D,
                mechanism: CounterMechanism::AnalyticalEstimator {
                    whole_scope: coverage == Coverage::Whole,
                },
            },
            JcpLatticeRung::NotAvailable => Self::unattested_api(),
        }
    }

    pub fn meet(self, other: Self) -> Self {
        Self {
            boundary: self.boundary.meet(other.boundary),
            attribution: self.attribution.meet(other.attribution),
            mechanism: self.mechanism.meet(other.mechanism),
        }
    }
}
