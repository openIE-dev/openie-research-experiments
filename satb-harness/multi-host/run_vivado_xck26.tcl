# =============================================================================
# Xilinx Vivado 2026.1 Non-Project Batch Synthesis, Place-and-Route & Power
# Target Part : AMD Kria KV260 SOM (`xck26-sfvc784-2LV-c`)
# Clock       : 250.000 MHz (`create_clock -period 4.000`)
# Thread Cap  : `set_param general.maxThreads 4` (low-footprint batch mode)
# Usage       :
#   BUILD_DIR=$BUILD_DIR REPO_DIR=$BENCH_ROOT/lut-adapt-ai \
#     nice -n 15 vivado -mode batch -nojournal -nolog -source run_vivado_xck26.tcl
# =============================================================================

set_param general.maxThreads 4

set part_name "xck26-sfvc784-2LV-c"
set repo_dir  [expr {[info exists ::env(REPO_DIR)]  ? $::env(REPO_DIR)  : "."}]
set build_dir [expr {[info exists ::env(BUILD_DIR)] ? $::env(BUILD_DIR) : "./vivado_xck26_out"}]
file mkdir $build_dir

# -----------------------------------------------------------------------------
# Pass 1: Out-of-Context (`-mode out_of_context`) Implementation of the 512-Page
#         `81 x RAMB36E2` + `512x512` Benes-Copy-Benes Speculative Core
#         (`clai_benes_paged_hotswap_core` in `hw/kv260/rtl/clai_benes_hotswap_core.sv`)
# -----------------------------------------------------------------------------
read_verilog -sv "$repo_dir/hw/kv260/rtl/clai_benes_hotswap_core.sv"

synth_design -top clai_benes_paged_hotswap_core -part $part_name -mode out_of_context
set_property MAX_DSP 0 [current_design]

create_clock -period 4.000 -name clk_pl_250m [get_ports clk]
set_clock_uncertainty 0.150 [get_clocks clk_pl_250m]
set_false_path -from [get_ports rst_n]

opt_design
place_design
phys_opt_design
route_design

report_utilization    -file "$build_dir/vivado_xck26_paged_benes_utilization.rpt"
report_timing_summary -delay_type max_min -max_paths 10 -file "$build_dir/vivado_xck26_paged_benes_timing.rpt"
report_power          -file "$build_dir/vivado_xck26_paged_benes_power.rpt"

set wns_benes [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set fmax_benes [expr {1000.0 / (4.000 - $wns_benes)}]
puts [format "VIVADO_RESULT top=clai_benes_paged_hotswap_core part=%s period_ns=4.000 wns_ns=%.3f fmax_mhz=%.2f" $part_name $wns_benes $fmax_benes]

close_design

# -----------------------------------------------------------------------------
# Pass 2: Out-of-Context Implementation of the Complete AMBA AXI4-Lite +
#         AXI4-Stream Rung-0 Subsystem (`clai_kv260_axi_top`)
# -----------------------------------------------------------------------------
read_verilog "$repo_dir/artifacts/clai_rung0_kv260.v"
read_verilog -sv [list \
    "$repo_dir/hw/kv260/rtl/clai_engram_streamer.sv" \
    "$repo_dir/hw/kv260/rtl/clai_rung0_hotswap_core.sv" \
    "$repo_dir/hw/kv260/rtl/clai_kv260_axi_top.sv" \
]

synth_design -top clai_kv260_axi_top -part $part_name -mode out_of_context
read_xdc "$repo_dir/hw/kv260/constraints/kv260_clai.xdc"

opt_design
place_design
phys_opt_design
route_design

report_utilization    -file "$build_dir/vivado_xck26_utilization.rpt"
report_timing_summary -delay_type max_min -max_paths 10 -file "$build_dir/vivado_xck26_timing.rpt"
report_power          -file "$build_dir/vivado_xck26_power.rpt"

set wns_axi [get_property SLACK [get_timing_paths -max_paths 1 -setup]]
set fmax_axi [expr {1000.0 / (4.000 - $wns_axi)}]
puts [format "VIVADO_RESULT top=clai_kv260_axi_top part=%s period_ns=4.000 wns_ns=%.3f fmax_mhz=%.2f" $part_name $wns_axi $fmax_axi]

close_design
exit
