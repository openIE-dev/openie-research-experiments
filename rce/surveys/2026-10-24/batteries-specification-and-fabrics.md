# Batteries included or specification and free: what the record says, and one Form on every compute fabric

## Summary

The argument between a large library shipped with the language ("batteries included") and a small specified core with a free package registry is usually framed as a trade between convenience and flexibility. The record surveyed here shows that both positions fail at the same point: the meaning of a library is held by something other than the language's specification. In a batteries-included language it is held by one implementation and that implementation's compatibility promise, so a shipped module stops changing and is removed once an installer exists (Python Enhancement Proposal (PEP) 594 removed 22 modules; JDK Enhancement Proposal (JEP) 320 removed nine Java modules). In a specification-and-free ecosystem it is held by each registry package and each implementation, so dependency graphs deepen (a median of 21 to 41 transitive dependencies in npm, NuGet and Cargo) and specified languages diverge between implementations (Scheme, Prolog, SQL, C, JSON). Where the record converges, it converges on a curated tier between the core and the registry.

The same failure appears one level down, across compute fabrics: central processing units (CPUs), graphics processing units (GPUs), field-programmable gate arrays (FPGAs), microcontroller units (MCUs) and WebAssembly. Libraries are platform-bound because they hold the per-target "how" (vendor linear-algebra and neural-network libraries, vendor hardware abstraction layers), and the conformance suites of specified library interfaces check tolerances, not identical bits. No surveyed system gives one program one meaning on a CPU, a GPU, an FPGA, an MCU and WebAssembly. The surveyed systems that do achieve one meaning across software and hardware achieve it by restriction: state of statically known size, no heap and no recursion in the hardware part, a logical tick, and causality cycles rejected. Where a portable layer works, it fixes semantics (WebAssembly, eBPF) and moves the per-target choice into a schedule that is measured and retuned per target (Halide, Kokkos, TVM). Placement by measurement is nondeterministic unless each decision is recorded and replayed.

Read together, the two records point at one position, and it is the position of the RCE (Reality Code Engine) design. The library is part of the one specification and written in the language; it is identified by content hash at one commit, has no platform variant, and performs no I/O except through adapters. The per-target "how" belongs to the engine, which places work on a fabric only after a logged bit-exactness probe and logs every placement for replay. The library is then neither a battery that ages in place nor a registry dependency: it is a set of Forms whose meaning does not depend on the hardware that runs them. The Form is not a filter that admits some programs and refuses others. It is the shape every program already has, rigid at each commit and expanding in the text when a program needs a form it lacks. The repository holds the library half of this position today. It holds the contract for the fabric half and a reference executor proved to replay, but that executor runs on CPUs only. Section 6 lists what the record says must be closed for the claim to hold on GPUs, FPGAs and MCUs.

## 1. Method and the standing of the evidence

Twelve working notes in `notes/` were written on 24 October 2026, numbered 7 to 18 after the six notes of the versioning syntheses. Notes 7 and 8 cover code across compute fabrics and the batteries-included debate. Both were verified adversarially, claim by claim: one verifier per load-bearing claim, instructed to refute it. Of 24 claims, 18 were confirmed, 6 were corrected and none was refuted; the corrections are applied to the notes, and the verdicts with the source each verifier read are in `fabric_verification.md` and `batteries_verification.md`.

Notes 9 to 17 fill the gaps a completeness review found in notes 7 and 8:

- one semantics compiled to software and hardware (note 9);
- energy per operation across fabrics (note 10);
- library interfaces defined by a specification with conformance suites (note 11);
- placement across fabrics from cost models, and its determinism (note 12);
- what developers and models do not know is available (note 13);
- concurrency semantics across fabrics (note 14);
- one unchanged source across CPU, GPU and FPGA, measured (note 15);
- standard-library breadth against dependency counts and vulnerabilities (note 16);
- model assistants and standard libraries (note 17).

These nine were not re-verified claim by claim. Each states which sources were read in full and which were confirmed only from search extracts. Most publisher hosts were unreachable from the research environment, so several notes rely on GitHub-hosted copies, author pages and repository documentation; figures a project reports about itself are marked self-reported.

Note 18 is an inventory of the RCE repository at commit `fe5fc5d7`, built and probed without edits, with each mechanism marked implemented, specified or proposed. The browser-checker build failure it records (its item A1) was fixed afterwards in openIE-dev/rce#26; every other item stands as recorded, except that the pinning gaps of its item A5 are addressed in part by proposal XF-3 (openIE-dev/rce#28).

## 2. The library question as the record states it

**A shipped library trades flexibility for stability.** Every language with one shipped library ties the library's interface to the language's compatibility promise. Go 1's promise covers the standard library, which may grow but may not break programs written to the specification, and it keeps `golang.org/x` outside that promise. Rust's Request for Comments (RFC) 1242 states that the standard library "has much less flexibility than other crates enjoy" and that new interfaces "can just as well begin their life as external crates". "The standard library is where modules go to die" is attributed to Reitz (PyCon 2012). Deno moved its standard library to separately released packages on JSR.

**Batteries are removed once an installer exists.** PEP 206 (2000) described the philosophy as "a rich and versatile standard library which is immediately available, without making the user download separate packages". PEP 453 (2013) bundled the pip installer. PEP 594 (2019, completed across Python 3.11 to 3.13) removed 22 modules, citing maintenance cost and the ease of installing from PyPI, and several reappeared there as packages. JEP 320 (JDK 11, 2018) removed nine Java EE and CORBA modules because stand-alone copies were on Maven Central. Julia proposed moving Statistics out of its standard set (PR #46501). In each case code moves from the shipped library to the registry, and the stated reason is the cost of changing code under the language's promise.

**A free registry produces deep graphs and concentrated risk.** Half of the dependent packages in Cargo, npm and NuGet have at least 41, 21 and 27 transitive dependencies (Decan, Mens and Grosjean 2019). A small number of maintainer accounts could inject code into the majority of npm packages (Zimmermann et al. 2019). 75.1% of the dependency relationships of 9,639 Maven artifacts are bloated (Soto-Valero et al. 2021). The left-pad removal of 2016 broke builds across npm.

**Breadth alone has not been shown to reduce that risk.** No study treats standard-library breadth as a measured variable (note 16). In the seven-ecosystem comparison the median number of direct dependencies is 2 to 3 everywhere; the differences are in transitive reach, and Python, Go and Java are not in it. Malicious-package reports concentrate in npm, then PyPI and RubyGems, with Go and crates.io near zero. Python ranks second despite a broad standard library, so these data cannot separate an effect of breadth from registry size, detection effort and install hooks. Standard libraries also carry their own steady flow of vulnerabilities, concentrated in networking, cryptography and parsers:

| Library | Reports |
|---|---|
| Go standard library | 181 (golang/vulndb) |
| CPython | 196 advisories |
| Node.js core | 208 Common Vulnerabilities and Exposures (CVE) entries |

What the record ties risk to is transitive reach and the number of independent publishers, not breadth as such.

**A specification with many implementations diverges at its edges.** Scheme's Requests for Implementation (SRFIs) had "no mechanism for specifying how to load a SRFI portably, or to write a portable library", so implementations re-invented the same utility libraries (Shinn, Scheme Workshop 2012). Prolog systems depart from each other beyond the ISO core (Wielemaker and Santos Costa 2010). For SQL, "no two database management systems implement the standard in exactly the same way" (Shonan meeting 267), and Guagliardo and Libkin (2017) gave SQL queries a formal semantics and validated it against real systems. C's undefined behaviour produced optimisation-unstable code and 160 confirmed bugs found by the STACK checker (Wang et al. 2013). Seriot tested more than 30 JSON parsers and found "no two parsers that exhibited the same behaviour" (2016). Go's two compilers, gc and gccgo, expose gaps in its specification where they disagree (Taylor 2012). Apple's 2022 Foundation rewrite argued that "multiple implementations of any API risks divergent behavior".

**Conformance suites check tolerances, not bits** (note 11). The Python Array API tests, the Vulkan and OpenCL conformance test suites, OpenJDK's `Math` contract and the C++ numerics clauses accept an error bound or several outcomes for transcendental functions, reductions and NaN or subnormal handling. Where a reference implementation acts as the specification, edge-case meaning changes when the reference changes, and vendors follow at different times: a LAPACK change reached OpenBLAS 0.3.15 and MKL 2022.0 in different releases. The working record of conformance is each project's list of known failures:

| Suite | Known failures or pass rate |
|---|---|
| Python Array API | 34 to 178 expected-failure test IDs per library |
| WebAssembly System Interface (WASI) preview 1 Rust tests | from 100% to about 9% passing by runtime |
| ONNX backend scoreboard | 88% to 90% |
| Microsoft's C++ standard library (MSVC STL) against libc++'s tests | 881 listed entries, 87 judged to encode libc++'s own choices |

Interfaces over a host system state openly that they do not aim at identical behaviour. The WASI filesystem interface calls its semantics "host-dependent". The SibylFS model of file systems needs separate Linux, POSIX, Mac OS X and FreeBSD variants. Who controls the suite also shapes the ecosystem: the Java compatibility kit is licensed, while the Eclipse process requires an open test kit and at least one open implementation.

**What is available is what is known** (notes 13 and 17). Developers put documentation and missing knowledge first among obstacles when learning an interface (Robillard and DeLine 2011), and API complexity (57%) and missing domain or library knowledge (28%) behind cryptography questions (Nadi et al. 2016). Misuse survives documentation: 39% of the data-library misuses studied by Galappaththi et al. (2024) violated documented rules, and static detectors find little afterwards, with precision under 12% and recall at most 20.8% (Amann et al. 2019). Client applications lag platform interfaces by a median of 16 months (McDonnell et al. 2013). For large language model (LLM) assistants the evidence is as follows:

- **Package hallucination.** Of the packages named by code that 16 models generated in Python and JavaScript, 19.7% did not exist; per model, the Python rate ran from 3.35% to 26.28% (Spracklen et al. 2025).
- **Recent interfaces.** Interfaces introduced after a model's training cutoff score lower (Kuhar et al. 2025). Asking for 2025 libraries made some models hallucinate in 37.7% to 84.4% of tasks (Twist et al. 2026).
- **Language resource tier.** On HumanEval as translated by MultiPL-E (Cassano et al. 2023), Codex's pass@1 (the share of tasks solved by the first sample), averaged per resource tier from the published data, falls from 46.6% for high-resource languages to 27.8% for niche ones (note 17).
- **Dependencies in agent pull requests.** Adding a dependency is rare (1.3%). External-import rates range from 3.2% in Go to 38.1% in TypeScript (Twist and Zhang 2026).

No verified source measures whether assistants reuse a standard library rather than reimplement it when free to choose.

**The convergent compromise is a curated tier.** The examples are:

- rust-lang crates and the blessed.rs list;
- Haskell's Core Libraries Committee;
- Deno's audited standard packages;
- Elm's kernel-only core;
- Julia's standard libraries installed with the runtime;
- Debian's one-version archive;
- Google's One-Version Rule (Potvin and Levenberg 2016).

Zimmermann et al. propose trusted maintainers and vetting for selected npm packages, which is the same remedy. Each curated tier is a body of code whose membership one group decides, delivered together and changed together.

## 3. The fabric question as the record states it

**Functional portability is solved; performance portability depends on the kernel.** Performance portability is the harmonic mean of an application's efficiency across a set of platforms, zero if any platform is unsupported (Pennycook, Sewall and Lee 2016). Across CUDA, HIP, Kokkos, RAJA, OpenMP, OpenACC and SYCL on five systems, every BabelStream kernel except the dot product is "highly consistent with the native port" (Davis et al., ICS 2025). The dot-product reduction is not:

| Model | Performance portability, dot product |
|---|---|
| native | 0.99 |
| SYCL | 0.91 |
| RAJA | 0.82 |
| Kokkos | 0.80 |
| OpenACC | 0.58 |
| OpenMP | 0.49 |

The same 48 Futhark benchmarks compiled to OpenCL, CUDA and HIP ran at 0.42 to 1.72 times each other, largely from defaults (Henriksen 2024). A tuned configuration moved between GPU generations keeps 58.5% to 99.9% of the optimum (arXiv:2303.08976).

**Portable layers that work separate what is computed from how, and retune the how per target.** Halide separates the algorithm from the schedule (Ragan-Kelley et al. 2012, 2013); Kokkos separates data layout (Edwards, Trott and Sunderland 2014); TVM and Ansor search schedules per target (Chen et al. 2018; Zheng et al. 2020); Taichi separates layout from computation (Hu et al. 2019, self-reported speed-ups).

**A portable intermediate form works only when it fixes semantics.** The intermediate representation (IR) of LLVM is not portable: it cannot hide calling conventions and application binary interfaces, and its undef and poison model caused long-standing miscompilations (Lee et al. 2017). WebAssembly had a formal semantics from the start (Haas et al. 2017) and fixes integer behaviour that C leaves undefined. It still admits NaN payload bits, shared-memory races and some relaxed single-instruction multiple-data (SIMD) results as nondeterministic. eBPF is portable across kernels only through load-time relocations.

**FPGAs need restructured code, not tuned code** (notes 7 and 15). One unmodified OpenCL code base, OpenDwarfs, ran on a CPU, a GPU and an FPGA (Krommydas et al. 2013), but without a comparison to FPGA-optimised versions. Altis-SYCL is the only verified study that makes that comparison for one source on all three (Weckert et al. 2023). Its source was migrated from CUDA and tuned for one GPU, with small `#ifdef` blocks for the FPGA in most benchmarks. From its published timings at the largest problem size, the survey derives that the FPGA reaches 0.2% to 47% of its own FPGA-optimised version and is 63 to 8,014 times slower than the best CPU or GPU. The fastest Rodinia FPGA kernels are rewrites of the GPU kernels into single work-item form (Zohouri et al. 2016). One high-level synthesis (HLS) kernel shows the scale of the difference (Xiao, Chamberlain and Cabrera 2021):

| Needleman-Wunsch kernel | Run time |
|---|---|
| Intel OpenCL ported one to one to a Xilinx Alveo U250 | 294 s |
| rewritten in Xilinx C++ with burst transfers | 2.2 s |
| on the Intel FPGAs | 0.26 to 0.29 s |

What carries across FPGAs is "same semantics, different source", which is why code divergence is measured separately from performance portability (Harrell et al. 2018).

**In the surveyed systems, one meaning across software and hardware is achieved by restriction** (note 9). Kôika proves its compiler to circuits, but its Verilog printer and C++ simulator are unverified (Bourgeat et al. 2020). Vélus proves Lustre down to assembly, which is software only, and excludes `pre` (Bourke et al. 2017). For Esterel, a program is constructive if and only if its circuit stabilises (Berry 2002; Mendler, Shiple and Berry 2012). Toolchains that emit both software and hardware share a front end and document their exceptions: Bluespec's scheduling list, Clash's "not meaning-preserving" `Integer`, CIRCT's undefined values. The restrictions recur wherever the surveyed systems achieve one meaning:

- state of statically known size (Clash bit widths; SCADE static allocation and constant-bound loops);
- no recursion and no heap in the hardware part (Clash, SCADE, LegUp, ROCCC, the SystemC synthesis subset);
- a discrete logical tick (Esterel and Lustre instants, Lingua Franca tags, Bluespec rules per cycle);
- causality cycles rejected (Esterel non-constructive programs, Lingua Franca causality loops);
- fixed rates for static schedules (synchronous dataflow).

Models that keep generality move decidability or determinism to a runtime or to the programmer. Bounded memory for Kahn networks is undecidable and needs Parks's dynamic scheduler (Parks 1995). Lingua Franca's determinism covers coordination, while reaction bodies written in C can break it. SystemC leaves process order to the implementation. Timing determinism is a further property: precision-timed (PRET) machines put it into the instruction set (Edwards and Lee 2007), precision-timed infrastructure into the semantics of the language (Broman et al. 2013), and FlexPRET into the hardware thread scheduler (Zimmer et al. 2014).

**Concurrency semantics differ per target, and no atomic ordering is available everywhere** (note 14).

- **Orderings.** Vulkan forbids sequentially consistent atomics, WebGPU Shading Language (WGSL) atomics are relaxed only, WebAssembly atomics are sequentially consistent only, and SYCL leaves orders and scopes optional per device.
- **Races.** WebAssembly defines data races; Vulkan and CUDA C++ leave them undefined.
- **Testing.** Weak behaviours are rare and depend on stress: GPUHarbor observed 35.4 million in about 395.5 billion iterations. Passing tests therefore do not show that a behaviour is forbidden.
- **Forward progress.** The portable guarantee is weak, and inter-workgroup barriers deadlocked on all eight GPUs tested (Sorensen et al. 2016).
- **Soundness.** Results are pairwise: scoped C++ to NVIDIA's Parallel Thread Execution (PTX) instruction set is proved in Coq (Lustig et al. 2019). No result found covers one model compiled to CPU, GPU and WebAssembly together.

**Bit-identical results cost little when designed in and much when retrofitted.** Two IEEE devices running the same instruction sequence agree. CPUs and GPUs differ through fused multiply-add (FMA) contraction, operation order, compiler flags and math libraries (Whitehead and Fit-Florea 2011); CUDA's `expf` has a maximum error of 2.32 units in the last place (ulp). Measured costs of reproducibility range widely:

| Approach | Cost |
|---|---|
| Tuned reproducible transcendentals and sums (Arteaga, Fuhrer and Hoefler 2014) | transcendentals faster than the platform libraries in the geometric mean; sums at most about 10% slower out of cache |
| Balanced-tree reduction in Triton lowering, with a layout optimisation (Yang et al. 2026) | 19 of 27 kernels within 10% of free-order performance |
| Deterministic atomic buffering in hardware (Chou et al. 2020) | about 23% slowdown, in simulation, on atomic-intensive applications |
| A later port of the same transcendentals with FMA disabled (bitrep fork) | 3.5 to 4.5 times slower on a transcendental-heavy kernel |

ReproBLAS (Ahrens, Demmel and Nguyen 2020) and ExBLAS (Iakymchuk et al. 2015) give order-independent sums and correctly rounded Basic Linear Algebra Subprograms (BLAS).

**Placement is measured, and nondeterministic unless recorded** (note 12). StarPU, OmpSs and Charm++ predict a task's cost from its past run times per kernel, data size and device, and need a few to ten samples before trusting the history. Analytical prediction is weaker: the best GPU simulator shows 2% to 33% cycle error per suite (Accel-Sim). Determinism comes only from recording and replaying decisions, as in Legion's replay mapper and Charm++'s record and replay, or from virtual-time simulation (StarPU on SimGrid). Both are in tension with adaptivity. Static list scheduling is deterministic only up to tie-breaking: in a run of the reference HEFT (Heterogeneous Earliest Finish Time) implementation, equal-makespan ties gave 15 different placements across 20 hash seeds.

**Energy follows data movement, and no measurement crosses all classes under one boundary** (notes 7 and 10). Circuit-level estimates put arithmetic far below data movement:

| Source | Operation | Data movement |
|---|---|---|
| Horowitz | 0.03 to 3.7 pJ per operation | 10 pJ from static random-access memory; roughly 1 to 2 nJ from dynamic random-access memory |
| Dally | 20 fJ | 1.3 nJ |

On the same vision kernels a GPU had 1.1 to 3.2 times better energy per frame on simple kernels, and an FPGA 1.2 to 22.3 times better on complex kernels and pipelines (Qasaimeh et al. 2019). The measurement boundary can decide such comparisons: servers draw about half of full power when idle (Barroso and Hölzle), and Qasaimeh et al. exclude static power. MLPerf Tiny and ULPMark measure within the microcontroller class and Green500 measures whole systems. No study found measures one kernel in joules on an MCU, a CPU, a GPU and an FPGA under one boundary.

**Libraries are platform-bound where the per-target how is sold.** CUDA's math, neural-network and communication libraries ship as closed binaries, and AMD mirrors them one to one (rocBLAS, MIOpen, RCCL). Vendor hardware abstraction layers for microcontrollers are mutually incompatible. Rust's embedded-hal 1.0 kept driver-level traits and dropped the goal of standardising whole hardware abstraction layers, because hardware capabilities vary too widely.

## 4. One question: where the meaning of a library lives

The two debates are about the same object. The record shows a library's meaning held in one of four places, each with its own documented failure:

| Where the meaning is held | Examples | Failure the record documents |
|---|---|---|
| one implementation, under a compatibility promise | Python, Go and Java standard libraries | the code cannot change without breaking the promise, so it ages in place and is moved out |
| each registry package | npm, Cargo, NuGet | transitive reach and the number of independent publishers grow |
| a specification checked with tolerances | Array API, Vulkan, POSIX, C++, SQL, JSON | implementations diverge at the edges, and conformance is a list of known failures |
| a vendor binary for one fabric | cuBLAS, cuDNN, microcontroller hardware abstraction layers | the program is bound to the fabric |

The record also shows what removes each failure, though always separately:

- **Identity by content** instead of by name and promise removes the cost of change (`continuous-improvement-without-versions.md`, section 3).
- **One group, one delivery and one unit of change**, as in the curated tier and the one-version rule, bound transitive reach and the number of publishers.
- **Semantics fixed to the bit** removes divergence at the edges, and costs little when designed in. Examples are WebAssembly's integer semantics, reproducible BLAS and the fixed reduction tree.
- **Separating what is computed from where and how** removes the need for a fabric-specific library. The how is then measured per target, and logging the decision removes the nondeterminism that measurement introduces.
- **Restricting state, recursion, allocation and time** is how the surveyed systems reach one meaning in hardware: they cut their source language down to what their hardware can mean.

The first four remedies compose into one position, and the fifth is not needed, when the unit of meaning is the RCE Form P = (S, E, δ, D, λ): declared state S, an event alphabet E, a step function δ, the hash-chained log D and the output function λ (6.1 of the specification). A library module is a set of Form definitions in the language itself, and four properties follow:

- **Its meaning is fixed to the bit by the specification** (6.3), not by a tolerance, so where a second implementation diverges, a probe detects it.
- **Its identity is its definition hashes** (F.4.3). A change is a new hash in the same commit rather than a broken promise, so the library has no reason to freeze.
- **It has no platform variant.** I/O goes through adapters (HC-3), and computation goes to whichever fabric the engine chooses. The engine chooses a fabric only after a logged probe (HC-13) and logs the decision (HC-12).
- **What is available is a list a tool prints,** complete at each commit and growing in the same text, which is the precondition for measuring and reducing reimplementation.

Batteries included and specification-and-free then stop being alternatives: the batteries are part of the specification, and the program is free of any fabric.

The fifth remedy is where the Form differs from the surveyed systems. Those systems restrict because their source language says more than their hardware can mean, so one meaning across both requires cutting the language down. The Form is the shape that software and hardware already share, so nothing is cut to reach it:

- **The step is already a logical tick.** The Form's event step is a tick in the synchronous-language sense.
- **The parallel construct already states what each iteration reads and writes.** `for … par` has no effects, writes only reductions and the iteration's own slot (C.8, W-PAR-3 and W-PAR-4), and its reductions combine through a fixed tree.
- **No memory ordering is exposed.** Because no single atomic ordering exists on every target, a surface that exposes none is the only surface that can mean the same thing everywhere, and the Form exposes none.
- **The engine reads the shape; it does not ask the program to be smaller.** A Form whose state has a statically known size is realised as a circuit with its state in registers. A Form whose state grows is realised with that state held in memory the circuit addresses. That is the shape expanding to state outside the circuit, not a class of program left out.

Performance on an FPGA then comes from a compiler realising the step from its stated state and stated work, not from a second source written by the programmer. The record measures the opposite approach, one source written and tuned for another device, and shows it performs poorly on FPGAs; it has no measurement of a compiler working from a stated step.

When a program needs a form the shape does not have, including one nobody foresaw, the shape gains it in the text. A change may extend, generalise or replace a form; it moves together with the programs of the repository in one commit, and the program hashes, the equivalence check and the log record what moved (`continuous-improvement-without-versions.md`, section 7). It never gains it through a macro, flag, directive or plugin beside the text. The specification already shows this: behaviour and equivalence (6.10) and the host's fabric entries were added this way, and the log as a partial order and intent with holes are proposed the same way.

## 5. Where the RCE design stands against the record

The status below is from note 18, updated for openIE-dev/rce#26.

**Standard library**

| Mechanism | Specification | Status |
|---|---|---|
| Every module of `stdlib/lib` resolves by `use` in every tool; `rce lib` lists the 46 modules | 4.1 | holds, the browser checker included |
| The library is RCE source with no `extern`; POSIX, Windows, WASI, Unified Extensible Firmware Interface (UEFI) and bare-metal rules are data in the `os.*` modules | 5.15, HC-3 | holds |
| `stdlib/lib/MANIFEST.json` pins the 46 modules by hash | F.5.3 | holds in continuous integration; the build embeds whatever files are present and never reads the manifest |
| A program's manifest pins the library it uses | F.5.3 | does not hold: a program with `use enc` fails its own manifest check, and dependency hashes are checked for format only |
| The method table, generated from the specification and tested against the evaluator | 5.15 | holds |
| One meaning of "standard library" | 4.1, 5.15, 6.3 | does not hold: 5.15 means the method table and 4.1 the 46 modules |
| `std.text`, `std.collections`, `std.math` | 4.1 S4 | names with no items, beside a `math` module that has them |
| 6.3 F9's list of present `math` functions | 6.3 | stale: `math.rce` exports `tan`, `atan2`, `pow` and about 20 others that F9 calls absent |

**Compute fabrics**

| Mechanism | Specification | Status |
|---|---|---|
| One numeric contract: no contraction, no flush to zero, non-finite results trap | 6.3 | holds in the reference evaluator and four emitted runtimes, with hash parity on six CPU targets including wasm32-wasip1 and s390x |
| The fixed reduction tree, the same bits for any thread count | C.8, T18 | holds for `for … par`; `List.sum` and plain loops are left folds, which differ on cancellation (1.5 against 0.5 on one probe) |
| Fabric discovery logged as `host.FabricCaps` | HC-11, E.7 | CPU only: GPU, neural processing unit (NPU) and memory fields are written as null; no field for an FPGA or an MCU; no hot-plug |
| Bit-exactness probe gating placement (`host.Exact`) | HC-13 | holds; replay does not re-derive the reference digest, and a public call accepts caller-supplied digests |
| Placement from a cost model, logged and re-derived on replay | HC-12 | implemented as a host interface and proved in the Lean model (`t37_placement`); no execution path calls it |
| Calibration (`host.Calibrated`) | E.5, HC-12 | logs caller-supplied numbers; no calibration run; the CPU's line is a constant; work is an element count rather than the C.6.4 cost |
| The rule that a null field of the fabric record means an absent fabric | E.7 | not honoured by placement |
| A real fabric through the `FabricExec` interface | E.6 | interface for binary64 lanes and sums only; test doubles only |
| Device regions and kernels | 5.13, C.7 | checked, with CPU meaning; no lowering to a kernel |
| Emitters | 10.5 | four CPU languages; hardware description and shader targets proposed (`emit-targets.md` Tier 3) |
| A host on a microcontroller | Appendix E | absent: the host needs the Rust standard library; no microcontroller CI target; no storage row for flash |
| Energy calibration | `energy-calibration.md` | proposed; reuses the name `host.Calibrated` with a different payload from E.5 |
| Foreign code as logged answers | 5.11, HC-4 | holds for meaning: δ never calls foreign code, and each call is a logged `Foreign` entry; the checker does not list the foreign functions a host must supply to run a program live |

The library half of the position therefore holds, with gaps in the pinning and in definitions. The fabric half is a contract and a reference executor that replays, exercised on CPUs only.

## 6. What the record says the design should state or close

| Item | Position | Ground in the record |
|---|---|---|
| One meaning of "standard library": the modules of `stdlib/lib`, whose methods include the table of 5.15; the empty `std.*` names filled or removed; 6.3 F9 reconciled with `math.rce` | Erratum to 4.1, 5.15 and 6.3 | A curated tier is one set with one membership (section 2); two definitions of the set reproduce Scheme's SRFI problem inside one text |
| The build embeds only the pinned library; a program's manifest pins the built-in library by the manifest's hash; dependency hashes are checked against the embedded text | Close F.5.3 | Identity from content (`continuous-improvement-without-versions.md`, section 3); a pin checked only in continuous integration is a promise, not an identity |
| One way to bring a library into a program, `use`; the `#!lib` directive retired by rewriting each use of it to `use`, with `rce equiv` showing every rewritten program equivalent, so no accepted program changes meaning | Adopt | Two spellings for one act; the directive was understood by one binary, which is the practice the batteries-included ledger row refuses |
| Foreign code is already in the shape: its answers are logged, so a program's meaning is the same on every fabric; the checker lists the adapters a program needs, and a WebAssembly component is the form every host can supply (HC-4) | Adopt | Vendor-bound libraries are where portability ends (section 3); WebAssembly's component model exists because core modules left each toolchain to generate its own bindings |
| Placement on every execution path: lane-wise operations, `for … par` bodies and reductions in `rce run` and the host | Close HC-12 | Placement is measured; recorded decisions replay (section 3, note 12) |
| One reduction rule per placement class: `sum.f64` is the fixed tree of C.8; a left fold is its own class, placed only where a probe matches the left fold; E.11's N-9 and TU-4 restated in these terms | Adopt | Fixed-order reductions are reproducible at small cost (Arteaga et al. 2014; Yang et al. 2026); C.8 is already normative and T18 proves the tree equal to the fold for associative operations with an identity |
| A calibration run that measures overhead and throughput per fabric and class, the CPU's line included, with work from the C.6.4 cost; energy calibration under its own entry name | Close E.5 and HC-12 | History-based models need a few to ten samples (StarPU, OmpSs); the energy result depends on the measurement boundary (note 10) |
| Replay re-derives every probe's reference digest; the probe call with caller-supplied digests is test-only; a null field of the fabric record excludes the fabric | Close HC-13 and E.7 | Passing tests do not show a behaviour forbidden (note 14), so the evidence admitted to D must be re-derivable (E.2c law 1) |
| Classes beyond binary64: the integer classes HC-13 already lists, a binary32 class with 6.3's binary32 rules on backends with IEEE binary32 and no contraction, and the traps of 6.3 F4 and the integer traps applied after every fabric result | Extend HC-12 and HC-13 | WGSL has no core binary64 and leaves float rounding unspecified; WebGPU studies report image agreement, not identical bits (Malyshau 2026) |
| A first real fabric: a GPU through Vulkan or wgpu, its float controls queried into the fabric record, with `for … par` bodies and device regions compiled to kernels | Implement E.6 | Single-source models reach 0.80 to 0.91 performance portability on the hardest GPU kernel (Davis et al. 2025) and 0.90 across 15 CPU and GPU platforms for OpenMP (Deakin et al. 2019, 2020, note 15); the probe makes the result exact rather than within tolerance |
| Hardware realisation read from the shape: the checker reports each Form's state sizes and step costs; a statically sized state is realised in registers, one step per clock, and a growing state in memory the circuit addresses | Adopt; the first thing a Tier 3 emitter needs | The surveyed systems reach one meaning in hardware by cutting their language down (note 9); the Form states state and step, which is what a compiler restructuring for an FPGA reads (note 15) |
| FPGA and MCU entries in the fabric record and the host survey; a host of the five primitives without the Rust standard library; a microcontroller target in the cross-architecture parity job; a storage row for flash | Extend Appendix E | Microcontroller abstraction layers standardise at the driver trait, not at the whole layer (embedded-hal 1.0) |
| One energy measurement across classes under a stated boundary, starting with the planned run on a Kria KV260 FPGA board | Measure | No such study exists (note 10) |
| The rate at which model assistants reuse the library rather than reimplement it, measured on generated RCE programs against `rce lib` | Measure | No verified study measures it in any language (note 17) |

## 7. What the record does not settle

- **Breadth and risk.** Whether a broader standard library reduces dependency risk is untested, because no study treats breadth as a variable.
- **FPGAs from one source.** Whether one unchanged source can perform well on an FPGA has no positive example. The Form's position, that a compiler realises a step from its stated state and work, is untested.
- **Energy across classes.** No measurement found covers MCUs, CPUs, GPUs and FPGAs under one boundary.
- **Bit-exact binary32 on GPUs.** Whether this is widely attainable depends on per-device float controls. WGSL does not specify rounding, so a WebGPU backend cannot be admitted for float classes through WGSL alone.
- **End-to-end proof.** No system proves one meaning from source to circuit. Kôika, Vélus and the Esterel results each stop short of the full chain, and the Lean model of the RCE host proves placement replay, not the fabric's arithmetic, which the probe establishes by evidence.
