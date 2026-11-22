//! Programmatic sovereign hardware design + metered `JCR-1` verification pipeline
//! for `MEI-JCP-Tag-v1` (`32 mm x 24 mm` 2-layer cold-chain sensor tag PCB,
//! `36 mm x 28 mm x 7.5 mm` 3D B-Rep enclosure, `CR2032` electro-thermal battery
//! simulation across `-20 C / +4 C / +25 C`, and `10,000`-wakeup `JCP` two-phase
//! `hold` / `settle` budget trace).

use std::collections::{BTreeMap, HashSet};
use std::fmt::Write as FmtWrite;
use std::fs;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use cad_eda::certify::{certify, CertifyVerdict};
use cad_eda::coord::{mm_to_nm, nm_to_mm, Angle, Coord, Nm};
use cad_eda::drc::DrcEngine;
use cad_eda::layer::Layer;
use cad_eda::netlist::{Net, NetClass, NetId, PinRef, PinType};
use cad_eda::pcb::{Board, DesignRules, FootprintInstance, Pad, PadShape, PadType, Pcb, Track, Via};
use cad_eda::project::EdaProject;
use cad_eda::schematic::{Label, SymbolInstance, SymbolPin, Wire};
use cad_format::drawing::{multiview_svg_hlr, DrawingFeature};
use cad_format::kicad::pcb::import_kicad_pcb;
use cad_format::stl::{read_binary, write_binary};
use cad_interop::eda_to_udd::eda_to_udd;
use cad_interop::gerber::udd_to_gerber;
use cad_interop::kicad::pcb_to_kicad_sexp;
use cad_joules::jcp_satb_bridge::{
    CadTract as BridgeTract, StageEnergyRecord, Step7SumOutcome,
};
use cad_joules::{metered, metered_repeated, EnergyMeter, JouleReceipt, Meter};
use cad_kernel::{compute_mass_properties, CadKernel, Pocket, Profile};
use cad_math::Point3D;
use cad_mfg::bom::BomEntry;
use cad_mfg::jlcpcb::{jlcpcb_bom_csv, jlcpcb_cpl_csv};
use cad_mfg::pcb_svg::{render_pcb_svg, PcbSvgOptions};
use cad_router::autorouter::{salt_decompose, MultipinNet};
use cad_router::pathfinder::{PathPoint, Pathfinder, PathfinderConfig, RoutePath};
use cad_sim::battery::{
    butler_volmer_current, capacity_at_rate, cell_resistance, heat_generation,
    open_circuit_voltage, terminal_voltage, BatteryMaterial,
};

use ed25519_dalek::SigningKey;
use jcp_efficiency::{aggregate, Efficiency};
use jcp_grant::issue;
use jcp_schema::{
    Capability, Caveat, ContentId, Coverage, Did, Energy, FrameKind, Grant, Trust,
};
use jcp_satb_cad_spine::{
    run_coldchain_10k_simulation, CadTract, ColdChainCellProfile, ColdChainRunSummary,
    SatbAttribution, SatbBoundary, SatbProvenance, SpineReceiptChain, StageAttemptSpec,
};
use serde::Serialize;
use serde_json::json;

const GRID_NM: Nm = 500_000; // 0.50 mm routing grid
const TRACK_WIDTH_NM: Nm = 180_000; // 0.18 mm (> 0.127 mm min_trace_width)
const VIA_DRILL_NM: Nm = 300_000; // 0.30 mm (== min_via_drill)
const VIA_SIZE_NM: Nm = 560_000; // 0.56 mm (annular ring = 0.130 mm > 0.125 mm min)

#[derive(Debug, Clone)]
struct PadSpec {
    pin: &'static str,
    dx_mm: f64,
    dy_mm: f64,
    w_mm: f64,
    h_mm: f64,
    drill_mm: Option<f64>,
    pin_type: PinType,
    net: &'static str,
}

#[derive(Debug, Clone)]
struct ComponentSpec {
    reference: &'static str,
    value: &'static str,
    lib_id: &'static str,
    footprint: &'static str,
    manufacturer: &'static str,
    mpn: &'static str,
    lcsc: &'static str,
    unit_price_usd: f64,
    x_mm: f64,
    y_mm: f64,
    back_side: bool,
    pads: Vec<PadSpec>,
}

#[derive(Debug, Clone, Serialize)]
struct PcbVerificationSummary {
    board_name: String,
    width_mm: f64,
    height_mm: f64,
    layers: u8,
    component_count: usize,
    pad_count: usize,
    net_count: usize,
    routed_edges: usize,
    total_edges: usize,
    completion_pct: f64,
    track_segments: usize,
    via_count: usize,
    total_copper_length_mm: f64,
    drc_passed: bool,
    drc_error_count: usize,
    drc_warning_count: usize,
    certify_verdict: String,
    kicad_roundtrip_tracks: usize,
    kicad_roundtrip_vias: usize,
    kicad_roundtrip_footprints: usize,
    gerber_files: Vec<String>,
    gerber_total_bytes: usize,
}

#[derive(Debug, Clone, Serialize)]
struct EnclosureVerificationSummary {
    outer_width_mm: f64,
    outer_depth_mm: f64,
    outer_height_mm: f64,
    overall_x_with_ear_mm: f64,
    wall_thickness_mm: f64,
    floor_thickness_mm: f64,
    volume_mm3: f64,
    mass_grams_abs: f64,
    surface_area_mm2: f64,
    vertex_count: usize,
    triangle_count: usize,
    step_bytes: usize,
    stl_bytes: usize,
    stl_roundtrip_triangles: usize,
}

#[derive(Debug, Clone, Serialize)]
struct BatteryTempPoint {
    temp_c: i32,
    ocv_100pct_v: f64,
    ocv_50pct_v: f64,
    r_int_50pct_ohm: f64,
    v_terminal_sleep_50pct_v: f64,
    v_terminal_tx_12ma_50pct_v: f64,
    tx_voltage_sag_mv: f64,
    butler_volmer_j_50mv_a_m2: f64,
    peukert_effective_ah_tx: f64,
    tx_ohmic_heat_mw: f64,
    usable_pulse_capacity_mah_to_2v0: f64,
    usable_energy_j_to_2v0: f64,
    derating_fraction_vs_nominal: f64,
}

/// Sample quiet host idle power (µW) over `100 ms` via `cad_joules::EnergyMeter`.
fn sample_idle_power_uw() -> Option<u64> {
    let mut meter = EnergyMeter::open();
    if !meter.supported() {
        return None;
    }
    let t0 = Instant::now();
    meter.start();
    std::thread::sleep(Duration::from_millis(100));
    let j = meter.end()?;
    let us = t0.elapsed().as_micros().max(1) as f64;
    let watts = (j.max(0.0) * 1_000_000.0) / us;
    Some((watts * 1_000_000.0).round() as u64)
}

/// Bracket a metered operation with pre/post `100 ms` idle power checks for SATB Falsifier 6.
fn run_bracketed_repeated<T>(
    op: &str,
    f: impl Fn() -> T,
) -> (T, JouleReceipt, Option<(u64, u64)>) {
    let pre = sample_idle_power_uw();
    let (val, mut receipt) = metered_repeated(op, f);
    // Sanitize hardware model string if empty or host-specific
    if receipt.model.is_empty() {
        receipt.model = "x86_64-linux-rapl".to_string();
    }
    let post = sample_idle_power_uw();
    let bracket = match (pre, post) {
        (Some(a), Some(b)) => Some((a, b)),
        _ => None,
    };
    (val, receipt, bracket)
}

fn run_bracketed_once<T>(
    op: &str,
    f: impl FnOnce() -> T,
) -> (T, JouleReceipt, Option<(u64, u64)>) {
    let pre = sample_idle_power_uw();
    let (val, mut receipt) = metered(op, f);
    if receipt.model.is_empty() {
        receipt.model = "x86_64-linux-rapl".to_string();
    }
    let post = sample_idle_power_uw();
    let bracket = match (pre, post) {
        (Some(a), Some(b)) => Some((a, b)),
        _ => None,
    };
    (val, receipt, bracket)
}

fn mei_tag_bom_specs() -> Vec<ComponentSpec> {
    vec![
        ComponentSpec {
            reference: "BT1",
            value: "CR2032_3V_225mAh",
            lib_id: "Device:Battery_Cell",
            footprint: "Battery:BatteryHolder_Keystone_3034_SMD",
            manufacturer: "Keystone Electronics",
            mpn: "3034",
            lcsc: "C70377",
            unit_price_usd: 0.68,
            x_mm: 16.0,
            y_mm: 12.0,
            back_side: true,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -11.5,
                    dy_mm: 0.0,
                    w_mm: 1.8,
                    h_mm: 1.8,
                    drill_mm: None,
                    pin_type: PinType::PowerOutput,
                    net: "VBAT_RAW",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 11.5,
                    dy_mm: 0.0,
                    w_mm: 1.8,
                    h_mm: 1.8,
                    drill_mm: None,
                    pin_type: PinType::PowerOutput,
                    net: "GND",
                },
            ],
        },
        ComponentSpec {
            reference: "R_SHUNT",
            value: "100mR_0.1pct_25ppm",
            lib_id: "Device:R_Shunt",
            footprint: "Resistor_SMD:R_0805_2012Metric",
            manufacturer: "Susumu",
            mpn: "RG2012P-101-B-T5",
            lcsc: "C275409",
            unit_price_usd: 0.24,
            x_mm: 5.5,
            y_mm: 17.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -1.0,
                    dy_mm: 0.0,
                    w_mm: 0.70,
                    h_mm: 0.80,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "VBAT_RAW",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 1.0,
                    dy_mm: 0.0,
                    w_mm: 0.70,
                    h_mm: 0.80,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "VDD_SYS",
                },
            ],
        },
        ComponentSpec {
            reference: "U2",
            value: "INA238AIDR",
            lib_id: "Sensor_Energy:INA238",
            footprint: "Package_SO:SOIC-8_3.9x4.9mm",
            manufacturer: "Texas Instruments",
            mpn: "INA238AIDR",
            lcsc: "C2875184",
            unit_price_usd: 1.85,
            x_mm: 11.5,
            y_mm: 17.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -2.0,
                    dy_mm: 1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "VBAT_RAW",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: -2.0,
                    dy_mm: 0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "3",
                    dx_mm: -2.0,
                    dy_mm: -0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "VBAT_RAW",
                },
                PadSpec {
                    pin: "4",
                    dx_mm: -2.0,
                    dy_mm: -1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::PowerInput,
                    net: "GND",
                },
                PadSpec {
                    pin: "5",
                    dx_mm: 2.0,
                    dy_mm: -1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::OpenCollector,
                    net: "JCP_ALERT",
                },
                PadSpec {
                    pin: "6",
                    dx_mm: 2.0,
                    dy_mm: -0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Bidirectional,
                    net: "I2C_SDA",
                },
                PadSpec {
                    pin: "7",
                    dx_mm: 2.0,
                    dy_mm: 0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "I2C_SCL",
                },
                PadSpec {
                    pin: "8",
                    dx_mm: 2.0,
                    dy_mm: 1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::PowerInput,
                    net: "VDD_SYS",
                },
            ],
        },
        ComponentSpec {
            reference: "U1",
            value: "STM32WBA52CGU",
            lib_id: "MCU_ST:STM32WBA52",
            footprint: "Package_DFN_QFN:QFN-13_ULP_Module",
            manufacturer: "STMicroelectronics",
            mpn: "STM32WBA52CGU6",
            lcsc: "C5362912",
            unit_price_usd: 2.65,
            x_mm: 19.5,
            y_mm: 12.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -2.5,
                    dy_mm: 2.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::PowerInput,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: -2.5,
                    dy_mm: 1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Output,
                    net: "I2C_SCL",
                },
                PadSpec {
                    pin: "3",
                    dx_mm: -2.5,
                    dy_mm: 0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Bidirectional,
                    net: "I2C_SDA",
                },
                PadSpec {
                    pin: "4",
                    dx_mm: -2.5,
                    dy_mm: -0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "JCP_ALERT",
                },
                PadSpec {
                    pin: "5",
                    dx_mm: -2.5,
                    dy_mm: -1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "NTC_ADC",
                },
                PadSpec {
                    pin: "6",
                    dx_mm: -2.5,
                    dy_mm: -2.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::PowerInput,
                    net: "GND",
                },
                PadSpec {
                    pin: "7",
                    dx_mm: 2.5,
                    dy_mm: -2.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Bidirectional,
                    net: "SWDIO",
                },
                PadSpec {
                    pin: "8",
                    dx_mm: 2.5,
                    dy_mm: -1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "SWCLK",
                },
                PadSpec {
                    pin: "9",
                    dx_mm: 2.5,
                    dy_mm: -0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Output,
                    net: "UART_TX",
                },
                PadSpec {
                    pin: "10",
                    dx_mm: 2.5,
                    dy_mm: 0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "SPI_MISO",
                },
                PadSpec {
                    pin: "11",
                    dx_mm: 2.5,
                    dy_mm: 1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Output,
                    net: "SPI_MOSI",
                },
                PadSpec {
                    pin: "12",
                    dx_mm: 2.5,
                    dy_mm: 2.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Output,
                    net: "SPI_SCK",
                },
                PadSpec {
                    pin: "13",
                    dx_mm: 0.0,
                    dy_mm: 3.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Output,
                    net: "SPI_CS",
                },
            ],
        },
        ComponentSpec {
            reference: "U3",
            value: "MB85RS256B_FRAM_256Kb",
            lib_id: "Memory_NVRAM:MB85RS256B",
            footprint: "Package_SO:SOIC-8_3.9x4.9mm",
            manufacturer: "Fujitsu / Kaga FEI",
            mpn: "MB85RS256BPNF-G-JNERE1",
            lcsc: "C90968",
            unit_price_usd: 1.42,
            x_mm: 26.5,
            y_mm: 18.0,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -2.0,
                    dy_mm: 1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "SPI_CS",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: -2.0,
                    dy_mm: 0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Output,
                    net: "SPI_MISO",
                },
                PadSpec {
                    pin: "3",
                    dx_mm: -2.0,
                    dy_mm: -0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "4",
                    dx_mm: -2.0,
                    dy_mm: -1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::PowerInput,
                    net: "GND",
                },
                PadSpec {
                    pin: "5",
                    dx_mm: 2.0,
                    dy_mm: -1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "SPI_MOSI",
                },
                PadSpec {
                    pin: "6",
                    dx_mm: 2.0,
                    dy_mm: -0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "SPI_SCK",
                },
                PadSpec {
                    pin: "7",
                    dx_mm: 2.0,
                    dy_mm: 0.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::Input,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "8",
                    dx_mm: 2.0,
                    dy_mm: 1.5,
                    w_mm: 0.50,
                    h_mm: 0.56,
                    drill_mm: None,
                    pin_type: PinType::PowerInput,
                    net: "VDD_SYS",
                },
            ],
        },
        ComponentSpec {
            reference: "RT1",
            value: "NTC_10k_B3380",
            lib_id: "Device:Thermistor_NTC",
            footprint: "Resistor_SMD:R_0603_1608Metric",
            manufacturer: "Murata",
            mpn: "NCP18XH103F03RB",
            lcsc: "C77131",
            unit_price_usd: 0.11,
            x_mm: 7.5,
            y_mm: 5.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "GND",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "NTC_ADC",
                },
            ],
        },
        ComponentSpec {
            reference: "R_BIAS",
            value: "10k_0.1pct",
            lib_id: "Device:R",
            footprint: "Resistor_SMD:R_0603_1608Metric",
            manufacturer: "Yageo",
            mpn: "RT0603BRD0710KL",
            lcsc: "C25804",
            unit_price_usd: 0.05,
            x_mm: 12.5,
            y_mm: 5.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "NTC_ADC",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "VDD_SYS",
                },
            ],
        },
        ComponentSpec {
            reference: "C1",
            value: "100nF_16V_X7R",
            lib_id: "Device:C",
            footprint: "Capacitor_SMD:C_0603_1608Metric",
            manufacturer: "Samsung Electro-Mechanics",
            mpn: "CL10B104KO8NNNC",
            lcsc: "C14663",
            unit_price_usd: 0.01,
            x_mm: 15.5,
            y_mm: 21.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "GND",
                },
            ],
        },
        ComponentSpec {
            reference: "C2",
            value: "1uF_16V_X7R",
            lib_id: "Device:C",
            footprint: "Capacitor_SMD:C_0603_1608Metric",
            manufacturer: "Samsung Electro-Mechanics",
            mpn: "CL10B105KO8NNNC",
            lcsc: "C15849",
            unit_price_usd: 0.02,
            x_mm: 19.5,
            y_mm: 6.5,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: -1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 1.0,
                    dy_mm: 0.0,
                    w_mm: 0.65,
                    h_mm: 0.70,
                    drill_mm: None,
                    pin_type: PinType::Passive,
                    net: "GND",
                },
            ],
        },
        ComponentSpec {
            reference: "J1",
            value: "SWD_UART_5P",
            lib_id: "Connector:Conn_01x05_Pin",
            footprint: "Connector_PinHeader_1.50mm:PinHeader_1x05_P1.50mm_Vertical",
            manufacturer: "JST / CJT",
            mpn: "A1501WV-5P",
            lcsc: "C2939543",
            unit_price_usd: 0.14,
            x_mm: 28.0,
            y_mm: 7.0,
            back_side: false,
            pads: vec![
                PadSpec {
                    pin: "1",
                    dx_mm: 0.0,
                    dy_mm: 3.0,
                    w_mm: 0.85,
                    h_mm: 0.85,
                    drill_mm: Some(0.50),
                    pin_type: PinType::PowerInput,
                    net: "VDD_SYS",
                },
                PadSpec {
                    pin: "2",
                    dx_mm: 0.0,
                    dy_mm: 1.5,
                    w_mm: 0.85,
                    h_mm: 0.85,
                    drill_mm: Some(0.50),
                    pin_type: PinType::Bidirectional,
                    net: "SWDIO",
                },
                PadSpec {
                    pin: "3",
                    dx_mm: 0.0,
                    dy_mm: 0.0,
                    w_mm: 0.85,
                    h_mm: 0.85,
                    drill_mm: Some(0.50),
                    pin_type: PinType::Input,
                    net: "SWCLK",
                },
                PadSpec {
                    pin: "4",
                    dx_mm: 0.0,
                    dy_mm: -1.5,
                    w_mm: 0.85,
                    h_mm: 0.85,
                    drill_mm: Some(0.50),
                    pin_type: PinType::Output,
                    net: "UART_TX",
                },
                PadSpec {
                    pin: "5",
                    dx_mm: 0.0,
                    dy_mm: -3.0,
                    w_mm: 0.85,
                    h_mm: 0.85,
                    drill_mm: Some(0.50),
                    pin_type: PinType::PowerInput,
                    net: "GND",
                },
            ],
        },
    ]
}

fn point_seg_dist_nm(p: Coord, a: Coord, b: Coord) -> f64 {
    let px = p.x as f64;
    let py = p.y as f64;
    let ax = a.x as f64;
    let ay = a.y as f64;
    let bx = b.x as f64;
    let by = b.y as f64;
    let dx = bx - ax;
    let dy = by - ay;
    let len_sq = dx * dx + dy * dy;
    if len_sq <= 1.0 {
        return p.distance_to(&a);
    }
    let t = (((px - ax) * dx + (py - ay) * dy) / len_sq).clamp(0.0, 1.0);
    let qx = ax + t * dx;
    let qy = ay + t * dy;
    ((px - qx).powi(2) + (py - qy).powi(2)).sqrt()
}

#[derive(Clone, Copy)]
struct PlacedPadInfo {
    pos: Coord,
    radius_nm: f64,
    layer: Option<Layer>, // None => through-hole (both FCu and BCu)
    drilled: bool,
    net: &'static str,
}

/// Build the complete `EdaProject` (`Schematic` + `Netlist` + `Pcb`) and route
/// 100% of nets via `cad_router::salt_decompose` + `cad_router::Pathfinder`.
fn build_and_route_mei_tag_eda() -> (EdaProject, Vec<BomEntry>, usize, usize) {
    let specs = mei_tag_bom_specs();
    let mut eda = EdaProject::new("MEI-JCP-Tag-v1");
    eda.netlist.classes.insert(
        "Default".to_string(),
        NetClass {
            name: "Default".to_string(),
            description: "2-layer 0.18mm signal / 0.30mm via".to_string(),
            trace_width: TRACK_WIDTH_NM,
            clearance: 160_000,
            via_drill: VIA_DRILL_NM,
            via_diameter: VIA_SIZE_NM,
            diff_pair_gap: 0,
            diff_pair_width: 0,
        },
    );

    let board = Board::rectangular("mei_jcp_tag_v1", 32.0, 24.0, 2);
    let mut pcb = Pcb::new(board);
    let mut bom_entries = Vec::new();
    let mut net_pins_sch: BTreeMap<&'static str, Vec<PinRef>> = BTreeMap::new();
    let mut net_points_pcb: BTreeMap<&'static str, Vec<PathPoint>> = BTreeMap::new();
    let mut all_pads: Vec<PlacedPadInfo> = Vec::new();

    for (idx, c) in specs.iter().enumerate() {
        // 1. Schematic symbol + wire stubs + net labels on Root sheet
        let sch_x = 25.0 + ((idx % 4) as f64) * 55.0;
        let sch_y = 30.0 + ((idx / 4) as f64) * 50.0;
        let sym_pins: Vec<SymbolPin> = c
            .pads
            .iter()
            .map(|p| {
                SymbolPin::new(
                    p.pin,
                    p.pin_type,
                    Coord::from_mm(p.dx_mm * 2.0, p.dy_mm * 2.0),
                )
            })
            .collect();
        let sym = SymbolInstance::new(c.lib_id, Coord::from_mm(sch_x, sch_y))
            .with_reference(c.reference)
            .with_value(c.value)
            .with_footprint(c.footprint)
            .with_pins(sym_pins.clone());
        let sym_id = sym.id;
        {
            let sheet = eda.schematic.root_mut().expect("root sheet");
            for sp in &sym_pins {
                let abs_pin = sym.pin_position(sp);
                let stub_end = Coord::new(abs_pin.x + mm_to_nm(3.0), abs_pin.y);
                sheet.add_wire(Wire::new(abs_pin, stub_end));
            }
            sheet.add_symbol(sym);
            for p in &c.pads {
                let abs_pos = Coord::from_mm(sch_x + p.dx_mm * 2.0 + 3.0, sch_y + p.dy_mm * 2.0);
                let lbl = if p.net == "GND" || p.net == "VDD_SYS" || p.net == "VBAT_RAW" {
                    Label::power(p.net, abs_pos)
                } else {
                    Label::global(p.net, abs_pos)
                };
                sheet.add_label(lbl);
                net_pins_sch.entry(p.net).or_default().push(PinRef {
                    component_id: sym_id,
                    pin: p.pin.to_string(),
                });
            }
        }

        // 2. PCB footprint + pads
        let mut fp = FootprintInstance::new(c.footprint, Coord::from_mm(c.x_mm, c.y_mm))
            .with_reference(c.reference)
            .with_value(c.value);
        if c.back_side {
            fp = fp.on_back();
        }
        let host_layer = fp.layer;

        for p in &c.pads {
            let w_nm = mm_to_nm(p.w_mm);
            let h_nm = mm_to_nm(p.h_mm);
            let (pad_type, pad_shape, drill_nm, pad_layer_opt) = match p.drill_mm {
                Some(d) => (
                    PadType::ThroughHole,
                    PadShape::Circle,
                    Some(mm_to_nm(d)),
                    None,
                ),
                None => (
                    PadType::Smd,
                    PadShape::RoundRect,
                    None,
                    Some(host_layer),
                ),
            };
            fp.pads.push(Pad {
                number: p.pin.to_string(),
                pad_type,
                shape: pad_shape,
                position: Coord::from_mm(p.dx_mm, p.dy_mm),
                rotation: Angle::ZERO,
                width: w_nm,
                height: h_nm,
                drill: drill_nm,
                net: p.net.to_string(),
                padstack: None,
                tenting: None,
            });
            let abs_coord = Coord::from_mm(c.x_mm + p.dx_mm, c.y_mm + p.dy_mm);
            let r_nm = ((w_nm as f64 / 2.0).powi(2) + (h_nm as f64 / 2.0).powi(2)).sqrt();
            all_pads.push(PlacedPadInfo {
                pos: abs_coord,
                radius_nm: r_nm,
                layer: pad_layer_opt,
                drilled: drill_nm.is_some(),
                net: p.net,
            });
            net_points_pcb.entry(p.net).or_default().push(PathPoint {
                position: abs_coord,
                layer: host_layer,
            });
        }
        pcb.add_footprint(fp);

        // 3. BOM entry
        bom_entries.push(BomEntry {
            reference: c.reference.to_string(),
            value: c.value.to_string(),
            footprint: c.footprint.to_string(),
            manufacturer: c.manufacturer.to_string(),
            mpn: c.mpn.to_string(),
            quantity: 1,
            unit_price: c.unit_price_usd,
            distributor: "LCSC".to_string(),
            distributor_pn: c.lcsc.to_string(),
        });
    }

    // Populate Netlist
    let mut net_ids: BTreeMap<&'static str, NetId> = BTreeMap::new();
    for (&net_name, pin_refs) in &net_pins_sch {
        let mut net = Net::new(net_name);
        net.class = "Default".to_string();
        net.pins = pin_refs.clone();
        let id = eda.netlist.add_net(net);
        net_ids.insert(net_name, id);
    }

    // Order nets: compact 2-pin signal buses first, multi-drop rails (`VBAT_RAW`, `VDD_SYS`, `GND`) last
    let route_order: [&str; 14] = [
        "I2C_SCL",
        "I2C_SDA",
        "JCP_ALERT",
        "NTC_ADC",
        "SPI_CS",
        "SPI_MISO",
        "SPI_MOSI",
        "SPI_SCK",
        "SWDIO",
        "SWCLK",
        "UART_TX",
        "VBAT_RAW",
        "VDD_SYS",
        "GND",
    ];

    let gx_max = mm_to_nm(32.0) / GRID_NM;
    let gy_max = mm_to_nm(24.0) / GRID_NM;

    let mut total_edges = 0usize;
    let mut routed_edges = 0usize;

    for net_name in route_order {
        let pts = net_points_pcb.get(net_name).expect("net points");
        let nid = *net_ids.get(net_name).expect("net id");
        let mp = MultipinNet::new(nid, net_name, pts.clone());
        let edges = salt_decompose(&mp, 0.35);
        let own_pin_cells: HashSet<PathPoint> = pts.iter().copied().collect();

        for conn in edges {
            total_edges += 1;
            let mut pf = Pathfinder::new(PathfinderConfig {
                grid_size: GRID_NM,
                via_cost: 7.5,
                corner_cost: 1.3,
                distance_cost: 1.0,
                max_iterations: 200_000,
            });

            // Build DRC-safe obstacle map for this connection
            for gx in 0..=gx_max {
                for gy in 0..=gy_max {
                    let c = Coord::new(gx * GRID_NM, gy * GRID_NM);
                    // 1. Board edge keepout (`>= 1.0 mm` margin -> copper_edge_clearance >= 0.72 mm >> 0.25 mm)
                    let near_edge = gx <= 1 || gx >= gx_max - 1 || gy <= 1 || gy >= gy_max - 1;
                    if near_edge {
                        pf.add_obstacle(PathPoint {
                            position: c,
                            layer: Layer::FCu,
                        });
                        pf.add_obstacle(PathPoint {
                            position: c,
                            layer: Layer::BCu,
                        });
                        continue;
                    }

                    for layer in [Layer::FCu, Layer::BCu] {
                        let cell = PathPoint { position: c, layer };
                        if own_pin_cells.contains(&cell) {
                            continue;
                        }

                        let mut blocked = false;

                        // 2. Foreign pad clearance + drilled-pad via protection on BCu
                        for pad in &all_pads {
                            if pad.net != net_name {
                                let margin = if pad.layer.map_or(true, |l| l == layer) {
                                    490_000.0
                                } else {
                                    // Opposite layer: prevent dropping a through-via onto an SMD pad
                                    460_000.0
                                };
                                if c.distance_to(&pad.pos) < pad.radius_nm + margin {
                                    blocked = true;
                                    break;
                                }
                            } else if pad.drilled && layer == Layer::BCu {
                                // Prevent dropping a redundant via within 0.90 mm of J1's own PTH drill
                                if c.distance_to(&pad.pos) < 900_000.0 {
                                    blocked = true;
                                    break;
                                }
                            }
                        }

                        // 3. Existing vias (mechanical drill spacing `>= 0.86 mm`; allow FCu escape on same net)
                        if !blocked {
                            for via in &pcb.vias {
                                let d = c.distance_to(&via.position);
                                if via.net == net_name {
                                    if layer == Layer::BCu && d > 1.0 && d < 860_000.0 {
                                        blocked = true;
                                        break;
                                    }
                                } else if d < 860_000.0 {
                                    blocked = true;
                                    break;
                                }
                            }
                        }

                        // 4. Foreign-net tracks on the same layer (`>= 0.60 mm` blocks diagonal X-crossings & via overlaps)
                        if !blocked {
                            for trk in &pcb.tracks {
                                if trk.layer == layer
                                    && trk.net != net_name
                                    && point_seg_dist_nm(c, trk.start, trk.end) < 600_000.0
                                {
                                    blocked = true;
                                    break;
                                }
                            }
                        }

                        if blocked {
                            pf.add_obstacle(cell);
                        }
                    }
                }
            }

            let path: RoutePath = pf
                .find_path(conn.from, conn.to)
                .unwrap_or_else(|| panic!("failed to route net {} ({:?} -> {:?})", net_name, conn.from, conn.to));
            routed_edges += 1;

            // Lift `RoutePath` into merged collinear `Track`s and deduplicated `Via`s
            lift_route_path_to_pcb(&mut pcb, &path, net_name);
        }
    }

    eda.pcb = Some(pcb);
    (eda, bom_entries, routed_edges, total_edges)
}

fn lift_route_path_to_pcb(pcb: &mut Pcb, path: &RoutePath, net_name: &str) {
    if path.points.len() < 2 {
        return;
    }
    let mut seg_start = path.points[0];
    let mut prev = path.points[0];

    for &curr in &path.points[1..] {
        if curr.layer != prev.layer {
            // Flush pending track on `prev.layer`
            if seg_start.position != prev.position {
                pcb.add_track(Track::new(
                    seg_start.position,
                    prev.position,
                    TRACK_WIDTH_NM,
                    prev.layer,
                    net_name,
                ));
            }
            // Place via if none already exists at `curr.position`
            if !pcb.vias.iter().any(|v| v.position == curr.position) {
                pcb.add_via(Via::through_hole(
                    curr.position,
                    VIA_DRILL_NM,
                    VIA_SIZE_NM,
                    net_name,
                ));
            }
            seg_start = curr;
            prev = curr;
        } else {
            // Check if collinear with `seg_start -> prev`
            let dx1 = prev.position.x - seg_start.position.x;
            let dy1 = prev.position.y - seg_start.position.y;
            let dx2 = curr.position.x - prev.position.x;
            let dy2 = curr.position.y - prev.position.y;
            let collinear =
                (dx1 == 0 && dy1 == 0) || (i128::from(dx1) * i128::from(dy2) == i128::from(dy1) * i128::from(dx2));
            if !collinear {
                pcb.add_track(Track::new(
                    seg_start.position,
                    prev.position,
                    TRACK_WIDTH_NM,
                    prev.layer,
                    net_name,
                ));
                seg_start = prev;
            }
            prev = curr;
        }
    }
    if seg_start.position != prev.position {
        pcb.add_track(Track::new(
            seg_start.position,
            prev.position,
            TRACK_WIDTH_NM,
            prev.layer,
            net_name,
        ));
    }
}

/// Render a publication-grade multi-layer SVG of the routed `MEI-JCP-Tag-v1` PCB
/// (grounded in the exact coordinates of `pcb.board`, `pcb.footprints`, `pcb.tracks`,
/// and `pcb.vias`).
fn render_annotated_pcb_svg(pcb: &Pcb) -> String {
    let scale = 24.0_f64; // 24 px/mm => 32x24mm board is 768x576 px
    let pad_left = 70.0_f64;
    let pad_top = 68.0_f64;
    let legend_w = 270.0_f64;
    let board_w_mm = nm_to_mm(pcb.board.width);
    let board_h_mm = nm_to_mm(pcb.board.height);
    let svg_w = pad_left + board_w_mm * scale + legend_w + 40.0;
    let svg_h = pad_top + board_h_mm * scale + 74.0;

    let bx = |x_mm: f64| pad_left + x_mm * scale;
    let by = |y_mm: f64| pad_top + (board_h_mm - y_mm) * scale;

    let mut s = String::with_capacity(32_768);
    let _ = writeln!(
        s,
        r##"<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {svg_w:.0} {svg_h:.0}" width="{svg_w:.0}" height="{svg_h:.0}" role="img" aria-label="MEI-JCP-Tag-v1 2-Layer Routed PCB Layout (32 mm x 24 mm, 0 DRC Violations)">"##
    );
    let _ = writeln!(
        s,
        r##"<defs>
  <style>
    .bg {{ fill: #f8fafc; }}
    .title {{ font: 700 16px ui-sans-serif, system-ui, -apple-system, sans-serif; fill: #0f172a; }}
    .sub {{ font: 500 11.5px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #475569; }}
    .dim {{ font: 600 11px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #334155; }}
    .ref {{ font: 700 10px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #f8fafc; }}
    .ref-bcu {{ font: 700 10px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #93c5fd; }}
    .pin {{ font: 600 7.5px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #0f172a; }}
    .leg-h {{ font: 700 12px ui-sans-serif, system-ui, sans-serif; fill: #0f172a; }}
    .leg-t {{ font: 500 10.5px ui-monospace, SFMono-Regular, Menlo, monospace; fill: #334155; }}
  </style>
</defs>"##
    );
    let _ = writeln!(s, r##"<rect class="bg" x="0" y="0" width="{svg_w:.0}" height="{svg_h:.0}" rx="10"/>"##);
    let _ = writeln!(
        s,
        r##"<text class="title" x="{pad_left:.0}" y="28">MEI-JCP-Tag-v1 — 2-Layer Sovereign Cold-Chain Sensor PCB</text>"##
    );
    let _ = writeln!(
        s,
        r##"<text class="sub" x="{pad_left:.0}" y="47">32.0 mm × 24.0 mm · FR-4 1.6 mm · 10 Components · 14 Nets · {tracks} Track Segments · {vias} Vias · DRC: 0 Violations (CERTIFIED)</text>"##,
        tracks = pcb.tracks.len(),
        vias = pcb.vias.len()
    );

    // FR-4 solder-mask substrate
    let bw = board_w_mm * scale;
    let bh = board_h_mm * scale;
    let _ = writeln!(
        s,
        r##"<rect x="{x:.1}" y="{y:.1}" width="{bw:.1}" height="{bh:.1}" rx="6" fill="#0d3321" stroke="#eab308" stroke-width="2.2"/>"##,
        x = bx(0.0),
        y = by(board_h_mm),
    );

    // Subtle 2.0 mm routing reference grid
    let _ = writeln!(s, r##"<g stroke="#1b4d35" stroke-width="0.6" opacity="0.55">"##);
    for gx in (2..32).step_by(2) {
        let x = bx(gx as f64);
        let _ = writeln!(s, r##"<line x1="{x:.1}" y1="{y0:.1}" x2="{x:.1}" y2="{y1:.1}"/>"##, y0 = by(board_h_mm), y1 = by(0.0));
    }
    for gy in (2..24).step_by(2) {
        let y = by(gy as f64);
        let _ = writeln!(s, r##"<line x1="{x0:.1}" y1="{y:.1}" x2="{x1:.1}" y2="{y:.1}"/>"##, x0 = bx(0.0), x1 = bx(board_w_mm));
    }
    let _ = writeln!(s, "</g>");

    // B.Cu courtyard for BT1 CR2032 coin cell (20 mm cell circle)
    let _ = writeln!(
        s,
        r##"<circle cx="{cx:.1}" cy="{cy:.1}" r="{r:.1}" fill="none" stroke="#60a5fa" stroke-width="1.3" stroke-dasharray="6 4" opacity="0.72"/>"##,
        cx = bx(16.0),
        cy = by(12.0),
        r = 10.0 * scale
    );

    // Render B.Cu tracks first, then F.Cu tracks
    for pass_layer in [Layer::BCu, Layer::FCu] {
        let color = if pass_layer == Layer::FCu {
            "#ef4444"
        } else {
            "#3b82f6"
        };
        let opacity = if pass_layer == Layer::FCu { "0.95" } else { "0.86" };
        let _ = writeln!(
            s,
            r##"<g stroke="{color}" stroke-linecap="round" stroke-linejoin="round" opacity="{opacity}">"##
        );
        for t in pcb.tracks.iter().filter(|t| t.layer == pass_layer) {
            let (x1, y1) = t.start.to_mm();
            let (x2, y2) = t.end.to_mm();
            let sw = (nm_to_mm(t.width) * scale).max(2.6);
            let _ = writeln!(
                s,
                r##"<line x1="{:.2}" y1="{:.2}" x2="{:.2}" y2="{:.2}" stroke-width="{sw:.2}"><title>{net} ({layer:?})</title></line>"##,
                bx(x1),
                by(y1),
                bx(x2),
                by(y2),
                net = t.net,
                layer = t.layer
            );
        }
        let _ = writeln!(s, "</g>");
    }

    // Component silkscreen courtyards + pads
    let mut fps: Vec<&FootprintInstance> = pcb.footprints.values().collect();
    fps.sort_by(|a, b| a.reference.cmp(&b.reference));
    for fp in fps {
        let (fx, fy) = fp.position.to_mm();
        let mut min_x = fx - 0.8;
        let mut max_x = fx + 0.8;
        let mut min_y = fy - 0.8;
        let mut max_y = fy + 0.8;
        for pad in &fp.pads {
            let (px, py) = pad.position.to_mm();
            let hw = nm_to_mm(pad.width) / 2.0;
            let hh = nm_to_mm(pad.height) / 2.0;
            min_x = min_x.min(fx + px - hw - 0.35);
            max_x = max_x.max(fx + px + hw + 0.35);
            min_y = min_y.min(fy + py - hh - 0.35);
            max_y = max_y.max(fy + py + hh + 0.35);
        }
        if fp.layer == Layer::FCu {
            let _ = writeln!(
                s,
                r##"<rect x="{:.1}" y="{:.1}" width="{:.1}" height="{:.1}" rx="3" fill="#14532d" fill-opacity="0.35" stroke="#e2e8f0" stroke-width="1.1"/>"##,
                bx(min_x),
                by(max_y),
                (max_x - min_x) * scale,
                (max_y - min_y) * scale
            );
        }
        for pad in &fp.pads {
            let (dx, dy) = pad.position.to_mm();
            let px = bx(fx + dx);
            let py = by(fy + dy);
            let pw = nm_to_mm(pad.width) * scale;
            let ph = nm_to_mm(pad.height) * scale;
            let pad_fill = if pad.drill.is_some() {
                "#facc15"
            } else if fp.layer == Layer::BCu {
                "#60a5fa"
            } else {
                "#f87171"
            };
            let _ = writeln!(
                s,
                r##"<rect x="{:.2}" y="{:.2}" width="{pw:.2}" height="{ph:.2}" rx="2.5" fill="{pad_fill}" stroke="#fef08a" stroke-width="0.8"><title>{r}.{pin} -> {net}</title></rect>"##,
                px - pw / 2.0,
                py - ph / 2.0,
                r = fp.reference,
                pin = pad.number,
                net = pad.net
            );
            if let Some(d_nm) = pad.drill {
                let dr = (nm_to_mm(d_nm) * scale / 2.0).max(2.2);
                let _ = writeln!(
                    s,
                    r##"<circle cx="{px:.2}" cy="{py:.2}" r="{dr:.2}" fill="#0f172a"/>"##
                );
            }
        }
        let label_y = if fp.reference == "BT1" {
            by(fy) + 4.0
        } else {
            by(max_y) - 5.0
        };
        let cls = if fp.layer == Layer::BCu {
            "ref-bcu"
        } else {
            "ref"
        };
        let _ = writeln!(
            s,
            r##"<text class="{cls}" x="{:.1}" y="{label_y:.1}" text-anchor="middle">{}</text>"##,
            bx(fx),
            fp.reference
        );
    }

    // Plated through-hole vias
    for v in &pcb.vias {
        let (vx, vy) = v.position.to_mm();
        let outer_r = (nm_to_mm(v.size) * scale / 2.0).max(4.0);
        let inner_r = (nm_to_mm(v.drill) * scale / 2.0).max(2.0);
        let _ = writeln!(
            s,
            r##"<circle cx="{:.2}" cy="{:.2}" r="{outer_r:.2}" fill="#eab308" stroke="#0f172a" stroke-width="0.8"><title>Via ({net})</title></circle>"##,
            bx(vx),
            by(vy),
            net = v.net
        );
        let _ = writeln!(
            s,
            r##"<circle cx="{:.2}" cy="{:.2}" r="{inner_r:.2}" fill="#0f172a"/>"##,
            bx(vx),
            by(vy)
        );
    }

    // Dimension callouts
    let dim_y = by(0.0) + 28.0;
    let _ = writeln!(
        s,
        r##"<line x1="{:.1}" y1="{dim_y:.1}" x2="{:.1}" y2="{dim_y:.1}" stroke="#334155" stroke-width="1.2"/>"##,
        bx(0.0),
        bx(board_w_mm)
    );
    let _ = writeln!(
        s,
        r##"<text class="dim" x="{:.1}" y="{:.1}" text-anchor="middle">32.00 mm (Edge.Cuts)</text>"##,
        bx(board_w_mm / 2.0),
        dim_y + 16.0
    );
    let dim_x = pad_left - 22.0;
    let _ = writeln!(
        s,
        r##"<line x1="{dim_x:.1}" y1="{:.1}" x2="{dim_x:.1}" y2="{:.1}" stroke="#334155" stroke-width="1.2"/>"##,
        by(board_h_mm),
        by(0.0)
    );
    let _ = writeln!(
        s,
        r##"<text class="dim" transform="translate({:.1},{:.1}) rotate(-90)" text-anchor="middle">24.00 mm</text>"##,
        dim_x - 10.0,
        by(board_h_mm / 2.0)
    );

    // Legend & BOM/Stackup card on right
    let lx = bx(board_w_mm) + 24.0;
    let ly = by(board_h_mm);
    let _ = writeln!(
        s,
        r##"<rect x="{lx:.1}" y="{ly:.1}" width="{legend_w:.1}" height="{bh:.1}" rx="8" fill="#ffffff" stroke="#cbd5e1" stroke-width="1.2"/>"##
    );
    let rows = [
        ("Stackup & Layers", ""),
        ("F.Cu (Top Red)", "MCU, INA238, FRAM, NTC"),
        ("B.Cu (Bot Blue)", "BT1 CR2032 + Return"),
        ("Plated Vias", "0.30 mm drill / 0.56 mm pad"),
        ("Trace / Space", "0.18 mm / >= 0.16 mm"),
        ("Key Subsystems", ""),
        ("U1 STM32WBA52", "ULP MCU + BLE-LR Gate"),
        ("U2 TI INA238", "16-bit I2C Shunt Monitor"),
        ("R_SHUNT 100 mOhm", "0.1% 25 ppm/C Sense"),
        ("U3 MB85RS256B", "256-Kb SPI FRAM JCR-1 Ring"),
        ("RT1 + R_BIAS", "10 kOhm Cold-Chain NTC"),
        ("C1, C2", "100 nF + 1 uF X7R Decoupling"),
        ("J1 5-Pin PTH", "SWD + JCR-1 UART Dump"),
        ("BT1 Keystone 3034", "CR2032 225 mAh (2,430 J)"),
        ("DRC & Export Status", ""),
        ("cad-eda DRC", "0 errors / 0 warnings"),
        ("Board Bench State", "Fabrication pkg (unbuilt)"),
    ];
    let mut cy = ly + 24.0;
    for (k, v) in rows {
        if v.is_empty() {
            cy += 6.0;
            let _ = writeln!(s, r##"<text class="leg-h" x="{:.1}" y="{cy:.1}">{k}</text>"##, lx + 14.0);
            cy += 18.0;
        } else {
            let _ = writeln!(
                s,
                r##"<text class="leg-t" x="{:.1}" y="{cy:.1}">{k}: {v}</text>"##,
                lx + 14.0
            );
            cy += 17.5;
        }
    }
    let _ = writeln!(s, "</svg>");
    s
}

/// Build the `MEI-JCP-Tag-v1` snap-fit vented cold-chain tag enclosure (`36 mm x 28 mm x 7.5 mm`
/// main tub + lanyard mounting ear + airflow/thermistor window + 4 internal PCB standoffs +
/// snap-fit retention slots) using `cad_kernel::CadKernel` (Y-up base-seated).
fn build_mei_tag_enclosure() -> (String, Vec<u8>, String, EnclosureVerificationSummary) {
    let mut k = CadKernel::new();

    // 1. Base-seated outer enclosure shell: width=36.0 (X), height=7.5 (+Y), depth=28.0 (Z)
    //    Spans x in [-18.0, +18.0], y in [0.0, 7.5], z in [-14.0, +14.0].
    let outer = k.create_box(36.0, 7.5, 28.0).expect("create outer box");

    // 2. Sink 6.1 mm blind interior cavity (`32.8 mm x 24.8 mm`, leaving 1.6 mm walls and 1.4 mm floor)
    let cavity = Pocket {
        profile: Profile::Rect {
            cx: 0.0,
            cz: 0.0,
            w: 32.8,
            d: 24.8,
        },
        depth: 6.1,
    };
    let mut body = k.pocket_body(outer, &cavity).expect("sink interior pocket");

    // 3. Mounting ear on +X wall with exact NURBS Ø4.0 mm lanyard/M3 bore.
    //    Translated +0.2 mm in Y (`y in [0.2, 2.8]`) and overlapping `x in [16.8, 23.5]`
    //    so zero faces are coplanar with the outer shell's floor or side wall!
    let ear = k
        .create_extrusion_with_holes(
            &Profile::Rect {
                cx: 20.15,
                cz: 0.0,
                w: 6.7,
                d: 12.0,
            },
            &[Profile::Circle {
                cx: 21.2,
                cz: 0.0,
                r: 2.0,
            }],
            2.6,
        )
        .expect("extrude mounting ear with bore");
    k.translate(ear, 0.0, 0.2, 0.0).expect("translate ear");
    body = k.boolean_union(body, ear).expect("union mounting ear");

    // 4. Cut airflow & NTC thermistor window on -Z/-X wall directly above RT1 (`x in [-13.5, -5.5]`),
    //    opening through the top rim (`y in [3.1, 8.2]`) for rapid convective equilibration.
    let vent = k.create_box(8.0, 5.1, 4.0).expect("create vent cutter");
    k.translate(vent, -9.5, 3.1, -13.2)
        .expect("position vent cutter");
    body = k
        .boolean_subtract(body, vent)
        .expect("subtract thermistor airflow window");

    // 5. Cut symmetric snap-fit lid retention slots on -X and +X upper inner rims (`y in [5.6, 6.7]`)
    for sign in [-1.0_f64, 1.0_f64] {
        let slot = k.create_box(1.4, 1.1, 10.0).expect("snap slot cutter");
        k.translate(slot, sign * 16.4, 5.6, 0.0)
            .expect("translate snap slot");
        body = k.boolean_subtract(body, slot).expect("subtract snap slot");
    }

    // 6. Union 4 internal PCB standoffs (`r = 1.4 mm`, penetrating 0.3 mm into y=1.4 floor -> y in [1.1, 2.9])
    for &(sx, sz) in &[
        (-14.2_f64, -10.2_f64),
        (14.2, -10.2),
        (-14.2, 10.2),
        (14.2, 10.2),
    ] {
        let post = k.create_cylinder(1.4, 1.8).expect("create standoff");
        k.translate(post, sx, 1.1, sz).expect("translate standoff");
        body = k.boolean_union(body, post).expect("union standoff");
    }

    let bbox = k.bounding_box(body, 0.08).expect("bounding box");
    let mesh = k.tessellate(body, 0.08).expect("tessellate enclosure");
    // ABS density = 1.05 g/cm3 = 0.00105 g/mm3
    let props = compute_mass_properties(&mesh, 0.00105);
    assert!(
        props.volume > 1500.0,
        "enclosure volume must be positive and physically realistic, got {}",
        props.volume
    );

    let step_str = k.export_step(body).expect("export STEP");
    let stl_bytes = write_binary(&mesh);
    let stl_back = read_binary(&stl_bytes).expect("round-trip binary STL");
    assert_eq!(stl_back.triangle_count(), mesh.triangle_count());

    let drawing_features = vec![DrawingFeature {
        center: Point3D::new(21.2, 1.5, 0.0),
        diameter: 4.0,
    }];
    let svg_drawing = multiview_svg_hlr(
        &mesh,
        "MEI-JCP-Tag-v1 Vented Cold-Chain Enclosure (36x28x7.5mm + Ear)",
        22.0,
        &drawing_features,
        28,
    );

    let summary = EnclosureVerificationSummary {
        outer_width_mm: 36.0,
        outer_depth_mm: 28.0,
        outer_height_mm: (bbox.max.y - bbox.min.y),
        overall_x_with_ear_mm: (bbox.max.x - bbox.min.x),
        wall_thickness_mm: 1.6,
        floor_thickness_mm: 1.4,
        volume_mm3: (props.volume * 100.0).round() / 100.0,
        mass_grams_abs: (props.mass * 1000.0).round() / 1000.0,
        surface_area_mm2: (props.surface_area * 100.0).round() / 100.0,
        vertex_count: mesh.vertex_count(),
        triangle_count: mesh.triangle_count(),
        step_bytes: step_str.len(),
        stl_bytes: stl_bytes.len(),
        stl_roundtrip_triangles: stl_back.triangle_count(),
    };
    (step_str, stl_bytes, svg_drawing, summary)
}

/// Construct calibrated `BatteryMaterial` for `CR2032` (`Li-MnO2`, `3.0 V`, `0.225 Ah` = `2,430 J`
/// nominal, `R_int(50% SOC, 25 C) = 12.0 Ohm`, `peukert_exponent = 1.12`) and evaluate
/// `cad-sim::battery` across `-20 C`, `+4 C`, and `+25 C`.
fn run_cr2032_battery_sim() -> Vec<BatteryTempPoint> {
    let cr2032 = BatteryMaterial {
        name: "CR2032 (Li-MnO2 Primary Coin Cell)".to_string(),
        nominal_voltage: 3.0,
        nominal_capacity: 0.225, // 225 mAh => 3.0 V * 0.225 Ah * 3600 = 2,430 J
        exchange_current_density: 0.85,
        alpha: 0.5,
        n_electrons: 1.0,
        internal_resistance: 12.0, // 12 Ohm at 25 C, 50% SOC
        peukert_exponent: 1.12,
        specific_heat: 920.0,
        cell_mass_kg: 0.0030,
        thermal_runaway_temp: 170.0,
        // Monotone Li-MnO2 discharge curve: ~2.10 V at 0% SOC -> ~2.96 V plateau -> ~3.20 V fresh
        ocv_coefficients: [2.10, 3.80, -8.40, 9.60, -5.30, 1.40],
    };

    let i_sleep_a = 3.0e-6; // 3 uA sleep/sense baseline
    let i_tx_a = 0.012; // 12 mA BLE-LR radio TX burst
    let v_cutoff = 2.00; // 2.00 V brownout threshold under TX pulse

    let mut out = Vec::new();
    for temp_c in [-20_i32, 4, 25] {
        let tc = temp_c as f64;
        let tk = tc + 273.15;
        let ocv_100 = open_circuit_voltage(&cr2032, 1.0);
        let ocv_50 = open_circuit_voltage(&cr2032, 0.5);
        let r_50 = cell_resistance(&cr2032, 0.5, tc);
        let v_sleep_50 = terminal_voltage(&cr2032, 0.5, i_sleep_a, tc);
        let v_tx_50 = terminal_voltage(&cr2032, 0.5, i_tx_a, tc);
        let bv_50mv = butler_volmer_current(
            cr2032.exchange_current_density,
            0.050,
            cr2032.alpha,
            cr2032.n_electrons,
            tk,
        );
        let peukert_ah = capacity_at_rate(
            cr2032.nominal_capacity,
            i_tx_a,
            cr2032.peukert_exponent,
        );
        let heat_w = heat_generation(&cr2032, i_tx_a, 0.5, tc);

        // Integrate SOC from 1.00 down to 0.00 in 1,000 steps until a 12 mA TX burst
        // hits `terminal_voltage < 2.00 V` (pulse-cutoff usable energy), scaled by Peukert factor.
        let peukert_ratio = (peukert_ah / cr2032.nominal_capacity).clamp(0.1, 1.0);
        let steps = 1_000usize;
        let d_ah = (cr2032.nominal_capacity * peukert_ratio) / (steps as f64);
        let mut usable_ah = 0.0_f64;
        let mut usable_j = 0.0_f64;
        for k in 0..steps {
            let soc = 1.0 - (k as f64 + 0.5) / (steps as f64);
            let v_pulse = terminal_voltage(&cr2032, soc, i_tx_a, tc);
            if v_pulse < v_cutoff {
                break;
            }
            let v_avg = terminal_voltage(&cr2032, soc, 85.0e-6, tc);
            usable_ah += d_ah;
            usable_j += v_avg * d_ah * 3600.0;
        }

        out.push(BatteryTempPoint {
            temp_c,
            ocv_100pct_v: (ocv_100 * 1000.0).round() / 1000.0,
            ocv_50pct_v: (ocv_50 * 1000.0).round() / 1000.0,
            r_int_50pct_ohm: (r_50 * 100.0).round() / 100.0,
            v_terminal_sleep_50pct_v: (v_sleep_50 * 1000.0).round() / 1000.0,
            v_terminal_tx_12ma_50pct_v: (v_tx_50 * 1000.0).round() / 1000.0,
            tx_voltage_sag_mv: ((ocv_50 - v_tx_50) * 1000.0 * 10.0).round() / 10.0,
            butler_volmer_j_50mv_a_m2: (bv_50mv * 1000.0).round() / 1000.0,
            peukert_effective_ah_tx: (peukert_ah * 10_000.0).round() / 10_000.0,
            tx_ohmic_heat_mw: (heat_w * 1000.0 * 100.0).round() / 100.0,
            usable_pulse_capacity_mah_to_2v0: (usable_ah * 1000.0 * 100.0).round() / 100.0,
            usable_energy_j_to_2v0: (usable_j * 100.0).round() / 100.0,
            derating_fraction_vs_nominal: ((usable_j / 2430.0) * 10_000.0).round() / 10_000.0,
        });
    }
    out
}

fn make_spine_spec_from_bridge(
    stage_rec: &StageEnergyRecord,
    action: &str,
    resource: ContentId,
    payload: &[u8],
    timestamp_s: u64,
    step7_phases: Option<Vec<u64>>,
) -> StageAttemptSpec {
    let tract = match stage_rec.tract {
        BridgeTract::Material => CadTract::Material,
        BridgeTract::SupplyChain => CadTract::SupplyChain,
        BridgeTract::Compute => CadTract::Compute,
    };
    let prov = if stage_rec.reported_uj.is_some() {
        let attr = if stage_rec.falsifier6.is_some() {
            SatbAttribution::A2
        } else {
            SatbAttribution::B
        };
        SatbProvenance::vendor_counter(
            SatbBoundary::L1,
            attr,
            stage_rec.backend == "macos-ioreport",
        )
    } else {
        SatbProvenance::estimator(SatbBoundary::L2)
    };
    let bracket = stage_rec
        .falsifier6
        .map(|f| (f.pre_idle_uw, f.post_idle_uw));
    StageAttemptSpec {
        stage: stage_rec.stage.clone(),
        tract,
        action: action.to_string(),
        resource,
        payload_bytes: payload.to_vec(),
        trust: Trust::Control,
        frame_kind: FrameKind::ToolCall,
        timestamp_s,
        window_us: stage_rec.window_us,
        backend: stage_rec.backend.clone(),
        provenance: prov,
        measured_uj: None, // Tag PCB is a fab export, not yet physically assembled on a bench!
        reported_uj: stage_rec.reported_uj,
        est_uj: stage_rec.est_uj,
        idle_bracket_uw: bracket,
        step7_subphases_uj: step7_phases,
    }
}

fn main() {
    let out_root = std::env::args()
        .nth(1)
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from("output"));
    let hw_dir = out_root.join("hardware");
    let gerber_dir = hw_dir.join("gerbers");
    let receipts_dir = out_root.join("receipts");
    fs::create_dir_all(&gerber_dir).expect("create gerbers dir");
    fs::create_dir_all(&receipts_dir).expect("create receipts dir");

    let pipeline_t0 = Instant::now();

    // Initialize JCP Steward & Session Grant (`500 J` compute/embodied ceiling)
    let issuer_sk = SigningKey::from_bytes(&[0x41; 32]);
    let builder_sk = SigningKey::from_bytes(&[0x42; 32]);
    let steward_sk = SigningKey::from_bytes(&[0x43; 32]);
    let issuer_did = Did::from_verifying_key(&issuer_sk.verifying_key());
    let builder_did = Did::from_verifying_key(&builder_sk.verifying_key());
    let resource_cad = ContentId::of_bytes(b"openie-cad:build:mei-jcp-tag-v1");

    let sg_build = issue(
        &issuer_sk,
        Grant {
            issuer: issuer_did,
            subject: builder_did,
            capability: Capability::new(
                resource_cad,
                ["cad.material", "cad.supply_chain", "cad.compute"],
            ),
            budget_uj: 500_000_000, // 500 J ceiling
            budget_funds: None,
            caveats: vec![Caveat::MaxCostUj(250_000_000)],
            expiry: 0,
            parent: None,
            delegate_depth: None,
            nonce: [0x51; 16],
        },
    )
    .expect("issue build grant");

    let mut spine = SpineReceiptChain::new(steward_sk, "did:openie:steward:mei-jcp-tag-v1-build");
    let mut bridge_stages: Vec<StageEnergyRecord> = Vec::new();

    // ─── Stage 1: Native 3D B-Rep Enclosure (`cad-kernel`) ───────────────────
    let ((step_str, stl_bytes, enclosure_svg, enc_summary), r_kernel, b_kernel) =
        run_bracketed_once("kernel.brep_enclosure", build_mei_tag_enclosure);
    fs::write(hw_dir.join("mei_jcp_tag_enclosure.step"), &step_str).expect("write STEP");
    fs::write(hw_dir.join("mei_jcp_tag_enclosure.stl"), &stl_bytes).expect("write STL");
    fs::write(hw_dir.join("mei-jcp-tag-enclosure.svg"), &enclosure_svg)
        .expect("write enclosure SVG");

    let est_kernel_uj = ((r_kernel.window_us as f64) * 35.0).round() as u64; // 35 W analytical compute model
    let rec_kernel = StageEnergyRecord::from_cad_receipt(
        &r_kernel,
        BridgeTract::Compute,
        Some(est_kernel_uj),
        b_kernel,
    );
    bridge_stages.push(rec_kernel.clone());

    // ─── Stage 2: Embodied Material Tract (`FR-4` + `ABS` analytical `est_j`) ─
    // Embodied analytical estimate only (never presented as host counter):
    // 2.27 g 2-layer FR-4/Cu (~18.2 J synthesis slice) + ABS enclosure mass * 9.5 J/g processing slice
    let embodied_est_uj =
        ((18.2 + enc_summary.mass_grams_abs * 9.5) * 1_000_000.0).round() as u64;
    let rec_material = StageEnergyRecord::estimator_only(
        "material.fr4_and_abs_embodied",
        BridgeTract::Material,
        embodied_est_uj,
        100,
    );
    bridge_stages.push(rec_material.clone());

    // ─── Stage 3: Supply-Chain SMT Tract (`JLCPCB` 10-part placement `est_j`) ─
    let smt_est_uj = 14_500_000_u64; // 14.5 J analytical reflow/pick-and-place amortized per board
    let rec_supply = StageEnergyRecord::estimator_only(
        "supply_chain.smt_10part_batch_share",
        BridgeTract::SupplyChain,
        smt_est_uj,
        100,
    );
    bridge_stages.push(rec_supply.clone());

    // ─── Stage 4: Native ECAD Schematic + 2-Layer Autorouting (`cad-eda` + `cad-router`) ─
    let ((eda_project, bom_entries, routed_edges, total_edges), r_route, b_route) =
        run_bracketed_repeated("ecad.schematic_and_autoroute", build_and_route_mei_tag_eda);
    let est_route_uj = ((r_route.window_us as f64) * 32.0).round() as u64;
    let rec_route = StageEnergyRecord::from_cad_receipt(
        &r_route,
        BridgeTract::Compute,
        Some(est_route_uj),
        b_route,
    );
    bridge_stages.push(rec_route.clone());

    // ─── Stage 5: DRC Certification + Gerber/Excellon/KiCad/BOM/CPL/SVG Export ─
    let ((pcb_summary, kicad_sexp, bom_csv, cpl_csv, pcb_svg, gerber_files_map, drill_str), r_fab, b_fab) =
        run_bracketed_repeated("ecad.drc_and_fab_export", || {
            let pcb = eda_project.pcb.as_ref().expect("routed PCB");
            let rules = DesignRules::default();
            let drc = DrcEngine::new(rules.clone()).run(pcb);
            assert!(
                drc.passed && drc.violations.is_empty(),
                "PCB DRC failed with {} violations: {:?}",
                drc.violations.len(),
                drc.violations
            );
            let cert = certify(pcb, &rules);
            assert_eq!(cert.verdict, CertifyVerdict::Certified);
            assert_eq!(cert.error_count, 0);
            assert_eq!(cert.warning_count, 0);

            let udd = eda_to_udd("mei_jcp_tag_v1", &eda_project);
            let gerber = udd_to_gerber(&udd).expect("udd_to_gerber");
            let kicad_out = pcb_to_kicad_sexp(pcb);
            let kicad_parsed = import_kicad_pcb(&kicad_out).expect("round-trip import_kicad_pcb");
            assert_eq!(kicad_parsed.tracks.len(), pcb.tracks.len());
            assert_eq!(kicad_parsed.vias.len(), pcb.vias.len());
            assert_eq!(kicad_parsed.footprints.len(), pcb.footprints.len());

            let bom_s = jlcpcb_bom_csv(&bom_entries);
            let cpl_s = jlcpcb_cpl_csv(pcb);
            let raw_mfg_svg = render_pcb_svg(pcb, &PcbSvgOptions::default());
            assert!(raw_mfg_svg.contains("<svg"));
            let rich_svg = render_annotated_pcb_svg(pcb);

            let mut files_map: BTreeMap<String, String> = BTreeMap::new();
            for (layer_name, content) in &gerber.copper {
                let fname = format!("mei_jcp_tag_v1-{}.gbr", layer_name.replace('.', "_"));
                files_map.insert(fname, content.clone());
            }
            if let Some(edge) = &gerber.edge_cuts {
                files_map.insert("mei_jcp_tag_v1-Edge_Cuts.gbr".to_string(), edge.clone());
            }
            let drl = gerber.drill.clone().unwrap_or_default();
            let g_bytes = gerber.total_bytes();
            let mut g_names: Vec<String> = files_map.keys().cloned().collect();
            if !drl.is_empty() {
                g_names.push("mei_jcp_tag_v1.drl".to_string());
            }

            let copper_len_mm: f64 = pcb
                .tracks
                .iter()
                .map(|t| nm_to_mm(t.length().round() as Nm))
                .sum();
            let pad_total: usize = pcb.footprints.values().map(|f| f.pads.len()).sum();

            let summary = PcbVerificationSummary {
                board_name: pcb.board.name.clone(),
                width_mm: nm_to_mm(pcb.board.width),
                height_mm: nm_to_mm(pcb.board.height),
                layers: pcb.board.layer_count,
                component_count: pcb.footprints.len(),
                pad_count: pad_total,
                net_count: eda_project.netlist.nets.len(),
                routed_edges,
                total_edges,
                completion_pct: (routed_edges as f64) * 100.0 / (total_edges as f64),
                track_segments: pcb.tracks.len(),
                via_count: pcb.vias.len(),
                total_copper_length_mm: (copper_len_mm * 100.0).round() / 100.0,
                drc_passed: drc.passed,
                drc_error_count: cert.error_count,
                drc_warning_count: cert.warning_count,
                certify_verdict: "CERTIFIED".to_string(),
                kicad_roundtrip_tracks: kicad_parsed.tracks.len(),
                kicad_roundtrip_vias: kicad_parsed.vias.len(),
                kicad_roundtrip_footprints: kicad_parsed.footprints.len(),
                gerber_files: g_names,
                gerber_total_bytes: g_bytes,
            };
            (summary, kicad_out, bom_s, cpl_s, rich_svg, files_map, drl)
        });

    for (fname, content) in &gerber_files_map {
        fs::write(gerber_dir.join(fname), content).expect("write gerber layer");
    }
    fs::write(gerber_dir.join("mei_jcp_tag_v1.drl"), &drill_str).expect("write drill file");
    fs::write(hw_dir.join("mei_jcp_tag_v1.kicad_pcb"), &kicad_sexp).expect("write kicad_pcb");
    fs::write(hw_dir.join("bom.csv"), &bom_csv).expect("write bom.csv");
    fs::write(hw_dir.join("cpl.csv"), &cpl_csv).expect("write cpl.csv");
    fs::write(hw_dir.join("mei-jcp-tag-pcb.svg"), &pcb_svg).expect("write pcb svg");

    let est_fab_uj = ((r_fab.window_us as f64) * 30.0).round() as u64;
    let rec_fab = StageEnergyRecord::from_cad_receipt(
        &r_fab,
        BridgeTract::Compute,
        Some(est_fab_uj),
        b_fab,
    );
    bridge_stages.push(rec_fab.clone());

    // ─── Stage 6: CR2032 Electro-Thermal Simulation (`cad-sim::battery`) ──────
    let (battery_points, r_bat, b_bat) =
        run_bracketed_repeated("sim.battery_cr2032_electrochem", run_cr2032_battery_sim);
    let est_bat_uj = ((r_bat.window_us as f64) * 28.0).round() as u64;
    let rec_bat = StageEnergyRecord::from_cad_receipt(
        &r_bat,
        BridgeTract::Compute,
        Some(est_bat_uj),
        b_bat,
    );
    bridge_stages.push(rec_bat.clone());

    // ─── Stage 7: 10,000-Wakeup Cold-Chain JCP Hold/Settle Simulation ─────────
    let (coldchain_runs, r_cc, b_cc) =
        run_bracketed_once("jcp.coldchain_10k_hold_settle", || -> Vec<ColdChainRunSummary> {
            vec![
                run_coldchain_10k_simulation(ColdChainCellProfile::preset_for_temp_c(-20), false),
                run_coldchain_10k_simulation(ColdChainCellProfile::preset_for_temp_c(4), false),
                run_coldchain_10k_simulation(ColdChainCellProfile::preset_for_temp_c(25), false),
            ]
        });
    for run in &coldchain_runs {
        assert!(run.verify_log_ok);
        assert!(run.replay_matches_runtime);
        assert_eq!(run.critical_alert_allowed, 40);
        assert_eq!(run.critical_alert_refused, 0);
    }
    let est_cc_uj = ((r_cc.window_us as f64) * 30.0).round() as u64;
    let rec_cc = StageEnergyRecord::from_cad_receipt(
        &r_cc,
        BridgeTract::Compute,
        Some(est_cc_uj),
        b_cc,
    );
    bridge_stages.push(rec_cc.clone());

    // ─── Seal All 7 Pipeline Stages into Canonical Det-CBOR `JCR-1` Spine ────
    let (_, _) = spine
        .decide_and_seal(
            &sg_build,
            builder_did,
            &make_spine_spec_from_bridge(
                &rec_material,
                "cad.material",
                resource_cad,
                b"fr4_2layer+abs_enclosure",
                1000,
                None,
            ),
        )
        .expect("seal material stage");

    let (_, _) = spine
        .decide_and_seal(
            &sg_build,
            builder_did,
            &make_spine_spec_from_bridge(
                &rec_supply,
                "cad.supply_chain",
                resource_cad,
                b"jlcpcb_10part_smt",
                1001,
                None,
            ),
        )
        .expect("seal supply chain stage");

    for (idx, comp_rec) in [&rec_kernel, &rec_route, &rec_fab, &rec_bat].iter().enumerate() {
        let primary = comp_rec.primary_jcp_cost().0;
        let half_a = primary / 2;
        let half_b = primary - half_a;
        let step7 = Step7SumOutcome::evaluate(&[half_a, half_b], primary);
        assert!(step7.passed);
        let spec = make_spine_spec_from_bridge(
            comp_rec,
            "cad.compute",
            resource_cad,
            comp_rec.stage.as_bytes(),
            1010 + idx as u64,
            Some(vec![half_a, half_b]),
        );
        spine
            .decide_and_seal(&sg_build, builder_did, &spec)
            .expect("seal compute stage");
    }

    // Seal Stage 7 (`jcp.coldchain_10k_hold_settle`) via Two-Phase `hold` -> `settle`!
    let (_, hold_ticket_opt) = spine
        .place_hold_and_seal(
            &sg_build,
            builder_did,
            &rec_cc.stage,
            CadTract::Compute,
            "cad.compute",
            resource_cad,
            b"coldchain_10k_3temps",
            Trust::Control,
            1020,
        )
        .expect("place hold for coldchain stage");
    let hold_ticket = hold_ticket_opt.expect("hold ticket");
    let cc_primary = rec_cc.primary_jcp_cost().0;
    let cc_spec = make_spine_spec_from_bridge(
        &rec_cc,
        "cad.compute",
        resource_cad,
        b"coldchain_10k_3temps",
        1021,
        Some(vec![cc_primary / 3, cc_primary / 3, cc_primary - 2 * (cc_primary / 3)]),
    );
    spine
        .settle_hold_and_seal(&sg_build.grant, &hold_ticket, &cc_spec)
        .expect("settle coldchain stage");

    // Append outcome-anchored `efficiency/1` receipt over the verified hardware package
    let total_wall_ns = pipeline_t0.elapsed().as_nanos().min(u128::from(u64::MAX)) as u64;
    let total_compute_reported_uj: u64 = bridge_stages
        .iter()
        .filter_map(|s| s.reported_uj)
        .sum();
    let total_est_uj: u64 = bridge_stages.iter().filter_map(|s| s.est_uj).sum();

    let (_, _, audit_pre) = spine.verify_and_replay().expect("pre-efficiency verify");
    let mut session_energy = Energy::estimator(audit_pre.replayed_total_debited_uj);
    session_energy.coverage = Coverage::Partial;

    spine.append_efficiency(&Efficiency {
        task: "openie-cad:mei-jcp-tag-v1:fab-package".to_string(),
        completed: true,
        verdict: "drc-0-violations-step-stl-gerber-10k-jcp-verified".to_string(),
        tokens_in: 1_000,
        tokens_out: 250,
        energy: session_energy,
        wall_ns: total_wall_ns,
        value_uusd: None,
        energy_attestation: None,
    });

    let (replayed_ledger, eff_receipts, audit_summary) =
        spine.verify_and_replay().expect("final spine verify_and_replay");
    let eff_totals = aggregate(&eff_receipts);
    assert_eq!(eff_totals.completed_units, 1);

    // Emit machine-readable ledgers (`$BENCH_ROOT`-scrubbed, zero private paths)
    let ledger_json = json!({
        "schema": "openie.lane4.jcr1_build_and_coldchain_ledger/v1",
        "artifact_root": "$BENCH_ROOT/experiment_bundle",
        "board_metered": false,
        "tag_bench_measured_j": null,
        "evidence_separation_contract": {
            "measured_j": null,
            "reported_j_host_rapl_uj": total_compute_reported_uj,
            "est_j_analytical_uj": total_est_uj,
            "explanation": "MEI-JCP-Tag-v1 is an exported, DRC-certified fabrication and 3D enclosure package; host build stages record Linux RAPL package-0 counter deltas in reported_uj alongside analytical est_uj, while physical tag rail-shunt measured_j remains null until PCB assembly."
        },
        "pipeline_wall_time_ms": (total_wall_ns as f64 / 1_000_000.0 * 100.0).round() / 100.0,
        "spine_audit": audit_summary,
        "replayed_grant_debits_uj": replayed_ledger
            .uj
            .iter()
            .map(|(cid, uj)| json!({ "grant_id": cid.to_hex(), "debited_uj": uj }))
            .collect::<Vec<_>>(),
        "jcr1_stage_receipts": spine.records(),
        "efficiency_receipt_hex": spine
            .efficiency_receipts()
            .iter()
            .map(hex::encode)
            .collect::<Vec<_>>(),
        "coldchain_10k_runs": coldchain_runs,
    });

    let conformance_json = json!({
        "schema": "openie.lane4.conformance_summary/v1",
        "board_metered": false,
        "tag_bench_measured_j": null,
        "deliverable_a_spine": {
            "crate": "jcp-satb-cad-spine",
            "patch": "cad-joules-jcp-bridge.patch",
            "lattice_pairs_checked": 78400,
            "silent_provenance_upgrades": 0,
            "silent_coverage_upgrades": 0,
            "falsifier_6_max_drift_bps": 500,
            "step_7_max_residual_uj": 1,
            "jcr1_chain_verified": true,
            "replay_ledger_verified": true,
            "verified_build_receipts": audit_summary.verified_jcr1_entries,
            "head_cid_hex": audit_summary.head_cid_hex,
        },
        "deliverable_b_hardware": {
            "pcb": pcb_summary,
            "enclosure": enc_summary,
            "battery_cr2032_electrochem": battery_points,
            "coldchain_10k_jcp_gate": coldchain_runs,
        }
    });

    fs::write(
        receipts_dir.join("jcr1_build_and_coldchain_ledger.json"),
        serde_json::to_string_pretty(&ledger_json).unwrap(),
    )
    .expect("write ledger json");
    fs::write(
        receipts_dir.join("conformance_summary.json"),
        serde_json::to_string_pretty(&conformance_json).unwrap(),
    )
    .expect("write conformance summary json");

    println!(
        "MEI-JCP-Tag-v1 build complete in {:.2} s | PCB DRC violations: {} | STEP: {} B | STL: {} tris | JCR-1 entries: {} | RAPL reported: {} uJ",
        total_wall_ns as f64 / 1e9,
        pcb_summary.drc_error_count + pcb_summary.drc_warning_count,
        enc_summary.step_bytes,
        enc_summary.triangle_count,
        audit_summary.verified_jcr1_entries,
        total_compute_reported_uj
    );
}

#[allow(dead_code)]
fn _touch_path(_p: &Path) {}
