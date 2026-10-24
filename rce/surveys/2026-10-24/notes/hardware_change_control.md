# Working note 3: versions, change and continuous improvement in digital and analog hardware

Written 24 October 2026. Direct page fetches were blocked for all external hosts; every source was located by live search and its bibliographic details confirmed from indexed page text. Normative text of DO-254 and DO-178C was not accessible; those items rest on practitioner quotations. Vendor figures are marked.

## 1. Engineering change orders, metal-only fixes, respins

- Tan, Jiang, "Recent Research Development in Metal-Only ECO", IEEE MWSCAS 2011: metal-only ECOs reuse base-layer masks by rewiring pre-placed spare cells, which are "limited both in number and in cell types". https://ir.lib.nycu.edu.tw/handle/11536/14576
- Chang, Jiang, Chang, "Timing ECO optimization using metal-configurable gate-array spare cells", DAC 2012, pp. 802-807: conventional spare cells "always consume leakage power despite their inputs being tied off".
- Mask-set cost by node: hundreds of thousands of dollars at 90 to 45 nm, beyond $1M at 28 nm, beyond $10M at 7 nm (analyst estimate). Patel, "The Dark Side of the Semiconductor Design Renaissance", SemiAnalysis, 2022. A 2026 analyst table gives about $3.5M (7 nm), $6.5M (5 nm), $15M (3 nm) for masks; the two estimates conflict at 7 nm. https://siliconanalysts.com/analysis/fabless-startup-tapeout-cost-guide
- First-silicon success fell to 14% of IC and ASIC projects in 2024, the lowest in two decades (86% need at least one respin); 30 to 33% from 2010 to 2020. Siemens EDA and Wilson Research Group, "2024 IC/ASIC Functional Verification Trend Report". https://verificationacademy.com/topics/planning-measurement-and-analysis/wrg-industry-data-and-trends/2024-siemens-eda-and-wilson-research-group-ic-asic-functional-verification-trend-report/ Earlier editions: Foster, Verification Horizons, 2016 and 2019 (logic and functional flaws the leading respin cause).
- Synopsys Formality ECO verifies only the affected logic cones between the ECO RTL and the unmodified netlist and emits the physical change commands. https://www.synopsys.com/glossary/what-is-functional-eco.html ; Formality datasheet.
- Cadence Conformal ECO Designer: pre- and post-mask ECO "with metal layers and spare gates"; a customer case reported about 50% schedule reduction and more than 60% mask-cost savings (vendor press release, 2016). https://www.cadence.com/en_US/home/resources/datasheets/conformal-eco-designer-ds.html

## 2. PDKs, IP versioning, design reuse

- IEEE Std 1685-2022 (IP-XACT): XML schema and consistency rules for packaging IP metadata and a tool-portable generator interface; supersedes 1685-2014 and 1685-2009. https://standards.ieee.org/ieee/1685/10583
- Keating, Bricaud, Reuse Methodology Manual for System-on-a-Chip Designs, 3rd ed., Kluwer, 2002: blocks not designed for reuse have "often provided little or no benefit".
- Saleh et al., "System-on-Chip: Reuse and Integration", Proceedings of the IEEE 94(6):1050-1069, 2006.
- Methodics by Perforce survey, 2022 (vendor-sponsored): about 40% say locating the right IP takes a day or more; 75% struggle to judge an IP block's context and quality.
- Open PDKs carry their own version strings (open_pdks builds; SKY130A v9.3.624-374 built with Open-PDKs v1.0.313) and are distributed through a PDK package manager (Ciel, formerly Volare). https://github.com/rtimothyedwards/open_pdks ; https://openlane2.readthedocs.io/en/latest/usage/about_pdks.html
- US Patent 10,719,657 (2020): a PDK scan script decides which pcells need regression testing when a PDK is revised.

## 3. Hardware revision control and configuration-management standards

- KiCad has no native semantic diff; a raw git diff of a schematic is "dominated by formatting and reordering noise"; community tools image-diff rendered layers (KiDiff, KiRI) or report nets added, removed and rewired (kigit). https://pypi.org/project/kidiff ; https://github.com/leoheck/kdiff ; https://pypi.org/project/kigit/
- Altium: Git repositories are created outside the application; it "does not fully support working with LFS repositories and doing so can lead to loss of user data". https://www.altium.com/documentation/altium-designer/using-external-version-control/git
- ASME Y14.35-2014 (R2019), "Revision of Engineering Drawings and Associated Documents": revision letters A, B, ... skipping I, O, Q, S, X, Z; every post-release change is logged in the revision block.
- ISO 10007:2017, "Quality management: guidelines for configuration management": planning, identification, baselines (5.3.3), change control (5.4), status accounting, audit. https://www.iso.org/standard/92170.html
- SAE EIA-649C (2019): five functions, planning, identification, change management, status accounting, verification and audit; MIL-HDBK-61A (2001) draws its principles from EIA-649; GEIA-HB-649A consolidates.
- Physical Configuration Audit: the item "as built" is examined against the documentation that defines it to establish the product baseline. US DoD IG Report 96-130, 1996.
- RTCA DO-254 section 7 (as quoted by Patmos Engineering): configuration management provides "the ability to consistently replicate the configuration item, regenerate the information if necessary and modify the configuration item in a controlled fashion"; HC1 items change after release only through a formal problem report. https://patmos-eng.com/?p=696
- RTCA DO-178C Table A-8: configuration identification, baselines and traceability, problem reporting, change control; AC/AMC 20-189 issued to curb long uncategorised open-problem-report lists.
- ISO 26262-8:2018, clause 7 configuration management and clause 8 change management. https://www.iso.org/standard/68390.html

## 4. Analog: why reuse and re-versioning are hard

- Gielen, Rutenbar, "Computer-Aided Design of Analog and Mixed-Signal Integrated Circuits", Proceedings of the IEEE 88(12), December 2000, doi:10.1109/5.899053.
- "Analog design is highly sensitive to device physical parameters and parasitics and to global technology constraints. This makes the retargeting of an analog portion of any design a tough task and is still a manual process." Electronic Design, "Automating Analog IP Process Migration". https://www.electronicdesign.com/technologies/analog/article/21750688/automating-analog-ip-process-migration
- "Even at any single process technology node, it is rare to see two foundries with the exactly same process." Design & Reuse, "Analog IP Integration in SoC". https://us.design-reuse.com/articles/20203/analog-ip-integration-soc.html
- Thalia Design Automation migration case (vendor): "total automation is a myth"; a large part of the effort is re-qualifying the IP in the target technology. https://us.design-reuse.com/articles/48927/solving-a-problem-like-reuse.html
- Analog as a respin driver: "tuning analog circuitry" in 41% of respin cases (Wilson 2020), nearly double 2018; 47% of sub-1M-gate ASICs had analog-caused respins (Wilson 2022). https://www.techdesignforums.com/?p=10056 ; https://semiengineering.com/analog-creates-ripples-in-digital-verification
- Kunal et al., "ALIGN: A System for Automating Analog Layout", IEEE Design & Test 2020, arXiv:2008.10682; Chen et al., "MAGICAL: An Open-Source Fully Automated Analog IC Layout System from Netlist to GDSII", IEEE Design & Test 38(2):19-26, 2021.

## 5. FPGA bitstreams, reconfiguration, open toolchains, hardware CI

- Vipin, Fahmy, "FPGA Dynamic and Partial Reconfiguration: A Survey", ACM Computing Surveys 51(4), 2018, doi:10.1145/3193827: partial reconfiguration "find[s] limited use in deployed systems".
- AMD UG909, Vivado Dynamic Function eXchange, 2025.1: one full bitstream per configuration and one partial bitstream per reconfigurable module; static placement shared through checkpoints.
- Build determinism: 20 placement-exploration runs gave inconsistent results, attributed to placer randomisation (Plunify PIN001, 2017); no authoritative AMD statement on bit-identical rebuilds was found.
- CHIPS Alliance F4PGA workgroup (18 February 2022): the toolchain formerly SymbiFlow, the FPGA Interchange Format and FASM. https://us.design-reuse.com/news/51460/chips-alliance-f4pga-workgroup-open-source-fpga-tools.html
- OpenTitan CI: public GitHub Actions, a private CI for proprietary EDA tools with public pass/fail, FPGA boards at lowRISC, nightly regressions with coverage (more than 40,000 tests per the FAQ); at RTL freeze 140 contributors and more than 13k merged pull requests. https://opentitan.org/book/doc/contributing/ci/index.html ; https://lowrisc.org/news/opentitans-rtl-freeze-leveraging-transparency-to-create-trustworthy-computing/
- FuseSoC; LibreCores CI (2019); CERN CMS automated FPGA firmware builds (2019). https://indico.cern.ch/event/799025/contributions/3523397

## 6. Hardware construction languages and generators

- Bachrach et al., "Chisel: Constructing Hardware in a Scala Embedded Language", DAC 2012, pp. 1212-1221 (DAC most influential paper 2010-2020).
- Izraelevitz et al., "Reusability is FIRRTL Ground", ICCAD 2017, pp. 209-216, doi:10.1109/ICCAD.2017.8203780: a target-independent IR with technology-specific transformations.
- CIRCT: MLIR applied to hardware tools, motivated by EDA tools being "inconsistent ... not designed together into a common platform". https://circt.llvm.org/ ; Neuendorffer, llvm-dev, July 2020.
- SpinalHDL ("a regular Scala library"); Amaranth (Python; not yet at 1.0 per its NLnet page).

## 7. Continuous improvement, design for change, MBSE

- Imai, Kaizen: The Key to Japan's Competitive Success, McGraw-Hill, 1986; Deming, Out of the Crisis, MIT CAES, 1986; Shewhart cycle (1939).
- Ward, Liker, Cristiano, Sobek, "The Second Toyota Paradox", Sloan Management Review 36:43-61, 1995; Sobek, Ward, Liker, "Toyota's Principles of Set-Based Concurrent Engineering", SMR 40:31-40, 1999: keep sets of alternatives open until late.
- Morgan, Liker, The Toyota Product Development System, Productivity Press, 2006.
- Fricke, Schulz, "Design for changeability (DfC)", Systems Engineering 8(4):342-359, 2005: flexibility, agility, robustness, adaptability.
- OMG SysML v2.0, KerML 1.0 and the Systems Modeling API 1.0 adopted June and July 2025. https://www.omg.org/news/releases/pr2025/07-21-25.htm

## 8. Formal equivalence checking across revisions

- Cadence Conformal Equivalence Checker: RTL through final netlist without test vectors (datasheet). Synopsys Formality (datasheet).
- Baumgartner, Mony, Paruthi, Kanzelman, Janssen, "Scalable Sequential Equivalence Checking across Arbitrary Design Transformations", ICCD 2006: retiming, clock gating and changed initialisation that combinational checking cannot handle.
- Cadence JasperGold SEC App (2014 launch; vendor figures 2 to 10x over a general property engine).

## What this note establishes

1. Hardware has a routine, tool-supported formal proof that a change preserved behaviour (combinational and sequential equivalence checking), applied as a gate on every revision; software's nearest mainstream analogue, reproducible builds, checks that a binary matches its source, not that a change preserved meaning.
2. Hardware has standardised, audited configuration management with baselines, as-built audits and problem-report-driven change control (ISO 10007; EIA-649; PCA; DO-254; ISO 26262-8); semantic versioning is a self-declared contract with no audit against the artifact.
3. Hardware quantifies the cost of a failed change and plans for it (spare cells; mask sets beyond $10M at 7 nm; 86% of 2024 projects needing a respin); software measures change by throughput and recovery (Forsgren, Humble, Kim, Accelerate, 2018).
4. Software has semantic diff and merge natively on its source form; hardware's canonical artifacts diff only by rendered images or bespoke tools, and the hardware-construction-language movement is an attempt to import software's single-source, compiler-driven model.
5. Software CI assumes deterministic, cheap rebuilds; hardware CI must work around proprietary tools, long place-and-route and placement randomisation that makes bit-identical rebuilds unreliable, while partial reconfiguration, hardware's mechanism for versioned field updates, finds limited deployed use.
