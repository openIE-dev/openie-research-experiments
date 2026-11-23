mod telemetry;

use blake3::Hasher as Blake3Hasher;
use ed25519_dalek::{Signature, Signer, SigningKey, VerifyingKey};
use rand::RngCore;
use rand::SeedableRng;
use rand_chacha::ChaCha20Rng;
use serde::Deserialize;
use serde_json::{json, Value};
use std::cmp::Ordering;
use std::collections::{BinaryHeap, HashMap, VecDeque};
use std::env;
use std::io::{self, BufRead, Write};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering as AtomicOrdering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};
use telemetry::{measure_fleet_idle, FleetMeterSession, OsEventHandle};

// ============================================================================
// 1. Constant-Time BLAKE3 (256-bit) + Ed25519 (64-byte RFC 8032) Attestation
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
            "router_ssp",
            "C1",
            "C2",
            "C3",
            "C4",
            "C5",
            "C6",
            "C7",
            "C8",
            "C9",
            "C10",
            "DES10",
            "enzyme_gate",
            "verifier_gate",
            "crystallizer",
            "commit_sink",
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

    pub fn verify_envelope(&self, env: &AttestedEnvelope) -> Result<(), &'static str> {
        let vk = self
            .verifying
            .get(&env.sender_id)
            .ok_or("unknown_sender_id")?;
        let actual_hash = blake3::hash(&env.payload);
        let claimed_hash = blake3::Hash::from_bytes(env.payload_blake3);
        if actual_hash != claimed_hash {
            return Err("blake3_digest_mismatch");
        }
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
// 2. Exact Successive Shortest Path (SSP) Min-Cost Flow Scheduler
// ============================================================================

#[derive(Clone, Debug)]
struct FlowEdge {
    to: usize,
    rev: usize,
    cap: i64,
    flow: i64,
    cost: i64,
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
// 3. Subcommand `bench-crypto`: 5-Host BLAKE3 + Ed25519 Attestation Benchmark
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
    let mut buckets = Vec::new();
    let mut any_board_metered = false;

    for &sz in &sizes {
        let mut payload = vec![0u8; sz];
        rng.fill_bytes(&mut payload);

        for i in 0..500 {
            let env = keyring
                .sign_envelope("warmup", i as u32, "n00", "n00", "n01", "raw", payload.clone())
                .unwrap();
            keyring.verify_envelope(&env).unwrap();
        }

        // 1. Sign + BLAKE3 (iters)
        let mut sign_ns = Vec::with_capacity(iters);
        let mut last_env = None;
        let mut meter_sign = FleetMeterSession::start();
        for i in 0..iters {
            if i % 4096 == 0 {
                meter_sign.sample_rapl();
            }
            let t0 = Instant::now();
            let env = keyring
                .sign_envelope("bench", i as u32, "n00", "n00", "n01", "raw", payload.clone())
                .unwrap();
            sign_ns.push(t0.elapsed().as_nanos() as u64);
            last_env = Some(std::hint::black_box(env));
        }
        let tel_sign = meter_sign.finish();
        sign_ns.sort_unstable();

        // 2. Verify + BLAKE3 (iters)
        let env_ref = last_env.unwrap();
        let mut verify_ns = Vec::with_capacity(iters);
        let mut ok_cnt = 0usize;
        let mut meter_ver = FleetMeterSession::start();
        for i in 0..iters {
            if i % 4096 == 0 {
                meter_ver.sample_rapl();
            }
            let t0 = Instant::now();
            if keyring.verify_envelope(std::hint::black_box(&env_ref)).is_ok() {
                ok_cnt += 1;
            }
            verify_ns.push(t0.elapsed().as_nanos() as u64);
        }
        let tel_ver = meter_ver.finish();
        verify_ns.sort_unstable();
        if tel_ver.board_metered {
            any_board_metered = true;
        }

        let n_f = iters as f64;
        let mean_sign_us = (sign_ns.iter().sum::<u64>() as f64 / n_f) / 1000.0;
        let mean_ver_us = (verify_ns.iter().sum::<u64>() as f64 / n_f) / 1000.0;

        buckets.push(json!({
            "payload_bytes": sz,
            "iterations": iters,
            "verified_ok": ok_cnt,
            "sign_mean_us": mean_sign_us,
            "sign_p50_us": percentile_u64(&sign_ns, 0.50) as f64 / 1000.0,
            "sign_p99_us": percentile_u64(&sign_ns, 0.99) as f64 / 1000.0,
            "verify_mean_us": mean_ver_us,
            "verify_p50_us": percentile_u64(&verify_ns, 0.50) as f64 / 1000.0,
            "verify_p99_us": percentile_u64(&verify_ns, 0.99) as f64 / 1000.0,
            "verify_window_s": tel_ver.elapsed_s,
            "board_metered": tel_ver.board_metered,
            // Separated measured_j / edge (microjoules) - ONLY on physical shunt hosts (Jetson Thor)
            "verify_vin_ina238_measured_uj_per_edge": tel_ver.l1_vin_ina238_measured_j.map(|j| j * 1e6 / n_f),
            "verify_vdd_cpu_soc_mss_measured_uj_per_edge": tel_ver.l2_vdd_cpu_soc_mss_measured_j.map(|j| j * 1e6 / n_f),
            "verify_vdd_gpu_measured_uj_per_edge": tel_ver.l2_vdd_gpu_measured_j.map(|j| j * 1e6 / n_f),
            "sign_vdd_cpu_soc_mss_measured_uj_per_edge": tel_sign.l2_vdd_cpu_soc_mss_measured_j.map(|j| j * 1e6 / n_f),
            // Separated reported_j / edge (microjoules) - on RAPL / Darwin / NVML hosts
            "verify_pkg_reported_uj_per_edge": tel_ver.pkg_reported_j.map(|j| j * 1e6 / n_f),
            "verify_core_reported_uj_per_edge": tel_ver.core_reported_j.map(|j| j * 1e6 / n_f),
            "verify_psys_reported_uj_per_edge": tel_ver.psys_reported_j.map(|j| j * 1e6 / n_f),
            "verify_amdgpu_ppt_reported_uj_per_edge": tel_ver.amdgpu_ppt_reported_j.map(|j| j * 1e6 / n_f),
            "verify_darwin_ri_reported_uj_per_edge": tel_ver.darwin_ri_energy_reported_j.map(|j| j * 1e6 / n_f),
            "verify_win_nvml_gpu_reported_uj_per_edge": tel_ver.win_nvml_gpu_reported_j.map(|j| j * 1e6 / n_f),
            "verify_win_cycles_per_edge": tel_ver.win_process_cycles.map(|c| c as f64 / n_f),
            "sign_pkg_reported_uj_per_edge": tel_sign.pkg_reported_j.map(|j| j * 1e6 / n_f),
            "sign_darwin_ri_reported_uj_per_edge": tel_sign.darwin_ri_energy_reported_j.map(|j| j * 1e6 / n_f),
            "raw_verify_telemetry": tel_ver,
        }));
    }

    json!({
        "benchmark": "cta_e4_crypto_attestation_blake3_ed25519",
        "os_event_mechanism": OsEventHandle::mechanism_name(),
        "board_metered": any_board_metered,
        "buckets": buckets,
    })
}

// ============================================================================
// 4. Subcommand `bench-e4-dag`: 16-Node DAG Zero-Clock Event vs 1,000 Hz Poll
// ============================================================================

#[derive(Clone)]
struct DagOutEdge {
    target: usize,
    weight_milli: u64,
}

struct NodeChannelState {
    inbox: VecDeque<(AttestedEnvelope, Instant)>,
    potential_milli: u64,
    threshold_milli: u64,
    heartbeat_seq: u64,
}

fn build_16_node_dag() -> (Vec<Vec<DagOutEdge>>, Vec<u64>, Vec<u32>) {
    let mut adj = vec![Vec::new(); 16];
    let thresholds = vec![1000u64; 16];
    let kernel_work: Vec<u32> = vec![
        180, 260, 340, 280, 320, 260, 220, 240, 280, 300, 360, 360, 180, 520, 420, 180,
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

fn run_single_e4_window(
    regime: &str,
    duty_cycle: f64,
    window_s: f64,
    pair_idx: usize,
    keyring: &Arc<NodeKeyring>,
) -> Value {
    let (adj, thresholds, kernel_work) = build_16_node_dag();
    let adj = Arc::new(adj);
    let kernel_work = Arc::new(kernel_work);
    let is_event_driven = regime == "event_threshold";

    #[cfg(windows)]
    if !is_event_driven {
        unsafe {
            let _ = telemetry::win_hw::timeBeginPeriod(1);
        }
    }

    let mut states = Vec::with_capacity(16);
    let mut os_events = Vec::with_capacity(16);
    for u in 0..16 {
        states.push(Mutex::new(NodeChannelState {
            inbox: VecDeque::with_capacity(64),
            potential_milli: 0,
            threshold_milli: thresholds[u],
            heartbeat_seq: 0,
        }));
        os_events.push(if is_event_driven {
            OsEventHandle::new_active()
        } else {
            OsEventHandle::new_disabled()
        });
    }
    let states = Arc::new(states);
    let os_events = Arc::new(os_events);

    let stop_flag = Arc::new(AtomicBool::new(false));
    let total_wakeups = Arc::new(AtomicU64::new(0));
    let empty_poll_wakeups = Arc::new(AtomicU64::new(0));
    let total_edge_verifies = Arc::new(AtomicU64::new(0));
    let commit_latencies_ns: Arc<Mutex<Vec<u64>>> = Arc::new(Mutex::new(Vec::with_capacity(1024)));

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
        let ev_c = Arc::clone(&os_events);
        let adj_c = Arc::clone(&adj);
        let kw_c = Arc::clone(&kernel_work);
        let keyring_c = Arc::clone(keyring);
        let stop_c = Arc::clone(&stop_flag);
        let wake_c = Arc::clone(&total_wakeups);
        let empty_c = Arc::clone(&empty_poll_wakeups);
        let ver_c = Arc::clone(&total_edge_verifies);
        let lats_c = Arc::clone(&commit_latencies_ns);

        handles.push(thread::spawn(move || {
            let my_name = format!("n{:02}", u);
            let mut poll_scratch = [0u8; 512];
            #[cfg(windows)]
            let hr_timer = if !is_event_driven {
                unsafe {
                    telemetry::win_hw::CreateWaitableTimerExW(
                        std::ptr::null(),
                        std::ptr::null(),
                        0x0000_0002,
                        0x001F_0003,
                    )
                }
            } else {
                std::ptr::null_mut()
            };

            loop {
                if is_event_driven {
                    ev_c[u].wait();
                } else {
                    #[cfg(windows)]
                    telemetry::win_hw::sleep_1khz_tick(hr_timer);
                    #[cfg(not(windows))]
                    thread::sleep(Duration::from_millis(1));
                }
                wake_c.fetch_add(1, AtomicOrdering::Relaxed);

                if !is_event_driven {
                    let mut hb_acc = 0u64;
                    for peer in 0..16 {
                        if let Ok(g) = states_c[peer].try_lock() {
                            hb_acc = hb_acc.wrapping_add(g.heartbeat_seq ^ (g.potential_milli << 3));
                        }
                    }
                    poll_scratch[0..8].copy_from_slice(&hb_acc.to_le_bytes());
                    std::hint::black_box(blake3::hash(&poll_scratch));
                }

                let mut fired_any = false;
                loop {
                    let batch: Option<Vec<(AttestedEnvelope, Instant)>> = {
                        let mut st = states_c[u].lock().unwrap();
                        st.heartbeat_seq = st.heartbeat_seq.wrapping_add(1);
                        if st.potential_milli >= st.threshold_milli && !st.inbox.is_empty() {
                            st.potential_milli -= st.threshold_milli;
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
                    let Some(items) = batch else { break };
                    if items.is_empty() {
                        break;
                    }
                    fired_any = true;
                    let origin_t0 = items[0].1;

                    let mut state_mix = Blake3Hasher::new();
                    for (env, _) in &items {
                        let _ = keyring_c.verify_envelope(env);
                        ver_c.fetch_add(1, AtomicOrdering::Relaxed);
                        state_mix.update(&env.payload_blake3);
                    }
                    let mut digest = state_mix.finalize();
                    for r in 0..kw_c[u] {
                        let mut h = Blake3Hasher::new();
                        h.update(digest.as_bytes());
                        h.update(&r.to_le_bytes());
                        digest = h.finalize();
                    }
                    let out_payload = digest.as_bytes().to_vec();

                    if u == 15 {
                        lats_c.lock().unwrap().push(origin_t0.elapsed().as_nanos() as u64);
                    } else {
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
                                ev_c[edge.target].signal();
                            }
                        }
                    }
                }
                if !fired_any && !is_event_driven {
                    empty_c.fetch_add(1, AtomicOrdering::Relaxed);
                }
                if stop_c.load(AtomicOrdering::Relaxed) {
                    break;
                }
            }
            #[cfg(windows)]
            if !hr_timer.is_null() {
                unsafe {
                    let _ = telemetry::win_hw::CloseHandle(hr_timer);
                }
            }
        }));
    }

    thread::sleep(Duration::from_millis(60));

    let total_events = ((duty_cycle * 5000.0 * (window_s / 10.0)).round() as usize).max(4);
    let micro_burst_size = 4usize;
    let num_bursts = (total_events + micro_burst_size - 1) / micro_burst_size;
    let mut rng = ChaCha20Rng::seed_from_u64(0xE400_0000 + (pair_idx as u64) * 97);
    let usable_s = (window_s - 0.35).max(0.5);
    let mut burst_offsets_s = Vec::with_capacity(num_bursts);
    for b in 0..num_bursts {
        let base = (b as f64 + 0.5) / (num_bursts as f64) * usable_s;
        let jitter = ((rng.next_u32() as f64 / u32::MAX as f64) - 0.5) * (usable_s / num_bursts as f64) * 0.6;
        burst_offsets_s.push(0.05 + (base + jitter).clamp(0.0, usable_s));
    }
    burst_offsets_s.sort_by(|a, b| a.partial_cmp(b).unwrap());

    let wake_pre = total_wakeups.load(AtomicOrdering::Relaxed);
    let empty_pre = empty_poll_wakeups.load(AtomicOrdering::Relaxed);
    let mut meter = FleetMeterSession::start();
    let win_start = Instant::now();
    let mut next_burst_idx = 0usize;
    let mut sent_events = 0usize;
    let mut next_rapl_sample = Duration::from_millis(200);

    while win_start.elapsed().as_secs_f64() < window_s {
        let elapsed = win_start.elapsed();
        if elapsed >= next_rapl_sample {
            meter.sample_rapl();
            next_rapl_sample += Duration::from_millis(200);
        }
        if next_burst_idx < burst_offsets_s.len() {
            let target_t = Duration::from_secs_f64(burst_offsets_s[next_burst_idx]);
            if elapsed >= target_t {
                let k = micro_burst_size.min(total_events - sent_events);
                for j in 0..k {
                    let eid = sent_events + j;
                    let trace_id = format!("e4_{}_p{}_{}", regime, pair_idx, eid);
                    let init_env = keyring
                        .sign_envelope("source", 0, "source", "source", "n00", "ingress", trace_id.into_bytes())
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
                        os_events[0].signal();
                    }
                }
                sent_events += k;
                next_burst_idx += 1;
                continue;
            } else {
                thread::sleep((target_t - elapsed).min(Duration::from_millis(40)));
            }
        } else {
            let rem = Duration::from_secs_f64(window_s).saturating_sub(elapsed);
            if rem.is_zero() {
                break;
            }
            thread::sleep(rem.min(Duration::from_millis(40)));
        }
    }

    let tel = meter.finish();
    let wake_delta = total_wakeups.load(AtomicOrdering::Relaxed).saturating_sub(wake_pre);
    let empty_delta = empty_poll_wakeups.load(AtomicOrdering::Relaxed).saturating_sub(empty_pre);

    stop_flag.store(true, AtomicOrdering::Relaxed);
    if is_event_driven {
        for ev in os_events.iter() {
            ev.signal();
        }
    }
    for h in handles {
        let _ = h.join();
    }
    #[cfg(windows)]
    if !is_event_driven {
        unsafe {
            let _ = telemetry::win_hw::timeEndPeriod(1);
        }
    }

    let mut lats_ms: Vec<f64> = commit_latencies_ns
        .lock()
        .unwrap()
        .iter()
        .map(|&ns| ns as f64 / 1e6)
        .collect();
    lats_ms.sort_by(|a, b| a.partial_cmp(b).unwrap());

    json!({
        "regime": regime,
        "os_event_mechanism": OsEventHandle::mechanism_name(),
        "duty_cycle": duty_cycle,
        "pair_idx": pair_idx,
        "window_s": tel.elapsed_s,
        "events_injected": sent_events,
        "events_committed": lats_ms.len(),
        "edge_verifications": total_edge_verifies.load(AtomicOrdering::Relaxed),
        "ssp_epoch0_schedule_ns": ssp_init_ns,
        "node_wakeups": wake_delta,
        "empty_polling_wakeups": empty_delta,
        "latency_p50_ms": percentile_f64(&lats_ms, 0.50),
        "latency_p99_ms": percentile_f64(&lats_ms, 0.99),
        "telemetry": tel,
    })
}

fn run_bench_e4_dag(window_s: f64, pairs: usize) -> Value {
    let keyring = Arc::new(NodeKeyring::deterministic_standard());
    let pre_idle = measure_fleet_idle(5.0);
    let mut windows = Vec::with_capacity(pairs * 2);

    // Counterbalanced AB/BA interleaved pairs at 1% bursty duty
    for p in 0..pairs {
        let order = if p % 2 == 0 {
            ["event_threshold", "poll_1000hz"]
        } else {
            ["poll_1000hz", "event_threshold"]
        };
        for &reg in &order {
            eprintln!("[CTA-E4 DAG] pair={}/{} regime={} ...", p + 1, pairs, reg);
            let w = run_single_e4_window(reg, 0.01, window_s, p, &keyring);
            windows.push(w);
        }
    }

    let post_idle = measure_fleet_idle(5.0);
    json!({
        "experiment": "CTA-E4-DAG-16node",
        "os_event_mechanism": OsEventHandle::mechanism_name(),
        "duty_cycle": 0.01,
        "window_s_target": window_s,
        "interleaved_pairs": pairs,
        "pre_idle_5s": pre_idle,
        "post_idle_5s": post_idle,
        "windows": windows,
    })
}

// ============================================================================
// 5. Subcommand `attest-daemon`: Digital Enzyme Channel Attestation + SSP Pipe
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
    payload_hex: String,
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

fn hex_decode(s: &str) -> Vec<u8> {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len() / 2);
    let mut i = 0;
    while i + 1 < b.len() {
        let hi = (b[i] as char).to_digit(16).unwrap_or(0) as u8;
        let lo = (b[i + 1] as char).to_digit(16).unwrap_or(0) as u8;
        out.push((hi << 4) | lo);
        i += 2;
    }
    out
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
            let raw_bytes = hex_decode(&req.payload_hex);
            let t0 = Instant::now();
            let env = match keyring.sign_envelope(
                &req.trace_id,
                req.step_idx,
                &req.sender_id,
                &req.sender_id,
                &req.receiver_id,
                &req.channel_type,
                raw_bytes,
            ) {
                Ok(e) => e,
                Err(err) => {
                    let _ = writeln!(stdout, "{}", json!({"ok": false, "error": err}));
                    let _ = stdout.flush();
                    continue;
                }
            };
            let sign_ns = t0.elapsed().as_nanos() as u64;
            let t_ver = Instant::now();
            let ver_ok = keyring.verify_envelope(&env).is_ok();
            let verify_ns = t_ver.elapsed().as_nanos() as u64;
            let resp = json!({
                "ok": ver_ok,
                "payload_blake3": hex_encode(&env.payload_blake3),
                "ed25519_sig_prefix": hex_encode(&env.ed25519_sig[..16]),
                "sign_ns": sign_ns,
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
            let _ = writeln!(
                stdout,
                "{}",
                json!({"ok": true, "flow": flow, "total_cost": cost, "solve_ns": ns, "active_edges": active})
            );
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
        "bench-e4-dag" => {
            let mut window_s = 5.0f64;
            let mut pairs = 4usize;
            let mut i = 2;
            while i + 1 < args.len() {
                if args[i] == "--window-s" {
                    window_s = args[i + 1].parse().unwrap_or(5.0);
                } else if args[i] == "--pairs" {
                    pairs = args[i + 1].parse().unwrap_or(4);
                }
                i += 2;
            }
            println!("{}", serde_json::to_string_pretty(&run_bench_e4_dag(window_s, pairs)).unwrap());
        }
        "attest-daemon" => run_attest_daemon(),
        "idle-check" => {
            let secs = args.get(2).and_then(|s| s.parse::<f64>().ok()).unwrap_or(5.0);
            println!("{}", serde_json::to_string_pretty(&measure_fleet_idle(secs)).unwrap());
        }
        _ => {
            eprintln!("Usage: cta_fleet_rust <bench-crypto|bench-e4-dag|attest-daemon|idle-check>");
            std::process::exit(1);
        }
    }
}
