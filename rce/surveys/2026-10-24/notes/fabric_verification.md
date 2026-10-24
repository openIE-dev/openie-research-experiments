# Verification of working note 7 (code across compute fabrics)

Adversarial verification of the load-bearing claims of the working note, 24 October 2026: one verifier per claim, instructed to refute, with verdicts confirmed, corrected, refuted or unverifiable. Corrections are applied to the note.

| Claim | Verdict | Source read |
|---|---|---|
| F1 | confirmed | https://arxiv.org/abs/1611.07409 |
| F2 | corrected | https://raw.githubusercontent.com/HPCRL/ICS2025-webpage/main/program/Proceedings_ICS25/ics25-63.pdf |
| F3 | confirmed | https://futhark-lang.org/publications/fproper24.pdf |
| F4 | corrected | https://www.cse.wustl.edu/~roger/papers/xcc21.pdf |
| F5 | confirmed | https://arxiv.org/abs/1906.11879 |
| F6 | confirmed | https://raw.githubusercontent.com/WebAssembly/design/main/Nondeterminism.md |
| F7 | confirmed | https://github.com/willow-ahrens/willow-ahrens.github.io/blob/HEAD/assets/documents/ahrens_algorithms_2020.pdf |
| F8 | corrected | http://www.unixer.de/publications/img/arteaga-fuhrer-hoefler-reproducible-apps-ipdps14.pdf |
| F9 | corrected | https://microarch.org/micro53/papers/738300a981.pdf |
| F10 | corrected | https://arxiv.org/abs/2608.17390 |
| F11 | confirmed | https://arxiv.org/abs/2310.01586 |
| F12 | confirmed | https://perso.ens-lyon.fr/christophe.alias/evalM2/choi2013-archline-ipdps.pdf |

## F1: confirmed

**Evidence.** arxiv.org would not resolve, so I read the paper's text from a GitHub copy: raw.githubusercontent.com/lizTheDeveloper/context_engineering_1_21_26/.../papers_cache/e6961d537b90a7ce9fb50999e83aae94.txt. Its header is "arXiv:1611.07409v1 [cs.PF] 22 Nov 2016 ... A Metric for Performance Portability, S. J. Pennycook, J. D. Sewall and V. W. Lee, Intel Corporation".

Section IV gives the metric in these words: "Our proposed metric is the harmonic mean of an application's performance efficiency observed across a set of platforms. If the application fails on any measured platform(s), then we define the performance portability to be 0. Formally, for a given set of platforms H, the performance portability PP of an application a solving problem p is: PP(a,p,H) = |H| / sum_{i in H} 1/e_i(a,p) if i is supported for all i in H; 0 otherwise". Criterion 3 says the metric should "Be zero if a platform in H is unsupported". Intel's P3HPC/p3-analysis-library (p3analysis/metrics/_pp.py) gives the same formula and credits "Pennycook, Sewall and Lee".

Two small points of wording. First, the paper's prose definition of performance portability is "A measurement of an application's performance efficiency for a given problem that can be executed correctly on all platforms in a given set"; the harmonic-mean formula is the metric PP that puts it into numbers. Second, the efficiencies are for a given problem p as well as an application. Neither changes any specific in the claim.

Venue: a search extract shows the paper hosted on the PMBS16 site (dcs.warwick.ac.uk/pmbs/pmbs16/PMBS/papers/paper7.pdf and PMBS16/abstracts/paper7.html, titled "A Metric for Performance Portability"). Another extract says PMBS16, the 7th workshop, was "held as part of SC16 in Salt Lake City". The UoB-HPC/performance-portability README and the P3HPC CITATION.md both cite it as "Proceedings of the 7th International Workshop in Performance Modeling, Benchmarking and Simulation of High Performance Computer Systems (PMBS), 2016". I could not fetch the Warwick host directly.

Journal version: P3HPC CITATION.md and the UoB-HPC README cite "Implications of a Metric for Performance Portability", Future Generation Computer Systems, Volume 92, March 2019, Pages 947-958, doi 10.1016/j.future.2017.08.007. Several BibTeX entries on GitHub give the same volume, pages and year (2019). It first appeared online in 2017, as the DOI suggests. I could not reach ScienceDirect, Crossref or dblp.

## F2: corrected

**As the source supports it.** Davis, Sivaraman, Kitson, Parasyris, Menon, Minn, Georgakoudis and Bhatele, 'Taking GPU Programming Models to Task for Performance Portability' (ICS '25, June 8-11 2025, Salt Lake City; DOI 10.1145/3721145.3730423; arXiv:2402.08950) compared CUDA, HIP, Kokkos, RAJA, OpenMP, OpenACC and SYCL on five systems (Summit, Perlmutter, Zaratan, Corona, Frontier). The paper gives no 0.99-1.00 ratio for copy or triad. It says only that, for every BabelStream kernel except dot, performance is "highly consistent with the native port", and its Figure 3 shows Copy and Add runtimes, not Triad. For the dot reduction, the performance-portability metric (harmonic mean of application efficiency, after optimizations, Figure 5) is Kokkos 0.80 (not 0.89), SYCL 0.91 (not 0.85), RAJA 0.82, OpenMP 0.49, OpenACC 0.58 and the native port 0.99. Observation 3 says SYCL "comes close to providing performance portability" for dot and that "OpenMP and OpenACC struggle to provide performance portability for dot". The paper notes "generally poor reduction performance in OpenACC and OpenMP", but OpenMP's lowest score is miniBUDE (0.41), not dot.

**Evidence.** The arXiv, UMD, OSTI and pssg hosts could not be reached (DNS failure or proxy 403). The full ICS '25 proceedings PDF came from raw.githubusercontent.com/HPCRL/ICS2025-webpage/main/program/Proceedings_ICS25/ics25-63.pdf. I extracted its text and rendered page 13 to an image to read Figure 5 directly.

- **Header:** the eight authors as listed, ICS '25, DOI 10.1145/3721145.3730423. The abstract names "CUDA, HIP, Kokkos, RAJA, OpenMP, OpenACC, and SYCL".
- **Figure 5, "Harmonic Mean of Application Efficiency"**, BabelStream Dot row: Native 0.99, SYCL 0.91, Kokkos 0.8, RAJA 0.82, OpenMP 0.49, OpenACC 0.58. SYCL's values across all apps are 0.91/0.91/0.95/0.97/0.76, so 0.85 does not appear for SYCL. The only 0.85 in the figure is RAJA on su3_bench, and 0.89 does not appear anywhere.
- **Figure 2 dot runtimes in seconds** (Summit/Perlmutter/Zaratan/Corona/Frontier): Native 14.9/7.4/4.1/17.1/9.8, Kokkos 17.3/9.5/6.5/19.0/9.8, SYCL 16.5/8.0/4.7/18.0/10.2. These give Kokkos per-system ratios of about 0.63-1.00 and SYCL about 0.87-0.96, which also do not match 0.89/0.85.
- **Section 7.2.1:** "for all kernels except dot, performance across programming models is highly consistent with the native port. Figure 3 displays the performance of the add and copy kernels". No numeric copy or triad ratio is given.
- **Observation 3:** "For dot, a reduction kernel, SYCL comes close to providing performance portability across all systems, and RAJA and OpenACC provide good performance on NVIDIA systems. OpenMP and OpenACC struggle to provide performance portability for dot."
- **Section 7.4:** "generally poor reduction performance in OpenACC and OpenMP".

Not checked: earlier arXiv versions (v1 had a different title, "An Evaluative Comparison of Performance Portability across GPU Programming Models"), because arXiv was unreachable.

## F3: confirmed

**Evidence.** I could not reach futhark-lang.org or icfp24.sigplan.org (DNS failure). So I downloaded the paper PDF (fproper24.pdf) and its .bib file from the futhark-website repository on GitHub (diku-dk/futhark-website, publications/) and read the text with pdftotext.

Bibliographic details: the sole author is Troels Henriksen (University of Copenhagen). The title is "A Comparison of OpenCL, CUDA, and HIP as Compilation Targets for a Functional Array Language", in the Proceedings of the 1st ACM SIGPLAN International Workshop on Functional Programming for Productivity and Performance (FProPer '24), September 6, 2024, Milan. DOI 10.1145/3677997.3678226.

The abstract, quoted verbatim, supports every specific in the claim: "We compare the performance of OpenCL versus CUDA, and OpenCL versus HIP, on the code generated by the Futhark compiler on a collection of 48 application benchmarks on two different GPUs. Despite the generated code in most cases being equivalent, we observe significant performance differences on the same hardware, ranging from 0.42x to 1.72x in the most extreme cases. We identify the root causes of most of these differences, many of which are due to relatively superficial details such as inconsistent defaults regarding compiler optimisation and numerical accuracy, although a few remain mysterious." The conclusion adds: "The differences are often down to differing defaults regarding floating point behaviour or unavailability of accurate hardware information."

Minor points, none of which changes the verdict:
(1) The ratios are speedups of OpenCL over CUDA (on an NVIDIA A100) and of OpenCL over HIP (on an AMD MI100), not a single three-way comparison. In Figure 2 the lowest value is 0.42 (tunnel, OpenCL vs HIP).
(2) The paper's own text and figure give the top value as 1.71x (mandelbrot on MI100: "outperforms HIP by 1.71x"), while the abstract says 1.72x. The claim follows the abstract.
(3) "Largely due to default settings" slightly overstates the paper's "many" and "often". The paper also blames substantial differences on missing OpenCL features (single-pass scan, the 256-thread block limit on AMD OpenCL, imprecise cache information), and a few causes remain unexplained.

## F4: corrected

**As the source supports it.** Xiao, Chamberlain & Cabrera (Zhili Xiao, Roger D. Chamberlain, Anthony M. Cabrera), 'HLS Portability from Intel to Xilinx: A Case Study', 2021 IEEE HPEC (20-24 Sept. 2021, pp. 1-8, DOI 10.1109/HPEC49654.2021.9622785). The paper ports Rodinia Needleman-Wunsch from Intel OpenCL C to a Xilinx Alveo U250. A one-to-one (minimal-effort) port of the best Intel-optimized kernel ran in 294 s. Rewriting it in Xilinx C/C++ with burst transfers and other optimizations brought that down to 2.2 s, still slower than 0.26-0.29 s on the Intel FPGAs.

**Evidence.** Both numbers check out. The author attribution does not: Cabrera is the third and last author, not the first, so the paper should be cited as 'Xiao et al.', not 'Cabrera et al.'.

(1) IEEE Xplore metadata, read from a GitHub mirror (raw.githubusercontent.com/SJTU-YONGFU-RESEARCH-GRP/CIRDC/main/CIRDC/9622740/2021.json, articleNumber 9622785). It lists the authors in this order: "Zhili Xiao", "Roger D. Chamberlain", "Anthony M. Cabrera". It also gives publicationTitle "2021 IEEE High Performance Extreme Computing Conference (HPEC)", publicationDate "20-24 Sept. 2021" and DOI 10.1109/HPEC49654.2021.9622785.

(2) Cabrera's own publication page source (github cabreraam/cabreraam.github.io, _publications/21_xcc_hpec.md) gives the same order: "authors: Zhili Xiao, RD Chamberlain, AM Cabrera".

(3) The authors' HPEC slides (cabreraam.github.io files/presentations/21_xcc_hpec_pres.pdf, downloaded and converted to text). The 'One-to-one Porting Results of the Best Kernel' table lists the Best version on Xilinx Alveo u250 at 294 s. The later 'Performance Analysis' table, after 'Enable Burst Transfer' and the other efforts, lists the same kernel at 2.2 s. The Intel FPGAs ran it in 0.26 s (Stratix V) and 0.29 s (Arria 10). The plain baseline kernel took 322 s on the U250.

(4) Search extracts of the abstract (NSF PAR, hgpu, ORNL listing) quote: "With rewriting the kernel for burst transfer and other optimizations, we are able to reduce the execution time from an initial 294 s to 2.2 s." They also say the authors 'start with the Intel-optimized kernels and do a minimal-effort port' and then rewrite in Xilinx C/C++.

Fetching the paper PDF itself failed (cse.wustl.edu, sbs.wustl.edu, par.nsf.gov and ieeexplore all returned DNS or proxy 403 errors). The abstract wording therefore comes from search extracts, and the numbers were checked against the authors' slides.

## F5: confirmed

**Evidence.** I could not open the primary source directly. arxiv.org, the IEEE Xplore document page, hgpu.org, rcl.ece.iastate.edu, semanticscholar.org, scipedia.com, works.bepress.com and dblp.org all failed with ENOTFOUND, curl to export.arxiv.org and the Semantic Scholar API got a proxy 403, and GitHub code search was blocked. So this verdict rests on web-search extracts of the abstract. Three exact-phrase searches all returned the arXiv PDF (arxiv.org/pdf/1906.11879), the Iowa State Reconfigurable Computing Lab page (rcl.ece.iastate.edu/node/122), the hgpu.org listing and the Scipedia/bepress mirrors, and the extracts agreed with each other.

- **GPU phrase:** the exact-phrase search "GPU achieves an energy/frame reduction ratio of 1.1-3.2X" matched these sources, and the extract gives it as the GPU's energy-per-frame advantage "compared to the others for simple kernels".
- **FPGA phrase:** the exact-phrase search "FPGA outperforms the others with energy/frame reduction ratios of 1.2-22.3X" matched the same mirrors. The extract applies it to "more complicated kernels and complete vision pipelines", and adds that the FPGA does increasingly better as pipeline complexity grows.
- **Setup:** an ARM57 CPU, a Jetson TX2 GPU and a ZCU102 FPGA, each running its vendor's vision library (OpenCV, VisionWorks, xfOpenCV).
- **Authors:** Qasaimeh, Denolf, Lo, Vissers, Zambreno and Jones.
- **Venue:** ICESS 2019, DOI 10.1109/ICESS.2019.8782524, with arXiv ID 1906.11879.

The title, arXiv ID, venue, year and both ranges in the claim match. One nuance: each ratio is measured against the other two platforms ("compared to the others"). The claim leaves the baseline unstated, which is consistent with the abstract.

## F6: confirmed

**Evidence.** I read both primary sources on GitHub. (1) The PLDI 2017 paper is the PDF in the WebAssembly spec repo at papers/pldi2017.pdf, which I extracted with pdftotext. Title: "Bringing the Web up to Speed with WebAssembly". Authors: Andreas Haas, Andreas Rossberg, Derek L. Schuff, Ben L. Titzer, Michael Holman, Dan Gohman, Luke Wagner, Alon Zakai, JF Bastien. Venue: PLDI '17, June 19-24, 2017, Barcelona, DOI 10.1145/3062341.3062363. The abstract says: "WebAssembly has been designed with a formal semantics from the start." The introduction promises "a complete yet concise formal semantics of both execution and validation, including a proof of soundness" and calls WebAssembly "the first industrial-strength language or VM that has been designed with a formal semantics from the start." The repo's papers/README.md gives the same title, authors and venue, so "Haas et al., PLDI 2017" is correct. (2) The 'Nondeterminism' document is Nondeterminism.md in the WebAssembly/design repo (raw.githubusercontent.com, main branch). It lists three items that match the claim. NaN bits: "when an arithmetic operator returns NaN, there is nondeterminism in determining the specific bits of the NaN"; it also says the NaN sign bit is nondeterministic. Shared memory: "With `shared` memory that can be accessed by multiple threads, the results of load, read-modify-write, wait, and awake operators are nondeterministic." SIMD: "The [relaxed SIMD] instructions have nondeterministic results." Two small wording points. The document never uses the word "races"; it describes nondeterministic results of shared-memory operations under multiple threads, so "shared-memory races" is a fair paraphrase. "Some SIMD results" means the relaxed SIMD instructions specifically. The document lists other items too (feature support, outside calls and arguments, resource exhaustion), and the claim does not say its three items are the whole list. arxiv, ACM DL and the publisher sites were unreachable, but the GitHub-hosted PDF is the paper's own text.

## F7: confirmed

**Evidence.** dl.acm.org, Crossref, OSTI, dblp and the Berkeley host could not be reached (DNS failure or proxy 403). The primary paper came instead from the first author's own copy in the GitHub repo willow-ahrens/willow-ahrens.github.io, file assets/documents/ahrens_algorithms_2020.pdf, footer "Most up-to-date version: 11/08/2023". Its ACM reference line reads: "Willow Ahrens, James Demmel, and Hong Diep Nguyen. 2020. Algorithms for Efficient Reproducible Floating Point Summation. ACM Trans. Math. Softw. 46, 3, Article 22 (July 2020), 49 pages. https://doi.org/10.1145/3389360". So the title, authors, journal, volume, issue, year and DOI all match the claim. The abstract says: "We describe a 'reproducible accumulator' data structure (the 'binned number') and associated algorithms to reproducibly sum binary floating point numbers, independent of summation order ... Our approach requires only one read-only pass over the data, and one reduction in parallel, using a 6-word reproducible accumulator". This supports "order-independent summation with a binned accumulator in one read-only pass". On the ReproBLAS tag, the conclusion says: "In the future, we will show how our methods have been used to create reproducible ... sums, dot products, norms, ... in an optimized library called ReproBLAS." So the paper describes the algorithms behind ReproBLAS but is not itself the ReproBLAS library paper; the claim's parenthetical tag is a fair reading of that. Minor note: the first author appears as "Peter Ahrens" in older copies (a search extract of an IEEE Milestones PDF) and as "Willow Ahrens" in the current ACM record. The surname Ahrens is correct either way. A web-search extract of the ACM DL page also agreed: TOMS Vol. 46, Issue 3, Article 22, online 21 July 2020.

## F8: corrected

**As the source supports it.** Arteaga, Fuhrer and Hoefler, 'Designing Bit-Reproducible Portable High-Performance Applications', IPDPS 2014 (28th IEEE IPDPS, Phoenix, pp. 1235-1244, DOI 10.1109/IPDPS.2014.127), names transcendental function evaluation and non-associative reductions as the sources of non-reproducibility it studies. It reports low overhead for its fixes: its tuned reproducible transcendental functions were, in the geometric mean, faster than the platform libraries on five systems and 10 functions, and its reproducible sum was at most about 10% slower out of cache. The "FMA disabled, roughly 3-4x slowdown for libm-heavy code" figure is not from this paper. It comes from a much later Fortran/OpenACC fork of the bitrep library (github.com/loicreynier/bitrep). That fork's README reports a "~3.5 to 4.5x slowdown" on a sin+cos+exp+log+atan kernel with NVHPC 25+, and its build uses -Mnofma and -fmad=false. A Fortran Discourse post about that fork describes the same thing.

**Evidence.** The paper's PDF could not be fetched: unixer.de, htor.inf.ethz.ch, spcl.inf.ethz.ch, researchgate and web.archive.org were all blocked (DNS failure or proxy 403). The paper's content below therefore comes only from search extracts of the paper's PDFs (unixer.de arteaga-fuhrer-hoefler-reproducible-apps-ipdps14.pdf and htor.inf.ethz.ch/sec/bitrep-ipdps.pdf) and from the dblp and hgpu records.
(1) Bibliographic details: authors Andrea Arteaga, Oliver Fuhrer and Torsten Hoefler; IPDPS 2014, Phoenix, pp. 1235-1244 (dblp); IEEE document 6877351. All match the claim.
(2) Scope, from an abstract extract: "identify the possible sources of non-reproducibility... evaluating transcendental functions and performing reductions using non-associative operators." This supports the first half of the claim. An extract also shows the paper describing FMA as a single-rounding IEEE 754-2008 operation, but I found no extract saying the paper disables FMA.
(3) Performance, from a contribution-list extract: "our tuned reproducible implementation is (in the geometric mean) even faster than the platform libraries on five systems and 10 functions." Another extract says the reproducible sum is at most about 10% slower than non-reproducible reductions in the out-of-cache case. Both contradict a 3-4x libm slowdown. One unconfirmed extract also says COSMO physics ran about 2.5x slower on CPU because of compiler constraints, which is still not 3-4x.
(4) Where the 3-4x figure actually comes from: I fetched raw.githubusercontent.com/loicreynier/bitrep/main/README.md. It says it is the "Original source by Andrea Arteaga... ported to GPU through OpenACC or OpenMP" and that "the cost to pay for bit-reproducibility seems to be a **~3.5 to 4.5x slowdown** (NVHPC, 25+)", with a measured "Overhead: 4.56x" on NVHPC 26.1. Its CMakeLists.txt sets -Kieee;-Mnofma, -fmad=false and -no-fma. A search extract of the Fortran Discourse thread (bit-reproducibility on GPU-accelerated Fortran) also mentions disabling FMA and a roughly 3-4x slowdown. These are recent community sources, not the 2014 paper.

## F9: corrected

**As the source supports it.** Deterministic Atomic Buffering (DAB; Chou, Ng, Cattell, Intan, Sinclair, Devietti, Rogers, Aamodt; MICRO-53, 2020, pp. 981-995, DOI 10.1109/MICRO50266.2020.00083) makes GPU atomics deterministic using hardware buffers that hold atomic results apart from other threads and make them visible later in a fixed order. In simulation, on atomic-intensive applications, it runs 4x faster than GPUDet and averages a 23% slowdown compared with a non-deterministic GPU architecture.

**Evidence.** I could not fetch any primary copy. The microarch.org/micro53 PDF, the Purdue and UBC author PDFs, computer.org CSDL and NSF PAR all failed with DNS errors (ENOTFOUND). Everything below comes from two separate search-result extracts of the abstract, which agree with each other. They quote the abstract as: "for atomic-intensive applications, DAB performs 4x better than GPUDet and incurs only a 23% slowdown on average compared to a non-deterministic GPU architecture." They describe the mechanism as "the crux of the approach is providing hardware buffers for atomic operations to keep them isolated from other threads," and give the venue as the 2020 53rd IEEE/ACM International Symposium on Microarchitecture (MICRO), pp. 981-995. The claim gets the venue, the year, the hardware mechanism and the 23% average right. It leaves out the abstract's limit that the 23% applies to atomic-intensive applications, and that the figure is the authors' own simulation result. As written, the claim reads like an overhead across all workloads, which the abstract does not say.

## F10: corrected

**As the source supports it.** Both 2026 arXiv preprints exist, but each is described inaccurately. (1) arXiv 2608.17390 is Dzmitry Malyshau, "Six Ways to Draw Vangers with WebGPU: Real-Time Rendering of Editable Multi-Layer Height Fields" (cs.GR, v1 announced 2026-08-18). It compares six terrain-rendering methods in wgpu/WebGPU. It does not claim that results were bit-identical. It reports "agreement" of the five result grids across four Vulkan adapters (Radeon 780M, Radeon 7900 XT, Intel, RTX 5070) and Apple Metal (M3), and calls this "image agreement". It also reports a measurable spread between devices: Scattered hangar 73.2% on the 780M versus 74.0% on the M3. (2) arXiv 2609.11356 is Ziteng Yang, Nicholas J. Riasanovsky, Warren Deng and Vivek Sarkar (four authors, not "Yang and Deng"), "Taming Bitwise Behavior in GPU Kernels with Tensor Core: Black-Box Reconstruction, Compiler Enforcement, and Static Verification" (submitted 2026-09-10). It enforces balanced-tree reduction during Triton lowering. The step that brings 19 of 27 kernels on GB300 and H100 within 10% of free-order performance is an added data-layout optimization, not the enforcement alone.

**Evidence.** arxiv.org was unreachable (DNS failure), as were export.arxiv.org, Semantic Scholar, Hugging Face, alphaxiv and hgpu. I verified through GitHub copies of arXiv RSS and API data, the author's own LaTeX source, and search extracts of the arXiv HTML.

2608.17390: the ehijano/rss_fetch file rss_data/cs.GR/2026-08-18_cs.GR.xml gives the title, ID and abstract ("All six implementations use the same native wgpu / WebGPU API and canonical WGSL"). Lyken17/arXiv-stats lists the author as Dzmitry Malyshau. kvark/kvark.github.io about.md lists the paper. I downloaded the full LaTeX source, kvark/vange-rs paper/paper.tex. Its own wording is "Agreement" (line 87): "Agreement of the five result grids across four Vulkan adapters and Apple Metal is the direct portability result; timing remains backend- and device-specific". Line 573 says "It establishes native WebGPU execution and image agreement across those backends". Line 303 says "The five image grids agree on that geometry: hangar Mesh see-through is 0.519% on every adapter. The only material cross-device spread is inside the already failing Scattered hangar row (73.2% on the 780M versus 74.0% on the M3)." The source contains no "bit-identical" or "bitwise" at all. Search extracts of arxiv.org/html/2608.17390 quote the same "Agreement of the five result grids" sentence, so the GitHub source matches the arXiv text.

2609.11356: the arXiv abstract appears in ehijano/rss_fetch rss_data/cs.DC/2026-09-11_cs.DC.xml (oai:arXiv.org:2609.11356v1) and in an arXiv API cache with updated date 2026-09-10. The decisive sentence is "Second, we enforce balanced-tree reduction during Triton lowering and introduce a data-layout optimization that brings 19 of 27 kernels on GB300 and H100 within 10 percent of free-order performance." The full-text copy in SichangHe/paper_collection agrees: "bringing 19 of 27 kernels across GB300 and H100 within 10% of the free-order mode". The four authors (Ziteng Yang, Nicholas J. Riasanovsky, Warren Deng, Vivek Sarkar) are confirmed by lonePatient's arXiv listing, the first author's homepage (Youngzt998.github.io) and several BibTeX entries.

## F11: confirmed

**Evidence.** I could not fetch the paper itself. arxiv.org, export.arxiv.org, dl.acm.org, osti.gov, ornl.gov, olcf.ornl.gov, semanticscholar.org, alphaxiv.org and r.jina.ai all failed on DNS, and a direct curl to arxiv.org was refused by the proxy with a 403. Everything below therefore comes from search-result extracts that index the arXiv PDF and the unpaywall/ACM copies.

What checks out:
- Title, ID and date: "Experiences Readying Applications for Exascale", arXiv:2310.01586, submitted 2 Oct 2023. It was also published at SC '23 as DOI 10.1145/3581784.3607065.
- ORNL attribution: the paper describes readying applications for the Oak Ridge Leadership Computing Facility's (OLCF) Frontier system. On arXiv the first author is Paul T. Bauman, with 32 authors in total. Most are from ORNL; others are from AMD, NREL, Sandia and HPE. Calling it an ORNL paper is fair. Note that the ACM/SC23 listing names Nicholas Malaya first.
- Method: three separate searches returned the same extract. OLCF staff used AMD's hipify tool to convert the CUDA SHOC benchmarks to HIP. They then compared the two versions on Summit's NVIDIA GPUs.
- The number: the decisive sentence, which appears to be a figure caption, reads "Average normalized HIP performance was 99.8% of CUDA performance when considering data transfer costs, 99.9% without." So the 99.8% figure is correct.

Context the claim leaves out:
- 99.8% is the figure with data transfer included. Without data transfer it is 99.9%.
- The tests ran on NVIDIA V100 GPUs (Summit), not on AMD hardware. The paper notes that HIP is a header-only layer when targeting NVIDIA, so "the HIP SHOC programs are CUDA executables once compiled and linked". The number shows HIP adds almost no overhead on NVIDIA hardware. It does not compare AMD performance with CUDA.

The 2019 OLCF slide deck by Roth ("HIP on Summit") is consistent with this. Search extracts of it give the same 99.8% (with transfer) and 99.9% (without), plus a QTC outlier about 44-45% slower, linked to texture memory.

## F12: confirmed

**Evidence.** I could not open the full text. Every PDF host failed with DNS or proxy 403 errors: repository.gatech.edu, hpcgarage.org (GT-CSE-2012-01), jeewhanchoi.github.io, perso.ens-lyon.fr (the IPDPS preprint), vuduc.org, dblp.org and semanticscholar.org. So this verdict rests on search-engine extracts of the paper, not on reading it myself.

Bibliographic details: a DBLP extract gives "A Roofline Model of Energy", IPDPS 2013, pp. 661-672, with authors JeeWhan Choi, Daniel Bedard, Robert J. Fowler and Richard W. Vuduc in that order. This matches the claim. One reference lists them as "J. W. Choi, D. Bedard, R. Fowler, and R. Vuduc ... 27th IEEE IPDPS 2013". An earlier Georgia Tech technical report has the same title (GT-CSE-2012-01, December 2012).

Curved roofline: extracts of the paper and preprint say the time and energy models differ. Time is the max of T_flops and T_mem because the two are assumed to overlap. Energy adds E_flops, E_mem and a constant-energy term E0(T). They state that "the energy-based 'roofline' is actually a smooth 'arch line' (see fig. 2a)", because time can overlap but energy cannot. A secondary summary (arXiv 1908.06115) agrees: "the energy roofline has an arched 'roof' due to the fact that runtime can be overlapped while energy consumption cannot."

Energy-balance point: a preprint extract reads "B_ε ≡ ε_mem/ε_flop is the energy-balance point", named by analogy to time-balance. The paper's Fermi-class GPU example gives time-balance of about 3.6 and energy-balance of about 14 flop:byte. This difference is the "balance gap".

The claim is supported on every point: venue, year, the four authors, the curve coming from energy not overlapping, and the energy-balance point.
