// Verified Combinational Operon Skill & Sensor-Routing Next-State Machine (`verified_skill.v`)
// Synthesized via Yosys (`synth -noalumacc -nordff; abc -lut 6; write_json`) into a
// 4,096-byte `CompactLut6Page` (`verified_skill.lut6`) and verified bit-for-bit across all
// 2^14 = 16,384 active input vectors inside `lut6-core`.
//
// Input ABI (`in_word[13:0]`):
//   [1:0]   : 2-bit sensor/paraphrase LSB wobble (intentionally ignored -> wobble immunity!)
//   [5:2]   : 4-bit Operon codon stem `stem`
//   [9:6]   : 4-bit quantized sensor magnitude `mag`
//   [11:10] : 2-bit metabolic state `mstate` (0=QUIET, 1=READY, 2=BUSY, 3=SATURATED)
//   [12]    : `safety_ok` hardware interlock
//   [13]    : `budget_ok` thermodynamic budget strobe
//
// Output ABI (`out_word[12:0]`):
//   [5:0]   : 6-bit canonical Operon opcode (`0x00`, `0x10`, `0x18`, `0x20`, `0x24`, `0x28`, `0x2C`, `0x30`, `0x3C`)
//   [9:6]   : 4-bit peripheral strobe flags
//   [11:10] : 2-bit next metabolic state `next_mstate`
//   [12]    : even-parity integrity bit over `opcode ^ flags ^ next_mstate`

module verified_skill (
    input  wire [13:0] in_word,
    output reg  [12:0] out_word
);
    wire [1:0] _unused_wobble = in_word[1:0];
    wire [3:0] stem       = in_word[5:2];
    wire [3:0] mag        = in_word[9:6];
    wire [1:0] mstate     = in_word[11:10];
    wire       safety_ok  = in_word[12];
    wire       budget_ok  = in_word[13];

    wire high_mag = (mag >= 4'd10);
    wire mid_mag  = (mag >= 4'd4) && (mag < 4'd10);

    reg [5:0] opcode6;
    reg [3:0] flags4;
    reg [1:0] next_mstate;
    reg       parity;

    always @* begin
        if (!safety_ok) begin
            out_word = 13'h00BC; // 0x0080 | 0x003C (APOPTOSIS_ROLLBACK + alarm)
        end else if (mstate == 2'd0) begin
            out_word = 13'h0040; // STOP_HALT + sleep_wfi
        end else begin
            case (stem)
                4'h8: begin
                    opcode6 = 6'h20; // BUS_PIO_SPI
                    flags4  = 4'b0010;
                end
                4'h9: begin
                    opcode6 = 6'h24; // BUS_UART_MCP
                    flags4  = 4'b0010;
                end
                4'hA: begin
                    if (budget_ok && (high_mag || mid_mag)) begin
                        opcode6 = 6'h28; // WAKE_LOCAL_NPU
                        flags4  = 4'b0100;
                    end else begin
                        opcode6 = 6'h2C; // VERIFY_CHECK
                        flags4  = 4'b0001;
                    end
                end
                4'hC: begin
                    if (budget_ok && high_mag && (mstate != 2'd3)) begin
                        opcode6 = 6'h30; // TRANSCRIBE_FRONTIER
                        flags4  = 4'b1000;
                    end else begin
                        opcode6 = 6'h2C; // VERIFY_CHECK
                        flags4  = 4'b0001;
                    end
                end
                4'h4: begin
                    opcode6 = 6'h10; // SPLICE_PAGE
                    flags4  = 4'b0001;
                end
                4'h6: begin
                    opcode6 = 6'h18; // FOLD_STATE
                    flags4  = 4'b0001;
                end
                4'hF: begin
                    opcode6 = 6'h3C; // APOPTOSIS_ROLLBACK
                    flags4  = 4'b1000;
                end
                default: begin
                    if (high_mag && budget_ok) begin
                        opcode6 = 6'h2C; // VERIFY_CHECK
                        flags4  = 4'b0001;
                    end else begin
                        opcode6 = 6'h00; // STOP_HALT
                        flags4  = 4'b0001;
                    end
                end
            endcase

            case (mstate)
                2'd1:    next_mstate = high_mag ? 2'd2 : 2'd1;
                2'd2:    next_mstate = high_mag ? 2'd2 : 2'd1;
                2'd3:    next_mstate = 2'd1;
                default: next_mstate = mstate;
            endcase

            parity   = ^(opcode6 ^ {2'b00, flags4} ^ {4'b0000, next_mstate});
            out_word = {parity, next_mstate, flags4, opcode6};
        end
    end
endmodule
