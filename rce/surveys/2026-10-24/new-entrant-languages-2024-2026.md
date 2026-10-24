# New-entrant programming languages, January 2024 to October 2026: what 111 of them converge on, read against the Form

## Summary

Two sweeps on 24 October 2026 catalogued 111 programming languages first made public between January 2024 and October 2026: 72 designed for language models or agents as authors, or implemented largely by an agent (48 from the agentlanguages.dev catalogue, read from its source repository at 48 entries, and 24 found beyond it), and 39 general-purpose or systems languages; a further 35 pre-2024 languages reached a milestone in the window (`notes/languages_for_machine_authors.md`, `notes/new_general_purpose_languages.md`). The count by year is steep: 3 in 2024, 10 in 2025 and 57 in 2026 among the machine-author entrants; 9, 7 and 11 among the general entrants, with 12 more created in the window whose year is unverified. Two positions are near-universal: refusal of invalid input at a boundary (54 of 72 machine-author entrants) and emission to another language (57 of 72; 17 of 39 general entrants, with Go the target of 2026 and C the systems default). Minorities take a canonical form (25 of 72), examples or tests inside the program (21 of 72; 2 of 39), a written specification as the authoritative definition (16 of 72; 14 of 39), deterministic evaluation as a stated gate (13 of 72; 3 of 39) and memory safety without a collector (8 of 72; 7 of 39, converging on Perceus-style reference counting or ownership rather than lifetime annotations). Rare: an append-only log with replay (5 of 72; 0 of 39) and hash-identified definitions (2 of 72; 3 of 39). An intermediate form as the source of truth is absent from the new general-purpose languages (Unison and Jule, both older, take it). A distinct trend of 2025 to 2026 is languages built largely by model agents and disclosed as such (Goose, Rue, Cursed, Jolt, and the catalogue's AILANG, Codex, Koru, Maxon and others), whose benchmark claims are self-reported.

Read against the Form, the entrants converge on the two mechanisms the Form shares with everyone (refuse at the boundary, print to other languages) and leave rare the ones the Form is built on: one canonical form as the source of truth, examples as part of the program, deterministic replay from a log, and name-free hash identity, each a theorem or a rule of the specification (6.1, 6.9, 6.10, T1, T3, T7). The emit target registry takes every entrant as a target and a source on the same terms as every other language (`spec/proposals/emit-targets.md`, Tier 5), so a program printed into any of them carries the log, the hashes and the determinism of the Form it came from.

## 1. Method and the standing of the evidence

The machine-author sweep read all 48 entry files of the agentlanguages.dev source repository (github.com/aallan/agentlanguages, maintained by Alasdair Allan) and its stars file, then fetched each project's GitHub page and pulled creation, last-push, star and licence data through the GitHub API for 60 repositories, and searched Hacker News, lobste.rs, arXiv, GitHub topics and announcement posts for entries beyond the catalogue. The general sweep used GitHub repository, release and commit pages, repository search filtered on creation date, and search extracts of LWN, InfoQ, the Racket blog, Habr, Hackaday and project blogs; Wikipedia, Hacker News, codeberg.org and most project websites were unreachable from the research environment, so those facts come from GitHub READMEs and indexed extracts and are marked where thin. Each note lists the entries it could not verify (ten catalogue entries in note 5; five leads in note 6) and the conflicting records (Zeta's versions, Fun's implementation language, Lisette's first date, Sever's and Marsha's dates). Mechanism values are yes, no, unclear or partial, read from the project's own text; "(sr)" marks a self-reported claim. Stars are as shown on 24 October 2026. Nothing here is the survey's own measurement.

## 2. The catalogue in numbers

| Mechanism | Machine-author entrants (72) | General entrants (39) |
|---|---|---|
| Refusal of invalid input at the boundary | 54 (plus 3 partial) | not coded |
| Emits or compiles to another language | 57 | 17 (plus 3 partial) |
| One canonical form or IR as source of truth | 25 (plus 7 partial) | 0 (plus 2 partial) |
| Examples or tests inside the program | 21 | 2 (plus 1 partial) |
| Written specification or formal semantics | 16 (plus 6 partial) | 14 |
| Deterministic evaluation across machines | 13 (plus 10 partial) | 3 (plus 1 partial) |
| Memory safety without a garbage collector | 8 (plus 11 partial) | 7 (13 explicitly have a GC or manual memory) |
| Lifts or imports code from other languages | 12 (plus 1 partial) | not coded |
| Append-only log or replay | 5 (plus 1 partial) | 0 |
| Hash-identified or content-addressed definitions | 2 (plus 2 partial) | 3 |
| Effect tracking or capability-based I/O | not coded | 4 (plus 1 partial) |
| No shared mutable memory between threads | not coded | 2 (plus 3 partial) |
| Proofs in a proof assistant | within "specification" | 2 (plus 1 partial) |

Regional reach of the general sweep: China (Cangjie, Nature, Wa, MoonBit, Dawn), Korea (Han), Ukraine (Rux), Switzerland (Micron, Luon), Poland (Fram), Slovakia (Par), New Zealand (Fearless, no release found); Japan surfaced only the machine-author language Sui; no new general-purpose language was found from India or Russia beyond two unverified leads. The conference sweep (PLDI, OOPSLA, POPL, ICFP, ECOOP, 2024 to 2026) added Cangjie, Fram, Fearless, Effekt and Verus and no other new general-purpose language with a public implementation.

## 3. What the convergence shows

- **The boundary and the print are shared.** Refusing invalid input and printing to a host language are the two things nearly every entrant does, whatever its author. They are also the two things that do not distinguish a design, since a refusal says nothing about what is accepted and a print says nothing about whether the printed program means what the source meant.
- **The specification is becoming the artifact.** Fourteen of 39 general entrants ship a specification in the repository as the authoritative definition, and the agent-assisted projects (Rue, Dawn, Gossamer, Hexa, Cursed) describe their test suites as checked against it. This is the position the Form takes to its end: the specification at one commit is the language (2.7, C.15), the checker is its reader, and conformance is measured against it.
- **Determinism is stated, rarely gated.** Three general entrants make bit-identical evaluation a release gate (Gossamer: VM, JIT and AOT must agree; Dawn: JVM and C backends must agree; Wyzer), and 13 of 72 machine-author entrants claim deterministic execution, mostly self-reported. None pairs it with a hash-chained log that replay verifies (T3) or with a name-free identity (T7); Boruna's evidence bundles and Codex's replay are the nearest.
- **Memory safety is converging on counting, not annotation.** The 2025 to 2026 cohort (Wyzer, Gossamer, Dawn, after Koka and Lean) takes Perceus-style precise reference counting, and Rue, Valen and Zeta take ownership or affine schemes; Goose's data stacks are the outlier. The Form's regions and events are the same bet made one level up: no sharing to count.
- **Examples in the program remain rare**, and where they exist (Dawn's test blocks, Soppo's doctests, C3's `@test`, Nature's first-class tests, Canlang's inline examples) they are tests the author runs, not admission conditions a checker enforces (6.9, W-INT-1).
- **Content addressing has not spread.** Bend's hub, Scrapscript, Dawn's packages and Unison identify artifacts by hash; no entrant identifies the program itself, or its log, by a name-free hash.
- **Languages by agents are a category now**, and the record on them is self-reported. The survey of versioning (same folder) is the context: a language whose compiler an agent wrote, checked by benchmarks and tests against a prose specification, is the pattern the Form exists to replace with a checker that admits or refuses on one meaning.

## 4. What this changes in the RCE materials

The emit target registry gains Tier 5 with all 111 entrants as targets and sources on the same terms as every other row; the paper's convergence observation (section 3.7) reads the two catalogues with the tallies above; and the README, the book, the playground and specification 10.5 state that every language is an output of the Form by its print table and an input by its lift, with Rust, Python, JavaScript and Scala the targets the reference checker emits today.
