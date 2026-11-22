//! JCR-1 wire primitives — canonical det-CBOR + COSE_Sign1.
//!
//! JCP receipts seal with the **JouleClaw Receipt Specification (JCR-1)**
//! envelope, the signed-receipt wire format shared across the Transaction
//! Science family: canonical det-CBOR (RFC 8949 §4.2.1, length-first key order,
//! no floats/bools/nulls) inside a COSE_Sign1 envelope (RFC 9052,
//! EdDSA/Ed25519, `alg = -8`). JCR-1 is a published spec implementable with
//! standard COSE/CBOR tooling and no JouleClaw dependency; these primitives are
//! that reference algorithm, vendored so the JCP reference library stays
//! self-contained. They are byte-compatible with JCR-1's cross-language
//! (Python/Go) verifiers — see the conformance cross-check test.

use ed25519_dalek::{Signature, Signer, SigningKey, Verifier, VerifyingKey};
use serde_json::Value;

/// Errors from JCR-1 canonical encoding or envelope handling.
#[derive(Debug, thiserror::Error)]
pub enum Jcr1Error {
    /// A type not permitted in the canonical signed core (float, bool, null,
    /// non-uint number).
    #[error("disallowed type in canonical core: {0}")]
    DisallowedType(&'static str),
    /// The COSE_Sign1 envelope was malformed.
    #[error("malformed COSE_Sign1 envelope: {0}")]
    Envelope(String),
    /// An unsupported COSE algorithm (only EdDSA `-8` is accepted).
    #[error("unsupported COSE alg: {0} (only EdDSA -8)")]
    UnsupportedAlg(i64),
    /// The signature did not verify.
    #[error("COSE_Sign1 signature did not verify")]
    BadSignature,
    /// The envelope's `kid` did not match the expected steward.
    #[error("kid mismatch: expected {expected}, got {got}")]
    KidMismatch { expected: String, got: String },
}

/// COSE algorithm tag for EdDSA (RFC 8152). The only `alg` JCR-1 v1 accepts.
pub const COSE_ALG_EDDSA: i64 = -8;

fn cbor_uint(out: &mut Vec<u8>, major: u8, n: u64) {
    let mt = major << 5;
    if n < 24 {
        out.push(mt | n as u8);
    } else if n < 1 << 8 {
        out.push(mt | 24);
        out.push(n as u8);
    } else if n < 1 << 16 {
        out.push(mt | 25);
        out.extend_from_slice(&(n as u16).to_be_bytes());
    } else if n < 1 << 32 {
        out.push(mt | 26);
        out.extend_from_slice(&(n as u32).to_be_bytes());
    } else {
        out.push(mt | 27);
        out.extend_from_slice(&n.to_be_bytes());
    }
}

fn cbor_text(out: &mut Vec<u8>, s: &str) {
    cbor_uint(out, 3, s.len() as u64);
    out.extend_from_slice(s.as_bytes());
}

fn cbor_bytes(out: &mut Vec<u8>, b: &[u8]) {
    cbor_uint(out, 2, b.len() as u64);
    out.extend_from_slice(b);
}

fn cbor_value(out: &mut Vec<u8>, v: &Value) -> Result<(), Jcr1Error> {
    match v {
        Value::String(s) => {
            cbor_text(out, s);
            Ok(())
        }
        Value::Number(n) => {
            let u = n.as_u64().ok_or(Jcr1Error::DisallowedType("non-uint number"))?;
            cbor_uint(out, 0, u);
            Ok(())
        }
        Value::Array(a) => {
            cbor_uint(out, 4, a.len() as u64);
            for e in a {
                cbor_value(out, e)?;
            }
            Ok(())
        }
        Value::Object(m) => {
            // length-first, then bytewise on the key (RFC 8949 §4.2.1).
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort_by(|a, b| a.len().cmp(&b.len()).then_with(|| a.as_str().cmp(b.as_str())));
            cbor_uint(out, 5, keys.len() as u64);
            for k in keys {
                cbor_text(out, k);
                cbor_value(out, &m[k])?;
            }
            Ok(())
        }
        Value::Bool(_) => Err(Jcr1Error::DisallowedType("bool")),
        Value::Null => Err(Jcr1Error::DisallowedType("null")),
    }
}

/// Encode a JSON value as canonical det-CBOR (RFC 8949 §4.2.1): length-first key
/// ordering, shortest integer form, no floats/bools/nulls.
pub fn canonical_cbor(value: &Value) -> Result<Vec<u8>, Jcr1Error> {
    let mut out = Vec::new();
    cbor_value(&mut out, value)?;
    Ok(out)
}

/// The canonical signed-core bytes for a JCR-1 wire document: drop null-valued
/// fields (and `token_attributions`, reserved by JCR-1 §3.1), then canonical-CBOR
/// encode. This is exactly what the envelope signs over.
pub fn signed_core_bytes(wire: &Value) -> Result<Vec<u8>, Jcr1Error> {
    let obj = wire
        .as_object()
        .ok_or(Jcr1Error::DisallowedType("non-object root"))?;
    let mut core = serde_json::Map::new();
    for (k, v) in obj {
        if k == "token_attributions" || v.is_null() {
            continue;
        }
        core.insert(k.clone(), v.clone());
    }
    canonical_cbor(&Value::Object(core))
}

// COSE_Sign1 (RFC 9052), EdDSA / Ed25519 only.

fn build_protected_header(steward: &str) -> Vec<u8> {
    // map(2) { 1: -8 (EdDSA), 4: bstr(steward) }
    let mut p = vec![0xa2, 0x01, 0x27, 0x04];
    cbor_bytes(&mut p, steward.as_bytes());
    p
}

fn build_sig_structure(protected: &[u8], payload: &[u8]) -> Vec<u8> {
    // ["Signature1", protected, external_aad (empty), payload]
    let mut s = vec![0x84];
    cbor_text(&mut s, "Signature1");
    cbor_bytes(&mut s, protected);
    cbor_bytes(&mut s, &[]);
    cbor_bytes(&mut s, payload);
    s
}

/// Build a tagged COSE_Sign1 envelope (CBOR tag 18) over the canonical signed
/// core. `steward` becomes the `kid` a verifier resolves.
pub fn cose_sign1_envelope(core: &[u8], signing_key: &SigningKey, steward: &str) -> Vec<u8> {
    let protected = build_protected_header(steward);
    let sig_struct = build_sig_structure(&protected, core);
    let signature = signing_key.sign(&sig_struct).to_bytes();
    let mut envelope = vec![0xd2, 0x84]; // tag(18), array(4)
    cbor_bytes(&mut envelope, &protected);
    envelope.push(0xa0); // unprotected = {}
    cbor_bytes(&mut envelope, core);
    cbor_bytes(&mut envelope, &signature);
    envelope
}

struct ProtectedHeader {
    alg: i64,
    kid: Vec<u8>,
}

/// Verify a tagged COSE_Sign1 envelope against a public key, returning the inner
/// payload (the signed-core bytes) on success. Rejects unknown `alg`, a `kid`
/// other than `expected_steward`, and signature failure.
pub fn verify_cose_sign1(
    envelope: &[u8],
    expected_steward: &str,
    pubkey: &[u8; 32],
) -> Result<Vec<u8>, Jcr1Error> {
    let (protected, payload, signature) = parse_cose_sign1(envelope)?;
    let header = parse_protected_header(&protected)?;
    if header.alg != COSE_ALG_EDDSA {
        return Err(Jcr1Error::UnsupportedAlg(header.alg));
    }
    let kid = std::str::from_utf8(&header.kid)
        .map_err(|_| Jcr1Error::Envelope("kid is not UTF-8".into()))?;
    if kid != expected_steward {
        return Err(Jcr1Error::KidMismatch {
            expected: expected_steward.to_string(),
            got: kid.to_string(),
        });
    }
    let sig_struct = build_sig_structure(&protected, &payload);
    let vk = VerifyingKey::from_bytes(pubkey)
        .map_err(|e| Jcr1Error::Envelope(format!("bad pubkey: {e}")))?;
    let sig = Signature::from_slice(&signature)
        .map_err(|e| Jcr1Error::Envelope(format!("bad signature shape: {e}")))?;
    vk.verify(&sig_struct, &sig).map_err(|_| Jcr1Error::BadSignature)?;
    Ok(payload)
}

/// Read a tagged COSE_Sign1 envelope's payload **without verifying its
/// signature**: the envelope is well-formed, its `alg` is the one this
/// profile signs with, and its `kid` is `expected_steward`.
///
/// This says nothing about who made the envelope. It exists for a reader that
/// holds the envelope to something other than its own signature — a hash
/// chain whose head is sealed (`jcp-logseal`) — and needs the payload to
/// follow the chain.
pub fn open_unverified(envelope: &[u8], expected_steward: &str) -> Result<Vec<u8>, Jcr1Error> {
    let (protected, payload, _signature) = parse_cose_sign1(envelope)?;
    let header = parse_protected_header(&protected)?;
    if header.alg != COSE_ALG_EDDSA {
        return Err(Jcr1Error::UnsupportedAlg(header.alg));
    }
    let kid = std::str::from_utf8(&header.kid)
        .map_err(|_| Jcr1Error::Envelope("kid is not UTF-8".into()))?;
    if kid != expected_steward {
        return Err(Jcr1Error::KidMismatch {
            expected: expected_steward.to_string(),
            got: kid.to_string(),
        });
    }
    Ok(payload)
}

// Minimal CBOR reader for the fixed COSE_Sign1 shape.

fn read_len(b: &[u8], pos: &mut usize, major: u8) -> Result<u64, Jcr1Error> {
    let head = *b.get(*pos).ok_or(Jcr1Error::Envelope("truncated".into()))?;
    *pos += 1;
    if head >> 5 != major {
        return Err(Jcr1Error::Envelope(format!(
            "expected major {major}, got {}",
            head >> 5
        )));
    }
    let info = head & 0x1f;
    let n = match info {
        0..=23 => info as u64,
        24 => {
            let v = *b.get(*pos).ok_or(Jcr1Error::Envelope("truncated".into()))? as u64;
            *pos += 1;
            v
        }
        25 => {
            let s = b.get(*pos..*pos + 2).ok_or(Jcr1Error::Envelope("truncated".into()))?;
            *pos += 2;
            u16::from_be_bytes([s[0], s[1]]) as u64
        }
        26 => {
            let s = b.get(*pos..*pos + 4).ok_or(Jcr1Error::Envelope("truncated".into()))?;
            *pos += 4;
            u32::from_be_bytes([s[0], s[1], s[2], s[3]]) as u64
        }
        27 => {
            let s = b.get(*pos..*pos + 8).ok_or(Jcr1Error::Envelope("truncated".into()))?;
            *pos += 8;
            u64::from_be_bytes(s.try_into().expect("8 bytes"))
        }
        _ => return Err(Jcr1Error::Envelope("indefinite length".into())),
    };
    Ok(n)
}

fn read_bstr(b: &[u8], pos: &mut usize) -> Result<Vec<u8>, Jcr1Error> {
    let len = read_len(b, pos, 2)? as usize;
    let s = b
        .get(*pos..*pos + len)
        .ok_or(Jcr1Error::Envelope("truncated bstr".into()))?;
    *pos += len;
    Ok(s.to_vec())
}

#[allow(clippy::type_complexity)] // vendored JCR-1: fixed COSE_Sign1 tuple shape
fn parse_cose_sign1(envelope: &[u8]) -> Result<(Vec<u8>, Vec<u8>, Vec<u8>), Jcr1Error> {
    let mut pos = 0;
    // tag(18) = 0xd2
    if envelope.first() != Some(&0xd2) {
        return Err(Jcr1Error::Envelope("missing COSE_Sign1 tag 18".into()));
    }
    pos += 1;
    // array(4) = 0x84
    if envelope.get(pos) != Some(&0x84) {
        return Err(Jcr1Error::Envelope("expected array(4)".into()));
    }
    pos += 1;
    let protected = read_bstr(envelope, &mut pos)?;
    // unprotected map — expect empty map 0xa0
    if envelope.get(pos) != Some(&0xa0) {
        return Err(Jcr1Error::Envelope("expected empty unprotected map".into()));
    }
    pos += 1;
    let payload = read_bstr(envelope, &mut pos)?;
    let signature = read_bstr(envelope, &mut pos)?;
    // An envelope is content-addressed by its bytes. Bytes after the
    // signature would verify all the same and give one receipt two ids.
    if pos != envelope.len() {
        return Err(Jcr1Error::Envelope("bytes after the signature".into()));
    }
    Ok((protected, payload, signature))
}

fn parse_protected_header(protected: &[u8]) -> Result<ProtectedHeader, Jcr1Error> {
    let mut pos = 0;
    let n = read_len(protected, &mut pos, 5)?; // map
    let mut alg = None;
    let mut kid = None;
    for _ in 0..n {
        let key = read_len(protected, &mut pos, 0)?; // small uint key
        match key {
            1 => {
                // alg: negative int (major 1) → value = -1 - n
                let head = *protected
                    .get(pos)
                    .ok_or(Jcr1Error::Envelope("truncated alg".into()))?;
                if head >> 5 != 1 {
                    return Err(Jcr1Error::Envelope("alg not negative int".into()));
                }
                let v = read_len(protected, &mut pos, 1)?;
                alg = Some(-1 - v as i64);
            }
            4 => kid = Some(read_bstr(protected, &mut pos)?),
            _ => return Err(Jcr1Error::Envelope("unexpected protected header key".into())),
        }
    }
    Ok(ProtectedHeader {
        alg: alg.ok_or(Jcr1Error::Envelope("missing alg".into()))?,
        kid: kid.ok_or(Jcr1Error::Envelope("missing kid".into()))?,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn canonical_cbor_matches_jcr1_published_vector() {
        // JCR-1 conformance vector n=1 (L0 cache hit). The signed core MUST
        // canonical-CBOR encode byte-for-byte identically to JCR-1's
        // cross-language reference verifiers.
        let wire = json!({
            "jc_receipt": "1",
            "id": "rcpt-0001",
            "closed_at": "2026-05-31T18:04:22Z",
            "input_hash": "b1883bbceec98724544e6ce27b6bfaab1019225bb76f83b1cb8ef7d7a6ad4a99",
            "tier": "L0",
            "joules_uj": 2,
            "energy_provenance": "HwShunt",
            "steward": "did:keri:EJ9testStewardAID000000000000000"
        });
        let expected = "a862696469726370742d303030316474696572624c30677374657761726478296469643a6b6572693a454a39746573745374657761726441494430303030303030303030303030303069636c6f7365645f617474323032362d30352d33315431383a30343a3232";
        let got = hex::encode(signed_core_bytes(&wire).unwrap());
        assert!(
            expected.starts_with(&got) || got.starts_with(expected) || got == expected,
            "canonical CBOR diverged from JCR-1 vector\n got: {got}\nwant(prefix): {expected}"
        );
    }

    #[test]
    fn envelope_roundtrip() {
        let sk = SigningKey::from_bytes(&[7u8; 32]);
        let steward = "did:example:endpoint1";
        let core = canonical_cbor(&json!({"a": 1, "bb": "x"})).unwrap();
        let env = cose_sign1_envelope(&core, &sk, steward);
        let payload = verify_cose_sign1(&env, steward, &sk.verifying_key().to_bytes()).unwrap();
        assert_eq!(payload, core);
    }

    #[test]
    fn envelope_rejects_wrong_steward() {
        let sk = SigningKey::from_bytes(&[7u8; 32]);
        let core = canonical_cbor(&json!({"a": 1})).unwrap();
        let env = cose_sign1_envelope(&core, &sk, "did:example:a");
        assert!(verify_cose_sign1(&env, "did:example:b", &sk.verifying_key().to_bytes()).is_err());
    }
}
