# Working note 7: code that runs on every compute fabric without a platform-specific library

Written 24 October 2026. arxiv.org and most hosts other than github.com were unreachable from the research environment; abstracts and figures were confirmed from search extracts where a fetch failed. **[self-reported]** marks a claim a project or vendor makes about itself; **[secondhand]** marks a figure taken from a citing source rather than the primary text. Claims are re-checked by the verification pass recorded in `fabric_verification.md`.

## 1. Portable programming models and their measured results

- **The metric.** Performance portability is a single application's efficiency across a set of platforms, measured as the harmonic mean of per-platform efficiencies and zero if any platform is unsupported. Pennycook, Sewall, Lee, "A Metric for Performance Portability," PMBS at SC16, 2016, arXiv:1611.07409; "Implications of a metric for performance portability," FGCS 92:947-958, 2019, doi:10.1016/j.future.2017.08.007; Pennycook, Sewall, "Revisiting a Metric for Performance Portability," P3HPC at SC21.
- **Kokkos.** The main obstacle to performance portability is conflicting memory-access-pattern constraints across devices, addressed by polymorphic layouts. Edwards, Trott, Sunderland, JPDC 74(12):3202-3216, 2014, doi:10.1016/j.jpdc.2014.07.003.
- **RAJA.** Beckingsale et al., "RAJA: Portable Performance for Large-Scale Scientific Applications," P3HPC at SC19. An SC15 poster on TeaLeaf found RAJA then lacked functional portability while Kokkos needed more up-front work but was competitive on CPUs and NVIDIA GPUs (Martineau, McIntosh-Smith et al.).
- **Head-to-head on NVIDIA and AMD.** Across CUDA, HIP, Kokkos, RAJA, OpenMP, OpenACC and SYCL on five proxy applications, Kokkos, RAJA and SYCL showed the most promise; Kokkos reached about 0.99 to 1.00 of CUDA on copy and triad but 0.89 on the dot reduction, SYCL about 0.85, and directive models struggled most on reductions. Davis et al., "Taking GPU Programming Models to Task for Performance Portability," ICS 2025, arXiv:2402.08950.
- **Cost of the layer.** Kokkos on CUDA almost matched native CUDA in an ANL lattice-Boltzmann study while Kokkos with a SYCL back end fell to about 70% for one access pattern [secondhand]; identically tiled tensor contractions in Kokkos and SYCL differed significantly from CUDA and HIP through register use (SC22 poster).
- **OpenCL ran everywhere, then vendors diverged.** One unmodified OpenCL code base (OpenDwarfs) ran on CPU, GPU, APU, Xeon Phi and FPGA. Krommydas, Feng, Owaida, Antonopoulos, Bellas, ICPADS 2013. Apple deprecated OpenCL in macOS 10.14 (2018) for Metal; NVIDIA became OpenCL 3.0 conformant with driver R465 in April 2021; OpenCL 3.0 made 1.2 the mandatory baseline and every 2.x feature optional.
- **SYCL and oneAPI.** Reguly, "Evaluating the performance portability of SYCL across CPUs and GPUs on bandwidth-bound applications," 2023, arXiv:2309.10075 (Intel Max 1100, A100, MI250X from one source). Costanzo et al., 2024, arXiv:2412.08308: SYCL near CUDA on NVIDIA, higher architectural efficiency elsewhere, multi-GPU and hybrid configurations weak.
- **Directives.** Lopez et al., WACCPD at SC16, journal IJHPCN 14(2):165-182, 2019: portability hinges on compiler maturity and tuning. Diaz et al., 2020, arXiv:2010.09454: OpenMP offload performance varies widely between compilers, tuning speed-ups up to 18x on V100.
- **HIP and hipify.** On SHOC, hipified code averaged 99.8% of CUDA performance (ORNL, "Experiences Readying Applications for Exascale," 2023, arXiv:2310.01586). Tsai, Cojean, Anzt, "Porting a sparse linear algebra library to HIP," 2020, arXiv:2006.14290, document the manual fixes.
- **Vulkan compute and SPIR-V.** Gkeka, Bellas, Antonopoulos, IWOCL 2019, doi:10.1145/3318170.3318174: Vulkan within about 10% of OpenCL, the SPIR-V compiler less mature. Mammeri, Juurlink, IISWC 2018 (VComputeBench): Vulkan faster than CUDA and OpenCL only after low-level tuning at more programming effort.
- **WebGPU.** One case study reports bit-identical result grids across four Vulkan adapters and Metal with backend-specific timing (2026, arXiv 2608.17390); the specification tracker records that subgroup reconvergence is not portable across D3D12, Metal and Vulkan (gpuweb issue 4306).
- **Halide.** Separating the algorithm from the schedule makes retargeting possible; up to 5x over hand-tuned code by schedule search. Ragan-Kelley et al., SIGGRAPH 2012; PLDI 2013.
- **Futhark.** The same 48 benchmarks compiled to OpenCL, CUDA and HIP produced mostly equivalent code but runtime ratios from 0.42x to 1.72x, largely from defaults. Henriksen, FProPer 2024.
- **Taichi.** Separates data layout from computation; one tenth the code and 4.55x average over hand-optimised references [self-reported]. Hu et al., SIGGRAPH Asia 2019, doi:10.1145/3355089.3356506.
- **Triton.** Tile-level language; matmul and convolution on par with cuBLAS and cuDNN [self-reported]. Tillet, Kung, Cox, MAPL 2019. It does not abstract library-level dependencies (cuDNN, TensorRT, cuBLAS).
- **TVM and Ansor.** TVM's motivation is frameworks' reliance on vendor operator libraries; competitive with hand-tuned libraries on several targets [self-reported]. Chen et al., OSDI 2018. Ansor: up to 3.8x (Intel CPU), 2.6x (ARM CPU), 1.7x (NVIDIA GPU) over prior state of the art, Zheng et al., OSDI 2020. Transferring a tuned optimum between GPU architectures yields 58.5% to 99.9% of optimal (arXiv:2303.08976).
- **XLA, StableHLO, IREE.** Project documents only: StableHLO as a portable, versioned operation set; IREE as an MLIR compiler and runtime for mobile and edge (Google Open Source Blog, March 2023).
- **MLIR.** Infrastructure for many dialects at different abstraction levels across targets. Lattner et al., CGO 2021, arXiv:2002.11054.
- **LLVM IR is not portable.** It cannot hide calling conventions and ABIs (llvm-dev, "LLVM IR is a compiler IR," October 2011); PNaCl froze a subset with a portable triple. Its undef and poison model caused long-standing miscompiles: Lee et al., "Taming Undefined Behavior in LLVM," PLDI 2017.
- **WebAssembly.** A portable low-level bytecode with a formal semantics from the start: Haas et al., "Bringing the Web up to Speed with WebAssembly," PLDI 2017. Its determinism is deliberately limited: NaN payload bits, shared-memory races and some relaxed SIMD results are nondeterministic (webassembly.org, "Nondeterminism"). The Component Model exists because core Wasm left each toolchain generating its own bindings.
- **eBPF.** Portability across kernels needed BPF CO-RE relocations resolved against BTF at load time (Nakryiko, 2020; "The eBPF Runtime in the Linux Kernel," 2024, arXiv:2410.00026).

## 2. FPGA and hardware

- **HLS across vendors.** A Needleman-Wunsch kernel ported minimally from Intel OpenCL to Xilinx ran in 294 s; a rewrite with burst transfers ran in 2.2 s. Cabrera et al., HPEC 2021; IWOCL 2021.
- **OpenCL for FPGA.** GPU-optimised Rodinia kernels do not perform well on a Stratix V without FPGA-specific restructuring. Zohouri et al., SC16.
- **Chisel.** One Scala-embedded description generates a C++ simulator and Verilog for FPGA or ASIC. Bachrach et al., DAC 2012.
- **Bluespec.** Guarded atomic actions give a fabric-neutral operational semantics from which a scheduler derives hardware. Hoe, Arvind, IEEE TCAD 23(9), 2004.
- **CGRAs.** Liu et al., ACM Computing Surveys 52(6), 2019; Podobas, Sano, Matsuoka, 2020, arXiv:2004.04509; a 2025 comparison of four CGRA mapping toolchains found failures on irregular loops (arXiv:2502.19114). No published DARPA SDH outcome metrics were found.
- **OpenTitan.** Open RTL frozen for tape-out in 2023; silicon-proven by 2024 (lowRISC; Ciani et al., arXiv:2406.11558). Portable RTL does not remove process dependence: the PDK remains the lock-in point. SKY130 (2020) was the first PDK downloadable without an NDA.

## 3. Microcontrollers and embedded

- **Vendor HALs** are mutually incompatible despite standardisation attempts (Beningo, Embedded.com); ST's HAL splits generic APIs from per-family extensions. No academic analysis of CMSIS as a standard was found.
- **Zephyr** compiles the devicetree at build time and claims more than 600 boards [self-reported]; configuration is still split across Kconfig, overlays and code. No peer-reviewed portability evaluation was found.
- **Arduino** `digitalWrite()` costs about 60 cycles against 4 for a direct register write on a 16 MHz Uno (hobbyist measurements).
- **TinyGo and MicroPython** on ESP32: C and C++ fastest, closely followed by TinyGo and Rust; MicroPython many times slower. Plauska, Liutkevičius, Janavičiūtė, Electronics 12(1), 2023.
- **Rust embedded-hal** traits act as a specification so a driver compiles unchanged against many HAL implementations; version 1.0 dropped the goal of standardising whole HAL APIs because hardware capabilities vary too widely.

## 4. Deterministic semantics across fabrics

- **CPU and GPU differ** under FMA contraction, operation order and compiler flags, while identical instruction sequences agree on any IEEE device. Whitehead, Fit-Florea, "Precision & Performance: Floating Point and IEEE 754 Compliance for NVIDIA GPUs," NVIDIA, 2011. No two standard math libraries are likely to give bit-identical results; CUDA's `expf` has a 2.32 ulp maximum error.
- **Integer semantics.** Signed overflow is undefined in C and shifts of negative values implementation-defined (GNU Autoconf manual); WebAssembly fixes both as the price of determinism.
- **ReproBLAS.** Order-independent summation with a binned accumulator in one pass. Ahrens, Demmel, Nguyen, ACM TOMS 46(3), 2020, doi:10.1145/3389360.
- **ExBLAS.** Bitwise-reproducible, correctly rounded BLAS on CPUs, Xeon Phi and GPUs, performance comparable to standard [self-reported]. Iakymchuk, Collange, Defour, Graillat, 2015.
- **Applications.** Transcendentals and non-associative reductions are the sources of irreproducibility; CPU and GPU agreement needed FMA disabled at about 3 to 4x slowdown for libm-heavy code [secondhand]. Arteaga, Fuhrer, Hoefler, IPDPS 2014.
- **ML frameworks.** PyTorch deterministic kernels are often slower and not reproducible across releases or platforms; deterministic FlashAttention-3 backward up to 37.9% throughput loss [secondhand]; deterministic atomic buffering in hardware costs 23% on average (MICRO-53, 2020); compiler-enforced balanced-tree reduction keeps 19 of 27 Triton kernels within 10% (Yang, Deng, 2026, arXiv 2609.11356).

## 5. Energy

- **Roofline** (Williams, Waterman, Patterson, CACM 52(4), 2009) and **energy roofline** (Choi, Bedard, Fowler, Vuduc, IPDPS 2013: the energy roof is curved because energy, unlike time, does not overlap).
- **Same kernel on CPU, GPU, FPGA.** Vision kernels: GPU 1.1 to 3.2x better energy per frame on simple kernels, FPGA 1.2 to 22.3x on complex kernels and pipelines. Qasaimeh et al., ICESS 2019, arXiv:1906.11879. FPGA better than CPU and GPU in single precision but worse in double for one ORNL kernel (Euro-Par 2017 workshops); IBM GEMM and FFT coprocessors about 10x energy gain in fixed point but at most 30% for double-precision GEMM (ASAP 2019).
- **MCU class.** MLPerf Tiny is the only common yardstick (Banbury et al., 2020, arXiv:2003.04821). No study measures the same kernel in joules on MCU, CPU, GPU and FPGA under one measurement boundary.

## 6. Vendor lock-in as the source of platform-bound libraries

- CUDA is a compiler, a runtime, math libraries (cuBLAS, cuDNN), a communications library (NCCL) and a decade of tuned kernels, the libraries shipped as precompiled code without source (industry analyses). Portability layers lag where frameworks depend on vendor libraries (TVM's motivation; SCALE, HCDS 2025). AMD mirrors the libraries one to one (rocBLAS, MIOpen, RCCL). No rigorous economic study of the lock-in was found.

## What this note establishes

1. Functional portability is solved; performance portability is not, and the gap depends on the kernel: streaming kernels reach native speed through Kokkos or SYCL, reductions and register-heavy kernels lose 10 to 30%, and one source through three GPU interfaces spans 0.42x to 1.72x.
2. Every portable layer that succeeded separated what is computed from how and retuned the how per target (Halide, Kokkos, TVM and Ansor, Taichi); a tuned configuration moved across GPU generations loses up to 41%.
3. A portable intermediate form works only when it gives up native ABI and hardware semantics: LLVM IR is not portable; WebAssembly and eBPF are, because they fix integer and most float semantics and pay in speed or an extra relocation layer.
4. Bit-identical results across fabrics are achievable and never free: order-independent summation, reproducible transcendentals and FMA suppression cost from about 20% to several times, depending on the kernel.
5. No surveyed system gives one meaning per program across CPU, GPU, FPGA, MCU and WebAssembly. WebAssembly comes closest on CPUs by fixing semantics, admitting NaN-payload and shared-memory nondeterminism, running through a compiler rather than on bare hardware, and not addressing GPUs or FPGAs. Platform-bound libraries persist because they are where the per-target how is sold, closed and NDA-gated.
