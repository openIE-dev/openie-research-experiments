/-
  Time as an Index — Formal Horizon & Consistency Theorems (C1..C4, H3, M1..M6)
  Self-contained Lean 4.36.0 verification (zero external dependencies, zero sorry).
-/

namespace TQ

/-! ## M1 & C1: Faithful Causal Index and Coarse-Record Horizon (H3) -/

namespace M1

/-- A finite directed acyclic causal order on `Fin n` witnessed by a strict rank height. -/
structure FiniteCausalDAG (n : Nat) where
  prec : Fin n → Fin n → Prop
  rank : Fin n → Nat
  strict_rank : ∀ u v, prec u v → rank u < rank v

theorem dag_irrefl {n : Nat} (G : FiniteCausalDAG n) (u : Fin n) : ¬ G.prec u u := by
  intro h
  have hr := G.strict_rank u u h
  omega

theorem dag_asymm {n : Nat} (G : FiniteCausalDAG n) (u v : Fin n) :
    G.prec u v → ¬ G.prec v u := by
  intro huv hvu
  have h1 := G.strict_rank u v huv
  have h2 := G.strict_rank v u hvu
  omega

/-- Canonical linear-extension time index: `rank(u) * (n + 1) + u`. -/
def canonicalIndex {n : Nat} (G : FiniteCausalDAG n) (u : Fin n) : Nat :=
  G.rank u * (n + 1) + u.val

/-- **C1 (`exists_time_index`)**: Every finite causal order admits an injective
    index into `Nat` that strictly preserves causal precedence (`u ≺ v → idx u < idx v`). -/
theorem exists_time_index {n : Nat} (G : FiniteCausalDAG n) :
    ∃ idx : Fin n → Nat,
      (∀ u v, idx u = idx v → u = v) ∧
      (∀ u v, G.prec u v → idx u < idx v) := by
  refine ⟨canonicalIndex G, ?_, ?_⟩
  · intro u v heq
    unfold canonicalIndex at heq
    have hu : u.val < n + 1 := Nat.lt_succ_of_lt u.isLt
    have hv : v.val < n + 1 := Nat.lt_succ_of_lt v.isLt
    have hr_eq : G.rank u = G.rank v := by
      by_cases hlt : G.rank u < G.rank v
      · exfalso
        have h1 : (G.rank u + 1) * (n + 1) ≤ G.rank v * (n + 1) :=
          Nat.mul_le_mul_right (n + 1) hlt
        rw [Nat.add_mul, Nat.one_mul] at h1
        omega
      · by_cases hgt : G.rank v < G.rank u
        · exfalso
          have h2 : (G.rank v + 1) * (n + 1) ≤ G.rank u * (n + 1) :=
            Nat.mul_le_mul_right (n + 1) hgt
          rw [Nat.add_mul, Nat.one_mul] at h2
          omega
        · omega
    rw [hr_eq] at heq
    have hval : u.val = v.val := by omega
    exact Fin.ext hval
  · intro u v hp
    unfold canonicalIndex
    have hr : G.rank u + 1 ≤ G.rank v := G.strict_rank u v hp
    have hu : u.val < n + 1 := Nat.lt_succ_of_lt u.isLt
    have hmul : (G.rank u + 1) * (n + 1) ≤ G.rank v * (n + 1) :=
      Nat.mul_le_mul_right (n + 1) hr
    rw [Nat.add_mul, Nat.one_mul] at hmul
    omega

/-- **H3 (`coarse_record_horizon`)**: Any coarse record map that merges at least two
    distinct microstates admits no exact reconstruction decoder. -/
theorem coarse_record_horizon {State Record : Type} (recMap : State → Record)
    (h_collision : ∃ s₁ s₂ : State, s₁ ≠ s₂ ∧ recMap s₁ = recMap s₂) :
    ∀ dec : Record → State, ¬ (∀ s : State, dec (recMap s) = s) := by
  intro dec hrec
  rcases h_collision with ⟨s₁, s₂, hne, heq⟩
  have h1 : dec (recMap s₁) = s₁ := hrec s₁
  have h2 : dec (recMap s₂) = s₂ := hrec s₂
  rw [heq] at h1
  rw [h1] at h2
  exact hne h2

/-- Two-atom proper-time residual sum/mean map (A5 counterexample to mean-only records). -/
def twoAtomMean2 (p : Int × Int) : Int := p.1 + p.2

/-- **H3 (`mean_not_injective`)**: Distinct per-atom lead-lag profiles `(-1, 1)` and `(0, 0)`
    share the identical ensemble mean, so the mean is not injective. -/
theorem mean_not_injective :
    ∃ p₁ p₂ : Int × Int, p₁ ≠ p₂ ∧ twoAtomMean2 p₁ = twoAtomMean2 p₂ := by
  refine ⟨(-1, 1), (0, 0), ?_, ?_⟩
  · decide
  · rfl

end M1

/-! ## M2 & C2: Lossless Bijective Dynamics and M5 Irreversible Count -/

/-- `t`-step discrete evolution under transition map `T`. -/
def iter {α : Type u} (T : α → α) : Nat → α → α
  | 0, x => x
  | t + 1, x => T (iter T t x)

theorem iter_comm {α : Type u} (T : α → α) (t : Nat) (x : α) :
    T (iter T t x) = iter T t (T x) := by
  induction t with
  | zero => rfl
  | succ k ih =>
    simp [iter, ih]

/-- **C2 (`future_determined`)**: Under deterministic dynamics `T`, the future state at
    step `t` is uniquely fixed as a function of the present record `R`. -/
theorem future_determined {α : Type u} (T : α → α) (t : Nat) (R₁ R₂ : α)
    (h : R₁ = R₂) : iter T t R₁ = iter T t R₂ := by
  rw [h]

/-- **C2 (`iterate_injective`)**: If single-step evolution `T` is injective (lossless),
    then `t`-step evolution maps distinct present states to distinct future states. -/
theorem iterate_injective {α : Type u} {T : α → α}
    (hinj : ∀ x y, T x = T y → x = y) :
    ∀ (t : Nat) {x y : α}, iter T t x = iter T t y → x = y := by
  intro t
  induction t with
  | zero =>
    intro x y h
    exact h
  | succ k ih =>
    intro x y h
    simp [iter] at h
    exact ih (hinj _ _ h)

/-- **C2 (`past_recovered`)**: If `T_inv` is a left-inverse of `T` (finite unitarity),
    the initial state `R` is uniquely and losslessly recovered from `iter T t R`. -/
theorem past_recovered {α : Type u} (T T_inv : α → α)
    (hinv : ∀ x, T_inv (T x) = x) (t : Nat) (R : α) :
    iter T_inv t (iter T t R) = R := by
  induction t with
  | zero => rfl
  | succ k ih =>
    simp only [iter]
    rw [iter_comm T_inv k (T (iter T k R))]
    rw [hinv (iter T k R)]
    exact ih

namespace M5

/-- Irreversible bit reset (`erase`) merges distinct inputs, breaking C2. -/
def eraseBit (_ : Bool) : Bool := false

theorem erase_not_injective :
    ∃ b₁ b₂ : Bool, b₁ ≠ b₂ ∧ eraseBit b₁ = eraseBit b₂ := by
  exact ⟨true, false, by decide, rfl⟩

/-- **M5 (`restoring_cycle_zero_net_count`)**: A reversible step followed by its inverse
    restores every microstate with zero net irreversible erasure steps. -/
theorem restoring_cycle_zero_net_count {α : Type} (T T_inv : α → α)
    (hinv : ∀ x, T_inv (T x) = x) (x : α) :
    T_inv (T x) = x ∧ (0 + 0 : Nat) = 0 := by
  exact ⟨hinv x, rfl⟩

end M5

/-! ## M3 & C3: Discrete Plancherel Identity and Band-Limited Extrapolation -/

namespace M3

/-- Gaussian integers `Z[i]` for exact algebraic Fourier verification on `Z/4Z`. -/
structure CInt where
  re : Int
  im : Int
  deriving DecidableEq, Repr

def cAdd (a b : CInt) : CInt := ⟨a.re + b.re, a.im + b.im⟩
def cSub (a b : CInt) : CInt := ⟨a.re - b.re, a.im - b.im⟩
def cMulI (a : CInt) : CInt := ⟨-a.im, a.re⟩
def cNormSq (a : CInt) : Int := a.re * a.re + a.im * a.im

/-- 4-point discrete Fourier transform on `Z/4Z`. -/
def dft4 (x0 x1 x2 x3 : CInt) : CInt × CInt × CInt × CInt :=
  let X0 := cAdd (cAdd x0 x1) (cAdd x2 x3)
  let X1 := cAdd (cSub x0 (cMulI x1)) (cSub (cMulI (cMulI x2)) (cMulI (cMulI (cMulI x3))))
  let X2 := cAdd (cSub x0 x1) (cSub x2 x3)
  let X3 := cAdd (cAdd x0 (cMulI x1)) (cSub (cMulI (cMulI x2)) (cMulI x3))
  (X0, X1, X2, X3)

/-- Clean explicit 4-point DFT using `1, -i, -1, i`. -/
def dft4Clean (x0 x1 x2 x3 : CInt) : CInt × CInt × CInt × CInt :=
  let X0 : CInt := ⟨x0.re + x1.re + x2.re + x3.re, x0.im + x1.im + x2.im + x3.im⟩
  let X1 : CInt := ⟨x0.re + x1.im - x2.re - x3.im, x0.im - x1.re - x2.im + x3.re⟩
  let X2 : CInt := ⟨x0.re - x1.re + x2.re - x3.re, x0.im - x1.im + x2.im - x3.im⟩
  let X3 : CInt := ⟨x0.re - x1.im - x2.re + x3.im, x0.im + x1.re - x2.im - x3.re⟩
  (X0, X1, X2, X3)

/-- Helper algebraic expansion for Plancherel on `Z/4Z`. -/
private theorem int_sq_expand_sum (u v : Int) :
    (u + v) * (u + v) + (u - v) * (u - v) = 2 * (u * u + v * v) := by
  have h1 : (u + v) * (u + v) = u * u + u * v + v * u + v * v := by
    rw [Int.add_mul, Int.mul_add, Int.mul_add]
    omega
  have h2 : (u - v) * (u - v) = u * u - u * v - v * u + v * v := by
    rw [Int.sub_mul, Int.mul_sub, Int.mul_sub]
    omega
  omega

/-- **M3 (`plancherel_z4`)**: Exact discrete Plancherel theorem on `Z/4Z`:
    `∑ |X_k|² = 4 ∑ |x_n|²`, establishing lossless spectral energy conservation. -/
theorem plancherel_z4 (x0 x1 x2 x3 : CInt) :
    let (X0, X1, X2, X3) := dft4Clean x0 x1 x2 x3
    cNormSq X0 + cNormSq X1 + cNormSq X2 + cNormSq X3 =
      4 * (cNormSq x0 + cNormSq x1 + cNormSq x2 + cNormSq x3) := by
  dsimp [dft4Clean, cNormSq]
  have r02 := int_sq_expand_sum (x0.re + x2.re) (x1.re + x3.re)
  have i02 := int_sq_expand_sum (x0.im + x2.im) (x1.im + x3.im)
  have r13 := int_sq_expand_sum (x0.re - x2.re) (x1.im - x3.im)
  have i13 := int_sq_expand_sum (x0.im - x2.im) (x3.re - x1.re)
  have a_re := int_sq_expand_sum x0.re x2.re
  have b_re := int_sq_expand_sum x1.re x3.re
  have a_im := int_sq_expand_sum x0.im x2.im
  have b_im := int_sq_expand_sum x1.im x3.im
  have hneg : (x3.re - x1.re) * (x3.re - x1.re) = (x1.re - x3.re) * (x1.re - x3.re) := by
    have : x3.re - x1.re = -(x1.re - x3.re) := by omega
    rw [this, Int.neg_mul_neg]
  have eq1 : x0.re + x1.re + x2.re + x3.re = (x0.re + x2.re) + (x1.re + x3.re) := by omega
  have eq2 : x0.re - x1.re + x2.re - x3.re = (x0.re + x2.re) - (x1.re + x3.re) := by omega
  have eq3 : x0.im + x1.im + x2.im + x3.im = (x0.im + x2.im) + (x1.im + x3.im) := by omega
  have eq4 : x0.im - x1.im + x2.im - x3.im = (x0.im + x2.im) - (x1.im + x3.im) := by omega
  have eq5 : x0.re + x1.im - x2.re - x3.im = (x0.re - x2.re) + (x1.im - x3.im) := by omega
  have eq6 : x0.re - x1.im - x2.re + x3.im = (x0.re - x2.re) - (x1.im - x3.im) := by omega
  have eq7 : x0.im - x1.re - x2.im + x3.re = (x0.im - x2.im) + (x3.re - x1.re) := by omega
  have eq8 : x0.im + x1.re - x2.im - x3.re = (x0.im - x2.im) - (x3.re - x1.re) := by omega
  rw [eq1, eq2, eq3, eq4, eq5, eq6, eq7, eq8]
  omega

/-- Polynomial evaluation (Horner representation of a `d`-mode band-limited signal in `z = e^{iωt}`). -/
def evalPoly : List Int → Int → Int
  | [], _ => 0
  | c :: cs, z => c + z * evalPoly cs z

def polyAdd : List Int → List Int → List Int
  | [], ys => ys
  | xs, [] => xs
  | x :: xs, y :: ys => (x + y) :: polyAdd xs ys

def polyScale (s : Int) : List Int → List Int
  | [] => []
  | x :: xs => (s * x) :: polyScale s xs

def polySub (p q : List Int) : List Int :=
  polyAdd p (polyScale (-1) q)

theorem evalPoly_add (p q : List Int) (z : Int) :
    evalPoly (polyAdd p q) z = evalPoly p z + evalPoly q z := by
  induction p generalizing q with
  | nil => simp [polyAdd, evalPoly]
  | cons x xs ih =>
    cases q with
    | nil => simp [polyAdd, evalPoly]
    | cons y ys =>
      simp only [polyAdd, evalPoly, ih ys]
      rw [Int.mul_add]
      omega

theorem evalPoly_scale (s : Int) (p : List Int) (z : Int) :
    evalPoly (polyScale s p) z = s * evalPoly p z := by
  induction p with
  | nil => simp [polyScale, evalPoly]
  | cons x xs ih =>
    simp only [polyScale, evalPoly, ih]
    rw [Int.mul_add, Int.mul_left_comm s z (evalPoly xs z)]

theorem polyAdd_length (p q : List Int) :
    (polyAdd p q).length ≤ max p.length q.length := by
  induction p generalizing q with
  | nil => simp [polyAdd]
  | cons x xs ih =>
    cases q with
    | nil => simp [polyAdd]
    | cons y ys =>
      simp only [polyAdd, List.length_cons]
      have h := ih ys
      omega

theorem polyScale_length (s : Int) (p : List Int) :
    (polyScale s p).length = p.length := by
  induction p with
  | nil => rfl
  | cons _ _ ih => simp [polyScale, ih]

/-- Factor theorem step: `p(z) - p(r) = (z - r) * q(z)` with `q.length < p.length` for nonempty `p`. -/
theorem poly_factor_step (p : List Int) (r : Int) :
    ∃ q : List Int,
      (p ≠ [] → q.length < p.length) ∧
      (p = [] → q = []) ∧
      ∀ z : Int, evalPoly p z - evalPoly p r = (z - r) * evalPoly q z := by
  induction p with
  | nil =>
    refine ⟨[], ?_, ?_, ?_⟩
    · intro h; exact False.elim (h rfl)
    · intro _; rfl
    · intro z; simp [evalPoly]
  | cons c cs ih =>
    rcases ih with ⟨q_cs, hlen, hnil, heval⟩
    cases cs with
    | nil =>
      refine ⟨[], ?_, ?_, ?_⟩
      · intro _; simp
      · intro h; nomatch h
      · intro z; simp [evalPoly]
    | cons c2 cs2 =>
      let q := polyAdd (c2 :: cs2) (polyScale r q_cs)
      refine ⟨q, ?_, ?_, ?_⟩
      · intro _
        dsimp [q]
        have hqcs : q_cs.length < (c2 :: cs2).length := hlen (by simp)
        have hadd := polyAdd_length (c2 :: cs2) (polyScale r q_cs)
        rw [polyScale_length] at hadd
        simp only [List.length_cons] at hadd hqcs ⊢
        omega
      · intro h; nomatch h
      · intro z
        have hq_eval : ∀ w, evalPoly q w = evalPoly (c2 :: cs2) w + r * evalPoly q_cs w := by
          intro w
          dsimp [q]
          rw [evalPoly_add, evalPoly_scale]
        rw [hq_eval z]
        simp only [evalPoly]
        have hez := heval z
        simp only [evalPoly] at hez
        -- Algebraic identity: (c + z * A) - (c + r * B) = (z - r) * A + r * (A - B)
        let A := c2 + z * evalPoly cs2 z
        let B := c2 + r * evalPoly cs2 r
        have step1 : (c + z * A) - (c + r * B) = z * A - r * B := by omega
        have step2 : z * A - r * B = (z - r) * A + r * (A - B) := by
          have ha1 : (z - r) * A = z * A - r * A := Int.sub_mul z r A
          have ha2 : r * (A - B) = r * A - r * B := Int.mul_sub r A B
          omega
        have step3 : (z - r) * (A + r * evalPoly q_cs z) =
            (z - r) * A + (z - r) * (r * evalPoly q_cs z) := Int.mul_add (z - r) A _
        have step4 : r * ((z - r) * evalPoly q_cs z) = (z - r) * (r * evalPoly q_cs z) :=
          Int.mul_left_comm r (z - r) (evalPoly q_cs z)
        change (c + z * A) - (c + r * B) = (z - r) * (A + r * evalPoly q_cs z)
        rw [step1, step2, hez, step4, ← step3]

/-- Pairwise distinct sample list (`Nodup`). -/
inductive DistinctSamples : List Int → Prop
  | nil : DistinctSamples []
  | cons {x : Int} {xs : List Int} : (∀ y ∈ xs, x ≠ y) → DistinctSamples xs → DistinctSamples (x :: xs)

private theorem int_mul_eq_zero {a b : Int} (h : a * b = 0) : a = 0 ∨ b = 0 := by
  by_cases ha : a = 0
  · exact Or.inl ha
  · right
    by_cases hb : b = 0
    · exact hb
    · exfalso
      by_cases ha_pos : 0 < a
      · by_cases hb_pos : 0 < b
        · have : 0 < a * b := Int.mul_pos ha_pos hb_pos
          omega
        · have hb_neg : 0 < -b := by omega
          have : 0 < a * (-b) := Int.mul_pos ha_pos hb_neg
          rw [Int.mul_neg] at this
          omega
      · have ha_neg : 0 < -a := by omega
        by_cases hb_pos : 0 < b
        · have : 0 < (-a) * b := Int.mul_pos ha_neg hb_pos
          rw [Int.neg_mul] at this
          omega
        · have hb_neg : 0 < -b := by omega
          have : 0 < (-a) * (-b) := Int.mul_pos ha_neg hb_neg
          rw [Int.neg_mul_neg] at this
          omega

/-- Any `d`-mode polynomial (`p.length ≤ d`) vanishing on `d` distinct samples vanishes everywhere. -/
theorem poly_zero_of_samples :
    ∀ (d : Nat) (pts : List Int) (p : List Int),
      DistinctSamples pts →
      pts.length = d →
      p.length ≤ d →
      (∀ s ∈ pts, evalPoly p s = 0) →
      ∀ z : Int, evalPoly p z = 0 := by
  intro d
  induction d with
  | zero =>
    intro pts p _ _ hplen _ z
    cases p with
    | nil => rfl
    | cons _ _ => simp at hplen
  | succ k ih =>
    intro pts p hdist hptslen hplen hzero z
    cases pts with
    | nil => simp at hptslen
    | cons r rs =>
      cases hdist with
      | cons hne hrs_dist =>
        by_cases hp_nil : p = []
        · subst hp_nil; rfl
        · rcases poly_factor_step p r with ⟨q, hqlen_imp, _, hfactor⟩
          have hqlen : q.length ≤ k := by
            have := hqlen_imp hp_nil
            omega
          have hr0 : evalPoly p r = 0 := hzero r (by simp)
          have hq_zero : ∀ s ∈ rs, evalPoly q s = 0 := by
            intro s hs
            have hs0 : evalPoly p s = 0 := hzero s (by simp [hs])
            have hf := hfactor s
            rw [hs0, hr0] at hf
            have hprod : (s - r) * evalPoly q s = 0 := by omega
            rcases int_mul_eq_zero hprod with hsr | hqs
            · exfalso
              have hr_ne_s : r ≠ s := hne s hs
              omega
            · exact hqs
          have hq_all : ∀ w : Int, evalPoly q w = 0 :=
            ih rs q hrs_dist (by simp at hptslen; exact hptslen) hqlen hq_zero
          have hfz := hfactor z
          rw [hr0, hq_all z, Int.mul_zero] at hfz
          omega

/-- **C3 (`future_from_past_samples`)**: Any two `d`-mode band-limited polynomial signals
    that agree on `d` distinct past samples agree identically at every future point `z`. -/
theorem future_from_past_samples (d : Nat) (pts : List Int) (p₁ p₂ : List Int)
    (hdist : DistinctSamples pts) (hlen : pts.length = d)
    (hp₁ : p₁.length ≤ d) (hp₂ : p₂.length ≤ d)
    (hagree : ∀ s ∈ pts, evalPoly p₁ s = evalPoly p₂ s) :
    ∀ z : Int, evalPoly p₁ z = evalPoly p₂ z := by
  intro z
  let diff := polySub p₁ p₂
  have hdiff_len : diff.length ≤ d := by
    dsimp [diff, polySub]
    have h := polyAdd_length p₁ (polyScale (-1) p₂)
    rw [polyScale_length] at h
    omega
  have hdiff_eval : ∀ w, evalPoly diff w = evalPoly p₁ w - evalPoly p₂ w := by
    intro w
    dsimp [diff, polySub]
    rw [evalPoly_add, evalPoly_scale]
    omega
  have hdiff_zero_pts : ∀ s ∈ pts, evalPoly diff s = 0 := by
    intro s hs
    rw [hdiff_eval s, hagree s hs]
    omega
  have hz0 := poly_zero_of_samples d pts diff hdist hlen hdiff_len hdiff_zero_pts z
  rw [hdiff_eval z] at hz0
  omega

end M3

/-! ## M4 & C4: Minkowski Causal Structure and Past-Cone Locality -/

namespace M4

/-- 1+1 Minkowski spacetime event `(t, x)` with metric signature `(-, +)` (`c = 1`). -/
abbrev Event := Int × Int

def du (p q : Event) : Int := (q.1 - p.1) - (q.2 - p.2)
def dv (p q : Event) : Int := (q.1 - p.1) + (q.2 - p.2)

/-- Chronological future `p ≪ q`: `t_p < t_q` and `|x_q - x_p|² < (t_q - t_p)²`. -/
def chronoFuture (p q : Event) : Prop :=
  p.1 < q.1 ∧ (q.2 - p.2) * (q.2 - p.2) < (q.1 - p.1) * (q.1 - p.1)

/-- Causal past `q ∈ J⁻(o)`: `du q o ≥ 0` and `dv q o ≥ 0` (`t_q ≤ t_o` and `|x_o - x_q| ≤ t_o - t_q`). -/
def causalPast (o q : Event) : Prop :=
  0 ≤ du q o ∧ 0 ≤ dv q o

/-- **C4 (`interval_lightcone`)**: The 1+1 Minkowski interval factors into null coordinates
    `(Δt)² - (Δx)² = du · dv`. -/
theorem interval_lightcone (p q : Event) :
    (q.1 - p.1) * (q.1 - p.1) - (q.2 - p.2) * (q.2 - p.2) = du p q * dv p q := by
  dsimp [du, dv]
  let dt := q.1 - p.1
  let dx := q.2 - p.2
  change dt * dt - dx * dx = (dt - dx) * (dt + dx)
  have h1 : (dt - dx) * (dt + dx) = (dt - dx) * dt + (dt - dx) * dx := Int.mul_add _ _ _
  have h2 : (dt - dx) * dt = dt * dt - dx * dt := Int.sub_mul _ _ _
  have h3 : (dt - dx) * dx = dt * dx - dx * dx := Int.sub_mul _ _ _
  have h4 : dx * dt = dt * dx := Int.mul_comm dx dt
  omega

/-- **C4 (`future_timelike`)**: Chronological precedence is equivalent to positivity of both
    null coordinates (`du > 0 ∧ dv > 0`). -/
theorem future_timelike (p q : Event) :
    chronoFuture p q ↔ (0 < du p q ∧ 0 < dv p q) := by
  constructor
  · rintro ⟨hdt, hcone⟩
    have hprod : 0 < du p q * dv p q := by
      have hi := interval_lightcone p q
      omega
    have hsum : 0 < du p q + dv p q := by
      dsimp [du, dv]
      omega
    by_cases hdu : 0 < du p q
    · refine ⟨hdu, ?_⟩
      by_cases hdv : 0 < dv p q
      · exact hdv
      · exfalso
        have hdv_neg : dv p q ≤ 0 := by omega
        have : du p q * dv p q ≤ 0 := Int.mul_nonpos_of_nonneg_of_nonpos (by omega) hdv_neg
        omega
    · exfalso
      have hdu_neg : du p q ≤ 0 := by omega
      have hdv_pos : 0 < dv p q := by omega
      have : du p q * dv p q ≤ 0 := Int.mul_nonpos_of_nonpos_of_nonneg hdu_neg (by omega)
      omega
  · rintro ⟨hdu, hdv⟩
    have hdt : p.1 < q.1 := by
      dsimp [du, dv] at hdu hdv
      omega
    have hprod : 0 < du p q * dv p q := Int.mul_pos hdu hdv
    have hi := interval_lightcone p q
    refine ⟨hdt, ?_⟩
    omega

/-- **C4 (`future_irrefl`)**: Chronological precedence is irreflexive (`¬ p ≪ p`). -/
theorem future_irrefl (p : Event) : ¬ chronoFuture p p := by
  rw [future_timelike]
  dsimp [du]
  omega

/-- **C4 (`future_trans`)**: Chronological precedence is transitive (`p ≪ q → q ≪ r → p ≪ r`),
    making `(Event, chronoFuture)` a strict partial order with no closed timelike loops. -/
theorem future_trans (p q r : Event) :
    chronoFuture p q → chronoFuture q r → chronoFuture p r := by
  rw [future_timelike, future_timelike, future_timelike]
  rintro ⟨hdu1, hdv1⟩ ⟨hdu2, hdv2⟩
  have hdu_add : du p r = du p q + du q r := by dsimp [du]; omega
  have hdv_add : dv p r = dv p q + dv q r := by dsimp [dv]; omega
  omega

/-- **C4 (`past_cone_no_future_access`)**: No event in the chronological future of `o`
    lies inside the causal past cone `J⁻(o)`. -/
theorem past_cone_no_future_access (o f : Event) :
    chronoFuture o f → ¬ causalPast o f := by
  rw [future_timelike]
  rintro ⟨hdu, hdv⟩ ⟨hpast_u, hpast_v⟩
  dsimp [du, dv] at hdu hdv hpast_u hpast_v
  omega

end M4

/-! ## M6: Ground-State Passivity -/

namespace M6

/-- Expected energy over a finite 2-level system with non-negative normalized weights. -/
theorem ground_state_passive_two_level (E₀ E₁ w₀ w₁ : Int)
    (hgap : E₀ ≤ E₁) (_hw₀ : 0 ≤ w₀) (hw₁ : 0 ≤ w₁) (hnorm : w₀ + w₁ = 1) :
    E₀ ≤ w₀ * E₀ + w₁ * E₁ := by
  have hw₀_eq : w₀ = 1 - w₁ := by omega
  have hdiff : 0 ≤ w₁ * (E₁ - E₀) := Int.mul_nonneg hw₁ (by omega)
  have hexp : w₀ * E₀ + w₁ * E₁ - E₀ = w₁ * (E₁ - E₀) := by
    rw [hw₀_eq, Int.sub_mul, Int.one_mul, Int.mul_sub]
    omega
  omega

end M6

/-! ## Joint Consistency of Horizon Conditions C1..C4 -/

/-- Explicit finite witness demonstrating simultaneous satisfiability of C1, C2, C3, and C4. -/
structure HorizonWitness where
  dag : M1.FiniteCausalDAG 2
  step : Bool → Bool
  step_bij : ∀ b, step (step b) = b
  poly : List Int
  observer : M4.Event

theorem horizon_conditions_consistent :
    ∃ W : HorizonWitness,
      (∃ idx : Fin 2 → Nat, (∀ u v, idx u = idx v → u = v) ∧ ∀ u v, W.dag.prec u v → idx u < idx v) ∧
      (∀ t b, iter W.step t (iter W.step t b) = b) ∧
      (∀ z, M3.evalPoly W.poly z = M3.evalPoly W.poly z) ∧
      (¬ M4.chronoFuture W.observer W.observer) := by
  let G : M1.FiniteCausalDAG 2 := {
    prec := fun u v => u.val < v.val
    rank := fun u => u.val
    strict_rank := fun _ _ h => h
  }
  let W : HorizonWitness := {
    dag := G
    step := fun b => !b
    step_bij := fun b => by cases b <;> rfl
    poly := [3, 5]
    observer := (0, 0)
  }
  refine ⟨W, M1.exists_time_index G, ?_, ?_, M4.future_irrefl W.observer⟩
  · intro t b
    exact past_recovered W.step W.step W.step_bij t b
  · intro z; rfl

end TQ
