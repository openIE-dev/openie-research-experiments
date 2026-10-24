# Working note 4: what the RCE repository already does about change, identity and compatibility

Read directly from `/home/user/rce` on 24 October 2026 (main after PR #16). Section numbers are the specification's own.

## Release label and releases (2.7, C.15)

- 2.7: "The label is tolerated and ignored: it selects nothing, gates nothing, is not hashed, does not appear in the Form, and no value of it is refused." "There is one language, the one this document defines, and every module of a program is in it." "A release label names exactly one spec commit (C.15)."
- C.15: a release is the text at one commit; the meaning of a module is "its outputs, states and outcomes, including where a budget traps"; a change that gives a valid program a different meaning is a new release; a change that makes implementations meet text that already defined the meaning, or touches artifacts outside meaning, is an erratum; "A release is never edited after it is named, and a label is never reused for a different commit." The classification table has one meaning change (size-scaled method costs) and the T7 hash erratum of 2026-10-22.
- Decision 64 ("One language, one text") retired per-module version gating; `conformance/clauses.json` keeps the retired clause `W-VER-1` with the note "retired by the one-language change (rce main 4a3dc1f)". 563 `.rce` files still carry a label (416 say 0.6, 41 say 0.8, 106 say 0.9); all are ignored.
- `rce --version` prints the crate version and "one language, release label 0.9" (`spec/checker/src/bin/rce.rs`, `tests/version.rs`).

## Definition hashes, `rce api-diff`, hash-pinned manifest (F.4.3, F.5.3, F.12)

- F.4.3: a definition hash is the SHA-256 of the canonical encoding of the name-free form together with the signature, contracts, measure, ghost clause, labels and the definition hashes of the items it names; a mutually recursive group is one unit; formatting, comments and declaration order are not hashed. The diff table is closed: compatible (export added; body change under unchanged signature, contracts and measure; `requires` weakened or `ensures` strengthened) and breaking (the rest, including an added field or variant because a pattern may become incomplete). T50 states that equal hash means equal meaning (stated, unproved).
- `apidiff.rs`: hash input `sha("rce-def/0.9\n" + module_version + unparse(item))` with names masked by the referenced hashes; `impl` blocks and `step`s are not individually hashed; contracts are not yet in the hash; the `requires`/`ensures` rows are not implemented. `rce hash` prints definition hashes; contract trap texts name the function by definition hash (Q28: no source span, because a span depends on whitespace).
- F.5.3: the manifest is canonical JSON listing every module with its SHA-256 and every dependency by hash; W-PIN-1 refuses a module whose hash differs, an unpinned dependency, a glob or relative import and a cycle. "Imports are an unordered set; adding an export is always compatible. There is no resolver: the manifest is the whole answer." "A published definition is immutable: a hash names one text forever. A correction is a new definition with a new hash." Withdrawal is a signed advisory that "never changes what a hash means, only whether a tool warns on it". T54 is stated and unproved. `rce manifest-check` exists (`manifest.rs`); SLSA provenance, the build cache and advisory key distribution do not.
- Proposal `form-ir-2.md` (open): content-addressed definitions whose key is the SHA-256 of the canonical JSON of the body, with acyclicity following from the digest.

## Modules and `use` (4.1, 10.2)

- `use p.q` makes a module visible by path and name; a program is the set of modules given together; a directory is a package; built-in `std.*`. There is no registry; hash pinning exists only through the manifest. `link.rs` does not link Form items of imported modules.

## Name independence (6.1, 6.6, T7)

- `state_hash` and entry `hash` are over positional forms; renaming every identifier leaves every id, log hash and select decision unchanged (T7, proved in Lean, `Positional.lean`); `rce fmt --nameless` prints the canonical positional text. Names live in a concept record outside the hash. No single whole-program name-free hash is defined yet (6.10 names the proposal's term hash and e-class key as undefined).

## The log, replay, traces, conformance (6.1, T1, T3, 10.9, Appendix E)

- T3: replaying D from s0 reproduces every state hash and every output. HC-8, HS-4, HS-5. The trace format is `rce-trace/2`, and "a trace is the log, and conformance to 6.1 implies conformance to the trace"; 64 fixtures and 102 conformance tests pin `trace_head`. Conformance runs the adapter against `rce` built from the same commit, "so there is no commit to pin". The log's hash choice carries no version tag (Appendix E proposal C-3); D's genesis carries no program identity.

## Behaviour equivalence (6.10, T57 to T61)

- "two programs are the same when their answers are the same, and that is the only sense of 'same' the Form needs"; equivalence is bisimilarity (T58 proved); `shape_ctl` is the hash of the canonical control string, invariant under renaming (T61 tested); `rce dim` is informative.

## Standard library

- No version number; delivered with the checker from the same commit; the one-language migration renamed `Json` to `JsonDoc` and `Url` to `UrlParts` once, without aliases or a deprecation period (`stdlib/README.md`, F.10, decision 64). The method table is generated from the book (`spec-tables.json`) and checked. Unicode is pinned at 18.0.0 (6.3 N7; `unicode_pin.rs`).

## Emitters

- Each emitted file embeds its runtime verbatim (`emit/base.rs`, `prog.rs`); emitted code carries no commit or hash stamp; an emitter that cannot implement a rule refuses (F.10).

## The one semantic-versioning mechanism: the engine profile (Appendix D)

- `spec NAME VERSION` (MAJOR.MINOR.PATCH), "not yet checked"; W-HS-VER-2 requires that removing or modifying a declaration raise MAJOR and additions raise MINOR; a RESOLVE entry of D records the version of δ at its node and the digests of the installed handler spec and the fit evidence, and the fold refuses a mismatched stamp. This profile depends on the engine's `rce`, which is not public.

## Stated non-goals and gaps

- No resolver, no registry, no version selection, no build profiles or conditional compilation, no deprecation mechanism (CONTRIBUTING rule 3: a construct unused for two releases is moved to a proposal and unreserved). Gaps: T50, T54, T60 unproved; contracts and steps outside the definition hash; no whole-program hash; no version tag on the hash choice; no program identity in D.

## Inconsistencies found

- 12-tooling 10.8 says the manifest and pin check do not exist yet; F.12 and the CLI implement `rce manifest-check`.
- 09-wellformedness headers still read "Version 0.8 only (5.16)" and "Version 0.9 only (Appendix F ...)"; 9.5 to 9.6 keep "Versions 0.5 and 0.6 keep their meaning".
- `apidiff.rs` and F.12 say contracts do not exist; F.12 later lists contracts as implemented in `tier3.rs`.
- The manifest `language` key is the release label, which 2.7 says gates nothing.
