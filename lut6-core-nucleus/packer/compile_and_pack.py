#!/usr/bin/env python3
"""Yosys `-lut 6` -> 4,096-byte `CompactLut6Page` (`.lut6`) Compiler, Levelizer & Miter Verifier.

Drives `yosys` (`synth -noalumacc -nordff; abc -lut 6; clean -purge; write_json`) on a real
combinational Verilog state-machine/routing rule (`verified_skill.v`), topologically levelizes
into `<= 64`-wide LUT6 layers (`<= 4` layers), executes the 64-point integer Walsh-Hadamard
spectral audit + exhaustive `2^14 = 16,384`-vector equivalence miter check, and emits:
  - `packer/verified_skill.lut6` (`4,096` bytes exact, verified inside Rust `lut6-core`)
  - `results/packer_yosys_audit.json`
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import zlib

LUT6_MAGIC = b"LUT6"
LUT6_SCHEMA_VER = 1
FLAG_VALIDATED = 1 << 0
FLAG_WOBBLE_CLEAN = 1 << 1
DOMAIN_HASH = 0x594F_5359_5336_4C55  # "YOSYS6LU"
MASK_CONST_0 = 0x0000_0000_0000_0000
MASK_CONST_1 = 0xFFFF_FFFF_FFFF_FFFF
MASK_WIRE0 = 0xAAAA_AAAA_AAAA_AAAA


def find_yosys() -> str:
    found = shutil.which("yosys")
    if found:
        return found
    local_y = Path.home() / ".local" / "bin" / "yosys"
    if local_y.is_file():
        return str(local_y)
    raise FileNotFoundError("`yosys` not found on PATH or ~/.local/bin/yosys")


def lut6_walsh_spectrum(init_mask: int) -> list[int]:
    """64-point unipolar integer Fast Walsh-Hadamard Transform (0 floats), matching `lut6-core`."""
    buf = [((init_mask >> x) & 1) for x in range(64)]
    step = 1
    while step < 64:
        jump = step * 2
        for base in range(0, 64, jump):
            for j in range(step):
                a = buf[base + j]
                b = buf[base + j + step]
                buf[base + j] = a + b
                buf[base + j + step] = a - b
        step *= 2
    return buf


def high_harmonic_energy(init_mask: int) -> int:
    wt = init_mask.bit_count()
    if wt == 0:
        return 0
    spec = lut6_walsh_spectrum(init_mask)
    deg5_sq = sum(spec[u] * spec[u] for u in range(64) if u.bit_count() >= 5)
    return (64 * deg5_sq) // wt


def max_boolean_degree(init_mask: int) -> int:
    if init_mask == 0:
        return 0
    spec = lut6_walsh_spectrum(init_mask)
    return max((u.bit_count() for u in range(64) if spec[u] != 0), default=0)


def pack_route6(wires: list[int]) -> tuple[int, int]:
    assert len(wires) == 6
    packed = 0
    for idx, w in enumerate(wires):
        packed |= (w & 0x3F) << (6 * idx)
    return packed & 0xFFFF_FFFF, (packed >> 32) & 0xFF


def expand_lut_to_u64(width: int, lut_bits_str: str) -> int:
    """Convert Yosys `$lut` `LUT` binary string (MSB-first `2^width` bits) into 64-bit `init_mask`."""
    assert 1 <= width <= 6
    n_entries = 1 << width
    bits = lut_bits_str.zfill(n_entries)
    # In Yosys JSON, `LUT` string index `0` is MSB (`addr = 2^width - 1`) and `[-1]` is LSB (`addr = 0`).
    base_mask = 0
    for addr in range(n_entries):
        ch = bits[n_entries - 1 - addr]
        if ch == "1":
            base_mask |= 1 << addr
    # Replicate across unused upper address bits `width..6` so wires[width..6] are true don't-cares!
    full_mask = 0
    for x in range(64):
        sub = x & (n_entries - 1)
        if (base_mask >> sub) & 1:
            full_mask |= 1 << x
    return full_mask


def parse_yosys_int_or_bin(val: int | str) -> int:
    if isinstance(val, int):
        return val
    s = str(val).strip()
    if all(c in "01" for c in s) and len(s) > 0:
        return int(s, 2)
    return int(s)


def golden_verified_skill(in_word: int) -> int:
    stem = (in_word >> 2) & 0x0F
    mag = (in_word >> 6) & 0x0F
    mstate = (in_word >> 10) & 0x03
    safety_ok = ((in_word >> 12) & 1) != 0
    budget_ok = ((in_word >> 13) & 1) != 0

    if not safety_ok:
        return 0x00BC
    if mstate == 0:
        return 0x0040

    high_mag = mag >= 10
    mid_mag = 4 <= mag < 10

    if stem == 0x8:
        opcode6, flags4 = 0x20, 0b0010
    elif stem == 0x9:
        opcode6, flags4 = 0x24, 0b0010
    elif stem == 0xA:
        opcode6, flags4 = (0x28, 0b0100) if (budget_ok and (high_mag or mid_mag)) else (0x2C, 0b0001)
    elif stem == 0xC:
        opcode6, flags4 = (0x30, 0b1000) if (budget_ok and high_mag and mstate != 3) else (0x2C, 0b0001)
    elif stem == 0x4:
        opcode6, flags4 = 0x10, 0b0001
    elif stem == 0x6:
        opcode6, flags4 = 0x18, 0b0001
    elif stem == 0xF:
        opcode6, flags4 = 0x3C, 0b1000
    else:
        opcode6, flags4 = (0x2C, 0b0001) if (high_mag and budget_ok) else (0x00, 0b0001)

    if mstate == 1:
        next_mstate = 2 if high_mag else 1
    elif mstate == 2:
        next_mstate = 2 if high_mag else 1
    elif mstate == 3:
        next_mstate = 1
    else:
        next_mstate = mstate

    parity = (opcode6 ^ flags4 ^ next_mstate).bit_count() & 1
    return opcode6 | (flags4 << 6) | (next_mstate << 10) | (parity << 12)


def eval_packed_page_py(
    num_layers: int,
    gates_per_layer: int,
    routes_lo: list[int],
    routes_hi: list[int],
    init_masks: list[int],
    state: int,
) -> int:
    passthrough_mask = 0 if gates_per_layer >= 64 else ((~0 << gates_per_layer) & ((1 << 64) - 1))
    cur = state & ((1 << 64) - 1)
    for layer in range(num_layers):
        base = layer * gates_per_layer
        nxt = cur & passthrough_mask
        for g in range(gates_per_layer):
            idx = base + g
            r = routes_lo[idx] | (routes_hi[idx] << 32)
            addr = 0
            for k in range(6):
                w = (r >> (6 * k)) & 0x3F
                addr |= ((cur >> w) & 1) << k
            if (init_masks[idx] >> addr) & 1:
                nxt |= 1 << g
        cur = nxt
    return cur


def compile_and_pack(verilog_path: Path, out_lut6_path: Path, out_json_path: Path) -> dict:
    yosys_bin = find_yosys()
    ver_out = subprocess.run([yosys_bin, "-V"], capture_output=True, text=True, check=True).stdout.strip()

    t0 = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
        netlist_json_path = Path(tf.name)

    try:
        yosys_script = (
            f"read_verilog {verilog_path}; "
            f"hierarchy -check -top verified_skill; "
            f"synth -top verified_skill -noalumacc -nordff; "
            f"abc -lut 6; "
            f"clean -purge; "
            f"write_json {netlist_json_path}"
        )
        subprocess.run(
            [yosys_bin, "-q", "-p", yosys_script],
            capture_output=True,
            text=True,
            check=True,
        )
        synth_ms = (time.perf_counter() - t0) * 1000.0
        raw_netlist_bytes = netlist_json_path.read_bytes()
        netlist = json.loads(raw_netlist_bytes.decode("utf-8"))
    finally:
        netlist_json_path.unlink(missing_ok=True)

    mod = netlist["modules"]["verified_skill"]
    in_bits = mod["ports"]["in_word"]["bits"]
    out_bits = mod["ports"]["out_word"]["bits"]
    assert len(in_bits) == 14 and len(out_bits) == 13

    # Map every Yosys net ID:
    #   "0" / "1": constant literals
    #   in_bits[i]: primary input wire `i` (`0..14`)
    #   cell output net `y_net`: produced by `$lut` cell `(inputs_nets, mask64)`
    lut_cells: dict[int, tuple[list[int | str], int, int]] = {}
    for cname, cinfo in mod["cells"].items():
        ctype = cinfo["type"]
        assert ctype == "$lut", f"Unexpected non-$lut cell `{ctype}` ({cname}) after `abc -lut 6`!"
        width = parse_yosys_int_or_bin(cinfo["parameters"]["WIDTH"])
        lut_raw = str(cinfo["parameters"]["LUT"])
        if not all(c in "01" for c in lut_raw):
            lut_val = int(lut_raw)
            lut_bits_str = format(lut_val, f"0{1 << width}b")
        else:
            lut_bits_str = lut_raw
        a_nets = cinfo["connections"]["A"]
        y_nets = cinfo["connections"]["Y"]
        assert len(a_nets) == width and len(y_nets) == 1
        y_net = y_nets[0]
        assert isinstance(y_net, int)
        mask64 = expand_lut_to_u64(width, lut_bits_str)
        lut_cells[y_net] = (a_nets, mask64, width)

    in_net_to_wire: dict[int, int] = {}
    for idx, b in enumerate(in_bits):
        assert isinstance(b, int)
        in_net_to_wire[b] = idx

    # Compute exact topological depth of every net (`0` for primary inputs / constants, `1..D` for `$lut` outputs)
    depth_map: dict[int | str, int] = {"0": 0, "1": 0}
    for net_id in in_net_to_wire:
        depth_map[net_id] = 0

    def get_depth(net: int | str) -> int:
        if net in depth_map:
            return depth_map[net]
        assert isinstance(net, int) and net in lut_cells, f"Undriven net {net}"
        a_nets, _, _ = lut_cells[net]
        d = 1 + max((get_depth(x) for x in a_nets), default=0)
        depth_map[net] = d
        return d

    for b in out_bits:
        get_depth(b)
    for y_net in lut_cells:
        get_depth(y_net)

    max_logic_depth = max((depth_map[y] for y in lut_cells), default=1)
    # Add 1 final output-alignment layer if needed, or pack directly into `num_layers = max_logic_depth`
    # Wait: if `max_logic_depth <= 3`, using `max_logic_depth + 1 <= 4` layers lets the final layer place
    # `out_bits[0..13]` directly on bus wires `0..13` cleanly, OR in the last layer `L = max_logic_depth`,
    # we can assign output-driving cells/buffers directly into slots `0..13`!
    # Let's assign slots cleanly per layer `l = 1 .. num_layers`:
    assert max_logic_depth <= 4, f"Logic depth {max_logic_depth} exceeds 4-layer single-page budget!"

    # Determine which signals must be alive after each layer `t in 0 .. max_logic_depth`:
    # At `t = 0`: primary inputs reside at wires `in_net_to_wire[net]`.
    # For each layer `t = 1 .. max_logic_depth`:
    #   - Every `$lut` cell with `depth == t` is evaluated in layer `t - 1`.
    #   - Any signal `s` with `depth < t` that is needed by a cell of `depth > t` OR is in `out_bits`
    #     is buffered through a 1-input pass-through LUT6 (`MASK_WIRE0`), and in the final layer
    #     (`t == max_logic_depth`), slots `0..13` are reserved in exact order for `out_bits[0..13]`!
    needed_at_end_of_layer: dict[int, set[int | str]] = {t: set() for t in range(1, max_logic_depth + 1)}
    for out_b in out_bits:
        for t in range(1, max_logic_depth + 1):
            if get_depth(out_b) <= t:
                needed_at_end_of_layer[t].add(out_b)

    for y_net, (a_nets, _, _) in lut_cells.items():
        dy = get_depth(y_net)
        for inp in a_nets:
            if inp in ("0", "1"):
                continue
            di = get_depth(inp)
            # `inp` is available at end of layer `di` (`t = 0` for PI) and consumed during layer `dy` (needs to survive end of `dy - 1`)
            for t in range(max(1, di), dy):
                needed_at_end_of_layer[t].add(inp)

    routes_lo = [0] * 256
    routes_hi = [0] * 256
    init_masks = [0] * 256

    # Track wire location (`0..63`) of each net at the input of layer `t` (`t = 1..max_logic_depth`)
    wire_loc: dict[int | str, int] = {net: w for net, w in in_net_to_wire.items()}
    layer_gate_counts: list[int] = []

    # Pre-check maximum width across all layers to choose uniform `gates_per_layer <= 64`
    layer_schedules: list[list[tuple[int | str | None, list[int], int]]] = []

    for t in range(1, max_logic_depth + 1):
        new_wire_loc: dict[int | str, int] = {}
        layer_ops: list[tuple[int | str | None, list[int], int]] = []

        def build_op_for_signal(sig: int | str) -> tuple[list[int], int]:
            if sig == "0":
                return [0, 0, 0, 0, 0, 0], MASK_CONST_0
            if sig == "1":
                return [0, 0, 0, 0, 0, 0], MASK_CONST_1
            if get_depth(sig) == t and sig in lut_cells:
                a_nets, m64, _w = lut_cells[sig]
                # Handle any literal `"0"` / `"1"` inside `a_nets` by folding cofactor if present
                wires6: list[int] = []
                eff_mask = m64
                # If a `$lut` had constant inputs, fold or map them cleanly:
                var_wires: list[int] = []
                # Evaluate full 6-input truth table over `var_wires`
                distinct_vars: list[int] = []
                for an in a_nets:
                    if isinstance(an, int):
                        w_idx = wire_loc[an]
                        if w_idx not in distinct_vars:
                            distinct_vars.append(w_idx)
                while len(distinct_vars) < 6:
                    distinct_vars.append(0)
                remapped_mask = 0
                for addr6 in range(64):
                    lut_in = 0
                    for bit_pos, an in enumerate(a_nets):
                        if an == "0":
                            bval = 0
                        elif an == "1":
                            bval = 1
                        else:
                            pos_in_dv = distinct_vars.index(wire_loc[an])
                            bval = (addr6 >> pos_in_dv) & 1
                        lut_in |= bval << bit_pos
                    if (eff_mask >> lut_in) & 1:
                        remapped_mask |= 1 << addr6
                return distinct_vars[:6], remapped_mask
            else:
                # Signal was already computed at depth `< t`: pass-through via `MASK_WIRE0`!
                src_w = wire_loc[sig]
                return [src_w, 0, 0, 0, 0, 0], MASK_WIRE0

        if t == max_logic_depth:
            # Final layer: place `out_bits[0..13]` at exact output wires `0..13`!
            for out_idx, out_sig in enumerate(out_bits):
                w6, m64 = build_op_for_signal(out_sig)
                layer_ops.append((out_sig, w6, m64))
                new_wire_loc[out_sig] = out_idx
        else:
            for sig in sorted(needed_at_end_of_layer[t], key=lambda x: (str(type(x)), x)):
                w6, m64 = build_op_for_signal(sig)
                slot = len(layer_ops)
                layer_ops.append((sig, w6, m64))
                new_wire_loc[sig] = slot

        assert len(layer_ops) <= 64, f"Layer {t} required {len(layer_ops)} > 64 LUT6 gates!"
        layer_gate_counts.append(len(layer_ops))
        layer_schedules.append(layer_ops)
        wire_loc = new_wire_loc

    num_layers = max_logic_depth
    gates_per_layer = max(max(layer_gate_counts), len(out_bits))
    assert num_layers <= 4 and gates_per_layer <= 64

    for layer_idx, ops in enumerate(layer_schedules):
        base = layer_idx * gates_per_layer
        for g_idx, (_sig, w6, m64) in enumerate(ops):
            lo, hi = pack_route6(w6)
            routes_lo[base + g_idx] = lo
            routes_hi[base + g_idx] = hi
            init_masks[base + g_idx] = m64
        # Remaining slots `[len(ops) .. gates_per_layer)` stay constant `0` (`init_mask = 0`)

    # Exhaustive `2^14 = 16,384`-vector equivalence miter check in Python BEFORE sealing!
    t_miter0 = time.perf_counter()
    miter_mismatches = 0
    wobble_mismatches = 0
    for vec in range(1 << 14):
        got = eval_packed_page_py(num_layers, gates_per_layer, routes_lo, routes_hi, init_masks, vec) & 0x1FFF
        exp = golden_verified_skill(vec)
        if got != exp:
            miter_mismatches += 1
        base_got = eval_packed_page_py(
            num_layers, gates_per_layer, routes_lo, routes_hi, init_masks, vec & ~0x3
        ) & 0x1FFF
        if got != base_got:
            wobble_mismatches += 1
    miter_ms = (time.perf_counter() - t_miter0) * 1000.0
    assert miter_mismatches == 0, f"Miter equivalence check failed on {miter_mismatches} vectors!"
    assert wobble_mismatches == 0, f"Wobble LSB invariance failed on {wobble_mismatches} vectors!"

    # Integer Walsh-Hadamard spectral audit across all active packed LUT6 slots
    active_slots = num_layers * gates_per_layer
    degree_hist = {d: 0 for d in range(7)}
    slot_energies = []
    for s in range(active_slots):
        m = init_masks[s]
        deg = max_boolean_degree(m)
        degree_hist[deg] += 1
        slot_energies.append(high_harmonic_energy(m))

    max_harm = max(slot_energies) if slot_energies else 0
    deg_ge5_count = sum(1 for e in slot_energies if e > 0)
    flags = FLAG_VALIDATED | (FLAG_WOBBLE_CLEAN if max_harm == 0 else 0)

    # Populate 32 embedded hardware anchors spanning all codon stems & metabolic states
    anchor_inputs = [0] * 32
    anchor_expected = [0] * 32
    for a in range(32):
        vec = ((a * 509) ^ 0x1234) & 0x3FFF
        anchor_inputs[a] = vec
        anchor_expected[a] = golden_verified_skill(vec)

    proof_digest = hashlib.sha256(raw_netlist_bytes + b"|MITER_16384_PASS").digest()
    parent_commit = hashlib.sha256(verilog_path.read_bytes()).digest()[:24]

    def build_binary(crc_val: int) -> bytes:
        hdr = struct.pack(
            "<4sHHQ24sQQBBBB I",
            LUT6_MAGIC,
            LUT6_SCHEMA_VER,
            flags,
            DOMAIN_HASH,
            parent_commit,
            0,  # conformal_mask
            0,  # override_mask
            64,  # conformal_thresh
            num_layers,
            gates_per_layer,
            3,  # kill_max_rejects
            crc_val,
        )
        assert len(hdr) == 64
        body = (
            struct.pack("<256I", *routes_lo)
            + bytes(routes_hi)
            + proof_digest
            + struct.pack("<32Q", *anchor_inputs)
            + struct.pack("<32Q", *anchor_expected)
            + struct.pack("<B", 32)
            + bytes(159)
            + struct.pack("<256Q", *init_masks)
        )
        page = hdr + body
        assert len(page) == 4096
        return page

    crc32_val = zlib.crc32(build_binary(0)) & 0xFFFF_FFFF
    final_page = build_binary(crc32_val)

    out_lut6_path.parent.mkdir(parents=True, exist_ok=True)
    out_lut6_path.write_bytes(final_page)

    audit = {
        "verilog_source": verilog_path.name,
        "verilog_sha256": hashlib.sha256(verilog_path.read_bytes()).hexdigest(),
        "yosys_version": ver_out,
        "yosys_command": "synth -top verified_skill -noalumacc -nordff; abc -lut 6; clean -purge; write_json",
        "yosys_synth_ms": round(synth_ms, 2),
        "abc_lut6_cell_count": len(lut_cells),
        "packed_num_layers": num_layers,
        "packed_gates_per_layer": gates_per_layer,
        "layer_active_gate_counts": layer_gate_counts,
        "total_packed_lut6_slots": active_slots,
        "walsh_hadamard_spectral_audit": {
            "boolean_degree_histogram": {str(k): v for k, v in degree_hist.items()},
            "max_gate_high_harmonic_energy": max_harm,
            "gates_with_deg_ge5_energy": deg_ge5_count,
            "lsb_2bit_wobble_invariant": wobble_mismatches == 0,
        },
        "exhaustive_equivalence_miter": {
            "active_input_bits": 14,
            "exhaustive_vectors_checked": 1 << 14,
            "miter_mismatches": miter_mismatches,
            "wobble_perturbation_mismatches": wobble_mismatches,
            "miter_check_ms": round(miter_ms, 2),
        },
        "emitted_crystal": {
            "file": out_lut6_path.name,
            "size_bytes": len(final_page),
            "crc32_hex": f"0x{crc32_val:08x}",
            "sha256": hashlib.sha256(final_page).hexdigest(),
            "embedded_anchors": 32,
        },
    }
    out_json_path.parent.mkdir(parents=True, exist_ok=True)
    out_json_path.write_text(json.dumps(audit, indent=2) + "\n", encoding="utf-8")
    return audit


def main() -> None:
    here = Path(__file__).resolve().parent
    root = here.parent
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--verilog", type=Path, default=here / "verified_skill.v")
    ap.add_argument("--out-lut6", type=Path, default=here / "verified_skill.lut6")
    ap.add_argument("--out-json", type=Path, default=root / "results" / "packer_yosys_audit.json")
    args = ap.parse_args()

    res = compile_and_pack(args.verilog.resolve(), args.out_lut6.resolve(), args.out_json.resolve())
    print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
