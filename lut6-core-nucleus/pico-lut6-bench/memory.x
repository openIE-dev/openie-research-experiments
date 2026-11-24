/* Raspberry Pi Pico RP2040 Dual Cortex-M0+ Linker Script
 *   - QSPI XIP Flash: 0x1000_0000 (2 MiB)
 *   - Striped SRAM:   0x2000_0000 (256 KiB 4-way word-striped zero-wait SRAM0..3)
 *   - Scratch SRAM4:  0x2004_0000 (4 KiB dedicated Core-0 stack)
 */
MEMORY
{
  FLASH        (rx)  : ORIGIN = 0x10000000, LENGTH = 2048K
  SRAM_STRIPED (rwx) : ORIGIN = 0x20000000, LENGTH = 256K
  SRAM4        (rwx) : ORIGIN = 0x20040000, LENGTH = 4K
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

  .lut6 ORIGIN(SRAM_STRIPED) : ALIGN(8)
  {
    __slut6 = .;
    KEEP(*(.lut6 .lut6.*));
    . = ALIGN(8);
    __elut6 = .;
  } > SRAM_STRIPED AT > FLASH
  __silut6 = LOADADDR(.lut6);

  .data : ALIGN(4)
  {
    __sdata = .;
    *(.data .data.*);
    . = ALIGN(4);
    __edata = .;
  } > SRAM_STRIPED AT > FLASH
  __sidata = LOADADDR(.data);

  .bss (NOLOAD) : ALIGN(4)
  {
    __sbss = .;
    *(.bss .bss.* COMMON);
    . = ALIGN(4);
    __ebss = .;
  } > SRAM_STRIPED

  _stack_top = ORIGIN(SRAM4) + LENGTH(SRAM4);

  /DISCARD/ :
  {
    *(.ARM.exidx .ARM.exidx.* .ARM.extab .ARM.extab.*);
  }
}
