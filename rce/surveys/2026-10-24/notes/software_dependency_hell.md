# Working note 1: dependency resolution, semantic versioning, one-version, content addressing

Written 24 October 2026 from search-engine extracts of the named pages, repository READMEs and one transcript read in full (Hickey 2016); research.swtch.com, arxiv.org, usenix.org, hyrumslaw.com, abseil.io and security.googleblog.com were not directly fetchable from the research environment, so their content was checked through indexed snippets and mirrors. Where a number comes from the authors' slides or a secondary summary rather than the paper text, that is stated.

## 1. Dependency resolution is NP-complete; solvers and the minimum-version escape

- The ASE 2006 EDOS paper formalises installability for Debian and RPM repositories (Depends, Conflicts, Provides), encodes it as boolean satisfiability and builds distribution-side tools (edos-debcheck) on that encoding. Mancinelli, Boender, Di Cosmo, Vouillon, Durak, Leroy, Treinen, "Managing the Complexity of Large Free and Open Source Package-Based Software Distributions", ASE 2006, pp. 199-208, doi:10.1109/ASE.2006.49. https://www.irif.fr/~treinen/publi/ase06.pdf
- The EDOS-to-Mancoosi survey states the theorem that installability is NP-complete (reductions both ways to SAT) and describes the solver tooling (distcheck, CUDF). Abate, Di Cosmo, Boender, Zacchiroli et al., "Solving package dependencies: from EDOS to Mancoosi", arXiv:0811.3620, 2008. https://arxiv.org/abs/0811.3620. "Strong Dependencies between Software Components" (Abate, Di Cosmo, Boender, Zacchiroli, ESEM 2009, arXiv:0905.4226) restates that installability and co-installability are NP-complete.
- SANER 2020: dependency solving is NP-complete "in all non-trivial component models"; without a complete solver a package manager can fail to find an existing valid combination; SAT-based solving is "starting to take off" while shared solver components (CUDF) have, with few exceptions, not been adopted. Abate, Di Cosmo, Gousios, Zacchiroli, "Dependency Solving Is Still Hard, but We Are Getting Better at It", SANER 2020, pp. 547-551, doi:10.1109/SANER48275.2020.9054837. https://arxiv.org/abs/2011.07851
- Debian QA (dose-distcheck) and opam (aspcud, mccs, packup through CUDF) use these solvers directly. https://manpages.debian.org/testing/dose-distcheck/dose-debcheck.1.en.html ; https://ocaml.org/p/opam-solver/2.4.0/doc/opam-solver/OpamCudfSolver/index.html
- Cox, "Version SAT" (13 December 2016): independent proof that version selection with one version per package and dependencies on specific versions is NP-complete by reduction from 3-SAT; the problem becomes easy if either assumption is dropped (several versions coexist, or only minimum-version constraints). https://research.swtch.com/version-sat
- Cox, "Minimal Version Selection" (21 February 2018): under the import compatibility rule ("if an old package and a new package have the same import path, the new package must be backwards compatible with the old package") each module lists only minimum versions, the build takes the highest minimum listed anywhere, the algorithm is polynomial, builds are reproducible without a lockfile, and a major version is a distinct import path. https://research.swtch.com/vgo-mvs ; https://go.dev/blog/versioning-proposal
- npm's alternative: several versions of one package coexist in a tree (nested node_modules), and `npm dedupe` collapses duplicates when one version satisfies all ranges. https://docs.npmjs.com/cli/v10/commands/npm-dedupe
- Cox, "Surviving Software Dependencies", Communications of the ACM 62(9):36-43, 2019: cheap fine-grained reuse arrived faster than the practice of choosing and inspecting dependencies; "we are trusting more code with less justification". https://research.swtch.com/deps

## 2. Semantic versioning in practice

- SemVer 2.0.0 defines "dependency hell" as the state where "version lock and/or version promiscuity prevent you from easily and safely moving your project forward". https://semver.org/
- Maven Central, seven years: about one third of releases introduce at least one breaking change, in minor and patch releases about as often as in major ones. Raemaekers, van Deursen, Visser, "Semantic Versioning versus Breaking Changes: A Study of the Maven Repository", SCAM 2014; journal version Journal of Systems and Software 129:140-158, 2017, doi:10.1016/j.jss.2016.04.008.
- Replication on 119,879 upgrades and 293,817 clients (Maracas): 83.4% of upgrades comply with semver; 20.1% of non-major releases are breaking; 7.9% of clients are impacted; breaking non-major releases fell from about two thirds (2005) to 16% (2018). Ochoa, Degueule, Falleri, Vinju, "Breaking bad? Semantic versioning and impact of breaking changes in Maven Central", Empirical Software Engineering 27:61, 2022, doi:10.1007/s10664-021-10052-y. https://arxiv.org/abs/2110.07889
- Cargo, npm, Packagist, RubyGems: constraints are mostly semver-compliant, all more permissive for 0.y.z, and over 16% of restrictive constraints in npm, Packagist and RubyGems block backward-compatible upgrades (about one third of outdated dependencies, per the authors' slides). Decan, Mens, "What do package dependencies tell us about semantic versioning?", IEEE TSE 47(6):1226-1240, 2021, doi:10.1109/TSE.2019.2918315.
- Breaking-change norms are community-specific (Eclipse never breaks, CRAN synchronises upstream and downstream fixes, npm breaks with a major bump), and most developers do not know the other communities' trade-offs. Bogart, Kästner, Herbsleb, Thung, "How to Break an API", FSE 2016, doi:10.1145/2950290.2950325; "When and How to Make Breaking Changes: Policies and Practices in 18 Open Source Software Ecosystems", ACM TOSEM 30(4), 2021, doi:10.1145/3447245.
- Rust: cargo-semver-checks over the top 1,000 crates found a violation in about 1 in 30 releases (3.2% of more than 14,000; 3,062 verified) and in 17.2% of crates; the tool states it does not catch every kind. Gruevski, "Semver violations are common, better tooling is the answer", 2023, https://predr.ag/blog/semver-violations-are-common-better-tooling-is-the-answer/ ; arXiv:2308.14623; https://github.com/obi1kenobi/cargo-semver-checks
- Hyrum's Law: "With a sufficient number of users of an API, it does not matter what you promise in the contract: all observable behaviors of your system will be depended on by somebody." https://www.hyrumslaw.com/

## 3. One version, live at head, monorepos

- Potvin, Levenberg, "Why Google Stores Billions of Lines of Code in a Single Repository", CACM 59(7):78-87, 2016, doi:10.1145/2854146: about 86 TB and 2 billion lines in 9 million files; benefits listed include unified versioning, one source of truth, atomic cross-project changes and avoidance of the diamond dependency problem. https://research.google/pubs/pub45424/
- Google's One Version Rule: only one version of a third-party package may exist because "if there are two versions present, eventually someone will try to build a project that depends on both versions". https://opensource.google/documentation/reference/thirdparty/oneversion
- Winters, Manshreck, Wright (eds.), Software Engineering at Google, O'Reilly 2020, chapter 21: the diamond problem, four upgrade strategies (never upgrade, semantic versioning, bundled distributions, Live at Head); semver both overpromises and overconstrains so that in the limit it requires SAT solving (the wording is the book's; it was not re-read from the page in this run). https://abseil.io/resources/swe-book/html/toc.html
- Meta: one repository with Mercurial extensions (2014) and Sapling (2022), splitting rejected because it would forfeit "simpler dependency management" and fast broad changes. https://engineering.fb.com/2014/01/07/core-infra/scaling-mercurial-at-facebook/ ; https://engineering.fb.com/2022/11/15/open-source/sapling-source-control-scalable/

## 4. Accretion and never breaking; enforced semver

- Hickey, "Spec-ulation", Clojure/conj 2016 (transcript read in full): a major bump collapses every kind of change into "you might be screwed"; every change is growth (provide more or require less) or breakage (require more or provide less); never break: add new names and let old and new coexist; version numbers are secondary. https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/Spec_ulation.md
- Elm: the package manager diffs the typed public API against the last published version and forces the bump (PATCH identical, MINOR additions only, MAJOR otherwise). https://discourse.elm-lang.org/t/semver-and-peer-dependecies/2534 ; https://docs.renovatebot.com/modules/versioning/elm/
- Rust: cargo-semver-checks is the tooling equivalent without publish-time enforcement (section 2).

## 5. Content-addressed code and functional package management

- Dolstra, "The Purely Functional Software Deployment Model", PhD thesis, Utrecht, 2006: components are stored under a name containing a cryptographic hash of all build inputs; a built component never changes; deployment failures are traced to lack of isolation, undetected dependencies and version and variant incompatibility. https://edolstra.github.io/pubs/phd-thesis.pdf
- Courtès, "Functional Package Management with Guix", ELS 2013, arXiv:1305.4584; Courtès, Wurmus, "Reproducible and User-Controlled Software Environments in HPC with Guix", Euro-Par 2015 Workshops, doi:10.1007/978-3-319-27308-2_47.
- Unison: every definition is identified by a hash of its syntax tree (names excluded); names are metadata; because references are by hash, dependency conflicts and the diamond problem "are not an issue" and two versions of a type can coexist. https://www.unison-lang.org/docs/the-big-idea/ ; https://github.com/unisonweb/unison
- Benet, "IPFS - Content Addressed, Versioned, P2P File System", arXiv:1407.3561, 2014.
- Scrapscript: "every scrap carries its own immutable dependencies", pinned at the expression level, distributed through content-addressed scrapyards. https://scrapscript.org/
- Darklang: functions and types are individually versioned and immutable; an older version is deprecated by a suffixed newer one, never changed. https://docs.darklang.com/discussion/unique-aspects

## 6. Lockfiles, reproducible builds, intrinsic identifiers

- Reproducible Builds definition: "given the same source code, build environment and build instructions, any party can recreate bit-by-bit identical copies of all specified artifacts". https://reproducible-builds.org/docs/definition/
- Lamb, Zacchiroli, "Reproducible Builds: Increasing the Integrity of Software Supply Chains", IEEE Software 39(2):62-70, 2022, doi:10.1109/MS.2021.3073045. https://arxiv.org/abs/2104.06020
- Di Cosmo, Gruenpeter, Zacchiroli, "Referencing Source Code Artifacts: a Separate Concern in Software Citation", Computing in Science & Engineering 22(2):33-43, 2020, doi:10.1109/MCSE.2019.2963148: intrinsic identifiers (Merkle hashes over files, directories, commits, releases, snapshots) can be recomputed by anyone; extrinsic ones depend on a registry. https://arxiv.org/abs/2001.08647

## 7. Incidents

- left-pad, 22 March 2016: 273 packages unpublished; builds of Babel, React and thousands of projects failed through a transitive 11-line leaf. https://www.theregister.com/2016/03/23/npm_left_pad_chaos/
- event-stream, 2018: a new maintainer added flatmap-stream within a compatible range; 0.1.1 carried a payload against the Copay wallet. https://blog.npmjs.org/post/180565383195/details-about-the-event-stream-incident
- colors and faker, January 2022: sabotaged releases reached more than 19,000 dependents through caret ranges. https://www.bleepingcomputer.com/news/security/dev-corrupts-npm-libs-colors-and-faker-breaking-thousands-of-apps/
- Log4Shell, December 2021: 35,863 Maven Central artifacts (more than 8%) depended on vulnerable log4j; for more than 80% the dependency was more than one level deep, for a majority five levels. Wetter, Ringland, Google Open Source Insights, https://blog.deps.dev/log4j/
- xz, March 2024 (CVE-2024-3094): a backdoor in the release tarballs of 5.6.0 and 5.6.1 reached sshd two hops away (sshd, libsystemd, liblzma). https://snyk.io/blog/the-xz-backdoor-cve-2024-3094/

## 8. Scale of dependency networks and technical lag

- Decan, Mens, Grosjean, "An empirical comparison of dependency network evolution in seven software packaging ecosystems", Empirical Software Engineering 24(1):381-416, 2019, doi:10.1007/s10664-017-9589-y: a small minority of packages account for most updates and reverse dependencies; a large and growing share are fragile through transitive dependencies. https://arxiv.org/abs/1710.04936
- Zimmermann, Staicu, Tenny, Pradel, "Small World with High Risks", USENIX Security 2019: a very small number of maintainer accounts could inject code into the majority of npm packages; many packages depend on code with known vulnerabilities years after disclosure. arXiv:1902.09217
- Zerouali et al., "An Empirical Analysis of Technical Lag in npm Package Dependencies", ICSR 2018, doi:10.1007/978-3-319-90421-4_6; "A formal framework for measuring technical lag", JSEP 31(8), 2019, doi:10.1002/smr.2157.
- Decan, Mens, Constantinou, "On the evolution of technical lag in the npm package dependency network", ICSME 2018: dependencies lag 7 to 9 months behind the latest release; most packages never change their constraints (figures from the authors' slides). https://arxiv.org/abs/1806.01545

## What this note establishes

1. General dependency resolution is NP-complete (Mancinelli et al. 2006; Abate et al. 2008, 2009, 2020; Cox 2016). Practical systems embed a solver or restrict the problem: minimum-only constraints (Go), coexisting versions (npm, Nix, Unison) or one version (Google).
2. Semantic versioning is adopted but only partly honoured and cannot carry the information it promises (Raemaekers et al. 2014, 2017; Ochoa et al. 2022; Gruevski 2023; Bogart et al. 2016, 2021; Hyrum's Law).
3. Exposure is a property of the transitive graph, not of the direct list (Decan, Mens, Grosjean 2019; Zimmermann et al. 2019; Wetter and Ringland 2021; the five incidents).
4. Open ranges transmit breakage and sabotage; restrictive constraints drive technical lag and block compatible upgrades in more than 16% of cases (Zerouali et al. 2018, 2019; Decan, Mens, Constantinou 2018; Decan and Mens 2021).
5. Immutable content-derived identity removes the conflict instead of solving it (Dolstra 2006; Courtès 2013, 2015; Unison; Scrapscript; Darklang; reproducible builds; SWHIDs), and never-break by accretion (Hickey 2016; Elm; Live at Head) is its social counterpart.
