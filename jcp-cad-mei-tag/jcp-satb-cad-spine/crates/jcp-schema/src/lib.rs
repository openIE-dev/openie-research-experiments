//! JCP schema (SPEC §2–§4) — the wire objects of the Joule Context Protocol.
//!
//! Four objects carry the whole substrate:
//!
//! - [`Did`] — every actor (model, agent, tool/server) is an Ed25519 `did:key`.
//!   No anonymous actors.
//! - [`Grant`] — the **metered capability**: a signed, content-addressed token
//!   binding a subject to a capability *and* a joule budget. The heart of JCP.
//! - [`Frame`] — every message, carrying its grant, a content-addressed payload,
//!   and a [`Trust`] tag separating principal *control* from untrusted *data*.
//! - The receipt (in `jcp-receipt`) seals every decision.
//!
//! Authorization and energy are one object here: a capability you cannot pay for
//! is denied, an expenditure you are not capable of is denied — checked
//! deterministically, outside any model.

use ed25519_dalek::VerifyingKey;
use serde::{Deserialize, Serialize};

mod cbor;
pub use cbor::{canonical_cbor, from_canonical_cbor};

pub mod flow;
pub use flow::{FlowCeiling, FlowFacts, Integrity, Label, Origin, Origins, Readers};

/// Errors from canonical serialization, content addressing, or DID parsing.
#[derive(Debug, thiserror::Error)]
pub enum SchemaError {
    #[error("disallowed type in canonical encoding: {0}")]
    DisallowedType(&'static str),
    #[error("malformed did:key: {0}")]
    BadDid(String),
}

/// `blake3` content address of any canonically-serialized value (SPEC §3).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
pub struct ContentId(pub [u8; 32]);

impl ContentId {
    pub fn of<T: Serialize>(value: &T) -> Result<Self, SchemaError> {
        Ok(Self::of_bytes(&canonical_cbor(value)?))
    }
    pub fn of_bytes(bytes: &[u8]) -> Self {
        ContentId(*blake3::hash(bytes).as_bytes())
    }
    pub fn to_hex(self) -> String {
        hex::encode(self.0)
    }
    pub fn from_hex(s: &str) -> Result<Self, SchemaError> {
        let raw = hex::decode(s).map_err(|e| SchemaError::BadDid(e.to_string()))?;
        let arr: [u8; 32] = raw.try_into().map_err(|_| SchemaError::BadDid("content id is not 32 bytes".into()))?;
        Ok(ContentId(arr))
    }
}

/// The multicodec prefix for an Ed25519 public key (`0xed 0x01`), per the
/// `did:key` method.
const ED25519_MULTICODEC: [u8; 2] = [0xed, 0x01];

/// An actor identity — an Ed25519 public key, rendered on the wire as a W3C
/// `did:key` (SPEC §2). Serializes to/from the `did:key:z…` string.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Hash, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(into = "String", try_from = "String")]
pub struct Did(pub [u8; 32]);

impl Did {
    pub fn from_verifying_key(vk: &VerifyingKey) -> Self {
        Did(vk.to_bytes())
    }
    pub fn verifying_key(&self) -> Result<VerifyingKey, SchemaError> {
        VerifyingKey::from_bytes(&self.0).map_err(|e| SchemaError::BadDid(e.to_string()))
    }
    /// The `did:key:z…` string (multibase base58btc of multicodec ‖ key).
    pub fn to_did_key(&self) -> String {
        let mut mc = ED25519_MULTICODEC.to_vec();
        mc.extend_from_slice(&self.0);
        format!("did:key:z{}", bs58::encode(mc).into_string())
    }
    pub fn parse(s: &str) -> Result<Self, SchemaError> {
        let z = s
            .strip_prefix("did:key:z")
            .ok_or_else(|| SchemaError::BadDid(format!("not a did:key:z… : {s}")))?;
        let raw = bs58::decode(z)
            .into_vec()
            .map_err(|e| SchemaError::BadDid(e.to_string()))?;
        if raw.len() != 34 || raw[0..2] != ED25519_MULTICODEC {
            return Err(SchemaError::BadDid("not an ed25519 did:key".into()));
        }
        let mut k = [0u8; 32];
        k.copy_from_slice(&raw[2..]);
        Ok(Did(k))
    }
}

impl From<Did> for String {
    fn from(d: Did) -> String {
        d.to_did_key()
    }
}
impl TryFrom<String> for Did {
    type Error = SchemaError;
    fn try_from(s: String) -> Result<Self, SchemaError> {
        Did::parse(&s)
    }
}

/// How honest an energy reading is (SPEC §5) — the family's provenance model.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Provenance {
    /// Read from a hardware energy interface: a dedicated shunt, or a vendor
    /// energy counter (RAPL, NVML, Apple IOReport, ...). A vendor counter's
    /// count is a real reading, not an estimate; how the vendor derives it is
    /// undisclosed and the platform relays it, which is a gap in provenance,
    /// not in accuracy. It earns this grade only while it is live for the domain
    /// the figure claims (SPEC §5): observed advancing under load. A counter
    /// that is present but frozen, or republished in lumps, never yields an
    /// `HwShunt` figure. Requires a measured figure.
    HwShunt,
    /// A model calibrated on the host or against a reading (time × a power
    /// the host measured, say), or a real reading apportioned by a model. A
    /// measured figure may be absent.
    ModelBased,
    /// A figure nothing calibrated: a coarse constant, or a model run at a
    /// default or assumed parameter — time × a default power is one. A
    /// measured figure MUST be absent.
    Estimator,
}

impl Provenance {
    pub fn jcr1_label(self) -> &'static str {
        match self {
            Provenance::HwShunt => "HwShunt",
            Provenance::ModelBased => "ModelBased",
            Provenance::Estimator => "Estimator",
        }
    }
}

/// How much of a unit of work an energy figure accounts for.
///
/// Deliberately separate from [`Provenance`]: a reading can be hardware-rooted
/// and still cover only part of the work, and reporting the two as one number
/// overstates it. A partial figure is not wrong — it is incomplete, and saying
/// which is the whole point.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
pub enum Coverage {
    /// The figure accounts for the whole unit of work.
    #[default]
    Whole,
    /// The figure accounts for only part of it. The remainder is **unmeasured**,
    /// which is not the same as zero, and a `Partial` figure MUST NOT be
    /// presented as a task total.
    Partial,
}

impl Coverage {
    /// Whether this is the default, wire-omitted case.
    pub fn is_whole(&self) -> bool {
        matches!(self, Coverage::Whole)
    }

    /// The wire label.
    pub fn label(self) -> &'static str {
        match self {
            Coverage::Whole => "Whole",
            Coverage::Partial => "Partial",
        }
    }
}

/// A two-part energy reading, integer microjoules (SPEC §5).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Energy {
    #[serde(skip_serializing_if = "Option::is_none")]
    pub measured_uj: Option<u64>,
    pub estimated_uj: u64,
    pub provenance: Provenance,
    /// How much of the work this figure accounts for.
    ///
    /// [`Provenance`] answers *how* the number was acquired; it says nothing
    /// about *how much of the task it covers*, and the two are routinely
    /// conflated to the figure's advantage. On a host where the accelerator
    /// exposes an energy counter but the CPU does not, a caller reads the
    /// accelerator and stamps `HwShunt` on a figure presented as the task's
    /// energy — the CPU's share is not zero, it is unmeasured and silently
    /// missing.
    ///
    /// Defaults to [`Coverage::Whole`] and is omitted from the wire in that
    /// case, so every previously sealed receipt and published vector is
    /// unchanged.
    #[serde(default, skip_serializing_if = "Coverage::is_whole")]
    pub coverage: Coverage,
}

impl Energy {
    pub fn modeled(uj: u64) -> Self {
        Energy { measured_uj: None, estimated_uj: uj, provenance: Provenance::ModelBased, coverage: Coverage::Whole }
    }
    pub fn measured(uj: u64) -> Self {
        Energy { measured_uj: Some(uj), estimated_uj: uj, provenance: Provenance::HwShunt, coverage: Coverage::Whole }
    }
    pub fn estimator(uj: u64) -> Self {
        Energy { measured_uj: None, estimated_uj: uj, provenance: Provenance::Estimator, coverage: Coverage::Whole }
    }
    /// A hardware reading that covers only part of the work — an accelerator
    /// counter on a host whose CPU has none, say.
    ///
    /// Exists so the honest case is as easy to express as the flattering one:
    /// without it, a caller with a partial reading reaches for
    /// [`Energy::measured`] and the figure silently claims the whole task.
    pub fn measured_partial(uj: u64) -> Self {
        Energy {
            measured_uj: Some(uj),
            estimated_uj: uj,
            provenance: Provenance::HwShunt,
            coverage: Coverage::Partial,
        }
    }

    /// Whether this figure accounts for the whole unit of work.
    pub fn is_whole(&self) -> bool {
        self.coverage.is_whole()
    }

    /// The figure to debit a budget by: the hardware reading if present, else the estimate.
    pub fn uj(&self) -> u64 {
        self.measured_uj.unwrap_or(self.estimated_uj)
    }
    pub fn check_provenance(&self) -> Result<(), SchemaError> {
        match (self.provenance, self.measured_uj) {
            (Provenance::HwShunt, None) => Err(SchemaError::DisallowedType("HwShunt without measured")),
            (Provenance::Estimator, Some(_)) => Err(SchemaError::DisallowedType("Estimator with measured")),
            _ => Ok(()),
        }
    }
}

/// What a grant permits: a set of actions over one content-addressed resource
/// (SPEC §4). The resource is addressed by content, not by URL — audience
/// binding an attacker cannot spoof by name.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Capability {
    pub resource: ContentId,
    pub actions: Vec<String>,
}

impl Capability {
    pub fn new(resource: ContentId, actions: impl IntoIterator<Item = impl Into<String>>) -> Self {
        Capability { resource, actions: actions.into_iter().map(Into::into).collect() }
    }
    /// Whether this capability permits `action` on `resource`.
    pub fn permits(&self, resource: &ContentId, action: &str) -> bool {
        &self.resource == resource && self.actions.iter().any(|a| a == action)
    }
    /// Whether `self` is no broader than `other` — every action ⊆, same resource.
    /// The basis of attenuation (a child grant may only narrow).
    pub fn is_subset_of(&self, other: &Capability) -> bool {
        self.resource == other.resource && self.actions.iter().all(|a| other.actions.contains(a))
    }
}

/// Delegation control (SPEC §4.4): how many further attenuation hops a grant
/// permits below itself. `None` = unlimited (the v0.1 behavior); `Some(0)` =
/// leaf-only, the holder may act but never re-delegate. Like every other
/// attenuation axis, the depth can only narrow: a child's allowance is at most
/// the parent's minus one.
pub fn depth_allows_delegation(depth: Option<u64>) -> bool {
    depth != Some(0)
}

/// The child allowance implied by a parent's `delegate_depth`.
pub fn child_depth_bound(parent: Option<u64>) -> Option<u64> {
    parent.map(|d| d.saturating_sub(1))
}

/// A **money ceiling** — an amount in a currency's minor units (integer cents,
/// never a float: the canonical encoding forbids floats, and money is typed).
///
/// This is the second, independent dimension of a dual-ceiling grant. It is
/// deliberately *not* convertible to joules: JCP invents no exchange rate. A
/// grant carrying both ceilings enforces each on its own terms and denies on
/// whichever binds first — so a receipt can say "denied: joule ceiling, while
/// the money ceiling had room", which is a statement no single-dimension
/// authorization can make.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Funds {
    /// The currency code the ceiling is denominated in (e.g. `USD`). Compared
    /// case-insensitively; a cost in a different currency is never debited
    /// against this ceiling.
    pub currency: String,
    /// The ceiling, in the currency's minor units (e.g. cents).
    pub minor: u64,
}

impl Funds {
    pub fn new(currency: impl Into<String>, minor: u64) -> Self {
        Funds { currency: currency.into(), minor }
    }
    /// Whether two ceilings/costs are denominated in the same currency.
    pub fn same_currency(&self, other: &str) -> bool {
        self.currency.eq_ignore_ascii_case(other)
    }
}

/// A **caveat** — an extra condition carried *inside* the grant that MUST hold
/// for a decision to be allowed (SPEC §4.9).
///
/// Attenuation's fixed axes (capability, budgets, expiry, depth) narrow by
/// set-subtraction: they can only remove actions or lower ceilings. A caveat is
/// the open axis — a delegator embeds an arbitrary condition the delegate cannot
/// remove, and **any** verifier holding the signed grant can check it offline,
/// with no call back to the issuer and no service-side policy to consult.
///
/// Every variant predicates only over what an enforcement point actually holds
/// when it decides: the frame, the caller, the clock, and the metered cost.
/// Notably there is **no content predicate** — the runtime sees a frame's
/// `payload_hash`, never its bytes — so a content condition is expressible only
/// as [`Caveat::PayloadIs`], binding an exact payload rather than inspecting it.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Caveat {
    /// The action must be one of these — narrower than the capability's set.
    ActionIn(Vec<String>),
    /// The frame's payload must be exactly this content id: a **one-shot**
    /// binding. The grant authorizes this specific call and nothing else, so a
    /// leaked grant cannot be replayed against different arguments.
    PayloadIs(ContentId),
    /// The caller must be this principal.
    CallerIs(Did),
    /// Not valid before this unix second.
    NotBefore(u64),
    /// Not valid after this unix second — a window narrower than `expiry`.
    NotAfter(u64),
    /// A ceiling on **one invocation's** cost, in µJ. Distinct from the grant's
    /// `budget_uj`, which is cumulative: this bounds any single call, so a
    /// delegate cannot spend the whole remaining budget in one shot.
    MaxCostUj(u64),
    /// The frame must name the model its action runs ([`Frame::model`]), and
    /// that model must be one of these content addresses: **which** model a
    /// grant authorizes, where the capability's `resource` names only the
    /// endpoint that runs it. It fails closed: a frame naming no model does
    /// not satisfy it, so a dispatcher that does not say what it will run
    /// cannot exercise the grant. This is authorization by content address,
    /// not a registry (SPEC §12): the grant names the bytes it permits.
    ModelIn(Vec<ContentId>),
    /// A **flow ceiling** (SPEC §4.10): the greatest-tainted provenance label
    /// whose values may exercise this grant. Unlike the other caveats, this one
    /// cannot be decided from the frame alone — it needs the argument's propagated
    /// label, which the runtime supplies as flow facts. So [`holds`](Self::holds)
    /// always returns `true` for it (it never blocks the caveat path); the real
    /// test is the runtime's flow gate, which reads this ceiling.
    FlowBelow(flow::FlowCeiling),
    /// A **sliding-window limit** (SPEC §4.12): over any `secs` seconds, the
    /// calls admitted under this grant, the distinct payloads they carry, or
    /// the joules metered for them stay within the limit. The budget bounds a
    /// grant's whole life; this bounds its rate. Like
    /// [`FlowBelow`](Self::FlowBelow), it cannot be decided from one frame. It
    /// needs the grant's recent history, which the runtime keeps, so
    /// [`holds`](Self::holds) refuses only a window of zero seconds, which
    /// would bound nothing.
    WithinWindow(Window),
}

/// A sliding window over a grant's recent use (SPEC §4.12).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Window {
    /// The window's length in seconds. A call admitted at `t` is inside the
    /// window decided at `now` while `now - t < secs`.
    pub secs: u64,
    /// What the window bounds.
    pub limit: WindowLimit,
}

/// What a [`Window`] bounds.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum WindowLimit {
    /// The joules metered for the calls inside the window, in µJ.
    MaxUj(u64),
    /// The calls admitted inside the window.
    MaxCalls(u64),
    /// The distinct payloads, by `payload_hash`, among the calls inside the
    /// window: how many different things the grant may be used on, not how
    /// often.
    MaxDistinctPayloads(u64),
}

impl Caveat {
    /// Whether this caveat can only be evaluated once the invocation's cost is
    /// known. Such a caveat is unevaluable in the two-phase metered path at
    /// authorize time and binds at the debit point instead (SPEC §4.9).
    pub fn is_cost_dependent(&self) -> bool {
        matches!(self, Caveat::MaxCostUj(_))
    }

    /// The per-invocation joule ceiling this caveat states, where it states
    /// one.
    ///
    /// Read in the two-phase path to size a hold: the cost is unknown at
    /// authorization, but a ceiling the grant states in advance is an upper
    /// bound the work is not permitted to exceed, so a hold may reserve that
    /// rather than the grant's whole remainder.
    pub fn max_cost_uj(&self) -> Option<u64> {
        match self {
            Caveat::MaxCostUj(max) => Some(*max),
            _ => None,
        }
    }

    /// Whether a cost-dependent caveat is breached by a measured cost. Needs no
    /// frame or clock, so it is checkable at the debit point.
    pub fn cost_breached(&self, cost_uj: u64) -> bool {
        match self {
            Caveat::MaxCostUj(max) => cost_uj > *max,
            _ => false,
        }
    }

    /// Whether this caveat holds. `cost_uj` is the metered cost of the
    /// invocation being decided; `now` the enforcement point's clock.
    pub fn holds(&self, frame: &Frame, caller: Did, cost_uj: u64, now: u64) -> bool {
        match self {
            Caveat::ActionIn(set) => set.iter().any(|a| a == &frame.action),
            Caveat::PayloadIs(id) => *id == frame.payload_hash,
            Caveat::CallerIs(did) => *did == caller,
            Caveat::NotBefore(t) => now >= *t,
            Caveat::NotAfter(t) => now <= *t,
            Caveat::MaxCostUj(max) => cost_uj <= *max,
            Caveat::ModelIn(set) => frame.model.as_ref().is_some_and(|m| set.contains(m)),
            // Flow is decided by the runtime gate against the argument's label,
            // not from the frame — so as a caveat it never blocks.
            Caveat::FlowBelow(_) => true,
            // A window is decided by the runtime gate against the grant's
            // history (§4.12). A zero-length window would bound nothing.
            Caveat::WithinWindow(w) => w.secs > 0,
        }
    }

    /// The window this caveat carries, if it is a [`Caveat::WithinWindow`].
    pub fn window(&self) -> Option<&Window> {
        match self {
            Caveat::WithinWindow(w) => Some(w),
            _ => None,
        }
    }

    /// The flow ceiling this caveat carries, if it is a [`Caveat::FlowBelow`].
    pub fn flow_ceiling(&self) -> Option<&flow::FlowCeiling> {
        match self {
            Caveat::FlowBelow(ceiling) => Some(ceiling),
            _ => None,
        }
    }
}

/// The **metered capability** (SPEC §4) — JCP's central object. A signed,
/// content-addressed token binding a `subject` to a `capability` *and* a joule
/// `budget`. A `parent` links it into an attenuation chain (object-capability
/// delegation: a child may only be weaker). Content-addressed by all fields.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Grant {
    pub issuer: Did,
    pub subject: Did,
    pub capability: Capability,
    /// The joule ceiling this grant may ever spend.
    pub budget_uj: u64,
    /// An **optional second ceiling, denominated in money** (SPEC §4.8).
    ///
    /// Absent = this grant is bounded by joules alone, and it serializes
    /// byte-identically to a grant minted before dual ceilings existed — so its
    /// content id, its signature, and every published conformance vector are
    /// unchanged. Present = both ceilings are enforced independently and the
    /// first to bind denies.
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub budget_funds: Option<Funds>,
    /// Conditions carried **inside** the grant that MUST all hold (SPEC §4.9).
    ///
    /// Empty = no caveats, and the field is omitted from the canonical encoding
    /// entirely — so a grant without caveats is byte-identical to one minted
    /// before they existed, and its content id and signature are unchanged.
    /// Attenuation may only **add** caveats: a child carries every one of its
    /// parent's, so authority narrows monotonically down a chain.
    #[serde(skip_serializing_if = "Vec::is_empty", default)]
    pub caveats: Vec<Caveat>,
    /// Unix seconds after which the grant is invalid; `0` means no expiry.
    pub expiry: u64,
    /// The parent grant this was attenuated from, if any.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent: Option<ContentId>,
    /// Delegation control (SPEC §4.4): how many further attenuation hops this
    /// grant permits. Absent = unlimited; `0` = leaf-only (the holder may act
    /// but never re-delegate). Narrows by at least one per hop.
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub delegate_depth: Option<u64>,
    pub nonce: [u8; 16],
}

impl Grant {
    /// The grant's content id — its stable identity and the audience a receipt
    /// and a frame reference.
    pub fn id(&self) -> ContentId {
        ContentId::of(self).expect("grant fields are canonical (no float/bool/null)")
    }
    pub fn is_expired(&self, now: u64) -> bool {
        self.expiry != 0 && now > self.expiry
    }
}

/// A grant plus the issuer's Ed25519 signature over its canonical bytes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedGrant {
    pub grant: Grant,
    /// Ed25519 signature (64 bytes) over `canonical_cbor(grant)`.
    pub signature: Vec<u8>,
}

/// A revocation of a previously issued grant (SPEC §4.1). Only the grant's
/// issuer may revoke it. Revoking a grant kills every grant attenuated from it,
/// transitively — a delegation subtree dies with any of its ancestors.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Revocation {
    /// The content id of the grant being revoked.
    pub grant_id: ContentId,
    /// The revoking actor. MUST equal the revoked grant's `issuer`.
    pub revoked_by: Did,
    pub nonce: [u8; 16],
}

/// A revocation plus the revoker's Ed25519 signature over its canonical bytes.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedRevocation {
    pub revocation: Revocation,
    /// Ed25519 signature (64 bytes) over `canonical_cbor(revocation)`.
    pub signature: Vec<u8>,
}

/// One event in an identity's key-rotation log (SPEC §2.1) — pre-committed
/// rotation in the KERI style.
///
/// An identity is its **inception DID** (seq 0), permanently. Each event names
/// the key that is `current` from this event on, and **pre-commits** to the
/// blake3 hash of the *next* key's public bytes. Rotation event N must be
/// signed by event N−1's `current` key AND its new `current` key must hash to
/// event N−1's `next_hash` — so a thief who steals the current key still cannot
/// rotate the identity away: they don't hold the pre-committed next key.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct KeyEvent {
    /// The identity being rotated — its seq-0 (inception) DID, forever.
    pub identity: Did,
    /// 0 = inception; N = the Nth rotation.
    pub seq: u64,
    /// The key that is current from this event on. At seq 0 this MUST equal
    /// `identity`.
    pub current: Did,
    /// blake3 of the next key's 32 public bytes — the pre-commitment.
    pub next_hash: ContentId,
    /// The id of the previous event; absent at inception.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub parent: Option<ContentId>,
    pub nonce: [u8; 16],
}

impl KeyEvent {
    pub fn id(&self) -> ContentId {
        ContentId::of(self).expect("key-event fields are canonical")
    }
}

/// A key event plus its authorizing signature: the inception key's at seq 0,
/// the *previous* current key's at every rotation.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SignedKeyEvent {
    pub event: KeyEvent,
    /// Ed25519 signature (64 bytes) over `canonical_cbor(event)`.
    pub signature: Vec<u8>,
}

/// Whether a frame's payload is principal **control** or untrusted **data**
/// (SPEC §6). Tool and agent *outputs* are always `Data`: they can never be
/// executed as instructions or used to request a capability. This closes the
/// asymmetric-trust gap that tool poisoning exploits.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Trust {
    Control,
    Data,
}

/// What kind of message a frame is (SPEC §6) — one envelope spans the tool layer
/// (MCP's job) and the agent layer (A2A's job).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum FrameKind {
    ToolCall,
    ToolResult,
    AgentTask,
    AgentReply,
}

/// A JCP message (SPEC §6): a typed action exercising a grant, with its trust
/// tag and a content-addressed payload.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Frame {
    pub kind: FrameKind,
    pub trust: Trust,
    pub grant_id: ContentId,
    pub action: String,
    pub resource: ContentId,
    pub payload_hash: ContentId,
    /// The content address of the model this frame's action runs, named by
    /// the runtime that dispatches it, which knows what it will load. Checked
    /// by [`Caveat::ModelIn`]. Absent for an action that runs no model, and
    /// then omitted from the encoding, so a frame without one is
    /// byte-identical to one built before the field existed, as is every
    /// receipt and vector over it.
    #[serde(skip_serializing_if = "Option::is_none", default)]
    pub model: Option<ContentId>,
}

/// Why the runtime denied an action (SPEC §7). A deterministic, enumerable set —
/// every denial names exactly one reason.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum DenyReason {
    BadSignature,
    WrongSubject,
    WrongResource,
    ActionNotGranted,
    Expired,
    BudgetExceeded,
    /// The action's money cost exceeds the grant's **money** ceiling — the
    /// second dimension of a dual-ceiling grant (SPEC §4.8). Distinct from
    /// `BudgetExceeded` (joules) on purpose: which ceiling bound is exactly
    /// the fact the receipt exists to record.
    FundsExceeded,
    /// A caveat carried inside the grant did not hold (SPEC §4.9) — the open
    /// attenuation axis. The label names which kind failed.
    CaveatUnsatisfied,
    /// A cost was presented in a currency the grant's money ceiling is not
    /// denominated in. JCP invents no exchange rate, so this is a denial rather
    /// than a conversion.
    CurrencyMismatch,
    /// A `Data`-tagged frame tried to exercise a capability — control from
    /// untrusted output is refused (anti-tool-poisoning).
    UntrustedControl,
    /// A delegated grant tried to exceed its parent.
    AttenuationViolation,
    /// The grant — or any ancestor in its delegation chain — has been revoked.
    Revoked,
    /// A presented delegation chain is structurally invalid: a missing or
    /// mismatched parent link, a hop issued by someone other than the previous
    /// holder, or a bad signature anywhere along it.
    ChainBroken,
    /// The chain's root issuer is not a configured trust root for the frame's
    /// resource (SPEC §7) — the enforcement point honors only the root keys it
    /// was configured with, `authorized_keys`-style.
    UntrustedRoot,
    /// The argument's propagated provenance label does not sit at or below the
    /// grant's flow ceiling, or the resource's taint floor refuses its origins
    /// (SPEC §4.10). The one denial that is about *where a value came from* rather
    /// than what it is.
    TaintedFlow,
    /// A tainted call would exceed the grant's smaller, once-tainted joule budget
    /// (SPEC §4.10) — a tighter wallet for work that has touched an untrusted
    /// source, distinct from the cumulative `BudgetExceeded`.
    TaintBudgetExceeded,
    /// A wire request stamped with a `now` outside the enforcement point's
    /// freshness window (SPEC §11). The point decides at its own clock, and a
    /// request signed for another time is not decided.
    StaleRequest,
    /// A wire request the enforcement point has already decided, presented
    /// again. The reference endpoint no longer refuses one. A request is still
    /// decided and debited once, but a repeat now gets its first answer,
    /// unchanged, so that a caller whose response was lost can recover it
    /// (SPEC §11). The reason is kept so that receipts sealed with it, and
    /// endpoints that still refuse, keep decoding.
    Replayed,
    /// The enforcement point could not record the request before deciding it
    /// (SPEC §4.11), so it does not decide it: a decision it could not record
    /// would be lost, with its debit, on a restart.
    Unrecorded,
    /// A sliding-window caveat (SPEC §4.12) would be exceeded: too many calls,
    /// distinct payloads or joules inside the window. A window whose history
    /// the enforcement point cannot vouch for counts as full.
    WindowExceeded,
    /// A settle or a cancel named a hold that is not outstanding (SPEC §8.1):
    /// it was already resolved, or never placed. A hold resolves **once**, so a
    /// second resolution is refused rather than debiting the same work twice,
    /// and a completion that crosses a cancellation loses the race
    /// deterministically.
    AlreadyResolved,
}

impl DenyReason {
    pub fn label(self) -> &'static str {
        match self {
            DenyReason::BadSignature => "bad-signature",
            DenyReason::WrongSubject => "wrong-subject",
            DenyReason::WrongResource => "wrong-resource",
            DenyReason::ActionNotGranted => "action-not-granted",
            DenyReason::Expired => "expired",
            DenyReason::BudgetExceeded => "budget-exceeded",
            DenyReason::FundsExceeded => "funds-exceeded",
            DenyReason::CurrencyMismatch => "currency-mismatch",
            DenyReason::CaveatUnsatisfied => "caveat-unsatisfied",
            DenyReason::UntrustedControl => "untrusted-control",
            DenyReason::AttenuationViolation => "attenuation-violation",
            DenyReason::Revoked => "revoked",
            DenyReason::ChainBroken => "chain-broken",
            DenyReason::UntrustedRoot => "untrusted-root",
            DenyReason::TaintedFlow => "tainted-flow",
            DenyReason::TaintBudgetExceeded => "taint-budget-exceeded",
            DenyReason::StaleRequest => "stale-request",
            DenyReason::Replayed => "replayed",
            DenyReason::Unrecorded => "unrecorded",
            DenyReason::WindowExceeded => "window-exceeded",
            DenyReason::AlreadyResolved => "already-resolved",
        }
    }
}

/// The runtime's deterministic verdict on a frame (SPEC §7).
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Verdict {
    Allow,
    Deny(DenyReason),
}

impl Verdict {
    pub fn is_allow(&self) -> bool {
        matches!(self, Verdict::Allow)
    }
    pub fn wire_tag(&self) -> &'static str {
        match self {
            Verdict::Allow => "allow",
            Verdict::Deny(_) => "deny",
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ed25519_dalek::SigningKey;

    fn did(seed: u8) -> Did {
        Did::from_verifying_key(&SigningKey::from_bytes(&[seed; 32]).verifying_key())
    }

    /// A frame that names no model encodes exactly as one built before the
    /// field existed, so its hash and every receipt over it are unchanged; a
    /// frame that names one encodes differently. `ModelIn` holds only for a
    /// frame naming a model in its set.
    #[test]
    fn a_frame_without_a_model_keeps_its_bytes() {
        #[derive(Serialize)]
        struct Before {
            kind: FrameKind,
            trust: Trust,
            grant_id: ContentId,
            action: String,
            resource: ContentId,
            payload_hash: ContentId,
        }
        let (g, r, p) = (ContentId::of_bytes(b"g"), ContentId::of_bytes(b"r"), ContentId::of_bytes(b"p"));
        let f = Frame { kind: FrameKind::ToolCall, trust: Trust::Control, grant_id: g, action: "read".into(), resource: r, payload_hash: p, model: None };
        let before = Before { kind: FrameKind::ToolCall, trust: Trust::Control, grant_id: g, action: "read".into(), resource: r, payload_hash: p };
        assert_eq!(crate::cbor::canonical_cbor(&f).unwrap(), crate::cbor::canonical_cbor(&before).unwrap());

        let m = ContentId::of_bytes(b"model weights");
        let named = Frame { model: Some(m), ..f.clone() };
        assert_ne!(crate::cbor::canonical_cbor(&named).unwrap(), crate::cbor::canonical_cbor(&f).unwrap());
        let c = Caveat::ModelIn(vec![m]);
        assert!(c.holds(&named, did(1), 0, 0));
        assert!(!c.holds(&f, did(1), 0, 0), "a frame naming no model fails closed");
        assert!(!c.holds(&Frame { model: Some(ContentId::of_bytes(b"other")), ..f }, did(1), 0, 0));
    }

    #[test]
    fn did_key_roundtrips() {
        let d = did(7);
        let s = d.to_did_key();
        assert!(s.starts_with("did:key:z"));
        assert_eq!(Did::parse(&s).unwrap(), d);
        // and through serde (which uses the string form)
        let j = serde_json::to_string(&d).unwrap();
        assert_eq!(j, format!("\"{s}\""));
        assert_eq!(serde_json::from_str::<Did>(&j).unwrap(), d);
    }

    #[test]
    fn grant_id_is_stable_and_capability_sensitive() {
        let g = Grant {
            issuer: did(1),
            subject: did(2),
            capability: Capability::new(ContentId::of_bytes(b"db"), ["read"]),
            budget_uj: 1000,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        };
        let mut g2 = g.clone();
        assert_eq!(g.id(), g2.id());
        g2.budget_uj = 999;
        assert_ne!(g.id(), g2.id()); // budget is part of identity
    }

    #[test]
    fn capability_permits_and_subset() {
        let r = ContentId::of_bytes(b"db");
        let read = Capability::new(r, ["read"]);
        let rw = Capability::new(r, ["read", "write"]);
        assert!(read.permits(&r, "read"));
        assert!(!read.permits(&r, "write"));
        assert!(!read.permits(&ContentId::of_bytes(b"other"), "read")); // audience binding
        assert!(read.is_subset_of(&rw));
        assert!(!rw.is_subset_of(&read)); // write is not in read
    }

    #[test]
    fn provenance_coupling() {
        assert!(Energy::modeled(10).check_provenance().is_ok());
        assert!(Energy::measured(10).check_provenance().is_ok());
        assert!(Energy::estimator(10).check_provenance().is_ok());
        let bad = Energy {
            measured_uj: None,
            estimated_uj: 1,
            provenance: Provenance::HwShunt,
            coverage: Coverage::Whole,
        };
        assert!(bad.check_provenance().is_err());
    }

    /// Provenance and coverage answer different questions, and a figure that
    /// conflates them overstates itself.
    #[test]
    fn coverage_is_separate_from_provenance() {
        // The flattering case the constructor made easy: a hardware reading
        // that silently claims the whole task.
        let whole = Energy::measured(10);
        assert_eq!(whole.provenance, Provenance::HwShunt);
        assert!(whole.is_whole());

        // The honest case, now equally easy to express. Same provenance — the
        // counter is just as real — but it accounts for part of the work.
        let part = Energy::measured_partial(10);
        assert_eq!(part.provenance, Provenance::HwShunt, "a partial reading is still a sensor reading");
        assert!(!part.is_whole());
        assert_eq!(part.coverage, Coverage::Partial);

        // Partial is orthogonal to the provenance coupling, so it must not
        // disturb it.
        part.check_provenance().expect("HwShunt + measured is still coherent");
    }

    /// Absence is the default and is omitted from the wire, so every receipt
    /// and vector sealed before this field existed is unchanged.
    #[test]
    fn whole_coverage_is_omitted_from_the_wire() {
        let whole = serde_json::to_string(&Energy::measured(10)).unwrap();
        assert!(!whole.contains("coverage"), "default coverage must not appear: {whole}");

        let part = serde_json::to_string(&Energy::measured_partial(10)).unwrap();
        assert!(part.contains("Partial"), "a partial figure must say so: {part}");

        // And a payload written before the field existed still parses, as Whole.
        let legacy: Energy =
            serde_json::from_str(r#"{"measured_uj":10,"estimated_uj":10,"provenance":"HwShunt"}"#)
                .expect("legacy payload must still parse");
        assert!(legacy.is_whole());
        assert_eq!(legacy, Energy::measured(10));
    }

    fn grant_without_funds() -> Grant {
        let r = ContentId::of_bytes(b"db");
        Grant {
            issuer: Did::from_verifying_key(&ed25519_dalek::SigningKey::from_bytes(&[1; 32]).verifying_key()),
            subject: Did::from_verifying_key(&ed25519_dalek::SigningKey::from_bytes(&[2; 32]).verifying_key()),
            capability: Capability::new(r, ["read"]),
            budget_uj: 100,
            budget_funds: None,
            caveats: Vec::new(),
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0; 16],
        }
    }

    /// THE backward-compatibility guarantee the dual-ceiling design rests on:
    /// a grant with no money ceiling must encode to the exact bytes it did
    /// before the field existed, so its content id — and therefore every
    /// signature and every published conformance vector — is unchanged.
    #[test]
    fn absent_money_ceiling_does_not_change_the_encoding() {
        let g = grant_without_funds();
        let bytes = crate::cbor::canonical_cbor(&g).expect("canonical");
        // The field must be entirely absent from the encoding, not present-as-empty.
        let hay = String::from_utf8_lossy(&bytes);
        assert!(!hay.contains("budget_funds"), "absent ceiling must not appear in the encoding");
        // And the id is a pure function of those bytes.
        assert_eq!(g.id(), ContentId::of(&g).unwrap());
    }

    /// Adding the ceiling MUST change identity — otherwise two grants with
    /// different authority would share a content id.
    #[test]
    fn present_money_ceiling_changes_identity() {
        let plain = grant_without_funds();
        let mut priced = grant_without_funds();
        priced.budget_funds = Some(Funds::new("USD", 500));
        assert_ne!(plain.id(), priced.id());
        let bytes = crate::cbor::canonical_cbor(&priced).expect("canonical");
        assert!(String::from_utf8_lossy(&bytes).contains("budget_funds"));
    }

    #[test]
    fn absent_flow_ceiling_does_not_change_the_encoding() {
        // A grant with no FlowBelow caveat is byte-identical to one minted before
        // the flow feature existed: adding a variant to an externally-tagged enum
        // changes the encoding of no value that omits it.
        let g = grant_without_funds();
        let bytes = crate::cbor::canonical_cbor(&g).expect("canonical");
        assert!(!String::from_utf8_lossy(&bytes).contains("FlowBelow"));
        assert!(!String::from_utf8_lossy(&bytes).contains("caveats"), "no caveats ⇒ field omitted");
        assert_eq!(g.id(), ContentId::of(&g).unwrap());
    }

    #[test]
    fn a_flow_caveat_changes_identity_and_carries_its_ceiling() {
        use crate::flow::{FlowCeiling, Label};
        let plain = grant_without_funds();
        let mut ceilinged = grant_without_funds();
        ceilinged.caveats = vec![Caveat::FlowBelow(FlowCeiling::new(Label::bottom()))];
        assert_ne!(plain.id(), ceilinged.id(), "a flow ceiling is part of authority");
        // The ceiling round-trips through canonical CBOR.
        let bytes = crate::cbor::canonical_cbor(&ceilinged).expect("canonical");
        let back: Grant = crate::cbor::from_canonical_cbor(&bytes).expect("decode");
        assert_eq!(back.caveats[0].flow_ceiling(), Some(&FlowCeiling::new(Label::bottom())));
    }

    #[test]
    fn funds_currency_compare_is_case_insensitive() {
        let f = Funds::new("USD", 500);
        assert!(f.same_currency("usd"));
        assert!(f.same_currency("USD"));
        assert!(!f.same_currency("EUR"));
    }
}
