//! The `training/1` receipt — measured energy for a **training** run, the
//! inference-side `efficiency/1` turned around to face the other direction.
//!
//! Every lab racing to ship models publishes efficiency in some unit that is not
//! energy: parameters, throughput, tokens, or a flat "runs on your hardware" that
//! quietly moves the electricity bill onto the buyer with no meter attached. The
//! one number nobody publishes is **joules per token trained**. This receipt seals
//! it, bound to the exact base weights, the exact dataset, and the exact resulting
//! weights, so a set of trained weights carries verifiable evidence of what it
//! cost to produce and what verified work produced it.
//!
//! It is the training-side twin of [`crate::Efficiency`]: same honest-provenance
//! energy (`measured` / `modeled` / `est.`, never overclaimed), same JCR-1 sealing
//! (COSE_Sign1 / EdDSA, integers and strings only), same hash-chaining, and the
//! same optional binding to an external energy attestation.

use ed25519_dalek::SigningKey;
use jcp_receipt::jcr1;
use jcp_schema::{ContentId, Energy};
use serde_json::{json, Value};

/// How a run produced its weights — sealed, so a receipt states whether the
/// energy bought a supervised imitation pass, a reinforcement pass over a
/// verifiable reward, a low-rank adapter, or a distillation from a teacher.
/// Serialized through [`TrainingMethod::tag`] rather than serde, matching the
/// crate's flat-wire convention (no `serde` dependency here).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TrainingMethod {
    /// Supervised fine-tuning — imitate verified completions.
    Sft,
    /// Reinforcement learning from a verifiable reward (a real build/test).
    Rl,
    /// Low-rank adaptation (LoRA/QLoRA) — the cheap, local-feasible path.
    Lora,
    /// Distillation from a teacher model.
    Distill,
}

impl TrainingMethod {
    /// The wire tag sealed into the receipt.
    pub fn tag(self) -> &'static str {
        match self {
            TrainingMethod::Sft => "sft",
            TrainingMethod::Rl => "rl",
            TrainingMethod::Lora => "lora",
            TrainingMethod::Distill => "distill",
        }
    }

    fn from_tag(tag: &str) -> Option<Self> {
        match tag {
            "sft" => Some(TrainingMethod::Sft),
            "rl" => Some(TrainingMethod::Rl),
            "lora" => Some(TrainingMethod::Lora),
            "distill" => Some(TrainingMethod::Distill),
            _ => None,
        }
    }
}

/// One training run, ready to seal as a `training/1` receipt. Every content id is
/// a commitment: swap the base weights, the dataset, or the output and the sealed
/// hash no longer matches, so the receipt cannot be moved onto different weights.
#[derive(Clone, Debug)]
pub struct TrainingRun {
    /// The run / job id.
    pub run: String,
    pub method: TrainingMethod,
    /// Content id of the **base** weights the run started from (a from-scratch run
    /// commits the all-zero id).
    pub base_model: ContentId,
    /// Content id of the training corpus — [`joule_core::training::digest`], so the
    /// receipt binds the weights to the verified work that produced them.
    pub dataset: ContentId,
    /// Content id of the **resulting** weights.
    pub new_weights: ContentId,
    /// Tokens the run trained over — the denominator for the headline figure.
    pub tokens_trained: u64,
    /// Examples in the corpus.
    pub examples: u64,
    /// Examples from verified runs (the positive / imitation subset). `<= examples`.
    pub verified_examples: u64,
    /// Energy over the whole run, at honest provenance. **The measured joules, not
    /// a FLOP estimate** — the point of the receipt.
    pub energy: Energy,
    /// Wall-clock nanoseconds — the denominator for tokens/second.
    pub wall_ns: u64,
    /// Hex content-id commitment to an external energy attestation (raw
    /// attestation-report bytes from `sandbox-tee::energy`). `None` = the counter
    /// is signed but unattested (today's default). The trust level is derived by
    /// verifying the referenced attestation, never asserted here.
    pub energy_attestation: Option<String>,
}

/// The `training/1` schema tag.
pub const TRAINING_SCHEMA: &str = "training/1";

impl TrainingRun {
    /// **Microjoules per token trained** — the figure no competitor publishes.
    /// `0` when the run trained no tokens (division by zero is meaningless).
    pub fn uj_per_token_trained(&self) -> u64 {
        self.energy.uj().checked_div(self.tokens_trained).unwrap_or(0)
    }

    /// Tokens trained per second — training throughput, recomputed from integers,
    /// never sealed as a float.
    pub fn tokens_per_sec(&self) -> f64 {
        if self.wall_ns == 0 {
            0.0
        } else {
            self.tokens_trained as f64 / (self.wall_ns as f64 / 1e9)
        }
    }

    /// Bind this run to a raw energy attestation report by committing its content
    /// id. Verifying that report via the attestation layer is what upgrades the
    /// energy from signed to physically-rooted.
    pub fn with_energy_attestation(mut self, attestation_report: &[u8]) -> Self {
        self.energy_attestation = Some(ContentId::of_bytes(attestation_report).to_hex());
        self
    }

    /// Seal this run as a `training/1` JCR-1 receipt, chained after `prev`
    /// (`ContentId([0;32])` for the genesis). Returns the sealed envelope; its
    /// content id is the next entry's `prev`.
    pub fn seal(&self, seq: u64, prev: &ContentId, steward_sk: &SigningKey, steward: &str) -> Vec<u8> {
        let wire = self.wire(seq, prev, steward);
        let core = jcr1::signed_core_bytes(&wire).expect("training wire is a JCR-1 object");
        jcr1::cose_sign1_envelope(&core, steward_sk, steward)
    }

    fn wire(&self, seq: u64, prev: &ContentId, steward: &str) -> Value {
        // JCR-1: integers + strings only. Rates (uj/token, tokens/sec) are the
        // headline figures and are recomputed on read from the sealed integers.
        let mut o = json!({
            "training_receipt": TRAINING_SCHEMA,
            "run": self.run,
            "method": self.method.tag(),
            "base_model": self.base_model.to_hex(),
            "dataset": self.dataset.to_hex(),
            "new_weights": self.new_weights.to_hex(),
            "tokens_trained": self.tokens_trained,
            "examples": self.examples,
            "verified_examples": self.verified_examples,
            "energy_uj": self.energy.uj(),
            "provenance": self.energy.provenance.jcr1_label(),
            "wall_ns": self.wall_ns,
            "uj_per_token_trained": self.uj_per_token_trained(),
            "seq": seq,
            "prev": prev.to_hex(),
            "steward": steward,
        });
        if let Some(a) = &self.energy_attestation {
            o["energy_attestation"] = json!(a);
        }
        o
    }
}

/// Errors verifying a `training/1` receipt.
#[derive(Debug, thiserror::Error)]
pub enum TrainingError {
    #[error("jcr1: {0}")]
    Jcr1(#[from] jcr1::Jcr1Error),
    #[error("schema: {0}")]
    Schema(String),
    #[error("malformed training receipt: {0}")]
    Malformed(String),
}

/// The fields recovered from a verified `training/1` receipt.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct TrainingReceipt {
    pub run: String,
    pub method: TrainingMethod,
    pub base_model: String,
    pub dataset: String,
    pub new_weights: String,
    pub tokens_trained: u64,
    pub examples: u64,
    pub verified_examples: u64,
    pub energy_uj: u64,
    pub provenance: String,
    pub wall_ns: u64,
    /// Microjoules per token trained (headline).
    pub uj_per_token_trained: u64,
    pub energy_attestation: Option<String>,
    pub seq: u64,
    pub prev: String,
    pub steward: String,
}

/// Verify a sealed `training/1` receipt against the steward key and recover its
/// fields. A flipped byte anywhere fails the signature.
pub fn verify(envelope: &[u8], steward: &str, pubkey: &[u8; 32]) -> Result<TrainingReceipt, TrainingError> {
    let payload = jcr1::verify_cose_sign1(envelope, steward, pubkey)?;
    let v: Value =
        jcp_schema::from_canonical_cbor(&payload).map_err(|e| TrainingError::Schema(e.to_string()))?;
    if v.get("training_receipt").and_then(Value::as_str) != Some(TRAINING_SCHEMA) {
        return Err(TrainingError::Malformed("not a training/1 receipt".into()));
    }
    let s = |k: &str| {
        v.get(k)
            .and_then(Value::as_str)
            .map(str::to_string)
            .ok_or_else(|| TrainingError::Malformed(format!("missing string '{k}'")))
    };
    let u = |k: &str| {
        v.get(k)
            .and_then(Value::as_u64)
            .ok_or_else(|| TrainingError::Malformed(format!("missing uint '{k}'")))
    };
    let method = TrainingMethod::from_tag(&s("method")?)
        .ok_or_else(|| TrainingError::Malformed("unknown training method".into()))?;
    Ok(TrainingReceipt {
        run: s("run")?,
        method,
        base_model: s("base_model")?,
        dataset: s("dataset")?,
        new_weights: s("new_weights")?,
        tokens_trained: u("tokens_trained")?,
        examples: u("examples")?,
        verified_examples: u("verified_examples")?,
        energy_uj: u("energy_uj")?,
        provenance: s("provenance")?,
        wall_ns: u("wall_ns")?,
        uj_per_token_trained: u("uj_per_token_trained")?,
        energy_attestation: v.get("energy_attestation").and_then(Value::as_str).map(str::to_string),
        seq: u("seq")?,
        prev: s("prev")?,
        steward: s("steward")?,
    })
}

/// Verify a whole chain of `training/1` receipts: each seal valid under the
/// steward key, and each `prev` linking to the prior envelope's content id.
/// Returns the verified receipts, or the index of the first break.
pub fn verify_chain(
    receipts: &[Vec<u8>],
    steward: &str,
    pubkey: &[u8; 32],
) -> Result<Vec<TrainingReceipt>, usize> {
    let mut prev = ContentId([0u8; 32]).to_hex();
    let mut out = Vec::with_capacity(receipts.len());
    for (i, env) in receipts.iter().enumerate() {
        let Ok(receipt) = verify(env, steward, pubkey) else {
            return Err(i);
        };
        if receipt.prev != prev {
            return Err(i);
        }
        prev = ContentId::of_bytes(env).to_hex();
        out.push(receipt);
    }
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn steward_key() -> SigningKey {
        SigningKey::from_bytes(&[5u8; 32])
    }

    fn a_run() -> TrainingRun {
        TrainingRun {
            run: "post-train-lfm2-on-verified-exhaust".into(),
            method: TrainingMethod::Lora,
            base_model: ContentId::of_bytes(b"lfm2-base-weights"),
            dataset: ContentId::of_bytes(b"the verified corpus"),
            new_weights: ContentId::of_bytes(b"the adapted weights"),
            tokens_trained: 2_000_000,
            examples: 512,
            verified_examples: 480,
            // 60 J measured over the run: 60_000_000 µJ.
            energy: Energy::measured(60_000_000),
            wall_ns: 30_000_000_000, // 30 s
            energy_attestation: None,
        }
    }

    #[test]
    fn the_headline_is_joules_per_token_trained() {
        let run = a_run();
        // 60_000_000 µJ / 2_000_000 tokens = 30 µJ/token trained.
        assert_eq!(run.uj_per_token_trained(), 30);
        // And it is recomputed identically on the verified receipt.
        let env = run.seal(0, &ContentId([0u8; 32]), &steward_key(), "did:jcp:trainer");
        let receipt = verify(&env, "did:jcp:trainer", &steward_key().verifying_key().to_bytes()).unwrap();
        assert_eq!(receipt.uj_per_token_trained, 30);
    }

    #[test]
    fn a_receipt_round_trips_and_binds_its_artifacts() {
        let run = a_run();
        let env = run.seal(0, &ContentId([0u8; 32]), &steward_key(), "did:jcp:trainer");
        let pk = steward_key().verifying_key().to_bytes();
        let receipt = verify(&env, "did:jcp:trainer", &pk).unwrap();
        assert_eq!(receipt.method, TrainingMethod::Lora);
        assert_eq!(receipt.base_model, ContentId::of_bytes(b"lfm2-base-weights").to_hex());
        assert_eq!(receipt.dataset, ContentId::of_bytes(b"the verified corpus").to_hex());
        assert_eq!(receipt.new_weights, ContentId::of_bytes(b"the adapted weights").to_hex());
        assert_eq!(receipt.verified_examples, 480);
        assert_eq!(receipt.provenance, "HwShunt");
    }

    #[test]
    fn tampering_with_any_bound_artifact_fails_verification() {
        let run = a_run();
        let env = run.seal(0, &ContentId([0u8; 32]), &steward_key(), "did:jcp:trainer");
        let pk = steward_key().verifying_key().to_bytes();
        // Flip one byte of the sealed envelope — the signature no longer holds.
        let mut tampered = env.clone();
        let last = tampered.len() - 1;
        tampered[last] ^= 0x01;
        assert!(verify(&tampered, "did:jcp:trainer", &pk).is_err());
    }

    #[test]
    fn a_from_scratch_run_commits_the_zero_base() {
        let mut run = a_run();
        run.method = TrainingMethod::Rl;
        run.base_model = ContentId([0u8; 32]);
        let env = run.seal(0, &ContentId([0u8; 32]), &steward_key(), "did:jcp:trainer");
        let receipt = verify(&env, "did:jcp:trainer", &steward_key().verifying_key().to_bytes()).unwrap();
        assert_eq!(receipt.method, TrainingMethod::Rl);
        assert_eq!(receipt.base_model, ContentId([0u8; 32]).to_hex());
    }

    #[test]
    fn the_energy_provenance_is_never_overclaimed() {
        // A modeled (FLOP-estimated) run seals as modeled, not measured.
        let mut run = a_run();
        run.energy = Energy::modeled(60_000_000);
        let env = run.seal(0, &ContentId([0u8; 32]), &steward_key(), "did:jcp:trainer");
        let receipt = verify(&env, "did:jcp:trainer", &steward_key().verifying_key().to_bytes()).unwrap();
        assert_eq!(receipt.provenance, "ModelBased");
    }

    #[test]
    fn a_chain_of_runs_verifies_end_to_end() {
        let key = steward_key();
        let steward = "did:jcp:trainer";
        let mut prev = ContentId([0u8; 32]);
        let mut receipts = Vec::new();
        for seq in 0..3 {
            let env = a_run().seal(seq, &prev, &key, steward);
            prev = ContentId::of_bytes(&env);
            receipts.push(env);
        }
        let verified = verify_chain(&receipts, steward, &key.verifying_key().to_bytes()).unwrap();
        assert_eq!(verified.len(), 3);
        // Excising the middle receipt breaks the chain at that index.
        let broken = vec![receipts[0].clone(), receipts[2].clone()];
        assert_eq!(verify_chain(&broken, steward, &key.verifying_key().to_bytes()), Err(1));
    }

    #[test]
    fn an_attestation_commitment_is_sealed_when_present() {
        let run = a_run().with_energy_attestation(b"a TEE energy report");
        let env = run.seal(0, &ContentId([0u8; 32]), &steward_key(), "did:jcp:trainer");
        let receipt = verify(&env, "did:jcp:trainer", &steward_key().verifying_key().to_bytes()).unwrap();
        assert_eq!(
            receipt.energy_attestation,
            Some(ContentId::of_bytes(b"a TEE energy report").to_hex())
        );
    }

    #[test]
    fn no_tokens_trained_yields_no_headline_rather_than_a_panic() {
        let mut run = a_run();
        run.tokens_trained = 0;
        assert_eq!(run.uj_per_token_trained(), 0);
    }
}
