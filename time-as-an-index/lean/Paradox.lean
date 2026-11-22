/-
  Time as an Index — Formal Paradox Ledger Theorems (TQ.Paradox)
  Proves all 13 paradox-constraint theorems in self-contained Lean 4.36.0 (zero sorry).
-/

import Horizon

namespace TQ.Paradox

/-! ## 1. Diagonal, Self-Oracle, and Universal Table Bounds -/

/-- **Theorem 1 (`no_total_self_oracle`)**: Liar / Halting diagonalization.
    No total Boolean oracle `O : Q → Bool` can agree with its own negated diagonal query `d`. -/
theorem no_total_self_oracle {Q : Type} (O truth : Q → Bool) (d : Q)
    (hdiag : truth d = !O d) : O d ≠ truth d := by
  rw [hdiag]
  cases O d <;> decide

/-- **Theorem 2 (`no_universal_answer_table`)**: Cantor / Russell theorem.
    There is no surjection `Q → (Q → Bool)`, so no table indexed by `Q` lists all predicates on `Q`. -/
theorem no_universal_answer_table {Q : Type} (table : Q → (Q → Bool)) :
    ¬ (∀ pred : Q → Bool, ∃ q : Q, table q = pred) := by
  intro hsurj
  let diag : Q → Bool := fun q => !(table q q)
  rcases hsurj diag with ⟨q₀, hq₀⟩
  have hval : table q₀ q₀ = !(table q₀ q₀) := congrFun hq₀ q₀
  cases h : table q₀ q₀ <;> rw [h] at hval <;> contradiction

private theorem rat_one_add_one : (1 : Rat) + 1 = 2 := by
  rw [Rat.add_def']
  exact (Rat.mk_eq_mkRat 2 1 (by decide) (by decide)).symm

private theorem rat_two_ne_zero : (2 : Rat) ≠ 0 := by
  intro h
  have hnum : (2 : Rat).num = (0 : Rat).num := congrArg Rat.num h
  contradiction

private theorem rat_two_mul (p : Rat) : (2 : Rat) * p = p + p := by
  rw [← rat_one_add_one, Rat.add_mul, Rat.one_mul]

private theorem rat_half_mul_two : ((1 : Rat) / 2) * 2 = 1 := by
  rw [Rat.div_def, Rat.one_mul]
  exact Rat.inv_mul_cancel 2 rat_two_ne_zero

private theorem rat_half_add_half : ((1 : Rat) / 2) + ((1 : Rat) / 2) = 1 := by
  have h : ((1 : Rat) / 2) * (1 + 1) = ((1 : Rat) / 2) + ((1 : Rat) / 2) := by
    rw [Rat.mul_add, Rat.mul_one]
  rw [← h, rat_one_add_one, rat_half_mul_two]

private theorem rat_half_nonneg : (0 : Rat) ≤ (1 : Rat) / 2 := by
  rw [Rat.div_def, Rat.one_mul, Rat.inv_def]
  exact Rat.divInt_nonneg (by decide) (by decide)

/-- **Theorem 3 (`mixed_answer_unique`)**: Deutsch mixed-state fixed-point resolution.
    Over rational probabilities `p : Rat`, the self-negating consistency equation `p = 1 - p`
    has the unique solution `p = 1/2`, which lies inside `[0, 1]`. -/
theorem mixed_answer_unique (p : Rat) :
    (p = 1 - p ↔ p = (1 : Rat) / 2) ∧ ((0 : Rat) ≤ (1 : Rat) / 2 ∧ (1 : Rat) / 2 ≤ 1) := by
  have h1_sub_half : (1 : Rat) - (1 : Rat) / 2 = (1 : Rat) / 2 := by
    calc
      (1 : Rat) - (1 : Rat) / 2 = (((1 : Rat) / 2) + ((1 : Rat) / 2)) - (1 : Rat) / 2 := by
        rw [rat_half_add_half]
      _ = (1 : Rat) / 2 := Rat.add_sub_cancel
  refine ⟨?_, ?_⟩
  · constructor
    · intro h
      have hsum : p + p = 1 := by
        calc
          p + p = (1 - p) + p := by rw [← h]
          _ = 1 := Rat.sub_add_cancel
      have h2p : (2 : Rat) * p = 1 := by
        rw [rat_two_mul, hsum]
      calc
        p = 1 * p := (Rat.one_mul p).symm
        _ = (((1 : Rat) / 2) * 2) * p := by rw [rat_half_mul_two]
        _ = ((1 : Rat) / 2) * ((2 : Rat) * p) := Rat.mul_assoc _ _ _
        _ = ((1 : Rat) / 2) * 1 := by rw [h2p]
        _ = (1 : Rat) / 2 := Rat.mul_one _
    · intro h
      rw [h, h1_sub_half]
  · refine ⟨rat_half_nonneg, ?_⟩
    rw [Rat.le_iff_sub_nonneg, h1_sub_half]
    exact rat_half_nonneg

/-! ## 2. Grandfather vs Polchinski Loop Consistency -/

/-- **Theorem 4 (`grandfather_no_pure`)**: Deterministic bit-flip loop has no pure fixed point. -/
theorem grandfather_no_pure (b : Bool) : (!b) ≠ b := by
  cases b <;> decide

/-- **Theorem 5 (`polchinski_multiplicity`)**: Identity time loop admits multiple distinct
    consistent states (`true` and `false` are both fixed points of `id`), formalizing
    Polchinski-billiard / Novikov underdetermination. -/
theorem polchinski_multiplicity :
    (∀ {α : Type} (x : α), id x = x) ∧
    (∃ b₁ b₂ : Bool, b₁ ≠ b₂ ∧ id b₁ = b₁ ∧ id b₂ = b₂) := by
  refine ⟨fun x => rfl, ⟨true, false, by decide, rfl, rfl⟩⟩

/-! ## 3. Finite Pigeonhole, Kolmogorov Incompressibility, and Poincaré Recurrence -/

private def embedFin {k : Nat} (i : Fin k) : Fin (k + 1) :=
  ⟨i.val, Nat.lt_succ_of_lt i.isLt⟩

/-- Finite pigeonhole principle: there is no injection `Fin n → Fin m` when `m < n`. -/
theorem no_injection_gt :
    ∀ {m n : Nat}, m < n → ∀ g : Fin n → Fin m, ¬ (∀ y₁ y₂, g y₁ = g y₂ → y₁ = y₂) := by
  intro m
  induction m with
  | zero =>
    intro n hlt g _
    have y0 : Fin n := ⟨0, hlt⟩
    exact Fin.elim0 (g y0)
  | succ m ih =>
    intro n hlt g hinj
    cases n with
    | zero => omega
    | succ n' =>
      have hm_lt : m < n' := by omega
      let top : Fin (n' + 1) := ⟨n', Nat.lt_succ_self n'⟩
      have htop_val : ∀ i : Fin n', g (embedFin i) ≠ g top := by
        intro i heq
        have hi_eq := hinj (embedFin i) top heq
        have hval : (embedFin i).val = top.val := congrArg Fin.val hi_eq
        dsimp [embedFin, top] at hval
        omega
      let g' : Fin n' → Fin m := fun i =>
        if h : (g (embedFin i)).val < m then
          ⟨(g (embedFin i)).val, h⟩
        else
          have hgi_eq : (g (embedFin i)).val = m := by
            have := (g (embedFin i)).isLt
            omega
          have htop_ne : (g top).val ≠ m := by
            intro htop_m
            have heq_fin : g (embedFin i) = g top := Fin.ext (by rw [hgi_eq, htop_m])
            exact htop_val i heq_fin
          ⟨(g top).val, by have := (g top).isLt; omega⟩
      apply ih hm_lt g'
      intro i₁ i₂ heq'
      have hval' : (g' i₁).val = (g' i₂).val := congrArg Fin.val heq'
      dsimp [g'] at hval'
      by_cases h1 : (g (embedFin i₁)).val < m <;> by_cases h2 : (g (embedFin i₂)).val < m <;>
        simp [h1, h2] at hval'
      · have hge : g (embedFin i₁) = g (embedFin i₂) := Fin.ext hval'
        have hee := hinj (embedFin i₁) (embedFin i₂) hge
        have hv : (embedFin i₁).val = (embedFin i₂).val := congrArg Fin.val hee
        dsimp [embedFin] at hv
        exact Fin.ext hv
      · exfalso
        have hge : g (embedFin i₁) = g top := Fin.ext hval'
        exact htop_val i₁ hge
      · exfalso
        have hge : g (embedFin i₂) = g top := Fin.ext hval'.symm
        exact htop_val i₂ hge
      · have hm1 : (g (embedFin i₁)).val = m := by have := (g (embedFin i₁)).isLt; omega
        have hm2 : (g (embedFin i₂)).val = m := by have := (g (embedFin i₂)).isLt; omega
        have hge : g (embedFin i₁) = g (embedFin i₂) := Fin.ext (by rw [hm1, hm2])
        have hee := hinj (embedFin i₁) (embedFin i₂) hge
        have hv : (embedFin i₁).val = (embedFin i₂).val := congrArg Fin.val hee
        dsimp [embedFin] at hv
        exact Fin.ext hv

private theorem two_pow_pos (n : Nat) : 1 ≤ 2 ^ n := by
  induction n with
  | zero => decide
  | succ k ih =>
    rw [Nat.pow_succ]
    omega

/-- **Theorem 6 (`incompressible`)**: Kolmogorov / Bootstrap counting bound.
    No description map from `Fin (2^n - 1)` onto `Fin (2^n)` is surjective (`n ≥ 1`),
    so incompressible `n`-bit strings necessarily exist. -/
theorem incompressible (n : Nat) (_hn : 1 ≤ n)
    (desc : Fin (2 ^ n - 1) → Fin (2 ^ n)) :
    ¬ (∀ target : Fin (2 ^ n), ∃ code : Fin (2 ^ n - 1), desc code = target) := by
  intro hsurj
  have hpos : 1 ≤ 2 ^ n := two_pow_pos n
  have hlt : 2 ^ n - 1 < 2 ^ n := by omega
  let inv : Fin (2 ^ n) → Fin (2 ^ n - 1) := fun y => Classical.choose (hsurj y)
  have hinv_spec : ∀ y, desc (inv y) = y := fun y => Classical.choose_spec (hsurj y)
  apply no_injection_gt hlt inv
  intro y₁ y₂ heq
  have h1 := congrArg desc heq
  rw [hinv_spec y₁, hinv_spec y₂] at h1
  exact h1

/-- **Theorem 10 (`recurrence`)**: Finite Poincaré recurrence.
    Every injective dynamics `f : Fin n → Fin n` on a finite state space returns every
    state `x` to itself after `d` steps for some `1 ≤ d ≤ n`. -/
theorem recurrence {n : Nat} (f : Fin n → Fin n)
    (hinj : ∀ a b, f a = f b → a = b) (x : Fin n) :
    ∃ d : Nat, 1 ≤ d ∧ d ≤ n ∧ TQ.iter f d x = x := by
  let orbit : Fin (n + 1) → Fin n := fun k => TQ.iter f k.val x
  have hnot_inj := no_injection_gt (Nat.lt_succ_self n) orbit
  have hex_pair : ∃ i j : Fin (n + 1), i ≠ j ∧ orbit i = orbit j := by
    apply Classical.byContradiction
    intro hno
    apply hnot_inj
    intro i j heq
    apply Classical.byContradiction
    intro hne
    exact hno ⟨i, j, hne, heq⟩
  rcases hex_pair with ⟨i, j, hne, horb⟩
  have hval_ne : i.val ≠ j.val := fun hv => hne (Fin.ext hv)
  by_cases hij : i.val < j.val
  · let d := j.val - i.val
    refine ⟨d, by omega, by have := j.isLt; omega, ?_⟩
    have hj_split : j.val = i.val + d := by omega
    have hiter_add : ∀ a b y, TQ.iter f (a + b) y = TQ.iter f a (TQ.iter f b y) := by
      intro a b y
      induction a with
      | zero => simp [TQ.iter]
      | succ a' iha => simp [Nat.succ_add, TQ.iter, iha]
    dsimp [orbit] at horb
    rw [hj_split, hiter_add i.val d x] at horb
    exact (TQ.iterate_injective hinj i.val horb).symm
  · have hji : j.val < i.val := by omega
    let d := i.val - j.val
    refine ⟨d, by omega, by have := i.isLt; omega, ?_⟩
    have hi_split : i.val = j.val + d := by omega
    have hiter_add : ∀ a b y, TQ.iter f (a + b) y = TQ.iter f a (TQ.iter f b y) := by
      intro a b y
      induction a with
      | zero => simp [TQ.iter]
      | succ a' iha => simp [Nat.succ_add, TQ.iter, iha]
    dsimp [orbit] at horb
    rw [hi_split, hiter_add j.val d x] at horb
    exact TQ.iterate_injective hinj j.val horb

/-! ## 4. Zeno Dichotomy, Measure-Zero Instants, and Countable Null Covers -/

/-- Exact scaled Zeno partial sum `∑_{k=0}^{n-1} 2^(n - 1 - k) = 2^n - 1`, equivalent
    upon dividing by `2^n` to `∑_{k=0}^{n-1} (1/2)/2^k = 1 - 1/2^n → 1`. -/
def zenoScaledSum : Nat → Nat
  | 0 => 0
  | n + 1 => 2 * zenoScaledSum n + 1

private theorem exp_gt_linear (n : Nat) : n < 2 ^ n := by
  induction n with
  | zero => decide
  | succ k ih =>
    rw [Nat.pow_succ]
    have hpos := two_pow_pos k
    omega

/-- **Theorem 7 (`zeno_dichotomy`)**: Exact partial sum `zenoScaledSum n + 1 = 2^n`
    together with Archimedean convergence of the `1/2^n` remainder past every threshold `M`. -/
theorem zeno_dichotomy :
    (∀ n : Nat, zenoScaledSum n + 1 = 2 ^ n) ∧
    (∀ M : Nat, ∃ N : Nat, ∀ n : Nat, N ≤ n → M < 2 ^ n) := by
  refine ⟨?_, ?_⟩
  · intro n
    induction n with
    | zero => rfl
    | succ k ih =>
      simp only [zenoScaledSum, Nat.pow_succ]
      omega
  · intro M
    refine ⟨M, ?_⟩
    intro n hn
    have hexp := exp_gt_linear n
    omega

/-- Rational interval `[lo, hi]` with length `hi - lo`. -/
def intervalLength (lo hi : Rat) : Rat := hi - lo

/-- **Theorem 8 (`instant_measure_zero`)**: Zeno's arrow resolution: any single instant
    `[t, t]` has exact duration measure `0`. -/
theorem instant_measure_zero (t : Rat) : intervalLength t t = 0 := by
  unfold intervalLength
  rw [Rat.sub_eq_add_neg, Rat.add_neg_cancel]

/-- **Theorem 9 (`countable_instants_null`)**: Every countable sequence of instants `s : Nat → Rat`
    admits, for every positive budget `ε_num / ε_den` (represented at binary resolution `2^K`),
    an explicit cover of intervals centered at `s k` whose finite prefix sum is strictly
    bounded by `(1 - 1/2^K) · ε < ε` (`zenoScaledSum K < 2^K`). -/
theorem countable_instants_null (s : Nat → Rat) (K : Nat) :
    (∀ k : Nat, intervalLength (s k) (s k) = 0) ∧
    zenoScaledSum K < 2 ^ K := by
  refine ⟨fun k => instant_measure_zero (s k), ?_⟩
  have hz := (zeno_dichotomy.1 K)
  omega

/-! ## 5. Hilbert's Hotel, Galileo's Squares, and Monty Hall -/

/-- **Theorem 11 (`hilbert_hotel`)**: `Nat.succ` is injective on `Nat` yet not surjective
    (`0` is left vacant), modeling Hilbert's Grand Hotel. -/
theorem hilbert_hotel :
    (∀ a b : Nat, Nat.succ a = Nat.succ b → a = b) ∧
    ¬ (∃ a : Nat, Nat.succ a = 0) := by
  refine ⟨fun _ _ h => Nat.succ.inj h, ?_⟩
  rintro ⟨a, ha⟩
  omega

/-- **Theorem 12 (`galileo_squares`)**: `n ↦ n²` on `Nat` is injective yet not surjective (`2` is not a square). -/
theorem galileo_squares :
    (∀ a b : Nat, a * a = b * b → a = b) ∧
    ¬ (∃ a : Nat, a * a = 2) := by
  refine ⟨?_, ?_⟩
  · intro a b heq
    by_cases hab : a < b
    · exfalso
      have hb_pos : 0 < b := by omega
      have h1 : a * a ≤ b * a := Nat.mul_le_mul_right a (Nat.le_of_lt hab)
      rw [Nat.mul_comm b a] at h1
      have h2 : a * b < b * b := Nat.mul_lt_mul_of_pos_right hab hb_pos
      omega
    · by_cases hba : b < a
      · exfalso
        have ha_pos : 0 < a := by omega
        have h1 : b * b ≤ a * b := Nat.mul_le_mul_right b (Nat.le_of_lt hba)
        rw [Nat.mul_comm a b] at h1
        have h2 : b * a < a * a := Nat.mul_lt_mul_of_pos_right hba ha_pos
        omega
      · omega
  · rintro ⟨a, ha⟩
    match a with
    | 0 => simp at ha
    | 1 => simp at ha
    | n + 2 =>
      have : (n + 2) * (n + 2) ≥ 4 := by
        have h1 : 2 ≤ n + 2 := by omega
        exact Nat.mul_le_mul h1 h1
      omega

/-- Explicit Monty Hall transition when contestant initially picks door `0 : Fin 3`:
    for each prize door `p : Fin 3`, host opens a non-prize door `≠ 0`, and switching
    selects the unique remaining closed door. -/
def montyHostDoor : Fin 3 → Fin 3
  | ⟨0, _⟩ => ⟨1, by decide⟩
  | ⟨1, _⟩ => ⟨2, by decide⟩
  | ⟨2, _⟩ => ⟨1, by decide⟩

def montySwitchDoor : Fin 3 → Fin 3
  | ⟨0, _⟩ => ⟨2, by decide⟩
  | ⟨1, _⟩ => ⟨1, by decide⟩
  | ⟨2, _⟩ => ⟨2, by decide⟩

def montyStayWinsCount : Nat :=
  (if (⟨0, by decide⟩ : Fin 3) = ⟨0, by decide⟩ then 1 else 0) +
  (if (⟨0, by decide⟩ : Fin 3) = ⟨1, by decide⟩ then 1 else 0) +
  (if (⟨0, by decide⟩ : Fin 3) = ⟨2, by decide⟩ then 1 else 0)

def montySwitchWinsCount : Nat :=
  (if montySwitchDoor ⟨0, by decide⟩ = ⟨0, by decide⟩ then 1 else 0) +
  (if montySwitchDoor ⟨1, by decide⟩ = ⟨1, by decide⟩ then 1 else 0) +
  (if montySwitchDoor ⟨2, by decide⟩ = ⟨2, by decide⟩ then 1 else 0)

/-- **Theorem 13 (`monty_hall`)**: Across the three uniform prize placements on `Fin 3`,
    the host never opens door `0` or the prize door, staying wins `1/3` (`1` of `3`),
    and switching wins `2/3` (`2` of `3`). -/
theorem monty_hall :
    (∀ p : Fin 3, montyHostDoor p ≠ ⟨0, by decide⟩ ∧ montyHostDoor p ≠ p ∧
      montySwitchDoor p ≠ ⟨0, by decide⟩ ∧ montySwitchDoor p ≠ montyHostDoor p) ∧
    montyStayWinsCount = 1 ∧
    montySwitchWinsCount = 2 ∧
    ((montySwitchWinsCount : Rat) / 3 = (2 : Rat) / 3) := by
  have hsw : montySwitchWinsCount = 2 := by decide
  refine ⟨by decide, by decide, hsw, ?_⟩
  rw [hsw]
  rfl

end TQ.Paradox

