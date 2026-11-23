#!/usr/bin/env python3
"""
Wave 5 · LUT-Adapt Section 4.16: Gate-Level Primitive & Verilator VCD
Switching-Activity Audit on `xck26-sfvc784-2LV-c` (`est_j` / `est_mW` ONLY).

Pre-registration: `PREREG_xck26_vcd.json`
Provenance discipline:
  - `basis = "est"` (`est_j`, `est_pJ_per_cycle`, `est_mW_at_250mhz`).
  - `measured_j = None`, `board_metered = False`.
  - Not Vivado post-place-and-route timing closure or vector-annotated `report_power`
    (Vivado 2026.1 requires an AMD Standard `.lic` license file not installed on host).
  - Zero private paths, hostnames, or usernames emitted in output artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def verify_prereg(prereg_path: Path, sha_path: Path) -> tuple[str, dict[str, Any]]:
    raw = prereg_path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    expected = sha_path.read_text(encoding="utf-8").strip().split()[0]
    if actual != expected:
        raise RuntimeError(f"PREREG SHA-256 mismatch: expected {expected}, got {actual}")
    return actual, json.loads(raw.decode("utf-8"))


def find_eda_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    cand = Path.home() / ".local" / "bin" / name
    if cand.exists():
        return str(cand)
    raise FileNotFoundError(f"Required EDA tool '{name}' not found on PATH or ~/.local/bin")


def run_yosys_xcup_audit(yosys_bin: str, verilog_files: list[Path], top_module: str, cache_dir: Path | None = None) -> dict[str, Any]:
    """Runs Yosys 0.71+ `synth_xilinx -family xcup` + `ltp -noff` and extracts exact xcup primitive counts."""
    h = hashlib.sha256()
    h.update(top_module.encode("utf-8"))
    for vf in verilog_files:
        h.update(vf.read_bytes())
    cache_file = (cache_dir / f"yosys_{top_module}_{h.hexdigest()[:16]}.json") if cache_dir else None
    if cache_file and cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    read_cmds = []
    for vf in verilog_files:
        sv_flag = "-sv " if vf.suffix == ".sv" else ""
        read_cmds.append(f"read_verilog {sv_flag}-DSYNTHESIS {vf}")
    script = "; ".join(read_cmds) + f"; synth_xilinx -family xcup -top {top_module}; ltp -noff; stat -json"
    t0 = time.perf_counter()
    cp = subprocess.run([yosys_bin, "-Q", "-T", "-p", script], capture_output=True, text=True, check=True)
    wall_s = time.perf_counter() - t0
    out = cp.stdout

    ltp_levels = 0
    for ln in out.splitlines():
        if "Longest topological path in" in ln and "(length=" in ln:
            part = ln.split("(length=", 1)[1].split(")", 1)[0]
            ltp_levels = max(ltp_levels, int(part))

    j_idx = out.rfind("\n{\n")
    if j_idx == -1:
        j_idx = out.find("{")
    stats = json.loads(out[j_idx:])
    cells = stats.get("design", {}).get("num_cells_by_type", {})

    def cnt(exact: str) -> int:
        return int(cells.get(exact, 0))

    lut_breakdown = {f"LUT{k}": cnt(f"LUT{k}") for k in range(1, 7) if cnt(f"LUT{k}") > 0}
    luts_total = sum(lut_breakdown.values())
    muxf7 = cnt("MUXF7")
    muxf8 = cnt("MUXF8")
    carry4_equiv = cnt("CARRY4") + 2 * cnt("CARRY8")
    carry8_equiv = (carry4_equiv + 1) // 2
    fdre = cnt("FDRE")
    fdse = cnt("FDSE")
    fd_other = sum(int(v) for k, v in cells.items() if k.startswith("FD") and k not in ("FDRE", "FDSE"))
    ramb36 = cnt("RAMB36E2")
    ramb18 = cnt("RAMB18E2")
    dsp48 = cnt("DSP48E2")
    ibuf = cnt("IBUF")
    obuf = cnt("OBUF")

    res = {
        "top_module": top_module,
        "synth_wall_s": round(wall_s, 3),
        "clb_luts_total": luts_total,
        "clb_lut_pct_xck26": round(100.0 * luts_total / 117120.0, 2),
        "lut_primitives": lut_breakdown,
        "muxf7": muxf7,
        "muxf8": muxf8,
        "carry4_yosys_cells": carry4_equiv,
        "carry8_ultrascale_equiv": carry8_equiv,
        "clb_registers_total": fdre + fdse + fd_other,
        "clb_register_pct_xck26": round(100.0 * (fdre + fdse + fd_other) / 234240.0, 2),
        "fdre": fdre,
        "fdse": fdse,
        "ramb36e2": ramb36,
        "ramb36e2_pct_xck26": round(100.0 * ramb36 / 144.0, 2),
        "ramb18e2": ramb18,
        "dsp48e2": dsp48,
        "inferred_ibuf_obuf": [ibuf, obuf],
        "longest_combinational_topological_levels": ltp_levels,
    }
    if cache_file:
        cache_file.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
    return res


def generate_benes_paged_tb(vcd_path: Path) -> str:
    """Generates a self-checking 4-phase 250 MHz SystemVerilog testbench for `clai_benes_paged_hotswap_core`."""
    return f"""`timescale 1ns/1ps
module tb_vcd_benes_paged;
    logic         clk = 0;
    logic         rst_n = 0;
    always #2 clk = ~clk; // 250 MHz nominal (4,000 ps period)

    logic [511:0] bus_in = 512'd0;
    logic         bus_valid = 1'b0;
    logic [1:0]   ctx_lang_id = 2'd0;
    logic         page_cache_en = 1'b1;

    logic         cfg_we = 1'b0;
    logic [1:0]   cfg_kind = 2'd0;
    logic [6:0]   cfg_idx = 7'd0;
    logic [255:0] cfg_vec256 = 256'd0;
    logic [511:0] cfg_vec512 = 512'd0;
    logic         atomic_swap_pulse = 1'b0;

    logic         page_prog_we = 1'b0;
    logic         page_prog_is_tag = 1'b0;
    logic [8:0]   page_prog_addr = 9'd0;
    logic [6:0]   page_prog_lut_idx = 7'd0;
    logic [63:0]  page_prog_data64 = 64'd0;

    wire          active_bank;
    wire          out_valid;
    wire          page_hit_out;
    wire  [8:0]   page_slot_out;
    wire  [79:0]  l0_out_debug;
    wire  [15:0]  draft_word16_out;
    wire  [15:0]  draft_unanimous16_out;
    wire  [31:0]  telemetry_lookups;
    wire  [31:0]  telemetry_page_hits;
    wire  [31:0]  telemetry_cam_fallbacks;

    integer errors = 0;
    integer cyc, gl, p;
    logic [63:0] prng = 64'hCAFE_F00D_2026_1123;
    logic [511:0] cur_bus = 512'd0;
    time t0, t1;

    function automatic [63:0] next_rng(input [63:0] s);
        logic [63:0] x;
        begin
            x = s ^ (s << 13);
            x = x ^ (x >> 7);
            x = x ^ (x << 17);
            return x;
        end
    endfunction

    clai_benes_paged_hotswap_core #(.PAGE_ADDR_BITS(9)) dut (.*);

    initial begin
        repeat (40000) @(posedge clk);
        $display("WATCHDOG_TIMEOUT clai_benes_paged_hotswap_core");
        $fatal(1);
    end

    initial begin
        $dumpfile("{vcd_path}");
        $dumpvars(0, dut);

        // Pre-window initialization: reset, program Benes-Copy-Benes + 512 BRAM page tags/tables
        repeat (6) @(posedge clk);
        rst_n <= 1'b1;
        @(posedge clk);

        for (gl = 0; gl < 17; gl = gl + 1) begin
            prng = next_rng(prng);
            @(posedge clk); cfg_we <= 1'b1; cfg_kind <= 2'd0; cfg_idx <= gl[6:0]; cfg_vec256 <= {{4{{prng}}}};
        end
        for (gl = 0; gl < 9; gl = gl + 1) begin
            prng = next_rng(prng);
            @(posedge clk); cfg_we <= 1'b1; cfg_kind <= 2'd1; cfg_idx <= gl[6:0]; cfg_vec512 <= {{8{{prng}}}};
        end
        for (gl = 0; gl < 17; gl = gl + 1) begin
            prng = next_rng(prng);
            @(posedge clk); cfg_we <= 1'b1; cfg_kind <= 2'd2; cfg_idx <= gl[6:0]; cfg_vec256 <= {{4{{prng}}}};
        end
        for (gl = 0; gl < 80; gl = gl + 1) begin
            prng = next_rng(prng);
            @(posedge clk); cfg_we <= 1'b1; cfg_kind <= 2'd3; cfg_idx <= gl[6:0]; cfg_vec256 <= {{192'd0, prng}};
        end
        @(posedge clk); cfg_we <= 1'b0; atomic_swap_pulse <= 1'b1;
        @(posedge clk); atomic_swap_pulse <= 1'b0;

        // Pre-seed 64 representative BRAM slots (80 LUT6s + tag) and tags across 512 slots
        for (p = 0; p < 64; p = p + 1) begin
            for (gl = 0; gl < 80; gl = gl + 1) begin
                prng = next_rng(prng);
                @(posedge clk);
                page_prog_we <= 1'b1; page_prog_is_tag <= 1'b0;
                page_prog_addr <= p[8:0]; page_prog_lut_idx <= gl[6:0]; page_prog_data64 <= prng;
            end
            @(posedge clk);
            page_prog_we <= 1'b1; page_prog_is_tag <= 1'b1;
            page_prog_addr <= p[8:0]; page_prog_data64 <= {{13'd0, 1'b1, 2'd1, 39'h123456789A, p[8:0]}};
        end
        @(posedge clk); page_prog_we <= 1'b0;
        cur_bus = {{8{{64'hA55A_3CC3_F00F_0FF0}}}};
        bus_in <= cur_bus; bus_valid <= 1'b0;
        repeat (10) @(posedge clk);

        // PHASE 1: idle_quiescent (256 cycles)
        @(negedge clk); t0 = $time;
        repeat (256) @(posedge clk);
        @(negedge clk); t1 = $time;
        $display("PHASE_WINDOW idle_quiescent %0d %0d 256", t0, t1);

        // PHASE 2: steady_lut6_eval_2048_cycles (2048 cycles, realistic ~18%% bus bit turnover/cycle)
        @(negedge clk); t0 = $time;
        for (cyc = 0; cyc < 2048; cyc = cyc + 1) begin
            prng = next_rng(prng);
            // Flip ~96 of 512 CodeBitBus wires per token step while holding context hash steady for 8-beat runs
            cur_bus[63:0]   = cur_bus[63:0] ^ (prng & next_rng(prng));
            cur_bus[255:192] = cur_bus[255:192] ^ next_rng(prng ^ 64'h5555);
            cur_bus[447:384] = prng;
            if ((cyc & 7) == 0) cur_bus[127:80] = prng[47:0];
            bus_valid <= 1'b1;
            ctx_lang_id <= cyc[4:3];
            bus_in <= cur_bus;
            @(posedge clk);
            if (cyc > 2 && out_valid !== 1'b1) errors = errors + 1;
        end
        @(negedge clk); t1 = $time;
        $display("PHASE_WINDOW steady_lut6_eval_2048_cycles %0d %0d 2048", t0, t1);
        bus_valid <= 1'b0;
        repeat (6) @(posedge clk);

        // PHASE 3: single_cycle_page_switch_512_burst (512 cycles: every cycle switches RAMB36E2 page slot + full bus)
        @(negedge clk); t0 = $time;
        for (cyc = 0; cyc < 512; cyc = cyc + 1) begin
            prng = next_rng(prng);
            cur_bus = {{prng, next_rng(prng), prng ^ 64'hFFFF_0000_FFFF_0000, next_rng(prng ^ 64'h1234),
                        prng ^ 64'hAAAA_5555_AAAA_5555, {{16'h5A5A, cyc[8:0], 23'h3ABCDE, prng[15:0]}}, prng, ~prng}};
            bus_valid <= 1'b1;
            ctx_lang_id <= cyc[1:0];
            bus_in <= cur_bus;
            @(posedge clk);
            if (cyc > 2 && out_valid !== 1'b1) errors = errors + 1;
        end
        @(negedge clk); t1 = $time;
        $display("PHASE_WINDOW single_cycle_page_switch_512_burst %0d %0d 512", t0, t1);
        bus_valid <= 1'b0;
        repeat (6) @(posedge clk);

        // PHASE 4: shadow_page_stream_write (512 cycles: concurrent SleepCrystallizer RAMB36E2 + shadow Benes writes)
        @(negedge clk); t0 = $time;
        for (cyc = 0; cyc < 512; cyc = cyc + 1) begin
            prng = next_rng(prng);
            bus_valid <= 1'b1;
            bus_in <= cur_bus ^ {{448'd0, prng}};
            page_prog_we <= 1'b1;
            page_prog_is_tag <= (cyc[6:0] == 7'd80) ? 1'b1 : 1'b0;
            page_prog_addr <= cyc[8:0];
            page_prog_lut_idx <= (cyc % 80);
            page_prog_data64 <= prng;
            cfg_we <= 1'b1;
            cfg_kind <= cyc[1:0];
            cfg_idx <= (cyc % 17);
            cfg_vec256 <= {{4{{prng}}}};
            cfg_vec512 <= {{8{{prng}}}};
            atomic_swap_pulse <= (cyc == 511) ? 1'b1 : 1'b0;
            @(posedge clk);
        end
        @(negedge clk); t1 = $time;
        $display("PHASE_WINDOW shadow_page_stream_write %0d %0d 512", t0, t1);

        page_prog_we <= 1'b0; cfg_we <= 1'b0; bus_valid <= 1'b0; atomic_swap_pulse <= 1'b0;
        repeat (4) @(posedge clk);
        if (telemetry_lookups < 32'd3000) errors = errors + 1;
        $display("COSIM_SUMMARY clai_benes_paged_hotswap_core lookups=%0d errors=%0d", telemetry_lookups, errors);
        if (errors != 0) $fatal(1);
        $finish;
    end
endmodule
"""


def generate_kv260_axi_tb(vcd_path: Path) -> str:
    """Generates a self-checking 4-phase 250 MHz SystemVerilog testbench for `clai_kv260_axi_top`."""
    return f"""`timescale 1ns/1ps
module tb_vcd_kv260_axi;
    logic        aclk = 0;
    logic        aresetn = 0;
    always #2 aclk = ~aclk; // 250 MHz PL Clock (4,000 ps period)

    logic [11:0] s_axi_awaddr = 12'd0;
    logic [2:0]  s_axi_awprot = 3'd0;
    logic        s_axi_awvalid = 1'b0;
    wire         s_axi_awready;
    logic [31:0] s_axi_wdata = 32'd0;
    logic [3:0]  s_axi_wstrb = 4'hF;
    logic        s_axi_wvalid = 1'b0;
    wire         s_axi_wready;
    wire  [1:0]  s_axi_bresp;
    wire         s_axi_bvalid;
    logic        s_axi_bready = 1'b1;

    logic [11:0] s_axi_araddr = 12'd0;
    logic [2:0]  s_axi_arprot = 3'd0;
    logic        s_axi_arvalid = 1'b0;
    wire         s_axi_arready;
    wire  [31:0] s_axi_rdata;
    wire  [1:0]  s_axi_rresp;
    wire         s_axi_rvalid;
    logic        s_axi_rready = 1'b1;

    logic [7:0]  s_axis_tdata = 8'd0;
    logic        s_axis_tvalid = 1'b0;
    wire         s_axis_tready;
    logic        s_axis_tlast = 1'b0;
    wire         irq_escalate_to_ps;

    integer errors = 0;
    integer cyc, b_cnt;
    logic [63:0] prng = 64'hBEEF_CAFE_2026_1123;
    time t0, t1;

    function automatic [63:0] next_rng(input [63:0] s);
        logic [63:0] x;
        begin
            x = s ^ (s << 13);
            x = x ^ (x >> 7);
            x = x ^ (x << 17);
            return x;
        end
    endfunction

    clai_kv260_axi_top #(.ENGRAM_ADDR_BITS(10)) dut (.*);

    initial begin
        repeat (40000) @(posedge aclk);
        $display("WATCHDOG_TIMEOUT clai_kv260_axi_top");
        $fatal(1);
    end

    task automatic axi_write_fast(input [11:0] addr, input [31:0] data);
        begin
            @(posedge aclk);
            s_axi_awaddr <= addr; s_axi_awvalid <= 1'b1;
            s_axi_wdata  <= data; s_axi_wstrb <= 4'hF; s_axi_wvalid <= 1'b1;
            s_axi_bready <= 1'b1;
            fork
                begin do @(posedge aclk); while (!s_axi_awready); s_axi_awvalid <= 1'b0; end
                begin do @(posedge aclk); while (!s_axi_wready);  s_axi_wvalid  <= 1'b0; end
            join
            while (!s_axi_bvalid) @(posedge aclk);
            @(posedge aclk);
        end
    endtask

    initial begin
        $dumpfile("{vcd_path}");
        $dumpvars(0, dut);

        repeat (6) @(posedge aclk);
        aresetn <= 1'b1;
        repeat (4) @(posedge aclk);

        // Verify "CLAI" magic read at 0x080 (10'h020 word offset)
        @(posedge aclk);
        s_axi_araddr <= 12'h080; s_axi_arvalid <= 1'b1; s_axi_rready <= 1'b1;
        do @(posedge aclk); while (!s_axi_arready);
        s_axi_arvalid <= 1'b0;
        while (!s_axi_rvalid) @(posedge aclk);
        #1;
        if (s_axi_rdata !== 32'h434C_4149) errors = errors + 1;
        @(posedge aclk);

        // Configure CSRs (0x000 CSR_CTRL bit 2 = irq_enable; 0x008 CSR_MARGIN_THRESH = 4)
        axi_write_fast(12'h000, 32'h0000_0004);
        axi_write_fast(12'h008, 32'h0000_0004);
        repeat (10) @(posedge aclk);

        // PHASE 1: idle_quiescent (256 cycles)
        @(negedge aclk); t0 = $time;
        repeat (256) @(posedge aclk);
        @(negedge aclk); t1 = $time;
        $display("PHASE_WINDOW idle_quiescent %0d %0d 256", t0, t1);

        // PHASE 2: steady_lut6_eval_2048_cycles (2048 cycles of AXI4-Stream 31-byte packets + Rung-0 LUT6 voter)
        b_cnt = 0;
        @(negedge aclk); t0 = $time;
        for (cyc = 0; cyc < 2048; cyc = cyc + 1) begin
            prng = next_rng(prng);
            if (s_axis_tready) begin
                s_axis_tvalid <= 1'b1;
                s_axis_tdata  <= prng[7:0];
                s_axis_tlast  <= (b_cnt == 30) ? 1'b1 : 1'b0;
                b_cnt = (b_cnt == 30) ? 0 : (b_cnt + 1);
            end else begin
                s_axis_tvalid <= 1'b0;
                s_axis_tlast  <= 1'b0;
            end
            @(posedge aclk);
        end
        @(negedge aclk); t1 = $time;
        $display("PHASE_WINDOW steady_lut6_eval_2048_cycles %0d %0d 2048", t0, t1);
        s_axis_tvalid <= 1'b0; s_axis_tlast <= 1'b0;
        repeat (8) @(posedge aclk);

        // PHASE 3: single_cycle_page_switch_512_burst (512 cycles: short 8-byte packets + overlay bank hot-swaps)
        b_cnt = 0;
        @(negedge aclk); t0 = $time;
        for (cyc = 0; cyc < 512; cyc = cyc + 1) begin
            prng = next_rng(prng);
            if (s_axis_tready) begin
                s_axis_tvalid <= 1'b1;
                s_axis_tdata  <= prng[15:8];
                s_axis_tlast  <= (b_cnt == 7) ? 1'b1 : 1'b0;
                b_cnt = (b_cnt == 7) ? 0 : (b_cnt + 1);
            end else begin
                s_axis_tvalid <= 1'b0; s_axis_tlast <= 1'b0;
            end
            // Pulse atomic_swap_pulse (0x000 bit 5) & toggle csr_overlay_enable (bit 4) over AXI4-Lite
            if ((cyc & 7) == 0 && !s_axi_awvalid && !s_axi_wvalid) begin
                s_axi_awaddr <= 12'h000; s_axi_awvalid <= 1'b1;
                s_axi_wdata  <= (cyc[3] ? 32'h0000_0034 : 32'h0000_0024); s_axi_wvalid <= 1'b1;
            end else begin
                if (s_axi_awready) s_axi_awvalid <= 1'b0;
                if (s_axi_wready)  s_axi_wvalid  <= 1'b0;
            end
            @(posedge aclk);
        end
        @(negedge aclk); t1 = $time;
        $display("PHASE_WINDOW single_cycle_page_switch_512_burst %0d %0d 512", t0, t1);
        s_axis_tvalid <= 1'b0; s_axis_tlast <= 1'b0; s_axi_awvalid <= 1'b0; s_axi_wvalid <= 1'b0;
        repeat (8) @(posedge aclk);

        // PHASE 4: shadow_page_stream_write (512 cycles: AXI4-Lite shadow LUT6 0x050..0x058 & Engram BRAM 0x040..0x048 writes)
        b_cnt = 0;
        @(negedge aclk); t0 = $time;
        for (cyc = 0; cyc < 512; cyc = cyc + 1) begin
            prng = next_rng(prng);
            if (s_axis_tready) begin
                s_axis_tvalid <= 1'b1;
                s_axis_tdata  <= prng[23:16];
                s_axis_tlast  <= (b_cnt == 15) ? 1'b1 : 1'b0;
                b_cnt = (b_cnt == 15) ? 0 : (b_cnt + 1);
            end else begin
                s_axis_tvalid <= 1'b0; s_axis_tlast <= 1'b0;
            end
            if (!s_axi_awvalid && !s_axi_wvalid) begin
                case ((cyc >> 1) & 3)
                    0: begin s_axi_awaddr <= 12'h054; s_axi_wdata <= prng[31:0];  s_axi_awvalid <= 1'b1; s_axi_wvalid <= 1'b1; end
                    1: begin s_axi_awaddr <= 12'h044; s_axi_wdata <= prng[63:32]; s_axi_awvalid <= 1'b1; s_axi_wvalid <= 1'b1; end
                    2: begin s_axi_awaddr <= 12'h050; s_axi_wdata <= {{1'b1, 22'd0, cyc[8], 2'd0, cyc[7:2]}}; s_axi_awvalid <= 1'b1; s_axi_wvalid <= 1'b1; end
                    3: begin s_axi_awaddr <= 12'h040; s_axi_wdata <= {{1'b1, 14'd0, cyc[2], 6'd0, cyc[12:3]}}; s_axi_awvalid <= 1'b1; s_axi_wvalid <= 1'b1; end
                endcase
            end else begin
                if (s_axi_awready) s_axi_awvalid <= 1'b0;
                if (s_axi_wready)  s_axi_wvalid  <= 1'b0;
            end
            @(posedge aclk);
        end
        @(negedge aclk); t1 = $time;
        $display("PHASE_WINDOW shadow_page_stream_write %0d %0d 512", t0, t1);

        s_axis_tvalid <= 1'b0; s_axi_awvalid <= 1'b0; s_axi_wvalid <= 1'b0;
        repeat (6) @(posedge aclk);
        $display("COSIM_SUMMARY clai_kv260_axi_top errors=%0d", errors);
        if (errors != 0) $fatal(1);
        $finish;
    end
endmodule
"""


SEQ_NAME_HINTS = (
    "pipe", "reg", "sw", "copy_en", "l0_lut", "l0_table", "l0_wires", "l1_table", "l1_wires",
    "active_bank", "out_valid", "page_slot_out", "telemetry", "swap_generation", "rd_tag64",
    "rd_lut_word", "state", "xor_bytes", "slot_sum", "byte_cnt", "quad_shift", "rolling_hash",
    "bram_r", "bus_out", "last_pkt_len", "csr_", "mmio_", "latched_", "aw_", "w_", "s_axi_",
    "done_sticky", "hs_",
)


def classify_dut_var(scope_path: str, var_type: str, name: str) -> str:
    low = name.lower()
    if low in ("clk", "aclk", "clka", "clkb"):
        return "clock"
    if "rd_luts_flat" in low or "rd_lut_word" in low or "rd_tag64" in low or "bram_r6" in low or "bram_r7" in low:
        return "bram_data"
    if var_type == "reg" or any(low.startswith(p) or p in low for p in SEQ_NAME_HINTS):
        return "seq"
    return "comb"


def parse_vcd_phase_activity(vcd_path: Path, windows: list[tuple[str, int, int, int]], module_name: str) -> dict[str, Any]:
    """
    Single-pass VCD parser over `dut` unique identifier codes across the 4 exact `[t0, t1]` phase windows.
    Counts exact bit-level Hamming transitions per signal and tracks BRAM read/write port enables.
    """
    code_info: dict[str, tuple[str, int, str]] = {}  # code -> (category, width, canonical_name)
    special_codes: dict[str, str] = {}
    scope_stack: list[str] = []

    def popcount_xor_str(prev_s: str, cur_s: str, width: int) -> int:
        # Fast exact bit-difference count for 2-state/4-state VCD scalar & vector strings
        p = prev_s.replace("x", "0").replace("z", "0").replace("X", "0").replace("Z", "0")
        c = cur_s.replace("x", "0").replace("z", "0").replace("X", "0").replace("Z", "0")
        if width == 1:
            return 1 if p != c else 0
        try:
            return (int(p, 2) ^ int(c, 2)).bit_count()
        except ValueError:
            return 0

    phase_stats = {
        nm: {
            "cycles": cyc,
            "t_start_ps": t0,
            "t_end_ps": t1,
            "clock_transitions": 0,
            "seq_transitions": 0,
            "comb_transitions": 0,
            "bram_data_transitions": 0,
            "bram_write_enable_high_cycles": 0,
            "bram_read_enable_high_cycles": 0,
        }
        for nm, t0, t1, cyc in windows
    }

    prev_val: dict[str, str] = {}
    in_defs = True
    cur_t = 0
    active_win: str | None = None
    win_idx = 0
    sorted_wins = sorted(windows, key=lambda x: x[1])
    n_wins = len(sorted_wins)

    with vcd_path.open("r", encoding="utf-8", errors="replace") as f:
        for raw_ln in f:
            ln = raw_ln.strip()
            if not ln:
                continue
            if in_defs:
                if ln.startswith("$scope"):
                    parts = ln.split()
                    if len(parts) >= 3:
                        scope_stack.append(parts[2])
                elif ln.startswith("$upscope"):
                    if scope_stack:
                        scope_stack.pop()
                elif ln.startswith("$var"):
                    parts = ln.split()
                    if len(parts) >= 5 and "dut" in scope_stack:
                        vtype, width, code, vname = parts[1], int(parts[2]), parts[3], parts[4]
                        spath = "/".join(scope_stack)
                        if code not in code_info:
                            cat = classify_dut_var(spath, vtype, vname)
                            code_info[code] = (cat, width, f"{spath}/{vname}")
                        if spath.endswith("dut") and vname in (
                            "clk", "aclk", "bus_valid", "page_prog_we", "s_axis_tvalid", "s_axis_tready", "s_axis_tlast"
                        ):
                            special_codes[vname] = code
                        elif spath.endswith("dut") and vname == "bram_we_pulse":
                            special_codes["bram_we_pulse"] = code
                elif ln.startswith("$enddefinitions"):
                    in_defs = False
                continue

            c0 = ln[0]
            if c0 == "#":
                cur_t = int(ln[1:])
                while win_idx < n_wins and cur_t > sorted_wins[win_idx][2]:
                    win_idx += 1
                if win_idx < n_wins and sorted_wins[win_idx][1] <= cur_t <= sorted_wins[win_idx][2]:
                    active_win = sorted_wins[win_idx][0]
                else:
                    active_win = None
                continue
            if c0 == "$":
                continue

            if c0 in ("b", "B"):
                sp = ln.find(" ")
                if sp == -1:
                    continue
                val_s = ln[1:sp]
                code = ln[sp + 1 :]
            elif c0 in ("0", "1", "x", "z", "X", "Z"):
                val_s = c0
                code = ln[1:]
            else:
                continue

            info = code_info.get(code)
            if info is None:
                continue
            old_s = prev_val.get(code)
            prev_val[code] = val_s
            if old_s is None or active_win is None or old_s == val_s:
                # Still check rising clock edge for BRAM cycle-enable sampling!
                pass

            # Sample BRAM synchronous read/write port enables on rising clock edge inside active window
            clk_key = "clk" if "clk" in special_codes else "aclk"
            if active_win is not None and code == special_codes.get(clk_key) and val_s == "1" and old_s == "0":
                st_p = phase_stats[active_win]
                if module_name == "clai_benes_paged_hotswap_core":
                    # In clai_uram_lut6_page_cache, ENARDEN is tied high (unconditional synchronous read);
                    # page_prog_we writes 1 of 81 RAMB36E2 blocks per cycle when asserted.
                    if prev_val.get(special_codes.get("bus_valid", ""), "0") == "1":
                        st_p["bram_read_enable_high_cycles"] += 1
                    if prev_val.get(special_codes.get("page_prog_we", ""), "0") == "1":
                        st_p["bram_write_enable_high_cycles"] += 1
                else:
                    # In clai_engram_streamer, ENARDEN = accept_byte && s_axis_tlast; ENBWREN = bram_we_pulse
                    tv = prev_val.get(special_codes.get("s_axis_tvalid", ""), "0") == "1"
                    tr = prev_val.get(special_codes.get("s_axis_tready", ""), "0") == "1"
                    tl = prev_val.get(special_codes.get("s_axis_tlast", ""), "0") == "1"
                    if tv and tr and tl:
                        st_p["bram_read_enable_high_cycles"] += 1
                    if prev_val.get(special_codes.get("bram_we_pulse", ""), "0") == "1":
                        st_p["bram_write_enable_high_cycles"] += 1

            if old_s is not None and active_win is not None and old_s != val_s:
                cat, width, _ = info
                diff = popcount_xor_str(old_s, val_s, width)
                if diff > 0:
                    phase_stats[active_win][f"{cat}_transitions"] += diff

    cat_bits = {"clock": 0, "seq": 0, "comb": 0, "bram_data": 0}
    for cat, w, _ in code_info.values():
        cat_bits[cat] += w

    return {
        "unique_vcd_net_codes_in_dut": len(code_info),
        "traced_bits_by_category": cat_bits,
        "phases_raw": phase_stats,
    }


def compute_module_est_metrics(
    mod_name: str,
    yosys_info: dict[str, Any],
    vcd_info: dict[str, Any],
    model_cfg: dict[str, Any],
) -> dict[str, Any]:
    vcc = float(model_cfg["vccint_v"])
    f_mhz = float(model_cfg["nominal_clock_mhz"])
    v2_half = 0.5 * vcc * vcc  # fF * V^2 -> fJ
    v2_full = vcc * vcc

    c_clk_leaf = float(model_cfg["capacitance_ff"]["clock_leaf_per_ff_per_cycle_ff"])
    c_muxf = float(model_cfg["capacitance_ff"]["muxf7_muxf8_stage_ff"])
    c_carry = float(model_cfg["capacitance_ff"]["carry8_stage_and_local_net_ff"])

    n_lut = int(yosys_info["clb_luts_total"])
    n_muxf = int(yosys_info["muxf7"]) + int(yosys_info["muxf8"])
    n_carry8 = int(yosys_info["carry8_ultrascale_equiv"])
    n_fd = int(yosys_info["clb_registers_total"])
    n_bram = int(yosys_info["ramb36e2"])

    seq_bits = max(1, int(vcd_info["traced_bits_by_category"]["seq"]))
    comb_bits = max(1, int(vcd_info["traced_bits_by_category"]["comb"]))

    phases_out: dict[str, Any] = {}
    for pname, pstat in vcd_info["phases_raw"].items():
        cyc = int(pstat["cycles"])
        alpha_seq = pstat["seq_transitions"] / (seq_bits * cyc)
        alpha_comb = pstat["comb_transitions"] / (comb_bits * cyc)
        rd_duty = pstat["bram_read_enable_high_cycles"] / cyc
        wr_duty = pstat["bram_write_enable_high_cycles"] / cyc

        bands: dict[str, dict[str, float]] = {}
        for band in ("low", "nominal", "high"):
            c_lut = float(model_cfg["capacitance_ff"]["lut6_output_and_routing_net_ff"][band])
            c_fd = float(model_cfg["capacitance_ff"]["fdre_q_and_routing_net_ff"][band])
            e_rd = float(model_cfg["bram_36k_sdp_read_pj_per_enabled_cycle"][band])
            e_wr = float(model_cfg["bram_36k_sdp_write_pj_per_enabled_cycle"][band])

            # 1. Clock leaf & slice clock-buffer dynamic switching (fJ -> pJ)
            e_clk_pj = (n_fd * c_clk_leaf * v2_full) * 1e-3
            # 2. Sequential FDRE/FDSE Q + routing switching (fJ -> pJ)
            e_seq_pj = (n_fd * alpha_seq * c_fd * v2_half) * 1e-3
            # 3. Combinational LUT + MUXF7/8 + CARRY8 switching (fJ -> pJ)
            e_comb_pj = ((n_lut * c_lut + n_muxf * c_muxf + n_carry8 * c_carry) * alpha_comb * v2_half) * 1e-3
            # 4. RAMB36E2 dynamic array read/write energy (pJ/cycle)
            if mod_name == "clai_benes_paged_hotswap_core":
                # All 81 RAMB36E2s have unconditional read port enabled in current RTL:
                # full active sensing when bus_valid=1 (rd_duty), 0.65 constant-addr precharge when bus_valid=0;
                # page_prog_we writes 1 bank per cycle (1 block out of 81).
                e_bram_pj = n_bram * (rd_duty * e_rd + (1.0 - rd_duty) * 0.65 * e_rd) + 1.0 * wr_duty * e_wr
                # Also compute clock-enable-gated variant (ENARDEN = bus_valid)
                e_bram_ce_gated_pj = n_bram * (rd_duty * e_rd + (1.0 - rd_duty) * 0.15) + 1.0 * wr_duty * e_wr
            else:
                # clai_engram_streamer gates ENARDEN with (accept_byte && s_axis_tlast) across 4 RAMB36E2s,
                # and bram_we_pulse writes 2 RAMB36E2s (1 x 64-bit bank).
                e_bram_pj = n_bram * (rd_duty * e_rd + (1.0 - rd_duty) * 0.15) + 2.0 * wr_duty * e_wr
                e_bram_ce_gated_pj = e_bram_pj

            e_tot_pj = e_clk_pj + e_seq_pj + e_comb_pj + e_bram_pj
            p_tot_mw = e_tot_pj * f_mhz * 1e-3
            bands[band] = {
                "clock_leaf_est_pj_per_cycle": round(e_clk_pj, 3),
                "fdre_seq_est_pj_per_cycle": round(e_seq_pj, 3),
                "lut_mux_carry_comb_est_pj_per_cycle": round(e_comb_pj, 3),
                "ramb36e2_est_pj_per_cycle": round(e_bram_pj, 3),
                "ramb36e2_if_ce_gated_est_pj_per_cycle": round(e_bram_ce_gated_pj, 3),
                "total_dynamic_est_pj_per_cycle": round(e_tot_pj, 3),
                "total_dynamic_est_mw_at_250mhz": round(p_tot_mw, 3),
                "total_dynamic_if_bram_ce_gated_est_mw_at_250mhz": round((e_clk_pj + e_seq_pj + e_comb_pj + e_bram_ce_gated_pj) * f_mhz * 1e-3, 3),
            }

        phases_out[pname] = {
            "cycles": cyc,
            "raw_seq_transitions_per_cycle": round(pstat["seq_transitions"] / cyc, 3),
            "raw_comb_transitions_per_cycle": round(pstat["comb_transitions"] / cyc, 3),
            "raw_bram_data_transitions_per_cycle": round(pstat["bram_data_transitions"] / cyc, 3),
            "alpha_seq_transitions_per_bit_cycle": round(alpha_seq, 6),
            "alpha_comb_transitions_per_bit_cycle": round(alpha_comb, 6),
            "bram_valid_read_duty": round(rd_duty, 4),
            "bram_write_duty": round(wr_duty, 4),
            "est_nominal": bands["nominal"],
            "est_sensitivity_range": {"low": bands["low"], "high": bands["high"]},
        }

    # Analytical DS925 -2LV critical-path delay budget (est_ns, NOT Vivado post-PAR WNS)
    td = model_cfg["timing_delay_budget_ds925_2lv_ns"]
    lvls = int(yosys_info["longest_combinational_topological_levels"])
    t_stage_nom = float(td["lut_t_ilo_ns"]) + float(td["interconnect_net_per_level_ns"]["nominal"])
    t_stage_wide = float(td["lut_t_ilo_ns"]) + float(td["interconnect_net_per_level_ns"]["congested_wide_bus"])
    bram_extra = float(td["ramb36e2_t_rcko_do_noreg_ns"]) - float(td["fdre_t_cko_ns"]) if mod_name == "clai_benes_paged_hotswap_core" else 0.0
    unpipelined_nom_ns = float(td["fdre_t_cko_ns"]) + bram_extra + lvls * t_stage_nom + float(td["fdre_setup_plus_uncertainty_ns"])
    unpipelined_wide_ns = float(td["fdre_t_cko_ns"]) + bram_extra + lvls * t_stage_wide + float(td["fdre_setup_plus_uncertainty_ns"])
    pipe4_levels = (lvls + 3) // 4
    pipe4_nom_ns = float(td["fdre_t_cko_ns"]) + pipe4_levels * (float(td["lut_t_ilo_ns"]) + float(td["interconnect_net_per_level_ns"]["short_local"])) + float(td["fdre_setup_plus_uncertainty_ns"])

    timing_est = {
        "basis": "analytical_ds925_2lv_logic_stage_model_not_vivado_post_par",
        "combinational_levels_ltp": lvls,
        "unpipelined_est_path_delay_nominal_ns": round(unpipelined_nom_ns, 3),
        "unpipelined_est_path_delay_wide_bus_ns": round(unpipelined_wide_ns, 3),
        "unpipelined_est_fmax_mhz_range": [round(1000.0 / unpipelined_wide_ns, 1), round(1000.0 / unpipelined_nom_ns, 1)],
        "unpipelined_est_slack_vs_4ns_nominal_ns": round(4.0 - unpipelined_nom_ns, 3),
        "pipelined_4stage_levels_per_stage": pipe4_levels,
        "pipelined_4stage_with_bram_doreg_est_delay_ns": round(pipe4_nom_ns, 3),
        "pipelined_4stage_meets_250mhz_4ns_budget_est": bool(pipe4_nom_ns <= 4.0),
    }

    return {
        "yosys_xcup_primitives": yosys_info,
        "vcd_trace_coverage": {
            "unique_vcd_net_codes_in_dut": vcd_info["unique_vcd_net_codes_in_dut"],
            "traced_bits_by_category": vcd_info["traced_bits_by_category"],
        },
        "phases": phases_out,
        "analytical_ds925_2lv_timing_budget": timing_est,
    }


def run_verilator_vcd(verilator_bin: str, work: Path, top_tb: str, rtl_files: list[Path], tb_src: str, vcd_path: Path) -> list[tuple[str, int, int, int]]:
    tb_file = work / f"{top_tb}.sv"
    tb_file.write_text(tb_src, encoding="utf-8")
    obj_dir = work / f"obj_{top_tb}"
    subprocess.run(
        [
            verilator_bin, "--binary", "--timing", "--trace",
            "--trace-max-array", "64", "--trace-max-width", "8192",
            "-j", "4", "-Wno-UNOPTFLAT", "-Wno-DECLFILENAME", "-Wno-UNUSED", "-Wno-WIDTHEXPAND", "-Wno-WIDTHTRUNC",
            "--Mdir", str(obj_dir), "--top-module", top_tb,
            *[str(p) for p in rtl_files], str(tb_file),
        ],
        check=True, capture_output=True, text=True,
    )
    cp = subprocess.run([str(obj_dir / f"V{top_tb}")], check=True, capture_output=True, text=True, timeout=45)
    windows: list[tuple[str, int, int, int]] = []
    for ln in cp.stdout.splitlines():
        if ln.startswith("PHASE_WINDOW "):
            _, nm, s0, s1, cyc = ln.split()
            # Testbench `timescale is 1ns/1ps: $time is in ns, VCD # timestamps are in ps (x1000)
            windows.append((nm, int(s0) * 1000, int(s1) * 1000, int(cyc)))
        elif ln.startswith("COSIM_SUMMARY "):
            print(f"  [{ln}]", flush=True)
    assert len(windows) == 4, f"Expected 4 PHASE_WINDOW lines, got {windows}"
    return windows


def main() -> None:
    ap = argparse.ArgumentParser(description="Run LUT-Adapt xck26 Verilator VCD toggle & DS925 est_j audit.")
    ap.add_argument("--prereg", required=True, type=Path)
    ap.add_argument("--prereg-sha256", required=True, type=Path)
    ap.add_argument("--repo-dir", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--out-json", required=True, type=Path)
    args = ap.parse_args()

    prereg_sha, prereg = verify_prereg(args.prereg, args.prereg_sha256)
    yosys_bin = find_eda_tool("yosys")
    verilator_bin = find_eda_tool("verilator")
    args.work_dir.mkdir(parents=True, exist_ok=True)

    repo = args.repo_dir
    benes_sv = repo / "hw/kv260/rtl/clai_benes_hotswap_core.sv"
    streamer_sv = repo / "hw/kv260/rtl/clai_engram_streamer.sv"
    hotswap_sv = repo / "hw/kv260/rtl/clai_rung0_hotswap_core.sv"
    axi_top_sv = repo / "hw/kv260/rtl/clai_kv260_axi_top.sv"
    rung0_v = repo / "artifacts/clai_rung0_kv260.v"

    print("[1/4] Synthesizing clai_benes_paged_hotswap_core with Yosys synth_xilinx -family xcup...", flush=True)
    y_benes = run_yosys_xcup_audit(yosys_bin, [benes_sv], "clai_benes_paged_hotswap_core", cache_dir=args.work_dir)

    print("[2/4] Synthesizing clai_kv260_axi_top with Yosys synth_xilinx -family xcup...", flush=True)
    y_axi = run_yosys_xcup_audit(yosys_bin, [rung0_v, streamer_sv, hotswap_sv, axi_top_sv], "clai_kv260_axi_top", cache_dir=args.work_dir)

    print("[3/4] Running 4-phase Verilator VCD simulation & transition audit on clai_benes_paged_hotswap_core...", flush=True)
    vcd_benes = args.work_dir / "benes_paged.vcd"
    win_benes = run_verilator_vcd(verilator_bin, args.work_dir, "tb_vcd_benes_paged", [benes_sv], generate_benes_paged_tb(vcd_benes), vcd_benes)
    parsed_benes = parse_vcd_phase_activity(vcd_benes, win_benes, "clai_benes_paged_hotswap_core")
    vcd_benes.unlink(missing_ok=True)

    print("[4/4] Running 4-phase Verilator VCD simulation & transition audit on clai_kv260_axi_top...", flush=True)
    vcd_axi = args.work_dir / "kv260_axi.vcd"
    win_axi = run_verilator_vcd(verilator_bin, args.work_dir, "tb_vcd_kv260_axi", [rung0_v, streamer_sv, hotswap_sv, axi_top_sv], generate_kv260_axi_tb(vcd_axi), vcd_axi)
    parsed_axi = parse_vcd_phase_activity(vcd_axi, win_axi, "clai_kv260_axi_top")
    vcd_axi.unlink(missing_ok=True)

    m_cfg = prereg["AnalyticalModel"]
    est_benes = compute_module_est_metrics("clai_benes_paged_hotswap_core", y_benes, parsed_benes, m_cfg)
    est_axi = compute_module_est_metrics("clai_kv260_axi_top", y_axi, parsed_axi, m_cfg)

    idle_b_comb = est_benes["phases"]["idle_quiescent"]["alpha_comb_transitions_per_bit_cycle"]
    idle_a_comb = est_axi["phases"]["idle_quiescent"]["alpha_comb_transitions_per_bit_cycle"]
    f2_trig = (idle_b_comb > 0.001) or (idle_a_comb > 0.001)

    payload = {
        "schema": "openie.lut_adapt.xck26_vcd_switching_est.v1",
        "prereg_id": prereg["id"],
        "prereg_sha256": prereg_sha,
        "recorded_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target_part": "xck26-sfvc784-2LV-c",
        "target_board": "AMD Kria KV260 Vision AI Starter Kit (K26 SOM, -2LV, VCCINT = 0.72 V, VCCBRAM = 0.85 V)",
        "source_repository": prereg["provenance"]["source_repository"],
        "source_commit": prereg["provenance"]["source_commit"],
        "nominal_clock_mhz": 250.0,
        "nominal_clock_period_ns": 4.0,
        "evidence_separation": {
            "basis": "est_j",
            "board_metered": False,
            "measured_j": None,
            "reported_j": None,
            "vivado_post_route_power_w": None,
            "vivado_post_route_wns_ns": None,
            "note": "Activity-calibrated analytical dynamic switching energy (est_pJ/cycle) and power (est_mW @ 250 MHz) derived from exact Verilator 5.054 VCD bit transitions and Yosys 0.71+ synth_xilinx -family xcup primitive counts using AMD DS925/UG573 -2LV 0.72 V capacitance & BRAM parameters. Excludes static silicon leakage and is never merged with measured_j or Vivado post-PAR timing closure.",
        },
        "eda_toolchains": {
            "yosys": subprocess.check_output([yosys_bin, "-V"], text=True).strip(),
            "verilator": subprocess.check_output([verilator_bin, "--version"], text=True).strip(),
            "host_os": f"{platform.system()} {platform.release()} {platform.machine()}",
        },
        "analytical_model_parameters": m_cfg,
        "modules": {
            "clai_benes_paged_hotswap_core": est_benes,
            "clai_kv260_axi_top": est_axi,
        },
        "falsifiers_check": {
            "F1_functional_cosim_error_triggered": False,
            "F2_quiescent_data_toggle_leak_triggered": f2_trig,
            "F3_provenance_conflation_triggered": False,
        },
    }

    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"[DONE] Wrote {args.out_json}", flush=True)


if __name__ == "__main__":
    main()
