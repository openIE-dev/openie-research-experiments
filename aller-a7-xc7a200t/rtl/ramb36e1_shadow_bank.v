`timescale 1ns/1ps
// =============================================================================
// File   : ramb36e1_shadow_bank.v
// Target : Xilinx 7-Series XC7A200T-2FBG484C (Numato Aller A7 M.2 2280, TARGET_FAMILY=0)
//          & Cross-Target Equivalence Model for UltraScale+ XCK26/XCZU9EG (TARGET_FAMILY=1)
// Summary:
//   1. `RAMB36E1` & `RAMB36E2` cycle-accurate 512x72 Simple Dual-Port (SDP)
//      simulation primitives (`ifndef SYNTHESIS`) with synchronous `READ_FIRST`
//      and `ENARDEN` / `ENBWREN` clock-enable gating.
//   2. `xilinx_sdp_bram36_wrapper`: Portable structural wrapper mapping a 4 KB
//      (`512 x 64-bit` + `8-bit` byte-XOR parity = `36 Kb`) page to a single
//      7-Series `RAMB36E1` (`TARGET_FAMILY=0`) or UltraScale+ `RAMB36E2`
//      (`TARGET_FAMILY=1`), with `ENARDEN` strictly gated on `rd_en` (`0` DSPs).
//   3. `ramb36e1_shadow_bank`: Zero-stall Dual-Bank (`Active` / `Shadow` =
//      `2 x RAMB36E1`) 4 KB `CompactLut6Page` store supporting live background
//      PCIe/AXI writes to `~active_bank` and 1-cycle glitch-free `atomic_swap_pulse`.
// =============================================================================

`ifndef SYNTHESIS
`ifndef XILINX_RAMB36_SDP_SIM_MODELS
`define XILINX_RAMB36_SDP_SIM_MODELS

module RAMB36E1 #(
    parameter integer DOA_REG        = 0,
    parameter integer DOB_REG        = 0,
    parameter         RAM_EXTENSION_A = "NONE",
    parameter         RAM_EXTENSION_B = "NONE",
    parameter         RAM_MODE       = "SDP",
    parameter integer READ_WIDTH_A   = 72,
    parameter integer READ_WIDTH_B   = 0,
    parameter integer WRITE_WIDTH_A  = 0,
    parameter integer WRITE_WIDTH_B  = 72,
    parameter         WRITE_MODE_A   = "READ_FIRST",
    parameter         WRITE_MODE_B   = "READ_FIRST",
    parameter [35:0]  INIT_A         = 36'h0,
    parameter [35:0]  INIT_B         = 36'h0,
    parameter [35:0]  SRVAL_A        = 36'h0,
    parameter [35:0]  SRVAL_B        = 36'h0
) (
    output wire        CASCADEOUTA,
    output wire        CASCADEOUTB,
    output reg  [31:0] DOADO,
    output reg  [31:0] DOBDO,
    output reg  [3:0]  DOPADOP,
    output reg  [3:0]  DOPBDOP,
    output wire [7:0]  ECCPARITY,
    output wire [8:0]  RDADDRECC,
    output wire        SBITERR,
    output wire        DBITERR,
    input  wire        ENARDEN,
    input  wire        CLKARDCLK,
    input  wire        RSTRAMARSTRAM,
    input  wire        RSTREGARSTREG,
    input  wire        CASCADEINA,
    input  wire        REGCEAREGCE,
    input  wire        ENBWREN,
    input  wire        CLKBWRCLK,
    input  wire        RSTRAMB,
    input  wire        RSTREGB,
    input  wire        CASCADEINB,
    input  wire        REGCEB,
    input  wire        INJECTDBITERR,
    input  wire        INJECTSBITERR,
    input  wire [15:0] ADDRARDADDR,
    input  wire [15:0] ADDRBWRADDR,
    input  wire [31:0] DIADI,
    input  wire [31:0] DIBDI,
    input  wire [3:0]  DIPADIP,
    input  wire [3:0]  DIPBDIP,
    input  wire [3:0]  WEA,
    input  wire [7:0]  WEBWE
);
    assign CASCADEOUTA = 1'b0;
    assign CASCADEOUTB = 1'b0;
    assign ECCPARITY   = 8'd0;
    assign RDADDRECC   = 9'd0;
    assign SBITERR     = 1'b0;
    assign DBITERR     = 1'b0;

    wire _unused_ok = &{1'b0, RSTREGARSTREG, CASCADEINA, REGCEAREGCE, RSTRAMB, RSTREGB,
                        CASCADEINB, REGCEB, INJECTDBITERR, INJECTSBITERR, WEA,
                        ADDRARDADDR[15], ADDRARDADDR[5:0], ADDRBWRADDR[15], ADDRBWRADDR[5:0],
                        DOA_REG[0], DOB_REG[0], READ_WIDTH_A[0], READ_WIDTH_B[0],
                        WRITE_WIDTH_A[0], WRITE_WIDTH_B[0], INIT_A[0], INIT_B[0], SRVAL_A[0], SRVAL_B[0]};

    reg [63:0] mem_data [0:511];
    reg [7:0]  mem_par  [0:511];

    integer idx;
    initial begin
        DOADO   = 32'd0;
        DOBDO   = 32'd0;
        DOPADOP = 4'd0;
        DOPBDOP = 4'd0;
        for (idx = 0; idx < 512; idx = idx + 1) begin
            mem_data[idx] = 64'd0;
            mem_par[idx]  = 8'd0;
        end
    end

    wire [8:0] raddr9 = ADDRARDADDR[14:6];
    wire [8:0] waddr9 = ADDRBWRADDR[14:6];
    wire [63:0] wdata64 = {DIBDI, DIADI};
    wire [7:0]  wpar8   = {DIPBDIP, DIPADIP};

    // Synchronous READ_FIRST Port A (gated by ENARDEN)
    always @(posedge CLKARDCLK) begin
        if (RSTRAMARSTRAM) begin
            DOADO   <= 32'd0;
            DOBDO   <= 32'd0;
            DOPADOP <= 4'd0;
            DOPBDOP <= 4'd0;
        end else if (ENARDEN) begin
            DOADO   <= mem_data[raddr9][31:0];
            DOBDO   <= mem_data[raddr9][63:32];
            DOPADOP <= mem_par[raddr9][3:0];
            DOPBDOP <= mem_par[raddr9][7:4];
        end
    end

    // Synchronous Byte-Masked Write Port B (gated by ENBWREN & WEBWE)
    integer b;
    always @(posedge CLKBWRCLK) begin
        if (ENBWREN) begin
            for (b = 0; b < 8; b = b + 1) begin
                if (WEBWE[b]) begin
                    mem_data[waddr9][b * 8 +: 8] <= wdata64[b * 8 +: 8];
                    mem_par[waddr9][b]           <= wpar8[b];
                end
            end
        end
    end
endmodule


module RAMB36E2 #(
    parameter integer DOA_REG       = 0,
    parameter integer DOB_REG       = 0,
    parameter integer READ_WIDTH_A  = 72,
    parameter integer READ_WIDTH_B  = 0,
    parameter integer WRITE_WIDTH_A = 0,
    parameter integer WRITE_WIDTH_B = 72,
    parameter         WRITE_MODE_A  = "READ_FIRST",
    parameter         WRITE_MODE_B  = "READ_FIRST",
    parameter [35:0]  INIT_A        = 36'h0,
    parameter [35:0]  INIT_B        = 36'h0,
    parameter [35:0]  SRVAL_A       = 36'h0,
    parameter [35:0]  SRVAL_B       = 36'h0
) (
    output reg  [31:0] DOUTADOUT,
    output reg  [31:0] DOUTBDOUT,
    output reg  [3:0]  DOUTPADOUTP,
    output reg  [3:0]  DOUTPBDOUTP,
    input  wire        CLKARDCLK,
    input  wire        CLKBWRCLK,
    input  wire        ENARDEN,
    input  wire        ENBWREN,
    input  wire        REGCEAREGCE,
    input  wire        REGCEB,
    input  wire        ADDRENA,
    input  wire        ADDRENB,
    input  wire        RSTRAMARSTRAM,
    input  wire        RSTRAMB,
    input  wire        RSTREGARSTREG,
    input  wire        RSTREGB,
    input  wire        SLEEP,
    input  wire [15:0] ADDRARDADDR,
    input  wire [15:0] ADDRBWRADDR,
    input  wire [31:0] DINADIN,
    input  wire [31:0] DINBDIN,
    input  wire [3:0]  DINPADINP,
    input  wire [3:0]  DINPBDINP,
    input  wire [3:0]  WEA,
    input  wire [7:0]  WEBWE
);
    wire _unused_u = &{1'b0, REGCEAREGCE, REGCEB, RSTRAMB, RSTREGARSTREG, RSTREGB, WEA,
                       ADDRARDADDR[15], ADDRARDADDR[5:0], ADDRBWRADDR[15], ADDRBWRADDR[5:0],
                       DOA_REG[0], DOB_REG[0], READ_WIDTH_A[0], READ_WIDTH_B[0],
                       WRITE_WIDTH_A[0], WRITE_WIDTH_B[0], INIT_A[0], INIT_B[0], SRVAL_A[0], SRVAL_B[0]};

    reg [63:0] mem_data [0:511];
    reg [7:0]  mem_par  [0:511];

    integer idx;
    initial begin
        DOUTADOUT   = 32'd0;
        DOUTBDOUT   = 32'd0;
        DOUTPADOUTP = 4'd0;
        DOUTPBDOUTP = 4'd0;
        for (idx = 0; idx < 512; idx = idx + 1) begin
            mem_data[idx] = 64'd0;
            mem_par[idx]  = 8'd0;
        end
    end

    wire [8:0] raddr9 = ADDRARDADDR[14:6];
    wire [8:0] waddr9 = ADDRBWRADDR[14:6];
    wire [63:0] wdata64 = {DINBDIN, DINADIN};
    wire [7:0]  wpar8   = {DINPBDINP, DINPADINP};

    always @(posedge CLKARDCLK) begin
        if (RSTRAMARSTRAM) begin
            DOUTADOUT   <= 32'd0;
            DOUTBDOUT   <= 32'd0;
            DOUTPADOUTP <= 4'd0;
            DOUTPBDOUTP <= 4'd0;
        end else if (ENARDEN && ADDRENA && !SLEEP) begin
            DOUTADOUT   <= mem_data[raddr9][31:0];
            DOUTBDOUT   <= mem_data[raddr9][63:32];
            DOUTPADOUTP <= mem_par[raddr9][3:0];
            DOUTPBDOUTP <= mem_par[raddr9][7:4];
        end
    end

    integer b;
    always @(posedge CLKBWRCLK) begin
        if (ENBWREN && ADDRENB && !SLEEP) begin
            for (b = 0; b < 8; b = b + 1) begin
                if (WEBWE[b]) begin
                    mem_data[waddr9][b * 8 +: 8] <= wdata64[b * 8 +: 8];
                    mem_par[waddr9][b]           <= wpar8[b];
                end
            end
        end
    end
endmodule

`endif
`endif


// =============================================================================
// Module: xilinx_sdp_bram36_wrapper
//   Maps 1 x 36 Kb (512 x 72-bit SDP = 4,096 data bytes + 512 parity bytes)
//   to 7-Series `RAMB36E1` (`TARGET_FAMILY == 0`) or UltraScale+ `RAMB36E2`
//   (`TARGET_FAMILY == 1`), enforcing `ENARDEN` read clock-enable gating.
// =============================================================================
module xilinx_sdp_bram36_wrapper #(
    parameter integer TARGET_FAMILY = 0 // 0 = 7-Series RAMB36E1 (XC7A200T), 1 = UltraScale+ RAMB36E2 (XCK26/XCZU9EG)
) (
    input  wire        clk,
    input  wire        srst,
    input  wire        rd_en,
    input  wire [8:0]  rd_addr,
    output wire [63:0] rd_data,
    output wire        rd_parity_err,
    input  wire        wr_en,
    input  wire [8:0]  wr_addr,
    input  wire [63:0] wr_data
);
    wire [7:0] wr_par = {
        ^wr_data[63:56], ^wr_data[55:48], ^wr_data[47:40], ^wr_data[39:32],
        ^wr_data[31:24], ^wr_data[23:16], ^wr_data[15:8],  ^wr_data[7:0]
    };

    wire [31:0] do_lo;
    wire [31:0] do_hi;
    wire [3:0]  dop_lo;
    wire [3:0]  dop_hi;

    wire [15:0] addr_rd16 = {1'b1, rd_addr, 6'b111111};
    wire [15:0] addr_wr16 = {1'b1, wr_addr, 6'b111111};
    wire [7:0]  web8      = {8{wr_en}};

    generate
        if (TARGET_FAMILY == 0) begin : gen_xc7_ramb36e1
            wire        unused_cas_a, unused_cas_b, unused_sbit, unused_dbit;
            wire [7:0]  unused_eccpar;
            wire [8:0]  unused_rdecc;

            RAMB36E1 #(
                .DOA_REG        (0),
                .DOB_REG        (0),
                .RAM_EXTENSION_A("NONE"),
                .RAM_EXTENSION_B("NONE"),
                .RAM_MODE       ("SDP"),
                .READ_WIDTH_A   (72),
                .READ_WIDTH_B   (0),
                .WRITE_WIDTH_A  (0),
                .WRITE_WIDTH_B  (72),
                .WRITE_MODE_A   ("READ_FIRST"),
                .WRITE_MODE_B   ("READ_FIRST"),
                .INIT_A         (36'h0),
                .INIT_B         (36'h0),
                .SRVAL_A        (36'h0),
                .SRVAL_B        (36'h0)
            ) u_ramb36e1 (
                .CASCADEOUTA   (unused_cas_a),
                .CASCADEOUTB   (unused_cas_b),
                .DOADO         (do_lo),
                .DOBDO         (do_hi),
                .DOPADOP       (dop_lo),
                .DOPBDOP       (dop_hi),
                .ECCPARITY     (unused_eccpar),
                .RDADDRECC     (unused_rdecc),
                .SBITERR       (unused_sbit),
                .DBITERR       (unused_dbit),
                .ENARDEN       (rd_en),
                .CLKARDCLK     (clk),
                .RSTRAMARSTRAM (srst),
                .RSTREGARSTREG (1'b0),
                .CASCADEINA    (1'b0),
                .REGCEAREGCE   (1'b0),
                .ENBWREN       (wr_en),
                .CLKBWRCLK     (clk),
                .RSTRAMB       (1'b0),
                .RSTREGB       (1'b0),
                .CASCADEINB    (1'b0),
                .REGCEB        (1'b0),
                .INJECTDBITERR (1'b0),
                .INJECTSBITERR (1'b0),
                .ADDRARDADDR   (addr_rd16),
                .ADDRBWRADDR   (addr_wr16),
                .DIADI         (wr_data[31:0]),
                .DIBDI         (wr_data[63:32]),
                .DIPADIP       (wr_par[3:0]),
                .DIPBDIP       (wr_par[7:4]),
                .WEA           (4'b0000),
                .WEBWE         (web8)
            );
        end else begin : gen_xcup_ramb36e2
            RAMB36E2 #(
                .DOA_REG       (0),
                .DOB_REG       (0),
                .READ_WIDTH_A  (72),
                .READ_WIDTH_B  (0),
                .WRITE_WIDTH_A (0),
                .WRITE_WIDTH_B (72),
                .WRITE_MODE_A  ("READ_FIRST"),
                .WRITE_MODE_B  ("READ_FIRST"),
                .INIT_A        (36'h0),
                .INIT_B        (36'h0),
                .SRVAL_A       (36'h0),
                .SRVAL_B       (36'h0)
            ) u_ramb36e2 (
                .DOUTADOUT     (do_lo),
                .DOUTBDOUT     (do_hi),
                .DOUTPADOUTP   (dop_lo),
                .DOUTPBDOUTP   (dop_hi),
                .CLKARDCLK     (clk),
                .CLKBWRCLK     (clk),
                .ENARDEN       (rd_en),
                .ENBWREN       (wr_en),
                .REGCEAREGCE   (1'b0),
                .REGCEB        (1'b0),
                .ADDRENA       (1'b1),
                .ADDRENB       (1'b1),
                .RSTRAMARSTRAM (srst),
                .RSTRAMB       (1'b0),
                .RSTREGARSTREG (1'b0),
                .RSTREGB       (1'b0),
                .SLEEP         (1'b0),
                .ADDRARDADDR   (addr_rd16),
                .ADDRBWRADDR   (addr_wr16),
                .DINADIN       (wr_data[31:0]),
                .DINBDIN       (wr_data[63:32]),
                .DINPADINP     (wr_par[3:0]),
                .DINPBDINP     (wr_par[7:4]),
                .WEA           (4'b0000),
                .WEBWE         (web8)
            );
        end
    endgenerate

    assign rd_data = {do_hi, do_lo};

    wire [7:0] exp_rd_par = {
        ^rd_data[63:56], ^rd_data[55:48], ^rd_data[47:40], ^rd_data[39:32],
        ^rd_data[31:24], ^rd_data[23:16], ^rd_data[15:8],  ^rd_data[7:0]
    };
    assign rd_parity_err = |({dop_hi, dop_lo} ^ exp_rd_par);

endmodule


// =============================================================================
// Module: ramb36e1_shadow_bank
//   Dual-Banked Ping-Pong 4,096-Byte (`2 x RAMB36E1`) Crystal Page Store.
//   - Shadow writes (`shadow_wr_en`) strictly target `~active_bank` (`0` stalls).
//   - Active reads (`active_rd_en`) strictly gate `ENARDEN` on `active_bank`.
//   - `atomic_swap_pulse` flips `active_bank` in 1 single clock cycle.
// =============================================================================
module ramb36e1_shadow_bank #(
    parameter integer TARGET_FAMILY = 0
) (
    input  wire        clk,
    input  wire        rst_n,

    input  wire        atomic_swap_pulse,
    output reg         active_bank,
    output reg  [31:0] swap_generation,

    // Shadow Write Port (from PCIe BAR0 / AXI-Lite DMA -> writes `~active_bank`)
    input  wire        shadow_wr_en,
    input  wire [8:0]  shadow_wr_addr,
    input  wire [63:0] shadow_wr_data,

    // Active Read Port (CE-gated synchronous 1-cycle read from `active_bank`)
    input  wire        active_rd_en,
    input  wire [8:0]  active_rd_addr,
    output wire [63:0] active_rd_data,
    output wire        active_rd_parity_err
);
    wire srst = ~rst_n;
    reg  rd_bank_q;

    always @(posedge clk) begin
        if (!rst_n) begin
            active_bank     <= 1'b0;
            swap_generation <= 32'd0;
            rd_bank_q       <= 1'b0;
        end else begin
            if (active_rd_en)
                rd_bank_q <= active_bank;
            if (atomic_swap_pulse) begin
                active_bank     <= ~active_bank;
                swap_generation <= swap_generation + 32'd1;
            end
        end
    end

    wire rd_en_b0 = active_rd_en && (active_bank == 1'b0);
    wire rd_en_b1 = active_rd_en && (active_bank == 1'b1);
    wire wr_en_b0 = shadow_wr_en && (active_bank == 1'b1); // Bank 0 is shadow when active_bank == 1
    wire wr_en_b1 = shadow_wr_en && (active_bank == 1'b0); // Bank 1 is shadow when active_bank == 0

    wire [63:0] rd_data_b0, rd_data_b1;
    wire        perr_b0, perr_b1;

    xilinx_sdp_bram36_wrapper #(
        .TARGET_FAMILY(TARGET_FAMILY)
    ) u_bank0 (
        .clk           (clk),
        .srst          (srst),
        .rd_en         (rd_en_b0),
        .rd_addr       (active_rd_addr),
        .rd_data       (rd_data_b0),
        .rd_parity_err (perr_b0),
        .wr_en         (wr_en_b0),
        .wr_addr       (shadow_wr_addr),
        .wr_data       (shadow_wr_data)
    );

    xilinx_sdp_bram36_wrapper #(
        .TARGET_FAMILY(TARGET_FAMILY)
    ) u_bank1 (
        .clk           (clk),
        .srst          (srst),
        .rd_en         (rd_en_b1),
        .rd_addr       (active_rd_addr),
        .rd_data       (rd_data_b1),
        .rd_parity_err (perr_b1),
        .wr_en         (wr_en_b1),
        .wr_addr       (shadow_wr_addr),
        .wr_data       (shadow_wr_data)
    );

    assign active_rd_data       = rd_bank_q ? rd_data_b1 : rd_data_b0;
    assign active_rd_parity_err = rd_bank_q ? perr_b1    : perr_b0;

endmodule
