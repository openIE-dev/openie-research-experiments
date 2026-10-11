# Defects4J, 100 bugs: G1-J (TBar port) vs TBar PerfectFL

## Bugs
The same 100 as the G1 run: the 61 active Lang bugs in 1-65, Chart 1-26,
Math 1-13 (run_batch.py). 0 model calls.

## TBar reference (tbar-ref/tbar_perfectfl_100.csv)
From TBar's repository, Results/PerfectFL/TBar (the 2019-07-10 update):
a directory in FixedBugs/ without a `_P`/`-P` suffix is a correct fix, one
with the suffix is plausible but incorrect, and PartiallyFixedBugs/ holds
patches that make only some failing tests pass. TBar's correctness labels
are its authors' manual judgments.

## Engine
src/repair/tbar.rs ports TBar's fixer to tree-sitter-java: the suspicious-
statement selection (SuspiciousCodeParser), the context-driven template
dispatch and its order (TBarFixer.fixWithMatchedFixTemplates), and all 15
templates with their mutation variants (ClassCastChecker, DataTypeReplacer,
ICASTIdivCastToDouble, LiteralExpressionMutator, MethodInvocationMutator,
NPEqualsShouldHandleNullArgument, NullPointerChecker, OperatorMutator,
ConditionalExpressionMutator, RangeChecker, ReturnStatementMutator,
StatementMover, StatementRemover, StatementInserter, VariableReplacer).
Types for VariableReplacer, MethodInvocationMutator and DataTypeReplacer come
from a project index (fields, methods, superclasses, imports) over --src.
Known differences: TBar iterates some HashMaps, so its order within one
template is not defined; the port uses insertion order. JDT and tree-sitter
trees differ (argument lists, parenthesized expressions); the port maps them.

## Harness (d4j_tbar.py)
- Localization: TBar's BugPositions.txt, the exact positions TBar used.
- Order: positions in file order, lines in order, statements on a line
  outermost first, candidates in template order. Whole-file duplicates are
  skipped. Caps: 10000 tried patches (TBar's own cap) and 30 min wall per bug.
- Validation: javac on the edited file, then the trigger tests, then the
  relevant tests. Plausible: all triggers pass and nothing that passed on the
  buggy version fails.
- Multi-location: a patch that fixes a strict subset of the failing triggers
  and breaks nothing is kept, and the search continues at the next position
  on top of it. A bug counts only when one combined patch passes. TBar
  instead restores the file after each partial patch and counts a bug fixed
  when the separate partial patches add up (for example Math-4), so our
  count is the stricter one.

## Correctness
1. Automatic: AST-normalized equivalence (`rce repair ast-eq`). For every
   file in the developer patch, the patched file and the developer-fixed file
   (patch reverse-applied byte-exactly, CRLF kept) have the same normal form:
   the token sequence of the tree-sitter parse with comments and layout
   dropped, redundant parentheses removed, and one-statement blocks unwrapped.
   Equal means correct.
2. Manual review: every other plausible patch is read against the developer
   patch and the triggering tests (REVIEW.md, one line of reasoning per bug).
   It counts as correct only if it is semantically equivalent to the
   developer fix on all inputs, the standard TBar's authors used.
   Overfitting patches stay plausible.

The old G1 harness compared whitespace-stripped text after reverse-applying
the patch in text mode. That turned CRLF into LF, so the fixed version of
every CRLF file (24 of the 26 Chart patches) failed to derive and could never match. That
is one reason the old run found 0 correct in Chart.
