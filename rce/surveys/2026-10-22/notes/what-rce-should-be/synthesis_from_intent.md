# Program synthesis from intent, holes and contracts, and verification-gated repair — design input for RCE

Grounding (read before any search): RCE paper §2.1–2.4, §4.2–4.3, §6 (https://research.openie.dev/papers/rce/); `spec/proposals/closing-the-loop.md`; `spec/book/17-draft09.md` §F.6; README `intent`/`example` syntax. RCE state as of the paper: G0 lookup by SHA-256 shape hash, G1 guarded templates (PAR/TBar/AVATAR/FixMiner/Coccinelle lineage), G2 enumeration over handler grammar sizes ≤2 (egg present but unused by G2), G3–G5 models off by default; gate = replay + shadow run with rule-of-three coverage bound + schema check + proof certificate, rejected candidates logged with counterexample. Repair ladder: L0 one-token 520,541/520,821 = 0.9995 (median 2.3 search bits, 0 model calls); L1 Java full-file ManySStuBs4J 13,586/21,320 = 0.637 (median 4.8 bits); L1 Python hunk-only TSSB-3M 0.174. Intent bits defined I = H_task − H_corpus; a gear ranking the right edit at rank r supplies log2(r) search bits. Proposal: `.intent` = Form with typed refined holes `?name : τ {p}` + `ensures` + `example` + `invariant` + `uses` + `budget`; catalog `{hash, path, name, type, pre/post, effects, totality, est_j, laws[], vectors[]}` (457 bricks, 269 lowered, 252 agree on vectors, 188 refusals); composer lookup → type-directed enumeration → e-graph → finite-domain constants; output = module + per-hole derivation (stage, candidates tried, winner hash) + hash chain. Contracts (F.6.2) always enforced, violation = defined refusal record `{kind, clause, function hash, index}`, one comparison per clause charged as operators; `ghost` erased before run; `decreases` lexicographic.

---

## KQ1. Classical synthesis: refinement types, type-and-example, sketching, SyGuS, type-directed library search — what scales and what does not

### Takeaway
Everything that scales in the no-model regime scales by *pruning before enumeration*: types (Myth, Hoogle+), refinement types with round-trip checking (Synquid), observational-equivalence classes and version spaces (Burst, FlashFill), and solver-backed hole filling (Sketch/CEGIS, cvc5 SyGuS). Ceilings are consistent: ~45–130 benchmark programs of textbook size, seconds to minutes, no inner lambdas, brittle with polymorphism, and "multiple functions"/instruction-selection style problems unsolved. RCE's G2 at size ≤2 is far below the state of the art; moving to type-pruned, equivalence-collapsed bottom-up enumeration over a typed brick catalog (as the proposal already plans) is the documented path.

### Cited Findings
- SyGuS-Comp 2018 (last full competition round reported in a paper): five solvers, >1,600 benchmarks. General track 598 benchmarks, CVC4 solved 448; CLIA 88, CVC4 85; Invariant 127, LoopInvGen 115; PBE-BV 750, CVC4 724; PBE-Strings 118, CVC4 102. No solver solved any Instruction-Selection benchmark; "Multiple Functions" named as still challenging; >74% of General solved — [SyGuS-Comp 2018 results, arXiv 1904.07146](https://www.arxiv.org/pdf/1904.07146)
- Hoogle+ (PLDI 2020) component library = 291 components from 12 Haskell modules; encodes types as Petri-net places, so polymorphism needs a brittle abstraction-refinement loop; components must be fully applied (higher-order use handled by duplicating nullary copies, bloating the library); no inner lambdas — [Searching Entangled Program Spaces (ICFP 2022)](https://arxiv.org/pdf/2206.07828)
- Hectare (ECTA, ICFP 2022) vs Hoogle+ on the 45-query Hoogle+ suite at 300 s timeout: 43 vs 39 solved; geometric-mean speedup 7× (intro says 8×, inconsistent in the paper); combined suites 88% vs 64%; Hoogle+ ≈ 4,000 LOC vs Hectare ≈ 400 LOC; on 19 higher-order StackOverflow queries Hoogle+ solves 0, Hectare 13. Core idea: tree automata with equality constraints between subterm paths (entangled holes, e.g. `X + X`), with static reduction (automata intersection) and dynamic reduction (unification variables) — [Searching Entangled Program Spaces](https://arxiv.org/pdf/2206.07828)
- Burst (POPL 2022): bottom-up synthesis of recursive functional programs from logical specifications via angelic execution + version-space learning; solves 94% of its benchmark suite, "outperforming prior work" (Myth/Smyth not named on the abstract page) — [arXiv 2107.06253](https://arxiv.org/abs/2107.06253)
- RCE paper itself cites FlashFill/Gulwani and Solar-Lezama sketching as the lineage of "synthesis narrows a hypothesis space" and lists G2 lineage as "sketching, SyGuS, egg"; proposal §6 claims convergence with Synquid (refinement-typed holes, round-trip checking), Myth (example-guided, type-pruned enumeration), egg, Sketch/CEGIS, miniKanren (fair interleaving), Hoogle (type-up-to-isomorphism keys) — [RCE paper](https://research.openie.dev/papers/rce/); local `spec/proposals/closing-the-loop.md` §6

### Inferences
- The 291-component Hoogle+ library is the same order as RCE's 457-brick catalog (269 lowered). Hoogle+'s Petri-net encoding failed on polymorphism and higher-order components; RCE's catalog has generics (refused today: `Deque[T]`) and will hit the same wall. ECTA-style equality-constrained enumeration is the direct successor and should be the model for the "type-directed enumeration" stage in proposal §5.3 step 2, not Petri nets.
- SyGuS's unsolved classes (multiple functions, instruction selection) map exactly to RCE's largest refusal class ("calls are inlined because the IR has no named sub-terms", 77 refusals): named sub-terms/definition table in the Form IR is a prerequisite for any multi-function synthesis.
- Burst's "angelic assumptions become strengthened spec" loop is the structural twin of RCE proposal §5.4 ("repair is search with learned exclusions, not mutation"); the derivation log should record each strengthening as a resolved constraint, which is the natural unit for "bits resolved".
- Sketch/CEGIS and SyGuS counts show enumerative + solver solve ≥85% of CLIA/PBE-BV but ~0% of structural multi-function problems: G2 should be expected to close holes of guard/constant/arith kind (RCE's "changed operators 91%, boolean literals 84%" class) and not holes that require new intent (method names 22%, new conjuncts 3–7%).

### Gaps
- Synquid (PLDI 2016), Myth (PLDI 2015), Smyth (ICFP 2020) exact benchmark counts and times were not re-fetched this session (publisher PDFs blocked by robots); the proposal's convergence claims rest on the original papers. Treat the Synquid 64-benchmark / Myth ~40-benchmark figures from memory as unverified.
- No post-2019 SyGuS competition report was found; the state 2020–2025 is best inferred from cvc5's continued development (see KQ5 Tinelli 2024) rather than competition tables.

---

## KQ2. Contracts and proof-carrying code in production languages; what always-on contracts cost

### Takeaway
2024–2026 verified-systems practice (Verus, Dafny, Lean 4, SPARK, Rust tools) treats contracts as *static* obligations discharged by SMT, with runtime checking only at trust boundaries; RCE's F.6.2 "always enforced, one comparison per clause" is a defensible but unusual choice, and the cost should be made explicit via `est_j` rather than argued away. Benchmarks now exist for the hard part — writing the proof, not the code — and the fraction of real-system proof tasks an LLM agent can finish is now >80% (VeruSAGE-Bench) while verified-synthesis from spec is 44% (Verus) / 27% (Lean) at best (Vericoding).

### Cited Findings
- VeruSAGE (Microsoft Research, arXiv Dec 20 2025): VeruSAGE-Bench = 849 proof tasks extracted from eight open-source Verus-verified Rust systems; best LLM-agent combination (o4-mini, GPT-5, Sonnet 4, Sonnet 4.5 tested) completes >80% of tasks and >90% of a set of proof tasks human experts had left unfinished; "different LLMs need different tools and agent settings" — [arXiv 2512.18436](https://arxiv.org/abs/2512.18436v1); NeurIPS 2026 poster listing — [neurips.cc](https://neurips.cc/virtual/2026/poster/139178)
- AutoVerus (Sep 19 2024, OOPSLA/SPLASH 2025): three-stage multi-agent (draft, refine by tips, debug by verifier errors) for Verus; 150 non-trivial proof tasks; correct proofs for >90%; more than half solved in <30 s or ≤3 LLM calls — [arXiv 2409.13082](https://arxiv.org/abs/2409.13082v1); [SPLASH 2025 listing](https://2025.splashcon.org/details/OOPSLA/200/AutoVerus-Automated-Proof-Generation-for-Rust-Code)
- Vericoding benchmark (MIT et al., 26 Sep 2025): 12,504 tasks (Dafny 3,029; Verus/Rust 2,334; Lean 7,141), 10,868 after filtering; models generate implementation + proof from formal spec; success rates Dafny 67–82%, Verus 44%, Lean 27%; up to 5 attempts (10 for hard) with verifier feedback; 55,397 experiments over nine models; validation scripts detect "cheating patterns" such as disabling proof checkers or trivializing specifications — [alphaxiv benchmark page](https://www.alphaxiv.org/benchmarks/mit/vericoding-benchmark); paper [arXiv 2509.22908](https://arxiv.org/pdf/2509.22908)
- DafnyBench (NeurIPS 2024 / TMLR 2025): >750 Dafny programs, ~53k LOC; task = supply enough annotations (hints) for Dafny to verify; best model+prompt 68%; success improves with error-message retries and falls as code + hint volume rises — [arXiv 2406.08467](https://arxiv.org/abs/2406.08467v1)
- Clover (Stanford/Barrett group, Oct 2023, v4 Nov 2024; Dafny 2024 workshop): checks pairwise consistency of code, docstring, and formal annotations using verifier + LLM; CloverBench textbook-level Dafny; accepts up to 87% of correct examples with zero false positives on adversarial incorrect programs — [arXiv 2310.17807](https://arxiv.org/abs/2310.17807v4)
- SpecRL (PKU/ISCAS/Tencent, arXiv 2604.05820, rev. Jul 2026, for IEEE TSE): the verifier checks only soundness — `ensures true` / `requires false` verify; completeness is measured by "spectests" (mutated outputs the deterministic implementation can never produce, which a complete spec must reject); staged reward 0.05 extract / 0.15 compile / 0.30 verify / 0.50 × fraction of spectests rejected; candidates that add `assume` or modify the implementation get zero reward; running spectests as executable predicates via `dafny test` was ~8× faster than as symbolic obligations; 7B model on DafnyComp-Spec: verifiable 10.40% vs 5.44% SFT (pass@1), completeness 24.30% vs 18.15%; beats GPT-5.1 on completeness (24.30 vs 19.60) but not verifiability (11.10 vs 10.40); removing the verification gate raised completeness but dropped verifiability to 1.56%; cost ≈3,160 GPU-hours for four RL runs, ≈$250 API for spectests over 5,002 programs — [arXiv 2604.05820](https://arxiv.org/pdf/2604.05820)
- Baldur (Mar 2023, ESEC/FSE 2023): whole-proof generation + separate repair model on 6,336 Isabelle/HOL theorems; +8.7% over Thor; Baldur+Thor 65.7% fully automatic; feeding the failed attempt + error message enables proof repair — [arXiv 2303.04910](https://arxiv.org/abs/2303.04910)
- RCE F.6.2: contracts are always enforced; violation is a defined refusal with record `{kind:"contract", clause, function: <definition hash>, index}`, no source span (whitespace independence); W-CON-1 refuses functions whose `requires` is statically false in the decidable fragment; checker assumes callee `ensures` after call and proves callee `requires` where the fragment decides, otherwise runtime; cost "one comparison per clause, charged as C.6.4 operators"; T46 stated, unproved. Ghost code (F.6.3) erased before evaluation/emission/run-hash; `mathint` ghost-only; unbounded quantifiers refused because "enforced contracts must be" evaluable — local `spec/book/17-draft09.md` §F.6

### Inferences
- The field's split is static discharge (Verus/Dafny/SPARK) vs dynamic enforcement (Racket contracts, Eiffel DbC, RCE F.6.2). RCE's choice forces contracts into the *evaluable* fragment (no unbounded quantifiers), which is exactly what makes them usable as oracle layer (b) in proposal §5.5 and as spectest-style completeness checks; the trade is that `ensures` on large data (e.g. `sorted(result)`) is O(n) per return, not "one comparison". `est_j` should charge the real predicate cost, not a flat per-clause constant.
- Static discharge in the decidable fragment + runtime enforcement elsewhere is already RCE's rule; the Verus/Dafny numbers say the LLM-assisted proof step is now ≥80% feasible for real-system obligations, so RCE can route "prove callee `requires`" failures to G3–G5 as *proof* proposals (gated by Z3 certificate) without touching the trusted path.
- SpecRL's vacuity finding is the key risk for `.intent`: a hole `?f : τ {ensures true}` plus a weak oracle will be "filled" trivially. The intent object needs a measured completeness (fraction of mutated/spectest outputs rejected), not just soundness.

### Gaps
- No measured runtime overhead figures for always-on contracts in SPARK/Ada (`-gnata`), Racket, or Eiffel were obtained this session; search returned only method papers on reducing checking cost (static contract simplification, property caching). Order-of-magnitude claims (few % for scalar pre/post, up to 2–10× for data-structure invariants) remain unsourced.
- Creusot, Prusti, Kani, Aeneas, F*, SPARK and Lean-4-as-a-language were not individually fetched; VeruSAGE and Vericoding are the only Rust-verification sources with numbers here.

---

## KQ3. Verification-gated LLM code generation and repair 2024–2026; the plausible-vs-correct gap; cost-of-pass; patch naturalness

### Takeaway
Gated loops (tests, verifier, consistency checks) are what moved the numbers: AlphaCodium 19→44% pass@5, Agentless 32% on SWE-bench Lite at $0.70, DGM 20→50% SWE-bench by evolving the agent, and 80.9% on SWE-bench Verified by Mar 2026 — but the same 81%-class models score 46–57% on SWE-bench Pro and an OpenAI audit found verbatim gold-patch recall, so Verified is contaminated. "Plausible" (tests pass) still ≠ correct; entropy-delta from a code LM is a cheap, training-free ranker that raises top-1 correct patches by 49%, confirming RCE's §2.1 bet that correct fixes lower entropy. Cost-of-pass is the right accounting unit and shows majority voting/self-refinement rarely pay.

### Cited Findings
- AlphaCodium (Jan 16 2024): test-based multi-stage iterative flow; GPT-4 pass@5 on CodeContests validation 19% → 44% — [arXiv 2401.08500](https://arxiv.org/abs/2401.08500)
- Agentless (Jul 2024, v2 Oct 2024): localization → repair → patch validation with no agentic tool use; SWE-bench Lite 32.00% (96 fixes) at $0.70/problem; manual audit found Lite problems with exact ground-truth patch in the issue or misleading descriptions, leading to SWE-bench Lite-S — [arXiv 2407.01489](https://arxiv.org/abs/2407.01489)
- SWE-bench Verified top-10 as of Mar 20 2026 (third-party compilation, not verified against leaderboard): Claude Opus 4.5 80.9%, Opus 4.6 80.8%, Gemini 3.1 Pro 80.6%, MiniMax M2.5 80.2%, GPT-5.2 80.0%, Sonnet 4.6 79.6%; average 62.2% across 77 models; top six within 1.3 pts. SWE-bench Pro (1,865 tasks, Python/JS/TS/Java/Go): GPT-5.3-Codex 56.8%, GPT-5.2-Codex 56.4%, GPT-5.2 55.6%, Opus 4.5 (SEAL scaffold) 45.9%; scaffolds differ. OpenAI audit: every frontier model tested (GPT-5.2, Opus 4.5, Gemini 3 Flash) could reproduce verbatim gold patches or problem-statement specifics → Verified scores inflated — [aicodereview.cc SWE-bench guide](https://aicodereview.cc/blog/swe-bench-scores-leaderboard)
- Yang, Kolak, Hellendoorn, Martins, Le Goues (CMU; "Revisiting Unnaturalness for APR in the Era of LLMs", arXiv 2404.15236): line entropy from InCoder/StarCoder-15.5B/CodeLlama-7B with masked-line scoring. Entropy-delta ranking of TBar patches improved 60/72 bug rankings, cut patches tested by mean 24 (median 5) per bug. Plausible-patch ranking on Defects4J v2.0 (197 bugs, 1,290 Shibboleth patches, 2,147 Panther patches): top-1 correct 85 → 127 (+49%), top-2 130 → 165 (+27%); classification precision 0.900 vs 0.760, F1 0.824 vs 0.750. Correct patches have median entropy-delta > 0 (entropy falls) in all six projects; incorrect have median < 0; not a perfect predictor (a test-failing patch outscored a plausible-incorrect one in their example). Entropy re-ranking lowered TransferFL top-1 (69 → 57), i.e. it is not monotone on every component — [arXiv 2404.15236](https://arxiv.org/pdf/2404.15236)
- Petke, Martinez, Kechagia, Aleti, Sarro (FSE Companion 2024, IVR): across 10 APR tools on Defects4J, median plausible patches per bug = 2; propose a Random Selection baseline for overfitting-assessment techniques and argue overfitting effort is lower than assumed — [UCL Discovery](https://discovery.ucl.ac.uk/id/eprint/10192372/)
- Cost-of-Pass (Erol, El, Suzgun, Yuksekgonul, Zou; Apr 17 2025): cost-of-pass = expected monetary cost of a correct solution (inference cost ÷ pass rate); frontier cost-of-pass = min over models and a human-expert baseline. Lightweight models cheapest for basic quantitative tasks, large models for knowledge tasks, reasoning models for complex quantitative tasks; frontier cost-of-pass for complex quantitative tasks roughly halved every few months; majority voting and self-refinement give marginal gains that "rarely justify their added cost" — [arXiv 2504.13359](https://arxiv.org/abs/2504.13359v1); code [github](https://github.com/mhamzaerol/Cost-of-Pass)
- DGM (Sakana/UBC, May 2025, ICLR 2026): 80 iterations; SWE-bench 20.0% → 50.0%, Polyglot 14.2% → 30.7% (full) / 14.0% → 38.0% (50-task subset); one run ≈2 weeks with "significant API costs"; 51.3% of generated SWE-bench agents retained basic editing capability; greedy parent selection drops to 39.7%/30.0%; transfer: Claude 3.7 Sonnet 19.0% → 59.5% SWE-bench with the evolved agent; sandboxed, every change in a traceable lineage archive; Appendix H is a hallucination case study (not in fetched text) — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3); [sakana.ai/dgm](https://sakana.ai/dgm/)
- RCE's own gate at L0/L1 is token identity ("stricter than passing tests"); L2+ use tests and report plausible and correct separately; the paper flags that L0's 0.9995 may reflect overlap between its one-token neighbourhood and the mutation operator tables, with no operator-inversion baseline run — [RCE paper §6](https://research.openie.dev/papers/rce/)

### Inferences
- The 81% → 46–57% Verified→Pro drop (~25–35 points) is the empirical plausible-vs-memorized gap for frontier models; RCE's offline SWE-bench Lite protocol (§8.2) should report Pro-style held-out, multi-language tasks or at least Lite-S, and a "verbatim recall" check per task (does the model reproduce the gold patch from the issue text alone?) belongs in the gate as a contamination falsifier.
- Entropy-delta is a G1/G2 *ranker*, not a gate: it reorders candidates before the gate runs (fewer tests executed), which is a direct reduction in search bits; its failure cases (ranking a test-failing patch above a plausible one) are harmless under a correct gate. Adopt as a ranking key in the derivation log, never as an acceptance criterion.
- Cost-of-pass is the natural unit for G3–G5 escalation policy: each gear has a measured pass rate and a measured joule/dollar cost per attempt; the escalation order should minimize expected cost-of-pass, and "self-refine/majority vote inside one gear" is empirically a poor use of budget relative to escalating to the next gear with a different proposer.
- DGM's archive with non-greedy parent selection is a "catalog of agents" rather than of code; its 51.3% retention and 2-week cost show that promotion without a sound gate is expensive. RCE's gate-then-promote is the sound version; DGM supplies the evidence that lineage/provenance must be recorded (Figure 3: winning lineages pass through low-scoring nodes), i.e. the derivation log should keep *rejected* candidates, which RCE already does ("rejected candidates are logged with their counterexample").

### Gaps
- Lemur (LLM+bounded model checking), RepairLLaMA, SWE-bench Multi/Multilingual, and Qi et al.'s original plausible-vs-correct study were not fetched; the leaderboard figures above come from a single secondary page dated Mar 2026 and should be re-checked against swebench.com before being quoted in the paper.
- No source gives per-task dollar cost-of-pass for verification-gated loops (AutoVerus reports LLM calls, not dollars).

---

## KQ4. Template/rule-based repair without models: ceilings

### Takeaway
Template repair (TBar) peaks at 74/101 Defects4J bugs with perfect localization and 43 with real localization; its ceiling is set by localization and by template coverage, not by search. Entropy-delta from a small code LM reduces TBar's patch-testing cost by a median 5 patches per bug without changing the template set. RCE's G1 at 63.7% full-file on ManySStuBs4J is in the same regime; the next ceiling is the "needs new intent" classes (method names, new conjuncts).

### Cited Findings
- TBar (ISSTA 2019, arXiv Mar 2019): recurrent fix patterns from the literature; with perfect fault localization 74/101 Defects4J bugs "correctly/plausibly" fixed; with a normal localization pipeline 43 correctly fixed — [arXiv 1903.08409](https://arxiv.org/abs/1903.08409)
- Entropy-delta re-ranking of TBar patches improved 60 of 72 rankings and reduced patches tested by mean 24 / median 5 per bug (same Yang et al. paper) — [arXiv 2404.15236](https://arxiv.org/pdf/2404.15236)
- Median plausible patches per bug across 10 APR tools on Defects4J = 2 (Petke et al. 2024) — [UCL Discovery](https://discovery.ucl.ac.uk/id/eprint/10192372/)
- RCE G1 lineage: PAR, TBar, AVATAR, FixMiner, Coccinelle; templates checked for mutation sensitivity; hunk-only L1 closes changed operators 91% and swapped boolean literals 84%, leaves method names 22%, new conjuncts 3–7% — [RCE paper §4.2, §6](https://research.openie.dev/papers/rce/)

### Inferences
- TBar's 74→43 gap (perfect vs real localization) is 30 points; RCE's L1 hunk-only→full-file gap (38.6% → 63.7%) is 25 points. Localization/context is the dominant lever at G1, consistent with G0's "localization to ranked functions" being a bit-supplying step; log2(rank) of the true location should be recorded separately from edit search bits in the derivation.
- Getafix (Facebook, OOPSLA 2019), Sorald (Sonar-rule fixes), Coccinelle semantic patches and Comby (lightweight structural rewriting) are the right G1 *carriers* (guarded rewrite with pattern + fix), but no Defects4J-style ceiling for Getafix/Sorald was fetched; treat as gap.

### Gaps
- Getafix, Sorald, Coccinelle, Comby numbers not fetched this session.
- No published result on newer benchmarks (SWE-bench, GitBug-Java) for pure template repair was found; the model-free ceiling there is unmeasured.

---

## KQ5. Intent capture (spec mining, examples, PBT, intent bits) and recording derivations/provenance (proof logs, SMT certificates)

### Takeaway
The best 2025–2026 evidence says intent must be captured on two axes — soundness (verifier) and completeness (does the spec reject behaviours the program cannot have) — and that completeness is cheaply measurable by executable mutated-output tests (SpecRL spectests, ~8× cheaper than symbolic). For provenance, SMT solvers now emit fine-grained textual proof certificates at small runtime overhead, so the gate's "proof certificate" can be an externally checkable object rather than a verdict bit.

### Cited Findings
- SpecRL spectests: LLM proposes inputs, implementation runs, outputs are mutated into values the deterministic implementation can never produce; spec completeness = fraction rejected; executed via `dafny test` (~8× faster than symbolic); vacuous `ensures true`/`requires false` get zero reward; threats: finite spectests cannot prove accuracy; programs with ghost functions or unbounded quantifiers filtered out — [arXiv 2604.05820](https://arxiv.org/pdf/2604.05820)
- Clover: three-way consistency (code ↔ docstring ↔ annotations) as the acceptance criterion; 87% acceptance on correct, 0 false positives on adversarial incorrect — [arXiv 2310.17807](https://arxiv.org/abs/2310.17807v4)
- Vericoding: validation scripts to detect disabling proof checkers or trivializing specifications — [alphaxiv](https://www.alphaxiv.org/benchmarks/mit/vericoding-benchmark)
- Tinelli, "Scalable Proof Production and Checking in SMT" (SAT 2024 invited): cvc5 produces textual proof certificates in multiple formats via a generic proof language based on SMT-LIB v3, customizable with new rules, integrating SAT-solver proofs via oracles, with "a small runtime overhead"; evaluated with a companion checker showing "viability of high-performance, fine-grained proof production and checking"; targets "skeptical proof assistants" — [LIPIcs SAT 2024](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SAT.2024.2)
- Kind 2 model checker emits proof certificates (SMT-LIB-based, checked externally) — [Kind 2 docs](https://kind.cs.uiowa.edu/kind2_user_docs/v2.3.0/9_other/5_proofs.html)
- RCE: `example` lines are part of the program and a failing example makes `rce check` refuse the file; proposal oracle = (a) intent examples, (b) properties sampled with seed derived from intent hash, (c) differential agreement between reference interpreter and emitted targets; rewrites require randomized check then Z3 proof; intent bits I = H_task − H_corpus; gear at rank r supplies log2(r) search bits — local README, `closing-the-loop.md` §5.5, [RCE paper §4.3, §6](https://research.openie.dev/papers/rce/)
- Entropy of a line under a code LM separates correct from incorrect patches (median entropy-delta >0 vs <0) — a usable, training-free proxy for "how many bits this candidate resolves" — [arXiv 2404.15236](https://arxiv.org/pdf/2404.15236)

### Inferences
- "Intent as a first-class object" should be the tuple: `(type with refinement, examples, properties/ensures, invariant, uses/budget)` + two measured scalars: *soundness status* (which clauses are statically decided vs enforced) and *completeness score* (spectest rejection fraction under a seeded mutation of recorded outputs). The latter is what no classical synthesizer records and what SpecRL shows is the actual failure mode of gated loops.
- Derivation log record per hole, ordered and hashed (P4): `{hole, stage ∈ {lookup, enum, egraph, constraint, repair}, candidate_hash, verdict ∈ {type-reject, example-reject(counterexample), property-reject(seed, cex), proof-reject(cert), accepted}, bits: log2(rank among surviving candidates), entropy_delta, est_j}`. "Bits resolved" = Σ log2(|candidates before| / |candidates after|) per eliminating check, which makes the gate's contribution ("the gate supplies the rest") a measured number rather than a residual.
- Proof certificates: adopt cvc5's textual certificate as the stored object for rewrite proofs (replacing a bare Z3 "unsat"), so promotion carries a checkable artifact; this matches "the gate is a boundary proof, not a score" (§2.4) and makes R1 (monotone correctness) auditable offline.
- Clover's three-way consistency is directly importable as an `rce check` rule: intent prose ↔ `example`/`ensures` ↔ body; the RCE `intent "…"` string is currently inert and should become a checked field (at minimum: every `ensures`/`example` must be reachable/non-vacuous, W-CON-1 extended to "no `ensures` that is a tautology in the decidable fragment").

### Gaps
- Daikon (dynamic invariant detection), Hypothesis/QuickCheck generator-based intent capture, and Rosette's symbolic-profiling provenance were not fetched; no numeric "intent bits" measure beyond RCE's own definition was found in the literature.
- DRAT/LFSC/Alethe checker overheads (e.g. % of solve time) were not obtained; Tinelli's abstract says only "small".

---

## KQ6. Caching and reuse: clone detection, shape-hash search, skill libraries, DGM archive, AlphaEvolve database — measured reuse rates

### Takeaway
Reuse is universally claimed and almost never measured as a rate. Voyager reports outcome multipliers (3.3× items, 15.3× faster milestones) for a code skill library but no reuse fraction; DGM reports lineage structure and a 51.3% retention rate, not reuse; AlphaEvolve reports production impact (0.7% of Google compute recovered, 23% kernel speedup) from an evaluator-gated program database. RCE's R2 (escalations 21 → 15 over eight rounds) is already a more precise reuse measurement than any of these; the open problem is to publish the hit rate per gear per round.

### Cited Findings
- Voyager (May 2023): "ever-growing skill library of executable code"; 3.3× more unique items, 2.3× longer distances, up to 15.3× faster tech-tree milestones than prior SOTA; skills described as compositional and transferable to a new world; no reuse statistic in the abstract — [arXiv 2305.16291](https://arxiv.org/abs/2305.16291)
- DGM: archive with parent selection ∝ performance and ∝ 1/(children); no reuse rate reported; 51.3% of generated agents retained basic editing functionality; greedy selection 39.7% vs 50.0% — [arXiv 2505.22954v3](https://arxiv.org/html/2505.22954v3)
- AlphaEvolve (DeepMind, May 14 2025): every generated+evaluated program stored in a database driving an evolutionary algorithm that selects prompt material; results: 4×4 complex matrix multiply in 48 scalar multiplications (beats Strassen 1969 in that setting), Borg heuristic recovering ~0.7% of worldwide compute in production >1 year, 23% Gemini matmul kernel speedup (1% training-time cut), >50 open math problems: ~75% rediscovered SOTA, ~20% improved; Verilog change required rigorous verification before TPU integration — [DeepMind blog](https://deepmind.google/discover/blog/alphaevolve-a-gemini-powered-coding-agent-for-designing-advanced-algorithms/)
- RCE: G0 keyed by SHA-256 shape hash (because n-gram predictability is largely syntax tokens, Rahman et al.); R2: cumulative escalations over eight rounds 21 → 15 with one correction at the sinks; R3: round energy falls toward handler floor as escalations → 0; ecosystem run 10,000 Forms, 393 s CPU, 0 model calls; Python projection 9,999/10,000 (one miss, no root cause) — [RCE paper §2.2–2.4, §4.2](https://research.openie.dev/papers/rce/)
- Hindle et al. (code "very repetitive"), Gabel & Su, Lopes et al. (most lines/files exist elsewhere), Ray et al. (buggy lines higher entropy) are the RCE paper's cited basis for G0 — [RCE paper §2.1](https://research.openie.dev/papers/rce/)

### Inferences
- The field has no standard "reuse rate" metric; RCE should define and publish one: per round, fraction of residuals resolved at G0 (hit), G1, G2, G3–G5, plus cumulative energy, and the falsifier "reuse rate non-increasing over rounds on the reference workload refutes R2/R3".
- AlphaEvolve's gate is a *scoring* evaluator (fitness), not a boundary proof; its production wins came where the evaluator is exact (compute scheduling, kernel timing) or where an external verifier existed (Verilog). This supports RCE's refusal of score-gates for promotion but suggests a scored *ranking* inside a gear is compatible with a proof gate at promotion.
- Voyager's retrieval-by-description is the opposite of G0's hash-by-shape; for intent-level reuse (`rce new TEMPLATE`), a second index keyed by normalized intent (type + canonicalized examples/ensures) is needed, i.e. Hoogle-style type-up-to-isomorphism plus example-set hashing — otherwise two identical intents written differently miss G0.

### Gaps
- No clone-detection or code-search-by-hash reuse rates (e.g. from SourcererCC/Lopes et al. 2017 "DéjàVu") were re-fetched; the RCE paper's citation is the only pointer here.
- Voyager's full-paper ablation (skill library removed) was not fetched; only abstract-level multipliers are available.

---

## KQ7. Design synthesis: what "intent" should be, how to record the derivation, and what RCE should adopt, refuse, and leave open

### Takeaway
Intent = a Form with typed refined holes plus examples, properties, invariants, effect bounds and budget (as proposed), with two additional *measured* fields — completeness (spectest rejection fraction) and statically-decided-vs-enforced status per clause — and a non-vacuity check at admission. The derivation is a hashed sequence of eliminating checks, each recording candidates-before/after (bits), counterexample or certificate, and est_j; the gate's contribution becomes a number. Adopt ECTA-style type-pruned enumeration, entropy-delta ranking, cvc5-style proof certificates, Clover-style consistency, cost-of-pass escalation; refuse score-gated promotion, unbounded/non-executable contracts, in-gear self-refinement loops, and Verified-only benchmarking.

### Cited Findings
- (All findings above; key anchors) SpecRL completeness via spectests and vacuity zero-reward — [arXiv 2604.05820](https://arxiv.org/pdf/2604.05820); Clover 87%/0 FP — [arXiv 2310.17807](https://arxiv.org/abs/2310.17807v4); ECTA 88% vs 64% — [arXiv 2206.07828](https://arxiv.org/pdf/2206.07828); entropy-delta +49% top-1 — [arXiv 2404.15236](https://arxiv.org/pdf/2404.15236); cost-of-pass — [arXiv 2504.13359](https://arxiv.org/abs/2504.13359v1); cvc5 certificates — [SAT 2024](https://drops.dagstuhl.de/entities/document/10.4230/LIPIcs.SAT.2024.2); Verified vs Pro gap and contamination audit — [aicodereview.cc](https://aicodereview.cc/blog/swe-bench-scores-leaderboard); VeruSAGE >80% — [arXiv 2512.18436](https://arxiv.org/abs/2512.18436v1); Vericoding Dafny 67–82 / Verus 44 / Lean 27 — [alphaxiv](https://www.alphaxiv.org/benchmarks/mit/vericoding-benchmark); RCE proposal §5.1–5.6 and F.6 — local files.

### Inferences (recommendations in RCE terms)
Adopt:
1. **Intent object** (`.intent`, proposal §5.1) extended with: `completeness: {seed, n_spectests, rejected}` computed by mutating recorded outputs of `example` traces and of oracle layer (b) samples; `clauses[]: {index, status ∈ {decided, enforced}}`; admission rule W-INT-1: refuse an intent whose `ensures` set rejects 0 spectests (vacuous) or whose examples are all subsumed by type alone. Keep `intent "…"` prose but hash it into the module and require Clover-style consistency where a G3–G5 proposer is used (prose ↔ examples/ensures, verifier-checked).
2. **Catalog** (§5.2): add ECTA/Hectare-style equality-constrained enumeration for the type-directed stage; add named sub-terms to the Form IR (removes the 77-refusal class and unlocks multi-function synthesis, the SyGuS-unsolved class).
3. **Gate**: store the cvc5/Z3 proof certificate object (not verdict) for rewrites and contract discharges; add a contamination falsifier for L5–L7 (gold-patch verbatim recall from issue text alone); report plausible and correct separately (already) plus Pro-style held-out.
4. **Derivation log**: per hole, ordered list of `(stage, candidate_hash, check, outcome, cex|cert, bits = log2(before/after), entropy_delta, est_j)`; total search bits = Σ over eliminating checks; publish median per rung (extends the §6 table's "median search bits" to attribution by stage).
5. **Escalation policy**: choose next gear by minimum expected cost-of-pass (pass rate × joules per attempt); use entropy-delta as the within-gear ranking key before running the gate.
6. **Reuse metric**: per-round G0 hit rate and cumulative energy; add intent-keyed index (type + canonical example set) alongside shape-hash for `rce new`.

Refuse:
- Score-based promotion (AlphaEvolve/DGM style fitness) — ranking only, never a gate (§2.4 "boundary proof, not a score").
- Contracts outside the evaluable fragment (already refused by F.6.3) — but charge real predicate cost in `est_j`, not one operator per clause.
- Self-refinement/majority voting loops inside a single model gear (cost-of-pass evidence); escalate instead.
- Reporting SWE-bench Verified alone as evidence for L5–L7.

Open problems (no result in the literature settles them):
- A principled "bits of intent" measure independent of a reference corpus; RCE's I = H_task − H_corpus depends on corpus choice and no external work measures it.
- Runtime cost of always-on contracts at scale in a deterministic, energy-accounted runtime (no numbers found).
- Reuse rate as a function of catalog size and intent diversity (no field metric exists).
- Completeness of a spec under unbounded quantifiers refused by F.6.3 — spectests are finite; SpecRL explicitly filters such programs.
- L0 operator-table overlap confound (RCE's own open issue) — run the operator-inversion baseline.

### Gaps
- No source directly evaluates "intent with holes + catalog + e-graph + enforced contracts" as one system; the closest composites are Hectare (types), Burst (angelic strengthening), Clover/SpecRL (spec quality), and AutoVerus/VeruSAGE (proof repair). The combined design is unmeasured.
