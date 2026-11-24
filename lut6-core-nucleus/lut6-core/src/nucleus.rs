//! 16 KB 3-Part Self-Hosting Bootstrap `Nucleus`:
//! - Part 1: Immutable `knowledge_root` (`4,096` bytes)
//! - Part 2: Immutable `agency_root` (`4,096` bytes, initialized from `SEED_AGENCY`)
//! - Part 3: Endogenous Self-Refining Overlays (`knowledge_overlay` `4,096` B + `agency_overlay` `4,096` B)
//!
//! Enforces Dual Walsh-Harmonic + Zero-Regression Anchor Retention gates on both `refine_knowledge`
//! and `refine_agency`, plus deterministic `APOPTOSIS_ROLLBACK` whenever `verifier_rejects >= kill_max_rejects`
//! or `OperonFrame` emits `APOPTOSIS_ROLLBACK (0x3C)`.

use core::mem::size_of;

use crate::bootstrap::{APOPTOSIS_ROLLBACK, AgencyStateWord, OperonFrame, build_seed_agency};
use crate::{CompactLut6Page, EvalOutcome, high_harmonic_energy};

/// Exact 16,384-byte (`4 x 4,096` B) contiguous `#![no_std]` 3-Part Crystal Arena,
/// suitable for direct placement in Cortex-M55 Zero-Wait DTCM (`0x2000_0000`) or RP2040 Striped SRAM.
#[repr(C, align(8))]
#[derive(Clone, Copy)]
pub struct CrystalArena16K {
    pub knowledge_root: CompactLut6Page,
    pub agency_root: CompactLut6Page,
    pub knowledge_overlay: CompactLut6Page,
    pub agency_overlay: CompactLut6Page,
}

const _: () = assert!(size_of::<CrystalArena16K>() == 16_384);

/// Admission failure reason returned by `Nucleus::refine_knowledge` and `Nucleus::refine_agency`.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum RefineError {
    /// Candidate failed header, magic, schema, or 4,096-byte IEEE CRC-32 integrity check.
    InvalidIntegrity,
    /// Candidate `domain_hash` does not match the protected `root.domain_hash`.
    DomainHashMismatch { expected: u64, got: u64 },
    /// Candidate gate exceeded maximum allowed degree `>= 5` Walsh-Hadamard parity noise.
    HighHarmonicNoise {
        gate_idx: usize,
        energy: u32,
        max_allowed: u32,
    },
    /// Candidate regressed or abstained on a protected `(input, expected)` anchor vector.
    AnchorRegression {
        anchor_idx: usize,
        expected: u64,
        actual_raw: u64,
    },
}

/// Receipt emitted on successful endogenous crystal splice (`SPLICE_PAGE 0x10`).
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct SpliceReceipt {
    pub generation: u32,
    pub active_gates_audited: usize,
    pub max_gate_harmonic_energy: u32,
    pub anchors_verified: usize,
    pub crc32: u32,
}

/// Self-hosting 3-Part Bootstrap `Nucleus` (`16 KB` `CrystalArena16K` + bounded reject counter).
#[repr(C, align(8))]
#[derive(Clone, Copy)]
pub struct Nucleus {
    pub arena: CrystalArena16K,
    pub verifier_rejects: u16,
    pub apoptosis_latched: bool,
    pub max_allowed_harmonic_energy: u32,
    pub knowledge_generation: u32,
    pub agency_generation: u32,
}

impl Nucleus {
    /// Boot a `Nucleus` from an immutable `knowledge_root` and the canonical `SEED_AGENCY` crystal.
    pub const fn new_bootstrap(knowledge_root: CompactLut6Page) -> Self {
        Self {
            arena: CrystalArena16K {
                knowledge_root,
                agency_root: build_seed_agency(),
                knowledge_overlay: CompactLut6Page::empty_invalid(),
                agency_overlay: CompactLut6Page::empty_invalid(),
            },
            verifier_rejects: 0,
            apoptosis_latched: false,
            max_allowed_harmonic_energy: 0,
            knowledge_generation: 0,
            agency_generation: 0,
        }
    }

    #[inline]
    pub const fn has_knowledge_overlay(&self) -> bool {
        !self.apoptosis_latched && self.arena.knowledge_overlay.is_valid()
    }

    #[inline]
    pub const fn has_agency_overlay(&self) -> bool {
        !self.apoptosis_latched && self.arena.agency_overlay.is_valid()
    }

    /// Purge all mutable overlays in `O(1)` while preserving `knowledge_root` and `agency_root` untouched.
    #[inline]
    pub const fn trigger_apoptosis(&mut self) {
        self.arena.knowledge_overlay.magic = [0; 4];
        self.arena.knowledge_overlay.flags = 0;
        self.arena.knowledge_overlay.crc32 = 0;
        self.arena.agency_overlay.magic = [0; 4];
        self.arena.agency_overlay.flags = 0;
        self.arena.agency_overlay.crc32 = 0;
        self.apoptosis_latched = true;
    }

    #[inline]
    const fn record_reject(&mut self, kill_limit: u8) {
        self.verifier_rejects = self.verifier_rejects.saturating_add(1);
        if kill_limit > 0 && self.verifier_rejects >= (kill_limit as u16) {
            self.trigger_apoptosis();
        }
    }

    /// Evaluate domain knowledge (`knowledge_root` + optional `knowledge_overlay`).
    #[inline]
    pub const fn query_knowledge(&self, state: u64) -> Result<EvalOutcome, !> {
        let effective_rejects = if self.apoptosis_latched {
            u16::MAX
        } else {
            self.verifier_rejects
        };
        let ov = if self.has_knowledge_overlay() {
            Some(&self.arena.knowledge_overlay)
        } else {
            None
        };
        self.arena
            .knowledge_root
            .evaluate(state, ov, effective_rejects)
    }

    /// Dispatch `AgencyStateWord -> OperonFrame` (`agency_root` + optional `agency_overlay`).
    /// Automatically triggers `APOPTOSIS_ROLLBACK` if the emitted opcode is `0x3C`.
    #[inline]
    pub const fn step_agency(&mut self, word: AgencyStateWord) -> OperonFrame {
        let effective_rejects = if self.apoptosis_latched {
            u16::MAX
        } else {
            self.verifier_rejects
        };
        let ov = if self.has_agency_overlay() {
            Some(&self.arena.agency_overlay)
        } else {
            None
        };
        let Ok(outcome) = self
            .arena
            .agency_root
            .evaluate(word.0, ov, effective_rejects);
        let raw = match outcome {
            EvalOutcome::Act { output, .. } => output,
            EvalOutcome::Escalate { raw_output, .. } => raw_output,
            EvalOutcome::Killed { fallback_output } => fallback_output,
        };
        let frame = OperonFrame(raw);
        if frame.opcode() == APOPTOSIS_ROLLBACK || frame.is_apoptosis() {
            self.trigger_apoptosis();
        }
        frame
    }

    fn verify_candidate_against_root(
        root: &CompactLut6Page,
        candidate: &CompactLut6Page,
        external_anchors: &[(u64, u64)],
        max_harmonic: u32,
    ) -> Result<(usize, u32, usize), RefineError> {
        // 1. Full 4 KB IEEE CRC-32 + header integrity
        if !candidate.verify_integrity() {
            return Err(RefineError::InvalidIntegrity);
        }
        if candidate.domain_hash != root.domain_hash {
            return Err(RefineError::DomainHashMismatch {
                expected: root.domain_hash,
                got: candidate.domain_hash,
            });
        }

        // 2. Gate 1: 64-Point Integer Walsh-Hadamard High-Harmonic Filter
        let active_gates = (candidate.num_layers as usize) * (candidate.gates_per_layer as usize);
        let mut worst_energy: u32 = 0;
        for g in 0..active_gates {
            let e = high_harmonic_energy(candidate.init_masks[g]);
            if e > worst_energy {
                worst_energy = e;
            }
            if e > max_harmonic {
                return Err(RefineError::HighHarmonicNoise {
                    gate_idx: g,
                    energy: e,
                    max_allowed: max_harmonic,
                });
            }
        }

        // 3. Gate 2: Zero-Regression Anchor Retention (embedded root anchors + external anchors)
        let embedded_n = root.anchor_count as usize;
        for i in 0..embedded_n {
            let inp = root.anchor_inputs[i];
            let exp = root.anchor_expected[i];
            let Ok(out) = candidate.evaluate(inp, None, 0);
            match out {
                EvalOutcome::Act { output, .. } if output == exp => {}
                EvalOutcome::Act { output, .. } => {
                    return Err(RefineError::AnchorRegression {
                        anchor_idx: i,
                        expected: exp,
                        actual_raw: output,
                    });
                }
                EvalOutcome::Escalate { raw_output, .. } => {
                    return Err(RefineError::AnchorRegression {
                        anchor_idx: i,
                        expected: exp,
                        actual_raw: raw_output,
                    });
                }
                EvalOutcome::Killed { fallback_output } => {
                    return Err(RefineError::AnchorRegression {
                        anchor_idx: i,
                        expected: exp,
                        actual_raw: fallback_output,
                    });
                }
            }
        }

        for (j, &(inp, exp)) in external_anchors.iter().enumerate() {
            let Ok(out) = candidate.evaluate(inp, None, 0);
            match out {
                EvalOutcome::Act { output, .. } if output == exp => {}
                EvalOutcome::Act { output, .. } => {
                    return Err(RefineError::AnchorRegression {
                        anchor_idx: embedded_n + j,
                        expected: exp,
                        actual_raw: output,
                    });
                }
                EvalOutcome::Escalate { raw_output, .. } => {
                    return Err(RefineError::AnchorRegression {
                        anchor_idx: embedded_n + j,
                        expected: exp,
                        actual_raw: raw_output,
                    });
                }
                EvalOutcome::Killed { fallback_output } => {
                    return Err(RefineError::AnchorRegression {
                        anchor_idx: embedded_n + j,
                        expected: exp,
                        actual_raw: fallback_output,
                    });
                }
            }
        }

        Ok((active_gates, worst_energy, embedded_n + external_anchors.len()))
    }

    /// Endogenous Knowledge Crystal Splicing (`SPLICE_PAGE 0x10` on `knowledge_overlay`).
    pub fn refine_knowledge(
        &mut self,
        candidate: &CompactLut6Page,
        anchors: &[(u64, u64)],
    ) -> Result<SpliceReceipt, RefineError> {
        let kill_limit = self.arena.knowledge_root.kill_max_rejects;
        match Self::verify_candidate_against_root(
            &self.arena.knowledge_root,
            candidate,
            anchors,
            self.max_allowed_harmonic_energy,
        ) {
            Ok((gates, max_e, total_anchors)) => {
                self.arena.knowledge_overlay = *candidate;
                self.apoptosis_latched = false;
                self.knowledge_generation = self.knowledge_generation.wrapping_add(1);
                Ok(SpliceReceipt {
                    generation: self.knowledge_generation,
                    active_gates_audited: gates,
                    max_gate_harmonic_energy: max_e,
                    anchors_verified: total_anchors,
                    crc32: candidate.crc32,
                })
            }
            Err(err) => {
                self.record_reject(kill_limit);
                Err(err)
            }
        }
    }

    /// Endogenous Agency Operon Splicing (`SPLICE_PAGE 0x10` on `agency_overlay`).
    pub fn refine_agency(
        &mut self,
        candidate: &CompactLut6Page,
        anchors: &[(u64, u64)],
    ) -> Result<SpliceReceipt, RefineError> {
        let kill_limit = self.arena.agency_root.kill_max_rejects;
        match Self::verify_candidate_against_root(
            &self.arena.agency_root,
            candidate,
            anchors,
            self.max_allowed_harmonic_energy,
        ) {
            Ok((gates, max_e, total_anchors)) => {
                self.arena.agency_overlay = *candidate;
                self.apoptosis_latched = false;
                self.agency_generation = self.agency_generation.wrapping_add(1);
                Ok(SpliceReceipt {
                    generation: self.agency_generation,
                    active_gates_audited: gates,
                    max_gate_harmonic_energy: max_e,
                    anchors_verified: total_anchors,
                    crc32: candidate.crc32,
                })
            }
            Err(err) => {
                self.record_reject(kill_limit);
                Err(err)
            }
        }
    }
}
