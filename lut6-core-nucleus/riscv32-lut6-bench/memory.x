/* Bare-Metal RV32IMAC Microcontroller Linker Script (SiFive E31 / ESP32-C3/C6 Class)
 *   - XIP Flash:   0x2000_0000 (512 KiB code & crystal LMA)
 *   - On-Chip RAM: 0x8000_0000 (64 KiB = 65,536 B single-cycle SRAM)
 */
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x20000000, LENGTH = 512K
  SRAM  (rwx) : ORIGIN = 0x80000000, LENGTH = 64K
}

ENTRY(_start);

SECTIONS
{
  .init ORIGIN(FLASH) : ALIGN(4)
  {
    KEEP(*(.init .init.*));
  } > FLASH

  .text : ALIGN(4)
  {
    *(.text .text.*);
    . = ALIGN(4);
  } > FLASH

  .rodata : ALIGN(8)
  {
    *(.rodata .rodata.* .srodata .srodata.*);
    . = ALIGN(8);
  } > FLASH

  .lut6_sram ORIGIN(SRAM) : ALIGN(8)
  {
    __slut6 = .;
    KEEP(*(.lut6_sram .lut6_sram.*));
    . = ALIGN(8);
    __elut6 = .;
  } > SRAM AT > FLASH
  __silut6 = LOADADDR(.lut6_sram);

  .data : ALIGN(4)
  {
    __sdata = .;
    *(.data .data.* .sdata .sdata.*);
    . = ALIGN(4);
    __edata = .;
  } > SRAM AT > FLASH
  __sidata = LOADADDR(.data);

  .bss (NOLOAD) : ALIGN(4)
  {
    __sbss = .;
    *(.bss .bss.* .sbss .sbss.* COMMON);
    . = ALIGN(4);
    __ebss = .;
  } > SRAM

  _stack_top = ORIGIN(SRAM) + LENGTH(SRAM);

  /DISCARD/ :
  {
    *(.eh_frame .eh_frame.*);
  }
}
