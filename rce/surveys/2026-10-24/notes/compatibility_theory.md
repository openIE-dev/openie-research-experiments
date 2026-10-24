# Working note 2: evolving interfaces, schemas and programs without breaking consumers

Written 24 October 2026. Only github.com was directly fetchable from the research environment; claims marked "read directly" come from GitHub-hosted sources (Pro Git, protobuf docs source, Thrift IDL, Rust RFC 1105, Elm package docs, Dhall wiki, IPFS docs, Unison README, the Hickey transcript, cargo-semver-checks). Everything else was confirmed from indexed page text and bibliographic metadata.

## 1. Wire and schema evolution rules

- Protocol Buffers: compatibility rests on numeric field tags; adding fields is wire-safe, a removed number must be declared `reserved` because "reusing a field number makes decoding wire-format messages ambiguous"; readers skip unknown fields. "Language Guide (proto 3)", protobuf.dev (read directly from the source Markdown). https://protobuf.dev/programming-guides/proto3/
- Apache Avro: the writer's schema and the reader's schema are resolved at read time by field name, with defaults and numeric promotions; evolution is a property of a pair of schemas, not of a version number. "Apache Avro Specification", section "Schema Resolution", 1.11.1. https://avro.apache.org/docs/1.11.1/specification/
- Thrift: numeric field ids make renames free; `required` fields "cannot be deprecated". Apache Thrift IDL specification (read directly). https://thrift.apache.org/docs/idl ; Slee, Agarwal, Kwiatkowski, "Thrift: Scalable Cross-Language Services Implementation", Facebook, 2007.
- Kleppmann, Designing Data-Intensive Applications, O'Reilly 2017, chapter 4: backward compatibility (new code reads old data) and forward compatibility (old code reads new data) are both needed because rolling upgrades make old and new code coexist (book text not read directly).
- Curino, Moon, Zaniolo, "Graceful database schema evolution: the PRISM workbench", PVLDB 1(1):761-772, 2008, doi:10.14778/1453856.1453943: schema modification operators with invertible mappings rewrite legacy queries; validated on more than 170 Wikipedia schema versions.
- Qiu, Li, Su, "An empirical analysis of the co-evolution of schema and code in database applications", ESEC/FSE 2013: ten applications, more than 160K revisions; schema changes induce substantial code changes concentrated in a minority of tables. https://www.cs.ucdavis.edu/~su/publications/fse13-db-study.pdf

## 2. API versioning without breaking

- Stripe pins each account to a dated API version and implements each incompatible change as a transformation module applied backwards from the current shape, so one codebase serves every version since 2011. Leach, "APIs as infrastructure: future-proofing Stripe with versioning", Stripe blog, August 2017. https://stripe.com/blog/api-versioning (dated scheme confirmed live in stripe-ruby's `ApiVersion::CURRENT`).
- GraphQL "favors evolution over versioning": clients name the fields they read, additions are invisible, retirement goes through `@deprecated`. https://www.graphql.org/learn/governance-versioning/
- Hickey, "Spec-ulation", Clojure/conj 2016 (transcript read directly): growth versus breakage; breakage is converted to accretion under new names. https://github.com/matthiasn/talk-transcripts/blob/master/Hickey_Rich/Spec_ulation.md
- Elm: `elm bump` computes the version from the type-level API diff; the version is derived from the interface, not asserted. elm/compiler docs, "elm.json for packages" (read directly). https://github.com/elm/compiler/blob/master/docs/elm.json/package.md
- Rust RFC 1105 "API Evolution" (2015, read directly): "all major changes are breaking, but not all breaking changes are major". https://rust-lang.github.io/rfcs/1105-api-evolution.html
- cargo-semver-checks diffs rustdoc JSON against a baseline, runs lints as queries tagged with the required bump, and can generate a witness program that compiles against the baseline and fails against the new version (read directly). https://github.com/obi1kenobi/cargo-semver-checks
- Java Language Specification chapter 13, "Binary Compatibility": the changes permitted "while preserving (not breaking) compatibility with pre-existing binaries"; binary and source compatibility differ. https://docs.oracle.com/javase/specs/jls/se18/html/jls-13.html
- Erlang/OTP keeps at most two loaded instances of a module, current and old; fully qualified calls resolve to current; loading a third purges the old. "Compilation and Code Loading", Erlang system documentation. https://www.erlang.org/doc/system/code_loading.html

## 3. Content-addressed and hash-identified code

- Unison: definitions identified by a hash of the syntax tree with positional variables and dependencies replaced by their hashes; names are metadata; no builds, free renames, cached tests, no dependency conflicts. https://www.unison-lang.org/docs/the-big-idea/ ; README read directly.
- Dolstra, de Jonge, Visser, "Nix: A Safe and Policy-Free System for Software Deployment", LISA 2004, pp. 79-92; Dolstra, PhD thesis, Utrecht 2006: store paths are hashes of all build inputs; dependencies are complete by construction; upgrades and rollbacks are atomic.
- Courtès, Wurmus, Euro-Par 2015 Workshops, doi:10.1007/978-3-319-27308-2_47 (Guix in HPC).
- Di Cosmo, Gruenpeter, Zacchiroli, Computing in Science & Engineering 22(2):33-43, 2020: SWHIDs are intrinsic identifiers (type plus hash of the object) that support integrity checking without a resolver. https://www.swhid.org/specification/v1.1/0.Introduction/
- Git is "a content-addressable filesystem": blobs, trees and commits under the SHA-1 of header plus content, a Merkle DAG in which an identifier pins exact content and all its dependencies. Chacon, Straub, Pro Git, 2nd ed., 10.2 (read directly).
- Dhall: the `sha256:` on an import hashes the expression's normal form after resolving transitive imports, so refactors and comments leave it unchanged and any behavioural change is rejected; an earlier textual hash was abandoned for this reason. dhall-lang wiki "Safety guarantees" (read directly); Gonzalez, "Semantic integrity checks are next", November 2017.
- IPFS CIDs: self-describing multihash plus codec. https://docs.ipfs.tech/concepts/content-addressing/ (read directly); https://specs.ipfs.tech/cid/

## 4. Formal accounts of change

- Roundy, "Theory of patches" (Darcs manual appendix, 2009): a repository is a set of patches with inverses and a commute operation. https://www.cs.tufts.edu/~nr/cs257/archive/david-roundy/theory-patches-2009.pdf
- Mimram, Di Giusto, "A Categorical Theory of Patches", ENTCS 298:283-307, 2013, arXiv:1311.3903: merging coinitial patches is a pushout; the free finite-colimit completion makes conflicts first-class objects.
- Pijul adds all pushouts so that patches producible in parallel always commute. https://pijul.com/model
- Shapiro, Preguiça, Baquero, Zawirski, "Conflict-free Replicated Data Types", SSS 2011, LNCS 6976, pp. 386-400: sufficient conditions for convergence without coordination.
- Kleppmann, Beresford, "A Conflict-Free Replicated JSON Datatype", IEEE TPDS 28(10):2733-2746, 2017, doi:10.1109/TPDS.2017.2697382.
- Ellis, Gibbs, "Concurrency Control in Groupware Systems", SIGMOD 1989, doi:10.1145/67544.66963 (operational transformation).
- Apel, Liebig, Brandl, Lengauer, Kästner, "Semistructured merge", ESEC/FSE 2011, doi:10.1145/2025113.2025141: 24 projects, 180 scenarios, conflicts reduced in 60% of scenarios by 34% on average. Apel, Leßenich, Lengauer, "Structured merge with auto-tuning", ASE 2012.
- Godlin, Strichman, "Regression verification", DAC 2009, doi:10.1145/1629911.1630034: proving equivalence of successive versions is often easier than full verification.
- Lahiri, Hawblitzel, Kawaguchi, Rebêlo, "SymDiff: A Language-Agnostic Semantic Diff Tool for Imperative Programs", CAV 2012, doi:10.1007/978-3-642-31424-7_54.
- Liskov, Wing, "A Behavioral Notion of Subtyping", ACM TOPLAS 16(6):1811-1841, 1994, doi:10.1145/197320.197383: the formal criterion for a replacement being compatible with every client.

## 5. Reproducibility and provenance

- Lamb, Zacchiroli, IEEE Software 39(2):62-70, 2022, doi:10.1109/MS.2021.3073045 (reproducible builds). https://reproducible-builds.org/docs/definition/
- SLSA v1.0, Build track levels L0 to L3; provenance as in-toto attestations. https://slsa.dev/spec/v1.0/levels
- Torres-Arias, Afzali, Kuppusamy, Curtmola, Cappos, "in-toto: Providing farm-to-table guarantees for bits and bytes", USENIX Security 2019, pp. 1393-1410: would have prevented at least 83% of 30 studied supply-chain compromises.
- Newman, Meyers, Torres-Arias, "Sigstore: Software Signing for Everybody", ACM CCS 2022, doi:10.1145/3548606.3560596.
- Lockfiles pin a version and record a content hash; the hash is what is checked. Nesbitt, "Lockfile format design and tradeoffs", 17 January 2026. https://nesbitt.io/2026/01/17/lockfile-format-design-and-tradeoffs

## 6. Hyrum's Law and the one-version rule

- https://www.hyrumslaw.com/ (wording verified through the Software Engineering at Google chapters).
- Winters, Manshreck, Wright (eds.), Software Engineering at Google, O'Reilly 2020, chapter 21: whether a change is breaking can only be judged by how the code is used; semantic versioning is "a lossy summary of the perceived risk in adopting any particular change". https://abseil.io/resources/swe-book/html/ch21.html

## What this note establishes

1. Compatibility is a relation between a producer artifact and a consumer artifact, not a property of a label (Avro; Protobuf; Thrift; JLS 13; Liskov and Wing 1994; Kleppmann 2017).
2. Safe change is additive and identity is never recycled (Protobuf `reserved`; Hickey 2016; GraphQL; Stripe 2017).
3. Meaningful versions are derived from the artifact, not asserted (Elm; cargo-semver-checks; RFC 1105), and content-addressed systems make the hash of the content or its normal form the identity, so two different things never share one (Git; Nix; Unison; SWHID; Dhall; IPFS).
4. Any observable behaviour is part of the interface, so a version bump cannot certify preservation; the formal answer is to check preserved behaviour directly (Hyrum's Law; Winters et al. 2020; Godlin and Strichman 2009; Lahiri et al. 2012).
5. Coexistence beats replacement (Erlang; Stripe; the one-version monorepo with atomic migration; CRDTs; commuting patches), and reproducible builds with signed provenance make it verifiable which artifact a consumer runs (Lamb and Zacchiroli 2022; SLSA; in-toto; Sigstore).
