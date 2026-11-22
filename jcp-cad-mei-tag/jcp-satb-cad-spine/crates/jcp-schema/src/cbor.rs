//! Canonical det-CBOR (RFC 8949 §4.2.1) — length-first key order, shortest
//! integer form, no floats/bools/nulls. The content-addressing basis (SPEC §3),
//! shared with the JCR-1 receipt so a content id and a receipt agree on bytes.

use crate::SchemaError;
use serde::Serialize;
use serde_json::Value;

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

fn cbor_value(out: &mut Vec<u8>, v: &Value) -> Result<(), SchemaError> {
    match v {
        Value::String(s) => {
            cbor_text(out, s);
            Ok(())
        }
        Value::Number(n) => {
            let u = n.as_u64().ok_or(SchemaError::DisallowedType("non-uint number"))?;
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
            let mut keys: Vec<&String> = m.keys().collect();
            keys.sort_by(|a, b| a.len().cmp(&b.len()).then_with(|| a.as_str().cmp(b.as_str())));
            cbor_uint(out, 5, keys.len() as u64);
            for k in keys {
                cbor_text(out, k);
                cbor_value(out, &m[k])?;
            }
            Ok(())
        }
        Value::Bool(_) => Err(SchemaError::DisallowedType("bool")),
        Value::Null => Err(SchemaError::DisallowedType("null")),
    }
}

/// Canonically encode any serializable value to det-CBOR bytes.
pub fn canonical_cbor<T: Serialize>(value: &T) -> Result<Vec<u8>, SchemaError> {
    let v = serde_json::to_value(value).map_err(|_| SchemaError::DisallowedType("unserializable"))?;
    let mut out = Vec::new();
    cbor_value(&mut out, &v)?;
    Ok(out)
}

struct Reader<'a> {
    buf: &'a [u8],
    pos: usize,
}

impl<'a> Reader<'a> {
    fn byte(&mut self) -> Result<u8, SchemaError> {
        let b = *self.buf.get(self.pos).ok_or(SchemaError::DisallowedType("truncated cbor"))?;
        self.pos += 1;
        Ok(b)
    }

    fn take(&mut self, n: usize) -> Result<&'a [u8], SchemaError> {
        let end = self.pos.checked_add(n).filter(|&e| e <= self.buf.len());
        let end = end.ok_or(SchemaError::DisallowedType("truncated cbor"))?;
        let s = &self.buf[self.pos..end];
        self.pos = end;
        Ok(s)
    }

    fn head(&mut self) -> Result<(u8, u64), SchemaError> {
        let ib = self.byte()?;
        let (major, info) = (ib >> 5, ib & 0x1f);
        let arg = match info {
            0..=23 => info as u64,
            24 => self.byte()? as u64,
            25 => u16::from_be_bytes(self.take(2)?.try_into().unwrap()) as u64,
            26 => u32::from_be_bytes(self.take(4)?.try_into().unwrap()) as u64,
            27 => u64::from_be_bytes(self.take(8)?.try_into().unwrap()),
            _ => return Err(SchemaError::DisallowedType("indefinite-length cbor")),
        };
        Ok((major, arg))
    }

    fn value(&mut self, depth: u8) -> Result<Value, SchemaError> {
        if depth == 0 {
            return Err(SchemaError::DisallowedType("cbor nesting too deep"));
        }
        let (major, arg) = self.head()?;
        match major {
            0 => Ok(Value::from(arg)),
            3 => {
                let s = self.take(arg as usize)?;
                let s = std::str::from_utf8(s).map_err(|_| SchemaError::DisallowedType("invalid utf-8"))?;
                Ok(Value::String(s.to_string()))
            }
            4 => {
                let mut a = Vec::with_capacity((arg as usize).min(1024));
                for _ in 0..arg {
                    a.push(self.value(depth - 1)?);
                }
                Ok(Value::Array(a))
            }
            5 => {
                let mut m = serde_json::Map::new();
                for _ in 0..arg {
                    let k = match self.value(depth - 1)? {
                        Value::String(s) => s,
                        _ => return Err(SchemaError::DisallowedType("non-text map key")),
                    };
                    m.insert(k, self.value(depth - 1)?);
                }
                Ok(Value::Object(m))
            }
            _ => Err(SchemaError::DisallowedType("cbor major type outside det profile")),
        }
    }
}

/// Decode det-CBOR bytes into a value, enforcing canonicity: the input must be
/// byte-identical to its own canonical re-encoding, so a non-canonical encoding
/// of the same value is rejected rather than silently accepted. This keeps
/// content addressing injective across the wire — one value, one byte string,
/// one id.
pub fn from_canonical_cbor<T: serde::de::DeserializeOwned>(bytes: &[u8]) -> Result<T, SchemaError> {
    let mut r = Reader { buf: bytes, pos: 0 };
    let v = r.value(64)?;
    if r.pos != bytes.len() {
        return Err(SchemaError::DisallowedType("trailing bytes after cbor value"));
    }
    let mut reenc = Vec::new();
    cbor_value(&mut reenc, &v)?;
    if reenc != bytes {
        return Err(SchemaError::DisallowedType("non-canonical cbor"));
    }
    serde_json::from_value(v).map_err(|_| SchemaError::DisallowedType("shape mismatch"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn determinism_independent_of_key_order() {
        let a = serde_json::json!({"bb": 1, "a": 2, "ccc": 3});
        let b = serde_json::json!({"ccc": 3, "a": 2, "bb": 1});
        assert_eq!(canonical_cbor(&a).unwrap(), canonical_cbor(&b).unwrap());
    }

    #[test]
    fn rejects_floats_and_bools() {
        assert!(canonical_cbor(&serde_json::json!({"x": 1.5})).is_err());
        assert!(canonical_cbor(&serde_json::json!({"x": true})).is_err());
    }

    #[test]
    fn decode_round_trips() {
        let v = serde_json::json!({"bb": [1, 2, 3], "a": "hi", "ccc": {"k": 18446744073709551615u64}});
        let bytes = canonical_cbor(&v).unwrap();
        let back: Value = from_canonical_cbor(&bytes).unwrap();
        assert_eq!(back, v);
    }

    #[test]
    fn decode_rejects_non_canonical_and_trailing() {
        // 0x18 0x05 is uint 5 in non-shortest form; canonical is 0x05.
        assert!(from_canonical_cbor::<Value>(&[0x18, 0x05]).is_err());
        assert!(from_canonical_cbor::<Value>(&[0x05]).is_ok());
        // trailing garbage
        assert!(from_canonical_cbor::<Value>(&[0x05, 0x00]).is_err());
        // map with keys in the wrong canonical order
        let bad = {
            let mut out = vec![0xa2]; // map(2)
            cbor_text(&mut out, "bb");
            out.push(0x01);
            cbor_text(&mut out, "a"); // shorter key after longer — non-canonical
            out.push(0x02);
            out
        };
        assert!(from_canonical_cbor::<Value>(&bad).is_err());
    }
}
