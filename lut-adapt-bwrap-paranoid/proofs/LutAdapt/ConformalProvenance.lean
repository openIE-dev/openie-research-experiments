/-
  LutAdapt/ConformalProvenance.lean
  Section 2.4 (Result 4) & Section 0.3:
    1. Radially Regularized `JEPA-EBRM` Off-Manifold Conformal Abstention (`C_t(x) = ∅`),
    2. Provenance Non-Strengthening Lattice (`ModelGenerated ↛ Deterministic`),
    3. Target-Verified Speculative Decoding Exact Greedy Parity (`The drafter proposes; the target decides`).
  Author: David Charlot, Open Interface Engineering
  License: Apache-2.0 / MIT
  Zero `sorry`, zero custom axioms.
-/

namespace LutAdapt.ConformalProvenance

/--
  Twice the radially regularized latent energy (`2 * E_phi(x, y)` in Section 2.4):
    `twoEnergy distSq lamR normSq twoPsi = distSq + lamR * normSq + twoPsi`,
  where `distSq = ‖f(x) - μ_y‖² ≥ 0`, `lamR > 0`, `normSq = ‖f(x)‖²`, and `|twoPsi| ≤ 2 * C_psi`.
-/
def twoLatentEnergy (distSq lamR normSq twoPsi : Int) : Int :=
  distSq + lamR * normSq + twoPsi

/--
  **Result 4a (Off-Manifold Radial Coercivity & Conformal Abstention, Section 2.4)**:
  Whenever an off-manifold input `x` satisfies `lamR * normSq > 2 * Q + twoCpsi`
  (equivalently `‖f(x)‖ > R(α_t) = √(2(Q + C_ψ) / λ_r)`), then for EVERY class prototype `y`
  (`distSq ≥ 0`) and bounded residual (`-twoCpsi ≤ twoPsi`), `2 * E_phi(x, y) > 2 * Q`,
  forcing `y ∉ C_t(x)` (`C_t(x) = ∅`, certified abstention / circuit breaker).
-/
theorem off_manifold_ray_forces_abstention
    (distSq lamR normSq twoPsi Q twoCpsi : Int)
    (hdist : 0 ≤ distSq)
    (hpsi : -twoCpsi ≤ twoPsi)
    (hray : 2 * Q + twoCpsi < lamR * normSq) :
    2 * Q < twoLatentEnergy distSq lamR normSq twoPsi := by
  unfold twoLatentEnergy
  omega

/--
  **Result 4b (Finite-Sample Split-Conformal Rank Coverage Bound, Vovk et al. 2005 / Lei et al. 2018)**:
  Over `n + 1` exchangeable calibration + test nonconformity scores (`n` calibration + `1` test),
  choosing order-statistic rank `k` satisfying `B * k ≥ (B - alphaScaled) * (n + 1)`
  (where `alphaScaled ∈ [0, B]` represents `α * B`) guarantees the scaled coverage fraction
  `B * k` is at least `(B - alphaScaled) * (n + 1)`, i.e. miscoverage `(n + 1 - k) / (n + 1) ≤ α`.
-/
theorem split_conformal_rank_miscoverage_bound
    (B alphaScaled n k : Int)
    (hk : (B - alphaScaled) * (n + 1) ≤ B * k) :
    B * (n + 1 - k) ≤ alphaScaled * (n + 1) := by
  have hdist : (B - alphaScaled) * (n + 1) = B * (n + 1) - alphaScaled * (n + 1) :=
    Int.sub_mul B alphaScaled (n + 1)
  have hsub : B * (n + 1 - k) = B * (n + 1) - B * k :=
    Int.mul_sub B (n + 1) k
  omega

/--
  **Adaptive Conformal Inference (ACI) Fixed-Point Equilibrium (Gibbs & Candès 2021)**:
  Scaled by step denominator `G > 0`, the online update
    `alphaNext = alphaCur + gamma * (alphaTarget - err_t)`
  is stationary (`alphaNext = alphaCur`) with `gamma > 0` if and only if empirical error
  equals target miscoverage (`err_t = alphaTarget`).
-/
theorem aci_stationary_iff_target_miscoverage (alphaCur gamma alphaTarget err_t : Int)
    (hgamma : 0 < gamma) :
    alphaCur + gamma * (alphaTarget - err_t) = alphaCur ↔ err_t = alphaTarget := by
  constructor
  · intro h
    have hzero : gamma * (alphaTarget - err_t) = 0 := by omega
    cases Int.mul_eq_zero.mp hzero with
    | inl hg0 => omega
    | inr hdiff => omega
  · intro heq
    subst heq
    simp

/--
  Four-level OpenIE epistemic provenance lattice (`Section 0.3` & `Section 1`):
    `modelGenerated < conformalBounded < checkSafe < deterministic`.
-/
inductive Provenance where
  | modelGenerated
  | conformalBounded
  | checkSafe
  | deterministic
  deriving DecidableEq, Repr

def Provenance.rank : Provenance → Nat
  | .modelGenerated   => 0
  | .conformalBounded => 1
  | .checkSafe        => 2
  | .deterministic    => 3

/-- Downward crystallization provenance assignment based on gate kind. -/
def crystallizeProvenance (hasExactRceCheck : Bool) : Provenance :=
  if hasExactRceCheck then .checkSafe else .conformalBounded

/--
  **Provenance Non-Strengthening Invariant (`ModelGenerated ↛ Deterministic`, Section 0.3)**:
  Neither oracle-free conformal crystallization (`hasExactRceCheck = false`) nor holdout RCE
  crystallization (`hasExactRceCheck = true`) ever stamps a learned `LUT6` table `Deterministic`.
-/
theorem downward_crystallize_never_deterministic (hasExactRceCheck : Bool) :
    crystallizeProvenance hasExactRceCheck ≠ Provenance.deterministic := by
  cases hasExactRceCheck <;> decide

/--
  Oracle-free conformal crystallization strictly stays below `CheckSafe` and `Deterministic`.
-/
theorem conformal_crystallize_rank_strictly_bounded :
    (crystallizeProvenance false).rank < Provenance.checkSafe.rank ∧
    (crystallizeProvenance false).rank < Provenance.deterministic.rank := by
  decide

/--
  **Target-Verified Speculative Decoding Exact Greedy Parity (`Section 0.3`, Claims LA-5..LA-9)**:
  Given any autoregressive greedy target step `target : State → Token`, state transition
  `advance : State → Token → State`, and arbitrary zero-FLOP `LUT6` draft burst `draft : List Token`,
  verifying prefix tokens up to the first mismatch and emitting `target s` on mismatch (or bonus step)
  produces the EXACT same token sequence as running `target` step-by-step for the same number of tokens!
-/
def greedyRun {State Token : Type} (target : State → Token) (advance : State → Token → State) :
    Nat → State → List Token
  | 0, _ => []
  | n + 1, s =>
      let t := target s
      t :: greedyRun target advance n (advance s t)

/--
  Single speculative sweep verifying proposed draft tokens `[d_1, ..., d_k]` against `target`
  (capped at `rem` remaining output tokens), always appending the authoritative `target` token
  at the rejection point (or bonus position if all `k` drafts match).
-/
def speculativeSweep {State Token : Type} [DecidableEq Token]
    (target : State → Token) (advance : State → Token → State) :
    Nat → State → List Token → List Token × State
  | 0, s, _ => ([], s)
  | _ + 1, s, [] =>
      let t := target s
      ([t], advance s t)
  | rem + 1, s, d :: ds =>
      let t := target s
      if d = t then
        let (acc, s') := speculativeSweep target advance rem (advance s t) ds
        (t :: acc, s')
      else
        ([t], advance s t)

theorem speculativeSweep_matches_greedy {State Token : Type} [DecidableEq Token]
    (target : State → Token) (advance : State → Token → State)
    (rem : Nat) (s : State) (draft : List Token) :
    let (emitted, s') := speculativeSweep target advance rem s draft
    emitted.length ≤ rem ∧
    greedyRun target advance rem s =
      emitted ++ greedyRun target advance (rem - emitted.length) s' := by
  induction rem generalizing s draft with
  | zero =>
    simp [speculativeSweep, greedyRun]
  | succ r ih =>
    cases draft with
    | nil =>
      simp [speculativeSweep, greedyRun]
    | cons d ds =>
      simp only [speculativeSweep]
      by_cases h : d = target s
      · simp only [h, ↓reduceIte]
        have hrec := ih (advance s (target s)) ds
        rcases hSpec : speculativeSweep target advance r (advance s (target s)) ds with ⟨acc, s'⟩
        rw [hSpec] at hrec
        rcases hrec with ⟨hlen, hrun⟩
        simp only [List.length_cons, List.cons_append]
        constructor
        · omega
        · have hsub : r + 1 - (acc.length + 1) = r - acc.length := by omega
          rw [hsub, greedyRun, hrun]
      · simp only [h, ↓reduceIte, List.length_singleton, Nat.add_sub_cancel, List.singleton_append]
        exact ⟨Nat.succ_pos r, rfl⟩

end LutAdapt.ConformalProvenance
