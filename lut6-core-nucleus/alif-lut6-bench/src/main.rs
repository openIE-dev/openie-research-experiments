#![no_std]
#![no_main]

//! Bare-metal Alif Ensemble E3/E4 Cortex-M55 HE (`thumbv8m.main-none-eabihf`)
//! Zero-Allocation `#![no_std]` `lut6-core` 3-Part `Nucleus` Benchmark Firmware:
//!   - Places `16,384`-byte `CrystalArena16K` in Zero-Wait `DTCM @ 0x2000_0000` (`.lut6_dtcm`).
//!   - Frames scalar `evaluate` and 64-lane bit-sliced `eval_batch_64` bursts with:
//!       * ARMv8.1-M `DWT->CYCCNT` (`0xE000_1004`) cycle counter
//!       * Alif `LPGPIO_0` (`0x4200_2000`) pin-0 hardware shunt trigger
//!   - Enters zero-clock `WFI` sleep when `SEED_AGENCY` dispatches `STOP_HALT (0x00)`.

use core::arch::asm;
use core::cell::UnsafeCell;
use core::panic::PanicInfo;
use core::ptr::{read_volatile, write_volatile};

use lut6_core::bootstrap::{
    AgencyStateWord, BUS_PIO_SPI, HOMEO_CONFORMAL_IN_BOUNDS, HOMEO_GOAL_PENDING, STOP_HALT,
};
use lut6_core::nucleus::Nucleus;
use lut6_core::{CompactLut6Page, EvalOutcome, FLAG_VALIDATED, FLAG_WOBBLE_CLEAN, wobble_codon_mask};

// ARMv8.1-M CoreDebug & DWT cycle counter registers
const DEMCR: *mut u32 = 0xE000_EDFC as *mut u32;
const DWT_CTRL: *mut u32 = 0xE000_1000 as *mut u32;
const DWT_CYCCNT: *mut u32 = 0xE000_1004 as *mut u32;
const DWT_LAR: *mut u32 = 0xE000_1FB0 as *mut u32;

// Alif Ensemble E3/E4 LPGPIO_0 (`0x4200_2000`, DesignWare APB GPIO)
const LPGPIO0_DR: *mut u32 = 0x4200_2000 as *mut u32;
const LPGPIO0_DDR: *mut u32 = 0x4200_2004 as *mut u32;

#[repr(C)]
pub struct BenchMailbox {
    pub scalar_cycles_64: u32,
    pub bitsliced_cycles_64: u32,
    pub checksum: u64,
    pub last_operon: u8,
}

struct SyncCell<T>(UnsafeCell<T>);
unsafe impl<T> Sync for SyncCell<T> {}

const fn build_alif_knowledge_seed() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(0xA11F_E3E4_C0DE_0055, 2, 16, 3);
    p.flags = FLAG_VALIDATED | FLAG_WOBBLE_CLEAN;
    p.conformal_mask = 0x00FF_0000_0000_0000;
    p.override_mask = 0xFF00_0000_0000_0000;
    p.conformal_thresh = 1;
    let mut g = 0;
    while g < 16 {
        p.set_gate(0, g, [0, 1, 2, 3, 4, 5], wobble_codon_mask((g as u8) << 2));
        p.set_gate(1, g, [g as u8, ((g + 1) & 15) as u8, 0, 0, 0, 0], 0x6666_6666_6666_6666);
        g += 1;
    }
    p.seal_crc32();
    p
}

#[unsafe(link_section = ".lut6_dtcm")]
#[unsafe(no_mangle)]
static DTCM_NUCLEUS: SyncCell<Nucleus> =
    SyncCell(UnsafeCell::new(Nucleus::new_bootstrap(build_alif_knowledge_seed())));

#[unsafe(no_mangle)]
static BENCH_MAILBOX: SyncCell<BenchMailbox> = SyncCell(UnsafeCell::new(BenchMailbox {
    scalar_cycles_64: 0,
    bitsliced_cycles_64: 0,
    checksum: 0,
    last_operon: 0xFF,
}));

#[repr(C)]
pub union VectorEntry {
    pub handler: unsafe extern "C" fn() -> !,
    pub pointer: *const u32,
}

unsafe impl Sync for VectorEntry {}

unsafe extern "C" {
    static _stack_top: u32;
    static mut __slut6: u32;
    static mut __elut6: u32;
    static __silut6: u32;
    static mut __sdata: u32;
    static mut __edata: u32;
    static __sidata: u32;
    static mut __sbss: u32;
    static mut __ebss: u32;
}

#[unsafe(link_section = ".vector_table")]
#[unsafe(no_mangle)]
pub static VECTOR_TABLE: [VectorEntry; 2] = [
    VectorEntry {
        pointer: &raw const _stack_top,
    },
    VectorEntry { handler: Reset },
];

#[inline(always)]
unsafe fn dwt_init() {
    unsafe {
        write_volatile(DEMCR, read_volatile(DEMCR) | (1 << 24));
        write_volatile(DWT_LAR, 0xC5AC_CE55);
        write_volatile(DWT_CYCCNT, 0);
        write_volatile(DWT_CTRL, read_volatile(DWT_CTRL) | 1);
    }
}

#[inline(always)]
unsafe fn lpgpio0_frame_high() {
    unsafe {
        write_volatile(LPGPIO0_DR, read_volatile(LPGPIO0_DR) | 1);
    }
}

#[inline(always)]
unsafe fn lpgpio0_frame_low() {
    unsafe {
        write_volatile(LPGPIO0_DR, read_volatile(LPGPIO0_DR) & !1);
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn Reset() -> ! {
    unsafe {
        // 1. Copy 16 KB `.lut6_dtcm` crystal arena from MRAM LMA (`0x8000_xxxx`) to Zero-Wait DTCM (`0x2000_0000`)
        let mut src = &raw const __silut6;
        let mut dst = &raw mut __slut6;
        let end = &raw mut __elut6;
        while dst < end {
            write_volatile(dst, read_volatile(src));
            dst = dst.add(1);
            src = src.add(1);
        }

        // 2. Copy `.data` and zero `.bss`
        let mut d_src = &raw const __sidata;
        let mut d_dst = &raw mut __sdata;
        let d_end = &raw mut __edata;
        while d_dst < d_end {
            write_volatile(d_dst, read_volatile(d_src));
            d_dst = d_dst.add(1);
            d_src = d_src.add(1);
        }

        let mut b_dst = &raw mut __sbss;
        let b_end = &raw mut __ebss;
        while b_dst < b_end {
            write_volatile(b_dst, 0);
            b_dst = b_dst.add(1);
        }
    }

    alif_bench_entry()
}

#[inline(never)]
fn alif_bench_entry() -> ! {
    unsafe {
        write_volatile(LPGPIO0_DDR, read_volatile(LPGPIO0_DDR) | 1);
        lpgpio0_frame_low();
        dwt_init();
    }

    let nuc = unsafe { &mut *DTCM_NUCLEUS.0.get() };
    let mut states = [0u64; 64];
    let mut i = 0usize;
    while i < 64 {
        states[i] = ((i as u64) & 0x3F) | (((i as u64) * 0x0101_0101) << 12);
        i += 1;
    }

    // Frame 1: 64 scalar `Nucleus::query_knowledge` evaluations in Zero-Wait DTCM
    let mut acc: u64 = 0;
    let c0 = unsafe {
        lpgpio0_frame_high();
        read_volatile(DWT_CYCCNT)
    };
    let mut k = 0usize;
    while k < 64 {
        let Ok(out) = nuc.query_knowledge(states[k]);
        if let EvalOutcome::Act { output, .. } = out {
            acc = acc.wrapping_add(output);
        }
        k += 1;
    }
    let c1 = unsafe {
        let now = read_volatile(DWT_CYCCNT);
        lpgpio0_frame_low();
        now
    };

    // Frame 2: 64-lane vertical bit-sliced `eval_batch_64` in Zero-Wait DTCM
    let b0 = unsafe {
        lpgpio0_frame_high();
        read_volatile(DWT_CYCCNT)
    };
    let batch_out = nuc.arena.knowledge_root.eval_batch_64(&states);
    let b1 = unsafe {
        let now = read_volatile(DWT_CYCCNT);
        lpgpio0_frame_low();
        now
    };

    let mut m = 0usize;
    while m < 64 {
        acc ^= batch_out[m];
        m += 1;
    }

    // Dispatch Operon transition -> when goal completes (`goal_pending == 0`), `SEED_AGENCY` emits `STOP_HALT (0x00)`
    let _active = nuc.step_agency(AgencyStateWord::new(
        BUS_PIO_SPI | 0b10,
        HOMEO_GOAL_PENDING | HOMEO_CONFORMAL_IN_BOUNDS,
        0,
        1,
        acc as u32,
    ));
    let halt_frame = nuc.step_agency(AgencyStateWord::new(
        STOP_HALT | 0b01,
        HOMEO_CONFORMAL_IN_BOUNDS,
        0,
        2,
        0,
    ));

    unsafe {
        let mb = &mut *BENCH_MAILBOX.0.get();
        write_volatile(&raw mut mb.scalar_cycles_64, c1.wrapping_sub(c0));
        write_volatile(&raw mut mb.bitsliced_cycles_64, b1.wrapping_sub(b0));
        write_volatile(&raw mut mb.checksum, acc);
        write_volatile(&raw mut mb.last_operon, halt_frame.opcode());
    }

    loop {
        if halt_frame.is_sleep_wfi() {
            unsafe {
                asm!("dsb sy", "wfi", options(nomem, nostack));
            }
        }
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    loop {
        unsafe {
            asm!("wfi", options(nomem, nostack));
        }
    }
}
