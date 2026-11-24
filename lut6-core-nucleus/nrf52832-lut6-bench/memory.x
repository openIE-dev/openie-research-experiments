/* Nordic Semiconductor nRF52832-QFAA Cortex-M4F Linker Script
 *   - On-Chip Flash: 0x0000_0000 (512 KiB XIP code & crystal LMA)
 *   - On-Chip SRAM:  0x2000_0000 (64 KiB = 65,536 B total single-cycle RAM)
 */
MEMORY
{
  FLASH (rx)  : ORIGIN = 0x00000000, LENGTH = 512K
  SRAM  (rwx) : ORIGIN = 0x20000000, LENGTH = 64K
}

ENTRY(Reset);

SECTIONS
{
  .vector_table ORIGIN(FLASH) :
  {
    KEEP(*(.vector_table));
  } > FLASH

  .text : ALIGN(4)
  {
    *(.text .text.*);
    . = ALIGN(4);
  } > FLASH

  .rodata : ALIGN(8)
  {
    *(.rodata .rodata.*);
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
    *(.data .data.*);
    . = ALIGN(4);
    __edata = .;
  } > SRAM AT > FLASH
  __sidata = LOADADDR(.data);

  .bss (NOLOAD) : ALIGN(4)
  {
    __sbss = .;
    *(.bss .bss.* COMMON);
    . = ALIGN(4);
    __ebss = .;
  } > SRAM

  _stack_top = ORIGIN(SRAM) + LENGTH(SRAM);

  /DISCARD/ :
  {
    *(.ARM.exidx .ARM.exidx.* .ARM.extab .ARM.extab.*);
  }
}
