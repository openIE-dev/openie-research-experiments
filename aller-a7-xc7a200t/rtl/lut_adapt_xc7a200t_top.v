`timescale 1ns/1ps
// =============================================================================
// File   : lut_adapt_xc7a200t_top.v
// Target : Numato Aller A7 M.2 2280 M-Key (`XC7A200T-2FBG484C`, `TARGET_FAMILY=0`)
//          & Cross-Target Equivalence Wrapper for `XCK26` / `XCZU9EG` (`TARGET_FAMILY=1`)
// Summary:
//   Complete zero-DSP (`DSP48E1 = 0`), DDR3-disabled pure-BRAM + `LUT6` gateware
//   port of `LUT-Adapt` onto Xilinx 7-Series Artix-7 `XC7A200T-2FBG484C`:
//     1. `clai_benes_512_stages_0_12_xc7` & `clai_benes_512_stages_13_16_xc7`:
//        4-stage balanced 512x512 Waksman/Beneš-Copy-Beneš router (`II=1`, `CPI=1.00`).
//     2. `ramb36e1_lut_page_cache_81`: Explicit `81 x RAMB36E1` (`TARGET_FAMILY=0`)
//        or `81 x RAMB36E2` (`TARGET_FAMILY=1`) Galois-XOR hash-indexed `512`-page
//        `LUT6 INIT` cache with `ENARDEN` read clock-enable gating.
//     3. `clai_benes_axi_stream_xc7_top`: Standalone retargeted `KV260` `P4-AXIS`
//        core for direct 1:1 `xc7` vs `xcup` primitive comparison.
//     4. `lut_adapt_xc7a200t_top`: Unified M.2 endpoint subsystem integrating BOTH
//        the `81-RAMB36E1` Beneš speculative core AND `compact_lut6_page_engine`
//        (`2 x RAMB36E1` canonical `4 KB` `CompactLut6Page` + conformal wake gate
//        = `83 x RAMB36E1` total = `22.74%` of `XC7A200T`'s `365` BRAMs, leaving
//        `282` BRAMs free for resident `4 KB` crystals!), with explicit DDR3 CMOS
//        reset / power-down tie-offs (`DDR3_RESET# = 0`, `DDR3_CKE = 0`).
//     5. `ramb36e1_crystal_vault_365`: Structural capacity proof instantiating all
//        `365 x RAMB36E1` blocks (`365 x 4,096 B = 1,460 KB` usable data / `1,642.5 KB`
//        raw parity-inclusive BRAM) on `XC7A200T-2FBG484C` with zero DDR3 PHY.
// =============================================================================

module clai_benes_512_stages_0_12_xc7 (
    input  wire [511:0]      in_wires,
    input  wire [13*256-1:0] sw_flat_0_12,
    output wire [511:0]      mid_wires
);
    wire [511:0] st_wires [0:13];
    assign st_wires[0] = in_wires;

    genvar d, blk, k;
    generate
        for (d = 0; d < 8; d = d + 1) begin : gen_fwd_stage
            localparam integer NUM_BLOCKS = (1 << d);
            localparam integer SUB_N      = (512 >> d);
            localparam integer SUB_HALF   = (SUB_N >> 1);
            for (blk = 0; blk < NUM_BLOCKS; blk = blk + 1) begin : gen_fwd_blk
                localparam integer W_BASE  = blk * SUB_N;
                localparam integer SW_BASE = d * 256 + blk * SUB_HALF;
                for (k = 0; k < SUB_HALF; k = k + 1) begin : gen_fwd_sw
                    wire s  = sw_flat_0_12[SW_BASE + k];
                    wire x0 = st_wires[d][W_BASE + 2 * k];
                    wire x1 = st_wires[d][W_BASE + 2 * k + 1];
                    assign st_wires[d + 1][W_BASE + k]            = s ? x1 : x0;
                    assign st_wires[d + 1][W_BASE + SUB_HALF + k] = s ? x0 : x1;
                end
            end
        end

        for (blk = 0; blk < 256; blk = blk + 1) begin : gen_center_sw
            wire sc = sw_flat_0_12[8 * 256 + blk];
            wire c0 = st_wires[8][2 * blk];
            wire c1 = st_wires[8][2 * blk + 1];
            assign st_wires[9][2 * blk]     = sc ? c1 : c0;
            assign st_wires[9][2 * blk + 1] = sc ? c0 : c1;
        end

        for (d = 4; d < 8; d = d + 1) begin : gen_rev_hi
            localparam integer ST_IDX     = 16 - d;
            localparam integer NUM_BLOCKS = (1 << d);
            localparam integer SUB_N      = (512 >> d);
            localparam integer SUB_HALF   = (SUB_N >> 1);
            for (blk = 0; blk < NUM_BLOCKS; blk = blk + 1) begin : gen_rev_blk_hi
                localparam integer W_BASE  = blk * SUB_N;
                localparam integer SW_BASE = ST_IDX * 256 + blk * SUB_HALF;
                for (k = 0; k < SUB_HALF; k = k + 1) begin : gen_rev_sw_hi
                    wire sr = sw_flat_0_12[SW_BASE + k];
                    wire b0 = st_wires[ST_IDX][W_BASE + k];
                    wire b1 = st_wires[ST_IDX][W_BASE + SUB_HALF + k];
                    assign st_wires[ST_IDX + 1][W_BASE + 2 * k]     = sr ? b1 : b0;
                    assign st_wires[ST_IDX + 1][W_BASE + 2 * k + 1] = sr ? b0 : b1;
                end
            end
        end
    endgenerate

    assign mid_wires = st_wires[13];
endmodule


module clai_benes_512_stages_13_16_xc7 (
    input  wire [511:0]     mid_wires,
    input  wire [4*256-1:0] sw_flat_13_16,
    output wire [511:0]     out_wires
);
    wire [511:0] st_wires [13:17];
    assign st_wires[13] = mid_wires;

    genvar d, blk, k;
    generate
        for (d = 0; d < 4; d = d + 1) begin : gen_rev_lo
            localparam integer ST_IDX     = 16 - d;
            localparam integer LOCAL_IDX  = ST_IDX - 13;
            localparam integer NUM_BLOCKS = (1 << d);
            localparam integer SUB_N      = (512 >> d);
            localparam integer SUB_HALF   = (SUB_N >> 1);
            for (blk = 0; blk < NUM_BLOCKS; blk = blk + 1) begin : gen_rev_blk_lo
                localparam integer W_BASE  = blk * SUB_N;
                localparam integer SW_BASE = LOCAL_IDX * 256 + blk * SUB_HALF;
                for (k = 0; k < SUB_HALF; k = k + 1) begin : gen_rev_sw_lo
                    wire sr = sw_flat_13_16[SW_BASE + k];
                    wire b0 = st_wires[ST_IDX][W_BASE + k];
                    wire b1 = st_wires[ST_IDX][W_BASE + SUB_HALF + k];
                    assign st_wires[ST_IDX + 1][W_BASE + 2 * k]     = sr ? b1 : b0;
                    assign st_wires[ST_IDX + 1][W_BASE + 2 * k + 1] = sr ? b0 : b1;
                end
            end
        end
    endgenerate

    assign out_wires = st_wires[17];
endmodule


// =============================================================================
// Module: ramb36e1_lut_page_cache_81
//   Retargets `clai_uram_lut6_page_cache_ce` onto 81 explicit structural
//   `RAMB36E1` (`TARGET_FAMILY=0`) or `RAMB36E2` (`TARGET_FAMILY=1`) blocks
//   (`1` 512-entry Tag BRAM + `80` parallel 512x64 `LUT6 INIT` BRAMs) with
//   `ENARDEN` gated strictly on `lookup_rd_en`.
// =============================================================================
module ramb36e1_lut_page_cache_81 #(
    parameter integer TARGET_FAMILY  = 0,
    parameter integer PAGE_ADDR_BITS = 9
) (
    input  wire                      clk,
    input  wire                      lookup_rd_en,
    input  wire [1:0]                lookup_lang_id,
    input  wire [47:0]               lookup_ctx6,
    output wire [PAGE_ADDR_BITS-1:0] lookup_hash_dbg,

    input  wire                      page_prog_we,
    input  wire                      page_prog_is_tag,
    input  wire [PAGE_ADDR_BITS-1:0] page_prog_addr,
    input  wire [6:0]                page_prog_lut_idx,
    input  wire [63:0]               page_prog_data64,

    output wire [63:0]               rd_tag64,
    output wire [80*64-1:0]          rd_luts_flat
);
    wire [15:0] f0    = lookup_ctx6[15:0]  ^ {lookup_ctx6[7:0],   lookup_ctx6[15:8]};
    wire [15:0] f1    = lookup_ctx6[31:16] ^ {lookup_ctx6[20:16], lookup_ctx6[31:21]};
    wire [15:0] f2    = lookup_ctx6[47:32] ^ {lookup_ctx6[38:32], lookup_ctx6[47:39]};
    wire [15:0] mix_a = f0 ^ {f1[12:0], f1[15:13]} ^ {f2[8:0], f2[15:9]};
    wire [15:0] mix_b = mix_a ^ {5'd0, mix_a[15:5]} ^ ({14'd0, lookup_lang_id} << 9)
                        ^ {6'd0, lookup_lang_id, lookup_ctx6[47:40]};
    wire [PAGE_ADDR_BITS-1:0] lookup_hash = mix_b[PAGE_ADDR_BITS-1:0];
    assign lookup_hash_dbg = lookup_hash;

    wire [8:0] rd_addr9 = lookup_hash[8:0];
    wire [8:0] wr_addr9 = page_prog_addr[8:0];
    wire       unused_tag_perr;

    xilinx_sdp_bram36_wrapper #(
        .TARGET_FAMILY(TARGET_FAMILY)
    ) u_tag_bram (
        .clk           (clk),
        .srst          (1'b0),
        .rd_en         (lookup_rd_en),
        .rd_addr       (rd_addr9),
        .rd_data       (rd_tag64),
        .rd_parity_err (unused_tag_perr),
        .wr_en         (page_prog_we && page_prog_is_tag),
        .wr_addr       (wr_addr9),
        .wr_data       (page_prog_data64)
    );

    genvar gi;
    generate
        for (gi = 0; gi < 80; gi = gi + 1) begin : gen_lut_bram80
            wire unused_lut_perr;
            xilinx_sdp_bram36_wrapper #(
                .TARGET_FAMILY(TARGET_FAMILY)
            ) u_lut_bram (
                .clk           (clk),
                .srst          (1'b0),
                .rd_en         (lookup_rd_en),
                .rd_addr       (rd_addr9),
                .rd_data       (rd_luts_flat[gi * 64 +: 64]),
                .rd_parity_err (unused_lut_perr),
                .wr_en         (page_prog_we && !page_prog_is_tag && (page_prog_lut_idx == gi[6:0])),
                .wr_addr       (wr_addr9),
                .wr_data       (page_prog_data64)
            );
        end
    endgenerate
endmodule


// =============================================================================
// Module: clai_benes_paged_pipelined_portable
//   4-Stage Balanced Pipelined (`II=1`, `CPI=1.00`) 512x512 Beneš-Copy-Beneš +
//   `81-RAMB36E1`/`RAMB36E2` Speculative Core with `FDRE` & `ENARDEN` CE gating.
// =============================================================================
module clai_benes_paged_pipelined_portable #(
    parameter integer TARGET_FAMILY    = 0,
    parameter integer PAGE_ADDR_BITS   = 9,
    parameter integer ENABLE_CE_GATING = 1
) (
    input  wire                      clk,
    input  wire                      rst_n,
    input  wire [511:0]              bus_in,
    input  wire                      bus_valid,
    input  wire [1:0]                ctx_lang_id,
    input  wire                      page_cache_en,

    input  wire                      cfg_we,
    input  wire [1:0]                cfg_kind,
    input  wire [6:0]                cfg_idx,
    input  wire [255:0]              cfg_vec256,
    input  wire [511:0]              cfg_vec512,
    input  wire                      atomic_swap_pulse,

    input  wire                      page_prog_we,
    input  wire                      page_prog_is_tag,
    input  wire [PAGE_ADDR_BITS-1:0] page_prog_addr,
    input  wire [6:0]                page_prog_lut_idx,
    input  wire [63:0]               page_prog_data64,

    output reg                       active_bank,
    output reg                       out_valid,
    output reg                       page_hit_out,
    output reg  [PAGE_ADDR_BITS-1:0] page_slot_out,
    output reg  [79:0]               l0_out_debug,
    output reg  [15:0]               draft_word16_out,
    output reg  [15:0]               draft_unanimous16_out,
    output reg  [31:0]               telemetry_lookups,
    output reg  [31:0]               telemetry_page_hits,
    output reg  [31:0]               telemetry_cam_fallbacks
);
    reg [255:0] b1_sw   [0:1][0:16];
    reg [511:0] copy_en [0:1][0:8];
    reg [255:0] b2_sw   [0:1][0:16];
    reg [63:0]  l0_lut  [0:1][0:79];

    wire shadow = ~active_bank;

    wire [17*256-1:0] act_b1_flat;
    wire [17*256-1:0] act_b2_flat;
    wire [80*64-1:0]  act_fallback_flat;
    genvar gs;
    generate
        for (gs = 0; gs < 17; gs = gs + 1) begin : gen_pack_sw
            assign act_b1_flat[gs * 256 +: 256] = active_bank ? b1_sw[1][gs] : b1_sw[0][gs];
            assign act_b2_flat[gs * 256 +: 256] = active_bank ? b2_sw[1][gs] : b2_sw[0][gs];
        end
        for (gs = 0; gs < 80; gs = gs + 1) begin : gen_pack_fb
            assign act_fallback_flat[gs * 64 +: 64] = active_bank ? l0_lut[1][gs] : l0_lut[0][gs];
        end
    endgenerate

    wire [PAGE_ADDR_BITS-1:0] lookup_hash_s0;
    wire [63:0]               rd_tag64_s1;
    wire [80*64-1:0]          rd_luts_flat_s1;
    wire                      bram_rd_en_s0 = (ENABLE_CE_GATING != 0) ? (bus_valid && page_cache_en) : 1'b1;

    ramb36e1_lut_page_cache_81 #(
        .TARGET_FAMILY (TARGET_FAMILY),
        .PAGE_ADDR_BITS(PAGE_ADDR_BITS)
    ) u_page_cache (
        .clk               (clk),
        .lookup_rd_en      (bram_rd_en_s0),
        .lookup_lang_id    (ctx_lang_id),
        .lookup_ctx6       (bus_in[127:80]),
        .lookup_hash_dbg   (lookup_hash_s0),
        .page_prog_we      (page_prog_we),
        .page_prog_is_tag  (page_prog_is_tag),
        .page_prog_addr    (page_prog_addr),
        .page_prog_lut_idx (page_prog_lut_idx),
        .page_prog_data64  (page_prog_data64),
        .rd_tag64          (rd_tag64_s1),
        .rd_luts_flat      (rd_luts_flat_s1)
    );

    wire [511:0] b1_mid_s0;
    clai_benes_512_stages_0_12_xc7 u_b1_hi (
        .in_wires     (bus_in),
        .sw_flat_0_12 (act_b1_flat[13*256-1:0]),
        .mid_wires    (b1_mid_s0)
    );

    reg                      s1_valid;
    reg                      s1_cache_en;
    reg [50:0]               s1_tag_exp;
    reg [PAGE_ADDR_BITS-1:0] s1_slot;
    reg [511:0]              s1_b1_mid;

    wire [511:0] b1_out_s1;
    clai_benes_512_stages_13_16_xc7 u_b1_lo (
        .mid_wires     (s1_b1_mid),
        .sw_flat_13_16 (act_b1_flat[17*256-1:13*256]),
        .out_wires     (b1_out_s1)
    );

    wire [511:0] cp_stage_s1 [0:9];
    assign cp_stage_s1[0] = b1_out_s1;
    genvar cd, ci;
    generate
        for (cd = 0; cd < 9; cd = cd + 1) begin : gen_copy_s1
            localparam integer STRIDE = (1 << cd);
            wire [511:0] en_vec = active_bank ? copy_en[1][cd] : copy_en[0][cd];
            for (ci = 0; ci < 512; ci = ci + 1) begin : gen_copy_mux_s1
                if (ci < STRIDE) begin : gen_keep_low
                    assign cp_stage_s1[cd + 1][ci] = cp_stage_s1[cd][ci];
                end else begin : gen_stride_mux
                    assign cp_stage_s1[cd + 1][ci] = en_vec[ci] ? cp_stage_s1[cd][ci - STRIDE] : cp_stage_s1[cd][ci];
                end
            end
        end
    endgenerate

    wire s1_hit = s1_valid && s1_cache_en && (rd_tag64_s1[50:0] == s1_tag_exp);
    wire [80*64-1:0] s1_eff_luts = s1_hit ? rd_luts_flat_s1 : act_fallback_flat;

    reg                      s2_valid;
    reg                      s2_hit;
    reg [PAGE_ADDR_BITS-1:0] s2_slot;
    reg [511:0]              s2_cp_out;
    reg [80*64-1:0]          s2_eff_luts;

    wire [511:0] b2_mid_s2;
    clai_benes_512_stages_0_12_xc7 u_b2_hi (
        .in_wires     (s2_cp_out),
        .sw_flat_0_12 (act_b2_flat[13*256-1:0]),
        .mid_wires    (b2_mid_s2)
    );

    reg                      s3_valid;
    reg                      s3_hit;
    reg [PAGE_ADDR_BITS-1:0] s3_slot;
    reg [511:0]              s3_b2_mid;
    reg [80*64-1:0]          s3_eff_luts;

    wire [511:0] routed_ports_s3;
    clai_benes_512_stages_13_16_xc7 u_b2_lo (
        .mid_wires     (s3_b2_mid),
        .sw_flat_13_16 (act_b2_flat[17*256-1:13*256]),
        .out_wires     (routed_ports_s3)
    );

    wire [79:0] l0_comb_s3;
    genvar gl;
    generate
        for (gl = 0; gl < 80; gl = gl + 1) begin : gen_lut80_s3
            wire [63:0] t64  = s3_eff_luts[gl * 64 +: 64];
            wire [5:0]  addr = routed_ports_s3[gl * 6 +: 6];
            assign l0_comb_s3[gl] = t64[addr];
        end
    endgenerate

    wire [15:0] draft_w16_comb;
    wire [15:0] draft_u16_comb;
    genvar gb;
    generate
        for (gb = 0; gb < 16; gb = gb + 1) begin : gen_voter5_s3
            wire [2:0] v_sum = {2'd0, l0_comb_s3[gb * 5 + 0]}
                             + {2'd0, l0_comb_s3[gb * 5 + 1]}
                             + {2'd0, l0_comb_s3[gb * 5 + 2]}
                             + {2'd0, l0_comb_s3[gb * 5 + 3]}
                             + {2'd0, l0_comb_s3[gb * 5 + 4]};
            assign draft_w16_comb[gb] = (v_sum >= 3'd3);
            assign draft_u16_comb[gb] = (v_sum == 3'd5) || (v_sum == 3'd0);
        end
    endgenerate

    integer b, s;
    always @(posedge clk) begin
        if (!rst_n) begin
            active_bank             <= 1'b0;
            s1_valid                <= 1'b0;
            s1_cache_en             <= 1'b0;
            s1_tag_exp              <= 51'd0;
            s1_slot                 <= {PAGE_ADDR_BITS{1'b0}};
            s1_b1_mid               <= 512'd0;
            s2_valid                <= 1'b0;
            s2_hit                  <= 1'b0;
            s2_slot                 <= {PAGE_ADDR_BITS{1'b0}};
            s2_cp_out               <= 512'd0;
            s2_eff_luts             <= {5120{1'b0}};
            s3_valid                <= 1'b0;
            s3_hit                  <= 1'b0;
            s3_slot                 <= {PAGE_ADDR_BITS{1'b0}};
            s3_b2_mid               <= 512'd0;
            s3_eff_luts             <= {5120{1'b0}};
            out_valid               <= 1'b0;
            page_hit_out            <= 1'b0;
            page_slot_out           <= {PAGE_ADDR_BITS{1'b0}};
            l0_out_debug            <= 80'd0;
            draft_word16_out        <= 16'd0;
            draft_unanimous16_out   <= 16'd0;
            telemetry_lookups       <= 32'd0;
            telemetry_page_hits     <= 32'd0;
            telemetry_cam_fallbacks <= 32'd0;
            for (b = 0; b < 2; b = b + 1) begin
                for (s = 0; s < 17; s = s + 1) begin
                    b1_sw[b][s] <= 256'd0;
                    b2_sw[b][s] <= 256'd0;
                end
                for (s = 0; s < 9; s = s + 1)
                    copy_en[b][s] <= 512'd0;
                for (s = 0; s < 80; s = s + 1)
                    l0_lut[b][s] <= 64'd0;
            end
        end else begin
            if (cfg_we) begin
                case (cfg_kind)
                    2'd0: if (cfg_idx < 7'd17) b1_sw[shadow][cfg_idx[4:0]]   <= cfg_vec256;
                    2'd1: if (cfg_idx < 7'd9)  copy_en[shadow][cfg_idx[3:0]] <= cfg_vec512;
                    2'd2: if (cfg_idx < 7'd17) b2_sw[shadow][cfg_idx[4:0]]   <= cfg_vec256;
                    2'd3: if (cfg_idx < 7'd80) l0_lut[shadow][cfg_idx]       <= cfg_vec256[63:0];
                endcase
            end
            if (atomic_swap_pulse)
                active_bank <= ~active_bank;

            s1_valid <= bus_valid;
            if ((ENABLE_CE_GATING == 0) || bus_valid) begin
                s1_cache_en <= page_cache_en;
                s1_tag_exp  <= {1'b1, ctx_lang_id, bus_in[127:80]};
                s1_slot     <= lookup_hash_s0;
                s1_b1_mid   <= b1_mid_s0;
            end

            s2_valid <= s1_valid;
            if ((ENABLE_CE_GATING == 0) || s1_valid) begin
                s2_hit      <= s1_hit;
                s2_slot     <= s1_slot;
                s2_cp_out   <= cp_stage_s1[9];
                s2_eff_luts <= s1_eff_luts;
            end

            s3_valid <= s2_valid;
            if ((ENABLE_CE_GATING == 0) || s2_valid) begin
                s3_hit      <= s2_hit;
                s3_slot     <= s2_slot;
                s3_b2_mid   <= b2_mid_s2;
                s3_eff_luts <= s2_eff_luts;
            end

            out_valid <= s3_valid;
            if ((ENABLE_CE_GATING == 0) || s3_valid) begin
                page_hit_out          <= s3_hit;
                page_slot_out         <= s3_slot;
                l0_out_debug          <= l0_comb_s3;
                draft_word16_out      <= draft_w16_comb;
                draft_unanimous16_out <= draft_u16_comb;
            end

            if (s3_valid) begin
                telemetry_lookups <= telemetry_lookups + 32'd1;
                if (s3_hit)
                    telemetry_page_hits <= telemetry_page_hits + 32'd1;
                else
                    telemetry_cam_fallbacks <= telemetry_cam_fallbacks + 32'd1;
            end
        end
    end
endmodule


// =============================================================================
// Module: clai_benes_axi_stream_xc7_top
//   Direct 1:1 pin-identical port of `KV260` `clai_benes_axi_stream_250mhz_top`
//   onto `RAMB36E1` (`TARGET_FAMILY=0`) vs `RAMB36E2` (`TARGET_FAMILY=1`).
// =============================================================================
module clai_benes_axi_stream_xc7_top #(
    parameter integer TARGET_FAMILY    = 0,
    parameter integer PAGE_ADDR_BITS   = 9,
    parameter integer ENABLE_CE_GATING = 1
) (
    input  wire        clk,
    input  wire        rst_n,
    input  wire [63:0] s_axis_tdata,
    input  wire [1:0]  s_axis_tuser_lang,
    input  wire        s_axis_tvalid,
    input  wire        s_axis_tlast,
    output wire        s_axis_tready,

    input  wire        csr_we,
    input  wire [5:0]  csr_cmd,
    input  wire [15:0] csr_addr,
    input  wire [31:0] csr_wdata,

    output wire        m_axis_tvalid,
    output wire        m_axis_page_hit,
    output wire [8:0]  m_axis_page_slot,
    output wire [15:0] m_axis_draft_word16,
    output wire [15:0] m_axis_draft_unanimous16
);
    assign s_axis_tready = 1'b1;

    reg [511:0] bus_shift_reg;
    reg [511:0] cfg_shift512;
    reg         fire_lookup;
    reg [1:0]   lang_reg;
    reg         cache_en_reg;

    reg                      cfg_we_r;
    reg [1:0]                cfg_kind_r;
    reg [6:0]                cfg_idx_r;
    reg                      swap_r;
    reg                      p_we_r;
    reg                      p_is_tag_r;
    reg [PAGE_ADDR_BITS-1:0] p_addr_r;
    reg [6:0]                p_lut_r;

    always @(posedge clk) begin
        if (!rst_n) begin
            bus_shift_reg <= 512'd0;
            cfg_shift512  <= 512'd0;
            fire_lookup   <= 1'b0;
            lang_reg      <= 2'd0;
            cache_en_reg  <= 1'b1;
            cfg_we_r      <= 1'b0;
            cfg_kind_r    <= 2'd0;
            cfg_idx_r     <= 7'd0;
            swap_r        <= 1'b0;
            p_we_r        <= 1'b0;
            p_is_tag_r    <= 1'b0;
            p_addr_r      <= {PAGE_ADDR_BITS{1'b0}};
            p_lut_r       <= 7'd0;
        end else begin
            fire_lookup <= s_axis_tvalid && s_axis_tlast;
            if (s_axis_tvalid) begin
                bus_shift_reg <= {s_axis_tdata, bus_shift_reg[511:64]};
                lang_reg      <= s_axis_tuser_lang;
            end

            cfg_we_r <= 1'b0;
            swap_r   <= 1'b0;
            p_we_r   <= 1'b0;
            if (csr_we) begin
                case (csr_cmd[2:0])
                    3'd0: cfg_shift512 <= {csr_wdata, cfg_shift512[511:32]};
                    3'd1: begin
                        cfg_we_r   <= 1'b1;
                        cfg_kind_r <= csr_cmd[4:3];
                        cfg_idx_r  <= csr_addr[6:0];
                    end
                    3'd2: begin
                        p_we_r     <= 1'b1;
                        p_is_tag_r <= csr_cmd[3];
                        p_addr_r   <= csr_addr[PAGE_ADDR_BITS-1:0];
                        p_lut_r    <= csr_addr[15:9];
                    end
                    3'd3: swap_r       <= 1'b1;
                    3'd4: cache_en_reg <= csr_wdata[0];
                    default: ;
                endcase
            end
        end
    end

    wire        unused_bank;
    wire [79:0] unused_l0;
    wire [31:0] unused_t0, unused_t1, unused_t2;

    clai_benes_paged_pipelined_portable #(
        .TARGET_FAMILY   (TARGET_FAMILY),
        .PAGE_ADDR_BITS  (PAGE_ADDR_BITS),
        .ENABLE_CE_GATING(ENABLE_CE_GATING)
    ) u_pipelined_core (
        .clk                    (clk),
        .rst_n                  (rst_n),
        .bus_in                 (bus_shift_reg),
        .bus_valid              (fire_lookup),
        .ctx_lang_id            (lang_reg),
        .page_cache_en          (cache_en_reg),
        .cfg_we                 (cfg_we_r),
        .cfg_kind               (cfg_kind_r),
        .cfg_idx                (cfg_idx_r),
        .cfg_vec256             (cfg_shift512[255:0]),
        .cfg_vec512             (cfg_shift512),
        .atomic_swap_pulse      (swap_r),
        .page_prog_we           (p_we_r),
        .page_prog_is_tag       (p_is_tag_r),
        .page_prog_addr         (p_addr_r),
        .page_prog_lut_idx      (p_lut_r),
        .page_prog_data64       (cfg_shift512[63:0]),
        .active_bank            (unused_bank),
        .out_valid              (m_axis_tvalid),
        .page_hit_out           (m_axis_page_hit),
        .page_slot_out          (m_axis_page_slot),
        .l0_out_debug           (unused_l0),
        .draft_word16_out       (m_axis_draft_word16),
        .draft_unanimous16_out  (m_axis_draft_unanimous16),
        .telemetry_lookups      (unused_t0),
        .telemetry_page_hits    (unused_t1),
        .telemetry_cam_fallbacks(unused_t2)
    );
endmodule


// =============================================================================
// Module: lut_adapt_xc7a200t_top
//   Complete Numato Aller A7 (`XC7A200T-2FBG484C`) M.2 2280 Gateware Top-Level:
//     - Integrates `81-RAMB36E1` Beneš-Copy-Beneš Speculative Core + `2-RAMB36E1`
//       `CompactLut6Page` Conformal Evaluator (`83 x RAMB36E1` total, `0` DSPs).
//     - Holds DDR3 SDRAM (`MT41J128M16`) disabled in CMOS reset (`CKE=0`, `RST#=0`).
//     - `s_axis_tuser_mode`:
//         `2'd0` = 512-bit Beneš stream beat (fires Beneš lookup on `s_axis_tlast`)
//         `2'd1` = 64-wire `CompactLut6Page` fast-path lookup (`CPI = 1.00`)
//         `2'd2` = Dual-engine simultaneous evaluation
// =============================================================================
module lut_adapt_xc7a200t_top #(
    parameter integer TARGET_FAMILY    = 0,
    parameter integer PAGE_ADDR_BITS   = 9,
    parameter integer ENABLE_CE_GATING = 1
) (
    input  wire        clk,
    input  wire        rst_n,

    // PCIe / AXI4-Stream 64-Bit Lookup Ingest
    input  wire [63:0] s_axis_tdata,
    input  wire [1:0]  s_axis_tuser_lang,
    input  wire [1:0]  s_axis_tuser_mode,
    input  wire        s_axis_tvalid,
    input  wire        s_axis_tlast,
    output wire        s_axis_tready,

    // PCIe BAR0 Serialized Control / Shadow-Bank DMA Port
    input  wire        csr_we,
    input  wire [5:0]  csr_cmd,
    input  wire [15:0] csr_addr,
    input  wire [31:0] csr_wdata,
    output reg  [31:0] csr_rdata,

    // Beneš-Copy-Beneš 81-RAMB36E1 Speculative Stream Outputs
    output wire        m_axis_tvalid,
    output wire        m_axis_page_hit,
    output wire [8:0]  m_axis_page_slot,
    output wire [15:0] m_axis_draft_word16,
    output wire [15:0] m_axis_draft_unanimous16,

    // `CompactLut6Page` 64-Wire + Conformal Wake-Gate Outputs
    output wire        cl6_out_valid,
    output wire [1:0]  cl6_outcome,
    output wire [63:0] cl6_payload64,
    output wire [6:0]  cl6_votes,
    output wire        irq_conformal_wake,
    output wire        irq_verifier_killed,

    // Explicit DDR3 Cold-Rail Tie-Offs (0 MIG PHY / 0 SSTL15 ODT instantiated)
    output wire        ddr3_reset_n_tieoff,
    output wire        ddr3_cke_tieoff,
    output wire        ddr3_odt_tieoff,
    output wire        ddr3_cs_n_tieoff
);
    // Hold external Micron MT41J128M16 DDR3 in deep CMOS reset (< 5 mW, 0 FPGA PHY mW)
    assign ddr3_reset_n_tieoff = 1'b0;
    assign ddr3_cke_tieoff     = 1'b0;
    assign ddr3_odt_tieoff     = 1'b0;
    assign ddr3_cs_n_tieoff    = 1'b1;

    wire benes_stream_en = (s_axis_tuser_mode == 2'd0) || (s_axis_tuser_mode == 2'd2);
    wire cl6_eval_en     = s_axis_tvalid && ((s_axis_tuser_mode == 2'd1) || (s_axis_tuser_mode == 2'd2));

    clai_benes_axi_stream_xc7_top #(
        .TARGET_FAMILY   (TARGET_FAMILY),
        .PAGE_ADDR_BITS  (PAGE_ADDR_BITS),
        .ENABLE_CE_GATING(ENABLE_CE_GATING)
    ) u_benes_subsys (
        .clk                     (clk),
        .rst_n                   (rst_n),
        .s_axis_tdata            (s_axis_tdata),
        .s_axis_tuser_lang       (s_axis_tuser_lang),
        .s_axis_tvalid           (s_axis_tvalid && benes_stream_en),
        .s_axis_tlast            (s_axis_tlast),
        .s_axis_tready           (s_axis_tready),
        .csr_we                  (csr_we && (csr_cmd[2:0] <= 3'd4)),
        .csr_cmd                 (csr_cmd),
        .csr_addr                (csr_addr),
        .csr_wdata               (csr_wdata),
        .m_axis_tvalid           (m_axis_tvalid),
        .m_axis_page_hit         (m_axis_page_hit),
        .m_axis_page_slot        (m_axis_page_slot),
        .m_axis_draft_word16     (m_axis_draft_word16),
        .m_axis_draft_unanimous16(m_axis_draft_unanimous16)
    );

    // Shadow-page staging & control registers for `CompactLut6Page`
    reg [31:0] cl6_stage_lo32;
    reg        cl6_wr_en_r;
    reg [8:0]  cl6_wr_addr_r;
    reg [63:0] cl6_wr_data_r;
    reg        cl6_swap_r;
    reg        cl6_reject_r;
    reg        cl6_clear_r;
    reg        cl6_rd_en_r;
    reg [8:0]  cl6_rd_addr_r;
    reg [2:0]  cl6_rdata_sel_r;

    reg [63:0] cl6_state_reg;
    reg        cl6_eval_valid_r;

    always @(posedge clk) begin
        if (!rst_n) begin
            cl6_stage_lo32   <= 32'd0;
            cl6_wr_en_r      <= 1'b0;
            cl6_wr_addr_r    <= 9'd0;
            cl6_wr_data_r    <= 64'd0;
            cl6_swap_r       <= 1'b0;
            cl6_reject_r     <= 1'b0;
            cl6_clear_r      <= 1'b0;
            cl6_rd_en_r      <= 1'b0;
            cl6_rd_addr_r    <= 9'd0;
            cl6_rdata_sel_r  <= 3'd0;
            cl6_state_reg    <= 64'd0;
            cl6_eval_valid_r <= 1'b0;
        end else begin
            cl6_eval_valid_r <= cl6_eval_en;
            if ((ENABLE_CE_GATING == 0) || cl6_eval_en)
                cl6_state_reg <= s_axis_tdata;

            cl6_wr_en_r  <= 1'b0;
            cl6_swap_r   <= 1'b0;
            cl6_reject_r <= 1'b0;
            cl6_clear_r  <= 1'b0;
            cl6_rd_en_r  <= 1'b0;

            if (csr_we) begin
                case (csr_cmd[2:0])
                    3'd5: begin
                        if (!csr_cmd[3]) begin
                            cl6_stage_lo32 <= csr_wdata;
                        end else begin
                            cl6_wr_en_r   <= 1'b1;
                            cl6_wr_addr_r <= csr_addr[8:0];
                            cl6_wr_data_r <= {csr_wdata, cl6_stage_lo32};
                        end
                    end
                    3'd6: begin
                        cl6_swap_r   <= csr_wdata[0];
                        cl6_reject_r <= csr_wdata[1];
                        cl6_clear_r  <= csr_wdata[2];
                    end
                    3'd7: begin
                        cl6_rd_en_r     <= 1'b1;
                        cl6_rd_addr_r   <= csr_addr[8:0];
                        cl6_rdata_sel_r <= csr_cmd[5:3];
                    end
                    default: ;
                endcase
            end
        end
    end

    wire [63:0] cl6_bram_rdata;
    wire        cl6_bram_perr;
    wire        cl6_active_bank;
    wire [31:0] cl6_swap_gen;
    wire [31:0] cl6_hits, cl6_escs, cl6_rejs;

    compact_lut6_page_engine #(
        .TARGET_FAMILY   (TARGET_FAMILY),
        .ENABLE_CE_GATING(ENABLE_CE_GATING)
    ) u_compact_page_engine (
        .clk                  (clk),
        .rst_n                (rst_n),
        .eval_valid           (cl6_eval_valid_r),
        .state_in             (cl6_state_reg),
        .shadow_wr_en         (cl6_wr_en_r),
        .shadow_wr_addr       (cl6_wr_addr_r),
        .shadow_wr_data       (cl6_wr_data_r),
        .atomic_swap_pulse    (cl6_swap_r),
        .verifier_reject_pulse(cl6_reject_r),
        .clear_ledger_pulse   (cl6_clear_r),
        .active_rd_en         (cl6_rd_en_r),
        .active_rd_addr       (cl6_rd_addr_r),
        .active_rd_data       (cl6_bram_rdata),
        .active_rd_parity_err (cl6_bram_perr),
        .active_bank          (cl6_active_bank),
        .swap_generation      (cl6_swap_gen),
        .out_valid            (cl6_out_valid),
        .out_outcome          (cl6_outcome),
        .out_payload64        (cl6_payload64),
        .out_votes            (cl6_votes),
        .irq_conformal_wake   (irq_conformal_wake),
        .irq_verifier_killed  (irq_verifier_killed),
        .ledger_hits          (cl6_hits),
        .ledger_escalations   (cl6_escs),
        .ledger_rejects       (cl6_rejs)
    );

    always @(*) begin
        case (cl6_rdata_sel_r)
            3'd0: csr_rdata = cl6_bram_rdata[31:0];
            3'd1: csr_rdata = cl6_bram_rdata[63:32];
            3'd2: csr_rdata = cl6_hits;
            3'd3: csr_rdata = cl6_escs;
            3'd4: csr_rdata = cl6_rejs;
            default: csr_rdata = {cl6_swap_gen[27:0], cl6_bram_perr, cl6_active_bank, irq_verifier_killed, irq_conformal_wake};
        endcase
    end

endmodule


// =============================================================================
// Module: ramb36e1_crystal_vault_365
//   Structural on-die BRAM capacity proof instantiating `NUM_CRYSTALS = 365`
//   independent `4,096-byte` `CompactLut6Page` `RAMB36E1` banks (`100.00%` of
//   `XC7A200T-2FBG484C`'s `365 x RAMB36E1` = `1,460 KB` data / `1,642.5 KB` raw
//   BRAM) with 1-hot bank clock-enable (`ENARDEN` / `ENBWREN`) gating so at most
//   1 single `RAMB36E1` fires per clock cycle (`~9.8 pJ/cycle` dynamic BRAM
//   read energy across the entire `365`-page knowledge vault, 0 DDR3 PHY!).
// =============================================================================
module ramb36e1_crystal_vault_365 #(
    parameter integer TARGET_FAMILY = 0,
    parameter integer NUM_CRYSTALS  = 365
) (
    input  wire        clk,
    input  wire        srst,
    input  wire        rd_en,
    input  wire [8:0]  rd_crystal_id,
    input  wire [8:0]  rd_word_addr,
    output reg  [63:0] rd_data,
    output reg         rd_parity_err,

    input  wire        wr_en,
    input  wire [8:0]  wr_crystal_id,
    input  wire [8:0]  wr_word_addr,
    input  wire [63:0] wr_data
);
    wire [63:0] bank_dout [0:NUM_CRYSTALS-1];
    wire        bank_perr [0:NUM_CRYSTALS-1];

    reg [8:0] rd_cid_q;
    always @(posedge clk) begin
        if (srst)
            rd_cid_q <= 9'd0;
        else if (rd_en)
            rd_cid_q <= rd_crystal_id;
    end

    genvar c;
    generate
        for (c = 0; c < NUM_CRYSTALS; c = c + 1) begin : gen_crystal_bram
            xilinx_sdp_bram36_wrapper #(
                .TARGET_FAMILY(TARGET_FAMILY)
            ) u_crystal_slot (
                .clk           (clk),
                .srst          (srst),
                .rd_en         (rd_en && (rd_crystal_id == c[8:0])),
                .rd_addr       (rd_word_addr),
                .rd_data       (bank_dout[c]),
                .rd_parity_err (bank_perr[c]),
                .wr_en         (wr_en && (wr_crystal_id == c[8:0])),
                .wr_addr       (wr_word_addr),
                .wr_data       (wr_data)
            );
        end
    endgenerate

    integer m;
    always @(*) begin
        rd_data       = 64'd0;
        rd_parity_err = 1'b0;
        for (m = 0; m < NUM_CRYSTALS; m = m + 1) begin
            if (rd_cid_q == m[8:0]) begin
                rd_data       = bank_dout[m];
                rd_parity_err = bank_perr[m];
            end
        end
    end
endmodule
