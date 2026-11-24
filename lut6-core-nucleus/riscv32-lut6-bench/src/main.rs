#![no_std]
#![no_main]

//! Bare-metal RV32IMAC (`riscv32imac-unknown-none-elf`, `64 KB` SRAM)
//! Zero-Allocation, Zero-Float `#![no_std]` `lut6-core` 3-Part `Nucleus` Firmware:
//!   - Places `16,384`-byte `CrystalArena16K` in `64 KiB` SRAM `@ 0x8000_0000` (`.lut6_sram`).
//!   - Frames scalar `evaluate` and 64-lane bit-sliced `eval_batch_64` bursts with:
//!       * RISC-V Machine Cycle Counter CSR (`csrr rd, mcycle`)
//!       * SiFive FE310/E31 GPIO `OUTPUT_VAL` (`0x1001_200C`) shunt trigger
//!   - Issues RISC-V `fence` + `wfi` sleep on `STOP_HALT (0x00)`.

use core::arch::{asm, global_asm};
use core::cell::UnsafeCell;
use core::panic::PanicInfo;
use core::ptr::{read_volatile, write_volatile};

use lut6_core::bootstrap::{
    AgencyStateWord, BUS_PIO_SPI, HOMEO_CONFORMAL_IN_BOUNDS, HOMEO_GOAL_PENDING, STOP_HALT,
};
use lut6_core::nucleus::Nucleus;
use lut6_core::{CompactLut6Page, EvalOutcome, FLAG_VALIDATED, FLAG_WOBBLE_CLEAN, wobble_codon_mask};

global_asm!(
    ".section .init, \"ax\"",
    ".global _start",
    "_start:",
    "    la sp, _stack_top",
    "    j Reset",
);

const GPIO_OUTPUT_EN: *mut u32 = 0x1001_2008 as *mut u32;
const GPIO_OUTPUT_VAL: *mut u32 = 0x1001_200C as *mut u32;
const GPIO_PIN0_MASK: u32 = 1 << 0;

#[repr(C)]
pub struct Rv32Mailbox {
    pub scalar_mcycle_64: u32,
    pub bitsliced_mcycle_64: u32,
    pub checksum: u64,
    pub last_operon: u8,
}

struct SyncCell<T>(UnsafeCell<T>);
unsafe impl<T> Sync for SyncCell<T> {}

const fn build_rv32_knowledge_seed() -> CompactLut6Page {
    let mut p = CompactLut6Page::new_blank(0x3210_AC64_C0DE_0005, 2, 16, 3);
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
static RV32_NUCLEUS: SyncCell<Nucleus> =
    SyncCell(UnsafeCell::new(Nucleus::new_bootstrap(build_rv32_knowledge_seed())));

#[unsafe(no_mangle)]
static RV32_MAILBOX: SyncCell<Rv32Mailbox> = SyncCell(UnsafeCell::new(Rv32Mailbox {
    scalar_mcycle_64: 0,
    bitsliced_mcycle_64: 0,
    checksum: 0,
    last_operon: 0xFF,
}));

unsafe extern "C" {
    static mut __slut6: u32;
    static mut __elut6: u32;
    static __silut6: u32;
    static mut __sdata: u32;
    static mut __edata: u32;
    static __sidata: u32;
    static mut __sbss: u32;
    static mut __ebss: u32;
}

#[inline(always)]
fn read_mcycle() -> u32 {
    let v: u32;
    unsafe {
        asm!("csrr {0}, mcycle", out(reg) v, options(nomem, nostack));
    }
    v
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

    rv32_bench_entry()
}

#[inline(never)]
fn rv32_bench_entry() -> ! {
    unsafe {
        write_volatile(GPIO_OUTPUT_VAL, read_volatile(GPIO_OUTPUT_VAL) & !GPIO_PIN0_MASK);
        write_volatile(GPIO_OUTPUT_EN, read_volatile(GPIO_OUTPUT_EN) | GPIO_PIN0_MASK);
    }

    let nuc = unsafe { &mut *RV32_NUCLEUS.0.get() };
    let mut states = [0u64; 64];
    let mut i = 0usize;
    while i < 64 {
        states[i] = ((i as u64) & 0x3F) | (((i as u64) * 0x0101_0101) << 12);
        i += 1;
    }

    let mut acc: u64 = 0;
    let c0 = unsafe {
        write_volatile(GPIO_OUTPUT_VAL, read_volatile(GPIO_OUTPUT_VAL) | GPIO_PIN0_MASK);
        read_mcycle()
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
        let now = read_mcycle();
        write_volatile(GPIO_OUTPUT_VAL, read_volatile(GPIO_OUTPUT_VAL) & !GPIO_PIN0_MASK);
        now
    };

    let b0 = unsafe {
        write_volatile(GPIO_OUTPUT_VAL, read_volatile(GPIO_OUTPUT_VAL) | GPIO_PIN0_MASK);
        read_mcycle()
    };
    let batch_out = nuc.arena.knowledge_root.eval_batch_64(&states);
    let b1 = unsafe {
        let now = read_mcycle();
        write_volatile(GPIO_OUTPUT_VAL, read_volatile(GPIO_OUTPUT_VAL) & !GPIO_PIN0_MASK);
        now
    };

    let mut m = 0usize;
    while m < 64 {
        acc ^= batch_out[m];
        m += 1;
    }

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
        let mb = &mut *RV32_MAILBOX.0.get();
        write_volatile(&raw mut mb.scalar_mcycle_64, c1.wrapping_sub(c0));
        write_volatile(&raw mut mb.bitsliced_mcycle_64, b1.wrapping_sub(b0));
        write_volatile(&raw mut mb.checksum, acc);
        write_volatile(&raw mut mb.last_operon, halt_frame.opcode());
    }

    loop {
        if halt_frame.is_sleep_wfi() {
            unsafe {
                asm!("fence iorw, iorw", "wfi", options(nomem, nostack));
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
