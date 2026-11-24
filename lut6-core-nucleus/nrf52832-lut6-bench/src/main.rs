#![no_std]
#![no_main]

//! Bare-metal Nordic nRF52832-QFAA Cortex-M4F (`thumbv7em-none-eabihf`, `64 KB` SRAM)
//! Zero-Allocation, Zero-Float `#![no_std]` `lut6-core` 3-Part `Nucleus` Firmware:
//!   - Places `16,384`-byte `CrystalArena16K` in `64 KiB` SRAM `@ 0x2000_0000` (`.lut6_sram`),
//!     leaving `~49 KiB` (`74.9%`) free SRAM for stack and BLE/sensor state.
//!   - Frames scalar `evaluate` and 64-lane bit-sliced `eval_batch_64` bursts with:
//!       * ARMv7E-M `DWT->CYCCNT` (`0xE000_1004`) cycle counter
//!       * nRF52 `P0` (`0x5000_0508`/`0x5000_050C`) pin P0.17 shunt trigger
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

// ARMv7E-M CoreDebug & DWT cycle counter registers
const DEMCR: *mut u32 = 0xE000_EDFC as *mut u32;
const DWT_CTRL: *mut u32 = 0xE000_1000 as *mut u32;
const DWT_CYCCNT: *mut u32 = 0xE000_1004 as *mut u32;

// Nordic nRF52832 GPIO P0 (`0x5000_0500`) atomic set/clear registers (P0.17)
const NRF_P0_OUTSET: *mut u32 = 0x5000_0508 as *mut u32;
const NRF_P0_OUTCLR: *mut u32 = 0x5000_050C as *mut u32;
const NRF_P0_DIRSET: *mut u32 = 0x5000_0518 as *mut u32;
const P0_17_MASK: u32 = 1 << 17;

#[repr(C)]
pub struct Nrf52Mailbox {
    pub scalar_cycles_64: u32,
    pub bitsliced_cycles_64: u32,
    pub checksum: u64,
    pub last_operon: u8,
}

struct SyncCell<T>(UnsafeCell<T>);
unsafe impl<T> Sync for SyncCell<T> {}

const fn build_nrf52_knowledge_seed() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(0x5283_2064_C0DE_0004, 2, 16, 3);
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

#[unsafe(link_section = ".lut6_sram")]
#[unsafe(no_mangle)]
static NRF52_NUCLEUS: SyncCell<Nucleus> =
    SyncCell(UnsafeCell::new(Nucleus::new_bootstrap(build_nrf52_knowledge_seed())));

#[unsafe(no_mangle)]
static NRF52_MAILBOX: SyncCell<Nrf52Mailbox> = SyncCell(UnsafeCell::new(Nrf52Mailbox {
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
        write_volatile(DWT_CYCCNT, 0);
        write_volatile(DWT_CTRL, read_volatile(DWT_CTRL) | 1);
    }
}

#[unsafe(no_mangle)]
pub unsafe extern "C" fn Reset() -> ! {
    unsafe {
        let mut src = &raw const __silut6;
        let mut dst = &raw mut __slut6;
        let end = &raw mut __elut6;
        while dst < end {
            write_volatile(dst, read_volatile(src));
            dst = dst.add(1);
            src = src.add(1);
        }

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

    nrf52_bench_entry()
}

#[inline(never)]
fn nrf52_bench_entry() -> ! {
    unsafe {
        write_volatile(NRF_P0_OUTCLR, P0_17_MASK);
        write_volatile(NRF_P0_DIRSET, P0_17_MASK);
        dwt_init();
    }

    let nuc = unsafe { &mut *NRF52_NUCLEUS.0.get() };
    let mut states = [0u64; 64];
    let mut i = 0usize;
    while i < 64 {
        states[i] = ((i as u64) & 0x3F) | (((i as u64) * 0x0101_0101) << 12);
        i += 1;
    }

    let mut acc: u64 = 0;
    let c0 = unsafe {
        write_volatile(NRF_P0_OUTSET, P0_17_MASK);
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
        write_volatile(NRF_P0_OUTCLR, P0_17_MASK);
        now
    };

    let b0 = unsafe {
        write_volatile(NRF_P0_OUTSET, P0_17_MASK);
        read_volatile(DWT_CYCCNT)
    };
    let batch_out = nuc.arena.knowledge_root.eval_batch_64(&states);
    let b1 = unsafe {
        let now = read_volatile(DWT_CYCCNT);
        write_volatile(NRF_P0_OUTCLR, P0_17_MASK);
        now
    };

    let mut m = 0usize;
    while m < 64 {
        acc ^= batch_out[m];
        m += 1;
    }

    let _active = nuc.step_agency(AgencyStateWord::new(
        BUS_PIO_SPI | 0b01,
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
        let mb = &mut *NRF52_MAILBOX.0.get();
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
