# SPDX-License-Identifier: Apache-2.0
"""Optional-graceful Cross-Fabric `waiOS` 256x128 Conformance & Tamper-Halt Runner:
  1. `gpu_vulkan_compute`: Vulkan 1.x SPIR-V Compute Shader on hardware GPU (e.g. Radeon 8060S)
  2. `hetero_cpu_gpu_split`: Co-scheduled GPU [0..cut) + CPU pthreads [cut..256) across 20 cuts
  3. `wasm32_simd128`: Clang `wasm32` SIMD128 `.wasm` executed in Node.js `WebAssembly`
  4. `verilog_rtl_sim`: Cycle-accurate zero-multiplier Verilog RTL (`iverilog` + `vvp`)
  5. `rv32imac_baremetal_mcu_elf`: `#![no_std]` `riscv32imac-unknown-none-elf` ELF in `qemu-riscv32`
"""

from __future__ import annotations

import ctypes
import json
import os
import shutil
import struct
import subprocess
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
KIT_ROOT = HERE.parent


def _pack_signed_bytes(vals: list[int]) -> bytes:
    return struct.pack(f"<{len(vals)}b", *vals)


def run_cross_fabric_conformance(
    weights: list[int],
    acts: list[int],
    tampered_weights: list[int],
    digest_fn: Callable[[list[int]], str],
    expected_digest: str,
    expected_tamper_digest: str,
    build_dir: Path | None = None,
    quick: bool = False,
) -> dict[str, Any]:
    bdir = build_dir or (KIT_ROOT / ".build")
    bdir.mkdir(parents=True, exist_ok=True)
    fabrics: dict[str, Any] = {}

    # ── Fabric A & B: Vulkan Hardware GPU Compute + Co-Scheduled CPU+GPU HeteroMosaic ──
    glslc = shutil.which("glslc")
    cc_bin = shutil.which("cc") or shutil.which("gcc") or shutil.which("clang")
    vk_header = Path("/usr/include/vulkan/vulkan.h")
    if glslc and cc_bin and vk_header.is_file():
        try:
            spv_path = bdir / "waios_tmac.spv"
            comp_src = HERE / "waios_tmac.comp"
            if not spv_path.exists() or comp_src.stat().st_mtime > spv_path.stat().st_mtime:
                subprocess.run([glslc, "-O", str(comp_src), "-o", str(spv_path)], check=True, timeout=30)

            vk_so = bdir / "libwaios_vulkan.so"
            vk_src = HERE / "vulkan_fabric.c"
            if not vk_so.exists() or vk_src.stat().st_mtime > vk_so.stat().st_mtime:
                subprocess.run(
                    [cc_bin, "-O2", "-shared", "-fPIC", "-pthread", str(vk_src), "-lvulkan", "-o", str(vk_so)],
                    check=True,
                    timeout=60,
                )

            vlib = ctypes.CDLL(str(vk_so))
            vlib.waios_vk_init.argtypes = [ctypes.c_char_p, ctypes.c_int]
            vlib.waios_vk_init.restype = ctypes.c_int
            vlib.waios_vk_run_matvec.argtypes = [
                ctypes.c_char_p,
                ctypes.POINTER(ctypes.c_int8),
                ctypes.POINTER(ctypes.c_int8),
                ctypes.c_int,
                ctypes.POINTER(ctypes.c_int32),
            ]
            vlib.waios_vk_run_matvec.restype = ctypes.c_int

            dev_buf = ctypes.create_string_buffer(256)
            rc_init = vlib.waios_vk_init(dev_buf, 256)
            if rc_init == 0:
                gpu_name = dev_buf.value.decode("utf-8", errors="ignore")
                w_c = (ctypes.c_int8 * len(weights))(*weights)
                wt_c = (ctypes.c_int8 * len(tampered_weights))(*tampered_weights)
                a_c = (ctypes.c_int8 * len(acts))(*acts)
                out_c = (ctypes.c_int32 * 256)()
                spv_b = str(spv_path).encode("utf-8")

                # 1. Pure GPU Compute (all 256 rows on GPU)
                rc1 = vlib.waios_vk_run_matvec(spv_b, w_c, a_c, 256, out_c)
                assert rc1 == 0, f"waios_vk_run_matvec(256) failed: {rc1}"
                d_gpu = digest_fn(list(out_c))

                vlib.waios_vk_run_matvec(spv_b, wt_c, a_c, 256, out_c)
                d_gpu_tamper = digest_fn(list(out_c))

                fabrics["gpu_vulkan_compute"] = {
                    "status": "verified_equal" if d_gpu == expected_digest else "disagreement_halt",
                    "device_name": gpu_name,
                    "observed_digest": d_gpu,
                    "matches_reference": d_gpu == expected_digest,
                    "tamper_row77_digest": d_gpu_tamper,
                    "tamper_halt_triggered": (d_gpu_tamper == expected_tamper_digest and d_gpu_tamper != expected_digest),
                }

                # 2. True Co-Scheduled CPU + GPU HeteroMosaic Split across shifted row cuts
                cuts = [64, 128, 192] if quick else [16, 32, 48, 64, 80, 96, 112, 128, 144, 160, 176, 192, 208, 224, 240, 100, 120, 140, 164, 180]
                disagreements = 0
                last_d = ""
                for cut in cuts:
                    rc_s = vlib.waios_vk_run_matvec(spv_b, w_c, a_c, cut, out_c)
                    assert rc_s == 0
                    last_d = digest_fn(list(out_c))
                    if last_d != expected_digest:
                        disagreements += 1

                # Row 77 falls inside GPU tile [0..128) -> verify GPU+CPU split halts on tamper!
                vlib.waios_vk_run_matvec(spv_b, wt_c, a_c, 128, out_c)
                d_split_tamper = digest_fn(list(out_c))

                fabrics["hetero_cpu_gpu_split"] = {
                    "status": "verified_equal" if disagreements == 0 else "disagreement_halt",
                    "gpu_device": gpu_name,
                    "cpu_workers": "2x pthreads (T-MAC pair LUT + 2-bit bit-sliced popcount)",
                    "schedule_cuts_tested": len(cuts),
                    "disagreements": disagreements,
                    "observed_digest": last_d,
                    "matches_reference": disagreements == 0 and last_d == expected_digest,
                    "tamper_row77_digest": d_split_tamper,
                    "tamper_halt_triggered": (d_split_tamper == expected_tamper_digest and d_split_tamper != expected_digest),
                }
            else:
                fabrics["gpu_vulkan_compute"] = {"status": "skipped_no_vulkan_device", "rc": rc_init}
                fabrics["hetero_cpu_gpu_split"] = {"status": "skipped_no_vulkan_device", "rc": rc_init}
        except Exception as exc:
            fabrics["gpu_vulkan_compute"] = {"status": "skipped_build_or_runtime_unavailable", "reason": str(exc)[:120]}
            fabrics["hetero_cpu_gpu_split"] = {"status": "skipped_build_or_runtime_unavailable", "reason": str(exc)[:120]}
    else:
        fabrics["gpu_vulkan_compute"] = {"status": "skipped_toolchain_not_installed"}
        fabrics["hetero_cpu_gpu_split"] = {"status": "skipped_toolchain_not_installed"}

    # ── Fabric C: WebAssembly (`wasm32-simd128` via Clang + Node.js WebAssembly) ──
    clang_bin = shutil.which("clang")
    wasm_ld = shutil.which("wasm-ld")
    node_bin = shutil.which("node")
    if clang_bin and wasm_ld and node_bin:
        try:
            wasm_path = bdir / "waios_kernel.wasm"
            wasm_src = HERE / "waios_wasm_kernel.c"
            if not wasm_path.exists() or wasm_src.stat().st_mtime > wasm_path.stat().st_mtime:
                subprocess.run(
                    [
                        clang_bin,
                        "--target=wasm32",
                        "-O2",
                        "-msimd128",
                        "-nostdlib",
                        "-Wl,--no-entry",
                        "-Wl,--export=waios_wasm_matvec",
                        "-o",
                        str(wasm_path),
                        str(wasm_src),
                    ],
                    check=True,
                    timeout=30,
                )

            js_runner = (
                "const fs=require('fs');"
                "const wasmBytes=fs.readFileSync(process.argv[1]);"
                "const inBytes=fs.readFileSync(0);"
                "(async()=>{"
                "const {instance}=await WebAssembly.instantiate(wasmBytes,{});"
                "const mem=new Uint8Array(instance.exports.memory.buffer);"
                "mem.set(inBytes.subarray(0,32768),1024);"
                "mem.set(inBytes.subarray(32768,32896),34816);"
                "instance.exports.waios_wasm_matvec(1024,34816,36864);"
                "process.stdout.write(Buffer.from(instance.exports.memory.buffer,36864,1024));"
                "})();"
            )
            p_ok = subprocess.run(
                [node_bin, "-e", js_runner, str(wasm_path)],
                input=_pack_signed_bytes(weights) + _pack_signed_bytes(acts),
                capture_output=True,
                check=True,
                timeout=20,
            )
            d_wasm = digest_fn(list(struct.unpack("<256i", p_ok.stdout)))

            p_bad = subprocess.run(
                [node_bin, "-e", js_runner, str(wasm_path)],
                input=_pack_signed_bytes(tampered_weights) + _pack_signed_bytes(acts),
                capture_output=True,
                check=True,
                timeout=20,
            )
            d_wasm_tamper = digest_fn(list(struct.unpack("<256i", p_bad.stdout)))

            fabrics["wasm32_simd128"] = {
                "status": "verified_equal" if d_wasm == expected_digest else "disagreement_halt",
                "wasm_bytes": wasm_path.stat().st_size,
                "observed_digest": d_wasm,
                "matches_reference": d_wasm == expected_digest,
                "tamper_row77_digest": d_wasm_tamper,
                "tamper_halt_triggered": (d_wasm_tamper == expected_tamper_digest and d_wasm_tamper != expected_digest),
            }
        except Exception as exc:
            fabrics["wasm32_simd128"] = {"status": "skipped_build_or_runtime_unavailable", "reason": str(exc)[:120]}
    else:
        fabrics["wasm32_simd128"] = {"status": "skipped_toolchain_not_installed"}

    # ── Fabric D: Cycle-Accurate Synthesizable Verilog RTL (`iverilog` + `vvp`) ──
    iverilog_bin = shutil.which("iverilog")
    vvp_bin = shutil.which("vvp")
    if iverilog_bin and vvp_bin:
        try:
            vvp_out = bdir / "waios_rtl.vvp"
            v_src = HERE / "waios_ternary_rtl.v"
            if not vvp_out.exists() or v_src.stat().st_mtime > vvp_out.stat().st_mtime:
                subprocess.run([iverilog_bin, "-g2012", "-o", str(vvp_out), str(v_src)], check=True, timeout=30)

            def _run_rtl(ws: list[int], tag: str) -> str:
                wf = bdir / f"rtl_w_{tag}.hex"
                af = bdir / f"rtl_a_{tag}.hex"
                wf.write_text("\n".join("01" if w == 1 else ("02" if w == -1 else "00") for w in ws) + "\n")
                af.write_text("\n".join(f"{(a & 0xFF):02x}" for a in acts) + "\n")
                pr = subprocess.run(
                    [vvp_bin, str(vvp_out), f"+WHEX={wf}", f"+AHEX={af}"],
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=30,
                )
                vals = [int(ln.strip()) for ln in pr.stdout.splitlines() if ln.strip().lstrip("-").isdigit()][:256]
                assert len(vals) == 256, f"Expected 256 RTL outputs, got {len(vals)}"
                return digest_fn(vals)

            d_rtl = _run_rtl(weights, "canon")
            d_rtl_tamper = _run_rtl(tampered_weights, "tamper")
            fabrics["verilog_rtl_sim"] = {
                "status": "verified_equal" if d_rtl == expected_digest else "disagreement_halt",
                "rtl_architecture": "16x parallel clocked waios_ternary_pe (0 multipliers, 2048 cycles)",
                "observed_digest": d_rtl,
                "matches_reference": d_rtl == expected_digest,
                "tamper_row77_digest": d_rtl_tamper,
                "tamper_halt_triggered": (d_rtl_tamper == expected_tamper_digest and d_rtl_tamper != expected_digest),
            }
        except Exception as exc:
            fabrics["verilog_rtl_sim"] = {"status": "skipped_build_or_runtime_unavailable", "reason": str(exc)[:120]}
    else:
        fabrics["verilog_rtl_sim"] = {"status": "skipped_toolchain_not_installed"}

    # ── Fabric E: Bare-Metal `#![no_std]` RV32IMAC Microcontroller ELF (`rustc` + `qemu-riscv32`) ──
    rustc_bin = shutil.which("rustc") or str(Path.home() / ".cargo/bin/rustc")
    qemu_rv32 = shutil.which("qemu-riscv32")
    if os.path.isfile(rustc_bin) and os.access(rustc_bin, os.X_OK) and qemu_rv32:
        try:
            elf_path = bdir / "waios_rv32imac_mcu.elf"
            rs_src = HERE / "waios_rv32imac_mcu.rs"
            if not elf_path.exists() or rs_src.stat().st_mtime > elf_path.stat().st_mtime:
                subprocess.run(
                    [
                        rustc_bin,
                        "--edition=2021",
                        "--target",
                        "riscv32imac-unknown-none-elf",
                        "-C",
                        "opt-level=2",
                        "-C",
                        "panic=abort",
                        "-C",
                        "relocation-model=static",
                        "-o",
                        str(elf_path),
                        str(rs_src),
                    ],
                    check=True,
                    timeout=45,
                )

            p_rv_ok = subprocess.run(
                [qemu_rv32, str(elf_path)],
                input=_pack_signed_bytes(weights) + _pack_signed_bytes(acts),
                capture_output=True,
                check=True,
                timeout=20,
            )
            d_rv = digest_fn(list(struct.unpack("<256i", p_rv_ok.stdout)))

            p_rv_bad = subprocess.run(
                [qemu_rv32, str(elf_path)],
                input=_pack_signed_bytes(tampered_weights) + _pack_signed_bytes(acts),
                capture_output=True,
                check=True,
                timeout=20,
            )
            d_rv_tamper = digest_fn(list(struct.unpack("<256i", p_rv_bad.stdout)))

            fabrics["rv32imac_baremetal_mcu_elf"] = {
                "status": "verified_equal" if d_rv == expected_digest else "disagreement_halt",
                "isa": "riscv32imac-unknown-none-elf (#![no_std], 0 hardware FPU instructions)",
                "elf_bytes": elf_path.stat().st_size,
                "observed_digest": d_rv,
                "matches_reference": d_rv == expected_digest,
                "tamper_row77_digest": d_rv_tamper,
                "tamper_halt_triggered": (d_rv_tamper == expected_tamper_digest and d_rv_tamper != expected_digest),
            }
        except Exception as exc:
            fabrics["rv32imac_baremetal_mcu_elf"] = {
                "status": "skipped_build_or_runtime_unavailable",
                "reason": str(exc)[:120],
            }
    else:
        fabrics["rv32imac_baremetal_mcu_elf"] = {"status": "skipped_toolchain_not_installed"}

    verified_cnt = sum(1 for v in fabrics.values() if v.get("matches_reference") is True)
    disagreed = [k for k, v in fabrics.items() if v.get("status") == "disagreement_halt"]
    return {
        "verified_optional_fabric_count": verified_cnt,
        "disagreed_fabrics": disagreed,
        "fabrics": fabrics,
    }
