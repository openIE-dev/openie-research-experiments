# Critique 6: faults at the host boundary (measured 2026-10-29)

Preregistered in `PREREG.json` (commit `56360e8`, before the run). Engine:
openIE-dev/rce branch `claude/host-faults` at `ca9371c1` (from main
`a82a0348`), `spec/checker/tests/host_faults.rs` in release mode, D files
under `/dev/shm`. Command, from `spec/checker`:

```sh
RCE_FAULT_SEEDS=1000 RCE_FAULT_MIXES=all,none,drop,dup,reorder,lose,restart,skew \
RCE_FAULT_OUT=runs.jsonl RCE_FAULT_DIR=/dev/shm/hf RCE_FAULT_THREADS=2 \
cargo test --release --test host_faults host_contract
```

72,000 runs (9 programs x 8 fault mixes x seeds 1 to 1000) in 789 s on two
threads; the 7,200 runs of seeds divisible by 10 were each run twice.
`results/runs.jsonl.gz` holds one line per run, `results/summary.json` and
`results/table.md` are made from it by `summarize.py`.

## The critique, and what was built

The critique: RCE's guarantees are about the pure step δ, while most
production faults (reordered, duplicated and dropped messages, clock
skew, crashes and restarts) happen in the host around it. To measure
this, the RCE project added a seeded fault injection harness to the host
tests. One seed fixes a client's operations and a fault schedule; the
programs run on the real `Host` with a durable D file, through the same
calls `rce host run` and `rce host serve` make (`apply_input` and
`settle` for a line, `http_input` for an HTTP request, `tick` for a
frame, `offer` and `close_window` for sourced inputs). The faults are
those of `PREREG.json`: a dropped copy, a duplicated copy, a copy delayed
up to 4 rounds (reorder), a lost answer, a kill in the middle of a batch
or between rounds with D left as a kill -9 leaves it, torn, cut to the
last barrier or cut part way past it, and steps of the wall clock.

Two ways of admitting the same client stream are compared. A *typed*
input is a line of the input stream (HC-10b); it carries no identity. A
*sourced* input carries (source, seq, tick) and is admitted in windows
(HC-15 to HC-17), where HC-16 removes duplicates and holds an input after
a gap until the gap is filled.

## Results

Counts are runs out of 1,000 per row. (a) replay of D with no adapters
does not give the live state, or a rerun gives a different D; (b) an
entry that is neither a step nor a kept step; (c) a restart that reuses
an id. (d) is what the program mishandles against the client's intent
(each operation applied once, in order), with the lowest seed that shows
it. The gap column is a property of the host contract, not of the
program (see below).

| program | mix | runs | (a) | (b) | (c) | not live | entries | net ids (after a restart) | kept | (d) runs per kind (lowest seed) |
|---|---|---|---|---|---|---|---|---|---|---|
| account/sourced | all | 1000 | 0 | 0 | 0 | 0 | 200621 | - | fail 4637 | 0; gap: duplicate_acked_without_outcome 998 |
| account/sourced | drop | 1000 | 0 | 0 | 0 | 0 | 120735 | - | fail 4637 | 0; gap: duplicate_acked_without_outcome 847 |
| account/sourced | dup | 1000 | 0 | 0 | 0 | 0 | 87637 | - | fail 4637 | 0; gap: duplicate_acked_without_outcome 960 |
| account/sourced | lose | 1000 | 0 | 0 | 0 | 0 | 104875 | - | fail 4637 | 0; gap: duplicate_acked_without_outcome 965 |
| account/sourced | none | 1000 | 0 | 0 | 0 | 0 | 87637 | - | fail 4637 | 0 |
| account/sourced | reorder | 1000 | 0 | 0 | 0 | 0 | 142353 | - | fail 4637 | 0 |
| account/sourced | restart | 1000 | 0 | 0 | 0 | 0 | 91407 | - | fail 4637 | 0 |
| account/sourced | skew | 1000 | 0 | 0 | 0 | 0 | 89735 | - | fail 4637 | 0 |
| account/typed | all | 1000 | 0 | 0 | 0 | 0 | 85732 | - | fail 5529 | answer_differs 814 (seed 1); duplicate_applied 987 (seed 1); state_differs 998 (seed 1) |
| account/typed | drop | 1000 | 0 | 0 | 0 | 0 | 52999 | - | fail 4614 | answer_differs 589 (seed 1); state_differs 588 (seed 1) |
| account/typed | dup | 1000 | 0 | 0 | 0 | 0 | 51169 | - | fail 5162 | answer_differs 465 (seed 1); duplicate_applied 912 (seed 1); state_differs 912 (seed 1) |
| account/typed | lose | 1000 | 0 | 0 | 0 | 0 | 57322 | - | fail 5114 | answer_differs 541 (seed 1); duplicate_applied 918 (seed 1); state_differs 941 (seed 1) |
| account/typed | none | 1000 | 0 | 0 | 0 | 0 | 47637 | - | fail 4637 | 0 |
| account/typed | reorder | 1000 | 0 | 0 | 0 | 0 | 59129 | - | fail 4650 | answer_differs 655 (seed 1); state_differs 655 (seed 1) |
| account/typed | restart | 1000 | 0 | 0 | 0 | 0 | 49236 | - | fail 4670 | answer_differs 46 (seed 43); duplicate_applied 96 (seed 8); state_differs 96 (seed 8) |
| account/typed | skew | 1000 | 0 | 0 | 0 | 0 | 49735 | - | fail 4637 | 0 |
| handshake/sourced | all | 1000 | 0 | 0 | 0 | 0 | 139084 | - | 0 | 0; gap: duplicate_acked_without_outcome 988 |
| handshake/sourced | drop | 1000 | 0 | 0 | 0 | 0 | 83138 | - | 0 | 0; gap: duplicate_acked_without_outcome 729 |
| handshake/sourced | dup | 1000 | 0 | 0 | 0 | 0 | 59806 | - | 0 | 0; gap: duplicate_acked_without_outcome 900 |
| handshake/sourced | lose | 1000 | 0 | 0 | 0 | 0 | 72472 | - | 0 | 0; gap: duplicate_acked_without_outcome 886 |
| handshake/sourced | none | 1000 | 0 | 0 | 0 | 0 | 59806 | - | 0 | 0 |
| handshake/sourced | reorder | 1000 | 0 | 0 | 0 | 0 | 98066 | - | 0 | 0 |
| handshake/sourced | restart | 1000 | 0 | 0 | 0 | 0 | 62375 | - | 0 | 0 |
| handshake/sourced | skew | 1000 | 0 | 0 | 0 | 0 | 61366 | - | 0 | 0 |
| handshake/typed | all | 1000 | 0 | 0 | 0 | 0 | 70967 | - | fail 13588 | answer_differs 1000 (seed 1); duplicate_applied 604 (seed 6); state_differs 1000 (seed 1) |
| handshake/typed | drop | 1000 | 0 | 0 | 0 | 0 | 39551 | - | fail 4588 | answer_differs 839 (seed 1); state_differs 793 (seed 1) |
| handshake/typed | dup | 1000 | 0 | 0 | 0 | 0 | 34429 | - | fail 889 | duplicate_applied 725 (seed 1); state_differs 611 (seed 1) |
| handshake/typed | lose | 1000 | 0 | 0 | 0 | 0 | 39528 | - | fail 1906 | answer_differs 784 (seed 1); duplicate_applied 544 (seed 1); state_differs 396 (seed 1) |
| handshake/typed | none | 1000 | 0 | 0 | 0 | 0 | 31403 | - | 0 | 0 |
| handshake/typed | reorder | 1000 | 0 | 0 | 0 | 0 | 49976 | - | fail 10791 | answer_differs 1000 (seed 1); state_differs 1000 (seed 1) |
| handshake/typed | restart | 1000 | 0 | 0 | 0 | 0 | 32518 | - | fail 36 | answer_differs 27 (seed 52); duplicate_applied 47 (seed 8); state_differs 37 (seed 8) |
| handshake/typed | skew | 1000 | 0 | 0 | 0 | 0 | 32963 | - | 0 | 0 |
| ledger/sourced | all | 1000 | 0 | 0 | 0 | 0 | 204762 | - | fail 8778 | 0; gap: duplicate_acked_without_outcome 998 |
| ledger/sourced | drop | 1000 | 0 | 0 | 0 | 0 | 124876 | - | fail 8778 | 0; gap: duplicate_acked_without_outcome 847 |
| ledger/sourced | dup | 1000 | 0 | 0 | 0 | 0 | 91778 | - | fail 8778 | 0; gap: duplicate_acked_without_outcome 960 |
| ledger/sourced | lose | 1000 | 0 | 0 | 0 | 0 | 109016 | - | fail 8778 | 0; gap: duplicate_acked_without_outcome 965 |
| ledger/sourced | none | 1000 | 0 | 0 | 0 | 0 | 91778 | - | fail 8778 | 0 |
| ledger/sourced | reorder | 1000 | 0 | 0 | 0 | 0 | 146494 | - | fail 8778 | 0 |
| ledger/sourced | restart | 1000 | 0 | 0 | 0 | 0 | 95548 | - | fail 8778 | 0 |
| ledger/sourced | skew | 1000 | 0 | 0 | 0 | 0 | 93876 | - | fail 8778 | 0 |
| ledger/typed | all | 1000 | 0 | 0 | 0 | 0 | 90698 | - | fail 10494 | duplicate_applied 980 (seed 1); state_differs 980 (seed 1) |
| ledger/typed | drop | 1000 | 0 | 0 | 0 | 0 | 57163 | - | fail 8778 | 0 |
| ledger/typed | dup | 1000 | 0 | 0 | 0 | 0 | 55672 | - | fail 9665 | duplicate_applied 890 (seed 1); state_differs 890 (seed 1) |
| ledger/typed | lose | 1000 | 0 | 0 | 0 | 0 | 61971 | - | fail 9763 | duplicate_applied 890 (seed 1); state_differs 890 (seed 1) |
| ledger/typed | none | 1000 | 0 | 0 | 0 | 0 | 51778 | - | fail 8778 | 0 |
| ledger/typed | reorder | 1000 | 0 | 0 | 0 | 0 | 63257 | - | fail 8778 | 0 |
| ledger/typed | restart | 1000 | 0 | 0 | 0 | 0 | 53407 | - | fail 8835 | duplicate_applied 87 (seed 8); state_differs 87 (seed 8) |
| ledger/typed | skew | 1000 | 0 | 0 | 0 | 0 | 53876 | - | fail 8778 | 0 |
| notes_http/http | all | 1000 | 0 | 0 | 0 | 0 | 121951 | - | 0 | delete_answered_404 323 (seed 1); duplicate_note 968 (seed 1) |
| notes_http/http | drop | 1000 | 0 | 0 | 0 | 0 | 82552 | - | 0 | 0 |
| notes_http/http | dup | 1000 | 0 | 0 | 0 | 0 | 75814 | - | 0 | duplicate_note 807 (seed 2) |
| notes_http/http | lose | 1000 | 0 | 0 | 0 | 0 | 89126 | - | 0 | delete_answered_404 330 (seed 5); duplicate_note 815 (seed 1) |
| notes_http/http | none | 1000 | 0 | 0 | 0 | 0 | 71000 | - | 0 | 0 |
| notes_http/http | reorder | 1000 | 0 | 0 | 0 | 0 | 90202 | - | 0 | 0 |
| notes_http/http | restart | 1000 | 0 | 0 | 0 | 0 | 72379 | - | 0 | delete_answered_404 26 (seed 20); duplicate_note 62 (seed 10) |
| notes_http/http | skew | 1000 | 0 | 0 | 0 | 0 | 72688 | - | 0 | 0 |
| notes_net/net | all | 1000 | 0 | 0 | 0 | 0 | 359015 | 19155 (9383) | 0 | delete_answered_404 177 (seed 1); duplicate_note 807 (seed 1) |
| notes_net/net | drop | 1000 | 0 | 0 | 0 | 0 | 184428 | 14286 (0) | 0 | 0 |
| notes_net/net | dup | 1000 | 0 | 0 | 0 | 0 | 144147 | 14151 (0) | 0 | duplicate_note 557 (seed 2) |
| notes_net/net | lose | 1000 | 0 | 0 | 0 | 0 | 186804 | 14296 (0) | 0 | delete_answered_404 177 (seed 1); duplicate_note 560 (seed 1) |
| notes_net/net | none | 1000 | 0 | 0 | 0 | 0 | 135528 | 13000 (0) | 0 | 0 |
| notes_net/net | reorder | 1000 | 0 | 0 | 0 | 0 | 182512 | 13000 (0) | 0 | 0 |
| notes_net/net | restart | 1000 | 0 | 0 | 0 | 0 | 162486 | 13724 (3500) | 0 | 0 |
| notes_net/net | skew | 1000 | 0 | 0 | 0 | 0 | 138568 | 13000 (0) | 0 | 0 |
| ratelimit/typed | all | 1000 | 0 | 0 | 0 | 0 | 641409 | - | trap 10283 | duplicate_applied 995 (seed 1); kept_on_clock_step 995 (seed 1); over_limit 28 (seed 60) |
| ratelimit/typed | drop | 1000 | 0 | 0 | 0 | 0 | 283650 | - | 0 | 0 |
| ratelimit/typed | dup | 1000 | 0 | 0 | 0 | 0 | 207990 | - | 0 | duplicate_applied 987 (seed 1) |
| ratelimit/typed | lose | 1000 | 0 | 0 | 0 | 0 | 292260 | - | 0 | duplicate_applied 983 (seed 1) |
| ratelimit/typed | none | 1000 | 0 | 0 | 0 | 0 | 204000 | - | 0 | 0 |
| ratelimit/typed | reorder | 1000 | 0 | 0 | 0 | 0 | 445848 | - | 0 | 0 |
| ratelimit/typed | restart | 1000 | 0 | 0 | 0 | 0 | 220686 | - | 0 | 0 |
| ratelimit/typed | skew | 1000 | 0 | 0 | 0 | 0 | 212967 | - | trap 8967 | kept_on_clock_step 811 (seed 1); over_limit 490 (seed 1) |

### (a), (b), (c): the host contract held in every run

- **(a) Determinism under faults: 0 of 72,000 runs.** Every D replayed
  with every adapter disconnected to the live state and state hash,
  after drops, duplicates, reordering, lost answers, 2,200 to 3,300
  restarts per program and mix with every kill variant, and clock steps.
  The 7,200 reruns wrote byte-identical D files.
- **(b) Every event is a step or a kept step: 0 runs.** Every host entry
  and every kept entry left the state hash unchanged, every kept cause was
  one of HC-21's (`fail` for a declared error, `trap` for the token
  bucket's underflow), and replay found no host fault.
- **(c) Restarts never reuse ids: 0 runs.** Every `host.Restarted` had
  below equal to its own seq. In notes_net, 12,883 of the net ids checked
  were issued after a restart; each was at least that restart's below and
  none was issued twice. No HTTP request id was used twice.
- **HC-16 on sourced inputs: 0 runs** of account, ledger or handshake
  applied an operation twice, answered differently from the in-order run,
  or ended in a different state, under every mix. The admitter removed
  the duplicates (`host_dups_removed` in `summary.json`) and held inputs
  after a gap, so even reordering left no trace in the state.

These support the host contract's claims at this scale. They do not
support the reading that RCE protects the program from the faults.

### (d): the faults the programs mishandle

With no faults, no program mishandles anything (row `none`, 0 in every
program). With faults, the same programs mishandle them often:

| Kind | What happened | Programs | Lowest seed, one fault class |
|---|---|---|---|
| duplicate_applied | a retried line was applied twice (a deposit, a withdrawal, a transfer, a `Data(n)`, a rate-limited request) | account, ledger, handshake, ratelimit (typed) | `dup` seed 1 (account op 6 `Withdraw(cents: 120)` applied 2 times); `lose` seed 1; `restart` seed 8 |
| duplicate_note | a retried POST made a second note; after the client deleted the id it was told, the other copy stayed | notes_http, notes_net | notes_http `dup` seed 2 (`c1n7` held 2 times), `lose` seed 1, `restart` seed 10; notes_net `dup` seed 2, `lose` seed 1 |
| delete_answered_404 | a retried DELETE was answered 404 because the first attempt, whose answer was lost, had deleted the note | notes_http, notes_net | notes_http `lose` seed 5, `restart` seed 20; notes_net `lose` seed 1 |
| answer_differs, state_differs | an operation applied out of the client's order: a withdrawal before the deposit it needs, a `SynAck` before its `Syn` (kept with `OutOfOrder`) | account, handshake (typed) | `reorder` seed 1 and `drop` seed 1 (a retransmission arrives after later operations) |
| kept_on_clock_step | a backward clock step made `now_ns - last` underflow; T8 kept the step, so the request was neither allowed nor denied | ratelimit | `skew` seed 1 (811 of 1,000 runs) |
| over_limit | a forward clock step gave tokens that true time did not: client b allowed 7 requests in 3 s of true time with a bucket of 3 and one per second | ratelimit | `skew` seed 1 (490 of 1,000 runs) |

Any of these reproduces with
`RCE_FAULT_SEED=N RCE_FAULT_MIXES=CLASS RCE_FAULT_PROGRAMS=PROGRAM`, and
`RCE_FAULT_KEEP=1` keeps the D file, which `rce host replay` folds to the
same state. Under `restart` alone, 87 to 96 of 1,000 typed runs applied a
duplicate: a kill after a batch was in D but before its barrier answered,
so the client retried an input that the reopened D still held.

No restart alone made a duplicate in notes_net: its kills fall between
frames, after every answer of the frame was handed out, so the harness
never kills a notes_net host between applying a request and answering
it. That is a limit of the harness, not a property of the program.

### What the host contract leaves to the client

- **Exactly once needs an identity the CLI host does not take.** HC-16
  covers inputs with (source, seq). The lines of `rce host run` and `rce
  host serve` and HTTP requests carry none, so a retry is a new input;
  sourced admission is reachable only through the embedding API
  (`Host::offer`, `Host::close_window`). Appendix E now says so after
  HC-16 (rce `ca9371c1`).
- **A duplicate is acked without its outcome.** In 729 to 998 of 1,000
  sourced runs under drop, dup or lose, the answer the client finally got
  for some operation was a duplicate ack: the window that found the copy
  holds no outcome for it, so the client learns that its input is in D
  but not whether its step was applied or kept (it has to read D). This
  is counted as a gap, not as a fault of the program, and is now stated in
  Appendix E.
- **The CLI host supplies no wall clock.** `rce host run` and `serve`
  deliver `Tick` frames but no `WallTime`; the harness injects it through
  `Host::wall_time`. Clock skew therefore reaches only programs embedded
  with a clock adapter, and in them it is the program's problem: the
  three stream programs and the notes services do not read time and were
  unaffected (row `skew`, 0), while the token bucket mishandled it in most
  runs.

## The answer to the critique

The critique is right about where the faults are, and the measurement
does not show that RCE prevents them: a program without an idempotency
key applies a duplicate twice, one that trusts the wall clock misbehaves
when it steps, and the host contract does not change that for typed or
HTTP inputs. What the contract does is narrower and held in every one of
72,000 runs: every fault that reached the program is an entry of D, the
run replays from D exactly, no event produced a state outside a step or a
kept step, and a restart never handed an old id to a new resource. So a
mishandled fault is replayable and detectable after the fact (each kind
above has a seed that reproduces it and a D that shows it), and the one
admission path with an identity (sourced inputs, HC-16) removed
duplicates and reordering entirely. The result goes against the strong
reading of RCE's guarantees and supports the narrow one.

## Host bugs

None found: no run broke (a), (b) or (c). The gaps above are recorded in
Appendix E instead of being changed; giving `rce host run`/`serve` a
sourced input form, and returning the first copy's outcome with a
duplicate ack, would be language changes for a proposal.

## Limits

- The transport, the HTTP connections and the sockets are simulated; the
  real TCP and HTTP adapters were not run. The simulated net adapter
  issues ids by the rule of the reference adapter (`restart(floor)`), so
  (c) tests the host's half of HC-22 (calling it with the right floor)
  and the id rule as written, not the reference adapter's code.
- A kill falls between host calls, never inside one admission's drain;
  the partial cut variant cuts D at a line past the last barrier, which
  covers stopping between the entries of one admission.
- The oracle is one client's intent (several independent clients for the
  notes services); interleavings of concurrent clients are not judged.
- The fault rates are high (10 % per copy), chosen so that every class
  occurs in most seeds; the counts are rates under this schedule, not
  production rates.
- The harness was tried on seeds 1 to 50 while it was written; those
  trial counts are not the results above.
