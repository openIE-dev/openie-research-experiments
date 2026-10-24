# Working note 8: "batteries included" versus "specification and free"

Written 24 October 2026. Hosts other than github.com were unreachable for fetching; where only search extracts of a primary source were seen, the bullet says so. "Self-reported" marks a project describing its own policy. Claims are re-checked by the verification pass recorded in `batteries_verification.md`.

## 1. The origin of "batteries included" and Python's arc

- The phrase is credited to Frank Stajano, "Implementing the SMS server, or why I switched from Tcl to Python," Proc. 7th International Python Conference, 1998 (Cambridge TR-1998-9); the companion slides read "Python is great because it comes with batteries included!" The paper's exact sentence was not fetched.
- PEP 206 (A. M. Kuchling, 2000, withdrawn): "The Python source distribution has long maintained the philosophy of 'batteries included' -- having a rich and versatile standard library which is immediately available, without making the user download separate packages." Read from the PEP source.
- PEP 453 (Stufft, Coghlan, 2013) bundled pip through `ensurepip` from Python 3.4: the standard library delegated acquisition to an external tool instead of growing.
- "The standard library is where modules go to die" is attributed to Kenneth Reitz, PyCon 2012 (reported by Dr. Drang, 2012; slides not fetched): once a module ships it cannot change much.
- PEP 594 (Heimes, Cannon, 2019, final in 3.11 to 3.13) calls batteries included "one of the cornerstones to Python's success story" and removes 22 modules, citing maintenance cost and the ease of installing from PyPI; several reappeared as PyPI packages (standard-aifc and others). LWN, "Python and 'dead' batteries," 2019.

## 2. One platform library: Go, Java, .NET

- Go 1 compatibility: "programs written to the Go 1 specification will continue to compile and run correctly, unchanged, over the lifetime of that specification"; the standard library is part of the promise and may grow but not break; golang.org/x has looser rules. Read from source.
- Cox, "Our Software Dependency Problem," 2019 (search extracts): discussion of reuse long outran actual reuse, and fine-grained reuse arrived before practices for choosing dependencies.
- Go 1.21 (2023) added `slices` and `maps` to the library, formalised GODEBUG for behaviour changes, and stated there will be no Go 2 that breaks Go 1; the `go` line became a minimum toolchain (Cox, "Backward Compatibility, Go 1.21, and Go 2," and "Forward Compatibility and Toolchain Management," Go Blog, 2023).
- The 2025 Go Developer Survey (5,379 respondents) found developers want help "making the most of the standard library"; the 2022 survey ranked avoiding vulnerable dependencies the top security challenge (search extracts).
- "The standard library is where code goes to live" could not be found in any Go source; unverified.
- Java's JEP 320 (JDK 11, 2018) removed nine Java EE and CORBA modules because stand-alone versions were available from Maven Central and syncing them was a burden.
- .NET Standard is "a formal specification of .NET APIs that are available on multiple .NET implementations," a set of `.cs` files, additive and frozen per version, ended at 2.1 by unified .NET.

## 3. The minimal-core tradition

- **C.** Ritchie, "The Development of the C Language," HOPL-II, SIGPLAN Notices 28(3), 1993. Undefined behaviour as portability failure: the STACK checker found optimisation-unstable code in Linux and PostgreSQL and 160 confirmed bugs (Wang, Zeldovich, Kaashoek, Solar-Lezama, SOSP 2013; TOCS 2015).
- **Scheme.** After R6RS the Steering Committee split Scheme into small and large languages (2009; InfoQ). Shinn's R7RS status report: SRFIs had "no mechanism for specifying how to load a SRFI portably, or to write a portable library," so implementations re-invented the same utility libraries; R7RS-large support varies by implementation (Scheme Workshop 2012). Cowan's Implementation Contrasts catalogues behavioural differences; Clinger, SFP 2015.
- **Common Lisp.** ANSI X3.226-1994: nearly 1,100 printed pages and nearly a thousand functions and variables (the large-specification model).
- **JavaScript.** ECMA-262: "ECMAScript as defined here is not intended to be computationally self-sufficient"; I/O is left to hosts. TC39's built-in modules proposal for a standard library (Saboff, Hoitink, 2019) was blocked from Stage 2. The left-pad incident (2016) followed.
- **Lua.** "Mechanisms instead of policies"; one general mechanism per aspect (Ierusalimschy, de Figueiredo, Celes, CACM 61(11), 2018; HOPL III, 2007); its batteries are third-party compiled libraries, some unmaintained across releases (LWN, 2020).
- **Forth.** The 2012 standard requires a core word set; every other word set is optional and advertised per implementation.
- **Prolog.** ISO 13211-1 (1995) covers the core; systems depart from each other beyond it, which challenges portability (Wielemaker, Santos Costa, CICLOPS-WLPE 2010, arXiv:1009.3796; PADL 2011).
- **SQL.** Guagliardo, Libkin, "A Formal Semantics of SQL Queries, Its Validation, and Applications," PVLDB 11(1), 2017; standard null semantics frequently yields incorrect answers on TPC-H (PODS 2016); "no two database management systems implement the standard in exactly the same way" (Shonan meeting 267).
- **JSON.** Seriot tested more than 30 parsers and found "no two parsers that exhibited the same behaviour," because RFC 7159 under-specifies numbers, malformed Unicode, duplicate keys and depth ("Parsing JSON is a Minefield," 2016).

## 4. Mixed positions

- **Rust.** std is "the foundation of portable Rust software, a set of minimal and battle-tested shared abstractions" (read from source); RFC 1242: std's stability is tied to Rust's own versioning, "meaning that the standard library has much less flexibility than other crates enjoy," and new APIs "can just as well begin their life as external crates," and rust-lang crates are "the rest of the standard library"; blessed.rs as a curated substitute. Specification: RFC approved July 2023; the Ferrocene Language Specification (2022) donated to the Rust Project in March 2025.
- **Haskell.** The Core Libraries Committee manages `base` and collectively owns core libraries distinct from GHC boot libraries (read from source).
- **OCaml.** 4.07 (2018) added `Seq` and `Float` and packed the library into `Stdlib` (read from Changes); Jane Street's Core is "an industrial-strength alternative to the OCaml standard library," Base a minimal replacement.
- **Zig.** std ships with the compiler at one commit; the specification issue (#75, 2016) was closed as not planned in April 2026 with the work moved to a separate repository; no std stability before 1.0.
- **Deno.** std moved to JSR, packages "audited by the Deno team" (self-reported) and versioned per package.
- **Swift.** A small standard library with Foundation beside it; Apple's 2022 rewrite argued "multiple implementations of any API risks divergent behavior" and aimed at one canonical Foundation on every platform.
- **Elm.** 0.19 restricted native code to core packages; the whitelist committee was "a failure overall" (Czaplicki, 2018); semantic versioning enforced from the API diff.
- **Racket.** racket/base, racket ("the 'batteries included' variant") and typed/racket; "eliminates the boundary between library and language" (Felleisen et al., CACM 61(3), 2018; SNAPL 2015).
- **Erlang/OTP.** The minimal system is STDLIB and Kernel; supervisors and gen_server are in STDLIB, with Mnesia, SSL, SSH and crypto as further OTP applications.
- **Julia.** The standard library is packages installed with the runtime, loaded by `using`, able to carry their own versions; Statistics was proposed to leave the set in 1.9 (PR #46501).
- **Mojo.** Standard library open-sourced March 2024 on a nightly branch that breaks with the nightly compiler; compiler opened August 2026 after 1.0 (self-reported).
- **MoonBit.** `core` open-sourced March 2024; compiler late 2024 under a modified SSPL (self-reported).

## 5. Evidence on outcomes

- **Transitive bloat.** Half of dependent packages in Cargo, npm and NuGet have at least 41, 21 and 27 transitive dependencies (Decan, Mens, Grosjean, EMSE 24, 2019); only 31.5% of PyPI packages declare dependencies against 58.7% of npm and 69.8% of CRAN (Decan, Mens, Claes, 2016); Cargo, npm and NuGet more subject to single points of failure by 2024 (Mens, Decan, arXiv:2409.18884).
- **npm risk.** A very small number of maintainer accounts could inject code into the majority of packages; vulnerable code persists for years; the proposed remedy is trusted maintainers and vetting for selected packages, a curated core (Zimmermann et al., USENIX Security 2019).
- **Bloat.** 75.1% of dependency relationships of 9,639 Maven artifacts are bloated (Soto-Valero et al., EMSE 2021); bloat grows over time and 22% of updates target bloated libraries (ESEC/FSE 2021).
- **Standard library against third-party defect rates.** No study comparing them directly was found. Adjacent: 544 security bugs in 252 of 13,565 Java third-party libraries (Wang et al., ICSME 2020); 1,396 vulnerability reports in 698 PyPI packages (Alfadel et al., EMSE 2023); 1,837 Go vulnerabilities (Hu et al., ICSE 2024); the Go vulnerability database labels standard-library entries `stdlib`. A 2026 preprint built 44 standard-library-only Python replacements of popular packages, about two thirds at performance parity (arXiv 2605.21405, not peer reviewed).
- **Fragmentation and migration.** Library migration is infrequent and depends on the software and the library (Teyton, Falleri, Blanc, 2013); 9 same-function migrations across 57,447 Java projects reduced coupling (Alrubaye et al., 2020). No study of competing JSON or HTTP libraries specifically was found.
- **Deprecation.** The JDK carries extensive deprecated API (Sawant, Robbes, Bacchelli, EMSE 23, 2018); the deprecate-replace-remove sequence often breaks down (Zhou, Walker); Python libraries handle deprecation poorly (Wang et al., ESEC/FSE 2020).
- **Distributions as batteries.** Debian's one-version practice collides with Go and npm, forcing adaptation or bundling (LWN, "Debian discusses vendoring—again," 2021); Fedora relaxed Go bundling in 2025.
- **One version.** Google's repository and One-Version Rule (Potvin, Levenberg, CACM 59(7), 2016; Software Engineering at Google, chapters 16 and 21).

## 6. Specification against implementation

- Go "has always been defined by a spec, not an implementation," with two compilers (gc, gccgo) whose disagreements expose spec gaps (Taylor, Go Blog, 2012).
- Python's reference warns that implementations may differ while describing CPython as the one in widespread use.
- Rust's specification came in 2023 to 2025; Zig's issue stayed open from 2016 to 2026; Scheme, C, SQL, Prolog and JavaScript are specified with many implementations and diverge as documented above.
- The argument that a library is portable only when its semantics is fixed by the specification is made explicitly by Shinn and Snell-Pym for Scheme, by Apple's Foundation team, and by Seriot for JSON.

## What this note establishes

1. A bundled library trades flexibility for stability: every one-library language ties the library's API to its compatibility promise (Go 1; Rust RFC 1242, "much less flexibility than other crates enjoy"; "where modules go to die"; Deno's per-package versions).
2. Batteries are removed once an installer exists: Python (PEP 453, then PEP 594, 22 modules), Java (JEP 320, 9 modules) and Julia all cite maintenance cost and the same code in a registry.
3. Free ecosystems produce deep transitive graphs and concentrated risk: a median of 21 to 41 transitive dependencies in npm, Cargo and NuGet, single packages reaching large parts of npm, 75% bloated Maven relationships, left-pad.
4. Specification-with-many-implementations languages pay in portability: Scheme, Prolog, SQL, C and JSON.
5. The convergent compromise is a curated middle tier between the core and the open registry: rust-lang crates and blessed.rs, Haskell's core libraries, Deno's audited std, Elm's kernel-only core, Julia's versioned stdlibs, Debian's one-version archive, Google's One-Version Rule.
