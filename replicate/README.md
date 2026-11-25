# OpenIE Standalone 1-Command External Replication Kit (`replicate/`)

**License:** `Apache-2.0` (code & scripts) · **Dependencies:** `python3 >= 3.10` (`stdlib`-only; optional `cc` / `rustc` auto-detected)

`replicate/` is an **Independent Replication Harness** designed so any external researcher or lab can audit repository SHA-256 pre-commitments and run the three narrowest, self-contained empirical benchmarks in `openie-research-experiments` on their own hardware in a single command—comparing local measurements against OpenIE's **Self-Checked Reference Artifacts** (which are treated strictly as baseline claims to test, never self-certified as `"Verified"`).

---

## 1. Quickstart (1 Command, Native or Docker)

### Option A — Native Linux or macOS (`python3 >= 3.10`, zero `pip` packages)

From the repository root:

```bash
./replicate/run_replication.sh
```

Fast CI / laptop smoke mode (still runs `N = 30` batches on Suite 1 and `N = 50` trials on Suite 3):

```bash
./replicate/run_replication.sh --quick --out replicate/out
```

Force pure-Python execution without compiling optional C/Rust micro-kernels:

```bash
./replicate/run_replication.sh --skip-native
```

### Option B — Reproducible Unprivileged Docker Container

```bash
docker build -t openie-replicate -f replicate/Dockerfile . && docker run --rm openie-replicate
```

Extract the sanitized JSON and Markdown receipts from Docker onto your host:

```bash
mkdir -p ./replication-receipts
docker run --rm -v "$(pwd)/replication-receipts:/out" openie-replicate --out /out
```

---

## 2. What Each Suite Tests — and What It Does *Not* Test

| Suite | What It Tests Locally | What It Does *Not* Test |
|---|---|---|
| **0. Integrity Audit** | Verifies `CHECKSUMS.sha256` across the repository plus per-experiment `.sha256` preregistration locks, reporting exact `matched / total` digests. | Does not prove that pre-registrations were timestamped externally unless cross-checked against git history / OpenTimestamps in companion repos. |
| **1. `deterministic-null`** | Verifies `SPEC v0.4` `Q = 1_000_000` truncation-toward-zero arithmetic, deterministic `SHA-256` case-store pre-commitment, `N >= 30` seeded batches comparing `DNULLMM1` binary lookup + exact integer solver fallback (`0` neural FLOPs) against structured prompt UTF-8 serialization + tokenization overhead, and exact Clopper–Pearson 95% upper bounds on replay divergence (+ optional `C -O3` `DNULLMM1` slot-probe kernel). | Does **not** call live cloud or local LLMs (`Claude`, `GPT`, `Grok`, `Qwen`); does **not** re-evaluate multi-turn agentic task accuracy on `SWE-bench` or `TAU-bench` (see companion repo `openIE-dev/deterministic-null`). |
| **2. `rce-compile`** | Audits `rce-compile/` artifacts; tests **de Bruijn (1972)** lexical-index AST canonicalization across `120` alpha-renamed program pairs (`120/120` hits) and `200` test-vector-verified semantic mutants (`0/200` collisions vs `50/50` binding-swap false positives on naive AST identifier-stripping); measures live compile-once vs repeated runtime re-validation / `-O0 -> -O3` break-even `N*` (`1..10,000` invocations) on your CPU (`Python` + `cc` + `rustc`). | Does **not** compile the external `openIE-dev/rce` compiler binary itself or re-run the full 20-kernel × 15-tier multi-hour soak (`rce-compile/run_e4_energy_and_e5_scale.py`). |
| **3. `ai-reads-human`** | Audits `ai-reads-human-energy/SHA256SUMS`; reproduces the exact `20,000`-record `seed = 20261016` corpus (`<IdBI3B3B`, `23` B/record) and verifies bit-exact SHA-256 parity against `ai-reads-human-energy/summary.json`; runs `N = 50` interleaved trials comparing `struct.iter_unpack` vs `json.loads` (compact & pretty) plus a native `C (-O3)` `N = 50` micro-kernel. | Measures CPU/wire serialization and parsing overhead (`ns/record` and on-chip `reported_j` when readable), **not** downstream GPU transformer attention or KV-cache energy. |

---

## 3. Orthogonal 4-Class Energy Taxonomy (`measured_j ⊥ reported_j ⊥ est_j ⊥ unmetered`)

Energy classes are mutually orthogonal and are **never** mixed, scaled, or summed:

1. **`measured_j`:** External physical inline DC shunt (`INA238`/`INA3221`) or calibrated AC wall power analyzer. Never emitted by software-only runs (`measured_j: null`).
2. **`reported_j`:** Unprivileged OS/on-chip hardware energy counter—specifically `/sys/class/powercap/intel-rapl*` (Intel & AMD RAPL package/core domains) when readable without root on bare-metal Linux. Includes pre/post quiet-window idle power (`W`) and drift percentage.
3. **`est_j`:** Analytical byte-movement or instruction model estimate. Never emitted by this live benchmark harness (`est_j: null`).
4. **`unmetered` (`joules: null`):** Emitted automatically inside unprivileged Docker containers, VMs without powercap passthrough, or macOS without root. Reports exact `perf_counter_ns` wall-clock medians/IQRs, process `user + sys` CPU milliseconds, and wire byte ratios without fabricating joules.

---

## 4. Submitting an External Replication Receipt (Confirming or Falsifying)

 Output artifacts (`replicate/out/replication-report.json` and `replicate/out/replication-report.md`) are automatically scrubbed and checked by `assert_sanitized()` so **no hostnames, usernames, local home directories, or private IPs** appear in generated reports.

External replications—**especially runs where your CPU, OS governor, Python build, or compiler version disagrees with OpenIE's self-checked reference ranges**—are explicitly invited:

1. Run `./replicate/run_replication.sh` (native or Docker).
2. Inspect `replicate/out/replication-report.json` and `replicate/out/replication-report.md` to confirm zero private metadata.
3. Open an issue or pull request on [`openIE-dev/openie-research-experiments`](https://github.com/openIE-dev/openie-research-experiments) attaching both files and noting whether the run was bare-metal (`reported_j` / `unmetered`) or containerized (`unmetered`).

See [`reference-linux-x86_64-report.md`](./reference-linux-x86_64-report.md) for a sanitized Linux `x86_64` (`AMD Ryzen AI Max+ 395`, `RAPL` `reported_j`) reference run produced by `./replicate/run_replication.sh`.
