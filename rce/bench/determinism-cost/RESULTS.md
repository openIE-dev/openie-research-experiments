# Critique 7: what determinism costs per step (first registered run, 2026-10-29)

Preregistered in `PREREG.json` (hash sidecar, committed at `7a2da18` and
pushed before the run). The run used openIE-dev/rce branch
`claude/determinism-cost` at `ac018204647605986782c72ba3977ef1d9740c17`
(the commit the preregistration names; clean tree), driver
`scripts/bench-determinism.py`, benchmark binary `rce-bench-det` built
from that commit with `cargo build --release`, and `rustc 1.97.0` for the
emitted and hand-written programs. Everything is in `results/`:
`results.json` (every configuration, its R, medians, min and max, start-up
times and the last output line), `tables.md` (made by `summarize.py`),
`streams/*.events` (the 11 streams, 1,000 applied events each) and
`run.log`.

**The critique.** "Bit-for-bit determinism and hash-chained logging
degrade throughput 10x to 100x." The two parts of determinism in RCE are
the float rules of 6.3 (no fused multiply-add (FMA), one rounding per
operation) and the log D of 6.1, in which every step writes an entry whose
`state_hash` is the SHA-256 of the canonical JSON of the whole state and
whose `hash` chains it to the previous entry.

**Machine.** One shared cloud VM: Intel Xeon @ 2.30 GHz, 4 logical CPUs,
Linux 6.18. Other jobs ran on it during the run (load average 114 at the
start, 10 to 130 during it), so CPU time (user + system of the measured
process) is the primary measure, as registered; wall time is in
`tables.md` and is about 1.2 to 2 times the CPU time.

## The numbers

CPU nanoseconds per step, median of 11 repeats (each repeat applies the
1,000-event stream R times; start-up subtracted). Letters as registered:
(a) the reference interpreter with the log D, (b) the same without it,
(c) the emitted Rust (`rce emit rust`, `rustc -O`), (d) hand-written
idiomatic Rust (`-C opt-level=3 -C target-cpu=native`).

| program | class | (b) δ only | (a) δ + D | (a) host | (c) emitted | (c) emitted + D | (d) hand, FMA | (d) hand, no FMA | (d) hand + D |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| bank | arithmetic | 1,148 | 4,880 | 7,016 | 435 | 4,062 | 0.6 | 0.6 | 2,192 |
| ring | arithmetic | 2,753 | 7,016 | 9,291 | 879 | 4,702 | - | - | - |
| automaton | arithmetic | 17,039 | 21,729 | 22,612 | 6,649 | 10,826 | 3.9 | 3.8 | 2,418 |
| inventory | collection | 104,671 | 131,262 | 136,640 | 17,549 | 40,760 | 39.5 | 39.8 | 13,238 |
| rcedb | collection | 76,365 | 98,260 | 103,535 | 25,164 | 49,611 | - | - | - |
| cart | collection | 4,026 | 8,963 | 12,084 | 2,614 | 7,637 | - | - | - |
| arm | float | 1,499 | 8,008 | 11,092 | 555 | 6,331 | 1.7 | 1.1 | 3,009 |
| floatvec | float | 1,385 | 9,745 | 14,628 | 548 | 7,227 | - | - | - |
| fir | float | 23,502 | 41,565 | 46,001 | 9,451 | 27,109 | 159 | 168 | 7,637 |
| elevator | state | 1,634 | 5,240 | 7,323 | 336 | 3,796 | 1.7 | 1.5 | 2,899 |
| lexer | state | 1,365 | 5,397 | 7,640 | 442 | 4,014 | - | - | - |

"(c) emitted" is the emitted program with its per-step state prints
removed (benchmark-only copy); "(c) emitted + D" is the same run with
`--trace`, which computes and prints every D entry. The plain emitted
program (state printed after every step) and `--trace` with the state
prints are in `tables.md` (1.4 to 61 µs). "(a) host" is the host runtime
of Appendix E on an in-memory store (no file, no fdatasync); "(a) δ + D"
is the bare chain. "(d) hand + D" is the hand-written program, no FMA,
keeping D natively with the emitted runtime's portable SHA-256.

**Parity.** For every program the head hash of (a) equals the `--trace`
head of (c), of the table-hex variant and of (d) + D, and the last state
of (d) (with and without FMA) hashes to the state hash of (b): every
configuration did the same work to the same state. (With FMA the float
programs reached the same last state on these streams; FMA does not
always round like two operations, which is why RCE forbids it.)

## Ratios (CPU), against the claimed 10x to 100x

| factor | arithmetic | collection | float | state | range over programs |
|---|---|---|---|---|---|
| log D in the checker, (a) chain / (b) | 2.55 | 1.29 | 5.34 | 3.58 | 1.25 to 7.04 |
| log D in the host, (a) host / (b) | 3.37 | 1.36 | 7.40 | 5.04 | 1.31 to 10.57 |
| log D in emitted code, (c) + D / (c) | 5.35 | 2.32 | 11.41 | 10.19 | 1.63 to 13.18 |
| log D in native code, (d) + D / (d) no FMA | 2,107 | 332 | 1,413 | 1,904 | 45 to 3,583 |
| float rule, (d) no FMA / (d) FMA | 0.98 | 1.01 | 0.85 | 0.90 | 0.65 to 1.06 |
| emitted / hand, (c) / (d) FMA | 1,202 | 444 | 196 | 199 | 59 to 1,699 |
| emitted + D / hand, (c) + D / (d) FMA | 4,671 | 1,032 | 1,980 | 2,241 | 170 to 6,576 |

Class medians; the native and hand rows have 6 programs (2 arithmetic, 1
collection, 2 float, 1 state), the others 11. Per-program ratios are in
`tables.md`.

## What the run says about the claim

**As stated, the claim does not hold for the parts of determinism it
names; it is both too high and too low, depending on what the step is
compared with.**

1. **The float rules cost nothing measurable.** Forbidding FMA (two
   roundings instead of one) changed the hand-written step time by 0.65x
   (arm) and 1.06x (fir), the two baselines with a multiply-add; on the
   other four baselines the two builds are the same code and differ by
   noise (0.90x to 1.01x). No class is near 10x. The no-FMA part of
   the critique is not supported on this machine.
2. **The log D costs 1.3x to 10.6x in the reference interpreter and host
   (median 2.6x bare chain, 3.4x host), and 1.6x to 13x in the emitted
   Rust (median 5.4x).** Below 10x for every class in the checker; in the
   emitted code the float and state classes sit at the bottom of the
   claimed range (class medians 11.4x and 10.2x), arithmetic and
   collection below it. The share is smallest where the step does real
   work (maps, loops: 1.3x) and largest where the step is one operation on
   a tiny state (a float add or a flag flip: 5x to 13x).
3. **Against hand-written native code the gap is far above 100x, and most
   of it is not determinism.** The emitted step without the log is 59x to
   1,699x the hand-written one (0.6 to 168 ns per step natively against
   0.34 to 25 µs emitted). The float rule is about 1x of that, and the log
   is excluded from this ratio, so the gap is the emitted code's
   representation: one dynamic value type for every value (`V` with i128
   integers and type tags as strings), the state as a vector of named
   pairs cloned per step, fuel counted per operation and checked
   arithmetic. That is critique 9 (non-idiomatic emitted code), measured
   here, not critique 7.
4. **Hashing the whole state every step is the cost that would dominate a
   native implementation.** Keeping D natively, with the same portable
   SHA-256 the emitted runtime uses, makes a hand-written step 45x (fir,
   whose step does 46 float operations and 30 divisions) to 3,583x (bank,
   one add) slower: two SHA-256 and the JSON of the state cost 2 to 13 µs,
   against a step of 1 to 170 ns. For small native steps the claim
   *understates* the cost of per-step full-state hashing; for the
   interpreted and emitted code that RCE runs today it overstates it.

**Dominant cost.** In the reference host (share of the host's step):
the interpreter's δ for loop and collection programs (automaton,
inventory, rcedb, fir, cart: 33% to 77%); SHA-256 and its hex for the
small-state programs (bank, ring, elevator, lexer: 30% to 38%); the
canonical JSON of floats for the float programs (arm, floatvec: 36% to
37%); host bookkeeping is 4% to 33%. In native code: the two SHA-256 and
the state's JSON per step.

## Energy (estimate only)

`est_j` = CPU seconds x 10 W, the estimate of the RCE paper (section
6.3). It is an estimate, not a measurement: no meter and no RAPL reading
were taken. Per million steps: the reference host 70 J (bank) to 1,366 J
(inventory); the same without the log 11 J to 1,047 J; emitted code with
the log 38 J to 496 J, without it 3.4 J to 252 J; hand-written Rust 0.006 J
to 1.6 J, and with the native log 22 J to 132 J. Every row is in
`tables.md`. Because the estimate is CPU time times a constant, its ratios
are the CPU ratios above and say nothing more.

## Speed-ups that keep D's bytes (recommendations)

These leave every hash and every byte of D unchanged, so they change no
semantics.

- **Hex from a table in `d_sha`.** `interp::d_sha` writes the digest with
  one `format!("{b:02x}")` per byte. The `chainfast` configuration writes
  the same 64 characters from a table: 0.57x to 0.97x of the chain's time
  (bank 4,880 to 2,838 ns, elevator 5,240 to 2,986 ns), same head hash on
  every program. The log's cost over δ in the checker falls from 4.25x to
  2.47x on bank.
- **Do not rebuild the event to hash it in the host.** `host::Entry::new`
  calls `hashed_event`, which parses the stored event JSON, builds a fresh
  `Interp::new(m)`, reconstructs the event and re-embeds it, although
  `Host::apply` already holds the event value; `apply` also clones the
  whole state before every input. Host bookkeeping is 24% to 33% of the
  host's step on the small-state programs. Passing the positional event
  from `apply` keeps the bytes. (Read from the code; the share is
  measured, the split inside it is not.)
- **SHA instructions in the emitted runtime.** The emitted Rust uses a
  portable SHA-256 that allocates per message and formats each word with
  `format!`; the CPU here has SHA instructions, which the checker's `sha2`
  crate uses. `std::arch` with runtime detection gives the same digest.
- **Hash at checkpoints, not every step: a specification change, not a
  speed-up.** D as specified hashes the state at every entry. The
  `ckpt64` configuration (state hash every 64th entry, the event chain
  every entry) took 0.75x to 0.98x of the chain's time in the checker,
  where δ and the JSON dominate (it still encodes the state every step, so
  it prices the SHA only). Against native code this is where the large
  factor is (item 4 above). It changes D, so it belongs with the open
  proposal HS-12 (checkpoints, `rcedb-host-contract.md`), and is listed
  here as evidence for it, not as a change.

## Found on the way: emitted Rust wrote one float differently in D

The pilot run found that the emitted Rust's `--trace` state hash differed
from the reference on `spec/examples/57_float_vectors.rce` for the event
`F32Mul(a: -14.6982, b: -54.3606)`. The product, 799.00299072265625, is an
exact tie between two shortest decimals; 6.1.1 rule 3 takes the even one
(799.0029907226562) and the reference does, but the emitted runtime's
`float_json` took Rust's `{:e}`, which takes the odd one (...563). The
emitted `show` already used the tie-to-even digits, so only the D hash
differed. Fixed in rce `8f9c7b05` (the emitted `float_json` now uses
`shortest_e`), with the test `rust_emitter_log_floats_tie_to_even`, before
the preregistration; the registered run shows equal heads on all 11
programs. The H8 parity run (`../determinism/`) did not see it because its
streams use only the examples' values.

## Limits

- One machine, shared with other jobs; CPU time is robust to that only in
  part (cache and frequency effects remain). Absolute numbers will move on
  another machine; the ratios are the result.
- One stream length (1,000) and bounded key spaces, so the growth of the
  per-step state hash with state size is not swept; a program with a
  large state pays the state's JSON and SHA-256 at every step.
- Five of the eleven programs have no hand-written baseline (ring, rcedb,
  cart, floatvec, lexer), so the native rows are over six programs.
- The emitted programs run through a benchmark-only `main` that reads the
  stream at start-up (an emitted 1,000-event example did not finish
  compiling within 6 minutes and used 3 GB); the step code is the
  emitter's.
- `fir_filter.rce` was written for this bench (from the kernels of
  `programs/science/numerics.rce`), as no existing state program does a
  float loop in its steps.
- No file store and no fdatasync are timed: durability is a cost of the
  host profile, not of determinism, and is not measured here.
