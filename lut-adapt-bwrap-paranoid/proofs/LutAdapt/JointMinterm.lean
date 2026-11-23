/-
  LutAdapt/JointMinterm.lean
  Section 2.3 (Proposition 3): Joint-Mode Minterm Dominance, Zero Off-Support Chimeras,
  and Lossless `≤ 64`-Bit BPE Token Packing.
  Author: David Charlot, Open Interface Engineering
  License: Apache-2.0 / MIT
  Zero `sorry`, zero custom axioms.
-/

namespace LutAdapt.JointMinterm

/-- Maximum empirical count across indices `0 .. n` for a discrete burst histogram `w : Nat → Nat`. -/
def argmaxUpTo (w : Nat → Nat) : Nat → Nat
  | 0 => 0
  | k + 1 =>
      let prev := argmaxUpTo w k
      if w prev < w (k + 1) then k + 1 else prev

/--
  **Proposition 3a (Joint-Mode Dominance Over Arbitrary Predictors, Section 2.3)**:
  For every burst index `y ≤ maxIdx` (in particular `y = y_marg`, the coordinatewise marginal
  DiffLogic rounding), the joint-mode entry `T* = argmaxUpTo w maxIdx` satisfies `w y ≤ w T*`.
-/
theorem joint_mode_dominates_all (w : Nat → Nat) (maxIdx : Nat) :
    ∀ y, y ≤ maxIdx → w y ≤ w (argmaxUpTo w maxIdx) := by
  induction maxIdx with
  | zero =>
    intro y hy
    have hy0 : y = 0 := by omega
    subst hy0
    exact Nat.le_refl _
  | succ k ih =>
    intro y hy
    simp only [argmaxUpTo]
    split
    · next hlt =>
      cases Nat.eq_or_lt_of_le hy with
      | inl heq =>
        subst heq
        exact Nat.le_refl _
      | inr hlt_y =>
        have hprev := ih y (Nat.le_of_lt_succ hlt_y)
        omega
    · next hge =>
      cases Nat.eq_or_lt_of_le hy with
      | inl heq =>
        subst heq
        omega
      | inr hlt_y =>
        exact ih y (Nat.le_of_lt_succ hlt_y)

/--
  **Proposition 3b (Zero Off-Support Chimera Guarantee, Section 2.3)**:
  Whenever at least one valid burst `y0 ≤ maxIdx` has positive empirical frequency `0 < w y0`,
  the joint-mode minterm `T* = argmaxUpTo w maxIdx` strictly stays inside the empirical support
  (`0 < w T*`), never emitting a zero-probability chimera token.
-/
theorem joint_mode_in_support (w : Nat → Nat) (maxIdx y0 : Nat)
    (hy0 : y0 ≤ maxIdx) (hpos : 0 < w y0) :
    0 < w (argmaxUpTo w maxIdx) := by
  have hdom := joint_mode_dominates_all w maxIdx y0 hy0
  omega

/--
  Concrete 3-bit correlated-branch distribution from Section 2.3 (`0..7` encoding `(b2, b1, b0)`):
    `(1,1,0) = 6` has weight `40` (`0.40`),
    `(1,0,1) = 5` has weight `35` (`0.35`),
    `(0,1,1) = 3` has weight `25` (`0.25`),
    all other 3-bit words (including `(1,1,1) = 7`) have weight `0`.
-/
def chimeraHist : Nat → Nat
  | 6 => 40
  | 5 => 35
  | 3 => 25
  | _ => 0

/-- Marginal bit-1 weight sum for bit plane `b ∈ {0, 1, 2}` across `0..7`. -/
def marginalBitMass (w : Nat → Nat) (bitPos : Nat) : Nat :=
  (List.range 8).foldl (fun acc y => if ((y >>> bitPos) &&& 1) == 1 then acc + w y else acc) 0

/-- Coordinatewise marginal rounding (`> 50` out of `100` total mass). -/
def marginalArgmax3Bit (w : Nat → Nat) : Nat :=
  (if 50 < marginalBitMass w 0 then 1 else 0) +
  (if 50 < marginalBitMass w 1 then 2 else 0) +
  (if 50 < marginalBitMass w 2 then 4 else 0)

/--
  **Proposition 3c (Constructive Chimera Witness, Section 2.3)**:
  On `chimeraHist`, independent bit-plane rounding evaluates marginal masses `(60, 65, 75) > 50`
  and emits off-support chimera `7 = (1,1,1)` with exact-match weight `0`, whereas `argmaxUpTo`
  emits in-support `6 = (1,1,0)` with exact-match weight `40`.
-/
theorem marginal_chimera_witness :
    marginalBitMass chimeraHist 0 = 60 ∧
    marginalBitMass chimeraHist 1 = 65 ∧
    marginalBitMass chimeraHist 2 = 75 ∧
    marginalArgmax3Bit chimeraHist = 7 ∧
    chimeraHist (marginalArgmax3Bit chimeraHist) = 0 ∧
    argmaxUpTo chimeraHist 7 = 6 ∧
    chimeraHist (argmaxUpTo chimeraHist 7) = 40 := by
  decide

/-- Pack `K` `b`-bit token IDs (each `< 2^b`) into one unsigned integer word. -/
def packTokens (b : Nat) : List Nat → Nat
  | [] => 0
  | tok :: rest => (tok % (2 ^ b)) + (2 ^ b) * packTokens b rest

/-- Unpack `K` `b`-bit token IDs from an integer word. -/
def unpackTokens (b : Nat) : Nat → Nat → List Nat
  | 0, _ => []
  | k + 1, word => (word % (2 ^ b)) :: unpackTokens b k (word / (2 ^ b))

theorem packTokens_bound (b : Nat) (toks : List Nat) :
    packTokens b toks < 2 ^ (b * toks.length) := by
  induction toks with
  | nil =>
    simp [packTokens]
  | cons tok rest ih =>
    simp only [packTokens, List.length_cons]
    have hB : 0 < 2 ^ b := Nat.two_pow_pos b
    have hmod : tok % (2 ^ b) < 2 ^ b := Nat.mod_lt tok hB
    have hpow : 2 ^ (b * (rest.length + 1)) = (2 ^ b) * (2 ^ (b * rest.length)) := by
      rw [Nat.mul_add, Nat.mul_one, Nat.pow_add, Nat.mul_comm]
    rw [hpow]
    have hle : packTokens b rest + 1 ≤ 2 ^ (b * rest.length) := ih
    have hmul : (2 ^ b) * (packTokens b rest + 1) ≤ (2 ^ b) * (2 ^ (b * rest.length)) :=
      Nat.mul_le_mul_left (2 ^ b) hle
    rw [Nat.mul_add, Nat.mul_one] at hmul
    omega

/--
  **Proposition 3d (Lossless `K`-Token Bit-Packing Bijection & `uint64` Fit)**:
  Whenever every token ID satisfies `tok < 2^b`, `unpackTokens b toks.length (packTokens b toks) = toks`,
  and if `b * toks.length ≤ 64` then `packTokens b toks < 2^64` (fits in a single `uint64` word).
-/
theorem unpack_pack_roundtrip (b : Nat) (toks : List Nat)
    (hvalid : ∀ t ∈ toks, t < 2 ^ b) :
    unpackTokens b toks.length (packTokens b toks) = toks := by
  induction toks with
  | nil => rfl
  | cons tok rest ih =>
    simp only [List.length_cons, packTokens, unpackTokens]
    have hB : 0 < 2 ^ b := Nat.two_pow_pos b
    have htok : tok < 2 ^ b := hvalid tok (List.Mem.head rest)
    have hrest : ∀ t ∈ rest, t < 2 ^ b := fun t ht => hvalid t (List.Mem.tail tok ht)
    have hmod_tok : tok % (2 ^ b) = tok := Nat.mod_eq_of_lt htok
    rw [hmod_tok]
    have h_div : (tok + (2 ^ b) * packTokens b rest) / (2 ^ b) = packTokens b rest := by
      rw [Nat.add_mul_div_left tok (packTokens b rest) hB, Nat.div_eq_of_lt htok, Nat.zero_add]
    have h_mod : (tok + (2 ^ b) * packTokens b rest) % (2 ^ b) = tok := by
      rw [Nat.add_mul_mod_self_left, hmod_tok]
    rw [h_mod, h_div, ih hrest]

theorem packTokens_fits_uint64 (b : Nat) (toks : List Nat) (hfit : b * toks.length ≤ 64) :
    packTokens b toks < 2 ^ 64 := by
  have hlt := packTokens_bound b toks
  have hmono : 2 ^ (b * toks.length) ≤ 2 ^ 64 := Nat.pow_le_pow_right (by omega) hfit
  exact Nat.lt_of_lt_of_le hlt hmono

/--
  **Exact 2026 Checkpoint `uint64` Burst Capacities (Claims LA-7 & LA-9)**:
  - `LiquidAI/LFM2.5-350M` (`|V| = 65,536 ≤ 2^16`): `K = 4` tokens (`16 * 4 = 64 ≤ 64`)
  - `LiquidAI/LFM3-1.7B` (`|V| = 128,000 ≤ 2^17`): `K = 3` tokens (`17 * 3 = 51 ≤ 64`)
  - `Qwen/Qwen3.5` & `Qwen/Qwen3.6-35B-A3B` (`|V| = 248,320 ≤ 2^18`): `K = 3` tokens (`18 * 3 = 54 ≤ 64`)
-/
theorem hf_2026_vocab_uint64_packing_bounds :
    (65536 ≤ 2 ^ 16 ∧ 16 * 4 ≤ 64) ∧
    (128000 ≤ 2 ^ 17 ∧ 17 * 3 ≤ 64) ∧
    (248320 ≤ 2 ^ 18 ∧ 18 * 3 ≤ 64) := by
  decide

end LutAdapt.JointMinterm
