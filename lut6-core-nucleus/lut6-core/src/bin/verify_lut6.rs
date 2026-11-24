//! Verifies a Yosys-synthesized 4,096-byte `.lut6` crystal (`packer/verified_skill.lut6`)
//! bit-for-bit inside `lut6-core` across all `16,384` exhaustive 14-bit active input vectors
//! for both scalar `eval_raw` and vertical bit-sliced `eval_batch_64`.

use std::env;
use std::fs;
use std::path::PathBuf;

use lut6_core::{CompactLut6Page, LUT6_PAGE_BYTES, high_harmonic_energy};

/// Golden behavioural specification matching `packer/verified_skill.v` bit-for-bit.
fn golden_verified_skill(in_word: u64) -> u64 {
    // 14 active input bits:
    //   [5:0]   = sensory codon (bits [1:0] are 2-bit wobble LSBs, ignored by design!)
    //   [9:6]   = 4-bit quantized sensor magnitude `mag`
    //   [11:10] = 2-bit metabolic state `mstate` (0=QUIET, 1=READY, 2=BUSY, 3=SATURATED)
    //   [12]    = `safety_ok` interlock
    //   [13]    = `budget_ok` strobe
    let stem = ((in_word >> 2) & 0x0F) as u8;
    let mag = ((in_word >> 6) & 0x0F) as u8;
    let mstate = ((in_word >> 10) & 0x03) as u8;
    let safety_ok = ((in_word >> 12) & 1) != 0;
    let budget_ok = ((in_word >> 13) & 1) != 0;

    if !safety_ok {
        // Emergency rollback opcode 0x3C + alarm bit 7
        return 0x0080 | 0x003C;
    }
    if mstate == 0 {
        // QUIET -> STOP_HALT 0x00 + sleep bit 6
        return 0x0040;
    }

    let high_mag = mag >= 10;
    let mid_mag = (4..10).contains(&mag);

    let (opcode6, flags4): (u64, u64) = match stem {
        0x8 => (0x20, 0b0010), // BUS_PIO_SPI
        0x9 => (0x24, 0b0010), // BUS_UART_MCP
        0xA => {
            if budget_ok && (high_mag || mid_mag) {
                (0x28, 0b0100) // WAKE_LOCAL_NPU
            } else {
                (0x2C, 0b0001) // VERIFY_CHECK fallback
            }
        }
        0xC => {
            if budget_ok && high_mag && mstate != 3 {
                (0x30, 0b1000) // TRANSCRIBE_FRONTIER
            } else {
                (0x2C, 0b0001) // VERIFY_CHECK
            }
        }
        0x4 => (0x10, 0b0001), // SPLICE_PAGE
        0x6 => (0x18, 0b0001), // FOLD_STATE
        0xF => (0x3C, 0b1000), // APOPTOSIS_ROLLBACK
        _ => {
            if high_mag && budget_ok {
                (0x2C, 0b0001) // VERIFY_CHECK on unexpected high sensor reading
            } else {
                (0x00, 0b0001) // STOP_HALT
            }
        }
    };

    let next_mstate: u64 = match (mstate, high_mag) {
        (1, true) => 2,
        (2, false) => 1,
        (3, _) => 1,
        _ => mstate as u64,
    };

    let parity = ((opcode6 ^ flags4 ^ next_mstate).count_ones() & 1) as u64;
    // 13-bit structured output word in bits [12:0] (upper bits pass through `0` when input upper bits are `0`)
    opcode6 | (flags4 << 6) | (next_mstate << 10) | (parity << 12)
}

fn main() {
    let path = env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("packer/verified_skill.lut6"));
    let raw = fs::read(&path).unwrap_or_else(|e| panic!("failed to read {}: {e}", path.display()));
    assert_eq!(
        raw.len(),
        LUT6_PAGE_BYTES,
        "expected exact 4096-byte .lut6 crystal"
    );
    let arr: &[u8; LUT6_PAGE_BYTES] = raw.as_slice().try_into().unwrap();
    let page = CompactLut6Page::from_bytes_verified(arr)
        .expect("4096-byte .lut6 crystal failed header or IEEE CRC-32 verification!");

    let total_vectors: usize = 1 << 14; // 16,384 exhaustive active 14-bit vectors
    let mut scalar_mismatches = 0usize;
    let mut bitsliced_mismatches = 0usize;
    let mut wobble_mismatches = 0usize;

    let mut batch_in = [0u64; 64];
    for base in (0..total_vectors).step_by(64) {
        for lane in 0..64 {
            batch_in[lane] = (base + lane) as u64;
        }
        let batch_out = page.eval_batch_64(&batch_in);
        for lane in 0..64 {
            let inp = batch_in[lane];
            let exp = golden_verified_skill(inp);
            let got_scalar = page.eval_raw(inp) & 0x1FFF;
            let got_bs = batch_out[lane] & 0x1FFF;
            if got_scalar != exp {
                scalar_mismatches += 1;
            }
            if got_bs != exp {
                bitsliced_mismatches += 1;
            }
            // Verify 2-bit LSB wobble invariance (`inp ^ 1`, `inp ^ 2`, `inp ^ 3`)
            let base_w0 = page.eval_raw(inp & !0x3) & 0x1FFF;
            if got_scalar != base_w0 {
                wobble_mismatches += 1;
            }
        }
    }

    let active_gates = (page.num_layers as usize) * (page.gates_per_layer as usize);
    let mut max_harm = 0u32;
    let mut deg_ge5_gates = 0usize;
    for g in 0..active_gates {
        let e = high_harmonic_energy(page.init_masks[g]);
        if e > max_harm {
            max_harm = e;
        }
        if e > 0 {
            deg_ge5_gates += 1;
        }
    }

    assert_eq!(scalar_mismatches, 0, "scalar eval_raw mismatch against Verilog spec!");
    assert_eq!(bitsliced_mismatches, 0, "eval_batch_64 mismatch against Verilog spec!");
    assert_eq!(wobble_mismatches, 0, "2-bit LSB wobble invariance violated!");

    println!(
        "{{\n  \"crystal_file\": \"{}\",\n  \"crystal_bytes\": {},\n  \
         \"crc32\": \"0x{:08x}\",\n  \"num_layers\": {},\n  \"gates_per_layer\": {},\n  \
         \"active_lut6_slots\": {},\n  \"exhaustive_vectors_tested\": {},\n  \
         \"scalar_mismatches\": {},\n  \"bitsliced_mismatches\": {},\n  \
         \"wobble_lsb_mismatches\": {},\n  \"max_gate_high_harmonic_energy\": {},\n  \
         \"gates_with_deg_ge5_energy\": {}\n}}",
        path.file_name().unwrap().to_string_lossy(),
        raw.len(),
        page.crc32,
        page.num_layers,
        page.gates_per_layer,
        active_gates,
        total_vectors,
        scalar_mismatches,
        bitsliced_mismatches,
        wobble_mismatches,
        max_harm,
        deg_ge5_gates
    );
}
