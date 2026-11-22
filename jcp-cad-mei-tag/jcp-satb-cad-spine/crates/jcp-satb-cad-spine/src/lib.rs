//! Unified `JCP` (`JCR-1`) <-> `SATB-IO` (`L0..L4` x `A1..N`) <-> `openie-cad`
//! (`cad-joules`) provenance lattice, empirical falsifier gates, and Ed25519
//! `COSE_Sign1` canonical det-CBOR receipt chain spine.

pub mod coldchain;
pub mod falsifiers;
pub mod lattice;
pub mod spine;

pub use coldchain::{
    run_coldchain_10k_simulation, ColdChainCellProfile, ColdChainRunSummary, WakeupKind,
};
pub use falsifiers::{
    Falsifier6Gate, Step7SumGate, FALSIFIER_6_MAX_DRIFT_BPS, STEP_7_MAX_RESIDUAL_UJ,
};
pub use lattice::{
    CadTract, CounterMechanism, EvidenceTier, JcpLatticeRung, SatbAttribution, SatbBoundary,
    SatbProvenance,
};
pub use spine::{
    HoldTicket, ReplayAuditSummary, SealedStageReceipt, SpineError, SpineReceiptChain,
    StageAttemptSpec,
};
