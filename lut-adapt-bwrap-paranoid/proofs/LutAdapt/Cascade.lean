/-
  LutAdapt/Cascade.lean
  Section 2.1 (Result 1): Simon–Kadane Cascade Ordering & Amortized Downward LUT6 Compilation.
  Author: David Charlot, Open Interface Engineering
  License: Apache-2.0 / MIT
  Zero `sorry`, zero custom axioms.
-/

namespace LutAdapt.Cascade

/--
  Two-gear expected analytical spend scaled by probability denominator `B > 0`
  (where `p1, p2 ∈ [0, B]` represent `p_i * B` so all arithmetic is exact over `Int`):
    `B * E[J_(1,2)] = B * c1 + (B - p1) * c2`.
-/
def twoGearScaledSpend (B p1 c1 _p2 c2 : Int) : Int :=
  B * c1 + (B - p1) * c2

/--
   Exact difference between running gear 2 first vs. gear 1 first:
   `twoGearScaledSpend B p2 c2 p1 c1 - twoGearScaledSpend B p1 c1 p2 c2 = p1 * c2 - p2 * c1`.
-/
theorem simon_kadane_two_gear_diff (B p1 c1 p2 c2 : Int) :
    twoGearScaledSpend B p2 c2 p1 c1 - twoGearScaledSpend B p1 c1 p2 c2 =
      p1 * c2 - p2 * c1 := by
  unfold twoGearScaledSpend
  rw [Int.sub_mul, Int.sub_mul]
  omega

/--
  **Simon–Kadane Adjacent Ordering Optimality (Section 2.1)**:
  Ordering gear 1 ahead of gear 2 achieves less-or-equal expected spend than `(2, 1)`
  if and only if `p1 * c2 ≥ p2 * c1` (i.e., `p1 / c1 ≥ p2 / c2` for `c1, c2 > 0`).
-/
theorem simon_kadane_adjacent_swap_iff (B p1 c1 p2 c2 : Int) :
    twoGearScaledSpend B p1 c1 p2 c2 ≤ twoGearScaledSpend B p2 c2 p1 c1 ↔
      p2 * c1 ≤ p1 * c2 := by
  have h := simon_kadane_two_gear_diff B p1 c1 p2 c2
  omega

/--
  Strict Simon–Kadane ordering improvement whenever `p1 / c1 > p2 / c2`.
-/
theorem simon_kadane_strict_iff (B p1 c1 p2 c2 : Int) :
    twoGearScaledSpend B p1 c1 p2 c2 < twoGearScaledSpend B p2 c2 p1 c1 ↔
      p2 * c1 < p1 * c2 := by
  have h := simon_kadane_two_gear_diff B p1 c1 p2 c2
  omega

/--
  Recursive expected spend of an arbitrary `n`-gear cascade `[(p_i, c_i)]`
  scaled by `B^(length)`:
    `cascadeSpend B [] = 0`
    `cascadeSpend B ((p, c) :: rest) = c * B^(rest.length + 1) + (B - p) * cascadeSpend B rest`.
-/
def powInt (base : Int) : Nat → Int
  | 0 => 1
  | k + 1 => base * powInt base k

def cascadeScaledSpend (B : Int) : List (Int × Int) → Int
  | [] => 0
  | (p, c) :: rest =>
      c * powInt B (rest.length + 1) + (B - p) * cascadeScaledSpend B rest

/--
  General adjacent-transposition identity inside a prefix of an arbitrary `n`-gear cascade:
  Swapping the first two gears `(p1, c1)` and `(p2, c2)` ahead of any suffix `tail`
  leaves the suffix survival probability `(B - p1) * (B - p2)` invariant and changes total
  scaled spend by `(p1 * c2 - p2 * c1) * B^(tail.length + 1)`.
-/
theorem cascade_head_swap_diff (B p1 c1 p2 c2 : Int) (tail : List (Int × Int)) :
    cascadeScaledSpend B ((p2, c2) :: (p1, c1) :: tail) -
      cascadeScaledSpend B ((p1, c1) :: (p2, c2) :: tail) =
      (p1 * c2 - p2 * c1) * powInt B (tail.length + 1) := by
  simp only [cascadeScaledSpend, List.length_cons, powInt]
  have h_comm :
      (B - p2) * ((B - p1) * cascadeScaledSpend B tail) =
        (B - p1) * ((B - p2) * cascadeScaledSpend B tail) := by
    rw [← Int.mul_assoc, ← Int.mul_assoc, Int.mul_comm (B - p2) (B - p1)]
  have h_expand1 :
      c2 * (B * (B * powInt B tail.length)) + (B - p2) * (c1 * (B * powInt B tail.length)) =
        (c2 * B + (B - p2) * c1) * (B * powInt B tail.length) := by
    rw [Int.add_mul, Int.mul_assoc c2 B, Int.mul_assoc (B - p2) c1]
  have h_expand2 :
      c1 * (B * (B * powInt B tail.length)) + (B - p1) * (c2 * (B * powInt B tail.length)) =
        (c1 * B + (B - p1) * c2) * (B * powInt B tail.length) := by
    rw [Int.add_mul, Int.mul_assoc c1 B, Int.mul_assoc (B - p1) c2]
  have h_coef : (c2 * B + (B - p2) * c1) - (c1 * B + (B - p1) * c2) = p1 * c2 - p2 * c1 := by
    have hc1 : (B - p2) * c1 = B * c1 - p2 * c1 := Int.sub_mul B p2 c1
    have hc2 : (B - p1) * c2 = B * c2 - p1 * c2 := Int.sub_mul B p1 c2
    have hb1 : c2 * B = B * c2 := Int.mul_comm c2 B
    have hb2 : c1 * B = B * c1 := Int.mul_comm c1 B
    omega
  rw [Int.mul_add (B - p2), Int.mul_add (B - p1), h_comm]
  have h_sub :
      (c2 * (B * (B * powInt B tail.length)) +
          ((B - p2) * (c1 * (B * powInt B tail.length)) +
            (B - p1) * ((B - p2) * cascadeScaledSpend B tail))) -
        (c1 * (B * (B * powInt B tail.length)) +
          ((B - p1) * (c2 * (B * powInt B tail.length)) +
            (B - p1) * ((B - p2) * cascadeScaledSpend B tail))) =
        (c2 * (B * (B * powInt B tail.length)) + (B - p2) * (c1 * (B * powInt B tail.length))) -
          (c1 * (B * (B * powInt B tail.length)) + (B - p1) * (c2 * (B * powInt B tail.length))) := by
    omega
  rw [h_sub, h_expand1, h_expand2, ← Int.sub_mul, h_coef]

/--
  Always-wake cumulative spend over `dT` queries scaled by probability denominator `B`:
    `B * (dT * c_wake) = dT * B * c_wake`.
-/
def alwaysWakeScaledSpend (B dT c_wake : Int) : Int :=
  dT * (B * c_wake)

/--
  Downward-crystallized cumulative spend over `dT` queries scaled by `B`:
    `B * E_compile + dT * (B * c0 + (B - p0') * c_wake)`.
-/
def crystallizedScaledSpend (B dT e_compile p0 c0 c_wake : Int) : Int :=
  B * e_compile + dT * (B * c0 + (B - p0) * c_wake)

/--
  **Proposition 1 (Net Energy Condition for Downward Crystallization, Section 2.1)**:
  Compiling certified wakes into a Rung 0 `LUT6` page strictly lowers cumulative spend
  over stationary horizon `dT` if and only if per-step savings `(p0 * c_wake - B * c0)`
  summed over `dT` strictly exceed `B * e_compile` (i.e., `dT * (p0' * c_wake - c0) > E_compile`).
-/
theorem proposition1_downward_compile_iff (B dT e_compile p0 c0 c_wake : Int) :
    crystallizedScaledSpend B dT e_compile p0 c0 c_wake < alwaysWakeScaledSpend B dT c_wake ↔
      B * e_compile < dT * (p0 * c_wake - B * c0) := by
  unfold crystallizedScaledSpend alwaysWakeScaledSpend
  have h_step : (B * c_wake) - (B * c0 + (B - p0) * c_wake) = p0 * c_wake - B * c0 := by
    have h1 : (B - p0) * c_wake = B * c_wake - p0 * c_wake := Int.sub_mul B p0 c_wake
    omega
  have h_dist : dT * (B * c_wake) - dT * (B * c0 + (B - p0) * c_wake) =
      dT * (p0 * c_wake - B * c0) := by
    rw [← Int.mul_sub, h_step]
  omega

/--
  **Rung 0 Precedence Condition (Proposition 1, Part 2)**:
  Under `p_wake = 1` (`p_wake_scaled = B`), Rung 0 precedes the wake path in Simon–Kadane order
  (`p0' / c0 > 1 / c_wake`) if and only if `B * c0 < p0 * c_wake`.
-/
theorem rung0_precedes_wake_iff (B p0 c0 c_wake : Int) :
    twoGearScaledSpend B p0 c0 B c_wake < twoGearScaledSpend B B c_wake p0 c0 ↔
      B * c0 < p0 * c_wake :=
  simon_kadane_strict_iff B p0 c0 B c_wake

/--
  **Adversarial / High-Entropy Churn Refusal Corollary (Section 6 Internal Validity)**:
  When post-compile hit probability vanishes (`p0 = 0`) and `B > 0, dT ≥ 0, c0 ≥ 0, e_compile > 0`,
  downward compilation strictly increases total energy spend (`alwaysWake < crystallized`),
  proving `SleepCrystallizer` must abstain when `p0' = 0`.
-/
theorem zero_hit_churn_refusal (B dT e_compile c0 c_wake : Int)
    (hB : 0 < B) (hdT : 0 ≤ dT) (hc0 : 0 ≤ c0) (he : 0 < e_compile) :
    alwaysWakeScaledSpend B dT c_wake < crystallizedScaledSpend B dT e_compile 0 c0 c_wake := by
  unfold alwaysWakeScaledSpend crystallizedScaledSpend
  have hBe : 0 < B * e_compile := Int.mul_pos hB he
  have hBc0 : 0 ≤ B * c0 := Int.mul_nonneg (Int.le_of_lt hB) hc0
  have hdTc0 : 0 ≤ dT * (B * c0) := Int.mul_nonneg hdT hBc0
  have h_sub : (B - 0) * c_wake = B * c_wake := by simp
  rw [h_sub, Int.mul_add]
  omega

end LutAdapt.Cascade
