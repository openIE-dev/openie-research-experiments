//! The JCP enforcement runtime (SPEC §7) — the deterministic check that decides
//! every frame **outside any model**.
//!
//! One function fuses authorization and energy: a frame is allowed only if it
//! carries principal control (not untrusted data), references a validly-signed,
//! unexpired grant held by the caller, whose capability permits the action on
//! the exact content-addressed resource, **and** whose remaining budget covers
//! the metered cost. On allow, the cost is debited. There is no LLM in this
//! loop — which is the entire point: the inverse-scaling-law result means a more
//! capable model is a more dangerous one, so the gate cannot be the model.

use std::collections::{BTreeMap, HashMap, HashSet};

use jcp_grant::{verify, verify_chain, GrantError, RevocationSet};
use jcp_schema::flow::{FlowCeiling, FlowFacts, Origins};
use jcp_schema::{
    Caveat, ContentId, DenyReason, Did, Energy, Frame, Grant, SignedGrant, SignedRevocation, Trust, Verdict, WindowLimit,
};
use serde::{Deserialize, Serialize};

/// The result of deciding one frame.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Decision {
    pub verdict: Verdict,
    pub cost: Energy,
    /// Joules left on the grant after this decision. A refusal leaves it where
    /// it was; a denial from the debit point has already taken its debit.
    pub budget_remaining_uj: u64,
    /// The joules this decision debited from the grant, or from a chain's leaf.
    /// The verdict does not say (SPEC §8.1): a denial from the debit point
    /// debited work that ran, and a debit capped at a ceiling is less than
    /// `cost`.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub debited_uj: u64,
    /// What each link of a chain was debited, root first. Empty when every
    /// link was debited `debited_uj`, which only a capped debit breaks: each
    /// link saturates at its own ceiling.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub chain_debited_uj: Vec<u64>,
    /// The money this decision debited from the grant, or from a chain's
    /// leaf, in the minor units of its money ceiling (SPEC §4.8). Zero where
    /// no money ceiling was debited.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub debited_minor: u64,
    /// What each link of a priced chain was debited in money, root first.
    /// Empty when every link was debited `debited_minor`, which only a link
    /// with no money ceiling breaks: it is debited none.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub chain_debited_minor: Vec<u64>,
    /// The joules this decision accrued against the tainted sub-budget
    /// (SPEC §4.10) of each grant it debited.
    #[serde(default, skip_serializing_if = "is_zero")]
    pub tainted_uj: u64,
}

fn is_zero(n: &u64) -> bool {
    *n == 0
}

impl Decision {
    pub fn is_allow(&self) -> bool {
        self.verdict.is_allow()
    }

    /// A refusal: nothing ran and nothing was debited, though `cost` may record
    /// what the call would have cost.
    /// Whether a resolution with this verdict **consumed** the hold it named
    /// (SPEC §8.1).
    ///
    /// A settle or cancel is not resolved-or-not by whether it allowed. Three
    /// refusals happen *before* the hold is taken and leave it outstanding —
    /// `already-resolved` (there was none), `currency-mismatch` (a resolution
    /// the grant is not denominated in cannot be this hold's) and
    /// `wrong-subject` (a stranger's cancellation). **Every other outcome
    /// consumed it**, including a deny: a `caveat-unsatisfied` joule overrun or
    /// a `funds-exceeded` over-settlement both account for work that really
    /// ran, so the debit stands and the verdict carries the breach.
    ///
    /// A caller that read `is_allow()` as "the hold is still mine" would hold a
    /// handle to a reservation that no longer exists, and count a charge as in
    /// flight for good.
    pub fn consumed_the_hold(&self) -> bool {
        !matches!(
            self.verdict,
            Verdict::Deny(
                DenyReason::AlreadyResolved | DenyReason::CurrencyMismatch | DenyReason::WrongSubject
            )
        )
    }

    pub fn refused(reason: DenyReason, cost: Energy, budget_remaining_uj: u64) -> Self {
        Decision {
            verdict: Verdict::Deny(reason),
            cost,
            budget_remaining_uj,
            debited_uj: 0,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        }
    }

    /// An allow that debited `debited_uj` of `cost`, and nothing else.
    fn allowed(cost: Energy, debited_uj: u64, budget_remaining_uj: u64) -> Self {
        Decision {
            verdict: Verdict::Allow,
            cost,
            budget_remaining_uj,
            debited_uj,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        }
    }
}

/// What a replayed receipt stream restores, grant by grant, in each dimension
/// a [`Runtime`] enforces (SPEC §8.1): joules, money, and the tainted
/// sub-budget. `jcp_receipt::replay_ledger` builds it from a verified stream,
/// and [`Runtime::restore_ledger`] applies it.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Ledger {
    /// Joules debited, as [`Runtime::restore`] takes them.
    pub uj: Vec<(ContentId, u64)>,
    /// Money debited, in each grant's money-ceiling minor units (§4.8).
    pub minor: Vec<(ContentId, u64)>,
    /// Joules accrued against each grant's tainted sub-budget (§4.10).
    pub tainted_uj: Vec<(ContentId, u64)>,
    /// Money returned to each grant by a refund (§8.1): it lowers the net
    /// money spend a decision is made against, and never the gross debit.
    pub refunded_minor: Vec<(ContentId, u64)>,
}

/// The cost [`Runtime::authorize`] puts on its decisions: zero, because no
/// call has run yet — a refusal never runs, and an authorization only lets
/// it. The zero is exact, but nothing read it, so it is graded `Estimator`
/// with no measured figure: sealed as `HwShunt`, every refusal's receipt
/// would claim a hardware reading of a call that never happened, and a
/// ledger's "all readings" floor would count it as one (SPEC §5: a figure
/// never claims better provenance than how it was obtained).
fn nothing_ran() -> Energy {
    Energy::estimator(0)
}

/// A price for one action, in a currency's minor units (SPEC §4.8).
///
/// The money dual of [`Energy`] — with one deliberate difference: energy carries
/// a [`Provenance`] because a joule figure can be *measured*, whereas a price is
/// always *asserted* by whoever quotes it. So there is no provenance ladder here
/// and none is implied.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Price {
    pub currency: String,
    pub minor: u64,
}

impl Price {
    pub fn new(currency: impl Into<String>, minor: u64) -> Self {
        Price { currency: currency.into(), minor }
    }
    pub fn free(currency: impl Into<String>) -> Self {
        Price { currency: currency.into(), minor: 0 }
    }
}

/// A stateful enforcer tracking per-grant joule spend across a session.
#[derive(Clone, Debug, Default)]
pub struct Runtime {
    spent_uj: HashMap<ContentId, u64>,
    /// Money spent per grant, in the grant ceiling's minor units. Tracked
    /// separately from joules — the two dimensions never convert into one
    /// another.
    spent_minor: HashMap<ContentId, u64>,
    /// Money refunded per grant (§8.1). Kept beside the gross debit rather
    /// than subtracted from it, so both stay monotonic and a replay can
    /// restore each from what the receipts state.
    refunded_minor: HashMap<ContentId, u64>,
    revocations: RevocationSet,
    /// How current this point's revocation knowledge is (SPEC §4.3,
    /// Propagation). `None` — the default — means it has not said, which an
    /// auditor must read as *unverifiable*, not as current. Opaque and
    /// monotonic in whatever the deployment's revocation feed counts.
    revocation_marker: Option<u64>,
    /// Configured trust roots (SPEC §7): resource → the root-issuer keys this
    /// enforcement point honors for it. Empty for a resource = not configured
    /// (open); once any root is configured for a resource, a chain whose root
    /// issuer isn't listed is denied `untrusted-root`.
    trust_roots: HashMap<ContentId, Vec<Did>>,
    /// The enforcement-point taint floor (SPEC §4.10) — the flow analogue of
    /// `trust_roots`. Default-open, so an unconfigured runtime behaves exactly as
    /// before.
    taint_floor: TaintFloor,
    /// Joules spent against each grant's *tainted* sub-budget — the tighter wallet
    /// for calls carrying untrusted provenance. Tracked separately from
    /// `spent_uj`, which it never converts into.
    spent_tainted_uj: HashMap<ContentId, u64>,
    /// The recent history of each grant that carries a window caveat (SPEC
    /// §4.12), pruned to its longest window.
    windows: HashMap<ContentId, WindowHistory>,
    /// Whether that history is complete. `None`: it is, since this runtime
    /// began. `Some(t)`: nothing before `t` is known, so a window is complete
    /// only once it lies wholly after `t`. `Some(u64::MAX)`: nothing is known.
    window_gap: Option<u64>,
    /// The holds placed by [`Runtime::hold`] and not yet settled (SPEC §8.1),
    /// by grant. Each counts against its grant in every decision until
    /// [`Runtime::settle`] replaces it with what the work debited.
    holds: HashMap<ContentId, BTreeMap<HoldId, Held>>,
    /// Source of [`HoldId`]s. Monotonic within an enforcement point, so a
    /// handle is never reused and a stale one resolves nothing.
    next_hold: u64,
}

/// A handle to one outstanding hold (SPEC §8.1).
///
/// A settle **names** the hold it resolves. Without a name, an enforcement
/// point with two holds outstanding on one grant can only resolve "the grant's
/// hold", which conflates them: resolving the first released the second's
/// reservation as well, so the next call was admitted against money and joules
/// another call was still holding. Measured on the reference implementation
/// before this existed, at two 300-minor holds where resolving one left zero
/// reserved instead of 300.
///
/// Opaque, and local to the enforcement point that issued it: the receipt names
/// the hold by its envelope's content id, which does not exist until the hold is
/// sealed — after the decision that placed it.
#[derive(Clone, Copy, Debug, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub struct HoldId(u64);

/// What a hold reserved, and the handle that resolves it.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HoldHandle {
    /// The handle to pass to the settle or cancel that resolves this hold.
    pub id: HoldId,
    /// Joules reserved.
    pub uj: u64,
    /// Money reserved, in the grant ceiling's minor units. Zero where the
    /// grant states no money ceiling.
    pub minor: u64,
}

/// What an unsettled hold counts against its grant (SPEC §8.1): its
/// `held_uj` against the joules, and, for a tainted call, the same against
/// the tainted sub-budget, as a replay reads a hold nothing settles.
#[derive(Clone, Copy, Debug, Default)]
struct Held {
    uj: u64,
    tainted_uj: u64,
    /// Money this hold reserves, in the grant ceiling's minor units (§4.8,
    /// §8.1). Zero for a hold on a grant with no money ceiling — which is not
    /// a zero ceiling, it is the absence of the dimension.
    minor: u64,
    /// The last moment this hold's money may be captured (§8.1). After it the
    /// payer may reclaim the reservation, and a capture is refused `expired`.
    /// `None` states no deadline.
    deadline: Option<u64>,
    /// Money captures have drawn from this hold so far: the most a reversal
    /// may return to it.
    drawn_minor: u64,
}

/// What a grant's window caveats are decided over (SPEC §4.12): the calls
/// admitted under it, with their payloads, and the joules debited for them,
/// each at the time its call was admitted.
#[derive(Clone, Debug, Default)]
struct WindowHistory {
    admissions: Vec<(u64, ContentId)>,
    debits: Vec<(u64, u64)>,
}

impl WindowHistory {
    /// The joules debited for calls inside a `secs` window decided at `now`.
    fn uj_within(&self, secs: u64, now: u64) -> u64 {
        self.debits
            .iter()
            .filter(|(at, _)| now.saturating_sub(*at) < secs)
            .fold(0u64, |sum, (_, uj)| sum.saturating_add(*uj))
    }
}


/// An enforcement-point-wide taint floor (SPEC §4.10): resources whose calls may
/// not carry values from certain origins, regardless of any grant. The flow
/// analogue of [`Runtime`]'s trust roots — an operator control that needs no new
/// grants and cannot be attenuated away by a delegated ceiling.
#[derive(Clone, Debug)]
pub struct TaintFloor {
    forbidden: BTreeMap<ContentId, Origins>,
    default_forbidden: Origins,
}

impl Default for TaintFloor {
    fn default() -> Self {
        // Nothing forbidden by default: an empty origin mask intersects nothing,
        // so an unconfigured floor is a no-op and every existing deployment is
        // unaffected.
        TaintFloor { forbidden: BTreeMap::new(), default_forbidden: Origins::none() }
    }
}

impl TaintFloor {
    /// Does this floor refuse a value with label `l` on `resource`? True when the
    /// label's origins touch the resource's forbidden mask (or the default mask,
    /// where the resource has none of its own).
    fn refuses(&self, resource: &ContentId, l: &jcp_schema::Label) -> bool {
        let mask = self.forbidden.get(resource).unwrap_or(&self.default_forbidden);
        l.origins.intersects(mask)
    }
}

/// The grant's effective flow ceiling: the [`FlowCeiling::attenuate`] fold over
/// every [`FlowBelow`](jcp_schema::Caveat::FlowBelow) caveat it carries, so
/// multiple ceilings compose to the strictest. `None` when the grant carries no
/// flow caveat — the case that behaves exactly as before this feature existed.
fn ceiling_of(g: &Grant) -> Option<FlowCeiling> {
    g.caveats.iter().filter_map(|c| c.flow_ceiling()).fold(None, |acc, fc| {
        Some(match acc {
            Some(parent) => parent.attenuate(fc),
            None => fc.clone(),
        })
    })
}

/// The flow gate (SPEC §4.10, check 6c). A value may exercise the grant only when
/// its label sits at or below the grant's ceiling **and** the resource's taint
/// floor does not refuse its origins.
///
/// The `facts` argument distinguishes three cases deliberately:
/// - `None` — provenance was **not computed** (an old, un-migrated caller). With a
///   ceiling present this **fails closed**; a ceiling-free grant is unaffected.
/// - `Some(bottom)` — provenance computed and **clean**; passes any ceiling.
/// - `Some(tainted)` — tested against the ceiling and the floor.
fn flow_gate(
    g: &Grant,
    floor: &TaintFloor,
    resource: &ContentId,
    facts: Option<&FlowFacts>,
) -> Option<DenyReason> {
    // The enforcement-point floor applies whenever facts exist, independent of any
    // grant ceiling — an operator refusal a delegated grant cannot widen.
    if let Some(f) = facts {
        if floor.refuses(resource, &f.label) {
            return Some(DenyReason::TaintedFlow);
        }
    }
    match (ceiling_of(g), facts) {
        // No ceiling: today's behaviour, for any facts including None.
        (None, _) => None,
        // Ceiling present but provenance not computed: fail closed.
        (Some(_), None) => Some(DenyReason::TaintedFlow),
        (Some(ceiling), Some(f)) => {
            if ceiling.admits(&f.label) {
                None
            } else {
                Some(DenyReason::TaintedFlow)
            }
        }
    }
}

/// The effective ceiling across a delegation chain — the attenuation fold of every
/// link's ceiling, so a chain is at most as permissive as its strictest link.
fn chain_ceiling(chain: &[SignedGrant]) -> Option<FlowCeiling> {
    chain.iter().filter_map(|sg| ceiling_of(&sg.grant)).fold(None, |acc, fc| {
        Some(match acc {
            Some(parent) => parent.attenuate(&fc),
            None => fc,
        })
    })
}

/// Whether every caveat carried inside the grant holds (SPEC §4.9).
///
/// `cost_uj` is `None` in the two-phase metered path ([`Runtime::authorize`]),
/// where the true cost is not yet known: cost-dependent caveats are skipped
/// there and bind later at [`Runtime::decide`] time. Every other caveat is
/// enforced in both paths.
fn caveats_unsatisfied(
    g: &jcp_schema::Grant,
    frame: &Frame,
    caller: Did,
    cost_uj: Option<u64>,
    now: u64,
) -> Option<DenyReason> {
    for c in &g.caveats {
        if c.is_cost_dependent() && cost_uj.is_none() {
            continue; // not yet knowable; binds at decide time
        }
        if !c.holds(frame, caller, cost_uj.unwrap_or(0), now) {
            return Some(DenyReason::CaveatUnsatisfied);
        }
    }
    None
}

impl Runtime {
    pub fn new() -> Self {
        Self::default()
    }

    /// Joules already spent against a grant.
    pub fn spent(&self, grant_id: &ContentId) -> u64 {
        *self.spent_uj.get(grant_id).unwrap_or(&0)
    }

    /// The joules an unsettled [`hold`](Self::hold) counts against a grant
    /// (SPEC §8.1): zero once it is settled, and for a grant never held.
    pub fn held(&self, grant_id: &ContentId) -> u64 {
        self.sum_holds(grant_id, |h| h.uj)
    }

    /// Sum one dimension across every hold outstanding on a grant.
    fn sum_holds(&self, grant_id: &ContentId, f: impl Fn(&Held) -> u64) -> u64 {
        self.holds
            .get(grant_id)
            .map_or(0, |hs| hs.values().map(f).fold(0u64, |a, b| a.saturating_add(b)))
    }

    /// How many holds are outstanding on a grant.
    pub fn outstanding_holds(&self, grant_id: &ContentId) -> usize {
        self.holds.get(grant_id).map_or(0, BTreeMap::len)
    }

    /// Place a hold on a grant and return its handle.
    fn place_hold(&mut self, grant_id: ContentId, held: Held) -> HoldId {
        self.next_hold += 1;
        let id = HoldId(self.next_hold);
        self.holds.entry(grant_id).or_default().insert(id, held);
        id
    }

    /// Take up again a hold that was outstanding when this enforcement point
    /// stopped (SPEC §8.1), reserving what it still reserved.
    ///
    /// A restart ordinarily restores an unsettled hold as **debited**
    /// (§4.11): the stream cannot tell whether its work ran, and a restart
    /// must never hand that room to someone else. That is safe and final:
    /// the hold can never be settled, so whoever was to be paid on it is not.
    /// A hold may instead be taken up again where the caller can show, from
    /// outside the stream, exactly which hold it is and what releases it.
    /// The reservation is then a reservation again, not a debit: still
    /// counted against both ceilings, and settled, reclaimed or cancelled by
    /// the ordinary rules.
    ///
    /// The caller must have restored this runtime from a ledger that does
    /// **not** count the hold (`jcp_receipt::replay_ledger_reopening`), or it
    /// is counted twice. Returns `None`, reserving nothing, if the hold does
    /// not fit under the grant's ceilings as they now stand.
    ///
    /// `drawn_minor` is what captures had drawn from the hold and reversals
    /// had not returned, so that one of those captures can still be reversed
    /// after the restart.
    pub fn adopt_hold(
        &mut self,
        grant: &Grant,
        uj: u64,
        minor: u64,
        deadline: Option<u64>,
        drawn_minor: u64,
    ) -> Option<HoldHandle> {
        let gid = grant.id();
        if self.committed(&gid).saturating_add(uj) > grant.budget_uj {
            return None;
        }
        let committed_minor = self.net_minor(&gid).saturating_add(self.held_minor(&gid));
        match &grant.budget_funds {
            Some(f) if committed_minor.saturating_add(minor) <= f.minor => {}
            None if minor == 0 => {}
            _ => return None,
        }
        let id = self.place_hold(gid, Held { uj, tainted_uj: 0, minor, deadline, drawn_minor });
        Some(HoldHandle { id, uj, minor })
    }

    /// Place one hold across every link of a chain under a single handle, so
    /// one resolution clears it from all of them.
    fn place_hold_chained(&mut self, links: &[(ContentId, Held)]) -> HoldId {
        self.next_hold += 1;
        let id = HoldId(self.next_hold);
        for (gid, held) in links {
            self.holds.entry(*gid).or_default().insert(id, *held);
        }
        id
    }

    /// Take one named hold off a grant, leaving any others outstanding.
    fn take_hold(&mut self, grant_id: &ContentId, hold: HoldId) -> Option<Held> {
        let hs = self.holds.get_mut(grant_id)?;
        let held = hs.remove(&hold)?;
        if hs.is_empty() {
            self.holds.remove(grant_id);
        }
        Some(held)
    }

    /// Whether a named hold is outstanding on a grant.
    fn has_hold(&self, grant_id: &ContentId, hold: HoldId) -> bool {
        self.holds.get(grant_id).is_some_and(|hs| hs.contains_key(&hold))
    }

    /// The spend a decision under a grant is made against (SPEC §7's check 9,
    /// §8.1): what was debited, and what an unsettled hold on it holds, since
    /// the work behind the hold can still debit that much.
    fn committed(&self, grant_id: &ContentId) -> u64 {
        self.spent(grant_id).saturating_add(self.held(grant_id))
    }

    /// [`committed`](Self::committed) for the tainted sub-budget (§4.10).
    fn committed_tainted(&self, grant_id: &ContentId) -> u64 {
        let held = self.sum_holds(grant_id, |h| h.tainted_uj);
        self.spent_tainted(grant_id).saturating_add(held)
    }

    /// The money an unsettled [`hold_priced`](Self::hold_priced) reserves
    /// against a grant (§8.1, money dimension): zero once it is resolved, and
    /// for a grant never held.
    pub fn held_minor(&self, grant_id: &ContentId) -> u64 {
        self.sum_holds(grant_id, |h| h.minor)
    }

    /// [`committed`](Self::committed) for the money dimension: what was
    /// debited, plus what an unsettled hold reserves.
    ///
    /// Every money check decides from this rather than from
    /// [`spent_minor`](Self::spent_minor), for the same reason §8.1 requires it
    /// of joules: two decisions that each read the spend before either hold is
    /// counted would each see the whole remainder, and a reservation that does
    /// not bind the next decision is not a reservation.
    fn committed_minor(&self, grant_id: &ContentId) -> u64 {
        self.net_minor(grant_id).saturating_add(self.held_minor(grant_id))
    }

    /// Money refunded to a grant (§8.1), in its ceiling's minor units.
    pub fn refunded_minor(&self, grant_id: &ContentId) -> u64 {
        *self.refunded_minor.get(grant_id).unwrap_or(&0)
    }

    /// The **net** money spend: what was debited, less what was refunded. This
    /// is what a ceiling bounds — a refund returns the payer's exposure, so it
    /// returns the room.
    pub fn net_minor(&self, grant_id: &ContentId) -> u64 {
        self.spent_minor(grant_id).saturating_sub(self.refunded_minor(grant_id))
    }

    /// Money already spent against a grant, in its ceiling's minor units.
    pub fn spent_minor(&self, grant_id: &ContentId) -> u64 {
        *self.spent_minor.get(grant_id).unwrap_or(&0)
    }

    /// Decide a frame against **both** ceilings of a dual-ceiling grant
    /// (SPEC §4.8): the joule budget and the money budget, enforced
    /// independently, denying on **whichever binds first**.
    ///
    /// This is the AP2/OpenPay path: a real-world payment mandate authorizes
    /// spend in a currency, while JCP meters the work in joules. The two are
    /// never reconciled by an invented exchange rate — they are simply both
    /// enforced, and the receipt records which one bound. A denial for
    /// `BudgetExceeded` while the money ceiling still had room is a statement
    /// no single-dimension authorization can make.
    ///
    /// Debits both dimensions on allow, neither on deny. A grant with no money
    /// ceiling (`budget_funds: None`) ignores `price` entirely and behaves
    /// exactly like [`decide`](Self::decide).
    pub fn decide_priced(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        cost: Energy,
        price: &Price,
        now: u64,
    ) -> Decision {
        let g = &sg.grant;
        let gid = g.id();
        let remaining = g.budget_uj.saturating_sub(self.committed(&gid));
        let deny = |r: DenyReason| Decision::refused(r, cost, remaining);

        // Validity checks 1–6, in the same fixed order as `decide`.
        if let Some(r) = self.check(frame, sg, caller, now, None) {
            return deny(r);
        }
        // 6b. Caveats (§4.9).
        if let Some(r) = caveats_unsatisfied(g, frame, caller, Some(cost.uj()), now)
            .or_else(|| self.window_unsatisfied(g, &frame.payload_hash, Some(cost.uj()), now))
        {
            return deny(r);
        }

        // 7. The JOULE ceiling. Checked first so that when both would bind, the
        //    receipt names energy — JCP's primary dimension. An unsettled hold
        //    counts as spent (§8.1).
        let spent = self.spent(&gid);
        let committed = self.committed(&gid);
        let c = cost.uj();
        if committed.saturating_add(c) > g.budget_uj {
            return deny(DenyReason::BudgetExceeded);
        }

        // 8. The MONEY ceiling, independently. Absent = joules alone bound.
        if let Some(funds) = &g.budget_funds {
            if !funds.same_currency(&price.currency) {
                // No rate is invented, so a foreign-currency cost is refused.
                return deny(DenyReason::CurrencyMismatch);
            }
            // Decided from the COMMITTED money, so an unsettled hold's
            // reservation bounds this call (§8.1).
            if self.committed_minor(&gid).saturating_add(price.minor) > funds.minor {
                return deny(DenyReason::FundsExceeded);
            }
            // Allow — debit money too. Only reached when BOTH ceilings pass.
            let spent_m = self.spent_minor(&gid);
            self.spent_minor.insert(gid, spent_m + price.minor);
        }
        let debited_minor = if g.budget_funds.is_some() { price.minor } else { 0 };

        // Allow — debit the energy.
        self.spent_uj.insert(gid, spent + c);
        self.admit_windows(g, frame.payload_hash, now);
        self.debit_windows(g, c, Some(now));
        Decision { debited_minor, ..Decision::allowed(cost, c, g.budget_uj - (committed + c)) }
    }

    /// Rebuild enforcement state from a replayed spend ledger (SPEC §8.1: the
    /// receipt stream is sufficient to reconstruct enforcement state). Each
    /// entry adds to the grant's recorded spend, so a restore never lowers a
    /// spend this runtime already holds — feed it what the receipts debited,
    /// e.g. via `jcp_receipt::replay_spend`.
    ///
    /// A spend ledger carries no times, so after restoring one this runtime
    /// cannot know what any window held (SPEC §4.12). It treats every window
    /// as full until [`resume_windows_at`](Self::resume_windows_at) says from
    /// when its history is complete.
    pub fn restore(&mut self, entries: impl IntoIterator<Item = (ContentId, u64)>) {
        for (gid, uj) in entries {
            let e = self.spent_uj.entry(gid).or_insert(0);
            *e = e.saturating_add(uj);
            self.window_gap = Some(u64::MAX);
        }
    }

    /// [`restore`](Self::restore) in every dimension a replayed stream
    /// records (SPEC §8.1): the joules, the money each grant was debited, and
    /// what its tainted sub-budget accrued. Restoring joules alone would hand
    /// the other two back on a restart. Each entry adds to what this runtime
    /// already holds, so a restore never lowers a spend in any dimension.
    pub fn restore_ledger(&mut self, ledger: Ledger) {
        self.restore(ledger.uj);
        for (gid, minor) in ledger.minor {
            let e = self.spent_minor.entry(gid).or_insert(0);
            *e = e.saturating_add(minor);
        }
        for (gid, uj) in ledger.tainted_uj {
            let e = self.spent_tainted_uj.entry(gid).or_insert(0);
            *e = e.saturating_add(uj);
        }
        for (gid, minor) in ledger.refunded_minor {
            let e = self.refunded_minor.entry(gid).or_insert(0);
            *e = e.saturating_add(minor);
        }
    }

    /// Declare this runtime's window history (SPEC §4.12) complete from `from`
    /// on: every call admitted since `from` has been decided here. A window is
    /// then decided once it lies wholly after `from`, and until then it counts
    /// as full, since calls before `from` may have filled it.
    pub fn resume_windows_at(&mut self, from: u64) {
        self.window_gap = Some(from);
    }

    /// Whether a `secs` window decided at `now` lies wholly inside the part of
    /// history this runtime knows.
    fn window_known(&self, secs: u64, now: u64) -> bool {
        match self.window_gap {
            None => true,
            Some(from) => from != u64::MAX && now.saturating_sub(from) >= secs,
        }
    }

    /// The window gate (SPEC §4.12): whether a call under `g` carrying
    /// `payload`, at `now`, costing `cost_uj`, would exceed any of its window
    /// caveats. The cost is `None` in the two-phase path, where a joule window
    /// admits a call while any of it is left and binds at the debit.
    fn window_unsatisfied(&self, g: &Grant, payload: &ContentId, cost_uj: Option<u64>, now: u64) -> Option<DenyReason> {
        let windows: Vec<_> = g.caveats.iter().filter_map(Caveat::window).collect();
        if windows.is_empty() {
            return None;
        }
        let history = self.windows.get(&g.id());
        for w in windows {
            if !self.window_known(w.secs, now) {
                return Some(DenyReason::WindowExceeded);
            }
            let admitted = history
                .into_iter()
                .flat_map(|h| &h.admissions)
                .filter(|(at, _)| now.saturating_sub(*at) < w.secs);
            let full = match w.limit {
                WindowLimit::MaxCalls(n) => admitted.count() as u64 >= n,
                WindowLimit::MaxDistinctPayloads(n) => {
                    let distinct: HashSet<&ContentId> = admitted.map(|(_, p)| p).collect();
                    !distinct.contains(payload) && distinct.len() as u64 >= n
                }
                WindowLimit::MaxUj(max) => {
                    let used = history.map_or(0, |h| h.uj_within(w.secs, now));
                    match cost_uj {
                        Some(c) => used.saturating_add(c) > max,
                        None => used >= max,
                    }
                }
            };
            if full {
                return Some(DenyReason::WindowExceeded);
            }
        }
        None
    }

    /// Record an admitted call under `g` for its window caveats, pruning what
    /// no window of `g` can reach any more.
    fn admit_windows(&mut self, g: &Grant, payload: ContentId, now: u64) {
        let Some(longest) = g.caveats.iter().filter_map(Caveat::window).map(|w| w.secs).max() else {
            return;
        };
        let h = self.windows.entry(g.id()).or_default();
        h.admissions.retain(|(at, _)| now.saturating_sub(*at) < longest);
        h.debits.retain(|(at, _)| now.saturating_sub(*at) < longest);
        h.admissions.push((now, payload));
    }

    /// Record joules debited under `g` for its window caveats, at `at`, the
    /// time the call was admitted. Returns whether a joule window is now
    /// exceeded.
    ///
    /// In the two-phase path the debit arrives without its time, so `at` is
    /// `None` and the debit is placed at the grant's latest admission. That is
    /// never earlier than the call's own, so the joules stay inside a window
    /// at least as long as they should. A debit with no admission recorded at
    /// all stays inside every window for good.
    fn debit_windows(&mut self, g: &Grant, uj: u64, at: Option<u64>) -> bool {
        let windows: Vec<_> = g.caveats.iter().filter_map(Caveat::window).copied().collect();
        if windows.is_empty() {
            return false;
        }
        let h = self.windows.entry(g.id()).or_default();
        let at = at.or_else(|| h.admissions.last().map(|(t, _)| *t)).unwrap_or(u64::MAX);
        h.debits.push((at, uj));
        windows.iter().any(|w| matches!(w.limit, WindowLimit::MaxUj(max) if h.uj_within(w.secs, at) > max))
    }

    /// Verify and honor a revocation for `grant`. Only the grant's issuer may
    /// revoke; an unauthorized or unsigned revocation is rejected and never
    /// enters the set. Once admitted, every decision against the revoked grant
    /// — and every chain that contains it — is denied.
    pub fn apply_revocation(&mut self, sr: &SignedRevocation, grant: &Grant) -> Result<(), GrantError> {
        self.revocations.apply(sr, grant)
    }

    pub fn is_revoked(&self, grant_id: &ContentId) -> bool {
        self.revocations.contains(grant_id)
    }

    /// Declare how current this enforcement point's revocation knowledge is
    /// (SPEC §4.3).
    ///
    /// The marker is opaque to JCP and monotonic in whatever the deployment's
    /// revocation feed counts — a sequence number, a log index, a timestamp.
    /// JCP neither defines nor interprets it; it only requires that a larger
    /// value mean "has seen at least as much".
    ///
    /// Why it exists. §4.3 requires an enforcement point to deny a revoked
    /// grant *once it has the revocation*, and says nothing about how it gets
    /// one. With budgets sharded across N points (§4.5), a revocation that has
    /// reached three of five leaves the grant live at two — and an allow from
    /// a point that had not yet heard is indistinguishable, after the fact,
    /// from an allow by a point that had heard and ignored it. The first is a
    /// propagation delay; the second is a violation of this spec. Recording
    /// the marker is what separates them: given a revocation issued at marker
    /// M, an allow from a point at `known_through < M` is explicable, and one
    /// at `>= M` is not.
    ///
    /// The marker reaches the audit trail: a receipt sealed by a point that has
    /// declared one states it as `known_through` in the signed core, so an
    /// auditor reconciling receipts against a revocation feed needs nothing out
    /// of band. It is stated by the **sealer**, not carried on a `Decision` —
    /// the marker is a property of the point, not of one call, and every
    /// receipt that point seals shares it. `jcp_receipt::seal_from_point`,
    /// `ReceiptLog::declare_revocation_marker`, and `jcp_bridge::Bridge`, which
    /// reads this value for every receipt it seals.
    pub fn revocation_known_through(&mut self, marker: u64) {
        self.revocation_marker = Some(marker);
    }

    /// The marker last declared by [`Runtime::revocation_known_through`].
    ///
    /// `None` means this point has not said how current its knowledge is. That
    /// is not "fully current": an auditor MUST treat its allows as
    /// unverifiable for revocation rather than as compliant (SPEC §4.3).
    pub fn revocation_marker(&self) -> Option<u64> {
        self.revocation_marker
    }

    /// Configure a trust root (SPEC §7): honor `issuer` as a root for
    /// `resource`. The same local, pairwise trust shape as `authorized_keys` —
    /// no certificate authority, no hierarchy. Once any root is configured for
    /// a resource, a grant or chain whose root issuer isn't listed is denied.
    pub fn trust_root(&mut self, resource: ContentId, issuer: Did) {
        self.trust_roots.entry(resource).or_default().push(issuer);
    }

    /// Whether `issuer` may anchor authority over `resource` here. True when
    /// the resource is unconfigured (open) or the issuer is listed.
    fn root_honored(&self, resource: &ContentId, issuer: &Did) -> bool {
        match self.trust_roots.get(resource) {
            None => true,
            Some(roots) => roots.contains(issuer),
        }
    }

    /// Forbid values carrying any origin in `mask` from reaching `resource` (SPEC
    /// §4.10) — the flow analogue of [`trust_root`](Self::trust_root). An
    /// enforcement-point control that applies regardless of any grant's ceiling and
    /// cannot be attenuated away.
    pub fn forbid_flow(&mut self, resource: ContentId, mask: Origins) {
        self.taint_floor.forbidden.insert(resource, mask);
    }

    /// Forbid `mask` on every resource without its own floor rule — a fail-closed
    /// default, off unless set.
    pub fn forbid_flow_by_default(&mut self, mask: Origins) {
        self.taint_floor.default_forbidden = mask;
    }

    /// Joules spent against a grant's tainted sub-budget.
    pub fn spent_tainted(&self, grant_id: &ContentId) -> u64 {
        *self.spent_tainted_uj.get(grant_id).unwrap_or(&0)
    }

    /// Decide a frame against the grant it references and a metered `cost`, for
    /// `caller` at time `now`. On `Allow`, debits the cost from the grant's
    /// budget. Pure and deterministic — the checks run in a fixed order and the
    /// first failure names the reason.
    pub fn decide(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        cost: Energy,
        now: u64,
    ) -> Decision {
        let g = &sg.grant;
        let gid = g.id();
        let remaining = g.budget_uj.saturating_sub(self.committed(&gid));
        let deny = |r: DenyReason| Decision::refused(r, cost, remaining);

        // Validity checks 1–6, in fixed order (first failure names the reason).
        if let Some(r) = self.check(frame, sg, caller, now, None) {
            return deny(r);
        }
        // 6b. Caveats carried inside the grant (§4.9) — the open attenuation axis.
        if let Some(r) = caveats_unsatisfied(g, frame, caller, Some(cost.uj()), now)
            .or_else(|| self.window_unsatisfied(g, &frame.payload_hash, Some(cost.uj()), now))
        {
            return deny(r);
        }
        // 7. Budget: prior spend + this cost must not exceed the ceiling. An
        //    unsettled hold is prior spend (§8.1).
        let spent = self.spent(&gid);
        let committed = self.committed(&gid);
        let c = cost.uj();
        if committed.saturating_add(c) > g.budget_uj {
            return deny(DenyReason::BudgetExceeded);
        }

        // Allow — debit the cost.
        self.spent_uj.insert(gid, spent + c);
        self.admit_windows(g, frame.payload_hash, now);
        self.debit_windows(g, c, Some(now));
        Decision::allowed(cost, c, g.budget_uj - (committed + c))
    }

    /// Validity checks 1–6 shared by [`decide`](Self::decide) and
    /// [`authorize`](Self::authorize): everything except the cost-specific
    /// budget test. `None` means the frame may proceed to a budget decision.
    fn check(
        &self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: Option<&FlowFacts>,
    ) -> Option<DenyReason> {
        let g = &sg.grant;
        let gid = g.id();
        // 1. Untrusted output can never exercise control — anti-tool-poisoning.
        if frame.trust == Trust::Data {
            return Some(DenyReason::UntrustedControl);
        }
        // 1b. A revoked grant conveys nothing.
        if self.revocations.contains(&gid) {
            return Some(DenyReason::Revoked);
        }
        // 1c. The issuer must be a configured trust root for the resource (§7).
        if !self.root_honored(&frame.resource, &g.issuer) {
            return Some(DenyReason::UntrustedRoot);
        }
        // 2. The frame must reference this exact grant.
        if frame.grant_id != gid {
            return Some(DenyReason::WrongResource);
        }
        // 3. The caller must be the grant's subject (the holder).
        if caller != g.subject {
            return Some(DenyReason::WrongSubject);
        }
        // 4. The issuer's signature must verify over the grant.
        if verify(sg).is_err() {
            return Some(DenyReason::BadSignature);
        }
        // 4b. A delegated grant is decided only with its chain (§4.2). Alone,
        //     nothing shows that it narrows what its issuer held: its budget,
        //     caveats and expiry would be taken at their word, as a root's are.
        if g.parent.is_some() {
            return Some(DenyReason::ChainBroken);
        }
        // 5. Not expired.
        if g.is_expired(now) {
            return Some(DenyReason::Expired);
        }
        // 6. Capability must permit the action on the frame's resource.
        if frame.resource != g.capability.resource {
            return Some(DenyReason::WrongResource);
        }
        if !g.capability.actions.iter().any(|a| a == &frame.action) {
            return Some(DenyReason::ActionNotGranted);
        }
        // 6c. Flow (SPEC §4.10): the argument's propagated provenance must sit at
        //     or below the grant's ceiling, and the resource's taint floor must not
        //     refuse its origins. Placed here on purpose — after capability (the
        //     ceiling lives inside an authenticated grant, so judging flow before
        //     the signature would seal a verdict over attacker-chosen policy) and
        //     before caveats and budget (a tainted call must cost zero joules, the
        //     same invariant tool-poisoning denial holds). A ceiling-free grant
        //     with no facts reaches here unchanged.
        if let Some(r) = flow_gate(g, &self.taint_floor, &frame.resource, facts) {
            return Some(r);
        }
        None
    }

    /// Phase one of metered enforcement: authorize a frame **without debiting**.
    /// Every check of [`decide`](Self::decide) runs, but the budget test becomes
    /// "any budget remains" (`spent < ceiling`) rather than "this cost fits" —
    /// because for a metered gateway the true cost is unknown until the call
    /// runs. Gate with this, run the tool, measure the joules, then
    /// [`charge`](Self::charge) the measured figure. The returned `Decision`
    /// carries the budget remaining and zero cost (nothing was debited, and
    /// nothing has run), graded `Estimator`: no meter read that zero.
    ///
    /// The budget is what the grant has left less any unsettled
    /// [`hold`](Self::hold) on it (SPEC §8.1). An allow here places no hold
    /// of its own, so until its work is charged a later decision under the
    /// grant does not count that work: an enforcement point that may decide
    /// another call before charging this one uses [`hold`](Self::hold).
    pub fn authorize(&mut self, frame: &Frame, sg: &SignedGrant, caller: Did, now: u64) -> Decision {
        let g = &sg.grant;
        let gid = g.id();
        let remaining = g.budget_uj.saturating_sub(self.committed(&gid));
        if let Some(r) = self.check(frame, sg, caller, now, None)
            .or_else(|| caveats_unsatisfied(g, frame, caller, None, now))
            .or_else(|| self.window_unsatisfied(g, &frame.payload_hash, None, now))
        {
            return Decision::refused(r, nothing_ran(), remaining);
        }
        if remaining == 0 {
            return Decision::refused(DenyReason::BudgetExceeded, nothing_ran(), 0);
        }
        self.admit_windows(g, frame.payload_hash, now);
        Decision::allowed(nothing_ran(), 0, remaining)
    }

    /// Phase two of metered enforcement: debit a **measured** cost against an
    /// already-[`authorize`](Self::authorize)d grant, saturating at the ceiling.
    /// Returns the accounting `Decision` to seal. Because the cost was unknown
    /// at authorization time, the final call of a grant's life may overrun: the
    /// debit is capped at the ceiling and the overrun is visible as
    /// `budget_remaining_uj == 0` with `cost.uj()` exceeding `debited_uj` —
    /// the receipt records the overshoot rather than hiding it. It settles no
    /// hold: a call placed with [`hold`](Self::hold) is charged by
    /// [`settle`](Self::settle).
    pub fn charge(&mut self, grant: &Grant, measured: Energy) -> Decision {
        let gid = grant.id();
        let spent = self.spent(&gid);
        let debited = measured.uj().min(grant.budget_uj.saturating_sub(spent));
        let new_spent = spent + debited;
        self.spent_uj.insert(gid, new_spent);
        // Cost-dependent caveats (§4.9) could not be evaluated at `authorize` —
        // the cost was unknown there. They bind HERE. The work has already run
        // and the joules are real, so the debit stands either way: what the
        // breach changes is the VERDICT, so the sealed receipt is evidence that
        // the invocation exceeded its authorized per-call ceiling rather than
        // silently absorbing it. Hiding the breach would be the dishonest move,
        // exactly as capping-without-recording would be for a budget overrun.
        let breached = grant.caveats.iter().any(|c| c.cost_breached(measured.uj()));
        // A joule window (§4.12) binds here for the same reason, and the same way.
        let window_breached = self.debit_windows(grant, measured.uj(), None);
        Decision {
            verdict: if breached {
                Verdict::Deny(DenyReason::CaveatUnsatisfied)
            } else if window_breached {
                Verdict::Deny(DenyReason::WindowExceeded)
            } else {
                Verdict::Allow
            },
            cost: measured,
            // Saturating: an old log replays a capped debit at its full cost
            // (SPEC §8.1), which can restore a grant past its ceiling.
            budget_remaining_uj: grant.budget_uj.saturating_sub(new_spent),
            debited_uj: debited,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        }
    }

    /// The flow-aware [`authorize`](Self::authorize): the same two-phase gate, but
    /// the flow facts are checked (check 6c) so a tainted argument is denied
    /// `TaintedFlow` **before** any budget is touched, and a call already at its
    /// tainted sub-budget is denied `TaintBudgetExceeded` before the tool runs.
    /// `authorize` itself delegates here conceptually with `facts = None`; a
    /// gateway that computes provenance calls this with real facts. Like
    /// `authorize`, it counts an unsettled [`hold`](Self::hold) and places
    /// none.
    pub fn authorize_flow(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: &FlowFacts,
    ) -> Decision {
        match self.flow_refusal(frame, sg, caller, now, facts) {
            Err(refused) => refused,
            Ok(remaining) => {
                self.admit_windows(&sg.grant, frame.payload_hash, now);
                Decision::allowed(nothing_ran(), 0, remaining)
            }
        }
    }

    /// Every check [`authorize_flow`](Self::authorize_flow) makes, admitting
    /// nothing: the joules left, or the refusal. Kept apart from the admission
    /// so a path with checks of its own after these — a priced hold's money —
    /// admits a call into its windows only once every check has passed, and a
    /// call refused for money is not counted against a window (§4.12).
    fn flow_refusal(
        &self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: &FlowFacts,
    ) -> Result<u64, Decision> {
        let g = &sg.grant;
        let gid = g.id();
        let remaining = g.budget_uj.saturating_sub(self.committed(&gid));
        let deny = |r: DenyReason| Decision::refused(r, nothing_ran(), remaining);
        if let Some(r) = self
            .check(frame, sg, caller, now, Some(facts))
            .or_else(|| caveats_unsatisfied(g, frame, caller, None, now))
            .or_else(|| self.window_unsatisfied(g, &frame.payload_hash, None, now))
        {
            return Err(deny(r));
        }
        if remaining == 0 {
            return Err(Decision::refused(DenyReason::BudgetExceeded, nothing_ran(), 0));
        }
        // Tainted work gets the smaller wallet. Pre-checked at authorize (like the
        // main budget's `remaining == 0` degradation) so a call that has exhausted
        // its tainted sub-budget is denied before the upstream tool runs.
        if !facts.is_bottom() {
            if let Some(cap) = ceiling_of(g).and_then(|fc| fc.tainted_budget_uj) {
                if self.committed_tainted(&gid) >= cap {
                    return Err(deny(DenyReason::TaintBudgetExceeded));
                }
            }
        }
        Ok(remaining)
    }

    /// The flow-aware [`charge`](Self::charge): debit the measured tool joules as
    /// usual, and — when the call was tainted — also accrue them against the
    /// grant's tainted sub-budget, so the tighter wallet actually depletes. The
    /// monitor's own evaluation cost (`facts.eval_uj`) is **not** folded in here;
    /// it is reported and sealed separately so a call's energy keeps its meaning.
    pub fn charge_flow(&mut self, grant: &Grant, measured: Energy, facts: &FlowFacts) -> Decision {
        let mut decision = self.charge(grant, measured);
        if !facts.is_bottom() {
            let gid = grant.id();
            let accrued = self.spent_tainted(&gid).saturating_add(measured.uj());
            self.spent_tainted_uj.insert(gid, accrued);
            decision.tainted_uj = measured.uj();
        }
        decision
    }

    /// What a hold must state before the work an allowed
    /// [`authorize_flow`](Self::authorize_flow) lets run (SPEC §8.1), so that a
    /// stream ending at the hold restores no less than the work's
    /// [`charge_flow`](Self::charge_flow) would have debited: the joules left on
    /// the grant, the most that charge can debit, since it saturates at the
    /// ceiling.
    ///
    /// A tainted call accrues its whole cost against the tainted sub-budget
    /// (§4.10), and nothing bounds that cost before it runs. But past what the
    /// sub-budget has left the gate refuses tainted work whatever was accrued,
    /// so for a tainted call against a sub-budget this is at least what the
    /// sub-budget has left: restored as accrued, the wallet is as spent as any
    /// accrual could leave it.
    ///
    /// This computes the figure and counts nothing: [`hold`](Self::hold)
    /// computes it and counts it against the grant until the work settles.
    /// A hold sealed with this figure beside an allow from
    /// [`authorize`](Self::authorize) or
    /// [`authorize_flow`](Self::authorize_flow), rather than through
    /// [`hold`](Self::hold), is not counted live, which breaks SPEC §8.1
    /// wherever another decision under the grant can come before the work is
    /// charged. It is sound only where the point decides one call at a time
    /// and charges each before it decides the next.
    pub fn hold_bound(&self, grant: &Grant, facts: &FlowFacts) -> u64 {
        let gid = grant.id();
        // From the COMMITTED spend, not the debited one: two holds that each
        // sized themselves against the remainder would together reserve more
        // than the grant has.
        let joules = grant.budget_uj.saturating_sub(self.committed(&gid));
        let wallet = match ceiling_of(grant).and_then(|fc| fc.tainted_budget_uj) {
            Some(cap) if !facts.is_bottom() => cap.saturating_sub(self.committed_tainted(&gid)),
            _ => 0,
        };
        let whole = joules.max(wallet);
        // A per-invocation ceiling the grant states in advance (§4.9's
        // `MaxCostUj`) is an upper bound the work is not permitted to exceed,
        // so a hold reserves that rather than everything left. This is what
        // makes the two-phase path concurrent instead of serial: a grant
        // stating no per-call ceiling has only its whole remainder as an upper
        // bound, so one outstanding hold leaves nothing to admit a second call
        // from — bounded, but one call at a time.
        //
        // Honestly: a call that overruns its stated ceiling has under-reserved,
        // and the debit at resolution still stands. That overrun is recorded as
        // a `caveat-unsatisfied` verdict over a real debit, exactly as a budget
        // overrun is, rather than absorbed — which is the same trade the debit
        // point already makes, moved to where the reservation is sized.
        match grant.caveats.iter().filter_map(|c| c.max_cost_uj()).min() {
            Some(per_call) => per_call.min(whole),
            None => whole,
        }
    }

    /// Authorize a two-phase call and place the hold its allow is sealed as,
    /// in one step (SPEC §8.1): [`authorize_flow`](Self::authorize_flow), and
    /// on allow the hold's `held_uj`, [`hold_bound`](Self::hold_bound), which
    /// is returned to be sealed. A refusal places no hold and returns `None`.
    ///
    /// The runtime counts the hold against the grant, live, as a replay
    /// counts a hold nothing settles: every decision under the grant reads it
    /// as debited `held_uj`, and a tainted call's tainted sub-budget as having
    /// accrued it, until [`settle`](Self::settle) replaces the hold with what
    /// the work debited. A hold states what the grant has left, so while it
    /// is unsettled the grant has nothing left: a call decided while this
    /// one's work runs is decided against the remainder less the hold, not
    /// against the remainder its work may yet spend, so every other
    /// two-phase call under the grant, and every one-shot call that would
    /// debit anything, is refused `budget-exceeded` where no earlier check
    /// refuses it. For the same reason a grant has one unsettled hold at
    /// most.
    ///
    /// The decision and the hold are one step so that no other decision can
    /// read the budget between them, which a caller that authorized and then
    /// held in two steps, around a lock released between, would allow.
    pub fn hold(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: &FlowFacts,
    ) -> (Decision, Option<HoldHandle>) {
        let decision = self.authorize_flow(frame, sg, caller, now, facts);
        if !decision.is_allow() {
            return (decision, None);
        }
        let uj = self.hold_bound(&sg.grant, facts);
        let tainted_uj = if facts.is_bottom() { 0 } else { uj };
        let id = self.place_hold(sg.grant.id(), Held { uj, tainted_uj, minor: 0, deadline: None, drawn_minor: 0 });
        (decision, Some(HoldHandle { id, uj, minor: 0 }))
    }

    /// Settle the grant's [`hold`](Self::hold) with what its work measured
    /// (SPEC §8.1): the hold stops counting, and the measured cost is debited
    /// as [`charge_flow`](Self::charge_flow) debits it, saturating at the
    /// ceiling. Returns the accounting `Decision` to seal as the receipt
    /// that settles the hold.
    ///
    /// A hold resolves **once**. A settle with no hold outstanding — a retried
    /// or replayed settle, or a completion that crossed a
    /// [`cancel`](Self::cancel) — is refused `already-resolved` and debits
    /// nothing. Settling unconditionally would debit the same work again:
    /// `remove` on an absent hold removes nothing, and the debit would land all
    /// the same.
    pub fn settle(&mut self, grant: &Grant, hold: HoldId, measured: Energy, facts: &FlowFacts) -> Decision {
        if self.take_hold(&grant.id(), hold).is_none() {
            let remaining = grant.budget_uj.saturating_sub(self.committed(&grant.id()));
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), remaining);
        }
        self.charge_flow(grant, measured, facts)
    }

    /// Resolve a [`hold`](Self::hold) whose work will not complete (SPEC §8.1):
    /// a **cancellation**.
    ///
    /// Without one, a hold nothing settles is unresolvable: §8.1 has the point
    /// name it unresolved and keep its grants debited `held_uj` while nothing
    /// settles it, so the grant refuses every later call for good while the
    /// joules the abandoned work really burned are never recorded as spent. A
    /// cancellation is the third resolution, and it is a **decision, not an
    /// absence**: it debits what the work spent, exactly as a settle debits it,
    /// and seals a receipt like any other decision.
    ///
    /// It is **not a refund** — energy already turned to heat cannot be
    /// returned to a budget — and a cancellation that released the hold without
    /// debiting would turn cancelling into a way to spend for nothing.
    /// `measured` is what the metering ladder yields for the work that ran
    /// (§5.1); the ladder always yields a figure (C9), so "it could not be
    /// measured" is never a licence to charge zero.
    ///
    /// Only the grant's `subject`, whose work it is, or its `issuer`, which can
    /// already revoke the grant outright (§4.3) and so holds the strictly
    /// greater power, may cancel — every act here is signed, since there are no
    /// anonymous actors (§2). Anyone else is refused `wrong-subject` **and the
    /// hold stays outstanding**, so a stranger can neither discard another
    /// actor's work nor strand its budget. A second cancellation, like a second
    /// settle, is refused `already-resolved`.
    /// Place a hold on **both** ceilings (§4.8, §8.1): the joule bound of
    /// [`hold`](Self::hold), and a money bound the caller states in advance.
    ///
    /// This is the shape usage-based payment actually has. A charge whose final
    /// amount is known only after the work runs can still be bounded before it:
    /// the payer authorizes a maximum, and that maximum — not an estimate of
    /// the outcome — is what a ceiling may admit on. `ceiling` is that
    /// maximum. It is checked against the **committed** money spend, so
    /// concurrent holds bound each other, and reserved without being debited;
    /// [`settle_priced`](Self::settle_priced) then debits what the work really
    /// cost and the remainder is released by the hold's removal.
    ///
    /// Refused `currency-mismatch` when the ceiling is denominated in a
    /// currency the grant is not, and `funds-exceeded` when the maximum will
    /// not fit beside what is already committed. Neither refusal places a
    /// hold, so neither leaves anything to release. A grant with no money
    /// ceiling holds no money: the dimension is absent, not zero.
    ///
    /// Returns the held `(joules, money)` on an allow.
    pub fn hold_priced(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: &FlowFacts,
        ceiling: &Price,
    ) -> (Decision, Option<HoldHandle>) {
        self.hold_priced_inner(frame, sg, caller, now, facts, ceiling, None)
    }

    /// [`hold_priced`](Self::hold_priced) with a **capture deadline** (§8.1):
    /// the last moment the hold's money may be captured.
    ///
    /// Without one, a hold whose resolver disappears reserves the payer's
    /// money until someone with the right to cancel does. A deadline makes the
    /// reservation recoverable by construction: past it, a capture is refused
    /// `expired` and [`reclaim`](Self::reclaim) releases the money to the
    /// payer without needing anyone's cooperation.
    #[allow(clippy::too_many_arguments)]
    pub fn hold_priced_until(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: &FlowFacts,
        ceiling: &Price,
        capture_deadline: u64,
    ) -> (Decision, Option<HoldHandle>) {
        self.hold_priced_inner(frame, sg, caller, now, facts, ceiling, Some(capture_deadline))
    }

    #[allow(clippy::too_many_arguments)]
    fn hold_priced_inner(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        now: u64,
        facts: &FlowFacts,
        ceiling: &Price,
        deadline: Option<u64>,
    ) -> (Decision, Option<HoldHandle>) {
        // The joule phase first, exactly as `hold` decides it, so one ordered
        // check governs both dimensions and the first failure names the reason.
        // The call enters its windows only after the money check too: a call
        // refused for money did not run, and must not fill a window (§4.12).
        let remaining = match self.flow_refusal(frame, sg, caller, now, facts) {
            Err(refused) => return (refused, None),
            Ok(remaining) => remaining,
        };
        let gid = sg.grant.id();
        if let Some(funds) = &sg.grant.budget_funds {
            if !funds.same_currency(&ceiling.currency) {
                return (
                    Decision::refused(DenyReason::CurrencyMismatch, nothing_ran(), remaining),
                    None,
                );
            }
            if self.committed_minor(&gid).saturating_add(ceiling.minor) > funds.minor {
                return (Decision::refused(DenyReason::FundsExceeded, nothing_ran(), remaining), None);
            }
        }
        self.admit_windows(&sg.grant, frame.payload_hash, now);
        let decision = Decision::allowed(nothing_ran(), 0, remaining);
        let uj = self.hold_bound(&sg.grant, facts);
        let tainted_uj = if facts.is_bottom() { 0 } else { uj };
        let minor = if sg.grant.budget_funds.is_some() { ceiling.minor } else { 0 };
        let id = self.place_hold(gid, Held { uj, tainted_uj, minor, deadline, drawn_minor: 0 });
        (decision, Some(HoldHandle { id, uj, minor }))
    }

    /// Resolve a [`hold_priced`](Self::hold_priced) with what the work really
    /// cost in **both** dimensions: `measured` joules and a `settled` amount.
    ///
    /// The reservation is released by the hold's removal, so a charge that
    /// settles for a tenth of its maximum leaves the other nine tenths
    /// available — the difference between a ceiling that can be re-used across
    /// a session and one that is consumed by the worst case of every call.
    ///
    /// `settled` **MUST NOT** exceed what the hold reserved. When it does, the
    /// debit still stands and the **verdict** turns `funds-exceeded`, for the
    /// reason [`charge`](Self::charge) gives for a joule overrun: the money has
    /// already moved on the rail, so capping it silently would absorb the
    /// breach, and the sealed receipt is the evidence that a settlement
    /// exceeded its authorization.
    ///
    /// A resolution denominated in another currency is refused
    /// `currency-mismatch` **and leaves the hold outstanding**, as a
    /// wrong-subject cancellation does: a malformed resolution must not be the
    /// one move that loses the bound. A hold already resolved, or never placed,
    /// is refused `already-resolved` and resolves nothing.
    pub fn settle_priced(
        &mut self,
        grant: &Grant,
        hold: HoldId,
        measured: Energy,
        settled: &Price,
        facts: &FlowFacts,
    ) -> Decision {
        let gid = grant.id();
        let joules_left = |rt: &Self| grant.budget_uj.saturating_sub(rt.committed(&gid));
        if let Some(funds) = &grant.budget_funds {
            if !funds.same_currency(&settled.currency) {
                let left = joules_left(self);
                return Decision::refused(DenyReason::CurrencyMismatch, nothing_ran(), left);
            }
        }
        let Some(held) = self.take_hold(&gid, hold) else {
            let left = joules_left(self);
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), left);
        };
        let mut decision = self.charge_flow(grant, measured, facts);
        if let Some(funds) = &grant.budget_funds {
            let spent_m = self.spent_minor(&gid);
            let debited = settled.minor.min(funds.minor.saturating_sub(self.net_minor(&gid)));
            self.spent_minor.insert(gid, spent_m.saturating_add(debited));
            decision.debited_minor = debited;
            if settled.minor > held.minor && decision.is_allow() {
                decision.verdict = Verdict::Deny(DenyReason::FundsExceeded);
            }
        }
        decision
    }

    /// **Capture part of a hold** (§8.1): debit `amount` of what it reserved
    /// and the joules `measured` since the last capture, leaving the rest
    /// reserved for a later capture or the final resolution.
    ///
    /// This is what metered work that bills as it goes needs — a stream paid
    /// per chunk, a session billed per period — and what a single resolution
    /// cannot express: one authorization, drawn down in steps, each step its
    /// own sealed decision.
    ///
    /// A capture is a decision **before** the money moves, so unlike the final
    /// resolution it refuses cleanly: more than the hold has left is
    /// `funds-exceeded` with nothing debited and the hold intact; past the
    /// hold's capture deadline is `expired`; another currency is
    /// `currency-mismatch`; an unknown hold is `already-resolved`. None of
    /// those consumes the hold. An allowed capture leaves it outstanding too,
    /// with less reserved — only [`settle_priced`](Self::settle_priced) and
    /// [`cancel`](Self::cancel) resolve it.
    pub fn capture_priced(
        &mut self,
        grant: &Grant,
        hold: HoldId,
        measured: Energy,
        amount: &Price,
        now: u64,
        facts: &FlowFacts,
    ) -> Decision {
        let links = [grant];
        if let Some(reason) = self.capture_refusal(&links, hold, amount, now) {
            let left = grant.budget_uj.saturating_sub(self.committed(&grant.id()));
            return Decision::refused(reason, nothing_ran(), left);
        }
        let mut decision = self.charge_flow(grant, measured, facts);
        let minors = self.capture_apply(&links, hold, amount, &[decision.debited_uj], decision.tainted_uj);
        decision.debited_minor = minors[0];
        decision
    }

    /// [`capture_priced`](Self::capture_priced) through a delegation chain:
    /// the draw is debited from **every** link and leaves every link's
    /// reservation that much smaller.
    ///
    /// One rule set governs both. A single grant is a chain of one link, and
    /// the money side of a capture — which refusals come before anything
    /// moves, what is drawn from which reservation — is one implementation
    /// over a list of links, so a rule added to the lifecycle cannot land for
    /// a lone grant and be missing for a delegated one.
    pub fn capture_chained_priced(
        &mut self,
        chain: &[SignedGrant],
        hold: HoldId,
        measured: Energy,
        amount: &Price,
        now: u64,
    ) -> Decision {
        let links: Vec<&Grant> = chain.iter().map(|sg| &sg.grant).collect();
        if let Some(reason) = self.capture_refusal(&links, hold, amount, now) {
            return Decision::refused(reason, nothing_ran(), self.chain_left(chain));
        }
        let mut decision = self.charge_chained(chain, measured);
        let per_link: Vec<u64> = if decision.chain_debited_uj.is_empty() {
            vec![decision.debited_uj; links.len()]
        } else {
            decision.chain_debited_uj.clone()
        };
        let mut minors = self.capture_apply(&links, hold, amount, &per_link, 0);
        decision.debited_minor = minors.last().copied().unwrap_or(0);
        if minors.iter().all(|m| *m == decision.debited_minor) {
            minors.clear();
        }
        decision.chain_debited_minor = minors;
        decision
    }

    /// Why a capture of `amount` from `hold` is refused across `links`, before
    /// anything moves — or `None` where it may proceed. The whole of the
    /// capture rule's refusals, for one link or many.
    fn capture_refusal(&self, links: &[&Grant], hold: HoldId, amount: &Price, now: u64) -> Option<DenyReason> {
        if links.iter().any(|g| g.budget_funds.as_ref().is_some_and(|f| !f.same_currency(&amount.currency))) {
            return Some(DenyReason::CurrencyMismatch);
        }
        let held = |g: &Grant| self.holds.get(&g.id()).and_then(|hs| hs.get(&hold)).copied();
        let Some(leaf) = links.last().and_then(|g| held(g)) else {
            return Some(DenyReason::AlreadyResolved);
        };
        if leaf.deadline.is_some_and(|d| now > d) {
            return Some(DenyReason::Expired);
        }
        let over = links
            .iter()
            .any(|g| g.budget_funds.is_some() && held(g).is_none_or(|h| amount.minor > h.minor));
        over.then_some(DenyReason::FundsExceeded)
    }

    /// Draw a capture from every link's reservation and enter it in every
    /// link's spend: the joules each link was just debited, and `amount` on
    /// each link that carries a money ceiling. Returns the money debited per
    /// link.
    fn capture_apply(
        &mut self,
        links: &[&Grant],
        hold: HoldId,
        amount: &Price,
        debited_uj: &[u64],
        tainted_uj: u64,
    ) -> Vec<u64> {
        let mut minors = Vec::with_capacity(links.len());
        for (g, uj) in links.iter().zip(debited_uj) {
            let gid = g.id();
            let minor = if g.budget_funds.is_some() { amount.minor } else { 0 };
            if let Some(h) = self.holds.get_mut(&gid).and_then(|hs| hs.get_mut(&hold)) {
                // What was just debited was part of what the hold reserved, so
                // it leaves the reservation as it enters the spend.
                h.uj = h.uj.saturating_sub(*uj);
                h.tainted_uj = h.tainted_uj.saturating_sub(tainted_uj);
                h.minor = h.minor.saturating_sub(minor);
                h.drawn_minor = h.drawn_minor.saturating_add(minor);
            }
            let spent = self.spent_minor(&gid);
            self.spent_minor.insert(gid, spent.saturating_add(minor));
            minors.push(minor);
        }
        minors
    }

    /// Return to a hold money a capture drew from it that never moved (§8.1).
    ///
    /// A capture is decided before the money moves, so a rail can refuse a
    /// capture the gate has already allowed. Where the rail's answer is a
    /// definite no, nothing moved: the capture's money debit is taken off
    /// the spend and returned to the hold's reservation, so it may be drawn
    /// again or released, and the receipt of the reversal names the capture.
    /// Joules are not returned: the work the capture paid for ran, and was
    /// measured.
    ///
    /// Refused `already-resolved` once the hold is settled, cancelled or
    /// never existed; `currency-mismatch` in another currency than the
    /// grant's; and `funds-exceeded` for more than captures have drawn from
    /// this hold and not already been returned. A refusal changes nothing.
    pub fn reverse_capture(&mut self, grant: &Grant, hold: HoldId, amount: &Price) -> Decision {
        let left = grant.budget_uj.saturating_sub(self.committed(&grant.id()));
        self.reverse_links(&[grant], hold, amount, left)
    }

    /// [`reverse_capture`](Self::reverse_capture) through a delegation chain:
    /// the money returns to the hold on **every link that carries a money
    /// ceiling**, as the capture drew it from every one (§8.1).
    pub fn reverse_capture_chained(&mut self, chain: &[SignedGrant], hold: HoldId, amount: &Price) -> Decision {
        let links: Vec<&Grant> = chain.iter().map(|sg| &sg.grant).collect();
        let left = self.chain_left(chain);
        self.reverse_links(&links, hold, amount, left)
    }

    /// The reversal rule, for one link or many. Every funded link is checked
    /// before any is changed, so a reversal is refused whole or applied
    /// whole.
    fn reverse_links(&mut self, links: &[&Grant], hold: HoldId, amount: &Price, left: u64) -> Decision {
        if links.iter().any(|g| g.budget_funds.as_ref().is_some_and(|f| !f.same_currency(&amount.currency))) {
            return Decision::refused(DenyReason::CurrencyMismatch, nothing_ran(), left);
        }
        let held = |rt: &Self, g: &Grant| rt.holds.get(&g.id()).and_then(|hs| hs.get(&hold)).copied();
        if links.last().and_then(|g| held(self, g)).is_none() {
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), left);
        }
        let funded: Vec<&Grant> = links.iter().copied().filter(|g| g.budget_funds.is_some()).collect();
        let fits = !funded.is_empty() && funded.iter().all(|g| held(self, g).is_some_and(|h| amount.minor <= h.drawn_minor));
        if !fits && amount.minor > 0 {
            return Decision::refused(DenyReason::FundsExceeded, nothing_ran(), left);
        }
        for g in funded {
            let gid = g.id();
            if let Some(h) = self.holds.get_mut(&gid).and_then(|hs| hs.get_mut(&hold)) {
                h.drawn_minor -= amount.minor;
                h.minor = h.minor.saturating_add(amount.minor);
            }
            let spent = self.spent_minor(&gid);
            self.spent_minor.insert(gid, spent.saturating_sub(amount.minor));
        }
        Decision {
            verdict: Verdict::Allow,
            cost: nothing_ran(),
            budget_remaining_uj: left,
            debited_uj: 0,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        }
    }

    /// What a hold still reserves, where it is outstanding: `(joules, money)`.
    pub fn hold_remaining(&self, grant_id: &ContentId, hold: HoldId) -> Option<(u64, u64)> {
        self.holds.get(grant_id).and_then(|hs| hs.get(&hold)).map(|h| (h.uj, h.minor))
    }

    /// **Reclaim** a hold's money after its capture deadline (§8.1): the
    /// payer's unilateral way out of a reservation nobody resolved.
    ///
    /// Anyone may call it, because all it can do is return a payer's own money
    /// once the time the payer agreed to has run out; before the deadline, or
    /// on a hold that states none, it is refused `caveat-unsatisfied` and
    /// changes nothing.
    ///
    /// It releases **money only**. The joule reservation stays until the hold
    /// is settled or cancelled, for the reason a cancellation debits rather
    /// than refunds: joules the work burned are burned, and a deadline that
    /// released them unrecorded would make waiting a way to spend for free.
    /// Money is different — an uncaptured reservation never moved.
    pub fn reclaim(&mut self, grant: &Grant, hold: HoldId, now: u64) -> (Decision, u64) {
        let left = grant.budget_uj.saturating_sub(self.committed(&grant.id()));
        self.reclaim_links(&[grant], hold, now, left)
    }

    /// [`reclaim`](Self::reclaim) through a delegation chain: the money
    /// reservation is released on **every** link, and the joule reservation
    /// stays on every link. Returns what the leaf released.
    pub fn reclaim_chained(&mut self, chain: &[SignedGrant], hold: HoldId, now: u64) -> (Decision, u64) {
        let links: Vec<&Grant> = chain.iter().map(|sg| &sg.grant).collect();
        let left = self.chain_left(chain);
        self.reclaim_links(&links, hold, now, left)
    }

    /// The reclaim rule, for one link or many.
    fn reclaim_links(&mut self, links: &[&Grant], hold: HoldId, now: u64, left: u64) -> (Decision, u64) {
        let deadline = links
            .last()
            .and_then(|g| self.holds.get(&g.id()))
            .and_then(|hs| hs.get(&hold))
            .map(|h| h.deadline);
        let Some(deadline) = deadline else {
            return (Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), left), 0);
        };
        if !deadline.is_some_and(|d| now > d) {
            return (Decision::refused(DenyReason::CaveatUnsatisfied, nothing_ran(), left), 0);
        }
        let mut released = 0;
        for g in links {
            if let Some(h) = self.holds.get_mut(&g.id()).and_then(|hs| hs.get_mut(&hold)) {
                released = std::mem::take(&mut h.minor);
            }
        }
        let decision = Decision {
            verdict: Verdict::Allow,
            cost: nothing_ran(),
            budget_remaining_uj: left,
            debited_uj: 0,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        };
        (decision, released)
    }

    /// **Refund** captured money to a grant (§8.1): lower its net spend by
    /// `amount`, up to what was debited and not already refunded.
    ///
    /// Only the grant's **issuer** may record one. A refund returns room under
    /// the money ceiling, so a subject able to declare its own refunds could
    /// spend, "refund", and spend again without limit — the ceiling would bind
    /// only the honest. The issuer is the party whose money it is and who
    /// already holds the strictly greater power to re-issue.
    ///
    /// The gross debit never decreases; the refund is counted beside it, so
    /// both stay monotonic and a replay restores each from its own receipts.
    /// **Joules have no refund.** Money that comes back was never spent;
    /// energy that was burned stays burned.
    pub fn refund(&mut self, grant: &Grant, caller: Did, amount: &Price) -> Decision {
        let gid = grant.id();
        let left = grant.budget_uj.saturating_sub(self.committed(&gid));
        if caller != grant.issuer {
            return Decision::refused(DenyReason::WrongSubject, nothing_ran(), left);
        }
        let Some(funds) = &grant.budget_funds else {
            return Decision::refused(DenyReason::FundsExceeded, nothing_ran(), left);
        };
        if !funds.same_currency(&amount.currency) {
            return Decision::refused(DenyReason::CurrencyMismatch, nothing_ran(), left);
        }
        if amount.minor > self.net_minor(&gid) {
            return Decision::refused(DenyReason::FundsExceeded, nothing_ran(), left);
        }
        let r = self.refunded_minor(&gid);
        self.refunded_minor.insert(gid, r.saturating_add(amount.minor));
        Decision {
            verdict: Verdict::Allow,
            cost: nothing_ran(),
            budget_remaining_uj: left,
            debited_uj: 0,
            chain_debited_uj: Vec::new(),
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        }
    }

    pub fn cancel(
        &mut self,
        grant: &Grant,
        hold: HoldId,
        caller: Did,
        measured: Energy,
        facts: &FlowFacts,
    ) -> Decision {
        let gid = grant.id();
        let remaining = || grant.budget_uj.saturating_sub(self.committed(&gid));
        if caller != grant.subject && caller != grant.issuer {
            let r = remaining();
            return Decision::refused(DenyReason::WrongSubject, nothing_ran(), r);
        }
        if !self.has_hold(&gid, hold) {
            let r = remaining();
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), r);
        }
        self.settle(grant, hold, measured, facts)
    }

    /// The flow-aware [`decide`](Self::decide): the one-shot path with flow facts
    /// checked at 6c. A tainted argument is denied `TaintedFlow` before the budget
    /// test, so — like a tool-poisoning denial — it debits zero joules.
    pub fn decide_flow(
        &mut self,
        frame: &Frame,
        sg: &SignedGrant,
        caller: Did,
        cost: Energy,
        now: u64,
        facts: &FlowFacts,
    ) -> Decision {
        let g = &sg.grant;
        let gid = g.id();
        let remaining = g.budget_uj.saturating_sub(self.committed(&gid));
        let deny = |r: DenyReason| Decision::refused(r, cost, remaining);
        if let Some(r) = self.check(frame, sg, caller, now, Some(facts)) {
            return deny(r);
        }
        if let Some(r) = caveats_unsatisfied(g, frame, caller, Some(cost.uj()), now)
            .or_else(|| self.window_unsatisfied(g, &frame.payload_hash, Some(cost.uj()), now))
        {
            return deny(r);
        }
        let spent = self.spent(&gid);
        let committed = self.committed(&gid);
        let c = cost.uj();
        if committed.saturating_add(c) > g.budget_uj {
            return deny(DenyReason::BudgetExceeded);
        }
        self.spent_uj.insert(gid, spent + c);
        self.admit_windows(g, frame.payload_hash, now);
        self.debit_windows(g, c, Some(now));
        let tainted_uj = if facts.is_bottom() { 0 } else { c };
        if tainted_uj > 0 {
            let accrued = self.spent_tainted(&gid).saturating_add(c);
            self.spent_tainted_uj.insert(gid, accrued);
        }
        Decision { tainted_uj, ..Decision::allowed(cost, c, g.budget_uj - (committed + c)) }
    }

    /// Decide a frame against a full delegation chain, **root first, leaf
    /// last** — multi-hop enforcement (SPEC §4.1).
    ///
    /// Beyond the per-grant checks of [`Runtime::decide`], this verifies the
    /// chain's structure and signatures hop by hop, denies if **any** link is
    /// revoked (a subtree dies with its ancestor), and conserves energy across
    /// siblings: the cost must fit the remaining budget of **every** grant in
    /// the chain, and on allow it is debited from all of them. Two children
    /// delegated from one root therefore share the root's budget — delegation
    /// can never mint joules.
    pub fn decide_chained(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        cost: Energy,
        now: u64,
    ) -> Decision {
        // No flow facts: a chain whose links carry a flow ceiling fails closed
        // (the un-migrated path), exactly as `decide` does with `check(.., None)`.
        self.decide_chained_inner(frame, chain, caller, cost, now, None, None)
    }

    /// [`decide_priced`](Self::decide_priced) over a delegation chain: both
    /// ceilings on **every** link (§4.8, §4.2). The joule ceiling is checked
    /// first on every link, then the money ceiling of every link that has
    /// one, refusing a cost in another currency. On allow both dimensions are
    /// debited from every link, so siblings share their parent's money as they
    /// share its joules; on deny neither is debited.
    pub fn decide_chained_priced(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        cost: Energy,
        price: &Price,
        now: u64,
    ) -> Decision {
        self.decide_chained_inner(frame, chain, caller, cost, now, None, Some(price))
    }

    /// The flow-aware [`decide_chained`](Self::decide_chained): the chain path with
    /// the argument's provenance checked against the chain's attenuated ceiling and
    /// the resource's taint floor, denied before any link is debited.
    pub fn decide_chained_flow(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        cost: Energy,
        now: u64,
        facts: &FlowFacts,
    ) -> Decision {
        self.decide_chained_inner(frame, chain, caller, cost, now, Some(facts), None)
    }

    #[allow(clippy::too_many_arguments)]
    fn decide_chained_inner(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        cost: Energy,
        now: u64,
        facts: Option<&FlowFacts>,
        price: Option<&Price>,
    ) -> Decision {
        let leaf_remaining = chain
            .last()
            .map_or(0, |l| l.grant.budget_uj.saturating_sub(self.committed(&l.grant.id())));
        let deny = |r: DenyReason| Decision::refused(r, cost, leaf_remaining);
        let leaf = match self.check_chained(frame, chain, caller, now, facts, Some(cost.uj())) {
            Ok(leaf) => leaf,
            Err(r) => return deny(r),
        };
        // Energy conservation: the cost must fit every link's remaining budget,
        // less any unsettled hold on the link (§8.1).
        let c = cost.uj();
        for sg in chain {
            let gid = sg.grant.id();
            if self.committed(&gid).saturating_add(c) > sg.grant.budget_uj {
                return deny(DenyReason::BudgetExceeded);
            }
        }
        // The money ceiling of every link that has one (§4.8), checked after
        // joules so that when both bind the receipt names energy. A link with
        // no money ceiling is bounded by joules alone.
        if let Some(price) = price {
            for sg in chain {
                if let Some(funds) = &sg.grant.budget_funds {
                    if !funds.same_currency(&price.currency) {
                        return deny(DenyReason::CurrencyMismatch);
                    }
                    if self.committed_minor(&sg.grant.id()).saturating_add(price.minor) > funds.minor {
                        return deny(DenyReason::FundsExceeded);
                    }
                }
            }
        }
        // Allow — debit every link, so sibling delegations share their root,
        // in money as in joules. A link with no money ceiling is debited none.
        let mut minors = Vec::with_capacity(chain.len());
        for sg in chain {
            let gid = sg.grant.id();
            let s = self.spent(&gid) + c;
            self.spent_uj.insert(gid, s);
            let mut debited_minor = 0;
            if let (Some(price), Some(_)) = (price, &sg.grant.budget_funds) {
                let m = self.spent_minor(&gid) + price.minor;
                self.spent_minor.insert(gid, m);
                debited_minor = price.minor;
            }
            minors.push(debited_minor);
        }
        let leaf_minor = minors.last().copied().unwrap_or(0);
        if minors.iter().all(|m| *m == leaf_minor) {
            minors.clear();
        }
        // Every link's windows (§4.12) count the call, so a parent's window
        // covers what its delegates spend.
        for sg in chain {
            self.admit_windows(&sg.grant, frame.payload_hash, now);
            self.debit_windows(&sg.grant, c, Some(now));
        }
        // A tainted chained call also depletes each link's tainted sub-budget.
        let tainted = facts.map(|f| !f.is_bottom()).unwrap_or(false);
        if tainted {
            for sg in chain {
                let gid = sg.grant.id();
                let accrued = self.spent_tainted(&gid).saturating_add(c);
                self.spent_tainted_uj.insert(gid, accrued);
            }
        }
        Decision {
            debited_minor: leaf_minor,
            chain_debited_minor: minors,
            tainted_uj: if tainted { c } else { 0 },
            ..Decision::allowed(cost, c, leaf.grant.budget_uj - self.committed(&leaf.grant.id()))
        }
    }

    /// Every check of a chained decision except the budget: structure,
    /// signatures and attenuation, revocation, the trust root, expiry, the
    /// leaf's audience and holder, flow, and every link's caveats. `cost_uj` is
    /// `None` in the two-phase metered path, where cost-dependent caveats wait
    /// for the debit. Returns the leaf.
    fn check_chained<'c>(
        &self,
        frame: &Frame,
        chain: &'c [SignedGrant],
        caller: Did,
        now: u64,
        facts: Option<&FlowFacts>,
        cost_uj: Option<u64>,
    ) -> Result<&'c SignedGrant, DenyReason> {
        let leaf = chain.last().ok_or(DenyReason::ChainBroken)?;
        // Structure + signatures + attenuation invariants, hop by hop.
        if let Err(e) = verify_chain(chain) {
            return Err(match e {
                GrantError::Amplifies(_) => DenyReason::AttenuationViolation,
                GrantError::BadSignature | GrantError::SigShape(_) => DenyReason::BadSignature,
                _ => DenyReason::ChainBroken,
            });
        }
        // A revoked ancestor kills the whole subtree.
        if self.revocations.hits_chain(chain) {
            return Err(DenyReason::Revoked);
        }
        // The chain's ROOT issuer must be a configured trust root for the
        // resource (SPEC §7) — authority anchors only in keys this enforcement
        // point was configured to honor.
        if !self.root_honored(&frame.resource, &chain[0].grant.issuer) {
            return Err(DenyReason::UntrustedRoot);
        }
        // No link may be expired at decision time.
        if chain.iter().any(|sg| sg.grant.is_expired(now)) {
            return Err(DenyReason::Expired);
        }
        // The leaf-level checks: trust, audience, holder, capability.
        if frame.trust == Trust::Data {
            return Err(DenyReason::UntrustedControl);
        }
        if frame.grant_id != leaf.grant.id() {
            return Err(DenyReason::WrongResource);
        }
        if caller != leaf.grant.subject {
            return Err(DenyReason::WrongSubject);
        }
        if frame.resource != leaf.grant.capability.resource {
            return Err(DenyReason::WrongResource);
        }
        if !leaf.grant.capability.actions.iter().any(|a| a == &frame.action) {
            return Err(DenyReason::ActionNotGranted);
        }
        // 6c (chain form): flow against the chain's attenuated ceiling and the
        // resource's taint floor. The ceiling is the meet over every link, so a
        // chain is at most as permissive as its strictest hop, and a facts-less
        // call under a ceilinged chain fails closed — mirroring the leaf gate.
        {
            let chained = chain_ceiling(chain);
            if let Some(f) = facts {
                if self.taint_floor.refuses(&frame.resource, &f.label) {
                    return Err(DenyReason::TaintedFlow);
                }
            }
            match (chained, facts) {
                (None, _) => {}
                (Some(_), None) => return Err(DenyReason::TaintedFlow),
                (Some(ceiling), Some(f)) => {
                    if !ceiling.admits(&f.label) {
                        return Err(DenyReason::TaintedFlow);
                    }
                }
            }
        }
        // Caveats (§4.9), on every link. `verify_chain` has refused a child that
        // dropped one of its parent's, so the leaf carries them all; evaluating
        // each link as well keeps this decision sound on its own.
        for sg in chain {
            if let Some(r) = caveats_unsatisfied(&sg.grant, frame, caller, cost_uj, now)
                .or_else(|| self.window_unsatisfied(&sg.grant, &frame.payload_hash, cost_uj, now))
            {
                return Err(r);
            }
        }
        Ok(leaf)
    }

    /// What a call can spend under `chain` before some link binds: the least
    /// any link has left, less any unsettled hold on it (§8.1).
    fn chain_remaining(&self, chain: &[SignedGrant]) -> u64 {
        chain
            .iter()
            .map(|sg| sg.grant.budget_uj.saturating_sub(self.committed(&sg.grant.id())))
            .min()
            .unwrap_or(0)
    }

    /// Phase one of metered enforcement over a delegation chain, root first:
    /// [`authorize`](Self::authorize) for a delegated grant. Every check of
    /// [`decide_chained`](Self::decide_chained) runs, except that the budget
    /// test is "every link has budget left" and cost-dependent caveats wait for
    /// [`charge_chained`](Self::charge_chained). Debits nothing. The reported
    /// `budget_remaining_uj` is the least any link has left, less any
    /// unsettled hold on it (SPEC §8.1).
    ///
    /// An allow here places no hold of its own, so until its work is charged
    /// a later decision through any of its links does not count that work:
    /// an enforcement point that may decide another call before charging this
    /// one uses [`hold_chained`](Self::hold_chained).
    pub fn authorize_chained(&mut self, frame: &Frame, chain: &[SignedGrant], caller: Did, now: u64) -> Decision {
        self.authorize_chained_for(frame, chain, caller, now, 1)
    }

    /// [`authorize_chained`](Self::authorize_chained) for a call that needs
    /// `need_uj` of every link's budget, such as one its caller holds to a
    /// joule ceiling before running it. A link with less left denies the call
    /// `budget-exceeded` here, before it is admitted, so a call refused for
    /// its ceiling is not counted in any window (§4.12). Like
    /// [`authorize_chained`](Self::authorize_chained), it counts an unsettled
    /// hold on any link and places none.
    pub fn authorize_chained_for(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
        need_uj: u64,
    ) -> Decision {
        match self.chained_refusal(frame, chain, caller, now, need_uj) {
            Err(refused) => refused,
            Ok(remaining) => {
                for sg in chain {
                    self.admit_windows(&sg.grant, frame.payload_hash, now);
                }
                Decision::allowed(nothing_ran(), 0, remaining)
            }
        }
    }

    /// Every check [`authorize_chained_for`](Self::authorize_chained_for)
    /// makes, admitting nothing, as [`flow_refusal`](Self::flow_refusal) is
    /// for a lone grant.
    fn chained_refusal(
        &self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
        need_uj: u64,
    ) -> Result<u64, Decision> {
        let remaining = self.chain_remaining(chain);
        match self.check_chained(frame, chain, caller, now, None, None) {
            Err(r) => Err(Decision::refused(r, nothing_ran(), remaining)),
            Ok(_) if remaining < need_uj.max(1) => {
                Err(Decision::refused(DenyReason::BudgetExceeded, nothing_ran(), remaining))
            }
            Ok(_) => Ok(remaining),
        }
    }

    /// [`hold`](Self::hold) over a delegation chain, root first: authorize the
    /// call as [`authorize_chained`](Self::authorize_chained) does and, on
    /// allow, place one hold naming every link, in the same step (SPEC §8.1).
    /// A refusal places no hold and returns `None`. Like `authorize_chained`
    /// it takes no flow facts, so a chain under a flow ceiling fails closed.
    ///
    /// The returned `held_uj`, sealed with every link's id
    /// (`chain_ids`), is the most any link has left: the work's
    /// [`settle_chained`](Self::settle_chained) debits every link, each
    /// saturating at its own ceiling, so it can debit a link up to what that
    /// link has left, and the one figure a hold states for every link it
    /// names must cover the largest. The runtime counts that figure against
    /// every link, as a replay reads a chained hold nothing settles, so each
    /// link has nothing left while the hold is unsettled: a sibling
    /// delegate's call through a held ancestor is decided against the
    /// ancestor's remainder less the hold, as the holder's own next call is.
    pub fn hold_chained(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
    ) -> (Decision, Option<HoldHandle>) {
        let decision = self.authorize_chained(frame, chain, caller, now);
        if !decision.is_allow() {
            return (decision, None);
        }
        let uj = self.hold_bound_chained(chain);
        let held = Held { uj, tainted_uj: 0, minor: 0, deadline: None, drawn_minor: 0 };
        let links: Vec<(ContentId, Held)> = chain.iter().map(|sg| (sg.grant.id(), held)).collect();
        let id = self.place_hold_chained(&links);
        (decision, Some(HoldHandle { id, uj, minor: 0 }))
    }

    /// [`hold_priced`](Self::hold_priced) through a delegation chain: a money
    /// bound reserved on **every link that carries a money ceiling** (§4.8,
    /// §8.1), beside the joule bound of [`hold_chained`](Self::hold_chained).
    ///
    /// A delegated agent doing metered work spends its parent's money as it
    /// spends its parent's joules, so the reservation has to stand on the
    /// parent too: reserved only on the leaf, two siblings could each hold the
    /// whole of what their shared parent has left. A link in another currency
    /// refuses the hold `currency-mismatch`; a link the maximum will not fit
    /// refuses it `funds-exceeded`; either way nothing is reserved anywhere.
    /// A link with no money ceiling reserves none.
    pub fn hold_chained_priced(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
        ceiling: &Price,
    ) -> (Decision, Option<HoldHandle>) {
        self.hold_chained_priced_inner(frame, chain, caller, now, 1, ceiling, None)
    }

    /// [`hold_chained_priced`](Self::hold_chained_priced) for a call that
    /// needs `need_uj` of every link's budget, as
    /// [`authorize_chained_for`](Self::authorize_chained_for) is for
    /// [`authorize_chained`](Self::authorize_chained): a link with less left
    /// refuses it `budget-exceeded` before anything is reserved or admitted.
    /// An enforcement point that holds each call to a joule ceiling of its
    /// own and to a money maximum decides both here in one step, so the call
    /// enters its windows once, and only when both fit.
    #[allow(clippy::too_many_arguments)]
    pub fn hold_chained_priced_for(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
        need_uj: u64,
        ceiling: &Price,
    ) -> (Decision, Option<HoldHandle>) {
        self.hold_chained_priced_inner(frame, chain, caller, now, need_uj, ceiling, None)
    }

    /// [`hold_chained_priced`](Self::hold_chained_priced) with a capture
    /// deadline, as [`hold_priced_until`](Self::hold_priced_until) gives a
    /// lone grant.
    pub fn hold_chained_priced_until(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
        ceiling: &Price,
        capture_deadline: u64,
    ) -> (Decision, Option<HoldHandle>) {
        self.hold_chained_priced_inner(frame, chain, caller, now, 1, ceiling, Some(capture_deadline))
    }

    /// The joules a chained hold reserves on every link: the tightest
    /// per-invocation ceiling any link states (§4.9), else the most any link
    /// has left — from the committed spend, so a second hold cannot size
    /// itself against room the first reserves.
    ///
    /// The per-call ceiling is what lets **sibling delegates run metered work
    /// at once**. Without one, a hold reserves the shared parent's whole
    /// remainder and every sibling waits; with one, each reserves its bound
    /// and the parent admits as many as fit.
    pub fn hold_bound_chained(&self, chain: &[SignedGrant]) -> u64 {
        let whole = chain
            .iter()
            .map(|sg| sg.grant.budget_uj.saturating_sub(self.committed(&sg.grant.id())))
            .max()
            .unwrap_or(0);
        let per_call = chain
            .iter()
            .flat_map(|sg| sg.grant.caveats.iter().filter_map(|c| c.max_cost_uj()))
            .min();
        match per_call {
            Some(p) => p.min(whole),
            None => whole,
        }
    }

    #[allow(clippy::too_many_arguments)]
    fn hold_chained_priced_inner(
        &mut self,
        frame: &Frame,
        chain: &[SignedGrant],
        caller: Did,
        now: u64,
        need_uj: u64,
        ceiling: &Price,
        deadline: Option<u64>,
    ) -> (Decision, Option<HoldHandle>) {
        let remaining = match self.chained_refusal(frame, chain, caller, now, need_uj) {
            Err(refused) => return (refused, None),
            Ok(remaining) => remaining,
        };
        for sg in chain {
            if let Some(funds) = &sg.grant.budget_funds {
                let reason = if !funds.same_currency(&ceiling.currency) {
                    Some(DenyReason::CurrencyMismatch)
                } else if self.committed_minor(&sg.grant.id()).saturating_add(ceiling.minor) > funds.minor {
                    Some(DenyReason::FundsExceeded)
                } else {
                    None
                };
                if let Some(reason) = reason {
                    return (Decision::refused(reason, nothing_ran(), self.chain_left(chain)), None);
                }
            }
        }
        // Admitted only now that the money fits on every link: a call refused
        // for money did not run, and must not fill a window (§4.12).
        for sg in chain {
            self.admit_windows(&sg.grant, frame.payload_hash, now);
        }
        let decision = Decision::allowed(nothing_ran(), 0, remaining);
        let uj = self.hold_bound_chained(chain);
        let links: Vec<(ContentId, Held)> = chain
            .iter()
            .map(|sg| {
                let minor = if sg.grant.budget_funds.is_some() { ceiling.minor } else { 0 };
                (sg.grant.id(), Held { uj, tainted_uj: 0, minor, deadline, drawn_minor: 0 })
            })
            .collect();
        let minor = links.last().map_or(0, |(_, h)| h.minor);
        let id = self.place_hold_chained(&links);
        (decision, Some(HoldHandle { id, uj, minor }))
    }

    /// Resolve a [`hold_chained_priced`](Self::hold_chained_priced): the
    /// measured joules and the settled money are debited from **every** link,
    /// and each link's reservation is released.
    ///
    /// As [`settle_priced`](Self::settle_priced): a settlement over what any
    /// link reserved debits and denies `funds-exceeded`; one in a currency a
    /// link is not denominated in is refused and leaves the hold outstanding;
    /// a hold not outstanding on the leaf is `already-resolved`.
    pub fn settle_chained_priced(
        &mut self,
        chain: &[SignedGrant],
        hold: HoldId,
        measured: Energy,
        settled: &Price,
    ) -> Decision {
        let foreign = chain.iter().any(|sg| {
            sg.grant.budget_funds.as_ref().is_some_and(|f| !f.same_currency(&settled.currency))
        });
        if foreign {
            return Decision::refused(DenyReason::CurrencyMismatch, nothing_ran(), self.chain_left(chain));
        }
        let held = chain.last().is_some_and(|leaf| self.has_hold(&leaf.grant.id(), hold));
        if !held {
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), self.chain_left(chain));
        }
        let mut over = false;
        let mut reserved = Vec::with_capacity(chain.len());
        for sg in chain {
            let h = self.take_hold(&sg.grant.id(), hold).unwrap_or_default();
            if sg.grant.budget_funds.is_some() && settled.minor > h.minor {
                over = true;
            }
            reserved.push(h);
        }
        let mut decision = self.charge_chained(chain, measured);
        let mut minors = Vec::with_capacity(chain.len());
        for sg in chain {
            let gid = sg.grant.id();
            let debited = match &sg.grant.budget_funds {
                Some(funds) => {
                    let d = settled.minor.min(funds.minor.saturating_sub(self.net_minor(&gid)));
                    let spent = self.spent_minor(&gid);
                    self.spent_minor.insert(gid, spent.saturating_add(d));
                    d
                }
                None => 0,
            };
            minors.push(debited);
        }
        decision.debited_minor = minors.last().copied().unwrap_or(0);
        if minors.iter().any(|m| *m != decision.debited_minor) {
            decision.chain_debited_minor = minors;
        }
        if over && decision.is_allow() {
            decision.verdict = Verdict::Deny(DenyReason::FundsExceeded);
        }
        decision
    }

    /// Settle a [`hold_chained`](Self::hold_chained) with what its work
    /// measured (SPEC §8.1): the hold stops counting on every link, and the
    /// measured cost is debited as [`charge_chained`](Self::charge_chained)
    /// debits it, each link saturating at its own ceiling. Returns the
    /// accounting `Decision` to seal as the receipt that settles the hold.
    ///
    /// As with [`settle`](Self::settle), a chained hold resolves once: a settle
    /// with no hold on the leaf is refused `already-resolved` and debits
    /// nothing on any link.
    pub fn settle_chained(&mut self, chain: &[SignedGrant], hold: HoldId, measured: Energy) -> Decision {
        let held = chain.last().is_some_and(|leaf| self.has_hold(&leaf.grant.id(), hold));
        if !held {
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), self.chain_left(chain));
        }
        for sg in chain {
            self.take_hold(&sg.grant.id(), hold);
        }
        self.charge_chained(chain, measured)
    }

    /// [`cancel`](Self::cancel) over a chain: the cost of the work that ran is
    /// debited from **every** link, as a settle's is (§4.2's conservation), so
    /// an abandoned delegated run cannot leave its ancestors' budgets untouched
    /// — or a delegate could spend its parent's joules by always cancelling.
    /// The right to cancel is the leaf subject's, or any link issuer's, since an
    /// issuer anywhere up the chain can already revoke the subtree (§4.3).
    pub fn cancel_chained(
        &mut self,
        chain: &[SignedGrant],
        hold: HoldId,
        caller: Did,
        measured: Energy,
    ) -> Decision {
        let Some(leaf) = chain.last() else {
            return Decision::refused(DenyReason::ChainBroken, nothing_ran(), 0);
        };
        if caller != leaf.grant.subject && !chain.iter().any(|sg| caller == sg.grant.issuer) {
            return Decision::refused(DenyReason::WrongSubject, nothing_ran(), self.chain_left(chain));
        }
        if !self.has_hold(&leaf.grant.id(), hold) {
            return Decision::refused(DenyReason::AlreadyResolved, nothing_ran(), self.chain_left(chain));
        }
        self.settle_chained(chain, hold, measured)
    }

    /// The least any link has left to decide against, holds counted (§8.1).
    fn chain_left(&self, chain: &[SignedGrant]) -> u64 {
        chain
            .iter()
            .map(|sg| sg.grant.budget_uj.saturating_sub(self.committed(&sg.grant.id())))
            .min()
            .unwrap_or(0)
    }

    /// Phase two over a chain: debit a measured cost against **every** link,
    /// each saturating at its own ceiling, so siblings delegated from one
    /// parent share it here as they do in [`decide_chained`](Self::decide_chained).
    /// A cost-dependent caveat on any link binds now; a breach denies the
    /// verdict, and the joules stay debited because they were spent (§4.9).
    /// It settles no hold: a call placed with
    /// [`hold_chained`](Self::hold_chained) is charged by
    /// [`settle_chained`](Self::settle_chained).
    pub fn charge_chained(&mut self, chain: &[SignedGrant], measured: Energy) -> Decision {
        let uj = measured.uj();
        let mut debits = Vec::with_capacity(chain.len());
        for sg in chain {
            let gid = sg.grant.id();
            let spent = self.spent(&gid);
            let debited = uj.min(sg.grant.budget_uj.saturating_sub(spent));
            self.spent_uj.insert(gid, spent + debited);
            debits.push(debited);
        }
        let leaf_debit = debits.last().copied().unwrap_or(0);
        if debits.iter().all(|d| *d == leaf_debit) {
            debits.clear();
        }
        let breached = chain.iter().any(|sg| sg.grant.caveats.iter().any(|c| c.cost_breached(uj)));
        let mut window_breached = false;
        for sg in chain {
            window_breached |= self.debit_windows(&sg.grant, uj, None);
        }
        Decision {
            verdict: if breached {
                Verdict::Deny(DenyReason::CaveatUnsatisfied)
            } else if window_breached {
                Verdict::Deny(DenyReason::WindowExceeded)
            } else {
                Verdict::Allow
            },
            cost: measured,
            budget_remaining_uj: self.chain_remaining(chain),
            debited_uj: leaf_debit,
            chain_debited_uj: debits,
            debited_minor: 0,
            chain_debited_minor: Vec::new(),
            tainted_uj: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::SigningKey;
    use jcp_schema::{Caveat, Funds};
    use jcp_grant::issue;
    use jcp_schema::{Capability, FrameKind, Grant};

    fn sk(s: u8) -> SigningKey {
        SigningKey::from_bytes(&[s; 32])
    }
    fn did(k: &SigningKey) -> Did {
        Did::from_verifying_key(&k.verifying_key())
    }

    /// A root over `db` held by `sk(2)`, carrying `caveats`.
    fn chain_root(budget_uj: u64, caveats: Vec<Caveat>) -> SignedGrant {
        let g = Grant {
            issuer: did(&sk(1)),
            subject: did(&sk(2)),
            capability: Capability::new(ContentId::of_bytes(b"db"), ["read"]),
            budget_uj,
            budget_funds: None,
            caveats,
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [1; 16],
        };
        issue(&sk(1), g).unwrap()
    }

    /// A delegated grant is decided only with its chain (§4.2). Alone, its
    /// budget, caveats and expiry would be taken at their word, as a root's
    /// are, and nothing would show that they narrow what its issuer held.
    #[test]
    fn a_delegated_grant_alone_is_refused() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000, Vec::new());
        let child = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 500, 0, [2; 16]).unwrap();
        let mut rt = Runtime::new();
        let f = frame(&child, r, "read", Trust::Control);
        let broken = Verdict::Deny(DenyReason::ChainBroken);
        assert_eq!(rt.decide(&f, &child, did(&sk(3)), Energy::measured(1), 10).verdict, broken);
        assert_eq!(rt.authorize(&f, &child, did(&sk(3)), 10).verdict, broken);
        assert_eq!(rt.decide_priced(&f, &child, did(&sk(3)), Energy::measured(1), &Price::new("USD", 1), 10).verdict, broken);
        assert!(rt.decide_chained(&f, &[root, child], did(&sk(3)), Energy::measured(1), 10).is_allow());
    }

    /// Money binds on every link of a chain (§4.8): siblings share their
    /// parent's money as they share its joules, a deny debits neither
    /// dimension, a foreign currency is refused, and joules are checked first.
    #[test]
    fn a_chain_is_bounded_in_money_on_every_link() {
        let r = ContentId::of_bytes(b"db");
        let mut g = chain_root(1_000_000, Vec::new()).grant;
        g.budget_funds = Some(Funds::new("USD", 1_000));
        let root = issue(&sk(1), g).unwrap();
        let usd = |m| Some(Funds::new("USD", m));
        let a = jcp_grant::attenuate_priced(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 500_000, usd(600), 0, [2; 16]).unwrap();
        let b = jcp_grant::attenuate_priced(&root, &sk(2), did(&sk(4)), Capability::new(r, ["read"]), 500_000, usd(600), 0, [3; 16]).unwrap();
        let (ca, cb) = ([root.clone(), a.clone()], [root.clone(), b.clone()]);
        let mut rt = Runtime::new();
        let (fa, fb) = (frame(&a, r, "read", Trust::Control), frame(&b, r, "read", Trust::Control));
        let usd_cost = |m| Price::new("USD", m);

        assert!(rt.decide_chained_priced(&fa, &ca, did(&sk(3)), Energy::measured(10), &usd_cost(500), 10).is_allow());
        assert_eq!((rt.spent_minor(&root.grant.id()), rt.spent_minor(&a.grant.id())), (500, 500));

        let d = rt.decide_chained_priced(&fb, &cb, did(&sk(4)), Energy::measured(10), &usd_cost(600), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded), "the parent has 500 left, though b has 600");
        assert_eq!((rt.spent_minor(&b.grant.id()), rt.spent(&b.grant.id()), rt.spent(&root.grant.id())), (0, 0, 10));

        let d = rt.decide_chained_priced(&fb, &cb, did(&sk(4)), Energy::measured(10), &Price::new("EUR", 1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        let d = rt.decide_chained_priced(&fb, &cb, did(&sk(4)), Energy::measured(600_000), &usd_cost(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded), "joules bind first");

        assert!(rt.decide_chained_priced(&fb, &cb, did(&sk(4)), Energy::measured(10), &usd_cost(500), 10).is_allow());
        assert_eq!(rt.spent_minor(&root.grant.id()), 1_000);
    }

    /// A chain with no money ceiling is bounded by joules alone, whatever the
    /// price or its currency, as a single grant is.
    #[test]
    fn a_chain_with_no_money_ceiling_ignores_the_price() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000, Vec::new());
        let child = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 500, 0, [2; 16]).unwrap();
        let mut rt = Runtime::new();
        let f = frame(&child, r, "read", Trust::Control);
        let chain = [root, child];
        assert!(rt.decide_chained_priced(&f, &chain, did(&sk(3)), Energy::measured(1), &Price::new("JPY", 1 << 40), 10).is_allow());
        assert_eq!(rt.spent_minor(&chain[0].grant.id()), 0);
    }

    /// A chained decision enforces caveats. It used to evaluate none, so a
    /// delegated one-shot grant could be exercised with any payload, past its
    /// window, or above its per-call cap.
    #[test]
    fn a_chained_decision_enforces_caveats() {
        let r = ContentId::of_bytes(b"db");
        let intended = ContentId::of_bytes(b"approved-args");
        let root = chain_root(1_000, vec![Caveat::PayloadIs(intended), Caveat::NotAfter(50), Caveat::MaxCostUj(100)]);
        let child = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 500, 0, [2; 16]).unwrap();
        let chain = [root, child];
        let mut rt = Runtime::new();
        let mut f = frame(&chain[1], r, "read", Trust::Control);
        let deny = Verdict::Deny(DenyReason::CaveatUnsatisfied);

        f.payload_hash = ContentId::of_bytes(b"attacker-args");
        assert_eq!(rt.decide_chained(&f, &chain, did(&sk(3)), Energy::measured(1), 10).verdict, deny);
        f.payload_hash = intended;
        assert_eq!(rt.decide_chained(&f, &chain, did(&sk(3)), Energy::measured(1), 60).verdict, deny, "past NotAfter");
        assert_eq!(rt.decide_chained(&f, &chain, did(&sk(3)), Energy::measured(200), 10).verdict, deny, "over MaxCostUj");
        assert_eq!(rt.spent(&chain[1].grant.id()), 0);
        assert!(rt.decide_chained(&f, &chain, did(&sk(3)), Energy::measured(1), 10).is_allow());
    }

    /// A child that dropped its parent's caveat does not convey authority.
    #[test]
    fn a_chain_whose_child_dropped_a_caveat_is_refused() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000, vec![Caveat::NotAfter(50)]);
        let child = Grant {
            issuer: did(&sk(2)),
            subject: did(&sk(3)),
            capability: Capability::new(r, ["read"]),
            budget_uj: 500,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: Some(root.grant.id()),
            delegate_depth: None,
            nonce: [2; 16],
        };
        let chain = [root, issue(&sk(2), child).unwrap()];
        let mut rt = Runtime::new();
        let f = frame(&chain[1], r, "read", Trust::Control);
        assert_eq!(
            rt.decide_chained(&f, &chain, did(&sk(3)), Energy::measured(1), 60).verdict,
            Verdict::Deny(DenyReason::AttenuationViolation)
        );
        assert_eq!(
            rt.authorize_chained(&f, &chain, did(&sk(3)), 60).verdict,
            Verdict::Deny(DenyReason::AttenuationViolation)
        );
    }

    /// The two-phase metered path over a chain: authorize debits nothing and
    /// defers cost caveats; charge debits every link, so siblings share their
    /// parent, and a per-call breach is reported with the joules still debited.
    #[test]
    fn a_chain_authorizes_without_debit_and_charges_every_link() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000, Vec::new());
        let capped = jcp_grant::attenuate_caveated(
            &root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 600, vec![Caveat::MaxCostUj(300)], 0, [2; 16],
        )
        .unwrap();
        let sibling = jcp_grant::attenuate(&root, &sk(2), did(&sk(4)), Capability::new(r, ["read"]), 600, 0, [3; 16]).unwrap();
        let (a, b) = ([root.clone(), capped], [root.clone(), sibling]);
        let mut rt = Runtime::new();
        let fa = frame(&a[1], r, "read", Trust::Control);
        let fb = frame(&b[1], r, "read", Trust::Control);

        let d = rt.authorize_chained(&fa, &a, did(&sk(3)), 10);
        assert!(d.is_allow(), "a cost caveat cannot bind before the cost is known");
        assert_eq!(d.budget_remaining_uj, 600, "the least any link has left");
        assert_eq!(rt.spent(&root.grant.id()), 0);

        let charged = rt.charge_chained(&a, Energy::measured(400));
        assert_eq!(charged.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
        assert_eq!((rt.spent(&root.grant.id()), rt.spent(&a[1].grant.id())), (400, 400));

        assert_eq!(rt.authorize_chained(&fb, &b, did(&sk(4)), 10).budget_remaining_uj, 600);
        assert!(rt.charge_chained(&b, Energy::measured(600)).is_allow());
        assert_eq!(rt.spent(&root.grant.id()), 1_000, "the siblings shared their parent");
        assert_eq!(
            rt.authorize_chained(&fb, &b, did(&sk(4)), 10).verdict,
            Verdict::Deny(DenyReason::BudgetExceeded)
        );
    }

    fn setup() -> (SignedGrant, Did, ContentId) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let g = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read"]),
            budget_uj: 100,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 1000,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        (issue(&issuer, g).unwrap(), did(&holder), resource)
    }

    fn frame(sg: &SignedGrant, resource: ContentId, action: &str, trust: Trust) -> Frame {
        Frame {
            kind: FrameKind::ToolCall,
            trust,
            grant_id: sg.grant.id(),
            action: action.into(),
            resource,
            payload_hash: ContentId::of_bytes(b"payload"),
            model: None,
        }
    }

    #[test]
    fn legitimate_call_is_allowed_and_debited() {
        let (sg, holder, r) = setup();
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let d = rt.decide(&f, &sg, holder, Energy::measured(30), 10);
        assert!(d.is_allow());
        assert_eq!(d.budget_remaining_uj, 70);
        assert_eq!(rt.spent(&sg.grant.id()), 30);
    }

    #[test]
    fn tool_poisoning_is_refused_structurally() {
        // A tool RESULT carrying injected control is tagged Data → denied,
        // regardless of what it says.
        let (sg, holder, r) = setup();
        let mut rt = Runtime::new();
        let injected = frame(&sg, r, "read", Trust::Data);
        let d = rt.decide(&injected, &sg, holder, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::UntrustedControl));
        assert_eq!(rt.spent(&sg.grant.id()), 0); // nothing debited
    }

    #[test]
    fn out_of_scope_action_and_resource_denied() {
        let (sg, holder, r) = setup();
        let mut rt = Runtime::new();
        // action not granted
        let d = rt.decide(&frame(&sg, r, "delete", Trust::Control), &sg, holder, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::ActionNotGranted));
        // wrong resource (audience binding)
        let other = ContentId::of_bytes(b"prod-secrets");
        let d2 = rt.decide(&frame(&sg, other, "read", Trust::Control), &sg, holder, Energy::measured(1), 10);
        assert_eq!(d2.verdict, Verdict::Deny(DenyReason::WrongResource));
    }

    #[test]
    fn wrong_caller_denied() {
        let (sg, _holder, r) = setup();
        let mut rt = Runtime::new();
        let not_holder = did(&sk(9));
        let d = rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, not_holder, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::WrongSubject));
    }

    #[test]
    fn budget_exhaustion_stops_the_loop() {
        let (sg, holder, r) = setup(); // budget 100
        let mut rt = Runtime::new();
        // spend 60, then 30 (ok, 90), then 30 would exceed → deny
        assert!(rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, holder, Energy::measured(60), 10).is_allow());
        assert!(rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, holder, Energy::measured(30), 10).is_allow());
        let d = rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, holder, Energy::measured(30), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
        assert_eq!(rt.spent(&sg.grant.id()), 90); // the denied call was not debited
    }

    /// A priced grant that also states a per-call joule ceiling, so a hold
    /// reserves that rather than the whole joule remainder and the money
    /// dimension can be the one that binds.
    fn priced_setup_per_call(budget_uj: u64, minor: u64, per_call_uj: u64) -> (SignedGrant, Did, ContentId) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let g = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read"]),
            budget_uj,
            budget_funds: Some(Funds::new("USD", minor)),
            caveats: vec![Caveat::MaxCostUj(per_call_uj)],
            expiry: 1000,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        (issue(&issuer, g).unwrap(), did(&holder), resource)
    }

    fn priced_setup(budget_uj: u64, minor: u64) -> (SignedGrant, Did, ContentId) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let g = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read"]),
            budget_uj,
            budget_funds: Some(Funds::new("USD", minor)),
            caveats: Vec::new(),
            expiry: 1000,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        (issue(&issuer, g).unwrap(), did(&holder), resource)
    }

    /// **The reservation a usage-based charge actually needs.** A charge whose
    /// final amount is known only after the work can still be bounded before
    /// it: hold the authorized maximum, settle for what it cost, and the
    /// difference comes back. Without the release, a ceiling is consumed by the
    /// worst case of every call and a session settling at a tenth of its
    /// maxima exhausts it ten times too fast.
    #[test]
    fn a_money_hold_reserves_the_maximum_and_settling_releases_the_rest() {
        let (sg, holder, r) = priced_setup(10_000, 1_000);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();

        let (d, held) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 900));
        assert!(d.is_allow());
        let h = held.expect("the hold was allowed");
        assert_eq!(h.minor, 900);
        // reserved, not spent
        assert_eq!((rt.spent_minor(&gid), rt.held_minor(&gid)), (0, 900));

        // the work cost a tenth of its maximum
        let d = rt.settle_priced(&sg.grant, h.id, Energy::measured(50), &Price::new("USD", 90), &FlowFacts::bottom());
        assert!(d.is_allow());
        assert_eq!(d.debited_minor, 90);
        assert_eq!((rt.spent_minor(&gid), rt.held_minor(&gid)), (90, 0));

        // and the released 810 is available again: a second charge of 900 fits
        let (d, _) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 900));
        assert!(d.is_allow(), "the over-reservation was not released");
    }

    /// A reservation that does not bound the next decision is not a
    /// reservation (§8.1, applied to money).
    #[test]
    fn an_unsettled_money_hold_bounds_the_next_priced_decision() {
        // a per-call joule ceiling, so the joule hold does not reserve
        // everything and the money dimension is the one that can bind
        let (sg, holder, r) = priced_setup_per_call(10_000, 1_000, 100);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);

        let (d, held) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 900));
        assert!(d.is_allow());
        let h = held.expect("the hold was allowed");
        assert_eq!((h.uj, h.minor), (100, 900), "the hold reserves the stated per-call ceiling");

        // 900 is held, so only 100 is decidable — even though NOTHING is spent
        let d = rt.decide_priced(&f, &sg, holder, Energy::measured(1), &Price::new("USD", 200), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert!(rt.decide_priced(&f, &sg, holder, Energy::measured(1), &Price::new("USD", 100), 10).is_allow());

        // a second hold cannot overdraw what the first reserved
        let (d, held) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 50));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert!(held.is_none(), "a refused hold must reserve nothing");
    }

    /// **Two metered calls in flight at once.** A grant stating a per-call
    /// ceiling admits a second call while the first is still out, each bounded
    /// in both dimensions — the property a session of usage-based charges needs
    /// and a whole-remainder hold cannot give.
    #[test]
    fn a_stated_per_call_ceiling_makes_the_two_phase_path_concurrent() {
        let (sg, holder, r) = priced_setup_per_call(1_000, 1_000, 100);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();

        assert!(rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 100)).0.is_allow());
        assert!(rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 100)).0.is_allow());
        assert_eq!((rt.held(&gid), rt.held_minor(&gid)), (200, 200), "both holds count");

        // a grant with no per-call ceiling has only its remainder as a bound,
        // so one hold leaves nothing to admit a second from — bounded, serial
        let (plain, holder2, r2) = priced_setup(1_000, 1_000);
        let mut rt2 = Runtime::new();
        let f2 = frame(&plain, r2, "read", Trust::Control);
        assert!(rt2.hold_priced(&f2, &plain, holder2, 10, &FlowFacts::bottom(), &Price::new("USD", 1)).0.is_allow());
        let (d, _) = rt2.hold_priced(&f2, &plain, holder2, 10, &FlowFacts::bottom(), &Price::new("USD", 1));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
    }

    /// Settling above what was reserved debits and **denies**: the money has
    /// already moved on the rail, so capping it silently would absorb the
    /// breach. The receipt is the evidence.
    #[test]
    fn settling_over_the_reservation_debits_and_denies() {
        let (sg, holder, r) = priced_setup(10_000, 1_000);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();

        let h = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 100)).1.expect("allowed");
        let d = rt.settle_priced(&sg.grant, h.id, Energy::measured(10), &Price::new("USD", 300), &FlowFacts::bottom());
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert_eq!(d.debited_minor, 300, "the debit stands; the verdict carries the breach");
        assert_eq!(rt.spent_minor(&gid), 300);
    }

    /// A malformed resolution must not be the one move that loses the bound.
    #[test]
    fn a_foreign_currency_resolution_leaves_the_hold_outstanding() {
        let (sg, holder, r) = priced_setup(10_000, 1_000);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();

        let h = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 500)).1.expect("allowed");
        let d = rt.settle_priced(&sg.grant, h.id, Energy::measured(1), &Price::new("EUR", 1), &FlowFacts::bottom());
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        assert_eq!(rt.held_minor(&gid), 500, "the reservation was released by a refusal");
        assert_eq!(rt.spent_minor(&gid), 0);

        // the correct resolution still works
        assert!(rt.settle_priced(&sg.grant, h.id, Energy::measured(1), &Price::new("USD", 10), &FlowFacts::bottom()).is_allow());
        assert_eq!(rt.held_minor(&gid), 0);
    }

    /// A hold in a currency the grant is not denominated in is refused rather
    /// than converted, and a priced hold resolves exactly once.
    #[test]
    fn a_priced_hold_refuses_a_foreign_ceiling_and_resolves_once() {
        let (sg, holder, r) = priced_setup(10_000, 1_000);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);

        let (d, held) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("EUR", 1));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        assert!(held.is_none());

        let h = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 10)).1.expect("allowed");
        assert!(rt.settle_priced(&sg.grant, h.id, Energy::measured(1), &Price::new("USD", 5), &FlowFacts::bottom()).is_allow());
        let again = rt.settle_priced(&sg.grant, h.id, Energy::measured(1), &Price::new("USD", 5), &FlowFacts::bottom());
        assert_eq!(again.verdict, Verdict::Deny(DenyReason::AlreadyResolved));
        assert_eq!(rt.spent_minor(&sg.grant.id()), 5, "the second resolution debited nothing");
    }

    /// An absent money ceiling is the absence of the dimension, not a zero
    /// ceiling: a hold on such a grant holds joules and no money.
    #[test]
    fn a_grant_without_a_money_ceiling_holds_no_money() {
        let sg = chain_root(10_000, Vec::new());
        let mut rt = Runtime::new();
        let r = ContentId::of_bytes(b"db");
        let f = frame(&sg, r, "read", Trust::Control);
        let (d, held) = rt.hold_priced(&f, &sg, did(&sk(2)), 10, &FlowFacts::bottom(), &Price::new("USD", 10_000));
        assert!(d.is_allow(), "money cannot bind a grant that states no money ceiling");
        let h = held.expect("the hold was allowed");
        assert_eq!(h.minor, 0);
        assert_eq!(rt.held_minor(&sg.grant.id()), 0);
        let d = rt.settle_priced(&sg.grant, h.id, Energy::measured(10), &Price::new("USD", 9_999), &FlowFacts::bottom());
        assert!(d.is_allow());
        assert_eq!((d.debited_minor, rt.spent_minor(&sg.grant.id())), (0, 0));
    }

    /// FALSIFICATION: with two holds outstanding on one grant, does resolving
    /// one leave the other's reservation standing?
    #[test]
    fn resolving_one_of_two_concurrent_holds_leaves_the_other_reserved() {
        let (sg, holder, r) = priced_setup_per_call(1_000, 1_000, 100);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();

        let (a, first) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 300));
        let (b, second) = rt.hold_priced(&f, &sg, holder, 10, &FlowFacts::bottom(), &Price::new("USD", 300));
        assert!(a.is_allow() && b.is_allow());
        let (first, second) = (first.expect("a"), second.expect("b"));
        assert_ne!(first.id, second.id, "two holds, two handles");
        assert_eq!((rt.held(&gid), rt.held_minor(&gid)), (200, 600));

        // resolve the FIRST one only, by name
        let d = rt.settle_priced(&sg.grant, first.id, Energy::measured(40), &Price::new("USD", 100), &FlowFacts::bottom());
        assert!(d.is_allow());
        assert_eq!(rt.spent_minor(&gid), 100);
        assert_eq!(
            (rt.held(&gid), rt.held_minor(&gid)),
            (100, 300),
            "resolving one hold released the other's reservation too"
        );

        // and the second resolves on its own terms
        let d = rt.settle_priced(&sg.grant, second.id, Energy::measured(10), &Price::new("USD", 50), &FlowFacts::bottom());
        assert!(d.is_allow());
        assert_eq!((rt.held(&gid), rt.held_minor(&gid), rt.spent_minor(&gid)), (0, 0, 150));
    }

    /// **One authorization, drawn down in steps.** A stream billed per chunk
    /// captures against one hold; each capture debits its own amount and
    /// joules and leaves the rest reserved, and the final resolution releases
    /// what was never drawn.
    #[test]
    fn a_hold_is_captured_in_parts_and_the_rest_stays_reserved() {
        let (sg, holder, r) = priced_setup_per_call(10_000, 1_000, 500);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();
        let facts = FlowFacts::bottom();

        let h = rt.hold_priced(&f, &sg, holder, 10, &facts, &Price::new("USD", 600)).1.expect("held");
        assert_eq!(rt.hold_remaining(&gid, h.id), Some((500, 600)));

        let c1 = rt.capture_priced(&sg.grant, h.id, Energy::measured(100), &Price::new("USD", 200), 11, &facts);
        assert!(c1.is_allow());
        assert_eq!((c1.debited_uj, c1.debited_minor), (100, 200));
        assert_eq!(rt.hold_remaining(&gid, h.id), Some((400, 400)), "the capture drew the reservation down");
        assert_eq!((rt.spent(&gid), rt.spent_minor(&gid)), (100, 200));
        // committed is unchanged by a capture: what left the hold entered the spend
        assert_eq!(rt.spent_minor(&gid) + rt.held_minor(&gid), 600);

        let c2 = rt.capture_priced(&sg.grant, h.id, Energy::measured(50), &Price::new("USD", 150), 12, &facts);
        assert!(c2.is_allow());
        assert_eq!(rt.hold_remaining(&gid, h.id), Some((350, 250)));

        // more than is left is refused cleanly: nothing debited, hold intact
        let over = rt.capture_priced(&sg.grant, h.id, Energy::measured(1), &Price::new("USD", 251), 13, &facts);
        assert_eq!(over.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert!(!over.consumed_the_hold() || rt.hold_remaining(&gid, h.id).is_some());
        assert_eq!(rt.hold_remaining(&gid, h.id), Some((350, 250)), "a refused capture moved the books");
        assert_eq!(rt.spent_minor(&gid), 350);

        // the final resolution debits the last draw and releases the rest
        let end = rt.settle_priced(&sg.grant, h.id, Energy::measured(10), &Price::new("USD", 50), &facts);
        assert!(end.is_allow());
        assert_eq!(rt.hold_remaining(&gid, h.id), None);
        assert_eq!((rt.spent_minor(&gid), rt.held_minor(&gid)), (400, 0));
        // and a capture against a resolved hold draws nothing
        let late = rt.capture_priced(&sg.grant, h.id, Energy::measured(1), &Price::new("USD", 1), 14, &facts);
        assert_eq!(late.verdict, Verdict::Deny(DenyReason::AlreadyResolved));
        assert_eq!(rt.spent_minor(&gid), 400);
    }

    /// **A reservation the payer can always get back.** Past its capture
    /// deadline a hold's money is refused to a capture and released to a
    /// reclaim, with nobody's cooperation — and the joules stay reserved,
    /// because a deadline that released burned energy unrecorded would make
    /// waiting a way to spend for free.
    #[test]
    fn past_its_deadline_a_holds_money_is_reclaimable_and_its_joules_are_not() {
        let (sg, holder, r) = priced_setup_per_call(10_000, 1_000, 500);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();
        let facts = FlowFacts::bottom();

        let h = rt
            .hold_priced_until(&f, &sg, holder, 10, &facts, &Price::new("USD", 600), 100)
            .1
            .expect("held");

        // before the deadline: capturable, not reclaimable
        let (early, released) = rt.reclaim(&sg.grant, h.id, 100);
        assert_eq!(early.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
        assert_eq!((released, rt.held_minor(&gid)), (0, 600));
        assert!(rt.capture_priced(&sg.grant, h.id, Energy::measured(10), &Price::new("USD", 100), 100, &facts).is_allow());

        // after it: a capture is refused, and the remaining money comes back
        let late = rt.capture_priced(&sg.grant, h.id, Energy::measured(10), &Price::new("USD", 100), 101, &facts);
        assert_eq!(late.verdict, Verdict::Deny(DenyReason::Expired));
        let (d, released) = rt.reclaim(&sg.grant, h.id, 101);
        assert!(d.is_allow());
        assert_eq!(released, 500);
        assert_eq!(rt.held_minor(&gid), 0, "the money reservation is gone");
        assert_eq!(rt.held(&gid), 490, "the joule reservation is not");
        assert_eq!(rt.spent_minor(&gid), 100, "what was captured stays captured");

        // reclaimed room is spendable again; a second reclaim releases nothing
        assert!(rt.hold_priced(&f, &sg, holder, 102, &facts, &Price::new("USD", 900)).0.is_allow());
        assert_eq!(rt.reclaim(&sg.grant, h.id, 200).1, 0);

        // a hold that states no deadline is never reclaimable
        let (sg2, holder2, r2) = priced_setup(1_000, 1_000);
        let f2 = frame(&sg2, r2, "read", Trust::Control);
        let mut rt2 = Runtime::new();
        let h2 = rt2.hold_priced(&f2, &sg2, holder2, 10, &facts, &Price::new("USD", 5)).1.unwrap();
        assert_eq!(rt2.reclaim(&sg2.grant, h2.id, u64::MAX).0.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
    }

    /// **Only the issuer may record a refund.** A refund returns room under the
    /// ceiling, so a subject able to declare its own could spend, "refund" and
    /// spend again without limit.
    #[test]
    fn a_refund_returns_room_and_only_the_issuer_may_record_one() {
        let (sg, holder, r) = priced_setup(10_000, 1_000);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();
        let issuer = sg.grant.issuer;

        assert!(rt.decide_priced(&f, &sg, holder, Energy::measured(10), &Price::new("USD", 800), 10).is_allow());
        // 800 of 1000 spent: a 300 charge does not fit
        assert_eq!(
            rt.decide_priced(&f, &sg, holder, Energy::measured(1), &Price::new("USD", 300), 11).verdict,
            Verdict::Deny(DenyReason::FundsExceeded)
        );

        // the subject cannot refund itself
        let d = rt.refund(&sg.grant, holder, &Price::new("USD", 500));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::WrongSubject));
        assert_eq!(rt.refunded_minor(&gid), 0);

        // the issuer can, in the grant's currency, up to what is refundable
        assert_eq!(rt.refund(&sg.grant, issuer, &Price::new("EUR", 1)).verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        assert_eq!(rt.refund(&sg.grant, issuer, &Price::new("USD", 801)).verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert!(rt.refund(&sg.grant, issuer, &Price::new("USD", 500)).is_allow());
        assert_eq!((rt.spent_minor(&gid), rt.refunded_minor(&gid), rt.net_minor(&gid)), (800, 500, 300));

        // the room came back, and the gross debit never decreased
        assert!(rt.decide_priced(&f, &sg, holder, Energy::measured(1), &Price::new("USD", 300), 12).is_allow());
        assert_eq!(rt.spent_minor(&gid), 1_100, "gross debit is monotonic and may pass the ceiling");
        assert_eq!(rt.net_minor(&gid), 600, "net spend is what the ceiling bounds");
        // refundable is net, so refunds cannot exceed what was really spent
        assert_eq!(rt.refund(&sg.grant, issuer, &Price::new("USD", 601)).verdict, Verdict::Deny(DenyReason::FundsExceeded));
        // joules have no refund: nothing in this test lowered them
        assert_eq!(rt.spent(&gid), 11, "10 + 1; the refused charge debited nothing");
    }

    /// **Metered money over a delegation chain.** The reservation stands on
    /// the parent too, or two siblings could each hold the whole of what their
    /// shared parent has left.
    #[test]
    fn a_chained_priced_hold_reserves_on_every_link_and_siblings_share_the_parent() {
        let r = ContentId::of_bytes(b"db");
        let root = {
            let g = Grant {
                issuer: did(&sk(1)),
                subject: did(&sk(2)),
                capability: Capability::new(r, ["read"]),
                budget_uj: 10_000,
                budget_funds: Some(Funds::new("USD", 1_000)),
                caveats: Vec::new(),
                expiry: 0,
                parent: None,
                delegate_depth: None,
                nonce: [1; 16],
            };
            issue(&sk(1), g).unwrap()
        };
        let a = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 4_000, 0, [2; 16]).unwrap();
        let b = jcp_grant::attenuate(&root, &sk(2), did(&sk(4)), Capability::new(r, ["read"]), 4_000, 0, [3; 16]).unwrap();
        let (chain_a, chain_b) = (vec![root.clone(), a.clone()], vec![root.clone(), b.clone()]);
        let (fa, fb) = (frame(&a, r, "read", Trust::Control), frame(&b, r, "read", Trust::Control));
        let mut rt = Runtime::new();
        let root_id = root.grant.id();

        // the children inherit the parent's 1000 ceiling
        let (d, h) = rt.hold_chained_priced(&fa, &chain_a, did(&sk(3)), 10, &Price::new("USD", 700));
        assert!(d.is_allow());
        let h = h.expect("held");
        assert_eq!(rt.held_minor(&root_id), 700, "the parent is reserved too");
        assert_eq!(rt.held_minor(&a.grant.id()), 700);

        // a sibling cannot hold what the parent no longer has — in money or,
        // since the first hold reserved the parent's whole joule remainder,
        // in joules; either way it is refused and reserves nothing
        let (d, none) = rt.hold_chained_priced(&fb, &chain_b, did(&sk(4)), 10, &Price::new("USD", 400));
        assert!(!d.is_allow());
        assert!(none.is_none());
        assert_eq!(rt.held_minor(&b.grant.id()), 0);

        // settle for less: every link is debited what settled, and released
        let d = rt.settle_chained_priced(&chain_a, h.id, Energy::measured(50), &Price::new("USD", 100));
        assert!(d.is_allow());
        assert_eq!(d.debited_minor, 100);
        assert_eq!((rt.spent_minor(&root_id), rt.held_minor(&root_id)), (100, 0));
        assert_eq!((rt.spent_minor(&a.grant.id()), rt.held_minor(&a.grant.id())), (100, 0));

        // now the sibling fits
        let (d, hb) = rt.hold_chained_priced(&fb, &chain_b, did(&sk(4)), 10, &Price::new("USD", 400));
        assert!(d.is_allow());
        // resolved once
        let again = rt.settle_chained_priced(&chain_a, h.id, Energy::measured(1), &Price::new("USD", 1));
        assert_eq!(again.verdict, Verdict::Deny(DenyReason::AlreadyResolved));
        // a foreign-currency resolution leaves the sibling's hold standing
        let hb = hb.unwrap();
        let foreign = rt.settle_chained_priced(&chain_b, hb.id, Energy::measured(1), &Price::new("EUR", 1));
        assert_eq!(foreign.verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        assert_eq!(rt.held_minor(&root_id), 400);
    }

    /// THE receipt only a dual-ceiling grant can produce: denied on ENERGY while
    /// the money ceiling still had room. A single-dimension authorization cannot
    /// make this statement.
    #[test]
    fn joule_ceiling_binds_while_money_has_room() {
        let (sg, holder, r) = priced_setup(100, 10_000); // tiny joules, huge money
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let d = rt.decide_priced(&f, &sg, holder, Energy::measured(500), &Price::new("USD", 1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
        // Neither dimension was debited on deny.
        assert_eq!(rt.spent(&sg.grant.id()), 0);
        assert_eq!(rt.spent_minor(&sg.grant.id()), 0);
    }

    /// The mirror: money binds while joules had room.
    #[test]
    fn money_ceiling_binds_while_joules_have_room() {
        let (sg, holder, r) = priced_setup(1_000_000, 50); // huge joules, tiny money
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let d = rt.decide_priced(&f, &sg, holder, Energy::measured(10), &Price::new("USD", 500), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        // A money denial must not silently debit energy.
        assert_eq!(rt.spent(&sg.grant.id()), 0);
        assert_eq!(rt.spent_minor(&sg.grant.id()), 0);
    }

    #[test]
    fn both_ceilings_debit_independently_on_allow() {
        let (sg, holder, r) = priced_setup(1_000, 500);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        assert!(rt
            .decide_priced(&f, &sg, holder, Energy::measured(400), &Price::new("USD", 200), 10)
            .is_allow());
        assert_eq!(rt.spent(&sg.grant.id()), 400);
        assert_eq!(rt.spent_minor(&sg.grant.id()), 200);
        // Second call: joules fit (800≤1000) and money fits (400≤500).
        assert!(rt
            .decide_priced(&f, &sg, holder, Energy::measured(400), &Price::new("USD", 200), 10)
            .is_allow());
        assert_eq!(rt.spent(&sg.grant.id()), 800);
        assert_eq!(rt.spent_minor(&sg.grant.id()), 400);
        // Third: joules would fit (1200>1000 → no). Energy binds first.
        let d = rt.decide_priced(&f, &sg, holder, Energy::measured(400), &Price::new("USD", 50), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
    }

    /// No exchange rate is ever invented — a foreign-currency cost is refused,
    /// not converted.
    #[test]
    fn foreign_currency_is_denied_not_converted() {
        let (sg, holder, r) = priced_setup(1_000_000, 10_000);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let d = rt.decide_priced(&f, &sg, holder, Energy::measured(1), &Price::new("EUR", 1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        assert_eq!(rt.spent(&sg.grant.id()), 0);
    }

    /// A grant with no money ceiling must behave exactly like `decide` — the
    /// price is ignored entirely, not treated as zero-budget.
    #[test]
    fn no_money_ceiling_ignores_price() {
        let (sg, holder, r) = setup(); // budget_funds: None, budget_uj 100
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let d = rt.decide_priced(&f, &sg, holder, Energy::measured(30), &Price::new("USD", 999_999), 10);
        assert!(d.is_allow(), "an absent money ceiling must not bind");
        assert_eq!(rt.spent(&sg.grant.id()), 30);
        assert_eq!(rt.spent_minor(&sg.grant.id()), 0); // nothing tracked
    }

    fn caveated(cavs: Vec<Caveat>) -> (SignedGrant, Did, ContentId) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let g = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read", "write"]),
            budget_uj: 1_000_000,
            budget_funds: None,
            caveats: cavs,
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        (issue(&issuer, g).unwrap(), did(&holder), resource)
    }

    /// A one-shot grant: bound to an exact payload, so a leaked grant cannot be
    /// replayed against different arguments. This is the capability the fixed
    /// axes cannot express — `capability` narrows to an ACTION, never to a call.
    #[test]
    fn payload_is_makes_a_grant_one_shot() {
        let intended = ContentId::of_bytes(b"the-approved-args");
        let (sg, holder, r) = caveated(vec![Caveat::PayloadIs(intended)]);
        let mut rt = Runtime::new();

        let mut f = frame(&sg, r, "read", Trust::Control);
        f.payload_hash = intended;
        assert!(rt.decide(&f, &sg, holder, Energy::measured(1), 10).is_allow());

        // Same grant, same action, different arguments → refused.
        let mut replay = frame(&sg, r, "read", Trust::Control);
        replay.payload_hash = ContentId::of_bytes(b"attacker-args");
        let d = rt.decide(&replay, &sg, holder, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
    }

    /// Which model a grant authorizes. The capability's resource names the
    /// endpoint; `ModelIn` names the model content addresses that endpoint may
    /// run for this grant. A frame naming one of them is allowed, a frame
    /// naming another is denied, and a frame naming none is denied too, so a
    /// dispatcher that does not say what it will run cannot exercise the grant.
    /// A denial debits nothing.
    #[test]
    fn model_in_admits_only_a_named_model_and_fails_closed() {
        let approved = ContentId::of_bytes(b"nli weights, revision 7");
        let other = ContentId::of_bytes(b"some other weights");
        let (sg, holder, r) = caveated(vec![Caveat::ModelIn(vec![approved])]);
        let mut rt = Runtime::new();

        let mut f = frame(&sg, r, "read", Trust::Control);
        f.model = Some(approved);
        assert!(rt.decide(&f, &sg, holder, Energy::measured(10), 10).is_allow());

        let mut wrong = frame(&sg, r, "read", Trust::Control);
        wrong.model = Some(other);
        let d = rt.decide(&wrong, &sg, holder, Energy::measured(10), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));

        let unnamed = frame(&sg, r, "read", Trust::Control);
        assert_eq!(unnamed.model, None);
        let d = rt.decide(&unnamed, &sg, holder, Energy::measured(10), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
        assert_eq!(rt.spent(&sg.grant.id()), 10, "only the allowed call was debited");
    }

    /// A delegate narrows the models by adding a smaller `ModelIn` beside the
    /// inherited one; both must hold, so only their intersection is allowed.
    #[test]
    fn model_in_narrows_by_intersection() {
        let (a, b) = (ContentId::of_bytes(b"model a"), ContentId::of_bytes(b"model b"));
        let (sg, holder, r) = caveated(vec![Caveat::ModelIn(vec![a, b]), Caveat::ModelIn(vec![b])]);
        let mut rt = Runtime::new();
        let mut fa = frame(&sg, r, "read", Trust::Control);
        fa.model = Some(a);
        assert_eq!(rt.decide(&fa, &sg, holder, Energy::measured(1), 10).verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
        let mut fb = frame(&sg, r, "read", Trust::Control);
        fb.model = Some(b);
        assert!(rt.decide(&fb, &sg, holder, Energy::measured(1), 10).is_allow());
    }

    /// A per-invocation ceiling, distinct from the cumulative budget: a delegate
    /// cannot burn the whole remaining budget in one call.
    #[test]
    fn max_cost_bounds_a_single_call_not_the_total() {
        let (sg, holder, r) = caveated(vec![Caveat::MaxCostUj(500)]);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        // Well within the 1_000_000 cumulative budget, but over the per-call cap.
        let d = rt.decide(&f, &sg, holder, Energy::measured(900), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
        assert_eq!(rt.spent(&sg.grant.id()), 0);
        // Under the cap → allowed, and repeatable.
        assert!(rt.decide(&f, &sg, holder, Energy::measured(400), 10).is_allow());
        assert!(rt.decide(&f, &sg, holder, Energy::measured(400), 10).is_allow());
        assert_eq!(rt.spent(&sg.grant.id()), 800);
    }

    #[test]
    fn time_window_and_action_and_caller_caveats_bind() {
        let (sg, holder, r) = caveated(vec![Caveat::NotBefore(100), Caveat::NotAfter(200)]);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        assert!(rt.decide(&f, &sg, holder, Energy::measured(1), 50).verdict != Verdict::Allow);
        assert!(rt.decide(&f, &sg, holder, Energy::measured(1), 150).is_allow());
        assert!(rt.decide(&f, &sg, holder, Energy::measured(1), 250).verdict != Verdict::Allow);

        // ActionIn narrows BELOW the capability, which permits read+write.
        let (sg2, holder2, r2) = caveated(vec![Caveat::ActionIn(vec!["read".into()])]);
        let mut rt2 = Runtime::new();
        let w = frame(&sg2, r2, "write", Trust::Control);
        assert_eq!(
            rt2.decide(&w, &sg2, holder2, Energy::measured(1), 10).verdict,
            Verdict::Deny(DenyReason::CaveatUnsatisfied),
            "a caveat must be able to narrow below the capability"
        );

        // CallerIs pins the principal.
        let (sg3, _h3, r3) = caveated(vec![Caveat::CallerIs(did(&sk(9)))]);
        let mut rt3 = Runtime::new();
        let f3 = frame(&sg3, r3, "read", Trust::Control);
        assert_eq!(
            rt3.decide(&f3, &sg3, did(&sk(2)), Energy::measured(1), 10).verdict,
            Verdict::Deny(DenyReason::CaveatUnsatisfied)
        );
    }

    /// A grant with no caveats must behave exactly as before — the field is
    /// absent from the encoding, so identity and signature are unchanged.
    #[test]
    fn no_caveats_is_byte_identical_and_unaffected() {
        let (plain, holder, r) = setup();
        let bytes = jcp_schema::canonical_cbor(&plain.grant).unwrap();
        assert!(!String::from_utf8_lossy(&bytes).contains("caveats"));
        let mut rt = Runtime::new();
        assert!(rt.decide(&frame(&plain, r, "read", Trust::Control), &plain, holder, Energy::measured(1), 10).is_allow());
    }

    /// The two-phase metered path: a cost-dependent caveat is unevaluable at
    /// authorize (the cost is unknown), so it MUST bind at the debit point —
    /// and the joules are still debited, because they were really spent.
    #[test]
    fn cost_caveat_binds_at_the_debit_point() {
        let (sg, holder, r) = caveated(vec![Caveat::MaxCostUj(500)]);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);

        // Phase one: authorize cannot know the cost, so it does not pretend to.
        let a = rt.authorize(&f, &sg, holder, 10);
        assert!(a.is_allow(), "authorize must not fail a caveat it cannot evaluate");
        assert_eq!(rt.spent(&sg.grant.id()), 0, "authorize never debits");

        // Phase two: the measured cost breaches the per-call ceiling.
        let d = rt.charge(&sg.grant, Energy::measured(900));
        assert_eq!(
            d.verdict,
            Verdict::Deny(DenyReason::CaveatUnsatisfied),
            "a cost-dependent caveat must bind at the debit point"
        );
        // …and the energy is STILL accounted: it was really consumed.
        assert_eq!(rt.spent(&sg.grant.id()), 900, "spent joules must never be hidden");

        // Within the ceiling, charge allows and debits normally.
        let d2 = rt.charge(&sg.grant, Energy::measured(100));
        assert!(d2.is_allow());
        assert_eq!(rt.spent(&sg.grant.id()), 1_000);
    }

    /// Cost-INdependent caveats are enforced in both phases, including authorize.
    #[test]
    fn cost_independent_caveats_bind_at_authorize() {
        let (sg, _h, r) = caveated(vec![Caveat::CallerIs(did(&sk(9)))]);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let a = rt.authorize(&f, &sg, did(&sk(2)), 10);
        assert_eq!(a.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
    }

    #[test]
    fn expired_grant_denied() {
        let (sg, holder, r) = setup(); // expiry 1000
        let mut rt = Runtime::new();
        let d = rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, holder, Energy::measured(1), 2000);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::Expired));
    }

    #[test]
    fn forged_grant_denied() {
        let (mut sg, holder, r) = setup();
        sg.grant.budget_uj = 1_000_000; // tamper after signing
        let mut rt = Runtime::new();
        // grant_id changes with the tamper, so the frame must point at the new id
        let f = frame(&sg, r, "read", Trust::Control);
        let d = rt.decide(&f, &sg, holder, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BadSignature));
    }

    #[test]
    fn an_unstated_revocation_marker_is_not_a_current_one() {
        // SPEC §4.3, Propagation. The marker exists so an allow can be told
        // apart from an allow by a point that had not yet heard. The default
        // must therefore be "has not said" and not a number an auditor could
        // read as current — `None`, never `Some(0)`, which would claim the
        // point had seen the start of the feed.
        let mut rt = Runtime::new();
        assert_eq!(rt.revocation_marker(), None, "a fresh point must not claim currency");
        rt.revocation_known_through(42);
        assert_eq!(rt.revocation_marker(), Some(42));
        // Monotonic is the deployment's contract, not this crate's: JCP does
        // not interpret the marker, so it does not police its direction either.
        // Stated plainly because a reader could expect a clamp here.
        rt.revocation_known_through(7);
        assert_eq!(rt.revocation_marker(), Some(7), "JCP neither defines nor polices the feed's order");
        // And declaring one changes no decision: it is a statement about the
        // point's knowledge, not an input to the gate. Checked against a
        // runtime that actually holds a revocation — comparing two runtimes
        // with empty revocation sets would pass however the marker behaved.
        let (sg, holder, r) = setup();
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        let sr = jcp_grant::revoke(&sk(1), &sg.grant, [7; 16]).unwrap();
        rt.apply_revocation(&sr, &sg.grant).unwrap();
        assert_eq!(
            rt.decide(&f, &sg, holder, Energy::measured(1), 10).verdict,
            Verdict::Deny(DenyReason::Revoked),
            "premise: the grant is revoked at this point"
        );
        rt.revocation_known_through(99);
        assert_eq!(
            rt.decide(&f, &sg, holder, Energy::measured(1), 10).verdict,
            Verdict::Deny(DenyReason::Revoked),
            "declaring a marker un-revoked a grant: the marker is not an input to the gate"
        );
        assert!(rt.is_revoked(&sg.grant.id()));
    }

    #[test]
    fn revoked_grant_denied() {
        let (sg, holder, r) = setup();
        let mut rt = Runtime::new();
        assert!(rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, holder, Energy::measured(1), 10).is_allow());
        let sr = jcp_grant::revoke(&sk(1), &sg.grant, [7; 16]).unwrap();
        rt.apply_revocation(&sr, &sg.grant).unwrap();
        let d = rt.decide(&frame(&sg, r, "read", Trust::Control), &sg, holder, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::Revoked));
        // a forged revocation (wrong signer) is refused and changes nothing
        let forged = jcp_grant::revoke(&sk(8), &sg.grant, [7; 16]);
        assert!(forged.is_err());
    }

    /// issuer→holder (1000 µJ) → two sibling children (600 µJ each) held by sub.
    fn chain_setup() -> (Vec<SignedGrant>, Vec<SignedGrant>, Did, ContentId) {
        let issuer = sk(1);
        let holder = sk(2);
        let sub = sk(3);
        let r = ContentId::of_bytes(b"db");
        let root = issue(
            &issuer,
            Grant {
                issuer: did(&issuer),
                subject: did(&holder),
                capability: Capability::new(r, ["read"]),
                budget_uj: 1000,
                budget_funds: None,
                caveats: Vec::new(),
                expiry: 0,
                parent: None,
                delegate_depth: None,
                nonce: [0; 16],
            },
        )
        .unwrap();
        let kid = |nonce: u8| {
            jcp_grant::attenuate(&root, &holder, did(&sub), Capability::new(r, ["read"]), 600, 0, [nonce; 16]).unwrap()
        };
        let (a, b) = (kid(1), kid(2));
        (vec![root.clone(), a], vec![root, b], did(&sub), r)
    }

    fn leaf_frame(chain: &[SignedGrant], r: ContentId) -> Frame {
        Frame {
            kind: FrameKind::ToolCall,
            trust: Trust::Control,
            grant_id: chain.last().unwrap().grant.id(),
            action: "read".into(),
            resource: r,
            payload_hash: ContentId::of_bytes(b"p"),
            model: None,
        }
    }

    #[test]
    fn chained_decision_allows_and_debits_every_link() {
        let (chain_a, _, sub, r) = chain_setup();
        let mut rt = Runtime::new();
        let d = rt.decide_chained(&leaf_frame(&chain_a, r), &chain_a, sub, Energy::measured(400), 10);
        assert!(d.is_allow());
        assert_eq!(d.budget_remaining_uj, 200); // leaf 600 − 400
        assert_eq!(rt.spent(&chain_a[0].grant.id()), 400); // root debited too
    }

    #[test]
    fn sibling_delegations_share_the_root_budget() {
        let (chain_a, chain_b, sub, r) = chain_setup();
        let mut rt = Runtime::new();
        // sibling A spends 600 of the root's 1000
        assert!(rt.decide_chained(&leaf_frame(&chain_a, r), &chain_a, sub, Energy::measured(600), 10).is_allow());
        // sibling B has 600 of its own — but the root only has 400 left.
        // Delegation must not mint joules: 600 through B is denied…
        let d = rt.decide_chained(&leaf_frame(&chain_b, r), &chain_b, sub, Energy::measured(600), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
        // …while 400 through B still fits both B and the root.
        assert!(rt.decide_chained(&leaf_frame(&chain_b, r), &chain_b, sub, Energy::measured(400), 10).is_allow());
        assert_eq!(rt.spent(&chain_b[0].grant.id()), 1000); // root exactly conserved
    }

    #[test]
    fn revoking_the_root_kills_chained_decisions() {
        let (chain_a, _, sub, r) = chain_setup();
        let mut rt = Runtime::new();
        let sr = jcp_grant::revoke(&sk(1), &chain_a[0].grant, [7; 16]).unwrap();
        rt.apply_revocation(&sr, &chain_a[0].grant).unwrap();
        let d = rt.decide_chained(&leaf_frame(&chain_a, r), &chain_a, sub, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::Revoked));
    }

    #[test]
    fn broken_chain_denied() {
        let (chain_a, chain_b, sub, r) = chain_setup();
        let mut rt = Runtime::new();
        // splice sibling B's leaf under A's frame: parent links don't match the order
        let spliced = vec![chain_a[1].clone(), chain_b[1].clone()];
        let d = rt.decide_chained(&leaf_frame(&spliced, r), &spliced, sub, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::ChainBroken));
        // empty chain
        let f = leaf_frame(&chain_a, r);
        assert_eq!(rt.decide_chained(&f, &[], sub, Energy::measured(1), 10).verdict, Verdict::Deny(DenyReason::ChainBroken));
    }

    // ── flow gate (SPEC §4.10, check 6c) ─────────────────────────────────────

    use jcp_schema::flow::{FlowCeiling, FlowFacts, Integrity, Label, Origin, Origins, Readers};
    use jcp_schema::Provenance;

    fn flow_grant(caveats: Vec<Caveat>) -> (SignedGrant, Did, ContentId) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let g = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read"]),
            budget_uj: 100,
            budget_funds: None,
            caveats,
            expiry: 1000,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        (issue(&issuer, g).unwrap(), did(&holder), resource)
    }

    /// A tainted argument: untrusted, carrying `channel`'s origin.
    fn tainted(channel: u8) -> FlowFacts {
        FlowFacts {
            label: Label {
                integrity: Integrity::Untrusted,
                origins: Origins::one(Origin::channel(ContentId::of_bytes(&[channel; 4]))),
                readers: Readers::Public,
            },
            witness_id: ContentId([0u8; 32]),
            eval_uj: 5,
            eval_prov: Provenance::ModelBased,
        }
    }

    /// A ceiling that admits only principal-clean, origin-free values.
    fn principal_only() -> FlowCeiling {
        FlowCeiling::new(Label {
            integrity: Integrity::Principal,
            origins: Origins::none(),
            readers: Readers::Public,
        })
    }

    /// A permissive ceiling that admits any label but has a small tainted budget.
    fn permissive_with_tainted_budget(budget: u64) -> FlowCeiling {
        FlowCeiling { ceiling: Label::top(), tainted_budget_uj: Some(budget) }
    }

    #[test]
    fn ceiling_free_grant_is_a_noop_for_any_facts() {
        // Every grant that exists today is ceiling-free; it must behave identically
        // whether facts are absent, clean, or tainted.
        let (sg, holder, r) = flow_grant(Vec::new());
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        assert!(rt.decide(&f, &sg, holder, Energy::measured(10), 10).is_allow());
        let mut rt = Runtime::new();
        assert!(rt.decide_flow(&f, &sg, holder, Energy::measured(10), 10, &FlowFacts::bottom()).is_allow());
        let mut rt = Runtime::new();
        assert!(rt.decide_flow(&f, &sg, holder, Energy::measured(10), 10, &tainted(3)).is_allow());
    }

    #[test]
    fn a_bottom_flow_call_is_byte_identical_to_the_plain_path() {
        let (sg, holder, r) = flow_grant(Vec::new());
        let f = frame(&sg, r, "read", Trust::Control);
        let mut plain = Runtime::new();
        let mut flow = Runtime::new();
        assert_eq!(
            plain.decide(&f, &sg, holder, Energy::measured(30), 10),
            flow.decide_flow(&f, &sg, holder, Energy::measured(30), 10, &FlowFacts::bottom()),
        );
        assert_eq!(plain.spent(&sg.grant.id()), flow.spent(&sg.grant.id()));
    }

    #[test]
    fn clean_facts_pass_a_ceiling() {
        let (sg, holder, r) = flow_grant(vec![Caveat::FlowBelow(principal_only())]);
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        assert!(rt.decide_flow(&f, &sg, holder, Energy::measured(10), 10, &FlowFacts::bottom()).is_allow());
    }

    #[test]
    fn a_tainted_argument_is_denied_by_a_ceiling_with_zero_debit() {
        // The core property: a value from an untrusted origin cannot exercise a
        // principal-only grant, and the denial precedes the budget so it costs no
        // joules — the same invariant tool poisoning holds.
        let (sg, holder, r) = flow_grant(vec![Caveat::FlowBelow(principal_only())]);
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        let d = rt.decide_flow(&f, &sg, holder, Energy::measured(30), 10, &tainted(7));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::TaintedFlow));
        assert_eq!(rt.spent(&sg.grant.id()), 0, "a tainted deny debits nothing");
    }

    #[test]
    fn a_ceiling_grant_on_the_old_path_fails_closed() {
        // An un-migrated caller (no facts) handed a ceilinged grant is denied, never
        // silently unenforced.
        let (sg, holder, r) = flow_grant(vec![Caveat::FlowBelow(principal_only())]);
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        assert_eq!(
            rt.decide(&f, &sg, holder, Energy::measured(10), 10).verdict,
            Verdict::Deny(DenyReason::TaintedFlow),
        );
        assert_eq!(rt.spent(&sg.grant.id()), 0);
    }

    #[test]
    fn the_taint_floor_refuses_a_forbidden_origin_regardless_of_ceiling() {
        // An enforcement-point refusal that no grant carries and none can widen.
        let (sg, holder, r) = flow_grant(Vec::new()); // no ceiling at all
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        let forbidden = Origins::one(Origin::channel(ContentId::of_bytes(&[7u8; 4])));
        rt.forbid_flow(r, forbidden);
        let d = rt.decide_flow(&f, &sg, holder, Energy::measured(10), 10, &tainted(7));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::TaintedFlow));
        // A value from a different origin is unaffected.
        assert!(rt.decide_flow(&f, &sg, holder, Energy::measured(10), 10, &tainted(9)).is_allow());
    }

    #[test]
    fn the_tainted_sub_budget_pre_checks_at_authorize() {
        // A permissive ceiling admits the label, but the tighter tainted wallet
        // denies once spent — before the upstream tool runs.
        let (sg, holder, r) = flow_grant(vec![Caveat::FlowBelow(permissive_with_tainted_budget(20))]);
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        // First tainted call is admitted and depletes the tainted wallet.
        assert!(rt.authorize_flow(&f, &sg, holder, 10, &tainted(3)).is_allow());
        rt.charge_flow(&sg.grant, Energy::measured(20), &tainted(3));
        assert_eq!(rt.spent_tainted(&sg.grant.id()), 20);
        // The wallet is now spent: the next tainted call is refused before running.
        let d = rt.authorize_flow(&f, &sg, holder, 10, &tainted(3));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::TaintBudgetExceeded));
        // A clean call still passes — the sub-budget only bounds tainted work.
        assert!(rt.authorize_flow(&f, &sg, holder, 10, &FlowFacts::bottom()).is_allow());
    }

    #[test]
    fn charge_flow_only_depletes_the_tainted_wallet_for_tainted_calls() {
        let (sg, _holder, _r) = flow_grant(Vec::new());
        let mut rt = Runtime::new();
        rt.charge_flow(&sg.grant, Energy::measured(15), &FlowFacts::bottom());
        assert_eq!(rt.spent_tainted(&sg.grant.id()), 0, "a clean call spends no tainted budget");
        rt.charge_flow(&sg.grant, Energy::measured(15), &tainted(1));
        assert_eq!(rt.spent_tainted(&sg.grant.id()), 15, "a tainted call does");
    }

    #[test]
    fn a_chained_grant_gates_flow_and_fails_closed_without_facts() {
        // A delegated grant carrying a ceiling: the plain chain path fails closed,
        // and the flow path denies a tainted argument.
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let root = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read"]),
            budget_uj: 100,
            budget_funds: None,
            caveats: vec![Caveat::FlowBelow(principal_only())],
            expiry: 1000,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        let root_sg = issue(&issuer, root).unwrap();
        let f = frame(&root_sg, resource, "read", Trust::Control);

        let mut rt = Runtime::new();
        // Plain chain path: no facts under a ceiling ⇒ fail closed.
        assert_eq!(
            rt.decide_chained(&f, std::slice::from_ref(&root_sg), did(&holder), Energy::measured(10), 10).verdict,
            Verdict::Deny(DenyReason::TaintedFlow),
        );
        // Flow chain path: a tainted argument is denied.
        assert_eq!(
            rt.decide_chained_flow(&f, std::slice::from_ref(&root_sg), did(&holder), Energy::measured(10), 10, &tainted(7)).verdict,
            Verdict::Deny(DenyReason::TaintedFlow),
        );
        // A clean argument passes.
        assert!(rt
            .decide_chained_flow(&f, &[root_sg], did(&holder), Energy::measured(10), 10, &FlowFacts::bottom())
            .is_allow());
    }

    /// `authorize` puts a zero on every decision it returns — allow and each
    /// refusal — because nothing has run. Nothing read that zero either, so
    /// it must be graded `Estimator`, never a hardware reading: a refusal's
    /// receipt seals this cost.
    #[test]
    fn an_authorizations_zero_is_never_a_reading() {
        let (sg, holder, r) = setup();
        let mut rt = Runtime::new();
        let cases = [
            ("allow", rt.authorize(&frame(&sg, r, "read", Trust::Control), &sg, holder, 10)),
            ("untrusted control", rt.authorize(&frame(&sg, r, "read", Trust::Data), &sg, holder, 10)),
            ("action not granted", rt.authorize(&frame(&sg, r, "delete", Trust::Control), &sg, holder, 10)),
            ("flow allow", rt.authorize_flow(&frame(&sg, r, "read", Trust::Control), &sg, holder, 10, &FlowFacts::bottom())),
        ];
        rt.charge(&sg.grant, Energy::measured(100));
        let exhausted = rt.authorize(&frame(&sg, r, "read", Trust::Control), &sg, holder, 10);
        let exhausted_flow = rt.authorize_flow(&frame(&sg, r, "read", Trust::Control), &sg, holder, 10, &FlowFacts::bottom());
        for (what, d) in cases.into_iter().chain([("budget spent", exhausted), ("flow, budget spent", exhausted_flow)]) {
            eprintln!("{what}: {:?} cost {} µJ [{}] measured {:?}", d.verdict, d.cost.uj(), d.cost.provenance.jcr1_label(), d.cost.measured_uj);
            assert_eq!(d.cost.uj(), 0, "{what}: authorize debits nothing");
            assert_eq!(d.cost.provenance, jcp_schema::Provenance::Estimator, "{what}: a zero nothing read graded {:?}", d.cost.provenance);
            assert_eq!(d.cost.measured_uj, None, "{what}: a measured zero nothing read");
        }
    }

    // ── sliding windows (SPEC §4.12) ─────────────────────────────────────────

    fn within(secs: u64, limit: WindowLimit) -> Caveat {
        Caveat::WithinWindow(jcp_schema::Window { secs, limit })
    }

    const FULL: Verdict = Verdict::Deny(DenyReason::WindowExceeded);

    /// A call window admits its limit inside any window, refuses the next
    /// without debiting it, and admits again once the earliest call has slid
    /// out. The budget alone would have allowed every call.
    #[test]
    fn a_call_window_admits_its_limit_and_then_slides() {
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxCalls(2))]);
        let mut rt = Runtime::new();
        let f = frame(&sg, r, "read", Trust::Control);
        let call = |rt: &mut Runtime, now| rt.decide(&f, &sg, holder, Energy::measured(10), now).verdict;
        assert_eq!(call(&mut rt, 100), Verdict::Allow);
        assert_eq!(call(&mut rt, 110), Verdict::Allow);
        assert_eq!(call(&mut rt, 159), FULL);
        assert_eq!(rt.spent(&sg.grant.id()), 20, "the refused call was not debited");
        assert_eq!(call(&mut rt, 160), Verdict::Allow, "the call at 100 has left the window");
        assert_eq!(call(&mut rt, 169), FULL, "the calls at 110 and 160 are inside it");
    }

    /// A distinct-payload window counts what a grant is used on, not how
    /// often: a payload already inside the window is admitted again, a new one
    /// beyond the limit is not.
    #[test]
    fn a_distinct_payload_window_counts_targets_not_calls() {
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxDistinctPayloads(2))]);
        let mut rt = Runtime::new();
        let on = |p: &[u8]| {
            let mut f = frame(&sg, r, "read", Trust::Control);
            f.payload_hash = ContentId::of_bytes(p);
            f
        };
        let mut call = |p: &[u8], now| rt.decide(&on(p), &sg, holder, Energy::measured(1), now).verdict;
        assert_eq!(call(b"a", 100), Verdict::Allow);
        assert_eq!(call(b"b", 101), Verdict::Allow);
        assert_eq!(call(b"a", 102), Verdict::Allow, "a is already inside the window");
        assert_eq!(call(b"c", 103), FULL);
        assert_eq!(call(b"c", 161), Verdict::Allow, "the first a and b have left");
    }

    /// A joule window in the one-shot path refuses a call whose cost would
    /// overfill it. In the two-phase path it admits a call while any of the
    /// window is left, and binds at the debit: an overrun is denied, the
    /// joules stay debited, and the full window refuses the next call.
    #[test]
    fn a_joule_window_binds_at_the_debit() {
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxUj(1_000))]);
        let f = frame(&sg, r, "read", Trust::Control);

        let mut one_shot = Runtime::new();
        assert!(one_shot.decide(&f, &sg, holder, Energy::measured(700), 100).is_allow());
        assert_eq!(one_shot.decide(&f, &sg, holder, Energy::measured(301), 110).verdict, FULL);
        assert!(one_shot.decide(&f, &sg, holder, Energy::measured(300), 110).is_allow());
        assert_eq!(one_shot.spent(&sg.grant.id()), 1_000);

        let mut rt = Runtime::new();
        assert!(rt.authorize(&f, &sg, holder, 100).is_allow());
        assert!(rt.charge(&sg.grant, Energy::measured(700)).is_allow());
        assert!(rt.authorize(&f, &sg, holder, 110).is_allow(), "300 µJ are left");
        assert_eq!(rt.charge(&sg.grant, Energy::measured(500)).verdict, FULL);
        assert_eq!(rt.spent(&sg.grant.id()), 1_200, "the overrun stays debited");
        assert_eq!(rt.authorize(&f, &sg, holder, 120).verdict, FULL);
        assert!(rt.authorize(&f, &sg, holder, 160).is_allow(), "the 700 at 100 has left; 500 remain");

        // A debit counts from its own call's admission, the latest, not the
        // grant's first: the 450 charged after the call at 150 is still inside
        // the window at 205, when the call at 100 is long gone.
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxUj(500))]);
        let f = frame(&sg, r, "write", Trust::Control);
        let mut rt = Runtime::new();
        assert!(rt.authorize(&f, &sg, holder, 100).is_allow());
        assert!(rt.charge(&sg.grant, Energy::measured(100)).is_allow());
        assert!(rt.authorize(&f, &sg, holder, 150).is_allow());
        assert_eq!(rt.charge(&sg.grant, Energy::measured(450)).verdict, FULL);
        assert_eq!(rt.decide(&f, &sg, holder, Energy::measured(100), 205).verdict, FULL);
        assert!(rt.decide(&f, &sg, holder, Energy::measured(50), 205).is_allow());
    }

    /// The priced and flow paths count against a window as the plain ones do,
    /// and gate on it: every way to decide a call is a way to fill the window.
    #[test]
    fn every_path_counts_against_the_window() {
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxCalls(1))]);
        let f = frame(&sg, r, "read", Trust::Control);
        let clean = FlowFacts::bottom();
        let usd = Price::new("USD", 1);

        let mut priced = Runtime::new();
        assert!(priced.decide_priced(&f, &sg, holder, Energy::measured(1), &usd, 100).is_allow());
        assert_eq!(priced.decide_priced(&f, &sg, holder, Energy::measured(1), &usd, 101).verdict, FULL);
        assert_eq!(priced.decide(&f, &sg, holder, Energy::measured(1), 102).verdict, FULL);

        let mut flow = Runtime::new();
        assert!(flow.decide_flow(&f, &sg, holder, Energy::measured(1), 100, &clean).is_allow());
        assert_eq!(flow.decide_flow(&f, &sg, holder, Energy::measured(1), 101, &clean).verdict, FULL);
        assert_eq!(flow.authorize(&f, &sg, holder, 102).verdict, FULL);

        let mut two_phase = Runtime::new();
        assert!(two_phase.authorize_flow(&f, &sg, holder, 100, &clean).is_allow());
        assert!(two_phase.charge_flow(&sg.grant, Energy::measured(1), &clean).is_allow());
        assert_eq!(two_phase.authorize_flow(&f, &sg, holder, 101, &clean).verdict, FULL);
        assert_eq!(two_phase.decide(&f, &sg, holder, Energy::measured(1), 102).verdict, FULL);
    }

    /// A priced hold refused for money did not run, so it does not fill a
    /// window: the next call that fits is admitted. Before the money check came
    /// ahead of the admission, the refused hold took the window's one call.
    #[test]
    fn a_hold_refused_for_money_leaves_the_window_open() {
        let (mut sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxCalls(1))]);
        sg.grant.budget_funds = Some(Funds::new("USD", 100));
        let sg = issue(&sk(1), sg.grant).unwrap();
        let f = frame(&sg, r, "read", Trust::Control);
        let clean = FlowFacts::bottom();
        let mut rt = Runtime::new();
        let (d, none) = rt.hold_priced(&f, &sg, holder, 100, &clean, &Price::new("USD", 500));
        assert_eq!((d.verdict, none.is_none()), (Verdict::Deny(DenyReason::FundsExceeded), true));
        let (d, _) = rt.hold_priced(&f, &sg, holder, 101, &clean, &Price::new("EUR", 5));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CurrencyMismatch));
        let (d, held) = rt.hold_priced(&f, &sg, holder, 102, &clean, &Price::new("USD", 50));
        assert!(d.is_allow() && held.is_some(), "{:?}", d.verdict);
        let (d, _) = rt.hold_priced(&f, &sg, holder, 103, &clean, &Price::new("USD", 10));
        assert_eq!(d.verdict, FULL, "the admitted hold is the window's one call");
    }

    /// The same over a chain, where the window sits on the parent, and for a
    /// hold that needs a stated joule amount: refused for joules or for money,
    /// it fills nothing.
    #[test]
    fn a_chained_hold_refused_for_money_or_joules_leaves_the_window_open() {
        let r = ContentId::of_bytes(b"db");
        let root = {
            let mut g = chain_root(1_000, vec![within(60, WindowLimit::MaxCalls(1))]).grant;
            g.budget_funds = Some(Funds::new("USD", 100));
            issue(&sk(1), g).unwrap()
        };
        let a = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 1_000, 0, [2; 16]).unwrap();
        let chain = [root.clone(), a.clone()];
        let f = frame(&a, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        let who = did(&sk(3));
        let (d, _) = rt.hold_chained_priced(&f, &chain, who, 100, &Price::new("USD", 500));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        let (d, _) = rt.hold_chained_priced_for(&f, &chain, who, 101, 5_000, &Price::new("USD", 10));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
        let (d, held) = rt.hold_chained_priced_for(&f, &chain, who, 102, 1_000, &Price::new("USD", 10));
        assert!(d.is_allow(), "{:?}", d.verdict);
        assert_eq!(rt.held_minor(&root.grant.id()), 10);
        let d = rt.settle_chained_priced(&chain, held.unwrap().id, Energy::measured(5), &Price::new("USD", 3));
        assert_eq!((d.verdict, d.debited_minor), (Verdict::Allow, 3));
        assert_eq!(rt.authorize_chained(&f, &chain, who, 103).verdict, FULL);
    }

    /// A debit that arrives with no admission recorded for it stays inside
    /// every window, so a window is never emptied by charging around it.
    #[test]
    fn a_debit_without_an_admission_stays_in_the_window() {
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxUj(100))]);
        let mut rt = Runtime::new();
        rt.charge(&sg.grant, Energy::measured(100));
        let f = frame(&sg, r, "read", Trust::Control);
        assert_eq!(rt.authorize(&f, &sg, holder, 1_000_000).verdict, FULL);
    }

    /// A parent's window counts what every delegate spends under it: two
    /// siblings cannot each take the parent's limit.
    #[test]
    fn a_parents_window_covers_its_delegates() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000_000, vec![within(60, WindowLimit::MaxCalls(2))]);
        let a = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 500_000, 0, [2; 16]).unwrap();
        let b = jcp_grant::attenuate(&root, &sk(2), did(&sk(4)), Capability::new(r, ["read"]), 500_000, 0, [3; 16]).unwrap();
        let mut rt = Runtime::new();
        let (fa, fb) = (frame(&a, r, "read", Trust::Control), frame(&b, r, "read", Trust::Control));
        let ca = [root.clone(), a.clone()];
        let cb = [root.clone(), b.clone()];
        assert!(rt.decide_chained(&fa, &ca, did(&sk(3)), Energy::measured(1), 100).is_allow());
        assert!(rt.decide_chained(&fb, &cb, did(&sk(4)), Energy::measured(1), 101).is_allow());
        assert_eq!(rt.decide_chained(&fa, &ca, did(&sk(3)), Energy::measured(1), 102).verdict, FULL);
        assert_eq!(rt.authorize_chained(&fb, &cb, did(&sk(4)), 103).verdict, FULL);
        assert!(rt.authorize_chained(&fb, &cb, did(&sk(4)), 160).is_allow());
    }

    /// Over a chain in the two-phase path, a joule window on any link binds at
    /// the debit, and every link keeps the joules.
    #[test]
    fn a_chained_joule_window_binds_at_the_debit() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000_000, vec![within(60, WindowLimit::MaxUj(500))]);
        let a = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 500_000, 0, [2; 16]).unwrap();
        let chain = [root.clone(), a.clone()];
        let f = frame(&a, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        assert!(rt.authorize_chained(&f, &chain, did(&sk(3)), 100).is_allow());
        assert_eq!(rt.charge_chained(&chain, Energy::measured(600)).verdict, FULL);
        assert_eq!((rt.spent(&root.grant.id()), rt.spent(&a.grant.id())), (600, 600));
        assert_eq!(rt.authorize_chained(&f, &chain, did(&sk(3)), 110).verdict, FULL);
    }

    /// A runtime restored from a spend ledger cannot know what its windows
    /// held, so it counts each as full until a whole window has passed since
    /// the time its history is declared complete. Grants with no window are
    /// unaffected.
    #[test]
    fn a_restored_runtime_counts_its_windows_as_full_until_their_history_is_known() {
        let (sg, holder, r) = caveated(vec![within(60, WindowLimit::MaxCalls(5))]);
        let f = frame(&sg, r, "read", Trust::Control);
        let (plain, plain_holder, _) = caveated(vec![]);
        let pf = frame(&plain, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        rt.restore([(sg.grant.id(), 10)]);
        assert_eq!(rt.decide(&f, &sg, holder, Energy::measured(1), 5_000).verdict, FULL);
        assert!(rt.decide(&pf, &plain, plain_holder, Energy::measured(1), 5_000).is_allow());

        rt.resume_windows_at(1_000);
        assert_eq!(rt.decide(&f, &sg, holder, Energy::measured(1), 1_059).verdict, FULL);
        assert!(rt.decide(&f, &sg, holder, Energy::measured(1), 1_060).is_allow());

        let mut empty = Runtime::new();
        empty.restore([]);
        assert!(empty.decide(&f, &sg, holder, Energy::measured(1), 0).is_allow(), "nothing restored, nothing unknown");
    }

    /// Restoring is never authority to lower a spend (SPEC §8.1): each entry
    /// adds to what the runtime already holds, so a ledger replayed into a
    /// runtime that has decided calls, or one naming a grant more than once,
    /// can only raise it.
    #[test]
    fn a_restore_adds_to_a_recorded_spend_and_never_lowers_it() {
        let (sg, holder, r) = caveated(vec![]);
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        assert!(rt.decide(&f, &sg, holder, Energy::measured(900), 10).is_allow());
        rt.restore([(sg.grant.id(), 100), (sg.grant.id(), 50)]);
        assert_eq!(rt.spent(&sg.grant.id()), 1_050, "a restore lowered or replaced a recorded spend");
    }

    /// The same in every dimension a ledger restores: money and the tainted
    /// sub-budget add to what a runtime holds, and never replace it.
    #[test]
    fn a_ledger_restore_adds_in_every_dimension() {
        let (sg, holder, r) = priced_setup(10_000, 1_000);
        let f = frame(&sg, r, "read", Trust::Control);
        let mut rt = Runtime::new();
        assert!(rt.decide_priced(&f, &sg, holder, Energy::measured(900), &Price::new("USD", 300), 10).is_allow());
        let id = sg.grant.id();
        rt.spent_tainted_uj.insert(id, 70);
        rt.restore_ledger(Ledger {
            uj: vec![(id, 100)],
            minor: vec![(id, 200), (id, 5)],
            tainted_uj: vec![(id, 30)],
            ..Ledger::default()
        });
        assert_eq!((rt.spent(&id), rt.spent_minor(&id), rt.spent_tainted(&id)), (1_000, 505, 100));
    }

    /// A hold's figure (SPEC §8.1) is no less than any charge of the work it
    /// lets run can debit, and restored as a debit and a tainted accrual it
    /// leaves the gate refusing what the charge could have left it refusing.
    #[test]
    fn a_hold_bound_covers_every_charge_the_work_can_make() {
        // A tainted wallet larger than the joules left, so the two parts differ.
        let wallet = FlowCeiling { ceiling: Label::top(), tainted_budget_uj: Some(500) };
        let (sg, holder, r) = flow_grant(vec![Caveat::FlowBelow(wallet)]);
        let f = frame(&sg, r, "read", Trust::Control);
        let id = sg.grant.id();
        let mut rt = Runtime::new();
        assert!(rt.authorize_flow(&f, &sg, holder, 10, &tainted(1)).is_allow());
        rt.charge_flow(&sg.grant, Energy::measured(30), &tainted(1));
        assert_eq!(rt.hold_bound(&sg.grant, &FlowFacts::bottom()), 70, "a clean call: the joules left");
        assert_eq!(rt.hold_bound(&sg.grant, &tainted(1)), 470, "a tainted call: also the wallet left");

        for cost in [0, 1, 69, 70, 71, 5_000] {
            let mut ran = rt.clone();
            assert!(ran.authorize_flow(&f, &sg, holder, 11, &tainted(1)).is_allow());
            let d = ran.charge_flow(&sg.grant, Energy::measured(cost), &tainted(1));
            assert!(d.debited_uj <= rt.hold_bound(&sg.grant, &tainted(1)), "cost {cost}: the debit passed the hold");
        }
        let mut held = rt.clone();
        let bound = rt.hold_bound(&sg.grant, &tainted(1));
        held.restore_ledger(Ledger { uj: vec![(id, bound)], minor: vec![], tainted_uj: vec![(id, bound)], ..Ledger::default() });
        assert_eq!(held.authorize_flow(&f, &sg, holder, 12, &tainted(1)).verdict, Verdict::Deny(DenyReason::BudgetExceeded));
        assert!(held.spent_tainted(&id) >= 500, "the wallet reads as spent");
    }

    /// SPEC §8.1: an unsettled hold counts against the budget a decision is
    /// made from, live as well as on replay. A call decided while a held
    /// call's work runs is decided against the remainder less the hold, which
    /// in the two-phase path is nothing, on every path that decides under the
    /// grant; settling replaces the hold with what the work debited. Decided
    /// against the settled spend alone, each such call would be admitted
    /// against the whole remainder the held work may still spend.
    #[test]
    fn a_hold_counts_against_its_grant_until_it_settles() {
        let (sg, holder, r) = setup();
        let f = frame(&sg, r, "read", Trust::Control);
        let id = sg.grant.id();
        let clean = FlowFacts::bottom();
        let mut rt = Runtime::new();
        assert!(rt.decide(&f, &sg, holder, Energy::measured(30), 10).is_allow());

        let (auth, held) = rt.hold(&f, &sg, holder, 10, &clean);
        assert!(auth.is_allow());
        let h = held.expect("the hold was allowed");
        assert_eq!((auth.budget_remaining_uj, h.uj), (70, 70), "the hold states what the grant has left");
        assert_eq!((rt.spent(&id), rt.held(&id)), (30, 70), "a hold debits nothing, and counts");

        let full = Verdict::Deny(DenyReason::BudgetExceeded);
        let seen = |d: Decision| (d.verdict, d.budget_remaining_uj);
        assert_eq!(seen(rt.authorize(&f, &sg, holder, 11)), (full, 0), "the remainder less the hold");
        assert_eq!(seen(rt.authorize_flow(&f, &sg, holder, 11, &clean)), (full, 0));
        assert_eq!(seen(rt.decide(&f, &sg, holder, Energy::measured(1), 11)), (full, 0));
        assert_eq!(seen(rt.decide_flow(&f, &sg, holder, Energy::measured(1), 11, &clean)), (full, 0));
        assert_eq!(seen(rt.decide_priced(&f, &sg, holder, Energy::measured(1), &Price::free("USD"), 11)), (full, 0));
        let (again, none) = rt.hold(&f, &sg, holder, 11, &clean);
        assert_eq!((again.verdict, none.is_none()), (full, true), "a second hold under the grant waits for the first");
        assert_eq!(rt.clone().authorize(&f, &sg, holder, 11).verdict, full, "a fork carries the hold");
        assert_eq!(rt.spent(&id), 30, "nothing refused was debited");

        let settled = rt.settle(&sg.grant, h.id, Energy::measured(20), &clean);
        assert!(settled.is_allow());
        assert_eq!((settled.debited_uj, settled.budget_remaining_uj), (20, 50));
        assert_eq!((rt.spent(&id), rt.held(&id)), (50, 0), "the settle replaced the hold with the work's debit");
        assert_eq!(seen(rt.authorize(&f, &sg, holder, 12)), (Verdict::Allow, 50));
        assert!(rt.decide(&f, &sg, holder, Energy::measured(50), 12).is_allow());
    }

    /// A hold counts on every path that decides under its grant, chained ones
    /// included: a delegate's call through a held root is decided against the
    /// root's remainder less the hold.
    #[test]
    fn a_held_root_admits_no_delegate_until_it_settles() {
        let (chain_a, _, sub, r) = chain_setup();
        let root = &chain_a[0];
        let clean = FlowFacts::bottom();
        let mut rt = Runtime::new();
        let (auth, held) = rt.hold(&frame(root, r, "read", Trust::Control), root, did(&sk(2)), 10, &clean);
        let h = held.expect("the hold was allowed");
        assert_eq!((auth.is_allow(), h.uj), (true, 1_000));
        let leaf = leaf_frame(&chain_a, r);
        let d = rt.decide_chained(&leaf, &chain_a, sub, Energy::measured(1), 10);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::BudgetExceeded));
        let d = rt.authorize_chained(&leaf, &chain_a, sub, 10);
        assert_eq!((d.verdict, d.budget_remaining_uj), (Verdict::Deny(DenyReason::BudgetExceeded), 0));

        rt.settle(&root.grant, h.id, Energy::measured(300), &clean);
        let d = rt.decide_chained(&leaf, &chain_a, sub, Energy::measured(600), 10);
        assert!(d.is_allow(), "the root has 700 left once its hold settles at 300");
        assert_eq!(rt.spent(&root.grant.id()), 900);
    }

    /// A hold placed through a delegation chain names every link and counts
    /// against each the most the work can debit any of them: a sibling
    /// delegate's call through the held root is refused, as are the
    /// delegate's own next call and the root's holder's. Settling replaces
    /// the hold on every link with that link's own debit.
    #[test]
    fn a_chained_hold_counts_on_every_link_until_it_settles() {
        let (chain_a, chain_b, sub, r) = chain_setup();
        let (root, a) = (chain_a[0].grant.id(), chain_a[1].grant.id());
        let fa = leaf_frame(&chain_a, r);
        let fb = leaf_frame(&chain_b, r);
        let mut rt = Runtime::new();
        let (auth, held) = rt.hold_chained(&fa, &chain_a, sub, 10);
        let h = held.expect("the chained hold was allowed");
        assert!(auth.is_allow());
        assert_eq!((auth.budget_remaining_uj, h.uj), (600, 1_000), "the root's remainder bounds what the work can debit it");
        assert_eq!((rt.held(&root), rt.held(&a), rt.spent(&root), rt.spent(&a)), (1_000, 1_000, 0, 0));

        let full = Verdict::Deny(DenyReason::BudgetExceeded);
        assert_eq!(rt.decide_chained(&fb, &chain_b, sub, Energy::measured(1), 10).verdict, full, "a sibling through the held root");
        let d = rt.authorize_chained(&fb, &chain_b, sub, 10);
        assert_eq!((d.verdict, d.budget_remaining_uj), (full, 0));
        let (again, none) = rt.hold_chained(&fb, &chain_b, sub, 10);
        assert_eq!((again.verdict, none), (full, None), "a second hold through the root waits for the first");
        assert_eq!(rt.authorize_chained(&fa, &chain_a, sub, 10).verdict, full, "the delegate's own next call");
        let froot = frame(&chain_a[0], r, "read", Trust::Control);
        assert_eq!(rt.decide(&froot, &chain_a[0], did(&sk(2)), Energy::measured(1), 10).verdict, full, "the root's holder");
        assert_eq!((rt.spent(&root), rt.spent(&a)), (0, 0), "nothing refused was debited");

        let d = rt.settle_chained(&chain_a, h.id, Energy::measured(700));
        assert_eq!(d.chain_debited_uj, vec![700, 600], "each link saturates at its own ceiling");
        assert_eq!((rt.held(&root), rt.held(&a), rt.spent(&root), rt.spent(&a)), (0, 0, 700, 600));
        assert!(rt.decide_chained(&fb, &chain_b, sub, Energy::measured(300), 10).is_allow(), "the root has 300 left");
        assert_eq!(rt.spent(&root), 1_000);
    }

    /// A tainted call's hold states the wallet left where that is more than
    /// the joules, and settles to what the work spent and accrued.
    #[test]
    fn a_tainted_hold_settles_to_what_its_work_spent() {
        let wallet = FlowCeiling { ceiling: Label::top(), tainted_budget_uj: Some(500) };
        let (sg, holder, r) = flow_grant(vec![Caveat::FlowBelow(wallet)]);
        let f = frame(&sg, r, "read", Trust::Control);
        let id = sg.grant.id();
        let mut rt = Runtime::new();
        let (auth, held) = rt.hold(&f, &sg, holder, 10, &tainted(1));
        let h = held.expect("the hold was allowed");
        assert_eq!((auth.is_allow(), h.uj), (true, 500));
        assert_eq!((rt.spent(&id), rt.spent_tainted(&id), rt.held(&id)), (0, 0, 500));
        let next = rt.authorize_flow(&f, &sg, holder, 11, &tainted(1));
        assert_eq!(next.verdict, Verdict::Deny(DenyReason::BudgetExceeded));

        let d = rt.settle(&sg.grant, h.id, Energy::measured(40), &tainted(1));
        assert_eq!((d.debited_uj, d.tainted_uj), (40, 40));
        assert_eq!((rt.spent(&id), rt.spent_tainted(&id), rt.held(&id)), (40, 40, 0));
        assert!(rt.authorize_flow(&f, &sg, holder, 12, &tainted(1)).is_allow());
    }

    /// A window of zero seconds would bound nothing, so it is refused rather
    /// than read as no limit.
    #[test]
    fn a_zero_second_window_is_refused() {
        let (sg, holder, r) = caveated(vec![within(0, WindowLimit::MaxCalls(1_000))]);
        let f = frame(&sg, r, "read", Trust::Control);
        let d = Runtime::new().decide(&f, &sg, holder, Energy::measured(1), 100);
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
    }
    /// §8.1. A hold resolves exactly once. Before this, `settle` removed the
    /// hold unconditionally and then debited, so a second settle — a retry, a
    /// replay, or a completion crossing a cancel — debited the same work again:
    /// measured at 80 µJ spent for 40 µJ of work.
    #[test]
    fn a_hold_resolves_exactly_once() {
        let (sg, holder, r) = setup(); // 100 µJ
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();
        let bottom = FlowFacts::bottom();
        let mut rt = Runtime::new();

        let h = rt.hold(&f, &sg, holder, 10, &bottom).1.expect("allowed");
        assert!(rt.settle(&sg.grant, h.id, Energy::measured(40), &bottom).is_allow());
        assert_eq!(rt.spent(&gid), 40);

        let again = rt.settle(&sg.grant, h.id, Energy::measured(40), &bottom);
        assert_eq!(again.verdict, Verdict::Deny(DenyReason::AlreadyResolved));
        assert_eq!(again.debited_uj, 0, "a refused resolution debits nothing");
        assert_eq!(rt.spent(&gid), 40, "the same work is not debited twice");
    }

    /// A cancellation resolves a hold whose work will never complete, debiting
    /// the joules it really burned. It is not a refund: before this there was no
    /// way to resolve such a hold at all, so the grant refused every later call
    /// for good while the abandoned work went unrecorded.
    #[test]
    fn a_cancellation_resolves_an_abandoned_hold_and_debits_what_ran() {
        let (sg, holder, r) = setup();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();
        let bottom = FlowFacts::bottom();
        let mut rt = Runtime::new();

        let h = rt.hold(&f, &sg, holder, 10, &bottom).1.expect("allowed");
        assert_eq!((rt.held(&gid), rt.spent(&gid)), (100, 0));

        let d = rt.cancel(&sg.grant, h.id, holder, Energy::measured(40), &bottom);
        assert!(d.is_allow(), "the subject may cancel its own work");
        assert_eq!(rt.spent(&gid), 40, "debited, not refunded");
        assert_eq!(rt.held(&gid), 0, "and the hold stops counting");
        assert!(rt.authorize(&f, &sg, holder, 10).is_allow(), "the grant works again");

        // Resolved once: a second cancel, and a late completion, both lose.
        let h2 = rt.hold(&f, &sg, holder, 10, &bottom).1.expect("allowed");
        assert!(rt.cancel(&sg.grant, h2.id, holder, Energy::measured(10), &bottom).is_allow());
        assert_eq!(
            rt.cancel(&sg.grant, h2.id, holder, Energy::measured(10), &bottom).verdict,
            Verdict::Deny(DenyReason::AlreadyResolved),
        );
        assert_eq!(
            rt.settle(&sg.grant, h2.id, Energy::measured(50), &bottom).verdict,
            Verdict::Deny(DenyReason::AlreadyResolved),
            "a completion that crossed the cancellation",
        );
        assert_eq!(rt.spent(&gid), 50, "40 + 10, and nothing from the losers");
    }

    /// Only the subject or the issuer may cancel, and a refusal leaves the hold
    /// outstanding — otherwise refusing a stranger would still have stranded
    /// the budget the stranger could not spend.
    #[test]
    fn only_the_subject_or_issuer_may_cancel_and_a_refusal_leaves_the_hold() {
        let (sg, holder, r) = setup();
        let f = frame(&sg, r, "read", Trust::Control);
        let gid = sg.grant.id();
        let bottom = FlowFacts::bottom();
        let mut rt = Runtime::new();

        let h = rt.hold(&f, &sg, holder, 10, &bottom).1.expect("allowed");
        assert_eq!(
            rt.cancel(&sg.grant, h.id, did(&sk(9)), Energy::measured(40), &bottom).verdict,
            Verdict::Deny(DenyReason::WrongSubject),
        );
        assert_eq!(rt.held(&gid), 100, "a refused cancel does not resolve the hold");
        assert_eq!(rt.spent(&gid), 0, "and debits nothing");

        // The issuer can: §4.3 already lets it revoke the grant outright.
        assert!(rt.cancel(&sg.grant, h.id, did(&sk(1)), Energy::measured(40), &bottom).is_allow());
        assert_eq!(rt.spent(&gid), 40);
    }

    /// An abandoned delegated run debits every link, as a settled one does
    /// (§4.2): otherwise a delegate could spend its parent's joules by always
    /// cancelling.
    #[test]
    fn an_abandoned_chained_run_debits_every_link() {
        let r = ContentId::of_bytes(b"db");
        let root = chain_root(1_000, Vec::new());
        let child = jcp_grant::attenuate(&root, &sk(2), did(&sk(3)), Capability::new(r, ["read"]), 600, 0, [2; 16]).unwrap();
        let chain = [root.clone(), child.clone()];
        let mut rt = Runtime::new();
        let f = frame(&child, r, "read", Trust::Control);

        let h = rt.hold_chained(&f, &chain, did(&sk(3)), 10).1.expect("allowed");
        assert_eq!(rt.held(&root.grant.id()), 1_000, "the hold binds the root too");

        assert_eq!(
            rt.cancel_chained(&chain, h.id, did(&sk(9)), Energy::measured(250)).verdict,
            Verdict::Deny(DenyReason::WrongSubject),
        );
        let d = rt.cancel_chained(&chain, h.id, did(&sk(3)), Energy::measured(250));
        assert!(d.is_allow());
        assert_eq!(rt.spent(&root.grant.id()), 250, "the root paid for the abandoned run");
        assert_eq!(rt.spent(&child.grant.id()), 250);
        assert_eq!(rt.held(&root.grant.id()), 0);
        assert_eq!(
            rt.settle_chained(&chain, h.id, Energy::measured(600)).verdict,
            Verdict::Deny(DenyReason::AlreadyResolved),
        );
        assert_eq!(rt.spent(&root.grant.id()), 250, "the late settle debited nothing");
    }
}

#[cfg(test)]
mod hold_invariants {
    //! Randomised invariant checks over the two-phase path.
    //!
    //! The two defects found by hand in this accounting — a resolution that
    //! released every hold on a grant, and a bound sized from the debited
    //! rather than the committed spend — were both found by writing one
    //! adversarial sequence and watching it fail. This runs many sequences and
    //! asserts the properties those failures violated, so the rest of that
    //! family is found by machine rather than by whoever next writes the right
    //! test by hand.
    //!
    //! Deterministic: a seeded generator, so a failure is reproducible from the
    //! seed printed in the panic. No dependency on a fuzzing harness.
    //!
    //! The seed counts are kept low enough that the suite stays quick — every
    //! decision verifies a signature, which dominates — and raising them is the
    //! first thing to try when hunting a suspected accounting bug.

    use super::*;
    use ed25519_dalek::SigningKey;
    use jcp_grant::issue;
    use jcp_schema::{Capability, Caveat, FrameKind, Funds, Grant};

    /// A small deterministic generator. Not cryptographic; it only has to walk
    /// a lot of different op orders reproducibly.
    struct Rng(u64);
    impl Rng {
        fn next(&mut self) -> u64 {
            // xorshift64*
            let mut x = self.0;
            x ^= x >> 12;
            x ^= x << 25;
            x ^= x >> 27;
            self.0 = x;
            x.wrapping_mul(0x2545_F491_4F6C_DD1D)
        }
        fn below(&mut self, n: u64) -> u64 {
            if n == 0 { 0 } else { self.next() % n }
        }
        /// An amount near `edge`. A bound is decided at the values either
        /// side of it, and an amount drawn evenly from a range lands there
        /// about never: so most draws are the edge itself, one over, one
        /// under, nothing, and well past it.
        fn around(&mut self, edge: u64) -> u64 {
            match self.below(8) {
                0 => 0,
                1 | 2 => edge,
                3 => edge.saturating_add(1),
                4 => edge.saturating_sub(1),
                5 => edge / 2,
                6 => edge.saturating_mul(3),
                _ => self.below(edge.saturating_add(40)),
            }
        }
    }

    fn sk(s: u8) -> SigningKey {
        SigningKey::from_bytes(&[s; 32])
    }
    fn did(k: &SigningKey) -> Did {
        Did::from_verifying_key(&k.verifying_key())
    }

    fn setup(budget_uj: u64, minor: u64, per_call: Option<u64>) -> (SignedGrant, Did, Frame) {
        let issuer = sk(1);
        let holder = sk(2);
        let resource = ContentId::of_bytes(b"db");
        let g = Grant {
            issuer: did(&issuer),
            subject: did(&holder),
            capability: Capability::new(resource, ["read"]),
            budget_uj,
            budget_funds: Some(Funds::new("USD", minor)),
            caveats: per_call.map(Caveat::MaxCostUj).into_iter().collect(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [5; 16],
        };
        let sg = issue(&issuer, g).unwrap();
        let frame = Frame {
            kind: FrameKind::ToolCall,
            trust: Trust::Control,
            grant_id: sg.grant.id(),
            resource,
            action: "read".into(),
            payload_hash: ContentId::of_bytes(b"args"),
            model: None,
        };
        (sg, did(&holder), frame)
    }

    /// The properties every sequence must leave intact.
    fn check(rt: &Runtime, g: &Grant, seed: u64, step: usize, outstanding: &[(HoldId, u64, u64)]) {
        let gid = g.id();
        let funds = g.budget_funds.as_ref().map_or(0, |f| f.minor);

        // 1. Neither dimension is ever committed past its ceiling. This is the
        //    property an over-sized hold breaks.
        assert!(
            rt.spent(&gid).saturating_add(rt.held(&gid)) <= g.budget_uj,
            "seed {seed} step {step}: committed joules {} + {} over the {} ceiling",
            rt.spent(&gid),
            rt.held(&gid),
            g.budget_uj
        );
        assert!(
            rt.net_minor(&gid).saturating_add(rt.held_minor(&gid)) <= funds,
            "seed {seed} step {step}: committed money {} net + {} held over the {funds} ceiling",
            rt.net_minor(&gid),
            rt.held_minor(&gid)
        );
        // Refunds never exceed what was debited: net spend cannot go negative.
        assert!(rt.refunded_minor(&gid) <= rt.spent_minor(&gid), "seed {seed} step {step}: over-refunded");

        // 2. What is held equals the sum of what the outstanding holds
        //    reserved. This is the property a resolution that released every
        //    hold broke: it left the sums disagreeing with the handles.
        let (want_uj, want_minor) = outstanding
            .iter()
            .fold((0u64, 0u64), |(a, b), (_, uj, m)| (a + uj, b + m));
        assert_eq!(
            (rt.held(&gid), rt.held_minor(&gid)),
            (want_uj, want_minor),
            "seed {seed} step {step}: {} holds outstanding but the reserved sums disagree",
            outstanding.len()
        );
        assert_eq!(rt.outstanding_holds(&gid), outstanding.len(), "seed {seed} step {step}");
    }

    #[test]
    fn random_hold_sequences_keep_both_ceilings_and_the_reservation_sums() {
        for seed in 1..=120u64 {
            let mut rng = Rng(seed.wrapping_mul(0x9E37_79B9_7F4A_7C15) | 1);
            // Half the grants state a per-call ceiling, so both the concurrent
            // and the serializing shape are exercised.
            let per_call = if seed % 2 == 0 { Some(50) } else { None };
            let (sg, holder, frame) = setup(1_000, 1_000, per_call);
            let mut rt = Runtime::new();
            let mut outstanding: Vec<(HoldId, u64, u64)> = Vec::new();
            let facts = FlowFacts::bottom();

            for step in 0..40 {
                match rng.below(8) {
                    // capture part of an outstanding hold
                    5 if !outstanding.is_empty() => {
                        let i = rng.below(outstanding.len() as u64) as usize;
                        let (id, uj, minor) = outstanding[i];
                        let amount = rng.around(minor); // exactly what is left, and either side of it
                        let d = rt.capture_priced(
                            &sg.grant,
                            id,
                            Energy::measured(rng.below(30)),
                            &Price::new("USD", amount),
                            10,
                            &facts,
                        );
                        if d.is_allow() {
                            outstanding[i] = (id, uj.saturating_sub(d.debited_uj), minor - amount);
                        } else {
                            assert_eq!(
                                rt.hold_remaining(&sg.grant.id(), id),
                                Some((uj, minor)),
                                "seed {seed} step {step}: a refused capture moved the hold"
                            );
                        }
                    }
                    // the issuer refunds some of what was really spent
                    6 => {
                        let net = rt.net_minor(&sg.grant.id());
                        let amount = rng.around(net); // exactly what is refundable, and either side of it
                        let d = rt.refund(&sg.grant, sg.grant.issuer, &Price::new("USD", amount));
                        assert_eq!(d.is_allow(), amount <= net, "seed {seed} step {step}: refund bound");
                    }
                    // the subject tries to refund itself: never
                    7 => {
                        let before = rt.refunded_minor(&sg.grant.id());
                        let d = rt.refund(&sg.grant, holder, &Price::new("USD", 1));
                        assert!(!d.is_allow(), "seed {seed}: a subject refunded itself");
                        assert_eq!(rt.refunded_minor(&sg.grant.id()), before);
                    }
                    // place a priced hold
                    0 | 1 => {
                        let gid = sg.grant.id();
                        let free = 1_000u64.saturating_sub(rt.net_minor(&gid) + rt.held_minor(&gid));
                        let ceiling = Price::new("USD", if rng.below(2) == 0 { rng.around(free) } else { rng.below(400) });
                        let (d, held) =
                            rt.hold_priced(&frame, &sg, holder, 10, &facts, &ceiling);
                        match held {
                            Some(h) => {
                                assert!(d.is_allow());
                                outstanding.push((h.id, h.uj, h.minor));
                            }
                            None => assert!(!d.is_allow(), "a refused hold returned a handle"),
                        }
                    }
                    // resolve one outstanding hold, named
                    2 | 3 if !outstanding.is_empty() => {
                        let i = rng.below(outstanding.len() as u64) as usize;
                        let (id, _uj, minor) = outstanding[i];
                        // settle at or under what this hold reserved
                        let settled = Price::new("USD", rng.around(minor).min(minor));
                        let measured = Energy::measured(rng.below(60));
                        let d = rt.settle_priced(&sg.grant, id, measured, &settled, &facts);
                        // A deny can still consume the hold: a per-call joule
                        // overrun debits what ran and carries the breach in the
                        // verdict. Resolution is not the same as allowance.
                        if d.consumed_the_hold() {
                            outstanding.remove(i);
                        }
                    }
                    // resolve a stale or unknown handle: must change nothing
                    4 => {
                        let before =
                            (rt.spent(&sg.grant.id()), rt.spent_minor(&sg.grant.id()), rt.held(&sg.grant.id()));
                        let bogus = HoldId(u64::MAX - rng.below(8));
                        let d = rt.settle_priced(
                            &sg.grant,
                            bogus,
                            Energy::measured(99),
                            &Price::new("USD", 99),
                            &facts,
                        );
                        assert!(
                            !d.consumed_the_hold(),
                            "seed {seed}: an unknown handle resolved something"
                        );
                        let after =
                            (rt.spent(&sg.grant.id()), rt.spent_minor(&sg.grant.id()), rt.held(&sg.grant.id()));
                        assert_eq!(before, after, "seed {seed}: a refused resolution moved the books");
                    }
                    2 | 3 => {} // nothing outstanding to resolve
                    _ => {
                        // an ordinary priced decision, which must respect both
                        // ceilings including what is held
                        let _ = rt.decide_priced(
                            &frame,
                            &sg,
                            holder,
                            Energy::measured(rng.below(40)),
                            &Price::new("USD", {
                                let gid = sg.grant.id();
                                rng.around(1_000u64.saturating_sub(rt.net_minor(&gid) + rt.held_minor(&gid)))
                            }),
                            10,
                        );
                    }
                }
                check(&rt, &sg.grant, seed, step, &outstanding);
            }

            // Draining every remaining hold leaves nothing reserved.
            for (id, _, _) in std::mem::take(&mut outstanding) {
                rt.settle_priced(&sg.grant, id, Energy::measured(0), &Price::new("USD", 0), &facts);
            }
            assert_eq!(
                (rt.held(&sg.grant.id()), rt.held_minor(&sg.grant.id())),
                (0, 0),
                "seed {seed}: holds survived being resolved one by one"
            );
        }
    }

    /// A parent with a money ceiling and a per-call joule ceiling, and two
    /// delegates under it — the shape of an agent handing metered work to
    /// sub-agents.
    fn family(per_call: Option<u64>) -> (SignedGrant, [SignedGrant; 2], [Frame; 2], [Did; 2]) {
        let r = ContentId::of_bytes(b"db");
        let root = issue(
            &sk(1),
            Grant {
                issuer: did(&sk(1)),
                subject: did(&sk(2)),
                capability: Capability::new(r, ["read"]),
                budget_uj: 2_000,
                budget_funds: Some(Funds::new("USD", 1_000)),
                caveats: per_call.map(Caveat::MaxCostUj).into_iter().collect(),
                expiry: 0,
                parent: None,
                delegate_depth: None,
                nonce: [6; 16],
            },
        )
        .unwrap();
        let kid = |seed: u8, budget: u64| {
            jcp_grant::attenuate(&root, &sk(2), did(&sk(seed)), Capability::new(r, ["read"]), budget, 0, [seed; 16])
                .unwrap()
        };
        let kids = [kid(3, 1_500), kid(4, 1_500)];
        let frame = |sg: &SignedGrant| Frame {
            kind: FrameKind::ToolCall,
            trust: Trust::Control,
            grant_id: sg.grant.id(),
            resource: r,
            action: "read".into(),
            payload_hash: ContentId::of_bytes(b"args"),
            model: None,
        };
        let frames = [frame(&kids[0]), frame(&kids[1])];
        (root, kids, frames, [did(&sk(3)), did(&sk(4))])
    }

    /// **Sibling delegates doing metered work at once.** With a per-call
    /// ceiling on the parent, each delegate's hold reserves its bound rather
    /// than the parent's whole remainder, so both run concurrently — and the
    /// parent's ceiling, in both dimensions, still bounds them together.
    #[test]
    fn sibling_delegates_hold_and_capture_concurrently_under_one_parent() {
        let (root, kids, frames, who) = family(Some(100));
        let chains = [vec![root.clone(), kids[0].clone()], vec![root.clone(), kids[1].clone()]];
        let mut rt = Runtime::new();
        let rid = root.grant.id();

        let a = rt.hold_chained_priced(&frames[0], &chains[0], who[0], 10, &Price::new("USD", 400)).1.expect("a");
        let b = rt.hold_chained_priced(&frames[1], &chains[1], who[1], 10, &Price::new("USD", 400)).1.expect("b");
        assert_eq!((a.uj, b.uj), (100, 100), "each reserves the per-call bound, not the parent's remainder");
        assert_eq!((rt.held(&rid), rt.held_minor(&rid)), (200, 800), "the parent carries both");

        // a third sibling-sized hold does not fit the parent's money
        let (d, none) = rt.hold_chained_priced(&frames[0], &chains[0], who[0], 10, &Price::new("USD", 400));
        assert_eq!(d.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert!(none.is_none());

        // each draws on its own reservation, on every link
        let c = rt.capture_chained_priced(&chains[0], a.id, Energy::measured(30), &Price::new("USD", 150), 11);
        assert!(c.is_allow());
        assert_eq!(c.debited_minor, 150);
        assert_eq!(rt.hold_remaining(&rid, a.id), Some((70, 250)));
        assert_eq!(rt.hold_remaining(&kids[0].grant.id(), a.id), Some((70, 250)));
        assert_eq!(rt.hold_remaining(&rid, b.id), Some((100, 400)), "the sibling's reservation is untouched");
        assert_eq!((rt.spent_minor(&rid), rt.spent_minor(&kids[0].grant.id())), (150, 150));

        // over what is left is refused on the whole chain, cleanly
        let over = rt.capture_chained_priced(&chains[0], a.id, Energy::measured(1), &Price::new("USD", 251), 12);
        assert_eq!(over.verdict, Verdict::Deny(DenyReason::FundsExceeded));
        assert_eq!(rt.spent_minor(&rid), 150);

        // resolving one leaves the other standing on the parent
        assert!(rt.settle_chained_priced(&chains[0], a.id, Energy::measured(5), &Price::new("USD", 50)).is_allow());
        assert_eq!((rt.held(&rid), rt.held_minor(&rid), rt.spent_minor(&rid)), (100, 400, 200));
    }

    /// A chained hold with a deadline: past it the money comes back on every
    /// link and the joules stay reserved on every link.
    #[test]
    fn a_chained_hold_is_reclaimed_on_every_link_past_its_deadline() {
        let (root, kids, frames, who) = family(Some(100));
        let chain = vec![root.clone(), kids[0].clone()];
        let mut rt = Runtime::new();
        let (rid, kid) = (root.grant.id(), kids[0].grant.id());

        let h = rt
            .hold_chained_priced_until(&frames[0], &chain, who[0], 10, &Price::new("USD", 400), 100)
            .1
            .expect("held");
        assert_eq!(rt.reclaim_chained(&chain, h.id, 100).0.verdict, Verdict::Deny(DenyReason::CaveatUnsatisfied));
        assert!(rt.capture_chained_priced(&chain, h.id, Energy::measured(10), &Price::new("USD", 100), 50).is_allow());
        assert_eq!(
            rt.capture_chained_priced(&chain, h.id, Energy::measured(1), &Price::new("USD", 1), 101).verdict,
            Verdict::Deny(DenyReason::Expired)
        );
        let (d, released) = rt.reclaim_chained(&chain, h.id, 101);
        assert!(d.is_allow());
        assert_eq!(released, 300);
        assert_eq!((rt.held_minor(&rid), rt.held_minor(&kid)), (0, 0));
        assert_eq!((rt.held(&rid), rt.held(&kid)), (90, 90), "joules are not reclaimed on any link");
        assert_eq!((rt.spent_minor(&rid), rt.spent_minor(&kid)), (100, 100));
    }

    /// **Randomised sibling sequences.** Two delegates under one parent hold,
    /// capture, settle and reclaim in random order; after every step the
    /// parent's ceilings bound them together and the parent's reservations are
    /// exactly the sum of what its delegates still hold.
    #[test]
    fn random_sibling_sequences_keep_the_parent_as_the_sum_of_its_delegates() {
        for seed in 1..=80u64 {
            let mut rng = Rng(seed.wrapping_mul(0xD6E8_FEB8_6659_FD93) | 1);
            let (root, kids, frames, who) = family(Some(60));
            let chains = [vec![root.clone(), kids[0].clone()], vec![root.clone(), kids[1].clone()]];
            let rid = root.grant.id();
            let mut rt = Runtime::new();
            // (which delegate, handle, joules left, money left)
            let mut out: Vec<(usize, HoldId, u64, u64)> = Vec::new();

            for step in 0..40 {
                let k = rng.below(2) as usize;
                match rng.below(6) {
                    0 | 1 => {
                        let ceiling = Price::new("USD", rng.around(350));
                        let (d, h) = match rng.below(2) {
                            0 => rt.hold_chained_priced(&frames[k], &chains[k], who[k], 10, &ceiling),
                            _ => rt.hold_chained_priced_until(&frames[k], &chains[k], who[k], 10, &ceiling, 50),
                        };
                        if let Some(h) = h {
                            assert!(d.is_allow());
                            out.push((k, h.id, h.uj, h.minor));
                        }
                    }
                    2 if !out.is_empty() => {
                        let i = rng.below(out.len() as u64) as usize;
                        let (k, id, uj, minor) = out[i];
                        let amount = rng.around(minor);
                        // the deadline is 50: the moment itself, and either side
                        let now = if rng.below(2) == 0 { 49 + rng.below(3) } else { 10 + rng.below(60) };
                        let d = rt.capture_chained_priced(
                            &chains[k], id, Energy::measured(rng.below(25)), &Price::new("USD", amount), now,
                        );
                        if d.is_allow() {
                            // the parent's debit bounds the draw on the reservation
                            let drawn = if d.chain_debited_uj.is_empty() { d.debited_uj } else { d.chain_debited_uj[0] };
                            out[i] = (k, id, uj.saturating_sub(drawn), minor - amount);
                        }
                    }
                    3 if !out.is_empty() => {
                        let i = rng.below(out.len() as u64) as usize;
                        let (k, id, _, minor) = out[i];
                        let settled = Price::new("USD", rng.around(minor).min(minor));
                        let d = rt.settle_chained_priced(&chains[k], id, Energy::measured(rng.below(40)), &settled);
                        if d.consumed_the_hold() {
                            out.remove(i);
                        }
                    }
                    4 if !out.is_empty() => {
                        let i = rng.below(out.len() as u64) as usize;
                        let (k, id, uj, minor) = out[i];
                        let (d, released) = rt.reclaim_chained(&chains[k], id, if rng.below(2) == 0 { 49 + rng.below(3) } else { 10 + rng.below(60) });
                        if d.is_allow() {
                            assert_eq!(released, minor, "seed {seed} step {step}: a reclaim released other than what was held");
                            out[i] = (k, id, uj, 0);
                        }
                    }
                    _ => {}
                }

                // The parent's ceilings bound its delegates together.
                assert!(
                    rt.net_minor(&rid) + rt.held_minor(&rid) <= 1_000,
                    "seed {seed} step {step}: the parent's money is over-committed"
                );
                // The parent's reservations are the sum of its delegates'.
                let want_minor: u64 = out.iter().map(|(_, _, _, m)| *m).sum();
                assert_eq!(rt.held_minor(&rid), want_minor, "seed {seed} step {step}: parent money held");
                for (k, kid) in kids.iter().enumerate() {
                    let kid_minor: u64 = out.iter().filter(|(w, ..)| *w == k).map(|(_, _, _, m)| *m).sum();
                    assert_eq!(rt.held_minor(&kid.grant.id()), kid_minor, "seed {seed} step {step}: delegate {k}");
                }
                assert_eq!(rt.outstanding_holds(&rid), out.len(), "seed {seed} step {step}");
                // A delegate never spends more money than its parent recorded.
                let kids_spent: u64 = kids.iter().map(|g| rt.spent_minor(&g.grant.id())).sum();
                assert_eq!(rt.spent_minor(&rid), kids_spent, "seed {seed} step {step}: money conservation");
            }
        }
    }

    /// A hold resolves at most once, however many times it is presented, and a
    /// resolution that loses debits nothing.
    #[test]
    fn a_handle_resolves_at_most_once_across_random_retries() {
        for seed in 1..=60u64 {
            let mut rng = Rng(seed.wrapping_mul(0xA24B_AED4_963E_E407) | 1);
            let (sg, holder, frame) = setup(10_000, 10_000, Some(100));
            let mut rt = Runtime::new();
            let facts = FlowFacts::bottom();

            let mut handles = Vec::new();
            for _ in 0..4 {
                if let (_, Some(h)) =
                    rt.hold_priced(&frame, &sg, holder, 10, &facts, &Price::new("USD", 100))
                {
                    handles.push(h.id);
                }
            }
            let mut resolved = std::collections::BTreeSet::new();
            let mut debited = 0u64;
            for _ in 0..40 {
                if handles.is_empty() {
                    break;
                }
                let id = handles[rng.below(handles.len() as u64) as usize];
                let before = rt.spent_minor(&sg.grant.id());
                let d = rt.settle_priced(&sg.grant, id, Energy::measured(10), &Price::new("USD", 7), &facts);
                let after = rt.spent_minor(&sg.grant.id());
                if d.consumed_the_hold() {
                    assert!(resolved.insert(id), "seed {seed}: a handle resolved twice");
                    debited += 7;
                    assert_eq!(after, before + 7);
                } else {
                    assert_eq!(after, before, "seed {seed}: a losing resolution debited");
                }
            }
            assert_eq!(rt.spent_minor(&sg.grant.id()), debited, "seed {seed}");
            assert!(resolved.len() <= 4);
        }
    }
}
