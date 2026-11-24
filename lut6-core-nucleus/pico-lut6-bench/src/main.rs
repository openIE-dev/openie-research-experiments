#![no_std]
#![no_main]

//! Bare-metal Raspberry Pi Pico RP2040 Cortex-M0+ (`thumbv6m-none-eabi`)
//! Zero-Allocation `#![no_std]` `lut6-core` 3-Part `Nucleus` Benchmark Firmware:
//!   - Places `16,384`-byte `CrystalArena16K` in 4-bank Striped SRAM `@ 0x2000_0000` (`.lut6`).
//!   - Frames scalar `evaluate` and 64-lane bit-sliced `eval_batch_64` bursts with:
//!       * RP2040 Single-Cycle IO (`SIO @ 0xD000_0000`) GP2 shunt trigger
//!       * ARMv6-M 24-bit `SysTick` (`0xE000_E010`) + RP2040 `TIMERAWL` (`0x4005_4028`)
//!   - Issues `WFI` metabolic sleep on `STOP_HALT (0x00)`.

use core::arch::asm;
use core::cell::UnsafeCell;
use core::panic::PanicInfo;
use core::ptr::{read_volatile, write_volatile};

use lut6_core::bootstrap::{
    AgencyStateWord, BUS_PIO_SPI, HOMEO_CONFORMAL_IN_BOUNDS, HOMEO_GOAL_PENDING, STOP_HALT,
};
use lut6_core::nucleus::Nucleus;
use lut6_core::{CompactLut6Page, EvalOutcome, FLAG_VALIDATED, FLAG_WOBBLE_CLEAN, wobble_codon_mask};

// RP2040 Single-Cycle IO (`SIO`) GPIO registers (GP2 = bit 2)
const SIO_GPIO_OUT_SET: *mut u32 = 0xD000_0014 as *mut u32;
const SIO_GPIO_OUT_CLR: *mut u32 = 0xD000_0018 as *mut u32;
const SIO_GPIO_OE_SET: *mut u32 = 0xD000_0024 as *mut u32;
const GP2_PIN_MASK: u32 = 1 << 2;

// ARMv6-M 24-bit SysTick + RP2040 1 MHz timer
const SYST_CSR: *mut u32 = 0xE000_E010 as *mut u32;
const SYST_RVR: *mut u32 = 0xE000_E014 as *mut u32;
const SYST_CVR: *mut u32 = 0xE000_E018 as *mut u32;
const RP2040_TIMERAWL: *const u32 = 0x4005_4028 as *const u32;

#[repr(C)]
pub struct PicoMailbox {
    pub scalar_systick_64: u32,
    pub bitsliced_systick_64: u32,
    pub timer_us_delta: u32,
    pub checksum: u64,
    pub last_operon: u8,
}

struct SyncCell<T>(UnsafeCell<T>);
unsafe impl<T> Sync for SyncCell<T> {}

const fn build_pico_knowledge_seed() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(0x2040_C0DE_54A4_0001, 2, 16, 3);
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

#[unsafe(link_section = ".lut6")]
#[unsafe(no_mangle)]
static STRIPED_NUCLEUS: SyncCell<Nucleus> =
    SyncCell(UnsafeCell::new(Nucleus::new_bootstrap(build_pico_knowledge_seed())));

#[unsafe(no_mangle)]
static PICO_MAILBOX: SyncCell<PicoMailbox> = SyncCell(UnsafeCell::new(PicoMailbox {
    scalar_systick_64: 0,
    bitsliced_systick_64: 0,
    timer_us_delta: 0,
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
unsafe fn systick_init() {
    unsafe {
        write_volatile(SYST_RVR, 0x00FF_FFFF);
        write_volatile(SYST_CVR, 0);
        write_volatile(SYST_CSR, 0x05); // CLKSOURCE = processor clock, ENABLE = 1
    }
}

#[inline(always)]
unsafe fn systick_elapsed(start_down: u32, end_down: u32) -> u32 {
    (start_down.wrapping_sub(end_down)) & 0x00FF_FFFF
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

    pico_bench_entry()
}

#[inline(never)]
fn pico_bench_entry() -> ! {
    unsafe {
        write_volatile(SIO_GPIO_OUT_CLR, GP2_PIN_MASK);
        write_volatile(SIO_GPIO_OE_SET, GP2_PIN_MASK);
        systick_init();
    }

    let nuc = unsafe { &mut *STRIPED_NUCLEUS.0.get() };
    let mut states = [0u64; 64];
    let mut i = 0usize;
    while i < 64 {
        states[i] = ((i as u64) & 0x3F) | (((i as u64) * 0x0101_0101) << 12);
        i += 1;
    }

    let t_us0 = unsafe { read_volatile(RP2040_TIMERAWL) };

    // Frame 1: 64 scalar evaluations in RP2040 Striped SRAM
    let mut acc: u64 = 0;
    let s0 = unsafe {
        write_volatile(SIO_GPIO_OUT_SET, GP2_PIN_MASK);
        read_volatile(SYST_CVR)
    };
    let mut k = 0usize;
    while k < 64 {
        let Ok(out) = nuc.query_knowledge(states[k]);
        if let EvalOutcome::Act { output, .. } = out {
            acc = acc.wrapping_add(output);
        }
        k += 1;
    }
    let s1 = unsafe {
        let v = read_volatile(SYST_CVR);
        write_volatile(SIO_GPIO_OUT_CLR, GP2_PIN_MASK);
        v
    };

    // Frame 2: 64-lane vertical bit-sliced `eval_batch_64` in Striped SRAM
    let b0 = unsafe {
        write_volatile(SIO_GPIO_OUT_SET, GP2_PIN_MASK);
        read_volatile(SYST_CVR)
    };
    let batch_out = nuc.arena.knowledge_root.eval_batch_64(&states);
    let b1 = unsafe {
        let v = read_volatile(SYST_CVR);
        write_volatile(SIO_GPIO_OUT_CLR, GP2_PIN_MASK);
        v
    };

    let t_us1 = unsafe { read_volatile(RP2040_TIMERAWL) };

    let mut m = 0usize;
    while m < 64 {
        acc ^= batch_out[m];
        m += 1;
    }

    let _active = nuc.step_agency(AgencyStateWord::new(
        BUS_PIO_SPI | 0b11,
        HOMEO_GOAL_PENDING | HOMEO_CONFORMAL_IN_BOUNDS,
        1,
        1,
        acc as u32,
    ));
    let halt_frame = nuc.step_agency(AgencyStateWord::new(
        STOP_HALT | 0b10,
        HOMEO_CONFORMAL_IN_BOUNDS,
        1,
        2,
        0,
    ));

    unsafe {
        let mb = &mut *PICO_MAILBOX.0.get();
        write_volatile(&raw mut mb.scalar_systick_64, systick_elapsed(s0, s1));
        write_volatile(&raw mut mb.bitsliced_systick_64, systick_elapsed(b0, b1));
        write_volatile(&raw mut mb.timer_us_delta, t_us1.wrapping_sub(t_us0));
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
