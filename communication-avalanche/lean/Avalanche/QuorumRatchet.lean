/-
  The Communication Tool Avalanche — Part I: Biological & Cultural Ratchet Mechanics
  Module: Avalanche.QuorumRatchet
  Self-contained Lean 4.36.0 formalization (zero external dependencies, zero sorry, zero custom axioms).

  Covers:
    1. Externalize -> Ingest -> Transform cycle & Unverified vs. Gated Multi-Hop Chains (T1..T6)
    2. Sub-Threshold Quiescence ("Zero-Clock Idle Conservation") vs. Clocked Polling (T7..T10)
    3. Cooperative Hill-Type Quorum Switch Monotonicity & Sub/Super-Threshold Steepness (T11..T14)
    4. Gated Cyanobacterial Septal Pore (`SepJ`) Fault Containment vs. Filament Collapse (T15)
-/

namespace Avalanche.QuorumRatchet

/-! ## 1. Conserved Cycle & Ratchet Non-Regression vs. Unverified Multi-Hop Decay -/

/-- Conserved three-phase operator across biological, cultural, and computational rungs. -/
structure CycleOperator (State Signal : Type) where
  externalize : State → Signal
  gate        : State → Signal → Bool
  transform   : State → Signal → State

/-- Single gated ingestion-and-transformation step: transforms iff the receptor/verifier gate fires. -/
def cycleStep {State Signal : Type} (op : CycleOperator State Signal) (s : State) (sig : Signal) : State :=
  if op.gate s sig then op.transform s sig else s

/-- Unverified additive corruption model across `k` relay hops with per-hop error `eps`. -/
def unverifiedError (err0 eps : Nat) : Nat → Nat
  | 0     => err0
  | k + 1 => unverifiedError err0 eps k + eps

/-- **T1 (`unverified_error_closed_form_and_growth`)**: Without a verification gate, additive channel
    corruption `eps >= 1` accumulates linearly as `err0 + k * eps` and strictly degrades after `k >= 1` hops. -/
theorem unverified_error_closed_form_and_growth (err0 eps k : Nat) :
    unverifiedError err0 eps k = err0 + k * eps ∧
    (0 < eps → 0 < k → err0 < unverifiedError err0 eps k) := by
  induction k with
  | zero =>
    simp [unverifiedError]
  | succ m ih =>
    rcases ih with ⟨heq, _⟩
    constructor
    · simp [unverifiedError, heq, Nat.succ_mul]
      omega
    · intro heps _
      simp [unverifiedError, heq]
      omega

/-- **T2 (`unverified_retention_strict_decay`)**: In scaled rational form (`0 < f < B`, representing
    per-hop retention `0 < f / B < 1`), `(f / B)^(k + 1) < (f / B)^k` for every hop `k`. -/
theorem unverified_retention_strict_decay (f B k : Nat) (hf_pos : 0 < f) (hf_lt : f < B) :
    f ^ (k + 1) * B ^ k < f ^ k * B ^ (k + 1) := by
  have hfk_pos : 0 < f ^ k := Nat.pow_pos hf_pos
  have hB_pos : 0 < B := Nat.lt_trans hf_pos hf_lt
  have hBk_pos : 0 < B ^ k := Nat.pow_pos hB_pos
  have hprod_pos : 0 < f ^ k * B ^ k := Nat.mul_pos hfk_pos hBk_pos
  have hmul : (f ^ k * B ^ k) * f < (f ^ k * B ^ k) * B :=
    Nat.mul_lt_mul_of_pos_left hf_lt hprod_pos
  have lhs_eq : f ^ (k + 1) * B ^ k = (f ^ k * B ^ k) * f := by
    rw [Nat.pow_succ]
    ac_rfl
  have rhs_eq : f ^ k * B ^ (k + 1) = (f ^ k * B ^ k) * B := by
    rw [Nat.pow_succ]
    ac_rfl
  rw [lhs_eq, rhs_eq]
  exact hmul

/-- Externalized artifact carrying a validity predicate witness and integer quality score. -/
structure Artifact where
  id      : Nat
  quality : Nat
  isValid : Bool
  deriving DecidableEq, Repr

/-- Constant-time deterministic verifier gate checking validity and strict quality gain. -/
def ratchetStep (gate : Artifact → Bool) (cur cand : Artifact) : Artifact :=
  if gate cand && decide (cur.quality < cand.quality) then cand else cur

/-- Multi-generation / multi-hop cultural or computational ratchet fold. -/
def ratchetFold (gate : Artifact → Bool) (init : Artifact) : List Artifact → Artifact
  | []      => init
  | c :: cs => ratchetFold gate (ratchetStep gate init c) cs

/-- **T3 (`ratchet_gate_soundness`)**: If `gate` accepts only valid artifacts (`gate a = true -> a.isValid = true`),
    then `ratchetStep` preserves validity across any candidate arrival. -/
theorem ratchet_gate_soundness (gate : Artifact → Bool)
    (h_sound : ∀ a, gate a = true → a.isValid = true)
    (cur cand : Artifact) (h_cur : cur.isValid = true) :
    (ratchetStep gate cur cand).isValid = true := by
  unfold ratchetStep
  split
  · next hcond =>
    have hg : gate cand = true := by
      cases hgc : gate cand
      · simp [hgc] at hcond
      · rfl
    exact h_sound cand hg
  · exact h_cur

/-- **T4 (`ratchet_non_regression_step`)**: A single verified ratchet step never lowers artifact quality. -/
theorem ratchet_non_regression_step (gate : Artifact → Bool) (cur cand : Artifact) :
    cur.quality ≤ (ratchetStep gate cur cand).quality := by
  unfold ratchetStep
  split
  · next hcond =>
    simp only [Bool.and_eq_true, decide_eq_true_eq] at hcond
    exact Nat.le_of_lt hcond.2
  · exact Nat.le_refl _

/-- **T5 (`ratchet_non_regression_chain`)**: Across any finite stream of externalized candidates
    (including arbitrarily corrupted or adversarial entries), `ratchetFold` preserves validity
    and guarantees non-decreasing quality ("Ratchet Non-Regression"). -/
theorem ratchet_non_regression_chain (gate : Artifact → Bool)
    (h_sound : ∀ a, gate a = true → a.isValid = true)
    (init : Artifact) (cands : List Artifact) (h_init : init.isValid = true) :
    (ratchetFold gate init cands).isValid = true ∧
    init.quality ≤ (ratchetFold gate init cands).quality := by
  induction cands generalizing init with
  | nil =>
    simp [ratchetFold, h_init]
  | cons c cs ih =>
    simp only [ratchetFold]
    have h_step_valid : (ratchetStep gate init c).isValid = true :=
      ratchet_gate_soundness gate h_sound init c h_init
    have h_step_qual : init.quality ≤ (ratchetStep gate init c).quality :=
      ratchet_non_regression_step gate init c
    rcases ih (ratchetStep gate init c) h_step_valid with ⟨h_end_valid, h_end_qual⟩
    exact ⟨h_end_valid, Nat.le_trans h_step_qual h_end_qual⟩

/-- **T6 (`ratchet_strict_advance_and_lock_in`)**: Once a gate-accepted candidate `w` with
    `init.quality < w.quality` arrives, the ratchet strictly advances and retains `w.quality`
    as a permanent lower bound across all subsequent generations, even after `w`'s producer is removed. -/
theorem ratchet_strict_advance_and_lock_in (gate : Artifact → Bool)
    (h_sound : ∀ a, gate a = true → a.isValid = true)
    (init w : Artifact) (later : List Artifact)
    (h_init : init.isValid = true) (h_gate : gate w = true) (h_better : init.quality < w.quality) :
    w.quality ≤ (ratchetFold gate init (w :: later)).quality ∧
    init.quality < (ratchetFold gate init (w :: later)).quality := by
  simp only [ratchetFold]
  have h_step_eq : ratchetStep gate init w = w := by
    unfold ratchetStep
    have hcond : (gate w && decide (init.quality < w.quality)) = true := by
      simp [h_gate, h_better]
    simp [hcond]
  rw [h_step_eq]
  have hw_valid : w.isValid = true := h_sound w h_gate
  have h_chain := (ratchet_non_regression_chain gate h_sound w later hw_valid).2
  let _ := h_init
  exact ⟨h_chain, Nat.lt_of_lt_of_le h_better h_chain⟩

/-! ## 2. Sub-Threshold Quiescence ("Zero-Clock Idle Conservation") -/

/-- Sum of incoming signal weights in a finite arrival trace. -/
def signalSum : List Nat → Nat
  | []      => 0
  | x :: xs => x + signalSum xs

/-- Integrate-and-fire step: accumulates `acc + x`; fires and resets iff `theta <= acc + x`. -/
def integrateAndFireStep (theta state acc x : Nat) : Nat × Nat × Bool :=
  if theta ≤ acc + x then (state + 1, 0, true) else (state, acc + x, false)

/-- Run integrate-and-fire node over an input sequence, returning `(finalState, finalAcc, fireCount)`. -/
def runIntegrateAndFire (theta state acc : Nat) : List Nat → Nat × Nat × Nat
  | []      => (state, acc, 0)
  | x :: xs =>
    let (s', acc', fired) := integrateAndFireStep theta state acc x
    let (sFinal, accFinal, countRest) := runIntegrateAndFire theta s' acc' xs
    (sFinal, accFinal, (if fired then 1 else 0) + countRest)

/-- **T7 (`subthreshold_step_quiescent`)**: Any single arrival keeping `acc + x < theta` causes
    zero state change and emits `fired = false`. -/
theorem subthreshold_step_quiescent (theta state acc x : Nat) (h_sub : acc + x < theta) :
    integrateAndFireStep theta state acc x = (state, acc + x, false) := by
  unfold integrateAndFireStep
  have h_not : ¬ (theta ≤ acc + x) := by omega
  simp [h_not]

/-- **T8 (`subthreshold_trace_zero_firings`)**: If `acc + signalSum xs < theta`, an integrate-and-fire
    node executes zero firings across the entire trace and leaves `state` unchanged. -/
theorem subthreshold_trace_zero_firings (theta state acc : Nat) (xs : List Nat)
    (h_sub : acc + signalSum xs < theta) :
    runIntegrateAndFire theta state acc xs = (state, acc + signalSum xs, 0) := by
  induction xs generalizing acc with
  | nil =>
    simp [signalSum, runIntegrateAndFire]
  | cons x rest ih =>
    simp only [signalSum] at h_sub
    have h_step_sub : acc + x < theta := by omega
    have h_step := subthreshold_step_quiescent theta state acc x h_step_sub
    have h_rest_sub : (acc + x) + signalSum rest < theta := by omega
    have h_ih := ih (acc + x) h_rest_sub
    have h_assoc : (acc + x) + signalSum rest = acc + (x + signalSum rest) := by omega
    simp [runIntegrateAndFire, signalSum, h_step, h_ih, h_assoc]

/-- Clocked polling wake-up checks across `numNodes` over `ticks` clock cycles. -/
def clockedPollChecks (numNodes ticks : Nat) : Nat := numNodes * ticks

/-- **T9 (`clocked_vs_event_quiescent_checks`)**: Under sub-threshold input (`signalSum xs < theta`),
    event-driven firing executes `0` wake transitions whereas synchronous polling executes `N * T > 0` checks. -/
theorem clocked_vs_event_quiescent_checks (numNodes ticks theta state : Nat) (xs : List Nat)
    (hN : 0 < numNodes) (hT : 0 < ticks) (h_sub : signalSum xs < theta) :
    (runIntegrateAndFire theta state 0 xs).2.2 = 0 ∧
    0 < clockedPollChecks numNodes ticks := by
  have h0 : 0 + signalSum xs < theta := by omega
  have h_run := subthreshold_trace_zero_firings theta state 0 xs h0
  constructor
  · rw [h_run]
  · unfold clockedPollChecks
    exact Nat.mul_pos hN hT

/-- **T10 (`zero_clock_idle_energy_dominance`)**: For per-poll energy `cPoll > 0`, sub-threshold
    event-driven idle energy (`0`) is strictly smaller than clocked polling energy `N * T * cPoll`. -/
theorem zero_clock_idle_energy_dominance (numNodes ticks cPoll : Nat)
    (hN : 0 < numNodes) (hT : 0 < ticks) (hC : 0 < cPoll) :
    0 < clockedPollChecks numNodes ticks * cPoll := by
  unfold clockedPollChecks
  exact Nat.mul_pos (Nat.mul_pos hN hT) hC

/-! ## 3. Cooperative Hill-Type Quorum Switch (`H_n(c, K) = c^n / (K^n + c^n)`) -/

/-- Numerator of the Hill activation function `c^n`. -/
def hillNum (n c : Nat) : Nat := c ^ n

/-- Positive denominator of the Hill activation function `K^n + c^n`. -/
def hillDen (n K c : Nat) : Nat := K ^ n + c ^ n

/-- **T11 (`hill_half_maximal_at_threshold`)**: At exact threshold concentration `c = K`,
    `2 * hillNum n K = hillDen n K K` (`H_n(K, K) = 1/2`) for every cooperativity exponent `n`. -/
theorem hill_half_maximal_at_threshold (n K : Nat) :
    2 * hillNum n K = hillDen n K K := by
  unfold hillNum hillDen
  omega

/-- Monotonicity helper: `a <= b -> a^n <= b^n`. -/
theorem pow_le_pow_of_le (a b n : Nat) (hab : a ≤ b) : a ^ n ≤ b ^ n := by
  induction n with
  | zero => simp
  | succ m ih =>
    rw [Nat.pow_succ, Nat.pow_succ]
    exact Nat.mul_le_mul ih hab

/-- **T12 (`hill_monotone_concentration`)**: Cross-multiplied monotonicity of the Hill quorum response:
    for `c1 <= c2`, `H_n(c1, K) <= H_n(c2, K)` (`hillNum n c1 * hillDen n K c2 <= hillNum n c2 * hillDen n K c1`). -/
theorem hill_monotone_concentration (n K c1 c2 : Nat) (hc : c1 ≤ c2) :
    hillNum n c1 * hillDen n K c2 ≤ hillNum n c2 * hillDen n K c1 := by
  unfold hillNum hillDen
  rw [Nat.mul_add, Nat.mul_add]
  have hpow : c1 ^ n ≤ c2 ^ n := pow_le_pow_of_le c1 c2 n hc
  have h1 : c1 ^ n * K ^ n ≤ c2 ^ n * K ^ n := Nat.mul_le_mul_right (K ^ n) hpow
  have h2 : c1 ^ n * c2 ^ n = c2 ^ n * c1 ^ n := Nat.mul_comm (c1 ^ n) (c2 ^ n)
  omega

/-- **T13 (`hill_cooperative_subthreshold_suppression`)**: Below the quorum threshold (`0 < c < K`),
    increasing cooperativity from `n` to `n + 1` strictly suppresses premature activation:
    `H_{n+1}(c, K) < H_n(c, K)` for every `n >= 1`. -/
theorem hill_cooperative_subthreshold_suppression (n K c : Nat)
    (hc_pos : 0 < c) (hc_lt : c < K) :
    hillNum (n + 1) c * hillDen n K c < hillNum n c * hillDen (n + 1) K c := by
  unfold hillNum hillDen
  rw [Nat.mul_add, Nat.mul_add]
  have hcn_pos : 0 < c ^ n := Nat.pow_pos hc_pos
  have hK_pos : 0 < K := Nat.lt_trans hc_pos hc_lt
  have hKn_pos : 0 < K ^ n := Nat.pow_pos hK_pos
  have hprod_pos : 0 < c ^ n * K ^ n := Nat.mul_pos hcn_pos hKn_pos
  have h_strict : (c ^ n * K ^ n) * c < (c ^ n * K ^ n) * K :=
    Nat.mul_lt_mul_of_pos_left hc_lt hprod_pos
  have lhs1 : c ^ (n + 1) * K ^ n = (c ^ n * K ^ n) * c := by
    rw [Nat.pow_succ]
    ac_rfl
  have rhs1 : c ^ n * K ^ (n + 1) = (c ^ n * K ^ n) * K := by
    rw [Nat.pow_succ]
    ac_rfl
  have eq_cross : c ^ (n + 1) * c ^ n = c ^ n * c ^ (n + 1) := Nat.mul_comm _ _
  rw [lhs1, rhs1, eq_cross]
  omega

/-- **T14 (`hill_cooperative_superthreshold_sharpening`)**: Above the quorum threshold (`0 < K < c`),
    increasing cooperativity from `n` to `n + 1` strictly amplifies collective commitment:
    `H_n(c, K) < H_{n+1}(c, K)`. -/
theorem hill_cooperative_superthreshold_sharpening (n K c : Nat)
    (hK_pos : 0 < K) (hK_lt : K < c) :
    hillNum n c * hillDen (n + 1) K c < hillNum (n + 1) c * hillDen n K c := by
  unfold hillNum hillDen
  rw [Nat.mul_add, Nat.mul_add]
  have hc_pos : 0 < c := Nat.lt_trans hK_pos hK_lt
  have hcn_pos : 0 < c ^ n := Nat.pow_pos hc_pos
  have hKn_pos : 0 < K ^ n := Nat.pow_pos hK_pos
  have hprod_pos : 0 < c ^ n * K ^ n := Nat.mul_pos hcn_pos hKn_pos
  have h_strict : (c ^ n * K ^ n) * K < (c ^ n * K ^ n) * c :=
    Nat.mul_lt_mul_of_pos_left hK_lt hprod_pos
  have lhs1 : c ^ n * K ^ (n + 1) = (c ^ n * K ^ n) * K := by
    rw [Nat.pow_succ]
    ac_rfl
  have rhs1 : c ^ (n + 1) * K ^ n = (c ^ n * K ^ n) * c := by
    rw [Nat.pow_succ]
    ac_rfl
  have eq_cross : c ^ n * c ^ (n + 1) = c ^ (n + 1) * c ^ n := Nat.mul_comm _ _
  rw [lhs1, rhs1, eq_cross]
  omega

/-! ## 4. Cyanobacterial `SepJ` Gated Septal Nanopore Containment -/

/-- Number of lysed cells in an `L`-cell filament after `steps` propagation hops from cell `0`
    when septal junctions are open (`gated = false`) vs closed upon `Ca2+` influx (`gated = true`). -/
def filamentDamagedCells (L steps : Nat) (sepJGated : Bool) : Nat :=
  if L = 0 then 0
  else if sepJGated then 1
  else Nat.min L (1 + steps)

/-- Number of surviving metabolically active cells in an `L`-cell filament. -/
def filamentViableCells (L steps : Nat) (sepJGated : Bool) : Nat :=
  L - filamentDamagedCells L steps sepJGated

/-- **T15 (`sepj_gated_containment_vs_collapse`)**: For any multicellular filament of length `L >= 2`,
    after `steps >= L - 1` diffusion steps following terminal-cell lysis, an ungated septal pore
    collapses the entire filament (`0` viable cells), whereas `Ca2+`-gated `SepJ` closure confines
    loss to `1` cell and preserves `L - 1 >= 1` viable cells. -/
theorem sepj_gated_containment_vs_collapse (L steps : Nat) (hL : 2 ≤ L) (hSteps : L - 1 ≤ steps) :
    filamentDamagedCells L steps true = 1 ∧
    filamentViableCells L steps true = L - 1 ∧
    filamentDamagedCells L steps false = L ∧
    filamentViableCells L steps false = 0 ∧
    filamentViableCells L steps false < filamentViableCells L steps true := by
  have hL_ne : L ≠ 0 := by omega
  have h_le : L ≤ 1 + steps := by omega
  have h_min : Nat.min L (1 + steps) = L := Nat.min_eq_left h_le
  unfold filamentViableCells filamentDamagedCells
  simp [hL_ne, h_min]
  omega

end Avalanche.QuorumRatchet
