// SPDX-License-Identifier: Apache-2.0
// Synthesizable 16-PE parallel clocked ternary accumulator RTL for `waiOS` 256x128 (0 multipliers).

`timescale 1ns / 1ps

module waios_ternary_pe (
    input  wire        clk,
    input  wire        clr,
    input  wire        en,
    input  wire [1:0]  w_code, // 2'b01 = +1, 2'b10 = -1, 2'b00 = 0
    input  wire signed [7:0] act,
    output reg  signed [31:0] acc
);
    wire signed [31:0] act_ext = {{24{act[7]}}, act};
    always @(posedge clk) begin
        if (clr) begin
            acc <= 32'sd0;
        end else if (en) begin
            case (w_code)
                2'b01:   acc <= acc + act_ext;
                2'b10:   acc <= acc - act_ext;
                default: acc <= acc;
            endcase
        end
    end
endmodule

module waios_ternary_rtl_tb;
    reg clk = 1'b0;
    always #1 clk = ~clk;

    reg [1:0]  w_mem [0:32767];
    reg [7:0]  a_mem [0:127];
    reg signed [31:0] out_mem [0:255];

    reg        clr = 1'b0;
    reg        en  = 1'b0;
    reg [1:0]  pe_w [0:15];
    reg signed [7:0] cur_act = 8'sd0;
    wire signed [31:0] pe_acc [0:15];

    genvar p;
    generate
        for (p = 0; p < 16; p = p + 1) begin : gen_pes
            waios_ternary_pe u_pe (
                .clk(clk),
                .clr(clr),
                .en(en),
                .w_code(pe_w[p]),
                .act(cur_act),
                .acc(pe_acc[p])
            );
        end
    endgenerate

    integer tile, col, lane, r_idx;
    reg [1023:0] w_file;
    reg [1023:0] a_file;

    initial begin
        if (!$value$plusargs("WHEX=%s", w_file)) w_file = "rtl_weights.hex";
        if (!$value$plusargs("AHEX=%s", a_file)) a_file = "rtl_acts.hex";
        $readmemh(w_file, w_mem);
        $readmemh(a_file, a_mem);

        for (tile = 0; tile < 16; tile = tile + 1) begin
            @(negedge clk);
            clr = 1'b1;
            en  = 1'b0;
            @(negedge clk);
            clr = 1'b0;
            en  = 1'b1;
            for (col = 0; col < 128; col = col + 1) begin
                cur_act = a_mem[col];
                for (lane = 0; lane < 16; lane = lane + 1) begin
                    pe_w[lane] = w_mem[(tile * 16 + lane) * 128 + col];
                end
                @(negedge clk);
            end
            en = 1'b0;
            @(negedge clk);
            for (lane = 0; lane < 16; lane = lane + 1) begin
                out_mem[tile * 16 + lane] = pe_acc[lane];
            end
        end

        for (r_idx = 0; r_idx < 256; r_idx = r_idx + 1) begin
            $display("%0d", out_mem[r_idx]);
        end
        $finish;
    end
endmodule
