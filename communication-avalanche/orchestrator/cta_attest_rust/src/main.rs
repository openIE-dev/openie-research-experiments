use blake3::Hasher as Blake3Hasher;
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use rand::RngCore;
use rand::SeedableRng;
use rand_chacha::ChaCha20Rng;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashMap, VecDeque};
use std::env;
use std::fs;
use std::io::{self, BufRead, Write};
use std::path::Path;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering as AtomicOrdering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

// ============================================================================
// 1. Wrap-Safe Linux RAPL Telemetry & Thread-Wide OS Context Switches
// ============================================================================

#[derive(Clone, Copy, Debug, Default, Serialize)]
pub struct RaplRaw {
    pub pkg_uj: u64,
    pub core_uj: u64,
    pub psys_uj: u64,
    pub max_range_uj: u64,
}

fn read_u64_file(path: &str) -> Option<u64> {
    fs::read_to_string(path).ok()?.trim().parse::<u64>().ok()
}

pub fn read_rapl_raw() -> RaplRaw {
    let max_range_uj = read_u64_file("/sys/class/powercap/intel-rapl:0/max_energy_range_uj")
        .unwrap_or(262_143_328_850);
    let pkg_uj = read_u64_file("/sys/class/powercap/intel-rapl:0/energy_uj").unwrap_or(0);
    let core_uj = read_u64_file("/sys/class/powercap/intel-rapl:0:0/energy_uj").unwrap_or(0);
    let psys_uj = read_u64_file("/sys/class/powercap/intel-rapl:1/energy_uj").unwrap_or(0);
    RaplRaw {
        pkg_uj,
        core_uj,
        psys_uj,
        max_range_uj,
    }
}

pub struct RaplAccumulator {
    last: RaplRaw,
    pub pkg_total_uj: u128,
    pub core_total_uj: u128,
    pub psys_total_uj: u128,
    start_inst: Instant,
}

impl RaplAccumulator {
    pub fn start() -> Self {
        Self {
            last: read_rapl_raw(),
            pkg_total_uj: 0,
            core_total_uj: 0,
            psys_total_uj: 0,
            start_inst: Instant::now(),
        }
    }

    #[inline]
    fn delta_wrap(prev: u64, cur: u64, max_r: u64) -> u128 {
        if cur >= prev {
            (cur - prev) as u128
        } else if max_r > prev {
            (max_r - prev + cur) as u128
        } else {
            0
        }
    }

    pub fn sample(&mut self) {
        let cur = read_rapl_raw();
        let m = cur.max_range_uj;
        self.pkg_total_uj += Self::delta_wrap(self.last.pkg_uj, cur.pkg_uj, m);
        self.core_total_uj += Self::delta_wrap(self.last.core_uj, cur.core_uj, m);
        self.psys_total_uj += Self::delta_wrap(self.last.psys_uj, cur.psys_uj, m);
        self.last = cur;
    }

    pub fn finish(mut self) -> (f64, f64, f64, f64) {
        self.sample();
        let secs = self.start_inst.elapsed().as_secs_f64();
        (
            self.pkg_total_uj as f64 / 1e6,
            self.core_total_uj as f64 / 1e6,
            self.psys_total_uj as f64 / 1e6,
            secs,
        )
    }
}

/// Sums voluntary + nonvoluntary OS thread context switches across `/proc/self/task/*/status`.
pub fn read_all_thread_ctxt_switches() -> (u64, u64) {
    let mut vol = 0u64;
    let mut nonvol = 0u64;
    let task_dir = Path::new("/proc/self/task");
    if let Ok(entries) = fs::read_dir(task_dir) {
        for ent in entries.flatten() {
            let status_path = ent.path().join("status");
            if let Ok(txt) = fs::read_to_string(status_path) {
                for line in txt.lines() {
                    if let Some(rest) = line.strip_prefix("voluntary_ctxt_switches:") {
                        if let Ok(v) = rest.trim().parse::<u64>() {
                            vol += v;
                        }
                    } else if let Some(rest) = line.strip_prefix("nonvoluntary_ctxt_switches:") {
                        if let Ok(v) = rest.trim().parse::<u64>() {
                            nonvol += v;
                        }
                    }
                }
            }
        }
    }
    (vol, nonvol)
}

pub fn measure_idle_baseline(seconds: f64) -> Value {
    let mut acc = RaplAccumulator::start();
    let steps = ((seconds / 0.25).ceil() as usize).max(1);
    let step_dur = Duration::from_secs_f64(seconds / steps as f64);
    for _ in 0..steps {
        thread::sleep(step_dur);
        acc.sample();
    }
    let (pkg_j, core_j, psys_j, elapsed_s) = acc.finish();
    json!({
        "window_s": elapsed_s,
        "pkg_reported_j": pkg_j,
        "core_reported_j": core_j,
        "psys_reported_j": psys_j,
        "pkg_idle_w": pkg_j / elapsed_s,
        "core_idle_w": core_j / elapsed_s,
        "psys_idle_w": psys_j / elapsed_s,
    })
}

// ============================================================================
// 2. Cryptographic Channel Attestation (BLAKE3 256-bit + Ed25519 64-byte)
// ============================================================================

pub struct NodeKeyring {
    pub signing: HashMap<String, SigningKey>,
    pub verifying: HashMap<String, VerifyingKey>,
}

impl NodeKeyring {
    pub fn deterministic_standard() -> Self {
        let mut rng = ChaCha20Rng::seed_from_u64(0xC7A0_2026_0021);
        let mut signing = HashMap::new();
        let mut verifying = HashMap::new();
        let mut names: Vec<String> = (0..24).map(|i| format!("n{:02}", i)).collect();
        for named in [
            "source",
            "parse_kernel",
            "static_type_scope_kernel",
            "test_gen_kernel",
            "det_patch_kernel",
            "escalation_integrator",
            "llm_patch_proposer",
            "diff_verifier_kernel",
            "commit_gate",
            "parse_kernel_bak",
            "static_type_scope_bak",
            "test_gen_bak",
            "det_patch_bak",
            "llm_proposer_bak",
            "diff_verifier_bak",
            "rogue_adversary",
        ] {
            names.push(named.to_string());
        }
        for name in names {
            let mut secret = [0u8; 32];
            rng.fill_bytes(&mut secret);
            let sk = SigningKey::from_bytes(&secret);
            let vk = sk.verifying_key();
            signing.insert(name.clone(), sk);
            verifying.insert(name, vk);
        }
        Self { signing, verifying }
    }

    #[inline]
    fn canonical_signing_bytes(
        trace_id: &str,
        step_idx: u32,
        sender_id: &str,
        receiver_id: &str,
        channel_type: &str,
        payload_blake3: &[u8; 32],
    ) -> Vec<u8> {
        let mut buf = Vec::with_capacity(
            14 + trace_id.len() + sender_id.len() + receiver_id.len() + channel_type.len() + 40,
        );
        buf.extend_from_slice(b"CTA-ATTEST-V1\0");
        buf.extend_from_slice(&(trace_id.len() as u32).to_le_bytes());
        buf.extend_from_slice(trace_id.as_bytes());
        buf.extend_from_slice(&step_idx.to_le_bytes());
        buf.extend_from_slice(&(sender_id.len() as u32).to_le_bytes());
        buf.extend_from_slice(sender_id.as_bytes());
        buf.extend_from_slice(&(receiver_id.len() as u32).to_le_bytes());
        buf.extend_from_slice(receiver_id.as_bytes());
        buf.extend_from_slice(&(channel_type.len() as u32).to_le_bytes());
        buf.extend_from_slice(channel_type.as_bytes());
        buf.extend_from_slice(payload_blake3);
        buf
    }

    pub fn sign_envelope(
        &self,
        trace_id: &str,
        step_idx: u32,
        sender_id: &str,
        signer_key_id: &str,
        receiver_id: &str,
        channel_type: &str,
        payload: Vec<u8>,
    ) -> Result<AttestedEnvelope, String> {
        let sk = self
            .signing
            .get(signer_key_id)
            .ok_or_else(|| format!("unknown signer key {}", signer_key_id))?;
        let digest = blake3::hash(&payload);
        let digest_bytes = *digest.as_bytes();
        let msg = Self::canonical_signing_bytes(
            trace_id,
            step_idx,
            sender_id,
            receiver_id,
            channel_type,
            &digest_bytes,
        );
        let sig: Signature = sk.sign(&msg);
        Ok(AttestedEnvelope {
            trace_id: trace_id.to_string(),
            step_idx,
            sender_id: sender_id.to_string(),
            receiver_id: receiver_id.to_string(),
            channel_type: channel_type.to_string(),
            payload_blake3: digest_bytes,
            ed25519_sig: sig.to_bytes(),
            payload,
        })
    }

    pub fn verify_envelope(&self, env: &AttestedEnvelope, check_json_frame: bool) -> Result<(), &'static str> {
        let vk = self
            .verifying
            .get(&env.sender_id)
            .ok_or("unknown_sender_id")?;
        // 1. Constant-time BLAKE3 digest equality (blake3::Hash PartialEq uses subtle::ConstantTimeEq)
        let actual_hash = blake3::hash(&env.payload);
        let claimed_hash = blake3::Hash::from_bytes(env.payload_blake3);
        if actual_hash != claimed_hash {
            return Err("blake3_digest_mismatch");
        }
        // 2. Strict RFC 8032 Ed25519 verification
        let sig = Signature::from_bytes(&env.ed25519_sig);
        let msg = Self::canonical_signing_bytes(
            &env.trace_id,
            env.step_idx,
            &env.sender_id,
            &env.receiver_id,
            &env.channel_type,
            &env.payload_blake3,
        );
        vk.verify_strict(&msg, &sig)
            .map_err(|_| "ed25519_signature_invalid")?;
        // 3. Optional typed JSON/AST frame completeness check
        if check_json_frame {
            let v: Value = serde_json::from_slice(&env.payload).map_err(|_| "truncated_or_malformed_json_frame")?;
            let obj = v.as_object().ok_or("frame_not_object")?;
            if !obj.contains_key("kind") || !obj.contains_key("ast_ok") {
                return Err("missing_typed_channel_fields");
            }
        }
        Ok(())
    }
}

#[derive(Clone, Debug)]
pub struct AttestedEnvelope {
    pub trace_id: String,
    pub step_idx: u32,
    pub sender_id: String,
    pub receiver_id: String,
    pub channel_type: String,
    pub payload_blake3: [u8; 32],
    pub ed25519_sig: [u8; 64],
    pub payload: Vec<u8>,
}

fn hex_encode(bytes: &[u8]) -> String {
    let mut s = String::with_capacity(bytes.len() * 2);
    for b in bytes {
        use std::fmt::Write as _;
        let _ = write!(&mut s, "{:02x}", b);
    }
    s
}

// ============================================================================
// 3. Exact Successive Shortest Path (SSP) Min-Cost Flow Scheduler
//    (Bellman-Ford Initial Potentials + Johnson Reduced-Cost Dijkstra)
// ============================================================================

#[derive(Clone, Debug)]
struct FlowEdge {
    to: usize,
    rev: usize,
    cap: i64,
    flow: i64,
    cost: i64, // microjoule-scaled integer cost weight from cost_lut.json
    edge_id: String,
}

pub struct MinCostFlowScheduler {
    pub node_names: Vec<String>,
    pub name_to_idx: HashMap<String, usize>,
    adj: Vec<Vec<FlowEdge>>,
}

#[derive(Clone, Eq, PartialEq)]
struct DijkState {
    dist: i64,
    u: usize,
}

impl Ord for DijkState {
    fn cmp(&self, other: &Self) -> Ordering {
        other.dist.cmp(&self.dist).then_with(|| self.u.cmp(&other.u))
    }
}
impl PartialOrd for DijkState {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

impl MinCostFlowScheduler {
    pub fn new(nodes: Vec<String>) -> Self {
        let mut name_to_idx = HashMap::new();
        for (i, n) in nodes.iter().enumerate() {
            name_to_idx.insert(n.clone(), i);
        }
        let n = nodes.len();
        Self {
            node_names: nodes,
            name_to_idx,
            adj: vec![Vec::new(); n],
        }
    }

    pub fn add_edge(&mut self, from: &str, to: &str, cap: i64, cost: i64, edge_id: &str) {
        let u = self.name_to_idx[from];
        let v = self.name_to_idx[to];
        let u_rev = self.adj[v].len();
        let v_rev = self.adj[u].len();
        self.adj[u].push(FlowEdge {
            to: v,
            rev: u_rev,
            cap,
            flow: 0,
            cost,
            edge_id: edge_id.to_string(),
        });
        self.adj[v].push(FlowEdge {
            to: u,
            rev: v_rev,
            cap: 0,
            flow: 0,
            cost: -cost,
            edge_id: format!("{}_rev", edge_id),
        });
    }

    pub fn solve_ssp(
        &self,
        source: &str,
        sink: &str,
        demand: i64,
        disabled_nodes: &[String],
    ) -> (i64, i64, Vec<Value>, u64) {
        let t0 = Instant::now();
        let n = self.node_names.len();
        let s = self.name_to_idx[source];
        let t = self.name_to_idx[sink];
        let mut disabled = vec![false; n];
        for dn in disabled_nodes {
            if let Some(&idx) = self.name_to_idx.get(dn) {
                if idx != s && idx != t {
                    disabled[idx] = true;
                }
            }
        }
        let mut adj = self.adj.clone();
        let inf: i64 = i64::MAX / 4;

        // Step 1: Bellman-Ford initial potentials for general non-negative/signed DAG weights
        let mut pi = vec![inf; n];
        pi[s] = 0;
        for _ in 0..n {
            let mut changed = false;
            for u in 0..n {
                if disabled[u] || pi[u] >= inf {
                    continue;
                }
                for e in &adj[u] {
                    if e.cap - e.flow > 0 && !disabled[e.to] {
                        let nd = pi[u] + e.cost;
                        if nd < pi[e.to] {
                            pi[e.to] = nd;
                            changed = true;
                        }
                    }
                }
            }
            if !changed {
                break;
            }
        }

        let mut total_flow = 0i64;
        let mut total_cost = 0i64;

        // Step 2: Successive Shortest Path with Johnson potential updates
        while total_flow < demand {
            let mut dist = vec![inf; n];
            let mut prev_u = vec![usize::MAX; n];
            let mut prev_e = vec![usize::MAX; n];
            dist[s] = 0;
            let mut pq = BinaryHeap::new();
            pq.push(DijkState { dist: 0, u: s });

            while let Some(DijkState { dist: d, u }) = pq.pop() {
                if d != dist[u] {
                    continue;
                }
                for (ei, e) in adj[u].iter().enumerate() {
                    if e.cap - e.flow <= 0 || disabled[e.to] {
                        continue;
                    }
                    let rcost = e.cost + pi[u] - pi[e.to];
                    let nd = d + rcost.max(0);
                    if nd < dist[e.to] {
                        dist[e.to] = nd;
                        prev_u[e.to] = u;
                        prev_e[e.to] = ei;
                        pq.push(DijkState { dist: nd, u: e.to });
                    }
                }
            }

            if dist[t] >= inf {
                break;
            }
            for v in 0..n {
                if dist[v] < inf && pi[v] < inf {
                    pi[v] += dist[v];
                }
            }

            let mut add_f = demand - total_flow;
            let mut cur = t;
            while cur != s {
                let pu = prev_u[cur];
                let pe = prev_e[cur];
                let rem = adj[pu][pe].cap - adj[pu][pe].flow;
                if rem < add_f {
                    add_f = rem;
                }
                cur = pu;
            }

            cur = t;
            while cur != s {
                let pu = prev_u[cur];
                let pe = prev_e[cur];
                let rev_idx = adj[pu][pe].rev;
                let edge_cost = adj[pu][pe].cost;
                adj[pu][pe].flow += add_f;
                adj[cur][rev_idx].flow -= add_f;
                total_cost += add_f * edge_cost;
                cur = pu;
            }
            total_flow += add_f;
        }

        let elapsed_ns = t0.elapsed().as_nanos() as u64;
        let mut active_edges = Vec::new();
        for u in 0..n {
            for e in &adj[u] {
                if e.cap > 0 && e.flow > 0 {
                    active_edges.push(json!({
                        "edge_id": e.edge_id,
                        "from": self.node_names[u],
                        "to": self.node_names[e.to],
                        "flow": e.flow,
                        "unit_cost": e.cost,
                    }));
                }
            }
        }
        (total_flow, total_cost, active_edges, elapsed_ns)
    }
}

// ============================================================================
// 4. Subcommand `bench-crypto`: Constant-Time BLAKE3 + Ed25519 RAPL Benchmark
// ============================================================================

fn percentile_u64(sorted: &[u64], p: f64) -> u64 {
    if sorted.is_empty() {
        return 0;
    }
    let idx = ((sorted.len() - 1) as f64 * p).round() as usize;
    sorted[idx.min(sorted.len() - 1)]
}

fn percentile_f64(sorted: &[f64], p: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let idx = ((sorted.len() - 1) as f64 * p).round() as usize;
    sorted[idx.min(sorted.len() - 1)]
}

fn run_bench_crypto(iters: usize) -> Value {
    let keyring = NodeKeyring::deterministic_standard();
    let sizes: [usize; 4] = [64, 1024, 16_384, 65_536];
    let mut rng = ChaCha20Rng::seed_from_u64(0xBEEF_2026);
    let mut results = Vec::new();

    for &sz in &sizes {
        let mut payload = vec![0u8; sz];
        rng.fill_bytes(&mut payload);

        // Warmup
        for i in 0..500 {
            let env = keyring
                .sign_envelope("warmup", i as u32, "n00", "n00", "n01", "raw", payload.clone())
                .unwrap();
            keyring.verify_envelope(&env, false).unwrap();
        }

        // Benchmark Sign + BLAKE3
        let mut sign_ns = Vec::with_capacity(iters);
        let mut last_env = None;
        let mut rapl_sign = RaplAccumulator::start();
        for i in 0..iters {
            if i % 4096 == 0 {
                rapl_sign.sample();
            }
            let t0 = Instant::now();
            let env = keyring
                .sign_envelope("bench", i as u32, "n00", "n00", "n01", "raw", payload.clone())
                .unwrap();
            sign_ns.push(t0.elapsed().as_nanos() as u64);
            last_env = Some(std::hint::black_box(env));
        }
        let (sign_pkg_j, sign_core_j, sign_psys_j, _) = rapl_sign.finish();
        sign_ns.sort_unstable();

        // Benchmark Verify + BLAKE3
        let env_ref = last_env.unwrap();
        let mut verify_ns = Vec::with_capacity(iters);
        let mut rapl_ver = RaplAccumulator::start();
        let mut ok_cnt = 0usize;
        for i in 0..iters {
            if i % 4096 == 0 {
                rapl_ver.sample();
            }
            let t0 = Instant::now();
            if keyring.verify_envelope(std::hint::black_box(&env_ref), false).is_ok() {
                ok_cnt += 1;
            }
            verify_ns.push(t0.elapsed().as_nanos() as u64);
        }
        let (ver_pkg_j, ver_core_j, ver_psys_j, _) = rapl_ver.finish();
        verify_ns.sort_unstable();

        let mean_sign_ns = sign_ns.iter().sum::<u64>() as f64 / iters as f64;
        let mean_ver_ns = verify_ns.iter().sum::<u64>() as f64 / iters as f64;

        results.push(json!({
            "payload_bytes": sz,
            "iterations": iters,
            "verified_ok": ok_cnt,
            "sign_mean_ns": mean_sign_ns,
            "sign_p50_ns": percentile_u64(&sign_ns, 0.50),
            "sign_p99_ns": percentile_u64(&sign_ns, 0.99),
            "sign_pkg_uj_per_op": (sign_pkg_j * 1e6) / iters as f64,
            "sign_core_uj_per_op": (sign_core_j * 1e6) / iters as f64,
            "sign_psys_uj_per_op": (sign_psys_j * 1e6) / iters as f64,
            "verify_mean_ns": mean_ver_ns,
            "verify_p50_ns": percentile_u64(&verify_ns, 0.50),
            "verify_p99_ns": percentile_u64(&verify_ns, 0.99),
            "verify_pkg_uj_per_op": (ver_pkg_j * 1e6) / iters as f64,
            "verify_core_uj_per_op": (ver_core_j * 1e6) / iters as f64,
            "verify_psys_uj_per_op": (ver_psys_j * 1e6) / iters as f64,
        }));
    }

    json!({
        "benchmark": "cta_crypto_attestation_blake3_ed25519",
        "board_metered": false,
        "measured_j": Value::Null,
        "buckets": results,
    })
}

// ============================================================================
// 5. Subcommand `bench-e1`: 16-Node Heterogeneous Orchestration DAG
//    Zero-Clock Event-Driven Threshold Firing (eventfd) vs. 10/100/1000 Hz Polling
// ============================================================================

#[derive(Clone)]
struct DagOutEdge {
    target: usize,
    weight_milli: u64, // 1000 = 1.0 threshold unit
}

struct NodeChannelState {
    inbox: VecDeque<(AttestedEnvelope, Instant)>,
    potential_milli: u64,
    threshold_milli: u64,
    heartbeat_seq: u64,
}

#[cfg(target_os = "linux")]
fn create_eventfd() -> i32 {
    unsafe { libc::eventfd(0, libc::EFD_CLOEXEC) }
}

#[cfg(not(target_os = "linux"))]
fn create_eventfd() -> i32 {
    -1
}

#[cfg(target_os = "linux")]
fn signal_eventfd(fd: i32) {
    if fd >= 0 {
        let val: u64 = 1;
        unsafe {
            let _ = libc::write(fd, &val as *const u64 as *const libc::c_void, 8);
        }
    }
}

#[cfg(not(target_os = "linux"))]
fn signal_eventfd(_fd: i32) {}

#[cfg(target_os = "linux")]
fn wait_eventfd(fd: i32) {
    if fd >= 0 {
        let mut val: u64 = 0;
        unsafe {
            let _ = libc::read(fd, &mut val as *mut u64 as *mut libc::c_void, 8);
        }
    }
}

#[cfg(not(target_os = "linux"))]
fn wait_eventfd(_fd: i32) {
    thread::sleep(Duration::from_micros(200));
}

#[cfg(target_os = "linux")]
fn close_eventfd(fd: i32) {
    if fd >= 0 {
        unsafe {
            let _ = libc::close(fd);
        }
    }
}

#[cfg(not(target_os = "linux"))]
fn close_eventfd(_fd: i32) {}

fn build_16_node_dag() -> (Vec<Vec<DagOutEdge>>, Vec<u64>, Vec<u32>) {
    // 16 nodes (n00..n15) across 5 heterogeneous layers:
    // L0: n00 -> (n01, n02)
    // L1: (n01, n02) -> each contributes 0.5 to n03, n04, n05, n06 (fires ONLY when both arrive: V >= 1.0)
    // L2: (n03..n06) -> each contributes 0.25 to n07, n08, n09 (fires ONLY when all 4 static checks arrive: V >= 1.0)
    // L3: (n07..n09) -> each contributes 0.34 to n10, n11 (fires when all 3 test-gen outputs arrive: V >= 1.02 >= 1.0)
    //     (n10, n11) -> each contributes 0.50 to n12 (escalation integrator)
    //     n12 -> n13 (targeted local proposer kernel) -> n14 (diff verifier)
    // L4: n14 -> n15 (commit gate)
    let mut adj = vec![Vec::new(); 16];
    let thresholds = vec![1000u64; 16];
    // Per-node deterministic kernel compute iterations (calibrated ~28 us/node -> ~0.45 ms total CPU work/burst)
    let kernel_work: Vec<u32> = vec![
        180, 260, 340, // n00..n02 ingress/lex/parse
        280, 320, 260, 220, // n03..n06 scope/types/cfg/purity
        240, 280, 300, // n07..n09 spec/boundary/prop
        360, 360, 180, 520, // n10..n13 det_syntax/det_scope/esc/proposer
        420, 180, // n14..n15 diff_verifier/commit_gate
    ];

    adj[0].push(DagOutEdge { target: 1, weight_milli: 1000 });
    adj[0].push(DagOutEdge { target: 2, weight_milli: 1000 });

    for u in 1..=2 {
        for v in 3..=6 {
            adj[u].push(DagOutEdge { target: v, weight_milli: 500 });
        }
    }
    for u in 3..=6 {
        for v in 7..=9 {
            adj[u].push(DagOutEdge { target: v, weight_milli: 250 });
        }
    }
    for u in 7..=9 {
        for v in 10..=11 {
            adj[u].push(DagOutEdge { target: v, weight_milli: 340 });
        }
    }
    adj[10].push(DagOutEdge { target: 12, weight_milli: 500 });
    adj[11].push(DagOutEdge { target: 12, weight_milli: 500 });
    adj[12].push(DagOutEdge { target: 13, weight_milli: 1000 });
    adj[13].push(DagOutEdge { target: 14, weight_milli: 1000 });
    adj[14].push(DagOutEdge { target: 15, weight_milli: 1000 });

    (adj, thresholds, kernel_work)
}

fn run_single_e1_window(
    regime: &str,
    duty_cycle: f64,
    window_s: f64,
    rep: usize,
    keyring: &Arc<NodeKeyring>,
) -> Value {
    let (adj, thresholds, kernel_work) = build_16_node_dag();
    let adj = Arc::new(adj);
    let kernel_work = Arc::new(kernel_work);

    let is_event_driven = regime == "event_threshold";
    let poll_period = match regime {
        "poll_10hz" => Duration::from_millis(100),
        "poll_100hz" => Duration::from_millis(10),
        "poll_1000hz" => Duration::from_millis(1),
        _ => Duration::from_millis(0),
    };

    let mut states = Vec::with_capacity(16);
    let mut efds = Vec::with_capacity(16);
    for u in 0..16 {
        states.push(Mutex::new(NodeChannelState {
            inbox: VecDeque::with_capacity(64),
            potential_milli: 0,
            threshold_milli: thresholds[u],
            heartbeat_seq: 0,
        }));
        efds.push(if is_event_driven { create_eventfd() } else { -1 });
    }
    let states = Arc::new(states);
    let efds = Arc::new(efds);

    let stop_flag = Arc::new(AtomicBool::new(false));
    let total_wakeups = Arc::new(AtomicU64::new(0));
    let empty_poll_wakeups = Arc::new(AtomicU64::new(0));
    let total_edge_verifies = Arc::new(AtomicU64::new(0));
    let active_kernel_ns = Arc::new(AtomicU64::new(0));
    let commit_latencies_ns: Arc<Mutex<Vec<u64>>> = Arc::new(Mutex::new(Vec::with_capacity(4096)));

    // Precompute SSP initial min-cost topology schedule ONCE at epoch 0 (0 per-tick overhead!)
    let mut ssp = MinCostFlowScheduler::new((0..16).map(|i| format!("n{:02}", i)).collect());
    for u in 0..16 {
        for e in &adj[u] {
            ssp.add_edge(
                &format!("n{:02}", u),
                &format!("n{:02}", e.target),
                100,
                (kernel_work[e.target] as i64) * 10,
                &format!("e_{:02}_{:02}", u, e.target),
            );
        }
    }
    let (_flow, _cost, _edges, ssp_init_ns) = ssp.solve_ssp("n00", "n15", 1, &[]);

    let mut handles = Vec::with_capacity(16);
    for u in 0..16 {
        let states_c = Arc::clone(&states);
        let efds_c = Arc::clone(&efds);
        let adj_c = Arc::clone(&adj);
        let kw_c = Arc::clone(&kernel_work);
        let keyring_c = Arc::clone(keyring);
        let stop_c = Arc::clone(&stop_flag);
        let wake_c = Arc::clone(&total_wakeups);
        let empty_c = Arc::clone(&empty_poll_wakeups);
        let ver_c = Arc::clone(&total_edge_verifies);
        let act_ns_c = Arc::clone(&active_kernel_ns);
        let lats_c = Arc::clone(&commit_latencies_ns);

        handles.push(thread::spawn(move || {
            let my_name = format!("n{:02}", u);
            let mut poll_scratch = [0u8; 512];
            loop {
                if is_event_driven {
                    wait_eventfd(efds_c[u]);
                } else {
                    thread::sleep(poll_period);
                }
                wake_c.fetch_add(1, AtomicOrdering::Relaxed);

                if !is_event_driven {
                    // Clocked polling regime: daemon scans incident channel status table & computes
                    // readiness digest on every clock tick before checking local threshold
                    let mut hb_acc = 0u64;
                    for peer in 0..16 {
                        if let Ok(g) = states_c[peer].try_lock() {
                            hb_acc = hb_acc.wrapping_add(g.heartbeat_seq ^ (g.potential_milli << 3));
                        }
                    }
                    poll_scratch[0..8].copy_from_slice(&hb_acc.to_le_bytes());
                    let poll_digest = blake3::hash(&poll_scratch);
                    std::hint::black_box(poll_digest);
                }

                // Drain all ready firings where V_u >= theta_u
                let mut fired_any = false;
                loop {
                    let batch: Option<Vec<(AttestedEnvelope, Instant)>> = {
                        let mut st = states_c[u].lock().unwrap();
                        st.heartbeat_seq = st.heartbeat_seq.wrapping_add(1);
                        if st.potential_milli >= st.threshold_milli && !st.inbox.is_empty() {
                            st.potential_milli -= st.threshold_milli;
                            // Pop the required upstream messages for one firing
                            let needed = match u {
                                0 | 1 | 2 | 13 | 14 | 15 => 1,
                                3..=6 | 12 => 2,
                                10 | 11 => 3,
                                7..=9 => 4,
                                _ => 1,
                            };
                            let mut items = Vec::with_capacity(needed);
                            for _ in 0..needed {
                                if let Some(it) = st.inbox.pop_front() {
                                    items.push(it);
                                }
                            }
                            Some(items)
                        } else {
                            None
                        }
                    };

                    let Some(items) = batch else {
                        break;
                    };
                    if items.is_empty() {
                        break;
                    }
                    fired_any = true;
                    let t_work = Instant::now();
                    let origin_t0 = items[0].1;

                    // Verify every incoming attested channel envelope
                    let mut state_mix = Blake3Hasher::new();
                    for (env, _) in &items {
                        let _ = keyring_c.verify_envelope(env, false);
                        ver_c.fetch_add(1, AtomicOrdering::Relaxed);
                        state_mix.update(&env.payload_blake3);
                    }

                    // Execute deterministic kernel work proportional to node profile
                    let rounds = kw_c[u];
                    let mut digest = state_mix.finalize();
                    for r in 0..rounds {
                        let mut h = Blake3Hasher::new();
                        h.update(digest.as_bytes());
                        h.update(&r.to_le_bytes());
                        digest = h.finalize();
                    }
                    let out_payload = digest.as_bytes().to_vec();

                    if u == 15 {
                        // Commit gate reached: record burst end-to-end latency
                        let lat = origin_t0.elapsed().as_nanos() as u64;
                        lats_c.lock().unwrap().push(lat);
                    } else {
                        // Emit attested envelopes along outgoing edges & integrate target potentials
                        for edge in &adj_c[u] {
                            let target_name = format!("n{:02}", edge.target);
                            let out_env = keyring_c
                                .sign_envelope(
                                    &items[0].0.trace_id,
                                    items[0].0.step_idx + 1,
                                    &my_name,
                                    &my_name,
                                    &target_name,
                                    "dag_signal",
                                    out_payload.clone(),
                                )
                                .unwrap();
                            let should_wake = {
                                let mut tst = states_c[edge.target].lock().unwrap();
                                let prev_v = tst.potential_milli;
                                tst.inbox.push_back((out_env, origin_t0));
                                tst.potential_milli += edge.weight_milli;
                                is_event_driven
                                    && prev_v < tst.threshold_milli
                                    && tst.potential_milli >= tst.threshold_milli
                            };
                            if should_wake {
                                signal_eventfd(efds_c[edge.target]);
                            }
                        }
                    }

                    act_ns_c.fetch_add(t_work.elapsed().as_nanos() as u64, AtomicOrdering::Relaxed);
                }

                if !fired_any && !is_event_driven {
                    empty_c.fetch_add(1, AtomicOrdering::Relaxed);
                }

                if stop_c.load(AtomicOrdering::Relaxed) {
                    break;
                }
            }
        }));
    }

    // Allow worker threads to settle into blocked eventfd / sleep state before window starts
    thread::sleep(Duration::from_millis(60));

    // Calibrated bursty arrival schedule:
    // Each 4-event micro-burst uses ~2.2 ms of aggregate CPU work across the 16 threads.
    // Over 10.0 s:
    //   duty 0.01 ->  50 events (12.5 micro-bursts)
    //   duty 0.05 -> 250 events (62.5 micro-bursts)
    //   duty 0.20 -> 1000 events (250 micro-bursts)
    let total_events = ((duty_cycle * 5000.0 * (window_s / 10.0)).round() as usize).max(4);
    let micro_burst_size = 4usize;
    let num_bursts = (total_events + micro_burst_size - 1) / micro_burst_size;
    let mut rng = ChaCha20Rng::seed_from_u64(0xE100_0000 + (rep as u64) * 97 + (duty_cycle * 1000.0) as u64);

    // Pre-generate arrival offsets in [0.05s, window_s - 0.35s] so all bursts drain inside window
    let usable_s = (window_s - 0.40).max(0.5);
    let mut burst_offsets_s = Vec::with_capacity(num_bursts);
    for b in 0..num_bursts {
        let base = (b as f64 + 0.5) / (num_bursts as f64) * usable_s;
        let jitter = ((rng.next_u32() as f64 / u32::MAX as f64) - 0.5) * (usable_s / num_bursts as f64) * 0.6;
        burst_offsets_s.push(0.05 + (base + jitter).clamp(0.0, usable_s));
    }
    burst_offsets_s.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let (vol_pre, nonvol_pre) = read_all_thread_ctxt_switches();
    let wake_pre = total_wakeups.load(AtomicOrdering::Relaxed);
    let empty_pre = empty_poll_wakeups.load(AtomicOrdering::Relaxed);
    let mut rapl = RaplAccumulator::start();
    let win_start = Instant::now();

    let mut next_burst_idx = 0usize;
    let mut sent_events = 0usize;
    let mut next_rapl_sample = Duration::from_millis(200);

    while win_start.elapsed().as_secs_f64() < window_s {
        let elapsed = win_start.elapsed();
        if elapsed >= next_rapl_sample {
            rapl.sample();
            next_rapl_sample += Duration::from_millis(200);
        }

        if next_burst_idx < burst_offsets_s.len() {
            let target_t = Duration::from_secs_f64(burst_offsets_s[next_burst_idx]);
            if elapsed >= target_t {
                let k = micro_burst_size.min(total_events - sent_events);
                for j in 0..k {
                    let eid = sent_events + j;
                    let trace_id = format!("e1_{}_r{}_{}", regime, rep, eid);
                    let init_env = keyring
                        .sign_envelope(
                            &trace_id,
                            0,
                            "source",
                            "source",
                            "n00",
                            "ingress_event",
                            trace_id.as_bytes().to_vec(),
                        )
                        .unwrap();
                    let t_inject = Instant::now();
                    let should_wake = {
                        let mut st0 = states[0].lock().unwrap();
                        let pv = st0.potential_milli;
                        st0.inbox.push_back((init_env, t_inject));
                        st0.potential_milli += 1000;
                        is_event_driven && pv < st0.threshold_milli && st0.potential_milli >= st0.threshold_milli
                    };
                    if should_wake {
                        signal_eventfd(efds[0]);
                    }
                }
                sent_events += k;
                next_burst_idx += 1;
                continue;
            } else {
                let wait_rem = (target_t - elapsed).min(Duration::from_millis(50));
                thread::sleep(wait_rem);
            }
        } else {
            let rem = Duration::from_secs_f64(window_s).saturating_sub(elapsed);
            if rem.is_zero() {
                break;
            }
            thread::sleep(rem.min(Duration::from_millis(50)));
        }
    }

    let (pkg_j, core_j, psys_j, actual_s) = rapl.finish();
    let (vol_post, nonvol_post) = read_all_thread_ctxt_switches();
    let wake_delta = total_wakeups.load(AtomicOrdering::Relaxed).saturating_sub(wake_pre);
    let empty_delta = empty_poll_wakeups.load(AtomicOrdering::Relaxed).saturating_sub(empty_pre);

    // Shut down 16 worker threads cleanly
    stop_flag.store(true, AtomicOrdering::Relaxed);
    if is_event_driven {
        for &fd in efds.iter() {
            signal_eventfd(fd);
        }
    }
    for h in handles {
        let _ = h.join();
    }
    for &fd in efds.iter() {
        close_eventfd(fd);
    }

    let mut lats_ms: Vec<f64> = commit_latencies_ns
        .lock()
        .unwrap()
        .iter()
        .map(|&ns| ns as f64 / 1e6)
        .collect();
    lats_ms.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let mean_lat_ms = if lats_ms.is_empty() {
        0.0
    } else {
        lats_ms.iter().sum::<f64>() / lats_ms.len() as f64
    };

    json!({
        "regime": regime,
        "duty_cycle": duty_cycle,
        "replicate": rep,
        "window_s": actual_s,
        "events_injected": sent_events,
        "events_committed": lats_ms.len(),
        "edge_verifications": total_edge_verifies.load(AtomicOrdering::Relaxed),
        "ssp_epoch0_schedule_ns": ssp_init_ns,
        "ssp_per_tick_recomputes": 0,
        "node_wakeups": wake_delta,
        "empty_polling_wakeups": empty_delta,
        "voluntary_ctxt_switches": vol_post.saturating_sub(vol_pre),
        "nonvoluntary_ctxt_switches": nonvol_post.saturating_sub(nonvol_pre),
        "total_ctxt_switches": (vol_post.saturating_sub(vol_pre)) + (nonvol_post.saturating_sub(nonvol_pre)),
        "active_kernel_cpu_ms": active_kernel_ns.load(AtomicOrdering::Relaxed) as f64 / 1e6,
        "pkg_reported_j": pkg_j,
        "core_reported_j": core_j,
        "psys_reported_j": psys_j,
        "pkg_avg_w": pkg_j / actual_s,
        "core_avg_w": core_j / actual_s,
        "latency_mean_ms": mean_lat_ms,
        "latency_p50_ms": percentile_f64(&lats_ms, 0.50),
        "latency_p99_ms": percentile_f64(&lats_ms, 0.99),
    })
}

fn run_bench_e1(window_s: f64, replicates: usize) -> Value {
    let keyring = Arc::new(NodeKeyring::deterministic_standard());
    let pre_idle = measure_idle_baseline(5.0);

    let duty_cycles = [0.01, 0.05, 0.20];
    let regimes = ["event_threshold", "poll_10hz", "poll_100hz", "poll_1000hz"];
    let mut runs = Vec::new();

    for &dc in &duty_cycles {
        for rep in 0..replicates {
            for &reg in &regimes {
                eprintln!(
                    "[CTA-E1] duty={:.0}% rep={}/{} regime={} ...",
                    dc * 100.0,
                    rep + 1,
                    replicates,
                    reg
                );
                let r = run_single_e1_window(reg, dc, window_s, rep, &keyring);
                runs.push(r);
            }
        }
    }

    let post_idle = measure_idle_baseline(5.0);
    let pre_pkg_w = pre_idle["pkg_idle_w"].as_f64().unwrap_or(1.0);
    let post_pkg_w = post_idle["pkg_idle_w"].as_f64().unwrap_or(1.0);
    let drift_pct = ((post_pkg_w - pre_pkg_w).abs() / pre_pkg_w.max(1e-6)) * 100.0;
    let f6_triggered = drift_pct > 10.0;

    json!({
        "experiment": "CTA-E1",
        "board_metered": false,
        "measured_j": Value::Null,
        "window_s_target": window_s,
        "replicates": replicates,
        "pre_idle_baseline": pre_idle,
        "post_idle_baseline": post_idle,
        "falsifier_6_idle_drift_pct": drift_pct,
        "falsifier_6_withhold_net_subtraction": f6_triggered,
        "runs": runs,
    })
}

// ============================================================================
// 6. Subcommand `bench-e3`: Byzantine Channel Faults & SSP 20-Dropout Re-Route
// ============================================================================

fn run_bench_e3_rust() -> Value {
    let keyring = NodeKeyring::deterministic_standard();
    let mut rng = ChaCha20Rng::seed_from_u64(0xE300_2026);

    let valid_payload = serde_json::to_vec(&json!({
        "kind": "patch_candidate",
        "ast_ok": true,
        "fn_name": "repair_target",
        "code": "def repair_target(x: int) -> int:\n    return x + 1\n",
    }))
    .unwrap();

    // 1. 200 Valid Control Envelopes
    let mut valid_ns = Vec::with_capacity(200);
    let mut valid_accepted = 0usize;
    for i in 0..200 {
        let env = keyring
            .sign_envelope(
                &format!("ctrl_{}", i),
                1,
                "det_patch_kernel",
                "det_patch_kernel",
                "diff_verifier_kernel",
                "typed_ast_patch",
                valid_payload.clone(),
            )
            .unwrap();
        let t0 = Instant::now();
        if keyring.verify_envelope(&env, true).is_ok() {
            valid_accepted += 1;
        }
        valid_ns.push(t0.elapsed().as_nanos() as u64);
    }
    valid_ns.sort_unstable();

    // 2A. 50 Payload Bit-Flips (post-signature corruption)
    let mut bitflip_ns = Vec::with_capacity(50);
    let mut bitflip_rejected = 0usize;
    for i in 0..50 {
        let mut env = keyring
            .sign_envelope(
                &format!("bf_{}", i),
                1,
                "det_patch_kernel",
                "det_patch_kernel",
                "diff_verifier_kernel",
                "typed_ast_patch",
                valid_payload.clone(),
            )
            .unwrap();
        let byte_idx = (rng.next_u32() as usize) % env.payload.len();
        let bit_mask = 1u8 << ((rng.next_u32() as usize) % 8);
        env.payload[byte_idx] ^= bit_mask;

        let t0 = Instant::now();
        if keyring.verify_envelope(&env, true).is_err() {
            bitflip_rejected += 1;
        }
        bitflip_ns.push(t0.elapsed().as_nanos() as u64);
    }
    bitflip_ns.sort_unstable();

    // 2B. 50 Spoofed Sender IDs (signed with rogue_adversary key claiming det_patch_kernel)
    let mut spoof_ns = Vec::with_capacity(50);
    let mut spoof_rejected = 0usize;
    for i in 0..50 {
        let env = keyring
            .sign_envelope(
                &format!("spoof_{}", i),
                1,
                "det_patch_kernel",
                "rogue_adversary",
                "diff_verifier_kernel",
                "typed_ast_patch",
                valid_payload.clone(),
            )
            .unwrap();
        let t0 = Instant::now();
        if keyring.verify_envelope(&env, true).is_err() {
            spoof_rejected += 1;
        }
        spoof_ns.push(t0.elapsed().as_nanos() as u64);
    }
    spoof_ns.sort_unstable();

    // 2C. 50 Truncated JSON/AST Frames (signed truncated/incomplete JSON frame)
    let mut trunc_ns = Vec::with_capacity(50);
    let mut trunc_rejected = 0usize;
    for i in 0..50 {
        let cut = 12 + (i % (valid_payload.len() - 20));
        let truncated_bytes = valid_payload[..cut].to_vec();
        let env = keyring
            .sign_envelope(
                &format!("trunc_{}", i),
                1,
                "det_patch_kernel",
                "det_patch_kernel",
                "diff_verifier_kernel",
                "typed_ast_patch",
                truncated_bytes,
            )
            .unwrap();
        let t0 = Instant::now();
        if keyring.verify_envelope(&env, true).is_err() {
            trunc_rejected += 1;
        }
        trunc_ns.push(t0.elapsed().as_nanos() as u64);
    }
    trunc_ns.sort_unstable();

    // 3. 20 Mid-Stream Node Dropouts forcing SSP Min-Cost Topology Recomputation
    let nodes = vec![
        "source",
        "parse_primary",
        "parse_standby",
        "static_primary",
        "static_standby",
        "testgen_primary",
        "testgen_standby",
        "detpatch_primary",
        "detpatch_standby",
        "proposer_primary",
        "proposer_standby",
        "verifier_primary",
        "verifier_standby",
        "commit_sink",
    ]
    .into_iter()
    .map(String::from)
    .collect::<Vec<_>>();

    let mut mcf = MinCostFlowScheduler::new(nodes);
    // Primary low-joule paths + standby higher-cost redundant paths + cross-over links
    mcf.add_edge("source", "parse_primary", 10, 1200, "e_src_p0");
    mcf.add_edge("source", "parse_standby", 10, 1650, "e_src_p1");
    mcf.add_edge("parse_primary", "static_primary", 10, 1800, "e_p0_s0");
    mcf.add_edge("parse_primary", "static_standby", 10, 2200, "e_p0_s1");
    mcf.add_edge("parse_standby", "static_primary", 10, 1950, "e_p1_s0");
    mcf.add_edge("parse_standby", "static_standby", 10, 2300, "e_p1_s1");
    mcf.add_edge("static_primary", "testgen_primary", 10, 2100, "e_s0_t0");
    mcf.add_edge("static_primary", "testgen_standby", 10, 2600, "e_s0_t1");
    mcf.add_edge("static_standby", "testgen_primary", 10, 2250, "e_s1_t0");
    mcf.add_edge("static_standby", "testgen_standby", 10, 2700, "e_s1_t1");
    mcf.add_edge("testgen_primary", "detpatch_primary", 10, 2900, "e_t0_d0");
    mcf.add_edge("testgen_primary", "detpatch_standby", 10, 3500, "e_t0_d1");
    mcf.add_edge("testgen_standby", "detpatch_primary", 10, 3100, "e_t1_d0");
    mcf.add_edge("testgen_standby", "detpatch_standby", 10, 3650, "e_t1_d1");
    mcf.add_edge("detpatch_primary", "verifier_primary", 6, 2400, "e_d0_v0_direct");
    mcf.add_edge("detpatch_primary", "proposer_primary", 10, 45000, "e_d0_m0_esc");
    mcf.add_edge("detpatch_primary", "proposer_standby", 10, 52000, "e_d0_m1_esc");
    mcf.add_edge("detpatch_standby", "verifier_standby", 6, 2850, "e_d1_v1_direct");
    mcf.add_edge("detpatch_standby", "proposer_primary", 10, 46500, "e_d1_m0_esc");
    mcf.add_edge("detpatch_standby", "proposer_standby", 10, 53000, "e_d1_m1_esc");
    mcf.add_edge("proposer_primary", "verifier_primary", 10, 2500, "e_m0_v0");
    mcf.add_edge("proposer_primary", "verifier_standby", 10, 2900, "e_m0_v1");
    mcf.add_edge("proposer_standby", "verifier_primary", 10, 2650, "e_m1_v0");
    mcf.add_edge("proposer_standby", "verifier_standby", 10, 3000, "e_m1_v1");
    mcf.add_edge("verifier_primary", "commit_sink", 10, 900, "e_v0_sink");
    mcf.add_edge("verifier_standby", "commit_sink", 10, 1150, "e_v1_sink");

    let dropout_scenarios: Vec<Vec<&str>> = vec![
        vec!["parse_primary"],
        vec!["static_primary"],
        vec!["testgen_primary"],
        vec!["detpatch_primary"],
        vec!["proposer_primary"],
        vec!["verifier_primary"],
        vec!["parse_primary", "static_primary"],
        vec!["static_primary", "testgen_primary"],
        vec!["testgen_primary", "detpatch_primary"],
        vec!["detpatch_primary", "proposer_primary"],
        vec!["proposer_primary", "verifier_primary"],
        vec!["parse_primary", "detpatch_primary"],
        vec!["static_primary", "verifier_primary"],
        vec!["parse_standby", "testgen_primary"],
        vec!["static_standby", "detpatch_primary"],
        vec!["parse_primary", "static_primary", "testgen_primary"],
        vec!["testgen_primary", "detpatch_primary", "verifier_primary"],
        vec!["parse_primary", "proposer_primary", "verifier_primary"],
        vec!["static_primary", "detpatch_primary", "proposer_primary"],
        vec!["parse_primary", "static_primary", "detpatch_primary", "verifier_primary"],
    ];

    let (base_flow, base_cost, _, base_ns) = mcf.solve_ssp("source", "commit_sink", 8, &[]);
    let mut reroute_ns = Vec::with_capacity(20);
    let mut reroute_events = Vec::with_capacity(20);

    for (idx, scen) in dropout_scenarios.iter().enumerate() {
        let dis: Vec<String> = scen.iter().map(|s| s.to_string()).collect();
        let (fl, cost, edges, ns) = mcf.solve_ssp("source", "commit_sink", 8, &dis);
        reroute_ns.push(ns);
        reroute_events.push(json!({
            "dropout_idx": idx,
            "disabled_nodes": dis,
            "satisfied_flow": fl,
            "demand": 8,
            "min_cost_uj_scaled": cost,
            "reroute_latency_us": ns as f64 / 1000.0,
            "active_edge_count": edges.len(),
        }));
    }
    reroute_ns.sort_unstable();

    json!({
        "control_valid_200": {
            "total": 200,
            "accepted": valid_accepted,
            "verify_mean_us": (valid_ns.iter().sum::<u64>() as f64 / 200.0) / 1000.0,
            "verify_p50_us": percentile_u64(&valid_ns, 0.50) as f64 / 1000.0,
            "verify_p99_us": percentile_u64(&valid_ns, 0.99) as f64 / 1000.0,
        },
        "fault_bitflip_50": {
            "injected": 50,
            "rejected": bitflip_rejected,
            "corrupt_commits": 50 - bitflip_rejected,
            "reject_mean_us": (bitflip_ns.iter().sum::<u64>() as f64 / 50.0) / 1000.0,
            "reject_p50_us": percentile_u64(&bitflip_ns, 0.50) as f64 / 1000.0,
            "reject_p99_us": percentile_u64(&bitflip_ns, 0.99) as f64 / 1000.0,
        },
        "fault_spoofed_sender_50": {
            "injected": 50,
            "rejected": spoof_rejected,
            "corrupt_commits": 50 - spoof_rejected,
            "reject_mean_us": (spoof_ns.iter().sum::<u64>() as f64 / 50.0) / 1000.0,
            "reject_p50_us": percentile_u64(&spoof_ns, 0.50) as f64 / 1000.0,
            "reject_p99_us": percentile_u64(&spoof_ns, 0.99) as f64 / 1000.0,
        },
        "fault_truncated_frame_50": {
            "injected": 50,
            "rejected": trunc_rejected,
            "corrupt_commits": 50 - trunc_rejected,
            "reject_mean_us": (trunc_ns.iter().sum::<u64>() as f64 / 50.0) / 1000.0,
            "reject_p50_us": percentile_u64(&trunc_ns, 0.50) as f64 / 1000.0,
            "reject_p99_us": percentile_u64(&trunc_ns, 0.99) as f64 / 1000.0,
        },
        "ssp_topology_rerouting_20": {
            "baseline_flow": base_flow,
            "baseline_cost_uj_scaled": base_cost,
            "baseline_solve_us": base_ns as f64 / 1000.0,
            "dropouts_tested": 20,
            "all_demands_satisfied": reroute_events.iter().all(|e| e["satisfied_flow"] == 8),
            "reroute_mean_us": (reroute_ns.iter().sum::<u64>() as f64 / 20.0) / 1000.0,
            "reroute_p50_us": percentile_u64(&reroute_ns, 0.50) as f64 / 1000.0,
            "reroute_p99_us": percentile_u64(&reroute_ns, 0.99) as f64 / 1000.0,
            "reroute_max_us": *reroute_ns.last().unwrap_or(&0) as f64 / 1000.0,
            "events": reroute_events,
        }
    })
}

// ============================================================================
// 7. Subcommand `attest-daemon`: Live Stdio Pipe for CTA-E2 Arm D Ledger & SSP
// ============================================================================

#[derive(Deserialize)]
struct DaemonReq {
    cmd: String,
    #[serde(default)]
    trace_id: String,
    #[serde(default)]
    step_idx: u32,
    #[serde(default)]
    sender_id: String,
    #[serde(default)]
    receiver_id: String,
    #[serde(default)]
    channel_type: String,
    #[serde(default)]
    input_str: String,
    #[serde(default)]
    output_str: String,
    #[serde(default)]
    nodes: Vec<String>,
    #[serde(default)]
    edges: Vec<Value>,
    #[serde(default)]
    source: String,
    #[serde(default)]
    sink: String,
    #[serde(default)]
    demand: i64,
    #[serde(default)]
    disabled_nodes: Vec<String>,
}

fn run_attest_daemon() {
    let keyring = NodeKeyring::deterministic_standard();
    let stdin = io::stdin();
    let mut stdout = io::stdout();

    for line in stdin.lock().lines() {
        let Ok(line) = line else { break };
        if line.trim().is_empty() {
            continue;
        }
        let req: DaemonReq = match serde_json::from_str(&line) {
            Ok(r) => r,
            Err(e) => {
                let _ = writeln!(stdout, "{}", json!({"ok": false, "error": e.to_string()}));
                let _ = stdout.flush();
                continue;
            }
        };

        if req.cmd == "quit" {
            break;
        } else if req.cmd == "attest" {
            let in_b3 = blake3::hash(req.input_str.as_bytes());
            let env = match keyring.sign_envelope(
                &req.trace_id,
                req.step_idx,
                &req.sender_id,
                &req.sender_id,
                &req.receiver_id,
                &req.channel_type,
                req.output_str.into_bytes(),
            ) {
                Ok(e) => e,
                Err(err) => {
                    let _ = writeln!(stdout, "{}", json!({"ok": false, "error": err}));
                    let _ = stdout.flush();
                    continue;
                }
            };
            let t_ver = Instant::now();
            let ver_ok = keyring.verify_envelope(&env, false).is_ok();
            let verify_ns = t_ver.elapsed().as_nanos() as u64;
            let resp = json!({
                "ok": ver_ok,
                "input_blake3": in_b3.to_hex().to_string(),
                "output_blake3": hex_encode(&env.payload_blake3),
                "ed25519_sig_prefix": hex_encode(&env.ed25519_sig[..16]),
                "ed25519_sig_hex": hex_encode(&env.ed25519_sig),
                "verify_ns": verify_ns,
            });
            let _ = writeln!(stdout, "{}", resp);
            let _ = stdout.flush();
        } else if req.cmd == "ssp" {
            let mut mcf = MinCostFlowScheduler::new(req.nodes);
            for e in &req.edges {
                mcf.add_edge(
                    e["from"].as_str().unwrap_or(""),
                    e["to"].as_str().unwrap_or(""),
                    e["cap"].as_i64().unwrap_or(1),
                    e["cost"].as_i64().unwrap_or(1),
                    e["edge_id"].as_str().unwrap_or("e"),
                );
            }
            let (flow, cost, active, ns) =
                mcf.solve_ssp(&req.source, &req.sink, req.demand.max(1), &req.disabled_nodes);
            let resp = json!({
                "ok": true,
                "flow": flow,
                "total_cost": cost,
                "solve_ns": ns,
                "active_edges": active,
            });
            let _ = writeln!(stdout, "{}", resp);
            let _ = stdout.flush();
        }
    }
}

fn main() {
    let args: Vec<String> = env::args().collect();
    let sub = args.get(1).map(|s| s.as_str()).unwrap_or("help");

    match sub {
        "bench-crypto" => {
            let mut iters = 50_000usize;
            let mut i = 2;
            while i + 1 < args.len() {
                if args[i] == "--iters" {
                    iters = args[i + 1].parse().unwrap_or(50_000);
                }
                i += 2;
            }
            println!("{}", serde_json::to_string_pretty(&run_bench_crypto(iters)).unwrap());
        }
        "bench-e1" => {
            let mut window_s = 10.0f64;
            let mut replicates = 5usize;
            let mut i = 2;
            while i + 1 < args.len() {
                if args[i] == "--window-s" {
                    window_s = args[i + 1].parse().unwrap_or(10.0);
                } else if args[i] == "--replicates" {
                    replicates = args[i + 1].parse().unwrap_or(5);
                }
                i += 2;
            }
            println!(
                "{}",
                serde_json::to_string_pretty(&run_bench_e1(window_s, replicates)).unwrap()
            );
        }
        "bench-e3" => {
            println!("{}", serde_json::to_string_pretty(&run_bench_e3_rust()).unwrap());
        }
        "attest-daemon" => {
            run_attest_daemon();
        }
        "idle-check" => {
            let secs = args.get(2).and_then(|s| s.parse::<f64>().ok()).unwrap_or(5.0);
            println!("{}", serde_json::to_string_pretty(&measure_idle_baseline(secs)).unwrap());
        }
        _ => {
            eprintln!(
                "Usage: cta_attest_rust <bench-crypto|bench-e1|bench-e3|attest-daemon|idle-check>"
            );
            std::process::exit(1);
        }
    }
}
