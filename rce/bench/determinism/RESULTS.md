# H8: determinism across machines (first recorded run, 2026-10-23)

Preregistered in `PREREG.json` (hash sidecar, committed at `c4a5db2` before
the run). The run is the "RCE replay-hash parity" workflow of
openIE-dev/rce on main at the merge of PR #8, commit
`94a93e4351c091518aeb91920ecec67dc2222b59`: run 39964276150
(https://github.com/openIE-dev/rce/actions/runs/39964276150). Each target
builds `rce` from that commit, runs `scripts/xarch-hashes.sh` (which runs
`scripts/xarch-streams.py` for the 15 stream lines, 700 streams each,
10,500 streams in all, seed `0x5eedd3ad0008`) and compares every line with
the golden set `scripts/xarch-hashes.x86_64-linux.txt` produced on the
x86_64 Linux reference.

The workflow had a sixth target the preregistration did not list, s390x
(big-endian, QEMU user mode); it is reported with the five.

| target | runner | job | parity step |
|---|---|---|---|
| linux-x86_64 | ubuntu-latest | 120449937523 | parity ok: 78 of 78 |
| linux-aarch64 | ubuntu-24.04-arm | 120449937056 | success (78 lines compared) |
| macos-aarch64 | macos-latest | 120449937197 | success (78 lines compared) |
| windows-x86_64 | windows-latest | 120449937118 | success (78 lines compared) |
| wasm32-wasip1 | wasmtime 50.0.0 on ubuntu-latest | 120449937165 | success (78 lines compared) |
| s390x-unknown-linux-gnu (qemu) | ubuntu-latest | 120449936750 | parity ok: 78 of 78 |

The parity step exits non-zero on any differing line, so "success" on a
target means every golden line, the 15 stream digests included, was
reproduced byte for byte; the two targets whose log line is quoted print
the count. The produced sets are the run's artefacts `xarch-<target>`
(3,781 to 3,799 bytes each; the s390x set is 16 bytes shorter because its
target name in the summary line differs, not its hashes).

**H8 as registered: supported at this scale.** 0 mismatching lines on all
six targets over 10,500 streams and the 63 pre-existing lines (the
example traces, the RCEdb host run, the chat application trace and the
crypto vectors): four instruction sets (x86_64, aarch64, s390x, wasm32),
three operating systems (Linux, macOS, Windows), both byte orders.

## Limits

- A stream's digest covers every step's event, state hash, previous hash,
  entry hash and outcome, so a single differing bit in any step of any
  stream on any target would change its program's line. The count of
  streams is therefore the count of chains compared, not of bytes
  inspected individually.
- The streams draw their payloads from the examples' own event instances
  (see `PREREG.json`, limits). Floats are exercised through
  `57_float_vectors` and `58_float_keys`, text through `56_utf8` and
  `52_context_text`, maps through `55_rcedb`; the boundary payloads that
  `rce dim` explores are not in this population. A wider population would
  be registered before its run.
- The golden set is produced on the reference machine and the other
  targets agree with it; the claim is agreement with one reference, which
  is what H8 states.
