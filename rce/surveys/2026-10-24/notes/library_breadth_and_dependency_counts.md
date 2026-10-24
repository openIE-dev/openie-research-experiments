# Working note 16: Comparative evidence linking standard-library breadth to dependency counts, trivial packages and vulnerabilities

Raised by the completeness critic: The batteries-included side rests on one empirical claim: a broad standard library reduces micro-dependencies and supply-chain risk. The opposing claim is that standard-library modules decay ('where modules go to die', PEP 594) and carry vulnerabilities of their own. The notes describe npm risks, Maven bloat, left-pad and the Decan/Mens networks one ecosystem at a time. No source compares ecosystems by standard-library breadth or measures vulnerability rates in standard libraries against third-party packages, so the synthesis cannot yet support or refute this central claim.

Written 24 October 2026 by a research agent with web search; github.com was reachable and most other hosts were not, so many sources were confirmed from search extracts, as each bullet says. Not independently re-verified claim by claim, unlike notes 7 and 8.

**Access limits this run.** The shared web-search budget was used up before my first query, so I ran no searches at all. arxiv.org, link.springer.com, dl.acm.org, usenix.org, ieeexplore, dblp and openalex all failed DNS resolution. Everything below therefore comes from GitHub-hosted primary data, authors' replication or dataset repos, and Oracle's advisory pages. I could not read the text of any candidate paper. You can send a follow-up to run the paper searches once the budget is available.

**Dependency counts across ecosystems**
- I recomputed snapshot metrics at 2017-01-01 from Decan's replication repo `ecos-emse`. I followed its `helpers.py` exactly: runtime dependencies only, latest release of each package, a package-level graph, and npm "fun packages" removed. The repo has no label, but its seven-ecosystem list and 2012–2017 date range match the paper. Results, counting only packages that have at least one dependency (median direct / median transitive / mean transitive):
  - Cargo: 7,421 packages, 71.0% with dependencies; 2 / 41 / 34.5
  - CPAN: 33,673 packages, 72.0%; 3 / 14 / 28.2
  - CRAN: 11,071 packages, 71.3%; 2 / 6 / 14.2
  - npm: 409,049 packages, 61.7%; 2 / 21 / 67.6 (90th percentile 187)
  - NuGet: 75,886 packages, 54.4%; 2 / 27 / 39.4
  - Packagist: 88,662 packages, 67.7%; 2 / 7 / 14.1
  - RubyGems: 128,422 packages, 60.6%; 2 / 7 / 13.1
  - Paper: Decan, Mens, Grosjean, "An empirical comparison of dependency network evolution in seven software packaging ecosystems", Empirical Software Engineering 24(1):381–416, 2019, doi:10.1007/s10664-017-9589-y. Replication repo: https://github.com/AlexandreDecan/ecos-emse (commit 0596a7a).
- The Cargo 41, npm 21 and NuGet 27 medians match the values that an earlier survey note in this workspace attributes to the paper [secondhand]. That note is `/home/user/openie-research-experiments/rce/surveys/2026-10-24/notes/batteries_versus_specification.md`.
- The paper does not include PyPI, Go or Maven, so the ecosystems with the broadest standard libraries are absent.
- Kula, Ouni, German, Inoue, "On the Impact of Micro-Packages: An Empirical Study of the npm JavaScript Ecosystem", arXiv:1709.04638, 2017, https://arxiv.org/abs/1709.04638. I confirmed only the bibliographic record, through Kula's own site repo (github.com/raux/raux.github.io, `data/papers.yaml`), which lists it as a preprint. No findings were verified.

**Supply-chain incidents by ecosystem**
- The OpenSSF malicious-package database holds these report counts: npm 222,434; PyPI 11,922; RubyGems 4,305; NuGet 782; crates.io 21; Go 20; Open VSX extensions 17; Maven 2; Packagist 1. The counts are not adjusted for registry size, detection-feed coverage or install-hook semantics. Source: OpenSSF, ossf/malicious-packages, `osv/malicious/`, commit ef188da (24 Oct 2026), https://github.com/ossf/malicious-packages.
- The Backstabber's Knife Collection dataset now lists 23,771 malicious package names: npm 15,606; PyPI 4,345; RubyGems 3,763; VS Code extensions 35; Maven 13; Composer 5; Cargo 4. Its landing page describes attacks "starting 2015". This is the grown dataset, not the 2020 paper's sample; I could not verify the paper's own numbers. Source: Ohm, Plate, Sykosch, Meier, dataset at https://github.com/dasfreak/Backstabbers-Knife-Collection (`data/packages.json`, commit 4d03199, 12 Oct 2026). Paper: "Backstabber's Knife Collection: A Review of Open Source Software Supply Chain Attacks", DIMVA 2020, Springer, doi:10.1007/978-3-030-52683-2_2.
- SAP's Risk Explorer attack tree has 118 nodes (88 leaves, depth 6), 43 safeguards and 379 references. Its README says "100+ attack vectors and techniques" [self-reported] and links the SoK at arXiv:2204.04008. This is the current taxonomy, not the version in the paper. Source: https://github.com/SAP/risk-explorer-for-software-supply-chains (`src/data/*.json`, commit 79e2a39, 27 May 2026). Ladisa, Plate, Martinez, Barais, "SoK: Taxonomy of Attacks on Open-Source Software Supply Chains", IEEE S&P 2023, doi:10.1109/SP46215.2023.10179304. I wrote these citation details from memory; only the arXiv link was confirmed.

**Vulnerabilities in standard libraries (counted from primary databases)**
- **Go:** 181 vulndb reports list module `std`. 162 affect only the standard library and 19 are shared with `golang.org/x` modules. A further 34 list `cmd` (the toolchain).
  - By CVE year: 2014–2020 had 24 in total, then 2021: 15, 2022: 34, 2023: 23, 2024: 11, 2025: 27, 2026: 47.
  - Most affected packages: net/http 33, crypto/x509 21, crypto/tls 15, html/template 14.
  - The database started in 2021, so earlier years are backfilled selectively.
  - Source: Go team, golang/vulndb, `data/reports`, commit e0bad56 (20 Oct 2026), https://github.com/golang/vulndb; served at https://pkg.go.dev/vuln.
- **CPython:** 196 PSF advisories, all against github.com/python/cpython, with CVE years 2007–2026. Recent years: 2024: 15, 2025: 20, 2026: 39; 15 advisories have no CVE alias. Historical entries were imported from vstinner/python-security. Source: Python Software Foundation, psf/advisory-database, commit 234ce11 (23 Oct 2026), https://github.com/psf/advisory-database.
- **Node.js core:** 204 NSWG-COR records covering 208 distinct CVEs from 2015–2026. Recent years: 2023: 29, 2024: 15, 2025: 14, 2026: 43. `index.json` lags behind at 194 entries. Source: Node.js Security Working Group, nodejs/security-wg `vuln/core`, commit 072e7e1 (22 Oct 2026), https://github.com/nodejs/security-wg.
- **Rust std:** RustSec's `rust/std` has 18 advisories (2015–2022), including CVE-2021-31162 (double free in `Vec::from_iter`) and CVE-2022-21658 (`remove_dir_all` race). Rust's release notes add CVE-2024-24576 and CVE-2024-43402, both in `std::process::Command` and neither in RustSec. That makes at least 20, and neither source is complete. Sources: rustsec/advisory-db commit 21d909e (24 Oct 2026), https://github.com/rustsec/advisory-db; rust-lang/rust `RELEASES.md` (master, fetched 24 Oct 2026).
- **Java SE:** new security patches per quarterly Critical Patch Update were:
  - 2023: 4, 8, 9, 5 (total 26)
  - 2024: 13, 13, 7, 8 (total 41)
  - 2025: 2, 6, 11, 5 (total 24)
  - 2026: 11, 11, 19, 55 (96 so far); in Oct 2026, 49 of the 55 may be remotely exploitable without authentication.
  - The 2025 risk matrices also cover JavaFX (WebKitGTK, gstreamer), bundled Node.js, the installer and Native Image, so these are not only class-library flaws.
  - Source: Oracle, Critical Patch Update Advisories, Jan 2023–Oct 2026, e.g. https://www.oracle.com/security-alerts/cpuoct2026.html.

**Why developers pick a third-party package over the standard library**
- I found no empirical study I could verify; only maintainers' own statements:
  - CPython's urllib.request docs say "The Requests package is recommended for a higher-level HTTP client interface" [self-reported]. Source: Python documentation, "urllib.request", https://docs.python.org/3/library/urllib.request.html (`Doc/library/urllib.request.rst`, cpython main, 24 Oct 2026).
  - PEP 594 says batteries included "was one of the cornerstones to Python's success story", cites the ease of installing from PyPI, and claims "a majority of users only pick third-party modules to replace a stdlib module, when they have a compelling reason, e.g. lxml instead of xml". That claim has no supporting data [self-reported]. Source: Heimes, Cannon, "PEP 594 – Removing dead batteries from the standard library", 2019, Final (Python 3.11), https://peps.python.org/pep-0594/.
  - The Temporal proposal states "`Date` has been a long-standing pain point in ECMAScript"; the README marks it Stage 4. Source: TC39, proposal-temporal README, https://github.com/tc39/proposal-temporal (27 Jul 2026).
  - Moment's maintainers call it "a legacy project in maintenance mode" (2020). In 2026 they report weekly downloads "more than tripled", which they attribute mostly to coding agents choosing it [self-reported]. Sources: Moment.js, "Project Status", 14 Sep 2020, https://momentjs.com/docs/#/-project-status/; "Project Status Update", 17 Aug 2026 (moment/momentjs.com, `news/moment/`).
  - The Go blog credits "the rich standard library" and a "culture of rejecting large dependency trees" for applications "with just a handful of dependencies". It gives no measurement [self-reported]. Source: Valsorda, "How Go Mitigates Supply Chain Attacks", The Go Blog, 31 Mar 2022, https://go.dev/blog/supply-chain.
- Not verified (paper text unreachable): Abdalkareem et al. (ESEC/FSE 2017, doi:10.1145/3106237.3106267) and the npm/PyPI extension in EMSE 2020 (doi:10.1007/s10664-019-09792-9); Kula et al.'s findings; Ohm et al.'s sample size; Zimmermann et al. (USENIX Security 2019); any Go module dependency-depth study.

**Confounders**
- **What counts as "stdlib":** Node core and Java SE include runtime, VM and bundled third-party code; Go's std includes net/http and crypto; CPython advisories cover the interpreter too.
- **Counting policies:** when each project became a CVE Numbering Authority (CNA), when each database started, and backfill differ.
- **Ecosystem age:** Cargo was about 2.5 years old in the 2017 snapshot.
- **Package granularity:** npm micro-packages are much smaller units than a Go module.
- **Registry and detection:** registry size and how hard each registry is watched drive the malicious-package counts.
- **Install semantics:** install-time scripts exist in npm and PyPI; Go fetches from version control without them.
- **Culture:** Go's stated norms against dependencies.

**What this establishes**
- No study I could verify treats standard-library breadth as a measured variable, let alone controls for it. The seven-ecosystem comparison has median direct dependencies of 2–3 everywhere; the differences are in transitive reach (Cargo 41, NuGet 27, npm 21, CPAN 14, Packagist and RubyGems 7, CRAN 6), and it omits Python, Go and Java (Decan et al. 2019 replication data).
- Malicious-package reports are concentrated in npm, then PyPI and RubyGems, with Go and crates.io near zero (OpenSSF; Backstabber's dataset). Python has a broad standard library yet ranks second, so these data do not isolate any protective effect of breadth from registry size, detection effort or install hooks.
- Standard libraries have a steady flow of vulnerabilities of their own, concentrated in networking, cryptography and parsers. Go std has 181 reports (27 with 2025 CVEs), CPython 196 advisories, Node core 208 CVEs, Java SE 24–96 patches a year, Rust std at least 20 (golang/vulndb; psf/advisory-database; nodejs/security-wg; Oracle CPUs; RustSec and Rust release notes).
- The available evidence for why developers choose third-party over standard-library modules is maintainers' statements, not measurement (CPython docs, PEP 594, the Temporal README, Moment, the Go blog).

The recompute and counting scripts are in `../scripts/` (`decan_recompute.py`, `go_count.py`, `psf_count.py`, `node_count.py`, `java_matrix.py`); each takes the downloaded data set as its argument.
