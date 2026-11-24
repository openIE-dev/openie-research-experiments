/* Alif Ensemble E3/E4 High-Efficiency Cortex-M55 Linker Script
 *   - Non-Volatile MRAM:   0x8000_0000 (1.5 MiB XIP code & crystal LMA)
 *   - Zero-Wait-State DTCM: 0x2000_0000 (256 KiB single-cycle Tightly Coupled Data Memory)
 */
MEMORY
{
  MRAM (rx)  : ORIGIN = 0x80000000, LENGTH = 1536K
  DTCM (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
}

ENTRY(Reset);

SECTIONS
{
  .vector_table ORIGIN(MRAM) :
  {
    KEEP(*(.vector_table));
  } > MRAM

  .text : ALIGN(4)
  {
    *(.text .text.*);
    . = ALIGN(4);
  } > MRAM

  .rodata : ALIGN(8)
  {
    *(.rodata .rodata.*);
    . = ALIGN(8);
  } > MRAM

  .lut6_dtcm ORIGIN(DTCM) : ALIGN(8)
  {
    __slut6 = .;
    KEEP(*(.lut6_dtcm .lut6_dtcm.*));
    . = ALIGN(8);
    __elut6 = .;
  } > DTCM AT > MRAM
  __silut6 = LOADADDR(.lut6_dtcm);

  .data : ALIGN(4)
  {
    __sdata = .;
    *(.data .data.*);
    . = ALIGN(4);
    __edata = .;
  } > DTCM AT > MRAM
  __sidata = LOADADDR(.data);

  .bss (NOLOAD) : ALIGN(4)
  {
    __sbss = .;
    *(.bss .bss.* COMMON);
    . = ALIGN(4);
    __ebss = .;
  } > DTCM

  _stack_top = ORIGIN(DTCM) + LENGTH(DTCM);

  /DISCARD/ :
  {
    *(.ARM.exidx .ARM.exidx.* .ARM.extab .ARM.extab.*);
  }
}
