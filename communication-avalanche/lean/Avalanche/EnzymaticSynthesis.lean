/-
  The Communication Tool Avalanche — Part III: Digital Enzymatic Synthesis,
  10-Camp Niche Specialization, and the 4-Tier Downward Crystallization Forcing Function
  Module: Avalanche.EnzymaticSynthesis
  Self-contained Lean 4.36.0 formalization (zero external dependencies, zero sorry, zero custom axioms).

  Covers:
    1. Digital Enzyme Catalysis, State Invariance, Zero Drift & Sequential Composition (CTA-T32..CTA-T35)
    2. K-Camp (K = 10) Niche Specialization & Enzymatic Pareto / CpJ Dominance (CTA-T36..CTA-T40)
    3. 4-Tier Downward Crystallization Forcing Function, Horizon Monotonicity & Kill Bound (CTA-T41..CTA-T45)
-/

namespace Avalanche.EnzymaticSynthesis

/-! ## 1. Digital Enzyme Catalysis & Activation-Barrier Lowering (`CTA-T32` to `CTA-T35`) -/

/-- A `DigitalEnzyme` bridges a source camp state `Src` to a destination camp state `Dst` via a
    canonical typed intermediate representation `IR`, a constant-time attestation check `attestOk`,
    and a deterministic semantic admission gate `vDet`, at per-handoff cost `cEnz`.
    `catalystId` tracks structural identity to certify that the enzyme is unconsumed across reactions. -/
structure DigitalEnzyme (Src IR Dst : Type) where
  catalystId  : Nat
  encodePhi   : Src → IR
  attestOk    : IR → Bool
  vDet        : IR → Bool
  decodeApply : Dst → IR → Dst
  cEnz        : Nat

/-- Combined constant-time cryptographic + deterministic semantic admission check. -/
def enzymeAdmit {Src IR Dst : Type} (E : DigitalEnzyme Src IR Dst) (ir : IR) : Bool :=
  E.attestOk ir && E.vDet ir

/-- Single catalyzed reaction step: returns the (unconsumed) enzyme, updated destination state, and fire bit. -/
def enzymaticStep {Src IR Dst : Type} (E : DigitalEnzyme Src IR Dst) (src : Src) (dst : Dst) :
    DigitalEnzyme Src IR Dst × Dst × Bool :=
  if enzymeAdmit E (E.encodePhi src) then (E, E.decodeApply dst (E.encodePhi src), true) else (E, dst, false)

/-- Run a sequence of `M` catalyzed handoffs using the same digital enzyme instance `E`. -/
def runEnzymaticChain {Src IR Dst : Type} (E : DigitalEnzyme Src IR Dst) (dst : Dst) :
    List Src → DigitalEnzyme Src IR Dst × Dst
  | []        => (E, dst)
  | s :: rest =>
    let (E', dst', _) := enzymaticStep E s dst
    runEnzymaticChain E' dst' rest

/-- Uncatalyzed natural-language multi-agent handoff cost (`kRetry * cNl`) and per-handoff
    activation-barrier reduction `DeltaE_ddagger = kRetry * cNl - cEnz`. -/
def uncatalyzedHandoffEnergy (kRetry cNl : Nat) : Nat := kRetry * cNl
def activationReduction (kRetry cNl cEnz : Nat) : Nat := kRetry * cNl - cEnz

/-- **CTA-T32 (`digital_enzyme_barrier_lowering_and_invariance`)**: Replacing unattested
    natural-language translation (`kRetry * cNl` with `1 <= kRetry`) by a `DigitalEnzyme` with
    `E.cEnz < cNl` yields strictly positive activation-energy reduction `DeltaE_ddagger > 0` while
    leaving the digital enzyme structurally unconsumed across any sequence of `inputs`. -/
theorem digital_enzyme_barrier_lowering_and_invariance {Src IR Dst : Type}
    (E : DigitalEnzyme Src IR Dst) (dst : Dst) (inputs : List Src)
    (kRetry cNl : Nat) (hk : 1 ≤ kRetry) (hc : E.cEnz < cNl) :
    (runEnzymaticChain E dst inputs).1 = E ∧
    E.cEnz < uncatalyzedHandoffEnergy kRetry cNl ∧
    0 < activationReduction kRetry cNl E.cEnz := by
  have h_inv : ∀ d (xs : List Src), (runEnzymaticChain E d xs).1 = E := by
    intro d xs
    induction xs generalizing d with
    | nil => rfl
    | cons s rest ih =>
      simp only [runEnzymaticChain, enzymaticStep]
      split
      · exact ih (E.decodeApply d (E.encodePhi s))
      · exact ih d
  have h_mult : cNl ≤ kRetry * cNl := by
    have h1 : 1 * cNl ≤ kRetry * cNl := Nat.mul_le_mul_right cNl hk
    omega
  unfold uncatalyzedHandoffEnergy activationReduction
  refine ⟨h_inv dst inputs, ?_, ?_⟩
  · omega
  · omega

/-- **CTA-T33 (`digital_enzyme_linear_cumulative_savings`)**: Across `M >= 1` catalyzed reactions,
    cumulative enzymatic handoff energy `M * cEnz` is strictly smaller than `M` uncatalyzed NL
    handoffs, and total joule savings grow linearly as `M * DeltaE_ddagger > 0`. -/
theorem digital_enzyme_linear_cumulative_savings (M kRetry cNl cEnz : Nat)
    (hM : 0 < M) (hk : 1 ≤ kRetry) (hc : cEnz < cNl) :
    M * cEnz < M * uncatalyzedHandoffEnergy kRetry cNl ∧
    M * uncatalyzedHandoffEnergy kRetry cNl - M * cEnz = M * activationReduction kRetry cNl cEnz ∧
    0 < M * activationReduction kRetry cNl cEnz := by
  unfold uncatalyzedHandoffEnergy activationReduction
  have h_mult : cNl ≤ kRetry * cNl := by
    have h1 : 1 * cNl ≤ kRetry * cNl := Nat.mul_le_mul_right cNl hk
    omega
  have h_lt : cEnz < kRetry * cNl := by omega
  have h_diff_pos : 0 < kRetry * cNl - cEnz := by omega
  have h_mul_lt : M * cEnz < M * (kRetry * cNl) := Nat.mul_lt_mul_of_pos_left h_lt hM
  have h_dist : M * (kRetry * cNl - cEnz) + M * cEnz = M * (kRetry * cNl) := by
    rw [← Nat.mul_add]
    have h_sub : kRetry * cNl - cEnz + cEnz = kRetry * cNl := by omega
    rw [h_sub]
  refine ⟨h_mul_lt, ?_, Nat.mul_pos hM h_diff_pos⟩
  omega

/-- **CTA-T34 (`digital_enzyme_zero_unverified_drift`)**: Whenever `vDet` is semantically sound
    with respect to recipient invariant `validDst` (`validDst d -> vDet ir = true -> validDst (decodeApply d ir)`),
    an enzymatic reaction chain propagates zero unverified drift across arbitrary input lists,
    whereas an unverified NL chain with per-hop drift `eps > 0` accumulates `M * eps > 0` drift. -/
theorem digital_enzyme_zero_unverified_drift {Src IR Dst : Type}
    (E : DigitalEnzyme Src IR Dst) (validDst : Dst → Prop)
    (h_sound : ∀ d ir, validDst d → E.vDet ir = true → validDst (E.decodeApply d ir))
    (dst0 : Dst) (inputs : List Src) (h0 : validDst dst0)
    (eps : Nat) (heps : 0 < eps) :
    validDst (runEnzymaticChain E dst0 inputs).2 ∧
    (0 < inputs.length → 0 < inputs.length * eps) := by
  constructor
  · induction inputs generalizing dst0 with
    | nil => exact h0
    | cons s rest ih =>
      simp only [runEnzymaticChain, enzymaticStep, enzymeAdmit]
      by_cases h_adm : (E.attestOk (E.encodePhi s) && E.vDet (E.encodePhi s)) = true
      · simp only [h_adm, ↓reduceIte]
        simp only [Bool.and_eq_true] at h_adm
        have h_next : validDst (E.decodeApply dst0 (E.encodePhi s)) :=
          h_sound dst0 (E.encodePhi s) h0 h_adm.2
        exact ih (E.decodeApply dst0 (E.encodePhi s)) h_next
      · simp only [h_adm]
        exact ih dst0 h0
  · intro hlen
    exact Nat.mul_pos hlen heps

/-- Sequential two-enzyme cascade `E2 ∘ E1` propagating `Src -> Mid -> Out` iff both gates pass. -/
def composeEnzymeStep {Src IR1 Mid IR2 Out : Type}
    (E1 : DigitalEnzyme Src IR1 Mid) (E2 : DigitalEnzyme Mid IR2 Out)
    (src : Src) (mid : Mid) (out : Out) :
    DigitalEnzyme Src IR1 Mid × DigitalEnzyme Mid IR2 Out × Mid × Out :=
  let (_, mid', fired1) := enzymaticStep E1 src mid
  if fired1 then
    let (_, out', _) := enzymaticStep E2 mid' out
    (E1, E2, mid', out')
  else
    (E1, E2, mid, out)

/-- **CTA-T35 (`digital_enzyme_sequential_composition`)**: Sequential composition `E2 ∘ E1` preserves
    catalyst invariance of both enzymes, composes semantic soundness end-to-end without intermediate
    drift leakage, and sums activation-energy savings `DeltaE_1 + DeltaE_2 > 0`. -/
theorem digital_enzyme_sequential_composition {Src IR1 Mid IR2 Out : Type}
    (E1 : DigitalEnzyme Src IR1 Mid) (E2 : DigitalEnzyme Mid IR2 Out)
    (invMid : Mid → Prop) (invOut : Out → Prop)
    (h1 : ∀ m ir1, invMid m → E1.vDet ir1 = true → invMid (E1.decodeApply m ir1))
    (h2 : ∀ o ir2, invOut o → E2.vDet ir2 = true → invOut (E2.decodeApply o ir2))
    (src : Src) (mid0 : Mid) (out0 : Out) (hm0 : invMid mid0) (ho0 : invOut out0)
    (k1 cNl1 k2 cNl2 : Nat) (hk1 : 1 ≤ k1) (hk2 : 1 ≤ k2)
    (hc1 : E1.cEnz < cNl1) (hc2 : E2.cEnz < cNl2) :
    let res := composeEnzymeStep E1 E2 src mid0 out0
    res.1 = E1 ∧ res.2.1 = E2 ∧ invMid res.2.2.1 ∧ invOut res.2.2.2 ∧
    (E1.cEnz + E2.cEnz < k1 * cNl1 + k2 * cNl2) ∧
    (k1 * cNl1 + k2 * cNl2) - (E1.cEnz + E2.cEnz) =
      activationReduction k1 cNl1 E1.cEnz + activationReduction k2 cNl2 E2.cEnz := by
  dsimp only [composeEnzymeStep]
  have hm_mult1 : cNl1 ≤ k1 * cNl1 := by
    have h := Nat.mul_le_mul_right cNl1 hk1; omega
  have hm_mult2 : cNl2 ≤ k2 * cNl2 := by
    have h := Nat.mul_le_mul_right cNl2 hk2; omega
  have h_step1 : invMid (enzymaticStep E1 src mid0).2.1 := by
    unfold enzymaticStep enzymeAdmit
    split
    · next hadm =>
      simp only [Bool.and_eq_true] at hadm
      exact h1 mid0 (E1.encodePhi src) hm0 hadm.2
    · exact hm0
  have h_step2 : ∀ m, invOut (enzymaticStep E2 m out0).2.1 := by
    intro m
    unfold enzymaticStep enzymeAdmit
    split
    · next hadm =>
      simp only [Bool.and_eq_true] at hadm
      exact h2 out0 (E2.encodePhi m) ho0 hadm.2
    · exact ho0
  unfold activationReduction
  split
  · refine ⟨rfl, rfl, h_step1, h_step2 _, ?_, ?_⟩ <;> omega
  · refine ⟨rfl, rfl, hm0, ho0, ?_, ?_⟩ <;> omega

/-! ## 2. 10-Camp Niche Specialization & Enzymatic Pareto Dominance (`CTA-T36` to `CTA-T40`) -/

/-- Canonical paradigm count in the DES-10 unification atlas (`C1` through `C10`). -/
def TenCamps : Nat := 10

/-- Convert Boolean pass indicator to `{0, 1}`. -/
def passInd (b : Bool) : Nat := if b then 1 else 0

/-- Coverage union across `K` paradigm camps (`0 .. K - 1`) in regime `r`. -/
def desPass (pass : Nat → Nat → Bool) (r : Nat) : Nat → Bool
  | 0     => false
  | k + 1 => desPass pass r k || pass k r

/-- Executable `O(K)` Enzymatic Niche Router selecting `k*(r) in argmin { cost k r | pass k r = true }`
    across camps `0 .. K - 1`. -/
def selectNicheCamp (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat) (r : Nat) : Nat → Option Nat
  | 0     => none
  | k + 1 =>
    match selectNicheCamp pass cost r k with
    | none      => if pass k r then some k else none
    | some best =>
      if pass k r && decide (cost k r < cost best r) then some k else some best

/-- Helper: if camp `k0 < K` passes regime `r`, then the `K`-camp union `desPass` passes `r`. -/
theorem desPass_of_camp (pass : Nat → Nat → Bool) (r K k0 : Nat)
    (hk0 : k0 < K) (hp : pass k0 r = true) :
    desPass pass r K = true := by
  induction K with
  | zero => omega
  | succ k ih =>
    simp only [desPass, Bool.or_eq_true]
    by_cases hjk : k0 = k
    · subst hjk; exact Or.inr hp
    · exact Or.inl (ih (by omega))

/-- Helper: `selectNicheCamp = none` implies every camp `< K` failed regime `r`. -/
theorem selectNicheCamp_none_imp (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (r K : Nat) (hnone : selectNicheCamp pass cost r K = none) :
    ∀ j, j < K → pass j r = false := by
  induction K with
  | zero => intro j hj; omega
  | succ k ih =>
    simp only [selectNicheCamp] at hnone
    cases hrec : selectNicheCamp pass cost r k with
    | none =>
      rw [hrec] at hnone
      dsimp at hnone
      have hpk : pass k r = false := by
        cases h : pass k r
        · rfl
        · simp [h] at hnone
      intro j hj
      by_cases hjk : j = k
      · subst hjk; exact hpk
      · exact ih hrec j (by omega)
    | some best =>
      rw [hrec] at hnone
      dsimp at hnone
      split at hnone <;> contradiction

/-- Helper: `selectNicheCamp = some kStar` certifies `kStar < K`, `pass kStar r = true`, and
    exact `argmin` cost optimality across all passing camps `< K`. -/
theorem selectNicheCamp_spec (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (r K kStar : Nat) (hsel : selectNicheCamp pass cost r K = some kStar) :
    kStar < K ∧ pass kStar r = true ∧ (∀ j, j < K → pass j r = true → cost kStar r ≤ cost j r) := by
  induction K generalizing kStar with
  | zero => simp [selectNicheCamp] at hsel
  | succ k ih =>
    simp only [selectNicheCamp] at hsel
    cases hrec : selectNicheCamp pass cost r k with
    | none =>
      rw [hrec] at hsel
      dsimp at hsel
      split at hsel
      · next hpk =>
        injection hsel with heq
        subst heq
        refine ⟨by omega, hpk, ?_⟩
        intro j hj hjp
        by_cases hjk : j = k
        · subst hjk; exact Nat.le_refl _
        · have hf := selectNicheCamp_none_imp pass cost r k hrec j (by omega)
          rw [hf] at hjp; contradiction
      · contradiction
    | some best =>
      rw [hrec] at hsel
      dsimp at hsel
      rcases ih best hrec with ⟨hb_lt, hb_pass, hb_min⟩
      split at hsel
      · next hcond =>
        simp only [Bool.and_eq_true, decide_eq_true_eq] at hcond
        injection hsel with heq
        subst heq
        refine ⟨by omega, hcond.1, ?_⟩
        intro j hj hjp
        by_cases hjk : j = k
        · subst hjk; exact Nat.le_refl _
        · have hbm := hb_min j (by omega) hjp
          omega
      · next hcond =>
        injection hsel with heq
        subst heq
        refine ⟨by omega, hb_pass, ?_⟩
        intro j hj hjp
        by_cases hjk : j = k
        · subst hjk
          simp only [Bool.and_eq_true, decide_eq_true_eq, hjp, true_and, Nat.not_lt] at hcond
          exact hcond
        · exact hb_min j (by omega) hjp

/-- Helper: any passing camp `k0 < K` guarantees `selectNicheCamp` returns `some kStar`. -/
theorem selectNicheCamp_some_of_pass (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (r K k0 : Nat) (hk0 : k0 < K) (hp : pass k0 r = true) :
    ∃ kStar, selectNicheCamp pass cost r K = some kStar := by
  cases hsel : selectNicheCamp pass cost r K with
  | none =>
    have hf := selectNicheCamp_none_imp pass cost r K hsel k0 hk0
    rw [hf] at hp; contradiction
  | some kStar => exact ⟨kStar, rfl⟩

/-- Count of passed regimes across `0 .. R - 1`. -/
def totalPassed (p : Nat → Bool) : Nat → Nat
  | 0     => 0
  | R + 1 => totalPassed p R + passInd (p R)

/-- Sum an integer-valued function over `0 .. R - 1`. -/
def sumRegimes (f : Nat → Nat) : Nat → Nat
  | 0     => 0
  | R + 1 => sumRegimes f R + f R

/-- **CTA-T36 (`des_coverage_union_dominates_solo`)**: For `K >= 2` paradigm camps (including
    `K = TenCamps = 10`) and any solo camp `k0 < K`, `DES` coverage `desPass` dominates `k0`
    pointwise and globally across all `R` regimes, and `selectNicheCamp` selects a verified camp
    `kStar` with `cost kStar r <= cost k0 r` whenever `k0` passes. -/
theorem des_coverage_union_dominates_solo (K R k0 r : Nat)
    (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (hK : 2 ≤ K) (hk0 : k0 < K) :
    passInd (pass k0 r) ≤ passInd (desPass pass r K) ∧
    (pass k0 r = true → ∃ kStar, selectNicheCamp pass cost r K = some kStar ∧
      kStar < K ∧ pass kStar r = true ∧ cost kStar r ≤ cost k0 r) ∧
    totalPassed (fun r' => pass k0 r') R ≤ totalPassed (fun r' => desPass pass r' K) R := by
  let _ := hK
  have h_pt : ∀ r', passInd (pass k0 r') ≤ passInd (desPass pass r' K) := by
    intro r'
    cases hp : pass k0 r'
    · simp [passInd]
    · have hdes := desPass_of_camp pass r' K k0 hk0 hp
      simp [passInd, hdes]
  refine ⟨h_pt r, ?_, ?_⟩
  · intro hp
    rcases selectNicheCamp_some_of_pass pass cost r K k0 hk0 hp with ⟨kStar, hsel⟩
    rcases selectNicheCamp_spec pass cost r K kStar hsel with ⟨hlt, hpass, hmin⟩
    exact ⟨kStar, hsel, hlt, hpass, hmin k0 hk0 hp⟩
  · induction R with
    | zero => simp [totalPassed]
    | succ m ih =>
      simp only [totalPassed]
      have hm := h_pt m
      omega

/-- Helper: `totalPassed p R <= R` always, and strictly `< R` if some `r0 < R` has `p r0 = false`. -/
theorem totalPassed_le_and_strict (p : Nat → Bool) (R : Nat) :
    totalPassed p R ≤ R ∧ (∀ r0, r0 < R → p r0 = false → totalPassed p R < R) := by
  induction R with
  | zero =>
    refine ⟨by simp [totalPassed], ?_⟩
    intro r0 hr0; omega
  | succ m ih =>
    rcases ih with ⟨hle, hlt⟩
    have h_ind : passInd (p m) ≤ 1 := by
      unfold passInd; split <;> omega
    refine ⟨by simp only [totalPassed]; omega, ?_⟩
    intro r0 hr0 hfalse
    simp only [totalPassed]
    by_cases hrm : r0 = m
    · subst hrm
      simp [passInd, hfalse]
      omega
    · have hm_lt := hlt r0 (by omega) hfalse
      omega

/-- **CTA-T37 (`des_strict_global_pass_superiority`)**: Formal refutation of siloed monocultures
    (valid for all `K >= 2`, including `K = TenCamps = 10`): whenever every regime `r < R` is
    solved by at least one specialist camp while no single solo camp solves all `R` regimes,
    `DES` achieves full coverage `R` and strictly outperforms every solo camp `k0 < K`. -/
theorem des_strict_global_pass_superiority (K R k0 : Nat) (pass : Nat → Nat → Bool)
    (hK : 2 ≤ K) (hR : 0 < R) (hk0 : k0 < K)
    (h_cover : ∀ r, r < R → ∃ k, k < K ∧ pass k r = true)
    (h_no_solo_all : ∀ k, k < K → ∃ r, r < R ∧ pass k r = false) :
    totalPassed (fun r => desPass pass r K) R = R ∧
    totalPassed (fun r => pass k0 r) R < totalPassed (fun r => desPass pass r K) R := by
  let _ := hK; let _ := hR
  have h_all_des : ∀ N, N ≤ R → totalPassed (fun r => desPass pass r K) N = N := by
    intro N hN
    induction N with
    | zero => rfl
    | succ m ih =>
      rcases h_cover m (by omega) with ⟨km, hkm_lt, hkm_pass⟩
      have hdes := desPass_of_camp pass m K km hkm_lt hkm_pass
      simp [totalPassed, passInd, hdes, ih (by omega)]
  have h_eq : totalPassed (fun r => desPass pass r K) R = R := h_all_des R (Nat.le_refl R)
  rcases h_no_solo_all k0 hk0 with ⟨rFail, hrFail_lt, hrFail_false⟩
  have h_strict := (totalPassed_le_and_strict (fun r => pass k0 r) R).2 rFail hrFail_lt hrFail_false
  exact ⟨h_eq, by rw [h_eq]; exact h_strict⟩

/-- Execution cost of the `selectNicheCamp`-selected specialist in regime `r` (or `0` if none). -/
def nicheRoutedCost (K : Nat) (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat) (r : Nat) : Nat :=
  match selectNicheCamp pass cost r K with
  | some kStar => cost kStar r
  | none       => 0

/-- Total `DES` energy across `0 .. R - 1`: specialist cost plus routing enzyme cost `cEnz` per regime. -/
def desTotalEnergy (K R : Nat) (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat) (cEnz : Nat) : Nat :=
  sumRegimes (fun r => nicheRoutedCost K pass cost r + cEnz) R

/-- Total energy of a solo universal camp `kUniv` across `0 .. R - 1`. -/
def soloTotalEnergy (R : Nat) (cost : Nat → Nat → Nat) (kUniv : Nat) : Nat :=
  sumRegimes (fun r => cost kUniv r) R

/-- Sum of per-regime execution savings `cost kUniv r - cost k*(r) r` across `0 .. R - 1`. -/
def totalNicheSavings (K R : Nat) (pass : Nat → Nat → Bool)
    (cost : Nat → Nat → Nat) (kUniv : Nat) : Nat :=
  sumRegimes (fun r => cost kUniv r - nicheRoutedCost K pass cost r) R

/-- **CTA-T38 (`des_strict_total_joule_dominance`)**: Against any universal solo camp `kUniv < K`
    (`K >= 2`, including `K = TenCamps = 10`) that passes all `R` regimes, `DES` achieves strictly
    lower total joules whenever cumulative niche execution savings exceed `R * cEnz`. -/
theorem des_strict_total_joule_dominance (K R kUniv cEnz : Nat)
    (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (hK : 2 ≤ K) (hkUniv : kUniv < K) (h_univ : ∀ r, r < R → pass kUniv r = true)
    (h_net : R * cEnz < totalNicheSavings K R pass cost kUniv) :
    desTotalEnergy K R pass cost cEnz < soloTotalEnergy R cost kUniv := by
  let _ := hK
  have h_pt_le : ∀ r, r < R → nicheRoutedCost K pass cost r ≤ cost kUniv r := by
    intro r hr
    have hp := h_univ r hr
    rcases selectNicheCamp_some_of_pass pass cost r K kUniv hkUniv hp with ⟨kStar, hsel⟩
    rcases selectNicheCamp_spec pass cost r K kStar hsel with ⟨_, _, hmin⟩
    unfold nicheRoutedCost
    rw [hsel]
    exact hmin kUniv hkUniv hp
  have h_decomp : ∀ N, N ≤ R →
      desTotalEnergy K N pass cost cEnz =
        sumRegimes (fun r => nicheRoutedCost K pass cost r) N + N * cEnz ∧
      sumRegimes (fun r => nicheRoutedCost K pass cost r) N +
        totalNicheSavings K N pass cost kUniv = soloTotalEnergy N cost kUniv := by
    intro N hN
    induction N with
    | zero =>
      simp [desTotalEnergy, soloTotalEnergy, totalNicheSavings, sumRegimes]
    | succ m ih =>
      rcases ih (by omega) with ⟨h_des_m, h_sav_m⟩
      have hm_le : nicheRoutedCost K pass cost m ≤ cost kUniv m := h_pt_le m (by omega)
      simp only [desTotalEnergy, soloTotalEnergy, totalNicheSavings, sumRegimes] at *
      have h_mul_succ : (m + 1) * cEnz = m * cEnz + cEnz := Nat.succ_mul m cEnz
      refine ⟨by omega, by omega⟩
  rcases h_decomp R (Nat.le_refl R) with ⟨h_des_R, h_sav_R⟩
  omega

/-- **CTA-T39 (`des_strict_cpj_dominance`)**: Cross-multiplied Coherence-per-Joule (`CpJ = Q / E`)
    dominance of `DES` over any universal solo camp `kUniv < K` (`K >= 2`, e.g., `K = TenCamps = 10`):
    `Q_solo * E_DES < Q_DES * E_solo` whenever `R >= 1` and niche savings exceed `R * cEnz`. -/
theorem des_strict_cpj_dominance (K R kUniv cEnz : Nat)
    (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (hK : 2 ≤ K) (hR : 0 < R) (hkUniv : kUniv < K)
    (h_univ : ∀ r, r < R → pass kUniv r = true)
    (h_net : R * cEnz < totalNicheSavings K R pass cost kUniv) :
    let qSolo := totalPassed (fun r => pass kUniv r) R
    let qDes  := totalPassed (fun r => desPass pass r K) R
    qSolo * desTotalEnergy K R pass cost cEnz < qDes * soloTotalEnergy R cost kUniv := by
  have hE : desTotalEnergy K R pass cost cEnz < soloTotalEnergy R cost kUniv :=
    des_strict_total_joule_dominance K R kUniv cEnz pass cost hK hkUniv h_univ h_net
  have h_q_eq : ∀ N, N ≤ R →
      totalPassed (fun r => pass kUniv r) N = N ∧
      totalPassed (fun r => desPass pass r K) N = N := by
    intro N hN
    induction N with
    | zero => simp [totalPassed]
    | succ m ih =>
      rcases ih (by omega) with ⟨hq1, hq2⟩
      have hpm := h_univ m (by omega)
      have hdm := desPass_of_camp pass m K kUniv hkUniv hpm
      simp [totalPassed, passInd, hpm, hdm, hq1, hq2]
  rcases h_q_eq R (Nat.le_refl R) with ⟨hqS, hqD⟩
  dsimp only
  rw [hqS, hqD]
  exact Nat.mul_lt_mul_of_pos_left hE hR

/-- Calibration sample budget for `1` zero-training pass of `m` probes per camp across `K` camps. -/
def calibrationProbeBudget (K m : Nat) : Nat := K * m

/-- **CTA-T40 (`des_one_pass_calibration_identifies_niche_router`)**: Zero-wait synthesis:
    a single deterministic calibration pass (`epochs = 1`, `0` gradient updates) of size `K * m`
    (`m >= 1`) per regime suffices to populate `(pass, cost)` and immediately identify `k*(r)`
    minimizing execution cost among all passing camps in `{0, .., K - 1}`. -/
theorem des_one_pass_calibration_identifies_niche_router (K m r k0 : Nat)
    (pass : Nat → Nat → Bool) (cost : Nat → Nat → Nat)
    (hK : 2 ≤ K) (hm : 1 ≤ m) (hk0 : k0 < K) (hp0 : pass k0 r = true) :
    0 < calibrationProbeBudget K m ∧
    calibrationProbeBudget K m = K * m ∧
    (∃ kStar, selectNicheCamp pass cost r K = some kStar ∧
      kStar < K ∧ pass kStar r = true ∧
      ∀ k, k < K → pass k r = true → cost kStar r ≤ cost k r) := by
  have hK_pos : 0 < K := by omega
  have hm_pos : 0 < m := by omega
  rcases selectNicheCamp_some_of_pass pass cost r K k0 hk0 hp0 with ⟨kStar, hsel⟩
  rcases selectNicheCamp_spec pass cost r K kStar hsel with ⟨hlt, hpass, hmin⟩
  unfold calibrationProbeBudget
  exact ⟨Nat.mul_pos hK_pos hm_pos, rfl, ⟨kStar, hsel, hlt, hpass, hmin⟩⟩

/-! ## 3. Closed-Loop 4-Tier Downward Forcing Function & Horizon Monotonicity (`CTA-T41` to `CTA-T45`) -/

/-- Ordered execution energies of the 4-tier downward crystallization hierarchy:
    `Tier 3` (Frontier Discovery `c3`) > `Tier 2` (Verified Symbolic Rule `c2`) >
    `Tier 1` (Episodic Case `DNULLMM1` `c1`) > `Tier 0` (Hardware `LUT6` / Automaton `c0`) > `0`. -/
structure FourTierCosts where
  c0   : Nat
  c1   : Nat
  c2   : Nat
  c3   : Nat
  hc0  : 0 < c0
  hc01 : c0 < c1
  hc12 : c1 < c2
  hc23 : c2 < c3

/-- Lookup tier execution cost for `j in {0, 1, 2, 3}`. -/
def tierCost (tc : FourTierCosts) : Fin 4 → Nat
  | ⟨0, _⟩ => tc.c0
  | ⟨1, _⟩ => tc.c1
  | ⟨2, _⟩ => tc.c2
  | ⟨3, _⟩ => tc.c3

/-- **CTA-T41 (`downward_step_amortization_dominance`)**: Promoting a verified witness from Tier
    `j + 1` (`c_j`) down to Tier `j` (`c_{j-1}`) at one-time compile cost `eComp` strictly reduces
    cumulative and per-step amortized energy across `N` post-promotion arrivals if and only if
    `eComp < N * (cHigh - cLow)` (i.e., `N > E_comp / (c_j - c_{j-1})`). -/
theorem downward_step_amortization_dominance (tc : FourTierCosts) (j : Fin 3) (eComp N : Nat) :
    let cLow  := tierCost tc ⟨j.val, by omega⟩
    let cHigh := tierCost tc ⟨j.val + 1, by omega⟩
    cLow < cHigh ∧ (eComp + N * cLow < N * cHigh ↔ eComp < N * (cHigh - cLow)) := by
  have h_lt : tierCost tc ⟨j.val, by omega⟩ < tierCost tc ⟨j.val + 1, by omega⟩ := by
    rcases j with ⟨val, hval⟩
    match val with
    | 0 => exact tc.hc01
    | 1 => exact tc.hc12
    | 2 => exact tc.hc23
  dsimp only
  refine ⟨h_lt, ?_⟩
  have h_split : N * (tierCost tc ⟨j.val + 1, by omega⟩ - tierCost tc ⟨j.val, by omega⟩) +
      N * tierCost tc ⟨j.val, by omega⟩ = N * tierCost tc ⟨j.val + 1, by omega⟩ := by
    rw [← Nat.mul_add]
    have h_sub : tierCost tc ⟨j.val + 1, by omega⟩ - tierCost tc ⟨j.val, by omega⟩ +
        tierCost tc ⟨j.val, by omega⟩ = tierCost tc ⟨j.val + 1, by omega⟩ := by omega
    rw [h_sub]
  omega

/-- Marginal execution energy at arrival index `n` under cumulative recurrence thresholds
    `tau3` (`Tier 3 -> 2`), `tau3 + tau2` (`Tier 2 -> 1`), and `tau3 + tau2 + tau1` (`Tier 1 -> 0`). -/
def marginalTierEnergy (tc : FourTierCosts) (tau3 tau2 tau1 n : Nat) : Nat :=
  if tau3 + tau2 + tau1 ≤ n then tc.c0
  else if tau3 + tau2 ≤ n then tc.c1
  else if tau3 ≤ n then tc.c2
  else tc.c3

/-- Cumulative execution + downward-compilation energy across `T` arrivals. -/
def cumulForcingEnergy (tc : FourTierCosts) (tau3 tau2 tau1 eCompTotal T : Nat) : Nat :=
  eCompTotal + sumRegimes (marginalTierEnergy tc tau3 tau2 tau1) T

/-- **CTA-T42 (`four_tier_downward_convergence_to_c0`)**: Marginal task energy under the 4-tier
    downward forcing function is monotonically non-increasing at every arrival `n`, steps down
    from `c3` (`n = 0`, `tau3 > 0`) to exact floor `c0` for all `n >= tau3 + tau2 + tau1`, and
    its time-averaged energy converges within any `eps > 0` of `c0` past finite amortization `T`. -/
theorem four_tier_downward_convergence_to_c0 (tc : FourTierCosts)
    (tau3 tau2 tau1 eCompTotal n T eps : Nat)
    (htau3 : 0 < tau3)
    (h_amort : eCompTotal + (tau3 + tau2 + tau1) * (tc.c3 - tc.c0) < T * eps) :
    marginalTierEnergy tc tau3 tau2 tau1 (n + 1) ≤ marginalTierEnergy tc tau3 tau2 tau1 n ∧
    marginalTierEnergy tc tau3 tau2 tau1 0 = tc.c3 ∧
    (tau3 + tau2 + tau1 ≤ n → marginalTierEnergy tc tau3 tau2 tau1 n = tc.c0) ∧
    cumulForcingEnergy tc tau3 tau2 tau1 eCompTotal T < T * (tc.c0 + eps) := by
  have hc01 := tc.hc01; have hc12 := tc.hc12; have hc23 := tc.hc23
  have h_mono : marginalTierEnergy tc tau3 tau2 tau1 (n + 1) ≤ marginalTierEnergy tc tau3 tau2 tau1 n := by
    unfold marginalTierEnergy
    by_cases a1 : tau3 + tau2 + tau1 ≤ n + 1 <;>
    by_cases a2 : tau3 + tau2 ≤ n + 1 <;>
    by_cases a3 : tau3 ≤ n + 1 <;>
    by_cases b1 : tau3 + tau2 + tau1 ≤ n <;>
    by_cases b2 : tau3 + tau2 ≤ n <;>
    by_cases b3 : tau3 ≤ n <;>
    simp only [a1, a2, a3, b1, b2, b3, ↓reduceIte] <;> omega
  have h_zero : marginalTierEnergy tc tau3 tau2 tau1 0 = tc.c3 := by
    unfold marginalTierEnergy
    have h1 : ¬ (tau3 + tau2 + tau1 ≤ 0) := by omega
    have h2 : ¬ (tau3 + tau2 ≤ 0) := by omega
    have h3 : ¬ (tau3 ≤ 0) := by omega
    simp [h1, h2, h3]
  have h_floor : tau3 + tau2 + tau1 ≤ n → marginalTierEnergy tc tau3 tau2 tau1 n = tc.c0 := by
    intro hge
    unfold marginalTierEnergy
    simp [hge]
  have h_sum_bound : ∀ K,
      sumRegimes (marginalTierEnergy tc tau3 tau2 tau1) K ≤
        K * tc.c0 + (tau3 + tau2 + tau1) * (tc.c3 - tc.c0) := by
    intro K
    induction K with
    | zero => simp [sumRegimes]
    | succ m ih =>
      simp only [sumRegimes]
      by_cases h_warm : tau3 + tau2 + tau1 ≤ m
      · have hm0 : marginalTierEnergy tc tau3 tau2 tau1 m = tc.c0 := by
          unfold marginalTierEnergy; simp [h_warm]
        rw [hm0]
        have h_succ : (m + 1) * tc.c0 = m * tc.c0 + tc.c0 := Nat.succ_mul m tc.c0
        omega
      · have h_m_lt : m < tau3 + tau2 + tau1 := by omega
        have h_le_m : ∀ k, k ≤ m → marginalTierEnergy tc tau3 tau2 tau1 k ≤ tc.c3 := by
          intro k _; unfold marginalTierEnergy
          split <;> try omega
          split <;> try omega
          split <;> omega
        have h_raw : ∀ J, J ≤ m + 1 →
            sumRegimes (marginalTierEnergy tc tau3 tau2 tau1) J ≤ J * tc.c3 := by
          intro J hJ
          induction J with
          | zero => simp [sumRegimes]
          | succ i ihi =>
            simp only [sumRegimes]
            have hi1 := ihi (by omega)
            have hi2 : marginalTierEnergy tc tau3 tau2 tau1 i ≤ tc.c3 := h_le_m i (by omega)
            have h_sm : (i + 1) * tc.c3 = i * tc.c3 + tc.c3 := Nat.succ_mul i tc.c3
            omega
        have h_m1_raw := h_raw (m + 1) (Nat.le_refl _)
        have h_split_c3 : (m + 1) * tc.c0 + (m + 1) * (tc.c3 - tc.c0) = (m + 1) * tc.c3 := by
          rw [← Nat.mul_add]
          have hsub : tc.c0 + (tc.c3 - tc.c0) = tc.c3 := by omega
          rw [hsub]
        have h_ex_le : (m + 1) * (tc.c3 - tc.c0) ≤ (tau3 + tau2 + tau1) * (tc.c3 - tc.c0) :=
          Nat.mul_le_mul_right (tc.c3 - tc.c0) h_m_lt
        simp only [sumRegimes] at h_m1_raw
        omega
  have hT_bound := h_sum_bound T
  have h_dist_T : T * (tc.c0 + eps) = T * tc.c0 + T * eps := Nat.mul_add T tc.c0 eps
  unfold cumulForcingEnergy
  exact ⟨h_mono, h_zero, h_floor, by omega⟩

/-- Horizon output `q * T` and crystallized post-warmup cumulative energy `eInit + T * c0`. -/
def horizonOutput (q T : Nat) : Nat := q * T
def horizonEnergy (eInit c0 T : Nat) : Nat := eInit + T * c0

/-- Helper: strict cross-multiplied CpJ growth across any two horizons `0 < T1 < T2` when `eInit > 0`. -/
theorem cpj_strict_horizon_pair (q eInit c0 T1 T2 : Nat)
    (hq : 0 < q) (he : 0 < eInit) (h12 : T1 < T2) :
    horizonOutput q T1 * horizonEnergy eInit c0 T2 <
      horizonOutput q T2 * horizonEnergy eInit c0 T1 := by
  unfold horizonOutput horizonEnergy
  rw [Nat.mul_add, Nat.mul_add]
  have h_qT : q * T1 < q * T2 := Nat.mul_lt_mul_of_pos_left h12 hq
  have h_term1 : (q * T1) * eInit < (q * T2) * eInit := Nat.mul_lt_mul_of_pos_right h_qT he
  have h_comm : (q * T1) * (T2 * c0) = (q * T2) * (T1 * c0) := by ac_rfl
  omega

/-- **CTA-T43 (`horizon_cpj_monotonicity_month_quarter_year_decade`)**: Temporal Horizon Monotonicity:
    for positive task value `q > 0`, positive initial discovery/compilation investment `eInit > 0`,
    and strictly increasing horizons `0 < T_M < T_Q < T_Y < T_D` (Month < Quarter < Year < Decade),
    cross-multiplied Coherence per Joule strictly increases across every timescale band:
    `CpJ(Month) < CpJ(Quarter) < CpJ(Year) < CpJ(Decade)`. -/
theorem horizon_cpj_monotonicity_month_quarter_year_decade
    (q eInit c0 tMonth tQuarter tYear tDecade : Nat)
    (hq : 0 < q) (he : 0 < eInit) (hM : 0 < tMonth)
    (hMQ : tMonth < tQuarter) (hQY : tQuarter < tYear) (hYD : tYear < tDecade) :
    horizonOutput q tMonth * horizonEnergy eInit c0 tQuarter <
      horizonOutput q tQuarter * horizonEnergy eInit c0 tMonth ∧
    horizonOutput q tQuarter * horizonEnergy eInit c0 tYear <
      horizonOutput q tYear * horizonEnergy eInit c0 tQuarter ∧
    horizonOutput q tYear * horizonEnergy eInit c0 tDecade <
      horizonOutput q tDecade * horizonEnergy eInit c0 tYear := by
  let _ := hM
  exact ⟨cpj_strict_horizon_pair q eInit c0 tMonth tQuarter hq he hMQ,
         cpj_strict_horizon_pair q eInit c0 tQuarter tYear hq he hQY,
         cpj_strict_horizon_pair q eInit c0 tYear tDecade hq he hYD⟩

/-- Gated downward compiler step: promotes `p` via `compileStep` iff `vDet` certifies the compiled target. -/
def promoteVerifiedTier {Prog : Type} (vDet : Prog → Bool) (compileStep : Prog → Prog) (p : Prog) : Prog :=
  if vDet (compileStep p) then compileStep p else p

/-- **CTA-T44 (`downward_compilation_preserves_soundness_all_tiers`)**: Soundness preservation
    across all downward compilation tiers (`Tier 3 -> Tier 2 -> Tier 1 -> Tier 0`): if `vDet` is
    semantically sound (`vDet p = true -> SemanticallySound p`), then starting from any `vDet`-admitted
    Tier-3 discovery `p3`, every promoted Tier-2 symbolic rule, Tier-1 `DNULLMM1` case, and Tier-0
    `LUT6` automaton remains semantically sound (`0` false commits across all four tiers). -/
theorem downward_compilation_preserves_soundness_all_tiers {Prog : Type}
    (SemanticallySound : Prog → Prop) (vDet : Prog → Bool)
    (h_sound : ∀ p, vDet p = true → SemanticallySound p)
    (compile3to2 compile2to1 compile1to0 : Prog → Prog)
    (p3 : Prog) (hp3 : vDet p3 = true) :
    let p2 := promoteVerifiedTier vDet compile3to2 p3
    let p1 := promoteVerifiedTier vDet compile2to1 p2
    let p0 := promoteVerifiedTier vDet compile1to0 p1
    SemanticallySound p3 ∧ SemanticallySound p2 ∧ SemanticallySound p1 ∧ SemanticallySound p0 := by
  have h_step : ∀ (f : Prog → Prog) (p : Prog),
      SemanticallySound p → SemanticallySound (promoteVerifiedTier vDet f p) := by
    intro f p hp
    unfold promoteVerifiedTier
    split
    · next hok => exact h_sound (f p) hok
    · exact hp
  have hs3 : SemanticallySound p3 := h_sound p3 hp3
  have hs2 := h_step compile3to2 p3 hs3
  have hs1 := h_step compile2to1 _ hs2
  have hs0 := h_step compile1to0 _ hs1
  exact ⟨hs3, hs2, hs1, hs0⟩

/-- Window energy over `N` tasks with `H` compiled-tier hits (`cLow`) and `N - H` fallbacks (`cHigh`). -/
def compiledWindowEnergy (eComp H N cLow cHigh : Nat) : Nat :=
  eComp + H * cLow + (N - H) * cHigh

/-- Baseline window energy over `N` tasks without downward compilation (`N * cHigh`). -/
def uncompiledWindowEnergy (N cHigh : Nat) : Nat :=
  N * cHigh

/-- **CTA-T45 (`downward_compilation_falsifier_hit_rate_iff`)**: Testable Forcing-Function Falsifier
    Bound: for `0 < N`, `H <= N`, and `cLow < cHigh`, downward compilation pays back strictly iff
    `eComp < H * (cHigh - cLow)` (`H / N > h_min = E_comp / (N * (cHigh - cLow))`), and FAILS to
    pay back (`uncompiledWindowEnergy <= compiledWindowEnergy`, triggering auto-pruning / kill)
    if and only if `H * (cHigh - cLow) <= eComp` (`h <= h_min`). -/
theorem downward_compilation_falsifier_hit_rate_iff (eComp H N cLow cHigh : Nat)
    (hN : 0 < N) (hH : H ≤ N) (hC : cLow < cHigh) :
    (compiledWindowEnergy eComp H N cLow cHigh < uncompiledWindowEnergy N cHigh ↔
      eComp < H * (cHigh - cLow)) ∧
    (uncompiledWindowEnergy N cHigh ≤ compiledWindowEnergy eComp H N cLow cHigh ↔
      H * (cHigh - cLow) ≤ eComp) := by
  let _ := hN
  unfold compiledWindowEnergy uncompiledWindowEnergy
  have h_hit_split : H * cLow + H * (cHigh - cLow) = H * cHigh := by
    rw [← Nat.mul_add]
    have h_sub : cLow + (cHigh - cLow) = cHigh := by omega
    rw [h_sub]
  have h_tot_split : H * cHigh + (N - H) * cHigh = N * cHigh := by
    rw [← Nat.add_mul]
    have h_add : H + (N - H) = N := by omega
    rw [h_add]
  omega

end Avalanche.EnzymaticSynthesis
