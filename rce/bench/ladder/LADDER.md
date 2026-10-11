# The RCE coding ladder

RCE's claim is that programming is intent conversion: a high-entropy intent
(what the person wants) becomes a low-entropy artifact (deterministic code).
A coding task is therefore measured by one quantity, the **intent bits** it
needs: the bits that must be supplied from outside the corpus RCE already
holds (the program around the edit, the libraries, the tests, the index of
known fixes and handlers). Writing H_task for the bits that pin the target
artifact down and H_corpus for the bits the corpus already fixes,

    I_supplied = H_task - H_corpus   (bits RCE must obtain: from a gear's prior, a spec, a test, a person or a model)

and the work of a rung is to build the gear that supplies those bits as cheaply
as possible and proves the result. A gear that ranks the right edit at rank r
among its candidates has supplied log2(r) bits of search; the gate (tests,
identity, equivalence) supplies the rest. The ladder is ordered by how many
bits the task leaves unsupplied, and by edit size as the objective proxy.

## Rungs (preregistered 2026-10-11, before the full runs)

| rung | task | objective metric (all must hold) | grounding | RCE mechanism |
|---|---|---|---|---|
| L0 | one token wrong | token edit distance 1; 1 line; location given | mutation operators of PIT (Coles et al. ISSTA 2016) and mutmut; mutant/real-fault coupling (Just et al. FSE 2014) | G0-T: the single-token neighbourhood, prior-ordered |
| L1 | one statement wrong (real bug) | 1 statement changed; any number of tokens in it | ManySStuBs4J (Karampatsis and Sutton MSR 2020), TSSB-3M (Richter and Wehrheim MSR 2022), PySStuBs | G0-T then G1 templates, then the G0 index of fixes seen in the corpus |
| L2 | one hunk, one function | 1 hunk, 1 function, ≤ 6 changed lines | Defects4J single-hunk subset (Sobreira et al. SANER 2018 dissection), QuixBugs, BugsInPy | G1-J (TBar port) with tests as gate |
| L3 | several hunks, one file | ≥ 2 hunks or ≥ 2 functions, 1 file | Defects4J multi-hunk subset (Hercules, Saha et al. ICSE 2019) | G1 kept-partial composition across positions |
| L4 | several files | ≥ 2 files changed | Defects4J, GitBug-Java (Silva et al. MSR 2024), Bears | composition of known handlers across files |
| L5 | function from spec or tests | body written from a signature, docstring, tests | HumanEval (Chen et al. 2021), MBPP (Austin et al. 2021), HumanEval-X | Form + spec + synthesis (enumerative/SyGuS), G0 index of existing functions; local model as fit supplier, compiled out |
| L6 | issue-level change | a real GitHub issue resolved; FAIL_TO_PASS tests | SWE-bench Lite / Verified (Jimenez et al. ICLR 2024; OpenAI 2024 difficulty labels: <15 min, 15 min-1 h, 1-4 h, >4 h) | Form of the issue, localization, composition |
| L7 | program from spec | whole program or app built to a spec | Codeflaws/RunBugRun programs as specs; APPS (Hendrycks 2021) difficulty labels | Form → engine, handlers composed and proven |

Edit size is read from the developer diff (lines, hunks, functions, files),
the same dissection metrics Sobreira et al. and Madeiral et al. (Bears) use.
Where a benchmark carries its own difficulty label (SWE-bench Verified time
buckets, APPS introductory/interview/competition) it is reported as a
sub-stratum of the rung.

## Corpora, pinned

See `corpora.json` for every source with version, licence, and SHA.
L0 sources: 12 real repositories (6 Java, 6 Python) at pinned commits, all
Apache-2.0, BSD or MIT. L1: TSSB-3M v1.0.0 (CC-BY-4.0, Zenodo 5845439),
ManySStuBs4J 2.0 (CC-BY-4.0, Zenodo 3653444).

## Gates (correctness first, joules second)

- L0, L1: the patched line is token-identical to the original / developer
  fix (whitespace ignored). Stricter than test-passing; a plausible but
  different patch counts as unsolved.
- L2-L4: the developer tests pass (plausible) and AST-normalized equality to
  the developer patch (correct), as in bench/defects4j.
- L5: the benchmark's hidden tests (pass@1, one deterministic attempt).
- L6: FAIL_TO_PASS and PASS_TO_PASS (the SWE-bench harness).
- L7: the spec's acceptance tests.

Unfinished rungs are work still to do, not a ceiling. See PREREG.json.
