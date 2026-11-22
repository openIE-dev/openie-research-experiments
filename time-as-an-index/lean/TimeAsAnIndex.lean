import Horizon
import Paradox

/-!
  Axiom audit for all exported Horizon (TQ) and Paradox (TQ.Paradox) theorems.
  Verifies zero `sorryAx` and standard axioms only.
-/

#print axioms TQ.M1.exists_time_index
#print axioms TQ.M1.coarse_record_horizon
#print axioms TQ.M1.mean_not_injective
#print axioms TQ.future_determined
#print axioms TQ.iterate_injective
#print axioms TQ.past_recovered
#print axioms TQ.M5.erase_not_injective
#print axioms TQ.M5.restoring_cycle_zero_net_count
#print axioms TQ.M3.plancherel_z4
#print axioms TQ.M3.future_from_past_samples
#print axioms TQ.M4.interval_lightcone
#print axioms TQ.M4.future_timelike
#print axioms TQ.M4.future_irrefl
#print axioms TQ.M4.future_trans
#print axioms TQ.M4.past_cone_no_future_access
#print axioms TQ.M6.ground_state_passive_two_level
#print axioms TQ.horizon_conditions_consistent

#print axioms TQ.Paradox.no_total_self_oracle
#print axioms TQ.Paradox.no_universal_answer_table
#print axioms TQ.Paradox.mixed_answer_unique
#print axioms TQ.Paradox.grandfather_no_pure
#print axioms TQ.Paradox.polchinski_multiplicity
#print axioms TQ.Paradox.no_injection_gt
#print axioms TQ.Paradox.incompressible
#print axioms TQ.Paradox.recurrence
#print axioms TQ.Paradox.zeno_dichotomy
#print axioms TQ.Paradox.instant_measure_zero
#print axioms TQ.Paradox.countable_instants_null
#print axioms TQ.Paradox.hilbert_hotel
#print axioms TQ.Paradox.galileo_squares
#print axioms TQ.Paradox.monty_hall
