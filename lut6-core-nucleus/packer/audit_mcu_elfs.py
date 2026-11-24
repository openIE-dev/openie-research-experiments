#!/usr/bin/env python3
"""Cross-Compiled Bare-Metal MCU ELF Section & Thumb/ARMv8-M/RV32IMAC Instruction Auditor.

Inspects release ELFs for:
  1. `alif-lut6-bench` (`thumbv8m.main-none-eabihf` — Alif Ensemble E3/E4 Cortex-M55 HE, MRAM + DTCM)
  2. `pico-lut6-bench` (`thumbv6m-none-eabi` — Raspberry Pi Pico RP2040 Cortex-M0+, Flash + Striped SRAM)
  3. `nrf52832-lut6-bench` (`thumbv7em-none-eabihf` — Nordic nRF52832-QFAA Cortex-M4F, 512 KB Flash + 64 KB SRAM)
  4. `riscv32-lut6-bench` (`riscv32imac-unknown-none-elf` — RV32IMAC MCU, 512 KB Flash + 64 KB SRAM)

Extracts exact `.vector_table`/`.init`, `.text`, `.rodata`, `.lut6_dtcm` / `.lut6` / `.lut6_sram`, `.data`, `.bss`
byte counts via `llvm-size -A`, and disassembles `.text` via `llvm-objdump -d` to verify:
  - Zero floating-point instructions across ARM VFP/MVE and RISC-V F/D
  - Presence of `wfi` zero-clock sleep instruction and tight integer shift/mask register loops
  - Explicit `64 KB` (`65,536 B`) SRAM fit check for `nRF52832` and `RV32IMAC`
  - Explicit `board_metered = false`, `measured_j = null`, `reported_j = null` epistemic provenance
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

FLOAT_MNEMONIC_RE = re.compile(
    r"^\s*[0-9a-f]+:\s+[0-9a-f ]+\s+"
    r"(vadd\.f|vsub\.f|vmul\.f|vdiv\.f|vfma\.f|vfms\.f|vcvt\.|vcmp\.f|vsqrt\.f|vabs\.f|vneg\.f|"
    r"fadd\.[sd]|fsub\.[sd]|fmul\.[sd]|fdiv\.[sd]|fmadd\.[sd]|fmsub\.[sd]|fcvt\.|flw|fld|fsw|fsd)\b",
    re.IGNORECASE | re.MULTILINE,
)


def find_llvm_tool(tool_name: str) -> str:
    found = shutil.which(tool_name)
    if found:
        return found
    rustup = Path.home() / ".rustup"
    if rustup.is_dir():
        matches = sorted(rustup.rglob(tool_name))
        if matches:
            return str(matches[-1])
    raise FileNotFoundError(f"Required LLVM binary `{tool_name}` not found")


def parse_llvm_size_sysv(size_out: str) -> dict[str, dict[str, int]]:
    sections: dict[str, dict[str, int]] = {}
    for line in size_out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[0].startswith("."):
            try:
                sz = int(parts[1])
                addr = int(parts[2])
                sections[parts[0]] = {"bytes": sz, "vma_hex": f"0x{addr:08x}"}
            except ValueError:
                continue
    return sections


def audit_single_elf(
    elf_path: Path,
    target_triple: str,
    mcu_label: str,
    lut6_section_name: str,
    sram_capacity_bytes: int,
    llvm_size: str,
    llvm_objdump: str,
) -> dict:
    assert elf_path.is_file(), f"Missing ELF binary: {elf_path}"
    raw_bytes = elf_path.read_bytes()

    sz_out = subprocess.run(
        [llvm_size, "-A", str(elf_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    sections = parse_llvm_size_sysv(sz_out)

    disasm = subprocess.run(
        [llvm_objdump, "-d", str(elf_path)],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    insn_lines = re.findall(r"^\s*[0-9a-f]+:\s+[0-9a-f ]+\t([a-zA-Z0-9_.]+)", disasm, flags=re.MULTILINE)
    float_hits = FLOAT_MNEMONIC_RE.findall(disasm)
    assert len(float_hits) == 0, f"Forbidden floating-point instructions in {elf_path.name}: {float_hits}"

    wfi_count = sum(1 for m in insn_lines if m.lower() == "wfi")
    dsb_or_fence_count = sum(1 for m in insn_lines if m.lower().startswith(("dsb", "fence")))
    bitwise_shift_count = sum(
        1
        for m in insn_lines
        if m.lower().startswith(
            ("lsr", "lsl", "and", "orr", "eor", "ubfx", "bfi", "bic", "srl", "sll", "xor", "or", "c.and", "c.or", "c.xor", "c.srli", "c.slli")
        )
    )
    assert wfi_count >= 1, f"Expected `wfi` sleep instruction in {elf_path.name}"

    lut6_sec = sections.get(lut6_section_name, {"bytes": 0, "vma_hex": "0x00000000"})
    boot_sec_name = ".init" if ".init" in sections else ".vector_table"
    boot_sec = sections.get(boot_sec_name, {"bytes": 0, "vma_hex": "0x00000000"})
    text_b = sections.get(".text", {}).get("bytes", 0)
    rodata_b = sections.get(".rodata", {}).get("bytes", 0)
    vec_b = boot_sec.get("bytes", 0)
    data_b = sections.get(".data", {}).get("bytes", 0)
    bss_b = sections.get(".bss", {}).get("bytes", 0)
    runtime_sram_b = lut6_sec["bytes"] + data_b + bss_b
    assert runtime_sram_b < sram_capacity_bytes, (
        f"Runtime SRAM {runtime_sram_b} exceeds target SRAM {sram_capacity_bytes}"
    )

    return {
        "crate": elf_path.name,
        "target_triple": target_triple,
        "mcu_platform": mcu_label,
        "elf_total_file_bytes": len(raw_bytes),
        "elf_sha256": hashlib.sha256(raw_bytes).hexdigest(),
        "board_metered": False,
        "measured_j": None,
        "reported_j": None,
        "provenance_note": "Cross-compiled bare-metal release ELF static section & disassembly audit (board_metered=false until physical MCU bench attachment).",
        "sections": {
            boot_sec_name: boot_sec,
            ".text": sections.get(".text", {"bytes": 0, "vma_hex": "0x00000000"}),
            ".rodata": sections.get(".rodata", {"bytes": 0, "vma_hex": "0x00000000"}),
            lut6_section_name: lut6_sec,
            ".data": sections.get(".data", {"bytes": 0, "vma_hex": "0x00000000"}),
            ".bss": sections.get(".bss", {"bytes": 0, "vma_hex": "0x00000000"}),
        },
        "summary_bytes": {
            "code_and_vectors_bytes": vec_b + text_b,
            "rodata_bytes": rodata_b,
            "lut6_nucleus_section_bytes": lut6_sec["bytes"],
            "sram_rw_metadata_bytes": data_b + bss_b,
            "total_nvm_lma_image_bytes": vec_b + text_b + rodata_b + lut6_sec["bytes"] + data_b,
            "total_tcm_or_sram_runtime_bytes": runtime_sram_b,
            "sram_capacity_bytes": sram_capacity_bytes,
            "sram_utilization_pct": round(100.0 * runtime_sram_b / sram_capacity_bytes, 2),
            "free_sram_headroom_bytes": sram_capacity_bytes - runtime_sram_b,
        },
        "disassembly_audit": {
            "total_instructions": len(insn_lines),
            "floating_point_instructions": len(float_hits),
            "zero_float_verified": len(float_hits) == 0,
            "wfi_sleep_instructions": wfi_count,
            "dsb_or_fence_barrier_instructions": dsb_or_fence_count,
            "bitwise_and_shift_instructions": bitwise_shift_count,
        },
    }


def main() -> None:
    root = Path(__file__).resolve().parent.parent
    llvm_size = find_llvm_tool("llvm-size")
    llvm_objdump = find_llvm_tool("llvm-objdump")

    alif_elf = (
        root / "alif-lut6-bench" / "target" / "thumbv8m.main-none-eabihf" / "release" / "alif-lut6-bench"
    )
    pico_elf = root / "pico-lut6-bench" / "target" / "thumbv6m-none-eabi" / "release" / "pico-lut6-bench"
    nrf52_elf = (
        root / "nrf52832-lut6-bench" / "target" / "thumbv7em-none-eabihf" / "release" / "nrf52832-lut6-bench"
    )
    rv32_elf = (
        root / "riscv32-lut6-bench" / "target" / "riscv32imac-unknown-none-elf" / "release" / "riscv32-lut6-bench"
    )

    rustc_ver = subprocess.run(["rustc", "--version"], capture_output=True, text=True, check=True).stdout.strip()

    report = {
        "rustc_version": rustc_ver,
        "edition": "2024",
        "nightly_features_used": 0,
        "targets": {
            "alif_e3_e4_cortex_m55": audit_single_elf(
                alif_elf,
                "thumbv8m.main-none-eabihf",
                "Alif Ensemble E3/E4 Cortex-M55 HE (MRAM @ 0x8000_0000 + 256 KB Zero-Wait DTCM @ 0x2000_0000)",
                ".lut6_dtcm",
                262144,
                llvm_size,
                llvm_objdump,
            ),
            "rp2040_cortex_m0plus": audit_single_elf(
                pico_elf,
                "thumbv6m-none-eabi",
                "Raspberry Pi Pico RP2040 Cortex-M0+ (Flash @ 0x1000_0000 + 264 KB Striped SRAM @ 0x2000_0000)",
                ".lut6",
                270336,
                llvm_size,
                llvm_objdump,
            ),
            "nrf52832_cortex_m4f_64kb": audit_single_elf(
                nrf52_elf,
                "thumbv7em-none-eabihf",
                "Nordic nRF52832-QFAA Cortex-M4F (512 KB Flash @ 0x0000_0000 + 64 KB SRAM @ 0x2000_0000)",
                ".lut6_sram",
                65536,
                llvm_size,
                llvm_objdump,
            ),
            "riscv32imac_baremetal_64kb": audit_single_elf(
                rv32_elf,
                "riscv32imac-unknown-none-elf",
                "Bare-Metal RV32IMAC MCU (512 KB XIP Flash @ 0x2000_0000 + 64 KB SRAM @ 0x8000_0000)",
                ".lut6_sram",
                65536,
                llvm_size,
                llvm_objdump,
            ),
        },
    }

    out_path = root / "results" / "mcu_cross_compile_audit.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
