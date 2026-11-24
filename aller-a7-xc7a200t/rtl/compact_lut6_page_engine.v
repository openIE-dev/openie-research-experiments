`timescale 1ns/1ps
// =============================================================================
// File   : compact_lut6_page_engine.v
// Target : Xilinx 7-Series XC7A200T-2FBG484C (`TARGET_FAMILY = 0`) &
//          UltraScale+ XCK26 / XCZU9EG (`TARGET_FAMILY = 1`)
// Summary:
//   Hardware 4,096-Byte `CompactLut6Page` (`lut6-core` canonical binary ABI)
//   Evaluator with:
//     - Dual-banked `2 x RAMB36E1` (`ramb36e1_shadow_bank`) storing the complete
//       canonical `512 x 64-bit` (`4,096-byte`) `.lut6` crystal (header, routes,
//       proof digest, CRC32, and `256 x 64-bit` `INIT` truth tables) with byte
//       parity and `ENARDEN` clock-enable gating.
//     - 3-stage balanced (`II = 1`, `CPI = 1.00`, `<= 10` LUT levels/stage)
//       64-wire `LUT6` bitboard pipeline (`FDRE` `CE`-gated on valid bubbles).
//     - Zero-DSP (`DSP48E1 = 0`) parallel 6-input `LUT6` popcount compressor
//       implementing the Conformal Wake Gate (`votes >= conformal_thresh` ->
//       `OUTCOME_ACT` vs `OUTCOME_ESCALATE` `irq_conformal_wake`) and hardware
//       falsifier kill latch (`rejects >= kill_max_rejects` -> `OUTCOME_KILLED`).
// =============================================================================

module compact_lut6_page_engine #(
    parameter integer TARGET_FAMILY    = 0,
    parameter integer ENABLE_CE_GATING = 1
) (
    input  wire        clk,
    input  wire        rst_n,

    // Streaming 64-Wire Canonical Bitboard Lookup Port (`CPI = 1.00`)
    input  wire        eval_valid,
    input  wire [63:0] state_in,

    // Shadow `CompactLut6Page` (`512 x 64-bit` = `4,096 B`) Programming Port
    input  wire        shadow_wr_en,
    input  wire [8:0]  shadow_wr_addr,
    input  wire [63:0] shadow_wr_data,
    input  wire        atomic_swap_pulse,
    input  wire        verifier_reject_pulse,
    input  wire        clear_ledger_pulse,

    // CE-Gated Active `RAMB36E1` Crystal Inspection / Readback Port
    input  wire        active_rd_en,
    input  wire [8:0]  active_rd_addr,
    output wire [63:0] active_rd_data,
    output wire        active_rd_parity_err,

    // Registered Stage-3 Outcomes & Conformal Interrupts
    output wire        active_bank,
    output wire [31:0] swap_generation,
    output reg         out_valid,
    output reg  [1:0]  out_outcome,      // 2'd0 = ACT, 2'd1 = ESCALATE, 2'd2 = KILLED
    output reg  [63:0] out_payload64,
    output reg  [6:0]  out_votes,
    output reg         irq_conformal_wake,
    output reg         irq_verifier_killed,

    // Hardware PageLedger Telemetry Counters
    output reg  [31:0] ledger_hits,
    output reg  [31:0] ledger_escalations,
    output reg  [31:0] ledger_rejects
);

    localparam [31:0] LUT6_MAGIC_LE    = 32'h3654_554C; // *b"LUT6"
    localparam [1:0]  OUTCOME_ACT      = 2'd0;
    localparam [1:0]  OUTCOME_ESCALATE = 2'd1;
    localparam [1:0]  OUTCOME_KILLED   = 2'd2;

    // -------------------------------------------------------------------------
    // 1. Canonical 4,096-Byte Dual-Bank `RAMB36E1` / `RAMB36E2` Store
    // -------------------------------------------------------------------------
    ramb36e1_shadow_bank #(
        .TARGET_FAMILY(TARGET_FAMILY)
    ) u_crystal_bram_bank (
        .clk                  (clk),
        .rst_n                (rst_n),
        .atomic_swap_pulse    (atomic_swap_pulse),
        .active_bank          (active_bank),
        .swap_generation      (swap_generation),
        .shadow_wr_en         (shadow_wr_en),
        .shadow_wr_addr       (shadow_wr_addr),
        .shadow_wr_data       (shadow_wr_data),
        .active_rd_en         (active_rd_en),
        .active_rd_addr       (active_rd_addr),
        .active_rd_data       (active_rd_data),
        .active_rd_parity_err (active_rd_parity_err)
    );

    // -------------------------------------------------------------------------
    // 2. Dual-Bank Fast-Path Working Registers Synchronized with Canonical Layout
    //    - word 0   (0x000): magic[31:0], schema_ver[15:0], flags[15:0]
    //    - word 4   (0x020): conformal_mask[63:0]
    //    - word 6   (0x030): conformal_thresh[15:0], num_layers[7:0],
    //                        gates_per_layer[7:0], kill_max_rejects[31:0]
    //    - words 8..39   (0x040..0x17F): Layer-0 routes_lo[0..63] (2 gates/word)
    //    - words 136..143(0x440..0x47F): Layer-0 routes_hi[0..63] (8 gates/word)
    //    - words 256..319(0x800..0x9FF): Layer-0 init_masks[0..63] (1 gate/word)
    // -------------------------------------------------------------------------
    reg [31:0] hdr_magic         [0:1];
    reg [63:0] hdr_conf_mask     [0:1];
    reg [15:0] hdr_conf_thresh   [0:1];
    reg [7:0]  hdr_num_layers    [0:1];
    reg [7:0]  hdr_gates_layer   [0:1];
    reg [31:0] hdr_kill_max_rej  [0:1];

    reg [29:0] gate_routes_lo    [0:1][0:63];
    reg [5:0]  gate_routes_hi    [0:1][0:63];
    reg [63:0] gate_init_mask    [0:1][0:63];

    wire shadow = ~active_bank;

    integer bi, gi;
    always @(posedge clk) begin
        if (!rst_n) begin
            for (bi = 0; bi < 2; bi = bi + 1) begin
                hdr_magic[bi]        <= LUT6_MAGIC_LE;
                hdr_conf_mask[bi]    <= 64'h0000_0000_0000_FF00;
                hdr_conf_thresh[bi]  <= 16'd6;
                hdr_num_layers[bi]   <= 8'd1;
                hdr_gates_layer[bi]  <= 8'd16;
                hdr_kill_max_rej[bi] <= 32'd3;
                for (gi = 0; gi < 64; gi = gi + 1) begin
                    gate_routes_lo[bi][gi] <= 30'd0;
                    gate_routes_hi[bi][gi] <= 6'd0;
                    gate_init_mask[bi][gi] <= 64'd0;
                end
            end
        end else if (shadow_wr_en) begin
            if (shadow_wr_addr == 9'd0) begin
                hdr_magic[shadow] <= shadow_wr_data[31:0];
            end else if (shadow_wr_addr == 9'd4) begin
                hdr_conf_mask[shadow] <= shadow_wr_data;
            end else if (shadow_wr_addr == 9'd6) begin
                hdr_conf_thresh[shadow]  <= shadow_wr_data[15:0];
                hdr_num_layers[shadow]   <= shadow_wr_data[23:16];
                hdr_gates_layer[shadow]  <= shadow_wr_data[31:24];
                hdr_kill_max_rej[shadow] <= shadow_wr_data[63:32];
            end else if ((shadow_wr_addr >= 9'd8) && (shadow_wr_addr < 9'd40)) begin
                // 2 x 32-bit `routes_lo` entries packed per 64-bit word
                gate_routes_lo[shadow][{shadow_wr_addr[4:0] - 5'd8, 1'b0}] <= shadow_wr_data[29:0];
                gate_routes_lo[shadow][{shadow_wr_addr[4:0] - 5'd8, 1'b1}] <= shadow_wr_data[61:32];
            end else if ((shadow_wr_addr >= 9'd136) && (shadow_wr_addr < 9'd144)) begin
                // 8 x 8-bit `routes_hi` entries packed per 64-bit word
                for (gi = 0; gi < 8; gi = gi + 1) begin
                    gate_routes_hi[shadow][{shadow_wr_addr[2:0], 3'd0} + gi[5:0]] <= shadow_wr_data[gi * 8 +: 6];
                end
            end else if ((shadow_wr_addr >= 9'd256) && (shadow_wr_addr < 9'd320)) begin
                gate_init_mask[shadow][shadow_wr_addr[5:0]] <= shadow_wr_data;
            end
        end
    end

    wire [31:0] act_magic        = active_bank ? hdr_magic[1]        : hdr_magic[0];
    wire [63:0] act_conf_mask    = active_bank ? hdr_conf_mask[1]    : hdr_conf_mask[0];
    wire [15:0] act_conf_thresh  = active_bank ? hdr_conf_thresh[1]  : hdr_conf_thresh[0];
    wire [7:0]  act_num_layers   = active_bank ? hdr_num_layers[1]   : hdr_num_layers[0];
    wire [7:0]  act_gates_layer  = active_bank ? hdr_gates_layer[1]  : hdr_gates_layer[0];
    wire [31:0] act_kill_max_rej = active_bank ? hdr_kill_max_rej[1] : hdr_kill_max_rej[0];

    wire act_page_valid = (act_magic == LUT6_MAGIC_LE)
                       && (act_gates_layer <= 8'd64)
                       && (act_num_layers >= 8'd1)
                       && (act_num_layers <= 8'd4);

    // -------------------------------------------------------------------------
    // Stage 1: Parallel 64-Gate x 6-Input Wire Gather (`384` 64:1 muxes)
    // -------------------------------------------------------------------------
    wire [64*6-1:0] gathered_addr_s0;
    genvar g;
    generate
        for (g = 0; g < 64; g = g + 1) begin : gen_wire_gather
            wire [29:0] r_lo = active_bank ? gate_routes_lo[1][g] : gate_routes_lo[0][g];
            wire [5:0]  r_hi = active_bank ? gate_routes_hi[1][g] : gate_routes_hi[0][g];
            wire b0 = state_in[r_lo[5:0]];
            wire b1 = state_in[r_lo[11:6]];
            wire b2 = state_in[r_lo[17:12]];
            wire b3 = state_in[r_lo[23:18]];
            wire b4 = state_in[r_lo[29:24]];
            wire b5 = state_in[r_hi[5:0]];
            assign gathered_addr_s0[g * 6 +: 6] = {b5, b4, b3, b2, b1, b0};
        end
    endgenerate

    reg             s1_valid;
    reg [64*6-1:0]  s1_lut_addr_flat;
    reg [7:0]       s1_gates_layer;
    reg [63:0]      s1_conf_mask;
    reg [15:0]      s1_conf_thresh;
    reg             s1_page_valid;
    reg             s1_bank;

    // -------------------------------------------------------------------------
    // Stage 2: Parallel 64-Gate `LUT6` Truth-Table Evaluation + Conformal Split
    // -------------------------------------------------------------------------
    wire [63:0] raw_lut_out_s1;
    generate
        for (g = 0; g < 64; g = g + 1) begin : gen_lut6_eval
            wire [63:0] mask64 = s1_bank ? gate_init_mask[1][g] : gate_init_mask[0][g];
            wire [5:0]  laddr  = s1_lut_addr_flat[g * 6 +: 6];
            assign raw_lut_out_s1[g] = (g < s1_gates_layer) ? mask64[laddr] : 1'b0;
        end
    endgenerate

    wire [63:0] payload_comb_s1   = raw_lut_out_s1 & ~s1_conf_mask;
    wire [63:0] vote_bits_comb_s1 = raw_lut_out_s1 &  s1_conf_mask;

    reg        s2_valid;
    reg [63:0] s2_payload64;
    reg [63:0] s2_vote_bits64;
    reg [15:0] s2_conf_thresh;
    reg        s2_page_valid;

    // -------------------------------------------------------------------------
    // Stage 3: Zero-DSP Balanced 6-Input `LUT6` Popcount Tree (64 bits -> 7 bits)
    //   Replaces serial 64-add loop with 10x 6-bit + 1x 4-bit leaf compressors!
    // -------------------------------------------------------------------------
    function automatic [2:0] pop6(input [5:0] v);
        begin
            pop6 = {2'd0, v[0]} + {2'd0, v[1]} + {2'd0, v[2]}
                 + {2'd0, v[3]} + {2'd0, v[4]} + {2'd0, v[5]};
        end
    endfunction

    wire [2:0] pc0  = pop6(s2_vote_bits64[5:0]);
    wire [2:0] pc1  = pop6(s2_vote_bits64[11:6]);
    wire [2:0] pc2  = pop6(s2_vote_bits64[17:12]);
    wire [2:0] pc3  = pop6(s2_vote_bits64[23:18]);
    wire [2:0] pc4  = pop6(s2_vote_bits64[29:24]);
    wire [2:0] pc5  = pop6(s2_vote_bits64[35:30]);
    wire [2:0] pc6  = pop6(s2_vote_bits64[41:36]);
    wire [2:0] pc7  = pop6(s2_vote_bits64[47:42]);
    wire [2:0] pc8  = pop6(s2_vote_bits64[53:48]);
    wire [2:0] pc9  = pop6(s2_vote_bits64[59:54]);
    wire [2:0] pc10 = pop6({2'b00, s2_vote_bits64[63:60]});

    wire [3:0] sum_a0 = {1'b0, pc0} + {1'b0, pc1};
    wire [3:0] sum_a1 = {1'b0, pc2} + {1'b0, pc3};
    wire [3:0] sum_a2 = {1'b0, pc4} + {1'b0, pc5};
    wire [3:0] sum_a3 = {1'b0, pc6} + {1'b0, pc7};
    wire [3:0] sum_a4 = {1'b0, pc8} + {1'b0, pc9};

    wire [4:0] sum_b0 = {1'b0, sum_a0} + {1'b0, sum_a1};
    wire [4:0] sum_b1 = {1'b0, sum_a2} + {1'b0, sum_a3};
    wire [4:0] sum_b2 = {1'b0, sum_a4} + {2'b00, pc10};

    wire [5:0] sum_c0 = {1'b0, sum_b0} + {1'b0, sum_b1};
    wire [6:0] votes_total_s2 = {1'b0, sum_c0} + {2'b00, sum_b2};

    wire kill_tripped  = (ledger_rejects >= act_kill_max_rej) || !s2_page_valid;
    wire conf_certified = ({9'd0, votes_total_s2} >= s2_conf_thresh);

    // -------------------------------------------------------------------------
    // Sequential Pipeline Advance & Clock-Enable (`FDRE` `CE`) Gating
    // -------------------------------------------------------------------------
    always @(posedge clk) begin
        if (!rst_n) begin
            s1_valid            <= 1'b0;
            s1_lut_addr_flat    <= {384{1'b0}};
            s1_gates_layer      <= 8'd0;
            s1_conf_mask        <= 64'd0;
            s1_conf_thresh      <= 16'd0;
            s1_page_valid       <= 1'b0;
            s1_bank             <= 1'b0;

            s2_valid            <= 1'b0;
            s2_payload64        <= 64'd0;
            s2_vote_bits64      <= 64'd0;
            s2_conf_thresh      <= 16'd0;
            s2_page_valid       <= 1'b0;

            out_valid           <= 1'b0;
            out_outcome         <= OUTCOME_ACT;
            out_payload64       <= 64'd0;
            out_votes           <= 7'd0;
            irq_conformal_wake  <= 1'b0;
            irq_verifier_killed <= 1'b0;

            ledger_hits         <= 32'd0;
            ledger_escalations  <= 32'd0;
            ledger_rejects      <= 32'd0;
        end else begin
            // Stage 0 -> Stage 1 (`CE`-gated on `eval_valid`)
            s1_valid <= eval_valid;
            if ((ENABLE_CE_GATING == 0) || eval_valid) begin
                s1_lut_addr_flat <= gathered_addr_s0;
                s1_gates_layer   <= act_gates_layer;
                s1_conf_mask     <= act_conf_mask;
                s1_conf_thresh   <= act_conf_thresh;
                s1_page_valid    <= act_page_valid;
                s1_bank          <= active_bank;
            end

            // Stage 1 -> Stage 2 (`CE`-gated on `s1_valid`)
            s2_valid <= s1_valid;
            if ((ENABLE_CE_GATING == 0) || s1_valid) begin
                s2_payload64   <= payload_comb_s1;
                s2_vote_bits64 <= vote_bits_comb_s1;
                s2_conf_thresh <= s1_conf_thresh;
                s2_page_valid  <= s1_page_valid;
            end

            // Stage 2 -> Stage 3 Output & Conformal Wake Gate (`CE`-gated on `s2_valid`)
            out_valid <= s2_valid;
            if ((ENABLE_CE_GATING == 0) || s2_valid) begin
                if (kill_tripped) begin
                    out_outcome   <= OUTCOME_KILLED;
                    out_payload64 <= 64'd0;
                    out_votes     <= 7'd0;
                end else if (conf_certified) begin
                    out_outcome   <= OUTCOME_ACT;
                    out_payload64 <= s2_payload64;
                    out_votes     <= votes_total_s2;
                end else begin
                    out_outcome   <= OUTCOME_ESCALATE;
                    out_payload64 <= s2_payload64;
                    out_votes     <= votes_total_s2;
                end
            end

            // Telemetry & Sticky Interrupt Management
            if (clear_ledger_pulse) begin
                ledger_hits         <= 32'd0;
                ledger_escalations  <= 32'd0;
                ledger_rejects      <= 32'd0;
                irq_conformal_wake  <= 1'b0;
                irq_verifier_killed <= 1'b0;
            end else begin
                if (verifier_reject_pulse) begin
                    ledger_rejects <= ledger_rejects + 32'd1;
                    if ((ledger_rejects + 32'd1) >= act_kill_max_rej)
                        irq_verifier_killed <= 1'b1;
                end
                if (s2_valid) begin
                    if (kill_tripped) begin
                        irq_verifier_killed <= 1'b1;
                    end else if (conf_certified) begin
                        ledger_hits <= ledger_hits + 32'd1;
                    end else begin
                        ledger_escalations <= ledger_escalations + 32'd1;
                        irq_conformal_wake <= 1'b1;
                    end
                end
            end
        end
    end

endmodule
