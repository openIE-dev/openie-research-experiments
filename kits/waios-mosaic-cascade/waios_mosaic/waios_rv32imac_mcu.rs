// SPDX-License-Identifier: Apache-2.0
// Zero-FPU `#![no_std]` bare-metal RV32IMAC microcontroller program (`riscv32imac-unknown-none-elf`).
// Reads 32,768 signed ternary weights + 128 signed int8 activations on fd 0 and emits 256 LE i32s on fd 1.

#![no_std]
#![no_main]

use core::arch::asm;
use core::panic::PanicInfo;

const ROWS: usize = 256;
const COLS: usize = 128;
const IN_BYTES: usize = ROWS * COLS + COLS;

static mut IN_BUF: [u8; IN_BYTES] = [0u8; IN_BYTES];
static mut OUT_BUF: [i32; ROWS] = [0i32; ROWS];

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    unsafe { sys_exit(1) }
}

#[inline(always)]
unsafe fn sys_read(fd: usize, buf: *mut u8, len: usize) -> isize {
    let ret: isize;
    asm!(
        "ecall",
        inlateout("a0") fd => ret,
        in("a1") buf,
        in("a2") len,
        in("a7") 63usize,
    );
    ret
}

#[inline(always)]
unsafe fn sys_write(fd: usize, buf: *const u8, len: usize) -> isize {
    let ret: isize;
    asm!(
        "ecall",
        inlateout("a0") fd => ret,
        in("a1") buf,
        in("a2") len,
        in("a7") 64usize,
    );
    ret
}

#[inline(always)]
unsafe fn sys_exit(code: usize) -> ! {
    asm!(
        "ecall",
        in("a0") code,
        in("a7") 93usize,
        options(noreturn)
    )
}

#[no_mangle]
pub unsafe extern "C" fn _start() -> ! {
    let base_in = core::ptr::addr_of_mut!(IN_BUF) as *mut u8;
    let mut got: usize = 0;
    while got < IN_BYTES {
        let n = sys_read(0, base_in.add(got), IN_BYTES - got);
        if n <= 0 {
            sys_exit(2);
        }
        got += n as usize;
    }

    let w_ptr = base_in as *const i8;
    let a_ptr = base_in.add(ROWS * COLS) as *const i8;
    let out_ptr = core::ptr::addr_of_mut!(OUT_BUF) as *mut i32;

    let mut r: usize = 0;
    while r < ROWS {
        let mut acc: i32 = 0;
        let row_off = r * COLS;
        let mut c: usize = 0;
        while c < COLS {
            let w = *w_ptr.add(row_off + c) as i32;
            let a = *a_ptr.add(c) as i32;
            if w == 1 {
                acc += a;
            } else if w == -1 {
                acc -= a;
            }
            c += 1;
        }
        *out_ptr.add(r) = acc.to_le();
        r += 1;
    }

    let out_bytes = core::ptr::addr_of!(OUT_BUF) as *const u8;
    let mut written: usize = 0;
    let total_out = ROWS * 4;
    while written < total_out {
        let n = sys_write(1, out_bytes.add(written), total_out - written);
        if n <= 0 {
            sys_exit(3);
        }
        written += n as usize;
    }
    sys_exit(0);
}
