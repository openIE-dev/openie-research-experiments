/-
  The Communication Tool Avalanche — Part II: Attested Orchestration DAGs, Min-Cost Flow & Agency-Preserving BCI
  Module: Avalanche.OrchestrationFlow
  Self-contained Lean 4.36.0 formalization (zero external dependencies, zero sorry, zero custom axioms).

  Covers:
    1. Attested Channel Payloads (`BLAKE3` content hash + `Ed25519` signature gate, T16..T18)
    2. Heterogeneous Pool Escalation & Coherence-per-Joule (`CpJ = Q / E`) Dominance (T19..T23)
    3. Potential-Reduced Edge Costs, Cycle Invariance, Flow Conservation & SSP Optimality (T24..T28)
    4. Agency-Preserving `N`-Mind Bridging vs. Forced Assimilation (T29..T31)
-/

namespace Avalanche.OrchestrationFlow

/-! ## 1. Attested Channel Payloads (`digest_eq && sig_ok`) -/

/-- Typed orchestration channel message carrying payload digest, claimed digest, signature bit, and weight. -/
structure ChannelPayload where
  computedDigest : Nat
  claimedDigest  : Nat
  sigOk          : Bool
  signalWeight   : Nat
  edgeEnergyCost : Nat
  deriving DecidableEq, Repr

/-- Constant-time channel verification predicate (`digest_eq && sig_ok`). -/
def verifyPayload (p : ChannelPayload) : Bool :=
  decide (p.computedDigest = p.claimedDigest) && p.sigOk

/-- Signal weight admitted into the recipient node's threshold accumulator. -/
def admittedWeight (p : ChannelPayload) : Nat :=
  if verifyPayload p then p.signalWeight else 0

/-- **T16 (`attested_edge_accept_iff`)**: A channel payload passes constant-time verification
    if and only if its content digest matches and its cryptographic signature verifies. -/
theorem attested_edge_accept_iff (p : ChannelPayload) :
    verifyPayload p = true ↔ (p.computedDigest = p.claimedDigest ∧ p.sigOk = true) := by
  unfold verifyPayload
  simp [Bool.and_eq_true, decide_eq_true_eq]

/-- **T17 (`tampered_digest_zero_activation`)**: Any payload with a mismatched content hash is
    rejected (`verifyPayload p = false`) and contributes zero activation weight. -/
theorem tampered_digest_zero_activation (p : ChannelPayload)
    (h_tamper : p.computedDigest ≠ p.claimedDigest) :
    verifyPayload p = false ∧ admittedWeight p = 0 := by
  unfold admittedWeight verifyPayload
  simp [h_tamper]

/-- **T18 (`invalid_signature_zero_activation`)**: Any payload with an invalid signature is
    rejected and contributes zero activation weight toward downstream threshold firing. -/
theorem invalid_signature_zero_activation (p : ChannelPayload) (h_sig : p.sigOk = false) :
    verifyPayload p = false ∧ admittedWeight p = 0 := by
  unfold admittedWeight verifyPayload
  simp [h_sig]

/-! ## 2. Heterogeneous Execution Pool & Coherence-per-Joule (`CpJ = Q / E`) Dominance -/

/-- Total energy of deterministic-first cascade across `N` tasks with `H` deterministic hits (`H <= N`),
    where every task runs the deterministic kernel (`cDet`) and only the `N - H` misses escalate to `cModel`. -/
def cascadeEnergy (N H cDet cModel : Nat) : Nat :=
  N * cDet + (N - H) * cModel

/-- Monolithic model-only baseline energy across `N` tasks. -/
def monolithicEnergy (N cModel : Nat) : Nat :=
  N * cModel

/-- **T19 (`cascade_joule_dominance_iff`)**: For `H <= N`, deterministic-first + thresholded model
    escalation consumes strictly fewer joules than monolithic model execution if and only if
    `N * cDet < H * cModel` (i.e., `c_det < p_hit * c_model`). -/
theorem cascade_joule_dominance_iff (N H cDet cModel : Nat) (hH : H ≤ N) :
    cascadeEnergy N H cDet cModel < monolithicEnergy N cModel ↔ N * cDet < H * cModel := by
  unfold cascadeEnergy monolithicEnergy
  have h_split : (N - H) * cModel + H * cModel = N * cModel := by
    rw [← Nat.add_mul]
    have h_add : N - H + H = N := by omega
    rw [h_add]
  omega

/-- **T20 (`cascade_exact_joule_savings`)**: When `H <= N` and `N * cDet <= H * cModel`, the exact
    joule reduction equals `H * cModel - N * cDet`. -/
theorem cascade_exact_joule_savings (N H cDet cModel : Nat)
    (hH : H ≤ N) (hDom : N * cDet ≤ H * cModel) :
    monolithicEnergy N cModel - cascadeEnergy N H cDet cModel = H * cModel - N * cDet := by
  unfold cascadeEnergy monolithicEnergy
  have h_split : (N - H) * cModel + H * cModel = N * cModel := by
    rw [← Nat.add_mul]
    have h_add : N - H + H = N := by omega
    rw [h_add]
  omega

/-- **T21 (`upstream_gate_reduces_pipeline_energy`)**: Halting `F` invalid candidates at an upstream
    verifier of total cost `eGate` prevents `F * eDown` wasted downstream joules whenever `eGate < F * eDown`. -/
theorem upstream_gate_reduces_pipeline_energy (eBase eGate F eDown : Nat)
    (h_save : eGate < F * eDown) :
    eBase + eGate < eBase + F * eDown := by
  omega

/-- **T22 (`cpj_strict_improvement_from_gating`)**: Cross-multiplied Coherence-per-Joule (`CpJ = Q / E`)
    dominance: for positive coherent output `Q > 0` and positive energy denominators, halting `F` invalid
    downstream firings strictly increases `CpJ` (`Q / (eBase + eGate) > Q / (eBase + F * eDown)`). -/
theorem cpj_strict_improvement_from_gating (Q eBase eGate F eDown : Nat)
    (hQ : 0 < Q) (h_save : eGate < F * eDown) :
    Q * (eBase + eGate) < Q * (eBase + F * eDown) := by
  have hE : eBase + eGate < eBase + F * eDown :=
    upstream_gate_reduces_pipeline_energy eBase eGate F eDown h_save
  exact Nat.mul_lt_mul_of_pos_left hE hQ

/-- **T23 (`cpj_crystallized_skill_amortization`)**: Once a verified artifact is compiled into a
    deterministic kernel (`cDet < cModel`) at one-time synthesis cost `eSynth`, across any horizon `K`
    with `eSynth < K * (cModel - cDet)` and `Q > 0` per task, cumulative `CpJ` strictly exceeds
    repeated model execution. -/
theorem cpj_crystallized_skill_amortization (Q K eSynth cDet cModel : Nat)
    (hQ : 0 < Q) (hDet : cDet < cModel) (hHorizon : eSynth < K * (cModel - cDet)) :
    (Q * K) * (eSynth + K * cDet) < (Q * K) * (K * cModel) := by
  have hK_pos : 0 < K := by
    by_cases hK0 : K = 0
    · subst hK0; simp at hHorizon
    · omega
  have hQK_pos : 0 < Q * K := Nat.mul_pos hQ hK_pos
  have h_split : K * (cModel - cDet) + K * cDet = K * cModel := by
    rw [← Nat.mul_add]
    have h_sub : cModel - cDet + cDet = cModel := by omega
    rw [h_sub]
  have hE : eSynth + K * cDet < K * cModel := by omega
  exact Nat.mul_lt_mul_of_pos_left hE hQK_pos

/-! ## 3. Potential-Reduced Edge Costs & Min-Cost Flow / SSP Optimality Certificates -/

/-- Potential-reduced edge cost `c_pi(u, v) = c(u, v) + pi(u) - pi(v)` on integer-weighted graphs. -/
def reducedCost {n : Nat} (cost : Fin n → Fin n → Int) (pi : Fin n → Int) (u v : Fin n) : Int :=
  cost u v + pi u - pi v

/-- Non-empty vertex walk `start :: rest` in a graph on `Fin n`. -/
def walkFinish {n : Nat} (start : Fin n) : List (Fin n) → Fin n
  | []      => start
  | v :: vs => walkFinish v vs

/-- Raw integer cost summed along consecutive directed edges of `start :: rest`. -/
def walkRawCost {n : Nat} (cost : Fin n → Fin n → Int) (start : Fin n) : List (Fin n) → Int
  | []      => 0
  | v :: vs => cost start v + walkRawCost cost v vs

/-- Potential-reduced cost summed along consecutive directed edges of `start :: rest`. -/
def walkReducedCost {n : Nat} (cost : Fin n → Fin n → Int) (pi : Fin n → Int)
    (start : Fin n) : List (Fin n) → Int
  | []      => 0
  | v :: vs => reducedCost cost pi start v + walkReducedCost cost pi v vs

/-- Predicate asserting every consecutive pair in `start :: rest` satisfies `validEdge`. -/
def ValidWalk {n : Nat} (validEdge : Fin n → Fin n → Prop) (start : Fin n) : List (Fin n) → Prop
  | []      => True
  | v :: vs => validEdge start v ∧ ValidWalk validEdge v vs

/-- **T24 (`reduced_cost_walk_telescoping`)**: Along any finite directed walk from `start` to
    `walkFinish start rest`, potential differences telescope cleanly:
    `walkReducedCost = walkRawCost + pi(start) - pi(finish)`. -/
theorem reduced_cost_walk_telescoping {n : Nat} (cost : Fin n → Fin n → Int)
    (pi : Fin n → Int) (start : Fin n) (rest : List (Fin n)) :
    walkReducedCost cost pi start rest =
      walkRawCost cost start rest + pi start - pi (walkFinish start rest) := by
  induction rest generalizing start with
  | nil =>
    simp [walkReducedCost, walkRawCost, walkFinish]
  | cons v vs ih =>
    simp only [walkReducedCost, walkRawCost, walkFinish, reducedCost]
    rw [ih v]
    omega

/-- **T25 (`reduced_cost_cycle_invariance`)**: Around any closed directed cycle (`walkFinish s rest = s`),
    the potential-reduced cost equals the exact raw cycle cost. -/
theorem reduced_cost_cycle_invariance {n : Nat} (cost : Fin n → Fin n → Int)
    (pi : Fin n → Int) (s : Fin n) (rest : List (Fin n)) (h_cycle : walkFinish s rest = s) :
    walkReducedCost cost pi s rest = walkRawCost cost s rest := by
  rw [reduced_cost_walk_telescoping, h_cycle]
  omega

/-- Non-negativity of reduced walk cost when every edge along the walk has `0 <= reducedCost`. -/
theorem walk_reduced_nonneg {n : Nat} (validEdge : Fin n → Fin n → Prop)
    (cost : Fin n → Fin n → Int) (pi : Fin n → Int)
    (h_nonneg : ∀ u v, validEdge u v → 0 ≤ reducedCost cost pi u v)
    (start : Fin n) (rest : List (Fin n)) (hw : ValidWalk validEdge start rest) :
    0 ≤ walkReducedCost cost pi start rest := by
  induction rest generalizing start with
  | nil => simp [walkReducedCost]
  | cons v vs ih =>
    rcases hw with ⟨hed, hrest⟩
    simp only [walkReducedCost]
    have h1 := h_nonneg start v hed
    have h2 := ih v hrest
    omega

/-- **T26 (`nonneg_reduced_cost_no_negative_cycles`)**: Complementary-slackness / Bellman-potential
    optimality certificate: if node potentials `pi` render all residual edge reduced costs non-negative,
    then no valid residual directed cycle has negative raw cost (`0 <= walkRawCost`). -/
theorem nonneg_reduced_cost_no_negative_cycles {n : Nat} (validEdge : Fin n → Fin n → Prop)
    (cost : Fin n → Fin n → Int) (pi : Fin n → Int)
    (h_nonneg : ∀ u v, validEdge u v → 0 ≤ reducedCost cost pi u v)
    (s : Fin n) (rest : List (Fin n)) (hw : ValidWalk validEdge s rest)
    (h_cycle : walkFinish s rest = s) :
    0 ≤ walkRawCost cost s rest := by
  have h_red := walk_reduced_nonneg validEdge cost pi h_nonneg s rest hw
  rw [reduced_cost_cycle_invariance cost pi s rest h_cycle] at h_red
  exact h_red

/-- **T27 (`ssp_tight_path_shortest_certificate`)**: Successive Shortest Path (`SSP`) certificate:
    if `0 <= reducedCost` on all valid edges and walk `optRest` from `s` to `t` has zero reduced cost
    (uses only tight shortest-path edges), then `optRest` achieves minimum raw cost among all valid
    `s -> t` walks! -/
theorem ssp_tight_path_shortest_certificate {n : Nat} (validEdge : Fin n → Fin n → Prop)
    (cost : Fin n → Fin n → Int) (pi : Fin n → Int)
    (h_nonneg : ∀ u v, validEdge u v → 0 ≤ reducedCost cost pi u v)
    (s t : Fin n) (optRest altRest : List (Fin n))
    (h_opt_end : walkFinish s optRest = t) (h_alt_end : walkFinish s altRest = t)
    (h_opt_tight : walkReducedCost cost pi s optRest = 0)
    (h_alt_valid : ValidWalk validEdge s altRest) :
    walkRawCost cost s optRest ≤ walkRawCost cost s altRest := by
  have h_tel_opt := reduced_cost_walk_telescoping cost pi s optRest
  have h_tel_alt := reduced_cost_walk_telescoping cost pi s altRest
  have h_red_alt := walk_reduced_nonneg validEdge cost pi h_nonneg s altRest h_alt_valid
  rw [h_opt_end, h_opt_tight] at h_tel_opt
  rw [h_alt_end] at h_tel_alt
  omega

/-- Net nodal balance `inflow - outflow` at a node. -/
def nodalBalance (inflow outflow : Int) : Int := inflow - outflow

/-- **T28 (`ssp_augmentation_preserves_flow_conservation`)**: Superposing a flow `f` with nodal balance
    `b` and an augmenting path flow `df` with nodal balance `db` (`0` at internal nodes, `+delta` at source,
    `-delta` at sink) yields exact balance `b + db` at every vertex. -/
theorem ssp_augmentation_preserves_flow_conservation
    (inflowF outflowF inflowDf outflowDf b db : Int)
    (hf : nodalBalance inflowF outflowF = b)
    (hdf : nodalBalance inflowDf outflowDf = db) :
    nodalBalance (inflowF + inflowDf) (outflowF + outflowDf) = b + db := by
  unfold nodalBalance at *
  omega

/-! ## 4. Agency-Preserving `N`-Mind Bridging vs. Forced Assimilation -/

/-- Local opt-in modulation step for participant `i`: ingests message `m` iff local agency gate `g s m` approves. -/
def bridgedStep {State Msg : Type} (gate : State → Msg → Bool)
    (modulate : State → Msg → State) (s : State) (m : Msg) : State :=
  if gate s m then modulate s m else s

/-- Ungated forced-assimilation step: overwrites/mutates participant state unconditionally. -/
def forcedStep {State Msg : Type} (modulate : State → Msg → State) (s : State) (m : Msg) : State :=
  modulate s m

/-- Broadcast a message stream across an `N`-participant bridged collective where each mind `i : Fin N`
    applies its own private agency gate `gate i` and state update `modulate i`. -/
def runBridgedMesh {N : Nat} {State Msg : Type}
    (gate : Fin N → State → Msg → Bool)
    (modulate : Fin N → State → Msg → State)
    (init : Fin N → State) : List Msg → Fin N → State
  | []      => init
  | m :: ms =>
    let nextState := fun i => bridgedStep (gate i) (modulate i) (init i) m
    runBridgedMesh gate modulate nextState ms

/-- **T29 (`agency_preserving_single_step`)**: If a participant's local gate `gate` is invariant-sound
    (`inv s -> gate s m = true -> inv (modulate s m)`), then `bridgedStep` preserves `inv` under
    every external modulation message `m` (including adversarial broadcasts). -/
theorem agency_preserving_single_step {State Msg : Type}
    (inv : State → Prop) (gate : State → Msg → Bool) (modulate : State → Msg → State)
    (h_sound : ∀ s m, inv s → gate s m = true → inv (modulate s m))
    (s : State) (m : Msg) (h_inv : inv s) :
    inv (bridgedStep gate modulate s m) := by
  unfold bridgedStep
  split
  · next hg => exact h_sound s m h_inv hg
  · exact h_inv

/-- **T30 (`agency_preserving_n_mind_sequence`)**: Across any `N`-mind bidirectional mesh and any
    finite sequence of collective broadcasts `msgs`, every participant `i : Fin N` equipped with an
    invariant-sound local opt-in gate preserves its private autonomy invariant `inv i` end-to-end. -/
theorem agency_preserving_n_mind_sequence {N : Nat} {State Msg : Type}
    (inv : Fin N → State → Prop)
    (gate : Fin N → State → Msg → Bool)
    (modulate : Fin N → State → Msg → State)
    (h_sound : ∀ i s m, inv i s → gate i s m = true → inv i (modulate i s m))
    (init : Fin N → State) (msgs : List Msg)
    (h_init : ∀ i, inv i (init i)) :
    ∀ i : Fin N, inv i (runBridgedMesh gate modulate init msgs i) := by
  induction msgs generalizing init with
  | nil =>
    intro i
    exact h_init i
  | cons m ms ih =>
    simp only [runBridgedMesh]
    apply ih
    intro j
    exact agency_preserving_single_step (inv j) (gate j) (modulate j) (h_sound j) (init j) m (h_init j)

/-- **T31 (`forced_assimilation_violates_invariant`)**: Explicit separation between opt-in bridging and
    forced assimilation: on integer preference states `(goalId, knowledge)` where private autonomy is
    `inv s := (s.1 = myGoal)`, an overwrite modulation `(msgGoal, s.2 + msgGain)` violates autonomy in
    one ungated step whenever `msgGoal != myGoal`, whereas the opt-in gate `decide (m.1 = s.1)`
    preserves `s.1 = myGoal` while strictly increasing shared knowledge (`s.2 < s'.2`) on aligned messages! -/
theorem forced_assimilation_violates_invariant (myGoal advGoal knowledge gain : Nat)
    (h_diff : advGoal ≠ myGoal) (h_gain : 0 < gain) :
    let modulate := fun (s : Nat × Nat) (m : Nat × Nat) => (m.1, s.2 + m.2)
    let optInGate := fun (s : Nat × Nat) (m : Nat × Nat) => decide (m.1 = s.1)
    let s0 : Nat × Nat := (myGoal, knowledge)
    (forcedStep modulate s0 (advGoal, gain)).1 ≠ myGoal ∧
    (bridgedStep optInGate modulate s0 (advGoal, gain)).1 = myGoal ∧
    (bridgedStep optInGate modulate s0 (myGoal, gain)).1 = myGoal ∧
    s0.2 < (bridgedStep optInGate modulate s0 (myGoal, gain)).2 := by
  dsimp [forcedStep, bridgedStep]
  simp [h_diff]
  omega

end Avalanche.OrchestrationFlow
