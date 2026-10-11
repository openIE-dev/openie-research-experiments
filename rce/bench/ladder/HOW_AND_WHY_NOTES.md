# Draft notes for the paper's "How RCE works, and why" section (coding-theory terms)

These are working notes from the ladder runs, not paper text.

## 1. The channel

A coding task is a message: the intent X that the requester holds, which has
to become a program Y that passes a gate G. RCE reads the task as decoding
over a channel whose side information is the corpus C: the program around the
edit, the project, its libraries, its tests, and the index of fixes and
handlers RCE already has. The bits RCE must obtain from outside are the
conditional entropy

    I_supplied = H(Y | C, task statement)

and the bits a deterministic gear contributes are the log of the size of the
candidate set it can enumerate before the gate accepts. A gear that ranks the
accepted program at position r has resolved log2(r) bits by search; the gate
G is the parity check that makes the decoding exact. Correctness is a gate,
and joules rank among programs that pass it.

## 2. Why low rungs need no model

On L0 (one token wrong) the correct program lies within edit distance one of
the input, inside a neighbourhood of a few dozen to a few hundred
candidates. The intent bits are the location plus a few bits of operator
choice. G0-T enumerates that neighbourhood in a fixed prior order, so the
median search cost on the L0 TEST split is about 2.3 bits (rank ≈ 5), at
an estimated fraction of a joule per task. That is a code with a tiny
covering radius: every point of the error ball decodes.

## 3. Where the bits come from on L1

On real single-statement bugs (ManySStuBs4J, TSSB-3M) the edit is still
small, but its material often isn't in the line: a different method name, a
string the developer had in mind, a conjunct for an `if`. RCE draws those bits
from the corpus first: identifiers in the file (nearest occurrence first),
then the project index (G0-V:index, built only from buggy code, never from
fixes), literals of the file, and structural moves (swap, drop or add an
argument; add or drop a condition). The by-pattern table on the TEST split is
a map of the bits still missing:
- operator, boolean, argument-swap and dropped-argument bugs: 79-91% solved. The bits are in the line.
- identifier and method-name changes: 22-37% solved with only a 7-line hunk as the corpus. The missing bits are the method vocabulary of the receiver's type. Next mechanism: a type-indexed API index (receiver type, then methods of that type), so the method choice costs log2(|methods of T|) bits rather than log2(|project vocabulary|).
- more- or less-specific `if` (3-7%): the conjunct is new intent. Next mechanism: conjuncts mined from the project's other guards on the same variable (a G0 index of guards).
- Python SINGLE_STMT and string-literal changes (TSSB-3M): high-entropy rewrites. These are where a supplier of the fit (spec, test, person, or the local model) has to provide bits, and where the compiled-out route applies: a supplied fix becomes a new G0 entry, so the same pattern later costs log2(rank) bits and 0 model calls.

## 4. The general law the ladder measures

For each rung, solved tasks need I_supplied ≤ log2(candidates the gear
enumerates under the joule budget). Climbing the ladder means adding gears
that move bits from "supplied" to "already in the corpus": templates (G1),
then indexes of existing code (G0), then Form/spec composition of known
handlers. Wherever a model supplies bits, it does so once, and the result is
compiled into the corpus. Every rung is an engineering target. A rung that
isn't passing yet is a gear still to be built.

## 5. Measured so far (frozen engines, TEST splits only; see RESULTS.md)
