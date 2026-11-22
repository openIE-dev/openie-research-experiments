//! Energy metering for JCP (SPEC §5) — the backend ladder that produces the
//! [`Energy`] a runtime debits.
//!
//! The rule is **measured when the platform exposes it, estimated when it
//! doesn't, and the provenance always says which**. There is always an
//! estimate: an environment with no energy interface still yields a usable
//! figure, it just carries `ModelBased` or `Estimator` provenance instead of
//! `HwShunt`. A reading never silently upgrades its own provenance.
//!
//! The ladder, best first. Every vendor counter rung is selected only while
//! its counter is live by one rule (SPEC §5): every rail of it that the figure
//! sums kept advancing over a probe, each in at least five sample intervals,
//! at least 80% of them, over at least 300 ms. A figure that sums a frozen rail
//! with live ones would leave out the frozen rail's share while claiming the
//! whole domain. Each probe runs once per process, and each rung's status says
//! why it was declined: [`Meter::detect_explained`] reports the rung selected
//! and the status of every rung asked on the way to it.
//! 1. **RAPL** (`/sys/class/powercap`, Linux) — hardware package energy,
//!    `Provenance::HwShunt`, **only while every package counter is live**
//!    under the probe's CPU burn ([`rapl_status`]). The figure sums the
//!    top-level zones whose `name` is `package-<n>`, every socket's (or
//!    `package-<n>-die-<m>`, every die's, where the kernel lists a multi-die
//!    Intel package one zone per die), each
//!    wraparound-corrected at its own range; never `psys` (the platform zone,
//!    which already includes the packages), a top-level `dram` zone, or a
//!    package's subzones. A span over which no package counter advanced is the
//!    default-power estimate (rung 6).
//!
//!    Some kernels ship without the powercap RAPL driver (Ubuntu without
//!    `linux-modules-extra`, as on some rented bare-metal servers), so powercap
//!    lists no package while the counters are there. Where it lists none, the
//!    reader takes the same counters directly: the energy-status MSR
//!    (`MSR_PKG_ENERGY_STATUS`, 0x611, on Intel family 6; 0xC001029B on AMD Zen
//!    and Hygon) of each counter domain, read on the domain's first CPU through
//!    the `msr` driver's `/dev/cpu/<n>/msr` (the `msr` module, `CAP_SYS_RAWIO`
//!    and read access to the file). A domain is a die on Intel and a package on
//!    AMD and Hygon, the Linux RAPL driver's own rule (`arch/x86/events/rapl.c`
//!    gives only AMD and Hygon a per-package counter; a multi-die Intel part's
//!    RAPL MSRs are die-scope), so a multi-die Intel package is read on each
//!    die's first CPU and the dies summed. Each 32-bit count is converted at the
//!    domain's own unit (bits
//!    12:8 of the power-unit MSR, 0x606 or 0xC0010299). It wraps at 2^32 counts
//!    and resolves one count (about 61 µJ at the common unit of 2^-14 J). A
//!    power-unit MSR that reads zero is no counter: some hypervisors let a guest
//!    read these MSRs and return zeros. The liveness rule is the same.
//! 2. **NVML** (feature `nvml`) — GPU energy via `libnvidia-ml`,
//!    `Provenance::HwShunt` with `Coverage::Partial`: the counter reads the
//!    GPU, so the CPU's share of the work is unmetered and the figure never
//!    claims the whole task. Only while the counter is live ([`nvml_status`])
//!    and plausibly counts the board's energy: over the probe it ran no
//!    faster than the board can draw, and not far slower than it drew
//!    ([`CounterStatus::Implausible`]); a span
//!    over which it did not advance is the whole-task default-power estimate.
//! 3. **Per-process CPU energy** (macOS) — the kernel's count of this
//!    process's own CPU energy, `ri_energy_nj` from
//!    `proc_pid_rusage(getpid(), RUSAGE_INFO_V6)` (public libproc, no
//!    entitlement, no privilege), `Provenance::HwShunt`, `Coverage::Whole`
//!    for in-process CPU work, **only while the count is live** under the
//!    probe's CPU burn ([`process_energy_status`]). Its domain is the CPU
//!    energy of this process's threads, all of them: not other processes, not
//!    child processes, not the GPU, the Neural Engine or DRAM. A span that
//!    reaps a child process, or ends with one (running or not yet reaped), is
//!    a `Coverage::Partial` reading: the child's energy is not in the count,
//!    and the figure does not claim it. It sits above
//!    IOReport because it attributes the work's own CPU energy, where
//!    IOReport's SoC-wide counter includes every other process. It is live
//!    for an unprivileged reader on macOS 27.0.1, where IOReport's CPU rails
//!    are not. A span over which it did not advance is the default-power
//!    estimate.
//!
//!    The kernel adds a thread's energy to the count only when the thread
//!    leaves a core, and a process's read of its own count does not take the
//!    reading thread off its core. So each end of a span is read only once
//!    the metering thread is SEEN to have left its core: it sleeps (50 µs,
//!    then 200 µs, 1 ms, 5 ms) until its own energy count
//!    (`proc_pidinfo`, `PROC_PIDTHREADCOUNTS`) rose across a sleep, which it
//!    does only when the kernel adds that thread's energy to the process's.
//!    An end whose thread was not seen to leave is not read, and the span is
//!    the default-power estimate — never a figure that is short of the
//!    span's tail, or holds what the thread spent before the span, graded as
//!    a reading (SPEC §5.1 rung 3). The rung is selected only where that
//!    count reads.
//! 4. **IOReport** (Apple Silicon) — the on-die SoC Energy Model counters via
//!    Apple's IOReport C API (no sudo, no external binary), `Provenance::HwShunt`.
//!    Like RAPL and NVML it is a vendor energy counter: the count is a real
//!    reading, not an estimate, and what it lacks is an independent root — how
//!    Apple derives it is undisclosed and the platform relays it — which is a
//!    question of provenance, not accuracy, so it takes the same grade. **Only
//!    while its CPU energy rail is live** ([`ioreport_status`]): a subscription
//!    can open while every CPU rail holds its value, refreshed only in rare
//!    batches, and then the summed total advances through the GPU rail — GPU
//!    energy reported as the energy of CPU work — or by a whole refresh at
//!    once. Live means every CPU rail kept advancing while the probe burned
//!    CPU — `CPU Energy`, or on a multi-die part each die's `DIE_<n>_CPU
//!    Energy`, since the counter sums them all: each in at least five separate
//!    sample intervals, in at least 80% of the intervals observed, over a
//!    window of at least 300 ms. A batch refresh, even one published in a few
//!    steps, is not a live rail, and one live die beside a frozen one is not a
//!    live CPU: the figure would miss the frozen die. Otherwise the
//!    platform is not exposing CPU energy, so by the rule above this rung is
//!    declined and the default-power time×power figure estimates instead. A
//!    span whose CPU rail did not advance is that estimate too, never a
//!    reading.
//!
//!    Declined, the rung does not report the GPU rail as a partial reading of
//!    the work, though on an M5 Max that rail stays live: it is machine-wide —
//!    display compositing moves it — so booking it to a task misattributes
//!    energy the task did not spend, and a partial figure would under-debit the
//!    budget, the CPU's share of the work going unmetered. The whole-task
//!    estimate stands.
//! 5. **Time × calibrated power** — wall-clock duration times an active power
//!    the host calibrated ([`Meter::time_power`]), `Provenance::ModelBased`.
//! 6. **Estimate** — a figure no host calibrated, `Provenance::Estimator`:
//!    wall-clock duration times a default active power
//!    ([`Meter::uncalibrated_time_power`], [`DEFAULT_ACTIVE_MILLIWATTS`]),
//!    which [`Meter::detect`] falls to when no counter rung is admitted and
//!    which every counter rung's span degrades to when its counter did not
//!    read the span; or a fixed per-operation figure ([`Meter::constant`]),
//!    for environments without even a usable clock. Always available.
//!
//! A time×power figure is `ModelBased` only when its power was calibrated on
//! the host: the power is the whole of the model, so a default power is a
//! constant the figure merely scales by time, and the figure is an estimate.

use std::time::Instant;

use jcp_schema::{Energy, Provenance};

/// Default active power for the time×power figure, in milliwatts: an
/// order-of-magnitude package draw for a busy core, assumed, not measured on
/// any host. A figure at this power is an estimate, `Provenance::Estimator`
/// ([`Meter::uncalibrated_time_power`]); a power calibrated on the deployment
/// host makes the figure a model, `Provenance::ModelBased`
/// ([`Meter::time_power`]).
pub const DEFAULT_ACTIVE_MILLIWATTS: u64 = 15_000;

/// Where the kernel lists its powercap zones.
const POWERCAP_ROOT: &str = "/sys/class/powercap";

/// RAPL package-energy reader (Linux `powercap`). Reads `energy_uj` for every
/// top-level zone (`intel-rapl:N`) whose `name` file reads `package-<n>` — every
/// socket's package — or `package-<n>-die-<m>` — every die's, on a multi-die
/// Intel package — and corrects each counter's wraparound at that zone's own
/// `max_energy_range_uj`. Where powercap lists no package zone, it reads each
/// package's energy-status MSR instead (see the crate docs, rung 1).
///
/// The figure is the packages' energy and nothing else. A top-level zone is not
/// necessarily a package: many Intel hosts expose `psys`, the platform zone,
/// whose count already includes the packages', so summing it beside them counts
/// that energy twice; some expose a top-level `dram` zone, which is not CPU
/// energy at all. Subzones (`intel-rapl:0:0`, a package's `core`, `uncore` or
/// `dram`) are a share of their package and never summed, and a second
/// interface to the same packages (`intel-rapl-mmio:N`) is not read either.
#[derive(Debug)]
pub struct Rapl {
    /// Every package, in package order.
    packages: Vec<RaplPackage>,
}

/// One package a [`Rapl`] reader sums.
#[derive(Debug, Clone, PartialEq, Eq)]
struct RaplPackage {
    /// The rail the liveness probe names it by: its powercap directory
    /// (`intel-rapl:0`, ...), or for one read from its MSR `package-<n> msr`,
    /// or `package-<n>-die-<m> msr` for each die of a multi-die Intel package.
    rail: String,
    /// Where its count is read: the zone's `energy_uj`, or the `msr` device
    /// file of the domain's (package's, or on Intel die's) first CPU,
    /// `/dev/cpu/<n>/msr`.
    path: std::path::PathBuf,
    /// The value its microjoule count wraps at: the zone's
    /// `max_energy_range_uj`, `None` where that could not be read or read as
    /// zero (a counter that falls across a span then has no known wrap, and
    /// gives no figure); for an MSR package, 2^32 counts at its unit.
    range: Option<u64>,
    /// How to read it from its MSR; `None` for a powercap zone.
    msr: Option<Msr>,
}

impl RaplPackage {
    /// Its count in µJ: the zone's `energy_uj`, or its MSR's 32-bit count at
    /// its unit. `None` when it cannot be read.
    fn read_uj(&self) -> Option<u64> {
        match self.msr {
            None => std::fs::read_to_string(&self.path).ok()?.trim().parse::<u64>().ok(),
            Some(msr) => read_msr(&self.path, msr.register).ok().map(|raw| msr.uj(raw)),
        }
    }
}

/// A package read from its energy-status MSR, where powercap lists no zone
/// for it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct Msr {
    /// The energy-status MSR: [`MSR_PKG_ENERGY_STATUS`] or
    /// [`MSR_AMD_PKG_ENERGY_STATUS`].
    register: u64,
    /// The energy-status unit, 2^-`unit_shift` J per count: bits 12:8 of the
    /// power-unit MSR. Never zero.
    unit_shift: u32,
}

/// Intel's power-unit MSR (family 6).
const MSR_RAPL_POWER_UNIT: u64 = 0x606;
/// Intel's package energy-status MSR (family 6).
const MSR_PKG_ENERGY_STATUS: u64 = 0x611;
/// AMD Zen's (and Hygon's) power-unit MSR.
const MSR_AMD_RAPL_POWER_UNIT: u64 = 0xC001_0299;
/// AMD Zen's (and Hygon's) package energy-status MSR.
const MSR_AMD_PKG_ENERGY_STATUS: u64 = 0xC001_029B;

impl Msr {
    /// The package's energy in µJ at a raw read of its energy-status MSR: the
    /// low 32 bits are the count.
    fn uj(self, raw: u64) -> u64 {
        ((u128::from(raw & 0xFFFF_FFFF) * 1_000_000) >> self.unit_shift) as u64
    }

    /// The µJ figure's wrap: 2^32 counts.
    fn range_uj(self) -> u64 {
        (((1u128 << 32) * 1_000_000) >> self.unit_shift) as u64
    }
}

/// The energy-status unit's shift, bits 12:8 of a power-unit MSR; `None` for a
/// zero unit, which is no counter (a hypervisor's stand-in).
fn msr_unit_shift(unit: u64) -> Option<u32> {
    let shift = ((unit >> 8) & 0x1F) as u32;
    (shift != 0).then_some(shift)
}

/// The 64-bit MSR `register`, read through the `msr` driver's device file
/// `device`, where the register number is the file offset. An error when the
/// file cannot be opened (no `msr` module; or no `CAP_SYS_RAWIO` or no read
/// access, both `PermissionDenied`) or the register cannot be read (the CPU
/// does not implement it).
#[cfg(unix)]
fn read_msr(device: &std::path::Path, register: u64) -> std::io::Result<u64> {
    use std::os::unix::fs::FileExt;
    let file = std::fs::File::open(device)?;
    let mut raw = [0u8; 8];
    file.read_exact_at(&mut raw, register)?;
    Ok(u64::from_le_bytes(raw))
}

#[cfg(not(unix))]
fn read_msr(_device: &std::path::Path, _register: u64) -> std::io::Result<u64> {
    Err(std::io::ErrorKind::Unsupported.into())
}

/// The CPU's vendor and family from `/proc/cpuinfo` text: the first CPU's
/// `vendor_id` and `cpu family`.
fn cpu_vendor_family(cpuinfo: &str) -> Option<(&str, u32)> {
    let field = |key: &str| {
        cpuinfo.lines().find_map(|line| {
            let (k, v) = line.split_once(':')?;
            (k.trim() == key).then(|| v.trim())
        })
    };
    Some((field("vendor_id")?, field("cpu family")?.parse().ok()?))
}

/// A CPU's RAPL MSRs, and the scope of its energy-status counter.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
struct MsrRegisters {
    /// The power-unit MSR.
    unit: u64,
    /// The energy-status MSR.
    energy: u64,
    /// Whether the counter counts one die (Intel) rather than the whole
    /// package (AMD, Hygon).
    per_die: bool,
}

/// The RAPL MSRs for a CPU's vendor and family, or `None` where this crate
/// knows none: Intel family 6, AMD Zen (family 0x17 and later) and Hygon.
///
/// Intel's counter is per die, AMD's and Hygon's per package. That is the
/// Linux RAPL driver's own rule: `arch/x86/events/rapl.c` scopes the package
/// counter per package only on AMD and Hygon ("AMD/HYGON platforms have a
/// per-PKG package energy counter"), and per die on Intel, where a multi-die
/// part such as Cascade Lake-AP has die-scope RAPL MSRs; `intel_rapl_common.c`
/// names such a part's powercap zones `package-<n>-die-<m>`.
fn msr_registers(vendor: &str, family: u32) -> Option<MsrRegisters> {
    match vendor {
        "GenuineIntel" if family == 6 => {
            Some(MsrRegisters { unit: MSR_RAPL_POWER_UNIT, energy: MSR_PKG_ENERGY_STATUS, per_die: true })
        }
        "AuthenticAMD" | "HygonGenuine" if family >= 0x17 => {
            Some(MsrRegisters { unit: MSR_AMD_RAPL_POWER_UNIT, energy: MSR_AMD_PKG_ENERGY_STATUS, per_die: false })
        }
        _ => None,
    }
}

/// A host's RAPL MSRs, and each counter domain's lowest-numbered CPU by
/// domain, `(package, die)`; the die is 0 where the counter is per package.
type MsrHost = (MsrRegisters, std::collections::BTreeMap<(u32, u32), u32>);

/// The CPU's RAPL MSRs under the filesystem root `root` (from its
/// `/proc/cpuinfo`), and each counter domain's lowest-numbered CPU, in domain
/// order. A domain is a package (`topology/physical_package_id`), and on Intel
/// a die of it (`topology/die_id`, 0 where the file is absent, as on kernels
/// that list no dies): see [`msr_registers`]. `None` when the CPU is not one
/// whose MSRs this crate knows, or no CPU topology is listed.
fn msr_host(root: &std::path::Path) -> Option<MsrHost> {
    let cpuinfo = std::fs::read_to_string(root.join("proc/cpuinfo")).ok()?;
    let registers = cpu_vendor_family(&cpuinfo).and_then(|(vendor, family)| msr_registers(vendor, family))?;
    let number = |p: std::path::PathBuf| std::fs::read_to_string(p).ok().and_then(|s| s.trim().parse::<u32>().ok());
    let mut first = std::collections::BTreeMap::new();
    for entry in std::fs::read_dir(root.join("sys/devices/system/cpu")).ok()?.flatten() {
        let Some(cpu) = entry.file_name().to_str().and_then(|n| n.strip_prefix("cpu")?.parse::<u32>().ok()) else {
            continue;
        };
        let topology = entry.path().join("topology");
        let Some(package) = number(topology.join("physical_package_id")) else {
            continue;
        };
        let die = if registers.per_die { number(topology.join("die_id")).unwrap_or(0) } else { 0 };
        let lowest = first.entry((package, die)).or_insert(cpu);
        *lowest = (*lowest).min(cpu);
    }
    (!first.is_empty()).then_some((registers, first))
}

/// The package zones of the powercap tree at `root`, in zone order.
/// `Ok(empty)` where the tree lists no package zone, or is not there; `Err`
/// where a zone that is or may be a package cannot be read — its `name`, or
/// its `energy_uj` — or the tree cannot be listed for want of privilege, since
/// a reader over the rest would leave that package out.
fn powercap_packages(root: &std::path::Path) -> Result<Vec<RaplPackage>, ()> {
    let dir = match std::fs::read_dir(root) {
        Ok(dir) => dir,
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => return Err(()),
        Err(_) => return Ok(Vec::new()),
    };
    let mut packages = Vec::new();
    for entry in dir.flatten() {
        let dir_name = entry.file_name().to_string_lossy().into_owned();
        let Some(index) = rapl_top_level_zone(&dir_name) else {
            continue;
        };
        let name = std::fs::read_to_string(entry.path().join("name")).map_err(|_| ())?;
        if !is_rapl_package_name(&name) {
            continue;
        }
        let energy = entry.path().join("energy_uj");
        // must actually be readable, not just present
        std::fs::read_to_string(&energy).ok().and_then(|s| s.trim().parse::<u64>().ok()).ok_or(())?;
        let range = std::fs::read_to_string(entry.path().join("max_energy_range_uj"))
            .ok()
            .and_then(|s| s.trim().parse::<u64>().ok())
            .filter(|&r| r > 0);
        packages.push((index, RaplPackage { rail: dir_name, path: energy, range, msr: None }));
    }
    packages.sort_by_key(|(index, _)| *index);
    Ok(packages.into_iter().map(|(_, package)| package).collect())
}

/// Every counter domain's energy-status MSR under the filesystem root `root`
/// — each die on Intel, each package on AMD and Hygon ([`msr_registers`]) — in
/// domain order, each read through the device file of the domain's first CPU
/// (`<root>/dev/cpu/<n>/msr`) at the unit its own power-unit MSR reads. `None`
/// when the CPU is not one whose MSRs this crate knows, no CPU topology is
/// listed, or any domain's power-unit MSR or energy-status MSR cannot be read
/// or its unit is zero: a figure that left a die or a package out would miss
/// its energy, and a zero unit is a hypervisor's stand-in, not a counter.
fn msr_packages(root: &std::path::Path) -> Option<Vec<RaplPackage>> {
    let (registers, first) = msr_host(root)?;
    let dies = |package: u32| first.keys().filter(|(p, _)| *p == package).count();
    first
        .iter()
        .map(|(&(package, die), &cpu)| {
            let path = root.join(format!("dev/cpu/{cpu}/msr"));
            let unit_shift = msr_unit_shift(read_msr(&path, registers.unit).ok()?)?;
            read_msr(&path, registers.energy).ok()?;
            let msr = Msr { register: registers.energy, unit_shift };
            let rail =
                if dies(package) > 1 { format!("package-{package}-die-{die} msr") } else { format!("package-{package} msr") };
            Some(RaplPackage { rail, path, range: Some(msr.range_uj()), msr: Some(msr) })
        })
        .collect()
}

/// Whether a powercap zone's `name` file names a CPU package's counter:
/// `package-<n>`, or `package-<n>-die-<m>`, `<n>` and `<m>` one or more ASCII
/// digits, trailing newline allowed. The kernel names one top-level zone per
/// die `package-<n>-die-<m>` on a multi-die Intel package, whose RAPL MSRs are
/// die-scope (`intel_rapl_common.c`: `"package-%d-die-%d"` where the MSRs are
/// not package-scope and a package has more than one die), so every die zone
/// is a package zone here and all are summed. Not `psys`, `dram`, `core`,
/// `uncore`, or anything else.
///
/// This is the predicate [`Rapl::open`] and [`Rapl::open_in`] apply to every
/// top-level zone: a zone qualifies for the RAPL rung exactly when this holds
/// of its `name`. A crate that decides the same question outside this one asks
/// it here, rather than keeping a copy that can fall behind it.
pub fn is_rapl_package_name(name: &str) -> bool {
    let digits = |n: &str| !n.is_empty() && n.bytes().all(|b| b.is_ascii_digit());
    let Some(rest) = name.trim().strip_prefix("package-") else {
        return false;
    };
    match rest.split_once("-die-") {
        Some((package, die)) => digits(package) && digits(die),
        None => digits(rest),
    }
}

/// The zone index of a top-level RAPL zone directory, `intel-rapl:<n>`; `None`
/// for anything else — the `intel-rapl` control type itself, a subzone
/// (`intel-rapl:0:0`), or another interface (`intel-rapl-mmio:0`).
fn rapl_top_level_zone(dir_name: &str) -> Option<u32> {
    let n = dir_name.strip_prefix("intel-rapl:")?;
    if n.is_empty() || !n.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    n.parse().ok()
}

impl Rapl {
    /// Open the RAPL interface: the powercap package zones, or, on Linux where
    /// powercap lists none, every package's energy-status MSR. `None` when the
    /// platform has neither (non-Linux, locked-down sysfs, no Intel/AMD RAPL,
    /// no `msr` module or no `CAP_SYS_RAWIO` on a host without the powercap
    /// driver), or a package whose counter cannot be read.
    /// Opening is not selection: [`Meter::detect`] selects the rung only while
    /// [`rapl_status`] is [`CounterStatus::Live`].
    pub fn open() -> Option<Self> {
        Self::open_from(std::path::Path::new(POWERCAP_ROOT), host_root())
    }

    /// The powercap tree at `powercap`, or, where it lists no package zone,
    /// the MSRs under the filesystem root `root` (none when `root` is `None`).
    /// A listed package zone that cannot be read is no reader, and no reason to
    /// read the MSRs instead: powercap is there, and this process may not read it.
    fn open_from(powercap: &std::path::Path, root: Option<&std::path::Path>) -> Option<Self> {
        match powercap_packages(powercap) {
            Ok(packages) if !packages.is_empty() => Some(Self { packages }),
            Ok(_) => root.and_then(msr_packages).map(|packages| Self { packages }),
            Err(()) => None,
        }
    }

    /// The reader [`Rapl::open`] would build from the powercap tree at `root`
    /// (`/sys/class/powercap` on a host), and from nothing else: no MSR is
    /// read where the tree lists no package zone. It answers which zones of
    /// that tree the RAPL rung sums: every top-level `intel-rapl:<n>` zone
    /// whose `name` satisfies [`is_rapl_package_name`], and no other. `None`
    /// where the tree lists no such zone, or is not there.
    ///
    /// Every package zone or none: the figure claims the whole CPU, so a
    /// package whose `energy_uj` cannot be read is not left out of it — the
    /// reader does not open. Nor does it open when a top-level zone's `name`
    /// cannot be read, since that zone may be a package. Opening is not
    /// selection, here as for [`Rapl::open`].
    pub fn open_in(root: &std::path::Path) -> Option<Self> {
        Self::open_from(root, None)
    }

    /// Current package counters, in µJ, one per package.
    fn read(&self) -> Option<Vec<u64>> {
        self.packages.iter().map(RaplPackage::read_uj).collect()
    }

    /// Energy spent between two counter snapshots: the sum of each package's
    /// own delta, each wraparound-corrected at that package's own range
    /// ([`rapl_zone_delta`]). `None` — no figure, never an invented one — if
    /// any package's delta is unknown.
    fn delta(&self, before: &[u64], after: &[u64]) -> Option<u64> {
        if before.len() != self.packages.len() || after.len() != self.packages.len() {
            return None;
        }
        let mut total = 0u64;
        for (package, (b, a)) in self.packages.iter().zip(before.iter().zip(after)) {
            total = total.checked_add(rapl_zone_delta(*b, *a, package.range)?)?;
        }
        Some(total)
    }

    /// One liveness sample: each package counter as a rail, named by its
    /// powercap directory (`intel-rapl:0`, ...) or as `package-<n> msr`, with
    /// its count in µJ. Only the packages the figure sums: `psys`, `dram` and
    /// subzones are neither summed nor probed. `None` when a package cannot be
    /// read, which the probe skips. A wrap shows as a fall, which the rule does
    /// not count as an advance.
    fn liveness_sample(&self) -> Option<Vec<(liveness::RailKey, i64)>> {
        let values = self.read()?;
        let named: Vec<(String, i64)> = self
            .packages
            .iter()
            .zip(values)
            .map(|(package, uj)| (package.rail.clone(), i64::try_from(uj).unwrap_or(i64::MAX)))
            .collect();
        Some(liveness::every_rail(&named))
    }
}

/// The filesystem root the MSR fallback reads under: `/` on Linux, where the
/// `msr` driver lives; none elsewhere.
fn host_root() -> Option<&'static std::path::Path> {
    cfg!(target_os = "linux").then_some(std::path::Path::new("/"))
}

/// One RAPL zone's energy between two reads of its `energy_uj`, modulo its own
/// wrap. A counter that went down wrapped at `max_range` (its
/// `max_energy_range_uj`): the energy is what it had left to the wrap plus what
/// it counted since. Without a known range, or with a first read above it, the
/// delta is unknown: `None`. It cannot see more than one wrap in a span —
/// minutes at package power.
fn rapl_zone_delta(before: u64, after: u64, max_range: Option<u64>) -> Option<u64> {
    if after >= before {
        return Some(after - before);
    }
    max_range?.checked_sub(before)?.checked_add(after)
}

/// NVML GPU-energy reader (feature `nvml`). Uses the device's total-energy
/// counter (millijoules since driver load).
#[cfg(feature = "nvml")]
pub struct Nvml {
    nvml: nvml_wrapper::Nvml,
    device_index: u32,
}

#[cfg(feature = "nvml")]
impl Nvml {
    /// Open device 0. `None` when the library or device is absent or the
    /// counter is unsupported — the caller falls down the ladder.
    pub fn open() -> Option<Self> {
        let nvml = nvml_wrapper::Nvml::init().ok()?;
        nvml.device_by_index(0).ok()?.total_energy_consumption().ok()?;
        Some(Self { nvml, device_index: 0 })
    }

    fn read_uj(&self) -> Option<u64> {
        let mj = self.nvml.device_by_index(self.device_index).ok()?.total_energy_consumption().ok()?;
        Some(mj.saturating_mul(1_000))
    }

    /// The board's power draw, in mW, as NVML reports it.
    fn draw_mw(&self) -> Option<u32> {
        self.nvml.device_by_index(self.device_index).ok()?.power_usage().ok()
    }

    /// The board's maximum power-management limit, in mW.
    fn max_limit_mw(&self) -> Option<u32> {
        let limits = self.nvml.device_by_index(self.device_index).ok()?.power_management_limit_constraints().ok()?;
        (limits.max_limit > 0).then_some(limits.max_limit)
    }

    /// One liveness sample: the device's total-energy counter as its one
    /// rail, in its raw millijoules. `None` when the read fails, which the
    /// probe skips.
    fn liveness_sample(&self) -> Option<Vec<(liveness::RailKey, i64)>> {
        let mj = self.nvml.device_by_index(self.device_index).ok()?.total_energy_consumption().ok()?;
        Some(liveness::every_rail(&[(
            format!("nvml device {} total energy", self.device_index),
            i64::try_from(mj).unwrap_or(i64::MAX),
        )]))
    }
}

#[cfg(feature = "nvml")]
impl std::fmt::Debug for Nvml {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("Nvml").field("device_index", &self.device_index).finish()
    }
}

/// The sustained-advance liveness rule (SPEC §5), one rule for every vendor
/// counter this crate reads: a counter's count is a hardware reading only while
/// the counter is live, and live means **every one of its rails kept
/// advancing** over a probe — each in at least [`MIN_LIVE_ADVANCES`] separate
/// sample intervals, in at least 80% of the intervals observed, over at least
/// [`MIN_LIVE_WINDOW`] of wall time. A rail is one cumulative count within a
/// sample: a RAPL package's `energy_uj`, NVML's total-energy counter, an
/// IOReport `CPU Energy` channel. Every rail, because each rung's figure sums
/// every rail it hands the rule — RAPL every package, IOReport every CPU rail
/// (both dies' on a two-die part) — and a figure summing a live rail with a
/// frozen one leaves the frozen rail's share out while claiming the whole
/// domain.
///
/// Kept apart from every counter's FFI, so the rule, its loop and its stopping
/// rule run on scripted samples and a scripted clock in tests, and so the RAPL,
/// NVML and IOReport rungs apply this one rule rather than copies of it. What a
/// rung hands the rule is its own business: IOReport picks its CPU energy rails
/// out of an Energy Model sample; RAPL hands every package counter; NVML its
/// one device counter.
///
/// The thresholds were set against the batch refreshes an unprivileged reader
/// sees on IOReport's CPU rails (see `ioreport::RailWatch`): a count republished
/// in one step, two, or a few, is not a live count, whichever counter it comes
/// from.
#[allow(unsafe_code)]
mod liveness {
    use std::os::raw::{c_int, c_long};
    use std::time::{Duration, Instant};

    use crate::CounterStatus;

    /// CPU time the probing thread burns, by its own CPU clock
    /// ([`thread_cpu_time`]), before each liveness re-sample. Thread CPU time,
    /// not wall time: on a loaded host a wall-clock spin of 25 ms can get a
    /// few milliseconds of CPU, and the rail would be watched while barely
    /// loaded.
    pub(crate) const PROBE_TICK: Duration = Duration::from_millis(25);

    /// The most wall time one tick may take. A thread that cannot get
    /// [`PROBE_TICK`] of CPU in this long (under 5% of a core) stops its tick
    /// here, so a starved probe still ends.
    pub(crate) const PROBE_TICK_WALL_CAP: Duration = Duration::from_millis(500);

    /// In how many separate sample intervals each rail must advance before
    /// it counts as live. Two is not enough: see `ioreport::RailWatch`.
    /// Also the fewest intervals the probe observes before it may call a rail
    /// frozen.
    pub(crate) const MIN_LIVE_ADVANCES: u32 = 5;

    /// The shortest observation window, by wall clock from the first usable
    /// sample, over which a rail may be called live. The batch refreshes seen
    /// were published within 64 ms, so the steps of one cannot fill this
    /// window, nor could those of one spread over twice as long.
    pub(crate) const MIN_LIVE_WINDOW: Duration = Duration::from_millis(300);

    /// Has a rail that advanced in `advancing` of `intervals` intervals
    /// advanced in at least 80% of them? Integer arithmetic, so the boundary is
    /// exact: 4 of 5 is enough, 3 of 4 is not.
    pub(crate) fn sustained(advancing: u32, intervals: u32) -> bool {
        u64::from(advancing) * 5 >= u64::from(intervals) * 4
    }

    /// However slow a counter is, or however many of its samples fail, the
    /// probe stops after this many budgets.
    pub(crate) const PROBE_BUDGET_CAP: u32 = 5;

    /// How many of the ticks a probe asked for one interval of IOReport's rails
    /// may last and still be evidence for the rule. Longer intervals are not
    /// counted, either way: neither their advances, nor the intervals, nor their
    /// time. A vendor counter has no cap ([`probe`]).
    ///
    /// The rule counts intervals, and a rail that steps twice a second steps in
    /// every interval once sampling has slowed to that cadence. On an M3 Ultra
    /// the same rail, burned and sampled by the same code in one quiet process,
    /// was Frozen in 17 of 17 probes ticking at 25, 100 or 250 ms and Live in 12
    /// of 12 ticking at 500 or 800 ms. A contended host slows sampling just so,
    /// and a Live is cached for the process. So a probe that could not sample
    /// near the cadence it asked for has no evidence, and declines: estimated,
    /// never over-claimed.
    ///
    /// Three, from interval streams recorded on real hosts and replayed under each
    /// cap. That M3 Ultra's rail under contention: Live in 57 of 80 streams with no
    /// cap, 13 at eight ticks, 9 at five, 2 at four, none at three. A RAPL counter
    /// that is live: Live in 10 of 10 on a quiet host, 9 of 10 with a spinning thread
    /// for every core, 2 of 10 with twice as many, where declining is the point.
    pub(crate) const MAX_INTERVAL_TICKS: u32 = 3;

    #[cfg(test)]
    thread_local! {
        static HELD: std::cell::Cell<u32> = const { std::cell::Cell::new(0) };
    }

    /// How many intervals this thread's watches have refused as past the cap since
    /// the last call. A test on the real clock asks: with none, every interval
    /// stayed near the probe's cadence, and the rule's exact results hold; with
    /// some, the host held the probe, which may take more samples or decline, and
    /// the run proves nothing about the rule. Test builds only; only the macOS
    /// IOReport tests read it.
    #[cfg(test)]
    #[cfg_attr(not(target_os = "macos"), allow(dead_code))]
    pub(crate) fn take_held() -> u32 {
        HELD.with(|h| h.replace(0))
    }

    /// Count one refused interval ([`take_held`]). Test builds only.
    #[cfg(test)]
    pub(crate) fn note_held() {
        HELD.with(|h| h.set(h.get() + 1));
    }

    /// The probe budget of the counter rungs (RAPL, NVML): one second, as
    /// IOReport's `CPU_RAIL_LIVENESS_BUDGET`. A live counter is called live
    /// about 300 ms in (five intervals in, on a loaded host); the budget only
    /// bounds how long a frozen one is watched. Paid once per process.
    pub(crate) const BUDGET: Duration = Duration::from_millis(1000);

    /// A rail within one sample: its name, and its ordinal among the rails of
    /// that name in the same sample. Names are not unique on every counter
    /// (an M3 Ultra's Energy Model group has 264 duplicated names), and keyed
    /// by name alone, two same-named rails stepping together in one refresh
    /// would count as two advances of one rail.
    #[derive(Debug, Clone, PartialEq, Eq)]
    pub(crate) struct RailKey {
        pub(crate) name: String,
        pub(crate) ordinal: u32,
    }

    /// The channels of one sample whose names `pick` accepts, each keyed by
    /// [`RailKey`], with its absolute raw value. Item by item: no arithmetic
    /// across channels.
    pub(crate) fn rails_where(sample: &[(String, i64)], pick: fn(&str) -> bool) -> Vec<(RailKey, i64)> {
        let mut rails: Vec<(RailKey, i64)> = Vec::new();
        for (name, raw) in sample {
            if pick(name) {
                let ordinal = rails.iter().filter(|(k, _)| k.name == *name).count() as u32;
                rails.push((RailKey { name: name.clone(), ordinal }, *raw));
            }
        }
        rails
    }

    /// Every channel of one sample as a rail: for a counter whose every
    /// channel is a count of the domain it claims (RAPL's packages, NVML's one
    /// counter).
    pub(crate) fn every_rail(sample: &[(String, i64)]) -> Vec<(RailKey, i64)> {
        rails_where(sample, |_| true)
    }

    /// The liveness rule over plain samples of rails, kept apart from the FFI
    /// so all of it, including the pairing of each sample with the previous
    /// one, runs on scripted samples in tests.
    ///
    /// A counter is live only when **every** rail seen keeps advancing, each
    /// on its own count: it advanced in at least [`MIN_LIVE_ADVANCES`]
    /// separate sample intervals, those are at least 80% of all the intervals
    /// observed so far ([`sustained`]), and the window observed so far spans
    /// at least [`MIN_LIVE_WINDOW`] of wall time from the first usable sample.
    /// The three are checked after each interval, and the counter is live from
    /// the first interval at which all three hold for every rail. A counter
    /// with no rail is never live.
    ///
    /// Every rail, not one: each rung sums every rail it hands the rule into
    /// its figure. On a two-die part (an M3 Ultra's `DIE_0_CPU Energy` and
    /// `DIE_1_CPU Energy`), one live die beside a frozen one would give a
    /// figure that misses the frozen die while claiming the whole CPU, and on a
    /// two-package RAPL host, one that misses a package. A rail seen in only
    /// some samples is still counted against every interval observed, so one
    /// missing from many of them fails the share and holds the counter frozen:
    /// a rail that comes and goes is not a live count either.
    ///
    /// Each condition closes a way for a refresh to pass. Five advances: a
    /// refresh is published in one step, two, or a few. 80% of the intervals: the
    /// steps of a refresh sit together, and are a small share of any window
    /// that also holds the flat intervals around them. 300 ms: a refresh
    /// published in five quick steps at the very start of a window is 100% of a
    /// 155 ms window, but not of a 300 ms one. A live rail advances in nearly
    /// every interval, so it meets all three about 300 ms in, or after five
    /// intervals on a host loaded enough that five take longer. Counting per
    /// rail keeps a step on each of several rails from adding up to a false
    /// Live.
    ///
    /// Each interval is a sample and the one **before** it. Compared with the
    /// first sample instead, a rail that stepped once would show a rise in
    /// every interval after the step, and one refresh would read as live.
    #[derive(Debug, Clone)]
    pub(crate) struct Advances {
        /// Sample intervals observed so far: pairs of consecutive usable samples.
        pub(crate) intervals: u32,
        /// The longest interval that counts: [`MAX_INTERVAL_TICKS`] of the tick
        /// the probe asked for.
        longest: Duration,
        /// When the last usable sample was taken, by the probe's clock.
        last_at: Option<Duration>,
        /// Intervals that counted: those no longer than `longest`.
        pub(crate) counted: u32,
        /// Those intervals' wall time.
        pub(crate) counted_for: Duration,
        /// The previous usable sample's rails, which the next one is compared
        /// with.
        prev: Option<Vec<(RailKey, i64)>>,
        /// Every rail seen, with the number of intervals that counted in which
        /// it advanced.
        pub(crate) rails: Vec<(RailKey, u32)>,
        /// When the first usable sample was taken, by the probe's clock: where
        /// the window starts.
        first_at: Option<Duration>,
        /// How much wall time the window spans so far: from the first usable
        /// sample to the latest.
        pub(crate) window: Duration,
        /// The longest interval observed, counted or not. Recorded, never
        /// decided on.
        pub(crate) longest_interval: Duration,
        /// Set at the first interval after which every rail met all three
        /// conditions, and never unset.
        live: bool,
    }

    impl Default for Advances {
        /// The rule with no cap on an interval: a vendor counter's ([`probe`]).
        fn default() -> Self {
            Self::asking(Duration::MAX)
        }
    }

    impl Advances {
        /// The rule for a probe asking for `tick` between two samples.
        pub(crate) fn asking(tick: Duration) -> Self {
            Self {
                intervals: 0,
                longest: tick.saturating_mul(MAX_INTERVAL_TICKS),
                last_at: None,
                counted: 0,
                counted_for: Duration::ZERO,
                prev: None,
                rails: Vec::new(),
                first_at: None,
                window: Duration::ZERO,
                longest_interval: Duration::ZERO,
                live: false,
            }
        }

        /// Fold in the next usable sample's rails, taken at `at` by the probe's
        /// wall clock. The first only sets the baseline, and starts the window.
        /// Each later one closes an interval with the sample before it, and a
        /// rail advanced over that interval when its raw value rose. A rail is
        /// counted at most once per interval. A rail whose value FELL did not
        /// advance: a cumulative counter that goes down was reset or wrapped,
        /// and that is not energy spent. A rail missing from the previous
        /// sample has nothing to be compared with, so this sample only sets its
        /// baseline. An interval longer than `longest` is observed, but is no
        /// evidence that a rail kept advancing ([`MAX_INTERVAL_TICKS`]). After
        /// each interval, the rule is checked.
        pub(crate) fn observe(&mut self, cur: Vec<(RailKey, i64)>, at: Duration) {
            for (key, _) in &cur {
                if !self.rails.iter().any(|(k, _)| k == key) {
                    self.rails.push((key.clone(), 0));
                }
            }
            let first_at = *self.first_at.get_or_insert(at);
            self.window = at.saturating_sub(first_at);
            let took = at.saturating_sub(self.last_at.replace(at).unwrap_or(at));
            if let Some(prev) = &self.prev {
                self.intervals += 1;
                self.longest_interval = self.longest_interval.max(took);
                let counts = took <= self.longest;
                if counts {
                    self.counted += 1;
                    self.counted_for += took;
                }
                #[cfg(test)]
                if !counts {
                    note_held();
                }
                for (key, now) in &cur {
                    let rose = counts && prev.iter().any(|(k, before)| k == key && now > before);
                    if let Some((_, count)) = self.rails.iter_mut().find(|(k, _)| k == key) {
                        *count += u32::from(rose);
                    }
                }
                // Only what counted: a burst's few steps beside one long interval
                // must not fill the window the long interval spanned.
                let intervals = self.counted;
                // Every rail, and at least one: `all` over no rails is true,
                // and a sample with no rail in it is no evidence of anything.
                self.live |= self.counted_for >= MIN_LIVE_WINDOW
                    && !self.rails.is_empty()
                    && self
                        .rails
                        .iter()
                        .all(|&(_, advancing)| advancing >= MIN_LIVE_ADVANCES && sustained(advancing, intervals));
            }
            self.prev = Some(cur);
        }

        /// Has every rail kept advancing: enough advances, a high enough
        /// share of the intervals, over a long enough window?
        pub(crate) fn is_live(&self) -> bool {
            self.live
        }

        /// Keep sampling? Until the rail proves live, or until `budget` has
        /// elapsed **and** at least [`MIN_LIVE_ADVANCES`] intervals counted, so
        /// a live rail could have shown that many advances (slow samples must
        /// not make a live rail look frozen while the probe can still get near
        /// its cadence) — and never past [`PROBE_BUDGET_CAP`] budgets.
        pub(crate) fn wants_more(&self, elapsed: Duration, budget: Duration) -> bool {
            !self.is_live()
                && elapsed < budget * PROBE_BUDGET_CAP
                && (elapsed < budget || self.counted < MIN_LIVE_ADVANCES)
        }

        /// What the rule held when the probe stopped, for the record.
        #[cfg_attr(not(target_os = "macos"), allow(dead_code))]
        pub(crate) fn evidence(&self) -> ProbeEvidence {
            ProbeEvidence {
                advances: self.rails.iter().map(|(k, n)| (k.name.clone(), k.ordinal, *n)).collect(),
                intervals: self.intervals,
                counted: self.counted,
                counted_for: self.counted_for,
                window: self.window,
                longest_interval: self.longest_interval,
            }
        }
    }

    /// What one liveness probe's rule held when the probe stopped: the
    /// evidence behind its verdict, kept beside the cached IOReport status
    /// ([`crate::ioreport_probe_evidence`]) so that a verdict the process
    /// cached can be checked from a log long after the run that made it.
    #[derive(Debug, Clone, PartialEq, Eq)]
    #[cfg_attr(not(target_os = "macos"), allow(dead_code))]
    pub(crate) struct ProbeEvidence {
        /// Every rail seen: its channel name, its ordinal among the channels
        /// of that name, and in how many intervals that counted it advanced.
        pub(crate) advances: Vec<(String, u32, u32)>,
        /// Intervals observed.
        pub(crate) intervals: u32,
        /// Of those, the intervals that counted: none longer than
        /// [`MAX_INTERVAL_TICKS`] ticks.
        pub(crate) counted: u32,
        /// The counted intervals' wall time, which the rule holds to
        /// [`MIN_LIVE_WINDOW`].
        pub(crate) counted_for: Duration,
        /// Wall time from the first usable sample to the last.
        pub(crate) window: Duration,
        /// The longest interval observed, counted or not.
        pub(crate) longest_interval: Duration,
    }

    impl ProbeEvidence {
        /// Whether the rule holds of this record: at least one rail, every
        /// one with enough advances and a high enough share of the counted
        /// intervals, over enough counted time. The probe stops as soon as its
        /// rule holds, and a rule that never held did not hold at the last
        /// interval, so for a probe's record this is true exactly when its
        /// verdict is Live.
        #[cfg_attr(not(test), allow(dead_code))]
        pub(crate) fn rule_holds(&self) -> bool {
            self.counted_for >= MIN_LIVE_WINDOW
                && !self.advances.is_empty()
                && self
                    .advances
                    .iter()
                    .all(|&(_, _, n)| n >= MIN_LIVE_ADVANCES && sustained(n, self.counted))
        }
    }

    /// The rule's loop, generic over where samples come from, what happens
    /// between them and the clock, so tests drive it with scripted samples and
    /// a scripted clock exactly as the probes drive it. Take a sample and read
    /// the clock; hand the rule the sample with that reading; stop when
    /// [`Advances::wants_more`] says so; otherwise `tick` and sample again. A
    /// sample that fails is skipped, so the next usable one is compared with
    /// the last usable one. `elapsed` is the wall time since the probe started,
    /// read once after each sample: that one reading is both the time the rule
    /// is handed with the sample and the time the stopping rule is asked about.
    /// `asked` is what `tick` asks for between two samples.
    pub(crate) fn watch(
        mut sample: impl FnMut() -> Option<Vec<(RailKey, i64)>>,
        mut tick: impl FnMut(),
        asked: Duration,
        mut elapsed: impl FnMut() -> Duration,
        budget: Duration,
    ) -> Advances {
        let mut advances = Advances::asking(asked);
        loop {
            let got = sample();
            let now = elapsed();
            if let Some(rails) = got {
                advances.observe(rails, now);
            }
            if !advances.wants_more(now, budget) {
                return advances;
            }
            tick();
        }
    }

    /// One liveness probe of a counter rung: `open` the counter; if it opens,
    /// [`watch`] its samples, `tick` between them, by the clock `now`, for
    /// `budget`, with no cap on an interval: each vendor counter publishes at
    /// least as often as its probe ticks, so sampling slowed by contention shows
    /// nothing a quiet probe would not, and a caller's load sets its own cadence.
    /// `None` when it does not open: then nothing is sampled and
    /// nothing ticks. The budget starts once the counter is open, so a slow
    /// open costs the probe none of it. Generic over each part, so the tests
    /// drive this very function with a scripted counter, tick and clock; the
    /// rungs' cached probes pass the real ones.
    pub(crate) fn probe<C>(
        open: impl FnOnce() -> Option<C>,
        sample: impl Fn(&C) -> Option<Vec<(RailKey, i64)>>,
        tick: impl FnMut(),
        now: impl Fn() -> Instant,
        budget: Duration,
    ) -> Option<Advances> {
        let counter = open()?;
        let started = now();
        Some(watch(|| sample(&counter), tick, Duration::MAX, || now().saturating_duration_since(started), budget))
    }

    /// The status a counter probe reports. No probe (the counter did not
    /// open) and no interval observed (no two usable samples in five budgets)
    /// are both `Unavailable`, never `Live`.
    pub(crate) fn status_of(probed: Option<&Advances>) -> CounterStatus {
        match probed {
            None => CounterStatus::Unavailable,
            Some(a) if a.intervals == 0 => CounterStatus::Unavailable,
            Some(a) if a.is_live() => CounterStatus::Live,
            Some(_) => CounterStatus::Frozen,
        }
    }

    /// `struct timespec` on 64-bit macOS and Linux.
    #[repr(C)]
    struct Timespec {
        tv_sec: c_long,
        tv_nsec: c_long,
    }

    /// `CLOCK_THREAD_CPUTIME_ID`: 16 in macOS `<time.h>`, 3 in Linux
    /// `<linux/time.h>`.
    #[cfg(target_os = "macos")]
    const CLOCK_THREAD_CPUTIME_ID: c_int = 16;
    #[cfg(any(target_os = "linux", target_os = "android"))]
    const CLOCK_THREAD_CPUTIME_ID: c_int = 3;

    #[cfg(any(target_os = "macos", target_os = "linux", target_os = "android"))]
    unsafe extern "C" {
        fn clock_gettime(clock_id: c_int, tp: *mut Timespec) -> c_int;
    }

    /// CPU time this thread has used, user and system, by
    /// `clock_gettime(CLOCK_THREAD_CPUTIME_ID)`. `None` if the clock cannot be
    /// read, and on a platform without that clock. The one thread clock of the
    /// probes: [`burn`] and the IOReport probe's clocks both read it.
    pub(crate) fn thread_cpu_time() -> Option<Duration> {
        #[cfg(any(target_os = "macos", target_os = "linux", target_os = "android"))]
        {
            let mut ts = Timespec { tv_sec: 0, tv_nsec: 0 };
            let rc = unsafe { clock_gettime(CLOCK_THREAD_CPUTIME_ID, &mut ts) };
            (rc == 0).then(|| Duration::new(ts.tv_sec as u64, ts.tv_nsec as u32))
        }
        #[cfg(not(any(target_os = "macos", target_os = "linux", target_os = "android")))]
        {
            let _ = Timespec { tv_sec: 0, tv_nsec: 0 };
            None
        }
    }

    /// Spin this thread until it has used `cpu` of CPU time by its own CPU
    /// clock, or until `wall_cap` of wall time has passed, whichever comes
    /// first. However loaded the host, the thread has then burned `cpu`, unless
    /// it got under `cpu / wall_cap` of a core. With no readable thread clock
    /// only the wall cap ends the spin: slower, never shorter.
    pub(crate) fn burn(cpu: Duration, wall_cap: Duration) {
        let wall = Instant::now();
        let start = thread_cpu_time();
        let mut acc: u64 = 0;
        loop {
            for _ in 0..1_000 {
                acc = std::hint::black_box(acc.wrapping_add(1));
            }
            let used = match (start, thread_cpu_time()) {
                (Some(a), Some(b)) => b.saturating_sub(a),
                _ => Duration::ZERO,
            };
            if used >= cpu || wall.elapsed() >= wall_cap {
                return;
            }
        }
    }

    /// The real probes' tick for a CPU-energy counter: spin until this thread
    /// has burned [`PROBE_TICK`] of its own CPU time, or
    /// [`PROBE_TICK_WALL_CAP`] of wall time has passed.
    pub(crate) fn burn_tick() {
        burn(PROBE_TICK, PROBE_TICK_WALL_CAP);
    }
}

/// The liveness status of a single vendor energy counter rung — RAPL's
/// package counters, NVML's total-energy counter, the kernel's per-process CPU
/// energy count — as its probe found it on this host. Probed once per process
/// and cached; see [`rapl_status`], [`nvml_status`] and
/// [`process_energy_status`]. Only [`CounterStatus::Live`] admits the rung
/// (SPEC §5).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CounterStatus {
    /// The counter could not be opened or read — absent (not this platform,
    /// no such device, the feature not built, for RAPL no zone named
    /// `package-<n>`), unreadable (a locked-down sysfs), or it gave fewer than
    /// two usable samples in five budgets. Never selected.
    Unavailable,
    /// The counter opened, but not every rail of it kept advancing while the
    /// probe ran: one held, or stepped a few times together — republished in
    /// lumps, not a live count. Never selected: a lump landing in one span
    /// would be graded a hardware reading of that span's work, and a held rail
    /// beside live ones would be left out of a figure that claims it.
    Frozen,
    /// The counter kept advancing, but a GPU counter (NVML's) ran faster than
    /// its board can draw power over the probe: past 1.5 times the board's
    /// maximum power limit, or past twice the board's own power draw plus 5 W.
    /// It is not counting the board's energy, so a figure from it would debit
    /// energy the device never spent. Seen on an RTX 4050 Laptop GPU (driver
    /// 595.84), whose counter runs at 4 to 30 times the board's draw while it
    /// is polled. Never selected.
    ///
    /// By how much it overran is in [`GpuPlausibility::CounterOverRate`], which
    /// carries the rate and the bound it broke: a counter 1.1 times over a
    /// bound and one 20 times over are the same status but not the same
    /// finding, and tuning the margins later needs the figures.
    ///
    /// A counter that accrued far less than its board drew is `Implausible`
    /// too ([`GpuPlausibility::CounterUnderRate`]), and that is the dangerous
    /// direction: graded a reading, it would spend a budget it is not
    /// measuring.
    Implausible,
    /// The counter kept advancing and could not be judged, because the board's
    /// own power telemetry was unusable over the probe: a draw reading past the
    /// board's own maximum power limit (an RTX 4050 Laptop GPU reports about
    /// 590 W for a second after it wakes).
    ///
    /// Split out from [`CounterStatus::Implausible`], which used to cover this
    /// and whose doc then asserted "it is not counting the board's energy" —
    /// a conclusion this case does not support. The yardstick is broken, not
    /// necessarily the counter. Never selected either way: unjudgeable is not
    /// admissible, and erring toward declining is the safe direction. The
    /// distinction is the diagnosis an operator gets, which is the difference
    /// between replacing a counter and waiting for the board to settle.
    Unjudgeable,
    /// Every rail of the counter kept advancing while the probe ran: each in
    /// at least five separate sample intervals, making up at least 80% of
    /// those observed, over at least 300 ms. The rung is selected.
    Live,
}

/// Whether a counter's liveness status admits its rung: [`CounterStatus::Live`]
/// and nothing else. The one gate the RAPL and NVML rungs go through, pure so
/// that every status is checked in a test.
fn admits_counter(status: CounterStatus) -> bool {
    matches!(status, CounterStatus::Live)
}

/// A rung's counter, opened only when its status admits the rung: `open` is
/// not even called otherwise. What [`Meter::detect`] selects a counter rung
/// with.
fn select<C>(status: CounterStatus, open: impl FnOnce() -> Option<C>) -> Option<C> {
    if admits_counter(status) {
        open()
    } else {
        None
    }
}

/// How many times the RAPL liveness probe has run in this process: the first
/// thing [`rapl_host_status`] does. [`rapl_status`] caches its answer, so this
/// never passes one; the fresh-process pin counts it.
static RAPL_PROBE_RUNS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// [`RAPL_PROBE_RUNS`].
#[cfg_attr(not(test), allow(dead_code))]
fn rapl_probe_runs() -> usize {
    RAPL_PROBE_RUNS.load(std::sync::atomic::Ordering::SeqCst)
}

/// This host's RAPL status, probed once per process and cached.
///
/// [`Meter::detect`] selects the RAPL rung only when this is
/// [`CounterStatus::Live`]: every package counter (the `energy_uj` of each
/// top-level `intel-rapl:N` zone whose `name` is `package-<n>`, or
/// `package-<n>-die-<m>` for each die of a multi-die Intel package) kept advancing
/// while the probing thread burned CPU, each in at least five sample
/// intervals, at least 80% of them, over at least 300 ms — the rule IOReport's
/// CPU rails are held to. Every package, because a span's figure
/// sums them all: one live package beside a frozen one would leave the frozen
/// package's energy out of a figure graded whole. A counter that holds, or is
/// republished in lumps (a virtualised powercap tree can be either), is
/// declined to the default-power estimate. Only the package zones are probed, as
/// only they are summed: a live `psys` or `dram` zone beside a held package
/// does not make the counter live. Where powercap lists no package zone, the
/// packages are their energy-status MSRs ([`Rapl::open`]), probed by the same
/// rule. Where neither reads — not Linux, no RAPL, an `energy_uj` only root may
/// read, or no package zone and no MSR this process may read (no `msr` module,
/// no `CAP_SYS_RAWIO`) — it is [`CounterStatus::Unavailable`] without burning
/// anything, as RAPL was declined before ([`rapl_access`] says which). The first call on a
/// host with a readable tree burns about 300 ms of the calling thread's CPU
/// (one second if the counter is not live).
pub fn rapl_status() -> CounterStatus {
    static STATUS: std::sync::OnceLock<CounterStatus> = std::sync::OnceLock::new();
    *STATUS.get_or_init(rapl_host_status)
}

/// The real RAPL probe: the real opener, sampler and tick. Counts itself,
/// then composes; its only caller is the cache in [`rapl_status`].
fn rapl_host_status() -> CounterStatus {
    RAPL_PROBE_RUNS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    rapl_status_on(Rapl::open)
}

/// The RAPL probe on a given opener: [`liveness::probe`] with RAPL's sampler,
/// the CPU-burning tick and the real clock, for one budget. The tests run it on
/// fake powercap trees.
fn rapl_status_on(open: impl FnOnce() -> Option<Rapl>) -> CounterStatus {
    liveness::status_of(
        liveness::probe(open, Rapl::liveness_sample, liveness::burn_tick, Instant::now, liveness::BUDGET).as_ref(),
    )
}

/// Whether this process can **read** this host's RAPL counter, as distinct
/// from whether the counter is advancing.
///
/// [`Rapl::open`] answers neither question on its own: it returns `None` for a
/// host with no powercap tree, a host whose package zone is root-only, and a
/// host whose counter is garbled alike. Those are different facts about the
/// world, and one of them is a fixable permission gap while another is an
/// absence of hardware — so [`survey`] needs them apart before it can report a
/// status honestly.
///
/// Linux has restricted `energy_uj` to privileged readers since the power
/// side-channel disclosures of 2020. A representative host carries
/// `mode 0440 root:energy`, so a process outside that group reads `EACCES` —
/// **not** `ENOENT`. The file is plainly there.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RaplAccess {
    /// A package zone is here and this process can read its `energy_uj`.
    ///
    /// This says nothing about the counter advancing; that is
    /// [`rapl_status`]'s question.
    Readable,
    /// A package zone is here and its `energy_uj` cannot be read for want of
    /// privilege. The counter exists and this process may not read it.
    NeedsPrivilege,
    /// No package zone is reachable here at all.
    NoInterface,
}

/// This host's RAPL accessibility: its powercap package zones', or, on Linux
/// where powercap exposes none, its packages' energy-status MSRs'
/// ([`Rapl::open`]). An MSR this process may not open — the `msr` driver's
/// device files need `CAP_SYS_RAWIO` and read access — is
/// [`RaplAccess::NeedsPrivilege`]; no `msr` module, a CPU whose MSRs this crate
/// does not know, or a power-unit MSR that reads zero (a hypervisor's
/// stand-in) is [`RaplAccess::NoInterface`].
#[must_use]
pub fn rapl_access() -> RaplAccess {
    rapl_access_from(std::path::Path::new(POWERCAP_ROOT), host_root(), read_msr)
}

/// [`rapl_access`] on the powercap tree at `powercap` and, where it exposes no
/// package zone, the MSRs under the filesystem root `root`, read with
/// `read_msr`, so tests run on fake trees and inject permission errors.
fn rapl_access_from(
    powercap: &std::path::Path,
    root: Option<&std::path::Path>,
    read_msr: impl Fn(&std::path::Path, u64) -> std::io::Result<u64>,
) -> RaplAccess {
    match (rapl_access_in(powercap), root) {
        (RaplAccess::NoInterface, Some(root)) => msr_access_with(root, read_msr),
        (access, _) => access,
    }
}

/// Whether this process can read every counter domain's energy-status MSR
/// under the filesystem root `root` — each die on Intel, each package on AMD
/// and Hygon, the domains [`Rapl::open`] reads — each on the domain's first
/// CPU, with `read` standing in for [`read_msr`]. As for powercap, a permission
/// failure on any domain decides the answer, even beside a readable one; any
/// other failure (no device file, a register the CPU does not implement) or a
/// zero unit is no interface.
fn msr_access_with(root: &std::path::Path, read: impl Fn(&std::path::Path, u64) -> std::io::Result<u64>) -> RaplAccess {
    let Some((registers, first)) = msr_host(root) else {
        return RaplAccess::NoInterface;
    };
    let denied = |e: &std::io::Error| e.kind() == std::io::ErrorKind::PermissionDenied;
    let mut readable = true;
    for cpu in first.values() {
        let device = root.join(format!("dev/cpu/{cpu}/msr"));
        match read(&device, registers.unit) {
            Ok(unit) if msr_unit_shift(unit).is_some() => match read(&device, registers.energy) {
                Ok(_) => {}
                Err(e) if denied(&e) => return RaplAccess::NeedsPrivilege,
                Err(_) => readable = false,
            },
            Ok(_) => readable = false,
            Err(e) if denied(&e) => return RaplAccess::NeedsPrivilege,
            Err(_) => readable = false,
        }
    }
    if readable { RaplAccess::Readable } else { RaplAccess::NoInterface }
}

/// [`rapl_access`] on the powercap tree at `root`, so tests run on fake trees.
fn rapl_access_in(root: &std::path::Path) -> RaplAccess {
    rapl_access_with(root, |p| std::fs::read_to_string(p))
}

/// [`rapl_access`] over an injected file reader, so a permission error can be
/// tested without `chmod` — which would prove nothing in a container running
/// as root, where every mode is readable.
///
/// A permission failure on **any** package zone decides the answer, even
/// beside a readable one. That follows [`Rapl::open_in`]'s own rule that a
/// figure claims the whole CPU and so is every package zone or none: where one
/// package cannot be read, the reader does not open, and the reason it did not
/// is privilege.
fn rapl_access_with(
    root: &std::path::Path,
    read: impl Fn(&std::path::Path) -> std::io::Result<String>,
) -> RaplAccess {
    let dir = match std::fs::read_dir(root) {
        Ok(dir) => dir,
        // The tree itself unreadable for want of privilege is the same finding
        // as a zone that is; anything else here is an absent interface.
        Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
            return RaplAccess::NeedsPrivilege;
        }
        Err(_) => return RaplAccess::NoInterface,
    };

    let mut readable = false;
    for entry in dir.flatten() {
        let dir_name = entry.file_name();
        if rapl_top_level_zone(&dir_name.to_string_lossy()).is_none() {
            continue;
        }
        match read(&entry.path().join("name")) {
            Ok(name) => {
                if !is_rapl_package_name(&name) {
                    continue;
                }
            }
            // A zone this process cannot even identify may be a package, and
            // the reason it could not is privilege.
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                return RaplAccess::NeedsPrivilege;
            }
            Err(_) => continue,
        }
        match read(&entry.path().join("energy_uj")) {
            Ok(_) => readable = true,
            Err(e) if e.kind() == std::io::ErrorKind::PermissionDenied => {
                return RaplAccess::NeedsPrivilege;
            }
            Err(_) => continue,
        }
    }
    if readable { RaplAccess::Readable } else { RaplAccess::NoInterface }
}

/// How many times the NVML liveness probe has run in this process. Always 0
/// without the `nvml` feature, which has no probe.
#[cfg_attr(not(all(test, feature = "nvml")), allow(dead_code))]
fn nvml_probe_runs() -> usize {
    #[cfg(feature = "nvml")]
    {
        NVML_PROBE_RUNS.load(std::sync::atomic::Ordering::SeqCst)
    }
    #[cfg(not(feature = "nvml"))]
    {
        0
    }
}

#[cfg(feature = "nvml")]
static NVML_PROBE_RUNS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// How long the NVML probe waits between samples. NVML's counter is the GPU's,
/// and burning this thread's CPU does not load the GPU, so the probe does not
/// burn: it waits, and a live counter advances on the device's own draw (a
/// powered GPU never draws zero). The wait is longer than the CPU probes' tick
/// so that a counter the driver refreshes up to every 100 ms still advances in
/// every interval; one refreshed less often fails the 80% share and is
/// declined — estimated, never over-claimed.
#[cfg(feature = "nvml")]
const NVML_PROBE_WAIT: std::time::Duration = std::time::Duration::from_millis(100);

/// This host's NVML status, probed once per process and cached. Always
/// [`CounterStatus::Unavailable`] without the `nvml` feature.
///
/// [`Meter::detect`] selects the NVML rung only when this is
/// [`CounterStatus::Live`]: device 0's total-energy counter advanced in at
/// least five sample intervals, at least 80% of them, over at least 300 ms,
/// and over that window counted no faster than the board can draw
/// ([`plausible_gpu_counter`], with the board's power draw read at every
/// sample and its maximum power limit). The probe has no way to load the
/// GPU, so liveness shows the counter is published continuously, not that it
/// tracks a load; a counter that holds or steps in lumps is declined, and one
/// that runs faster than its board draws is [`CounterStatus::Implausible`].
/// The first call on a host where NVML opens waits about half a second (one
/// second if the counter is not live).
pub fn nvml_status() -> CounterStatus {
    #[cfg(feature = "nvml")]
    {
        static STATUS: std::sync::OnceLock<CounterStatus> = std::sync::OnceLock::new();
        *STATUS.get_or_init(|| {
            NVML_PROBE_RUNS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            let seen = std::cell::RefCell::new(GpuWatch::default());
            let probed = liveness::probe(
                || {
                    let n = Nvml::open()?;
                    seen.borrow_mut().ceiling_mw = n.max_limit_mw();
                    Some(n)
                },
                |n: &Nvml| {
                    let sample = n.liveness_sample();
                    let mj = sample.as_ref().and_then(|rails| rails.first()).map(|(_, raw)| *raw);
                    seen.borrow_mut().saw(mj.and_then(|mj| u64::try_from(mj).ok()), n.draw_mw(), Instant::now());
                    sample
                },
                || std::thread::sleep(NVML_PROBE_WAIT),
                Instant::now,
                liveness::BUDGET,
            );
            nvml_status_of(probed.as_ref(), &seen.into_inner())
        })
    }
    #[cfg(not(feature = "nvml"))]
    {
        CounterStatus::Unavailable
    }
}

/// What the NVML probe saw of the board beside its counter: the counter's
/// first and last reading (mJ) and when, the board's power draw read with
/// every sample, and its maximum power limit.
#[derive(Debug, Default, Clone)]
#[cfg_attr(not(any(test, feature = "nvml")), allow(dead_code))]
struct GpuWatch {
    first: Option<(u64, Instant)>,
    last: Option<(u64, Instant)>,
    draws_mw: Vec<u32>,
    ceiling_mw: Option<u32>,
}

#[cfg_attr(not(any(test, feature = "nvml")), allow(dead_code))]
impl GpuWatch {
    /// Fold in one sample: the counter's reading, if it read, and the
    /// board's draw, if that read, at `at`.
    fn saw(&mut self, mj: Option<u64>, draw_mw: Option<u32>, at: Instant) {
        if let Some(mj) = mj {
            self.first.get_or_insert((mj, at));
            self.last = Some((mj, at));
        }
        self.draws_mw.extend(draw_mw);
    }
}

/// How far past its board's maximum power limit a GPU energy counter may run,
/// on average over a probe's window, as a fraction (3/2): a board can draw
/// past its limit for milliseconds, not on average over a third of a second.
const GPU_CEILING_MARGIN: (u128, u128) = (3, 2);

/// How much faster than its board's own power draw a GPU energy counter may
/// run over a probe's window: twice the draw's mean over the samples, plus
/// [`GPU_DRAW_SLACK_MW`]. The draw is a one-second average, so a load that
/// changed during the window can leave it behind the counter, but not by a
/// factor of two at a probe.
const GPU_DRAW_FACTOR: u128 = 2;

/// NVML's documented accuracy of a board's power draw, ±5 W, in mW.
const GPU_DRAW_SLACK_MW: u128 = 5_000;

/// How far **below** its board's mean draw a counter may accrue before it is
/// refuted: a shortfall of more than this factor, after [`GPU_DRAW_SLACK_MW`]
/// is taken off the draw, is no count of the board's energy.
///
/// The bound has to exist in this direction because **under-reporting is the
/// unsafe direction at an energy ceiling** (SPEC §5): it admits work the
/// budget cannot cover. The ceiling bounds only catch a counter running
/// *fast*, which fails safe. A counter republished in lumps and sampled across
/// its republish period reads low rather than frozen, so liveness alone does
/// not see it. It is looser than [`GPU_DRAW_FACTOR`] because the draw is a
/// one-second average a bursty load integrates below, and the slack comes off
/// before the division so an idle board (at or under the slack) makes no
/// finding. The same factor as `jouleclaw-energy`'s, `sandbox-meter`'s and
/// `eoc-meter`'s, so a counter one meter declines another does not admit.
const GPU_UNDER_FACTOR: u128 = 4;

/// Whether a GPU energy counter that counted `energy_mj` over `window`
/// plausibly counted its board's energy, beside the board's power draw
/// `draws_mw` read with the samples and its maximum power limit `ceiling_mw`.
/// Not when the counter ran past [`GPU_CEILING_MARGIN`] of the limit, or a
/// draw reading did (the board's own telemetry then is not a reading either:
/// an RTX 4050 Laptop GPU reports 590 W for about a second after it wakes),
/// or the counter ran past [`GPU_DRAW_FACTOR`] times the mean draw plus
/// [`GPU_DRAW_SLACK_MW`], or fell short of that mean, less the slack, by more
/// than [`GPU_UNDER_FACTOR`]. A bound whose reading is missing is not applied.
///
/// Liveness says the counter is republished continuously; this says what it
/// republishes is the board's energy. On the RTX 4050 Laptop GPU (driver
/// 595.84) the total-energy counter runs several times faster than the
/// board draws for as long as it is polled: at this probe's 100 ms wait it
/// ran at 58-305 W while the board drew 5-14 W against a 65 W limit.
/// Which bound a GPU counter's rate broke.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GpuBound {
    /// [`GPU_CEILING_MARGIN`] of the board's maximum power limit.
    PowerLimit,
    /// [`GPU_DRAW_FACTOR`] times the board's mean draw plus
    /// [`GPU_DRAW_SLACK_MW`].
    MeanDraw,
}

/// What the plausibility check found, with the figures it found it from.
///
/// A `bool` was the whole of this, and it threw away everything an operator or
/// an auditor needs: which of the bounds broke, by how much, and the rate it
/// broke them at. A counter 1.1 times over a bound and one 20 times over were
/// the same answer. The figures also make the judgement reproducible — the
/// margins are constants in this crate, and re-grading a past finding against
/// a different margin is only possible if the rate survived the check.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum GpuPlausibility {
    /// The counter's rate sits inside every bound whose reading was present.
    Plausible {
        /// The rate the counter implies over the window, in milliwatts.
        rate_mw: u64,
    },
    /// The counter ran faster than the board can draw.
    CounterOverRate {
        /// The rate the counter implies over the window, in milliwatts.
        rate_mw: u64,
        /// The bound it broke, in milliwatts.
        bound_mw: u64,
        /// Which bound that was.
        bound: GpuBound,
    },
    /// The counter accrued far less energy than the board's own telemetry says
    /// it drew: the dangerous finding, because a counter reading low is graded
    /// `HwShunt` and then spends a budget it is not measuring, while it still
    /// advances, so liveness calls it live.
    CounterUnderRate {
        /// The rate the counter implies over the window, in milliwatts.
        rate_mw: u64,
        /// The floor it fell below, in milliwatts.
        floor_mw: u64,
        /// The board's mean usable draw the floor was taken from, in
        /// milliwatts: the yardstick, so the judgement can be re-made.
        mean_draw_mw: u64,
    },
    /// The board's own telemetry read past the board's own power limit, so
    /// there is no yardstick to judge the counter against. An indeterminate,
    /// not a finding about the counter — see [`CounterStatus::Unjudgeable`].
    BoardTelemetryUnusable {
        /// The offending draw reading, in milliwatts.
        draw_mw: u64,
        /// The limit it exceeded (the margin-adjusted cap), in milliwatts.
        limit_mw: u64,
    },
}

impl GpuPlausibility {
    /// Whether the counter was judged to be counting its board's energy.
    ///
    /// `false` for an indeterminate as well as for an overrun: unjudgeable is
    /// not admissible, and erring toward declining is the safe direction. Use
    /// the variant itself to tell the two apart.
    pub fn plausible(&self) -> bool {
        matches!(self, GpuPlausibility::Plausible { .. })
    }
}

fn plausible_gpu_counter(
    energy_mj: u64,
    window: std::time::Duration,
    draws_mw: &[u32],
    ceiling_mw: Option<u32>,
) -> GpuPlausibility {
    let ns = window.as_nanos().max(1);
    // mJ per second is mW.
    let rate_mw = u128::from(energy_mj) * 1_000_000_000 / ns;
    let clamp = |v: u128| u64::try_from(v).unwrap_or(u64::MAX);
    let cap = ceiling_mw
        .filter(|&l| l > 0)
        .map(|l| u128::from(l) * GPU_CEILING_MARGIN.0 / GPU_CEILING_MARGIN.1);

    // A draw reading past the board's own limit is not a reading: an RTX 4050
    // Laptop GPU reports about 590 W for a second after it wakes. Such a
    // reading is dropped, and only that reading — it is one broken sample, not
    // a broken bracket. Voiding the whole judgement on it was the first shape
    // of this code and the hardware test refused it: on jetson-hub one spike
    // among otherwise sane 14.8 W samples turned a counter running
    // persistently at 4-30x the board's draw into an indeterminate, which is a
    // worse diagnosis than the overrun it actually is.
    //
    // Dropping them also keeps the mean honest. The old code summed every
    // reading, so a 590 W spike inflated the mean and made the mean-draw bound
    // *more* permissive — it only ever went unnoticed because any such reading
    // short-circuited the whole check first.
    let (usable, unusable): (Vec<u128>, Vec<u128>) = draws_mw
        .iter()
        .map(|&d| u128::from(d))
        .partition(|&d| cap.is_none_or(|c| d <= c));

    if let Some(cap) = cap {
        if rate_mw > cap {
            return GpuPlausibility::CounterOverRate {
                rate_mw: clamp(rate_mw),
                bound_mw: clamp(cap),
                bound: GpuBound::PowerLimit,
            };
        }
        // Only when nothing usable is left is there no yardstick at all.
        if usable.is_empty() && !unusable.is_empty() {
            return GpuPlausibility::BoardTelemetryUnusable {
                draw_mw: clamp(unusable[0]),
                limit_mw: clamp(cap),
            };
        }
    }
    if !usable.is_empty() {
        let mean = usable.iter().sum::<u128>() / usable.len() as u128;
        let bound = GPU_DRAW_FACTOR * mean + GPU_DRAW_SLACK_MW;
        if rate_mw > bound {
            return GpuPlausibility::CounterOverRate {
                rate_mw: clamp(rate_mw),
                bound_mw: clamp(bound),
                bound: GpuBound::MeanDraw,
            };
        }
        // And the same yardstick from below. The slack comes off the draw
        // before the division, so the floor is zero at or under
        // `GPU_DRAW_SLACK_MW` of mean draw: an idle board makes no finding.
        let floor = mean.saturating_sub(GPU_DRAW_SLACK_MW) / GPU_UNDER_FACTOR;
        if floor > 0 && rate_mw < floor {
            return GpuPlausibility::CounterUnderRate {
                rate_mw: clamp(rate_mw),
                floor_mw: clamp(floor),
                mean_draw_mw: clamp(mean),
            };
        }
    }
    GpuPlausibility::Plausible { rate_mw: clamp(rate_mw) }
}

/// The status an NVML probe reports: [`liveness::status_of`] its run, except
/// that a live counter which did not plausibly count its board's energy over
/// the run ([`plausible_gpu_counter`]), running faster than its board or far
/// slower, is [`CounterStatus::Implausible`].
#[cfg_attr(not(any(test, feature = "nvml")), allow(dead_code))]
fn nvml_status_of(probed: Option<&liveness::Advances>, gpu: &GpuWatch) -> CounterStatus {
    match liveness::status_of(probed) {
        CounterStatus::Live => match (gpu.first, gpu.last) {
            (Some((a, t0)), Some((b, t1))) => {
                match plausible_gpu_counter(
                    b.saturating_sub(a),
                    t1.saturating_duration_since(t0),
                    &gpu.draws_mw,
                    gpu.ceiling_mw,
                ) {
                    GpuPlausibility::Plausible { .. } => CounterStatus::Live,
                    GpuPlausibility::CounterOverRate { .. } | GpuPlausibility::CounterUnderRate { .. } => {
                        CounterStatus::Implausible
                    }
                    GpuPlausibility::BoardTelemetryUnusable { .. } => CounterStatus::Unjudgeable,
                }
            }
            // No pair of samples to compute a rate from. Not a judgement that
            // the counter is sound; liveness already passed, and there is
            // nothing here to contradict it.
            _ => CounterStatus::Live,
        },
        status => status,
    }
}

/// The byte layout of `struct rusage_info_v6`, which macOS's
/// `proc_pid_rusage(pid, RUSAGE_INFO_V6, &info)` fills, as far as this crate
/// reads it. From `<sys/resource.h>`, measured with `sizeof` and `offsetof` by
/// the C compiler against the macOS 26, 26.5 and 27 SDKs, which agree: the
/// struct is 464 bytes, a 16-byte UUID then 56 `uint64_t`s, and `ri_energy_nj`
/// and `ri_penergy_nj` sit at bytes 336 and 344 (the 43rd and 44th words),
/// `ri_child_user_time` and `ri_child_system_time` at bytes 96 and 104 (the
/// 11th and 12th). New fields go into the struct's reserved tail: the 27 SDK named three of
/// the nine reserved words the 26 SDKs had, and the size and the offsets
/// before them held.
///
/// The decoding is pure and compiled everywhere, so its tests run on any host,
/// on a fixed byte layout.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
mod rusage_v6 {
    /// `RUSAGE_INFO_V6` in `<sys/resource.h>`.
    pub(crate) const FLAVOR: i32 = 6;
    /// `sizeof(struct rusage_info_v6)`.
    pub(crate) const SIZE: usize = 464;
    /// `offsetof(struct rusage_info_v6, ri_energy_nj)`.
    pub(crate) const ENERGY_NJ: usize = 336;
    /// `offsetof(struct rusage_info_v6, ri_penergy_nj)`.
    pub(crate) const PENERGY_NJ: usize = 344;
    /// `offsetof(struct rusage_info_v6, ri_child_user_time)`.
    pub(crate) const CHILD_USER_TIME: usize = 96;
    /// `offsetof(struct rusage_info_v6, ri_child_system_time)`.
    pub(crate) const CHILD_SYSTEM_TIME: usize = 104;

    /// What this crate reads of one `rusage_info_v6`.
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    pub(crate) struct ProcessEnergyReading {
        /// `ri_energy_nj`: the CPU energy the kernel has attributed to this
        /// process's threads since it started, in nanojoules.
        pub(crate) energy_nj: u64,
        /// `ri_penergy_nj`: the part of it spent on performance cores.
        pub(crate) penergy_nj: u64,
        /// `ri_child_user_time`: the user CPU time of this process's children
        /// that it has reaped, in Mach absolute time units. The kernel adds a
        /// child's time here when the child is reaped, and adds nothing to
        /// `ri_energy_nj`; a child still running, or exited and not yet
        /// reaped, is in neither.
        pub(crate) child_user_time: u64,
        /// `ri_child_system_time`: the same, for system CPU time.
        pub(crate) child_system_time: u64,
    }

    impl ProcessEnergyReading {
        /// The reaped children's CPU time, user and system, in Mach absolute
        /// time units. Only whether it moved across a span is read.
        pub(crate) fn reaped_children_cpu(&self) -> u64 {
            self.child_user_time.saturating_add(self.child_system_time)
        }
    }

    /// The `uint64_t` at `offset`, in the host's byte order: the kernel writes
    /// the struct in place, natively.
    fn word(info: &[u8; SIZE], offset: usize) -> u64 {
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&info[offset..offset + 8]);
        u64::from_ne_bytes(bytes)
    }

    /// Decode the energy counts and the reaped children's CPU times from the
    /// bytes `proc_pid_rusage` wrote.
    pub(crate) fn decode(info: &[u8; SIZE]) -> ProcessEnergyReading {
        ProcessEnergyReading {
            energy_nj: word(info, ENERGY_NJ),
            penergy_nj: word(info, PENERGY_NJ),
            child_user_time: word(info, CHILD_USER_TIME),
            child_system_time: word(info, CHILD_SYSTEM_TIME),
        }
    }
}

/// The byte layout of `struct proc_threadcounts`, which macOS's
/// `proc_pidinfo(pid, PROC_PIDTHREADCOUNTS, thread_id, &counts, size)` fills:
/// one thread's counts, by its 64-bit thread id. The flavor and the struct
/// are in the kernel's `<sys/proc_info_private.h>` (macOS 13 and later) and
/// not in the SDK's public header, so nothing here trusts the layout further
/// than the call's own return value confirms it: a `uint16_t` count of CPU
/// performance levels and six bytes of padding, then for each level five
/// `uint64_t` — instructions, cycles, user time, system time, and the
/// thread's CPU energy in nanojoules. On an M5 Max, macOS 27.0.1: two levels,
/// 88 bytes.
///
/// The decoding is pure and compiled everywhere, so its tests run on any host,
/// on a fixed byte layout.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
mod thread_counts {
    /// `PROC_PIDTHREADCOUNTS`.
    pub(crate) const FLAVOR: i32 = 34;
    /// The bytes before the first level's record.
    pub(crate) const HEADER: usize = 8;
    /// The bytes of one level's record: five `uint64_t`.
    pub(crate) const LEVEL: usize = 40;
    /// Where a level's record keeps its energy: its fifth `uint64_t`.
    pub(crate) const ENERGY_NJ: usize = 32;
    /// The most performance levels a read leaves room for.
    pub(crate) const MAX_LEVELS: usize = 12;
    /// The buffer a read hands the kernel.
    pub(crate) const SIZE: usize = HEADER + MAX_LEVELS * LEVEL;

    /// The thread's CPU energy in nJ, summed over the performance levels,
    /// from the `wrote` bytes the call says it wrote into `counts`.
    ///
    /// `None` unless that is exactly the header and one record for each
    /// level the header names, at least one and no more than the buffer
    /// holds. A failed call (`wrote` ≤ 0) and any other size — a layout this
    /// crate does not know — are no count, never a field read from the wrong
    /// place.
    pub(crate) fn energy_nj(counts: &[u8; SIZE], wrote: i32) -> Option<u64> {
        let levels = usize::from(u16::from_ne_bytes([counts[0], counts[1]]));
        if !(1..=MAX_LEVELS).contains(&levels) || usize::try_from(wrote).ok() != Some(HEADER + levels * LEVEL) {
            return None;
        }
        let energy = (0..levels).map(|level| {
            let at = HEADER + level * LEVEL + ENERGY_NJ;
            let mut word = [0u8; 8];
            word.copy_from_slice(&counts[at..at + 8]);
            u64::from_ne_bytes(word)
        });
        Some(energy.fold(0, u64::saturating_add))
    }
}

/// When a process may read its own energy count: once the reading thread has
/// been SEEN to leave its core.
///
/// The kernel adds a thread's CPU energy to its process's count only when
/// the thread leaves a core (a context switch, or the end of its quantum,
/// about 10 ms of its CPU), and a process's read of its own count does not
/// take the reading thread off its core: its CPU time is current at the
/// read, its energy is not. A span read that way holds, at its start, up to
/// a quantum of what the thread spent BEFORE the span, and lacks, at its
/// end, what the thread spent since it last left a core. Measured on an
/// idle M3 Ultra, macOS 27.0.1, against the tests' own reader that sleeps
/// before each of its reads, 40 spans of each kind a run over six runs: of
/// the spans over 1 ms of the metering thread's CPU, all 40 showed no rise
/// and were the default-power estimate, every run; of the spans over a 2 ms
/// sleep taken straight after 8 ms of that thread's CPU, 39 or 40 were
/// graded `HwShunt` on the burn before them, about 41 mJ for a sleep. (On a
/// loaded host other work takes the thread off its core more often, and the
/// same spans read a part of the work, or of the burn, instead.) With the
/// check below, on that host, idle and under 40 busy loops (110 runs): every
/// span of both kinds was read, the work at 84% or more of the tests' own
/// window around it and the sleep at 6% or less of the window that held the
/// burn.
///
/// A sleep takes the thread off its core — but not always: when the sleep's
/// timer fires before the thread has blocked, it goes on without leaving.
/// So the thread sleeps and CHECKS: its own energy count
/// (`thread_counts`) is moved by the kernel only when it adds the thread's
/// energy to the process's, so a rise across a sleep is the thread having
/// left its core after all it did before the sleep. The process's
/// context-switch count is no such check: any other thread's switch moves
/// it. The sleeps grow ([`SLEEPS`]), so one that did not block is followed
/// by one that much more surely does.
///
/// The rule is pure and compiled everywhere, so its tests run on any host.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
mod off_core {
    use std::time::Duration;

    /// The sleeps the reading thread takes, in turn, until one is seen to
    /// take it off its core: 6.25 ms in all on a read that never is.
    pub(crate) const SLEEPS: [Duration; 4] =
        [Duration::from_micros(50), Duration::from_micros(200), Duration::from_millis(1), Duration::from_millis(5)];

    /// Whether the reading thread was seen to leave its core: its own energy
    /// count (`count`) rose across one of `sleeps`, taken in turn through
    /// `sleep`. A count that cannot be read ends the wait at once; one that
    /// held across every sleep, or fell, is no evidence. `false` either way,
    /// and the caller does not read the process's count.
    pub(crate) fn seen(sleeps: &[Duration], mut count: impl FnMut() -> Option<u64>, mut sleep: impl FnMut(Duration)) -> bool {
        for &pause in sleeps {
            let Some(before) = count() else { return false };
            sleep(pause);
            let Some(after) = count() else { return false };
            if after > before {
                return true;
            }
        }
        false
    }
}

/// The kernel's count of this process's own CPU energy, read through
/// `proc_pid_rusage(getpid(), RUSAGE_INFO_V6, ...)` from libproc: public API,
/// no entitlement, no privilege. `ri_energy_nj` is the cumulative CPU energy
/// the kernel attributes to this process's threads, in nanojoules.
///
/// Its domain, exactly: the CPU energy of **this process's threads** — every
/// thread of the process, not only the one a span runs on, so a span also
/// takes in what the process's other threads spent meanwhile, as a package
/// counter takes in other processes. Not other processes. Not child
/// processes: a child's energy is its own, and it is not added to the
/// parent's count when the child exits or is reaped. Not the GPU, the Neural
/// Engine or DRAM.
///
/// So a span whose work drives a child process is under-counted, and the
/// figure must not claim the whole of it (SPEC §5: a figure MUST NOT claim
/// coverage of a domain its counter does not read). The same `rusage_info_v6`
/// shows it: `ri_child_user_time` and `ri_child_system_time` rise when the
/// process reaps a child, and `child_count` lists the children it has —
/// running, or exited and not yet reaped. A span over which the reaped
/// children's CPU time moved, or at whose end the process has a child, is a
/// `Partial` reading (`process_span`). Measured on an M5 Max, macOS 27.0.1:
/// reaping a `yes` that ran ~190 ms raised the parent's child CPU time by
/// 4,565,861 Mach units (the child's own 4,565,473), and left `ri_energy_nj`
/// where it was.
///
/// It is live for an unprivileged reader where IOReport's CPU rails are not.
/// Measured on an M5 Max, macOS 27.0.1: 0.002 J/s idle, 2.4 J/s with one
/// thread burning, 5.3 J/s with two, changing about every 0.5 ms while
/// polled.
///
/// A span's two reads of the count are each taken only once the metering
/// thread is seen to have left its core (`off_core`), so the count holds
/// all that thread spent before the read; a read not so checked is no read
/// ([`ProcessEnergy::read`]). That covers the thread that reads. Another
/// thread of the process that is on a core at a read is short by what it
/// spent since it last left one, so its share of a span can be off by up to
/// a quantum at each end: work on the thread that opens and closes the span
/// is read whole, and the figure holds what the other threads spent as the
/// kernel had counted it. Each read costs the sleep and the wait for a core
/// after it: on an idle M3 Ultra 79 to 81 µs at the median, 113 µs at most;
/// under 40 busy loops there, 169 µs at the median over 110 runs, 0.6 ms at
/// the median of the worst run, and up to 27 ms for one read (200 reads a
/// run; under 1 µs with no sleep). A read that fails costs all four sleeps
/// (6.25 ms) and their waits. A span also holds its closing read's own
/// wake-up, a few tens of microjoules (59 µJ for a span over a 200 ms sleep,
/// on the M3 Ultra): most of the figure for a span over much less than a
/// millisecond of work, which is then a reading of what the process spent
/// between its two reads, over that work and not under it. The liveness
/// probe samples the count with no sleep: it asks only whether the count
/// keeps advancing under a burn, which it does at every quantum.
#[cfg(target_os = "macos")]
#[allow(unsafe_code)]
mod process_energy {
    use std::os::raw::{c_int, c_void};

    use crate::liveness;
    use crate::rusage_v6::{self, ProcessEnergyReading};
    use crate::{off_core, thread_counts};

    unsafe extern "C" {
        fn proc_pid_rusage(pid: c_int, flavor: c_int, buffer: *mut c_void) -> c_int;
        fn proc_listchildpids(ppid: c_int, buffer: *mut c_void, buffersize: c_int) -> c_int;
        fn proc_pidinfo(pid: c_int, flavor: c_int, arg: u64, buffer: *mut c_void, buffersize: c_int) -> c_int;
        fn pthread_self() -> *mut c_void;
        fn pthread_threadid_np(thread: *mut c_void, thread_id: *mut u64) -> c_int;
        fn getpid() -> c_int;
    }

    /// How many pids [`child_count`] asks the kernel for at most.
    const CHILD_PIDS: usize = 64;

    /// How many child processes this process has now, as
    /// `proc_listchildpids` lists them: running, or exited and not yet reaped
    /// (a zombie is listed until it is reaped). At most [`CHILD_PIDS`]; only
    /// whether there is one is read. `None` if the call fails. Asked with a
    /// buffer: asked without one it returns a size estimate, not a count
    /// (1,098 for a process with none, on macOS 27.0.1).
    pub(crate) fn child_count() -> Option<usize> {
        let mut pids: [c_int; CHILD_PIDS] = [0; CHILD_PIDS];
        let bytes = c_int::try_from(std::mem::size_of_val(&pids)).ok()?;
        let n = unsafe { proc_listchildpids(getpid(), pids.as_mut_ptr().cast(), bytes) };
        usize::try_from(n).ok()
    }

    /// A `rusage_info_v6`-sized buffer, aligned as the struct is.
    #[repr(C, align(8))]
    struct Info([u8; rusage_v6::SIZE]);

    /// This process's energy counts as the kernel holds them now, read with
    /// no sleep before the call: short of what the calling thread spent
    /// since it last left a core. `None` if the call fails (a kernel without
    /// the V6 flavor). No span is made of this read alone: a span's ends are
    /// [`read_off_core`].
    pub(crate) fn read() -> Option<ProcessEnergyReading> {
        let mut info = Info([0; rusage_v6::SIZE]);
        let rc = unsafe { proc_pid_rusage(getpid(), rusage_v6::FLAVOR, info.0.as_mut_ptr().cast()) };
        (rc == 0).then(|| rusage_v6::decode(&info.0))
    }

    /// A `proc_threadcounts`-sized buffer, aligned as the struct is.
    #[repr(C, align(8))]
    struct Counts([u8; thread_counts::SIZE]);

    /// The calling thread's own CPU energy count, in nJ: what `off_core`
    /// watches. `None` if the thread's id or its counts cannot be read, or
    /// the counts come back in a layout `thread_counts` does not know.
    pub(crate) fn thread_energy_nj() -> Option<u64> {
        let mut thread = 0u64;
        if unsafe { pthread_threadid_np(pthread_self(), &mut thread) } != 0 {
            return None;
        }
        let mut counts = Counts([0; thread_counts::SIZE]);
        let bytes = c_int::try_from(thread_counts::SIZE).ok()?;
        let wrote = unsafe { proc_pidinfo(getpid(), thread_counts::FLAVOR, thread, counts.0.as_mut_ptr().cast(), bytes) };
        thread_counts::energy_nj(&counts.0, wrote)
    }

    /// One end of a span: this process's energy counts, read once the
    /// calling thread is seen to have left its core (`off_core::seen` on
    /// `thread_count`, sleeping `off_core::SLEEPS`), so they hold all that
    /// thread spent before the read. `None` if the thread was not seen to
    /// leave — the process's count is then not read at all — or the read
    /// itself fails.
    fn read_off_core(thread_count: fn() -> Option<u64>) -> Option<ProcessEnergyReading> {
        off_core::seen(&off_core::SLEEPS, thread_count, std::thread::sleep).then(read).flatten()
    }

    /// The per-process CPU energy counter of this process. Each read asks
    /// the kernel about the calling process and the calling thread.
    #[derive(Debug)]
    pub struct ProcessEnergy {
        /// The reading thread's own energy count, which each read of a span
        /// is checked against: [`thread_energy_nj`], but for a test of a
        /// thread that is never seen to leave its core.
        thread_count: fn() -> Option<u64>,
    }

    impl ProcessEnergy {
        /// `Some` when the kernel answers for this process, and for the
        /// calling thread's own count: every read of a span is checked
        /// against that count, and a counter whose reads could never be
        /// checked would only ever estimate. Opening is not selection:
        /// [`crate::Meter::detect`] selects the rung only while
        /// [`crate::process_energy_status`] is Live.
        pub(crate) fn open() -> Option<Self> {
            read()?;
            thread_energy_nj()?;
            Some(ProcessEnergy { thread_count: thread_energy_nj })
        }

        /// A counter whose reading thread is never seen to leave its core:
        /// its own count reads, and never moves.
        #[cfg(test)]
        pub(crate) fn never_off_core() -> Self {
            ProcessEnergy { thread_count: || Some(7) }
        }

        /// `ri_energy_nj` now, in nJ, with no sleep before the read: the
        /// liveness probe's sample.
        pub(crate) fn read_nj(&self) -> Option<u64> {
            read().map(|r| r.energy_nj)
        }

        /// What a span reads at each end: the energy count and the reaped
        /// children's CPU time, from one call, taken once the calling thread
        /// is seen to have left its core. `None` where it was not: that end
        /// has no reading, and the span is the default-power estimate
        /// (`process_span`).
        pub(crate) fn read(&self) -> Option<ProcessEnergyReading> {
            read_off_core(self.thread_count)
        }

        /// [`Self::read`]'s energy count alone, in nJ.
        pub(crate) fn read_energy_nj(&self) -> Option<u64> {
            self.read().map(|r| r.energy_nj)
        }

        /// One liveness sample: `ri_energy_nj` as the counter's one rail.
        pub(crate) fn liveness_sample(&self) -> Option<Vec<(liveness::RailKey, i64)>> {
            let nj = self.read_nj()?;
            Some(liveness::every_rail(&[("ri_energy_nj".to_string(), i64::try_from(nj).unwrap_or(i64::MAX))]))
        }
    }
}

/// How many times the per-process energy probe has run in this process. Always
/// 0 off macOS, which has no such counter.
#[cfg_attr(not(test), allow(dead_code))]
fn process_energy_probe_runs() -> usize {
    PROCESS_ENERGY_PROBE_RUNS.load(std::sync::atomic::Ordering::SeqCst)
}

static PROCESS_ENERGY_PROBE_RUNS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);

/// This host's per-process CPU energy status, probed once per process and
/// cached. Always [`CounterStatus::Unavailable`] off macOS.
///
/// [`Meter::detect`] selects the process-energy rung only when this is
/// [`CounterStatus::Live`]: `ri_energy_nj` advanced while the probing thread
/// burned CPU, in at least five sample intervals, at least 80% of them, over at
/// least 300 ms — the rule every vendor counter here is held to. The first call
/// on macOS burns about 300 ms of the calling thread's CPU when the counter is
/// live (one second when it is not).
pub fn process_energy_status() -> CounterStatus {
    #[cfg(target_os = "macos")]
    {
        static STATUS: std::sync::OnceLock<CounterStatus> = std::sync::OnceLock::new();
        *STATUS.get_or_init(process_energy_host_status)
    }
    #[cfg(not(target_os = "macos"))]
    {
        CounterStatus::Unavailable
    }
}

/// The real per-process probe: the real opener and tick. Counts itself, then
/// composes; its only caller is the cache in [`process_energy_status`].
#[cfg(target_os = "macos")]
fn process_energy_host_status() -> CounterStatus {
    PROCESS_ENERGY_PROBE_RUNS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    liveness::status_of(process_energy_probe().as_ref())
}

/// The per-process probe on the real parts: [`liveness::probe`] on this
/// process's counter, sampled after every 25 ms of the probing thread's CPU,
/// by the real clock, for one budget.
#[cfg(target_os = "macos")]
fn process_energy_probe() -> Option<liveness::Advances> {
    liveness::probe(
        process_energy::ProcessEnergy::open,
        process_energy::ProcessEnergy::liveness_sample,
        liveness::burn_tick,
        Instant::now,
        liveness::BUDGET,
    )
}

/// Apple Silicon IOReport energy reader — a real, no-sudo, no-external-binary
/// reading of the SoC Energy Model channels through Apple's private IOReport C
/// API. Like RAPL and NVML it is a vendor energy counter: how Apple derives the
/// count is undisclosed and the platform relays it, which is a gap in
/// provenance, not in accuracy, so a live reading is graded `HwShunt` as theirs
/// are. It counts as a reading only while every CPU rail is live
/// ([`crate::ioreport_status`]) and only for a span over which a CPU rail
/// advanced (`ioreport_span`). Ported from jouleclaw-energy's validated
/// `apple_ioreport` backend.
#[cfg(target_os = "macos")]
#[allow(non_camel_case_types, unsafe_code)]
mod ioreport {
    use std::os::raw::{c_int, c_long, c_void};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::sync::Mutex;
    use std::time::{Duration, Instant};

    use crate::liveness::{self, rails_where, thread_cpu_time, Advances, RailKey};
    use crate::{IoReportReading, IoReportStatus};

    type CFTypeRef = *const c_void;
    type CFStringRef = *const c_void;
    type CFArrayRef = *const c_void;
    type CFDictionaryRef = *const c_void;
    type CFMutableDictionaryRef = *mut c_void;
    type IOReportSubscriptionRef = *const c_void;
    const K_CFSTRING_ENCODING_UTF8: u32 = 0x0800_0100;

    unsafe extern "C" {
        fn IOReportCopyAllChannels(a: u64, b: u64) -> CFMutableDictionaryRef;
        fn IOReportCopyChannelsInGroup(
            group: CFStringRef,
            subgroup: CFStringRef,
            a: u64,
            b: u64,
            c: u64,
        ) -> CFMutableDictionaryRef;
        fn IOReportCreateSubscription(
            allowed: *const c_void,
            desired_channels: CFMutableDictionaryRef,
            subscribed_channels: *mut CFMutableDictionaryRef,
            channel_id: u64,
            options: CFTypeRef,
        ) -> IOReportSubscriptionRef;
        fn IOReportCreateSamples(
            iorsub: IOReportSubscriptionRef,
            chan_dict: CFMutableDictionaryRef,
            options: CFTypeRef,
        ) -> CFDictionaryRef;
        fn IOReportCreateSamplesDelta(
            previous: CFDictionaryRef,
            current: CFDictionaryRef,
            options: CFTypeRef,
        ) -> CFDictionaryRef;
        fn IOReportChannelGetGroup(item: CFTypeRef) -> CFStringRef;
        fn IOReportChannelGetChannelName(item: CFTypeRef) -> CFStringRef;
        fn IOReportSimpleGetIntegerValue(item: CFTypeRef, _v: c_int) -> c_long;
        fn IOReportChannelGetUnitLabel(item: CFTypeRef) -> CFStringRef;
        fn CFRelease(cf: CFTypeRef);
        fn CFArrayGetCount(the_array: CFArrayRef) -> c_long;
        fn CFArrayGetValueAtIndex(the_array: CFArrayRef, idx: c_long) -> CFTypeRef;
        fn CFDictionaryGetValue(the_dict: CFDictionaryRef, key: *const c_void) -> *const c_void;
        fn CFStringCreateWithCString(
            allocator: *mut c_void,
            cstr: *const i8,
            encoding: u32,
        ) -> CFStringRef;
        fn CFStringGetCString(
            the_string: CFStringRef,
            buffer: *mut i8,
            buffer_size: c_long,
            encoding: u32,
        ) -> bool;
    }

    // Three distinct frameworks, each legitimately `kind = "framework"`; the
    // lint mis-reads the repeated key across separate `#[link]`s as a duplicate.
    #[allow(clippy::duplicated_attributes)]
    #[link(name = "IOReport", kind = "dylib")]
    #[link(name = "IOKit", kind = "framework")]
    #[link(name = "CoreFoundation", kind = "framework")]
    unsafe extern "C" {}

    struct State {
        sub: IOReportSubscriptionRef,
        channels: CFMutableDictionaryRef,
        prior_sample: Option<CFDictionaryRef>,
        cumulative: IoReportReading,
    }

    impl Drop for State {
        fn drop(&mut self) {
            unsafe {
                if let Some(prior) = self.prior_sample.take() {
                    CFRelease(prior);
                }
                if !self.sub.is_null() {
                    CFRelease(self.sub);
                }
                if !self.channels.is_null() {
                    CFRelease(self.channels as CFTypeRef);
                }
            }
        }
    }

    /// Apple Silicon IOReport energy counter (SoC-total, cumulative µJ).
    pub struct IoReport {
        state: Mutex<State>,
    }

    // Raw CF pointers are confined to `State` behind a `Mutex`.
    unsafe impl Send for IoReport {}
    unsafe impl Sync for IoReport {}

    impl std::fmt::Debug for IoReport {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            f.write_str("IoReport")
        }
    }

    impl IoReport {
        /// Open an IOReport subscription; `None` if unavailable (non-Apple-Silicon,
        /// Rosetta, or a future macOS that changes the surface).
        pub fn open() -> Option<Self> {
            unsafe {
                let all = IOReportCopyAllChannels(0, 0);
                if all.is_null() {
                    return None;
                }
                let mut subscribed: CFMutableDictionaryRef = std::ptr::null_mut();
                let sub = IOReportCreateSubscription(
                    std::ptr::null(),
                    all,
                    &mut subscribed as *mut _,
                    0,
                    std::ptr::null(),
                );
                CFRelease(all as CFTypeRef);
                if sub.is_null() || subscribed.is_null() {
                    if !sub.is_null() {
                        CFRelease(sub);
                    }
                    if !subscribed.is_null() {
                        CFRelease(subscribed as CFTypeRef);
                    }
                    return None;
                }
                Some(Self {
                    state: Mutex::new(State {
                        sub,
                        channels: subscribed,
                        prior_sample: None,
                        cumulative: IoReportReading::default(),
                    }),
                })
            }
        }

        /// Cumulative SoC energy (µJ) since the first read. Subtract two reads
        /// for an interval. `None` if the interface vanished mid-read.
        pub fn read_uj(&self) -> Option<u64> {
            self.read().map(|r| r.total_uj)
        }

        /// Cumulative energy (µJ) since the first read: the SoC total the
        /// counter sums, and within it the CPU energy rails' own share, both
        /// from the same pair of samples. Subtract two reads for an interval.
        /// `None` if the interface vanished mid-read.
        pub(crate) fn read(&self) -> Option<IoReportReading> {
            let mut state = self.state.lock().ok()?;
            unsafe {
                let current = IOReportCreateSamples(state.sub, state.channels, std::ptr::null());
                if current.is_null() {
                    return None;
                }
                if let Some(prior) = state.prior_sample {
                    let delta = IOReportCreateSamplesDelta(prior, current, std::ptr::null());
                    if !delta.is_null() {
                        let d = sum_energy_uj(delta);
                        state.cumulative = IoReportReading {
                            total_uj: state.cumulative.total_uj.saturating_add(d.total_uj),
                            cpu_uj: state.cumulative.cpu_uj.saturating_add(d.cpu_uj),
                            gpu_uj: state.cumulative.gpu_uj.saturating_add(d.gpu_uj),
                            ane_uj: state.cumulative.ane_uj.saturating_add(d.ane_uj),
                        };
                        CFRelease(delta);
                    }
                    CFRelease(prior);
                }
                state.prior_sample = Some(current);
            }
            Some(state.cumulative)
        }
    }

    // ── CPU-rail liveness ───────────────────────────────────────────────────
    //
    // The production chain, outermost first, and what pins each link:
    //
    // - `crate::ioreport_status()` caches one status per process in a
    //   `OnceLock`. `tests/ioreport_probed_once.rs`, and the lib test
    //   `the_liveness_probe_runs_once_in_a_fresh_process`, run it cold, from
    //   eight threads at once, in a process of their own, and count real runs.
    // - `host_status()` is the whole composition, with no branch: the real
    //   opener, tick and clocks handed to `probe_with`, and `status_of` on the
    //   verdict. The tests run this very function, with its subscription
    //   failing, with scripted samples, and against the hardware.
    // - `probe_with()` is the loop and its record, generic over opener,
    //   sampler, tick and clocks. The tests drive it with fakes.
    // - `watch()` and `RailWatch` are the rule (the crate's shared
    //   `liveness` rule, fed the CPU rails), on scripted samples.
    //   `status_of()` is a pure mapping.
    // - The real parts: `EnergyModelSubscription` (opener and FFI read), checked
    //   against an independent oracle, structurally and value by value;
    //   `liveness::burn_tick()` and `HostClocks`, checked on the tests' own
    //   clocks.

    /// How many times the real probe, [`host_status`], has run in this process.
    /// It is the first thing `host_status` does. [`crate::ioreport_status`]
    /// caches its answer, so this never passes one; a test pins that by
    /// counting rather than by timing.
    static HOST_PROBE_RUNS: AtomicUsize = AtomicUsize::new(0);

    /// How many times this process has opened a subscription to the Energy
    /// Model group: once per probe, whatever runs it. A path that probed
    /// without going through [`host_status`] would still show here.
    static ENERGY_MODEL_OPENS: AtomicUsize = AtomicUsize::new(0);

    /// [`HOST_PROBE_RUNS`], for `crate::ioreport_probe_runs`.
    pub(crate) fn host_probe_runs() -> usize {
        HOST_PROBE_RUNS.load(Ordering::SeqCst)
    }

    /// [`ENERGY_MODEL_OPENS`], for `crate::ioreport_energy_model_opens`.
    pub(crate) fn energy_model_opens() -> usize {
        ENERGY_MODEL_OPENS.load(Ordering::SeqCst)
    }

    /// What the liveness probe saw of the CPU energy rails.
    #[derive(Debug, Clone, Copy, PartialEq, Eq)]
    enum CpuRail {
        /// Every CPU energy rail kept advancing while the probing thread
        /// burned CPU: each in at least [`liveness::MIN_LIVE_ADVANCES`]
        /// separate sample intervals, in at least 80% of the intervals
        /// observed, over at least [`liveness::MIN_LIVE_WINDOW`].
        Live,
        /// A CPU energy rail exists, but not every one kept advancing: one
        /// held, or moved in a few steps (a batch refresh) — on a two-die part,
        /// possibly beside a live die.
        Frozen,
        /// No `CPU Energy` channel exists in the Energy Model group.
        Absent,
    }

    /// The Energy Model channels of one sample, as the rule is handed them:
    /// every in-group channel's name and its ABSOLUTE raw cumulative integer,
    /// in the order IOReport lists them. [`RailWatch::observe`] pairs each
    /// sample with the one before it.
    type Sample = Vec<(String, i64)>;

    /// The CPU energy rails in one sample, each with its absolute raw value.
    fn cpu_rails(sample: &[(String, i64)]) -> Vec<(RailKey, i64)> {
        rails_where(sample, is_cpu_energy_rail)
    }

    /// The `GPU Energy` rails in one sample. The rule never reads them. The
    /// probe's record keeps them, because where the GPU draws they move, and a
    /// test can then tell a fresh sample from a stale one.
    fn gpu_rails(sample: &[(String, i64)]) -> Vec<(RailKey, i64)> {
        rails_where(sample, is_gpu_energy_rail)
    }

    /// The Neural Engine rails in one sample, as the counter sums them
    /// ([`sum_energy_uj`]): the `ANE Energy` aggregate where a part publishes
    /// one, else every per-engine `ANE<n>` rail. Never both.
    fn ane_rails(sample: &[(String, i64)]) -> Vec<(RailKey, i64)> {
        let aggregate = rails_where(sample, is_ane_energy_rail);
        if aggregate.is_empty() { rails_where(sample, is_ane_base_rail) } else { aggregate }
    }

    /// One Neural Engine liveness probe: the shared rule
    /// ([`crate::liveness::probe`]) over the ANE rails of the Energy Model
    /// group subscription, with `load` between samples. A sample with no ANE
    /// rail is no sample, so a part without one is `Unavailable`, never a
    /// vacuous `Live`.
    pub(crate) fn npu_status(load: impl FnMut()) -> crate::CounterStatus {
        npu_status_with(EnergyModelSubscription::open, load, Instant::now)
    }

    /// [`npu_status`], generic over the subscription and the clock, so the
    /// tests drive this very function with scripted samples.
    fn npu_status_with<S: Sampler>(
        open: impl FnOnce() -> Option<S>,
        load: impl FnMut(),
        now: impl Fn() -> Instant,
    ) -> crate::CounterStatus {
        let probed = crate::liveness::probe(
            open,
            |sub: &S| sub.sample().map(|g| ane_rails(&g.values)).filter(|rails| !rails.is_empty()),
            load,
            now,
            crate::liveness::BUDGET,
        );
        crate::liveness::status_of(probed.as_ref())
    }

    /// The shared liveness rule ([`liveness::Advances`]) fed IOReport's CPU
    /// energy rails: [`RailWatch::observe`] picks the CPU rails out of an
    /// Energy Model sample and hands the rule those alone, so the GPU rail,
    /// which rises wherever the GPU draws, is never counted. Every CPU rail
    /// handed over must keep advancing (the rule's every-rail condition): on a
    /// multi-die part the counter sums each die's `DIE_<n>_CPU Energy`, so one
    /// live die beside a frozen one is Frozen, never a Live that would leave
    /// the frozen die out of a whole-CPU figure. It dereferences to the rule's
    /// state, which is all it holds.
    ///
    /// Why the rule asks for five advances in 80% of the intervals over
    /// 300 ms: on macOS 27.0.1 an unprivileged reader's CPU rails are not
    /// permanently frozen, they are refreshed in rare batches, ~30 minutes
    /// apart. On an M3 Ultra both dies' rails held for at least 22 minutes,
    /// stepped +1,344,869 and +1,391,637 mJ in one 100 ms sample, then held
    /// again; an M5 Max's `CPU Energy` did not change in 13,614 samples over 25
    /// minutes, yet had moved from 480,083,160 to 541,893,638 mJ earlier that
    /// hour. And a refresh is not always one step. On an M5 Max, a watcher
    /// sampling the group every ~16 ms saw `CPU Energy` go 2,643,843,378 ->
    /// 2,705,607,863 (+61,764,485), then 2,705,607,863 -> 2,705,611,298
    /// (+3,435) 64 ms later, and `MCPU0`, `MCPU1` and `PCPU` each step twice.
    /// The probe's intervals are ~31 ms (a 25 ms tick and a ~6 ms sample), so a
    /// window holding that refresh sees two advancing intervals. Two advances
    /// of one rail would call that Live, and a Live is cached for the process:
    /// the rung is selected, and every later ~1.3 kJ refresh is attributed
    /// whole to whichever metered span straddles it. A live rail advances in
    /// nearly every interval (the M5 Max GPU rail changes every ~28 ms), so it
    /// meets the rule about 300 ms in.
    #[derive(Debug, Default, Clone)]
    struct RailWatch(Advances);

    impl std::ops::Deref for RailWatch {
        type Target = Advances;

        fn deref(&self) -> &Advances {
            &self.0
        }
    }

    impl RailWatch {
        /// Fold in the next usable Energy Model sample, taken at `at` by the
        /// probe's wall clock: its CPU energy rails ([`cpu_rails`]), and
        /// nothing else, go to the rule ([`Advances::observe`]).
        #[cfg_attr(not(test), allow(dead_code))]
        fn observe(&mut self, sample: &[(String, i64)], at: Duration) {
            self.0.observe(cpu_rails(sample), at);
        }

        /// The verdict, or `None` if not a single interval could be observed.
        fn verdict(&self) -> Option<CpuRail> {
            if self.intervals == 0 {
                None
            } else if self.is_live() {
                Some(CpuRail::Live)
            } else if self.rails.is_empty() {
                Some(CpuRail::Absent)
            } else {
                Some(CpuRail::Frozen)
            }
        }
    }

    /// The shared rule's loop ([`liveness::watch`]) on Energy Model samples,
    /// each handed over as its CPU rails: take a sample and read the clock;
    /// hand the rule the sample with that reading; stop when
    /// [`Advances::wants_more`] says so; otherwise `tick` and sample again. A
    /// sample that fails is skipped, so the next usable one is compared with
    /// the last usable one. `elapsed` is the wall time since the probe started.
    fn watch(
        mut sample: impl FnMut() -> Option<Sample>,
        tick: impl FnMut(),
        elapsed: impl FnMut() -> Duration,
        budget: Duration,
    ) -> RailWatch {
        RailWatch(liveness::watch(|| sample().map(|s| cpu_rails(&s)), tick, liveness::PROBE_TICK, elapsed, budget))
    }

    /// One channel of one sample, as the FFI reads it, and nothing more: its
    /// group, its name and its raw integer. Everything done with it after that
    /// is [`group_sample`]'s, which tests can run.
    #[derive(Debug, Clone)]
    struct Item {
        group: Option<String>,
        name: Option<String>,
        raw: i64,
    }

    /// One sample of the probe's subscription: how many channels it carried,
    /// how many of those were outside the Energy Model group, and the in-group
    /// channels the rule is handed.
    #[derive(Debug)]
    struct GroupSample {
        channels: usize,
        outside_group: usize,
        values: Sample,
    }

    /// A [`GroupSample`] from one read's channels, one channel at a time. A
    /// channel's value is its own raw integer; nothing is summed or carried
    /// across channels. A channel outside the Energy Model group is counted
    /// and not handed on. A channel with no name cannot be keyed, so it is not
    /// handed on either.
    fn group_sample(items: Vec<Item>) -> GroupSample {
        let channels = items.len();
        let mut outside_group = 0;
        let mut values = Vec::with_capacity(channels);
        for item in items {
            if !item.group.as_deref().is_some_and(|g| g.eq_ignore_ascii_case("Energy Model")) {
                outside_group += 1;
                continue;
            }
            if let Some(name) = item.name {
                values.push((name, item.raw));
            }
        }
        GroupSample { channels, outside_group, values }
    }

    /// Where the probe's samples come from: the real subscription, or, in
    /// tests, a script.
    trait Sampler {
        fn sample(&self) -> Option<GroupSample>;
    }

    /// The liveness probe's own subscription, to the Energy Model group only.
    ///
    /// The counter's subscription covers every channel (~11,890 on an M5 Max,
    /// ~14,350 on an M3 Ultra), and one sample of it takes 0.13-0.8 s of wall
    /// time and ~0.1 s of CPU. The group alone (364 channels on an M5 Max, 645
    /// on an M3 Ultra) samples in ~5-12 ms and ~8 ms of CPU, and carries the
    /// same absolute CPU rail values.
    struct EnergyModelSubscription {
        sub: IOReportSubscriptionRef,
        channels: CFMutableDictionaryRef,
    }

    impl Drop for EnergyModelSubscription {
        fn drop(&mut self) {
            unsafe {
                CFRelease(self.sub);
                CFRelease(self.channels as CFTypeRef);
            }
        }
    }

    impl EnergyModelSubscription {
        /// `None` when IOReport cannot open, or has no Energy Model group.
        /// Counted in [`ENERGY_MODEL_OPENS`], opened or not. In this crate's
        /// unit tests a test can make it fail (`tests::seam`); nothing else can.
        fn open() -> Option<Self> {
            ENERGY_MODEL_OPENS.fetch_add(1, Ordering::SeqCst);
            #[cfg(test)]
            if tests::seam::open_fails() {
                return None;
            }
            unsafe {
                let group = CFStringCreateWithCString(
                    std::ptr::null_mut(),
                    c"Energy Model".as_ptr() as *const _,
                    K_CFSTRING_ENCODING_UTF8,
                );
                if group.is_null() {
                    return None;
                }
                let desired = IOReportCopyChannelsInGroup(group, std::ptr::null(), 0, 0, 0);
                CFRelease(group);
                if desired.is_null() {
                    return None;
                }
                let mut channels: CFMutableDictionaryRef = std::ptr::null_mut();
                let sub = IOReportCreateSubscription(
                    std::ptr::null(),
                    desired,
                    &mut channels as *mut _,
                    0,
                    std::ptr::null(),
                );
                CFRelease(desired as CFTypeRef);
                if sub.is_null() || channels.is_null() {
                    if !sub.is_null() {
                        CFRelease(sub);
                    }
                    if !channels.is_null() {
                        CFRelease(channels as CFTypeRef);
                    }
                    return None;
                }
                Some(Self { sub, channels })
            }
        }

        /// One read's channels. In this crate's unit tests a test can stand in
        /// for the FFI read, passing it through or replacing it
        /// (`tests::seam`); nothing else can.
        fn items(&self) -> Option<Vec<Item>> {
            let read = || unsafe { self.read_items() };
            #[cfg(test)]
            if let Some(items) = tests::seam::sample(&read) {
                return items;
            }
            read()
        }

        /// One plain sample (no delta) of this subscription, channel by
        /// channel. `None` when IOReport yields no usable sample.
        unsafe fn read_items(&self) -> Option<Vec<Item>> {
            let sample = IOReportCreateSamples(self.sub, self.channels, std::ptr::null());
            if sample.is_null() {
                return None;
            }
            let items = sample_items(sample);
            CFRelease(sample);
            items
        }
    }

    impl Sampler for EnergyModelSubscription {
        fn sample(&self) -> Option<GroupSample> {
            self.items().map(group_sample)
        }
    }

    /// Every channel of a plain sample, as `(group, name, raw integer)` in
    /// IOReport's order. Raw integers, before unit conversion, so a small
    /// advance in a fine unit cannot truncate to zero. `None` when the sample
    /// carries no channel array.
    unsafe fn sample_items(sample: CFDictionaryRef) -> Option<Vec<Item>> {
        let key = CFStringCreateWithCString(
            std::ptr::null_mut(),
            c"IOReportChannels".as_ptr() as *const _,
            K_CFSTRING_ENCODING_UTF8,
        );
        if key.is_null() {
            return None;
        }
        let arr = CFDictionaryGetValue(sample, key as *const _) as CFArrayRef;
        CFRelease(key as CFTypeRef);
        if arr.is_null() {
            return None;
        }
        let count = CFArrayGetCount(arr);
        let mut items = Vec::with_capacity(count.max(0) as usize);
        for i in 0..count {
            let item = CFArrayGetValueAtIndex(arr, i);
            if item.is_null() {
                continue;
            }
            items.push(Item {
                group: cfstring_to_string(IOReportChannelGetGroup(item)),
                name: cfstring_to_string(IOReportChannelGetChannelName(item)),
                raw: IOReportSimpleGetIntegerValue(item, 0) as i64,
            });
        }
        Some(items)
    }

    /// The clocks the probe reads: wall time, for its budget and its record,
    /// and this thread's CPU time, for its record. The tick reads the thread
    /// clock for itself.
    trait Clocks {
        fn now(&self) -> Instant;
        fn thread_cpu(&self) -> Option<Duration>;
    }

    /// The real clocks: [`Instant`] and [`thread_cpu_time`].
    struct HostClocks;

    impl Clocks for HostClocks {
        fn now(&self) -> Instant {
            Instant::now()
        }

        fn thread_cpu(&self) -> Option<Duration> {
            thread_cpu_time()
        }
    }

    /// What one sample call handed the rule, and how big the sample was. Read
    /// by the tests alone; see [`ProbeRun`].
    #[cfg_attr(not(test), allow(dead_code))]
    #[derive(Debug, Clone)]
    struct Taken {
        /// Channels in the sample.
        channels: usize,
        /// How many of them were outside the Energy Model group.
        outside_group: usize,
        /// The CPU rails of the sample handed to the rule, keyed and valued as
        /// the rule reads them ([`cpu_rails`]).
        cpu_rails: Vec<(RailKey, i64)>,
        /// The `GPU Energy` rails of the same sample.
        gpu_rails: Vec<(RailKey, i64)>,
    }

    /// One sample call of a probe run.
    #[cfg_attr(not(test), allow(dead_code))]
    #[derive(Debug, Clone)]
    struct SampleCall {
        /// When the call began, by the probe's wall clock.
        at: Instant,
        /// Its wall time.
        wall: Duration,
        /// This thread's CPU time over it; `None` if the clock could not be read.
        cpu: Option<Duration>,
        /// What it handed the rule; `None` if it gave no sample.
        taken: Option<Taken>,
    }

    /// One tick of a probe run, as the probe's clocks saw it.
    #[cfg_attr(not(test), allow(dead_code))]
    #[derive(Debug, Clone, Copy)]
    struct Tick {
        /// This thread's CPU time over the tick; `None` if unreadable.
        cpu: Option<Duration>,
        /// Wall time over the tick.
        wall: Duration,
    }

    /// One probe run: the rule's watch (`None` when no subscription opened),
    /// and a record of every sample call and every tick, in order. Only the
    /// watch decides anything. The record is kept in every build, so the probe
    /// the tests read is the probe that ships, and only the tests read it.
    #[cfg_attr(not(test), allow(dead_code))]
    #[derive(Debug, Clone)]
    struct ProbeRun {
        /// When the run's budget began, by the probe's wall clock: once the
        /// subscription was open. A slow open costs a probe none of its budget.
        started: Instant,
        watch: Option<RailWatch>,
        samples: Vec<SampleCall>,
        ticks: Vec<Tick>,
        /// The probe's wall-clock reading after each sample call, one per
        /// call, in order: the very reading from which the rule got that
        /// call's time (this less `started`), with the sample if it was
        /// usable, and on which the stopping rule decided. So each interval
        /// the rule timed is the span between two of these. Not `at + wall` of
        /// a [`SampleCall`]: between the end of a call and this reading the
        /// probe records the call, and on a loaded host its thread can be
        /// descheduled there for any length of time.
        checks: Vec<Instant>,
    }

    impl ProbeRun {
        /// The run's verdict: none when no subscription opened, or when not
        /// one interval was observed on it.
        fn verdict(&self) -> Option<CpuRail> {
            self.watch.as_ref().and_then(RailWatch::verdict)
        }
    }

    /// CPU time between two readings of a thread clock, if both were read.
    fn cpu_between(from: Option<Duration>, to: Option<Duration>) -> Option<Duration> {
        Some(to?.saturating_sub(from?))
    }

    /// The probe: `open` a subscription and, if one opens, [`watch`] it. Take
    /// a sample; until [`RailWatch::wants_more`] says stop, `tick` and sample
    /// again. Every sample call, every tick and every clock reading the rule
    /// is handed is recorded by `clocks`. With no subscription there is no
    /// sample, no tick and no verdict. The budget starts once the subscription
    /// is open.
    ///
    /// Generic over each part, so the tests drive this very loop with a
    /// scripted subscription, tick and clocks. [`host_status`] passes the real
    /// ones, and is its only production caller. Each record is taken from the
    /// sample as it is handed to the rule, and each clock reading as the rule
    /// gets it, so what the tests read is what the rule saw.
    fn probe_with<S: Sampler>(
        open: impl FnOnce() -> Option<S>,
        mut tick: impl FnMut(),
        clocks: &impl Clocks,
        budget: Duration,
    ) -> ProbeRun {
        let opened = open();
        let started = clocks.now();
        let mut samples = Vec::new();
        let mut ticks = Vec::new();
        let mut checks = Vec::new();
        let rail_watch = opened.map(|sub| {
            watch(
                || {
                    // Wall, then CPU; at the end CPU, then wall: the CPU
                    // interval sits inside the wall one.
                    let (at, cpu) = (clocks.now(), clocks.thread_cpu());
                    let got = sub.sample();
                    let cpu = cpu_between(cpu, clocks.thread_cpu());
                    let wall = clocks.now().saturating_duration_since(at);
                    let taken = got.as_ref().map(|g| Taken {
                        channels: g.channels,
                        outside_group: g.outside_group,
                        cpu_rails: cpu_rails(&g.values),
                        gpu_rails: gpu_rails(&g.values),
                    });
                    samples.push(SampleCall { at, wall, cpu, taken });
                    got.map(|g| g.values)
                },
                || {
                    let (at, cpu) = (clocks.now(), clocks.thread_cpu());
                    tick();
                    let cpu = cpu_between(cpu, clocks.thread_cpu());
                    ticks.push(Tick { cpu, wall: clocks.now().saturating_duration_since(at) });
                },
                || {
                    let now = clocks.now();
                    checks.push(now);
                    now.saturating_duration_since(started)
                },
                budget,
            )
        });
        let run = ProbeRun { started, watch: rail_watch, samples, ticks, checks };
        #[cfg(test)]
        tests::seam::deliver(&run);
        run
    }

    /// The status a probe verdict reports. No verdict — no Energy Model
    /// subscription, or not one interval observed on it — is `Unavailable`:
    /// never `Live`, and never `CpuRailAbsent`, which says a group was read
    /// and had no CPU rail.
    fn status_of(verdict: Option<CpuRail>) -> IoReportStatus {
        match verdict {
            None => IoReportStatus::Unavailable,
            Some(CpuRail::Live) => IoReportStatus::Live,
            Some(CpuRail::Frozen) => IoReportStatus::CpuRailFrozen,
            Some(CpuRail::Absent) => IoReportStatus::CpuRailAbsent,
        }
    }

    /// This host's liveness status: [`probe_with`] on the real opener
    /// ([`EnergyModelSubscription::open`]), the real tick
    /// ([`liveness::burn_tick`]) and
    /// the real clocks ([`HostClocks`]) for
    /// [`crate::CPU_RAIL_LIVENESS_BUDGET`], mapped by [`status_of`]. It counts
    /// itself, then composes, and has no branch of its own: every decision is
    /// in `probe_with` and `status_of`. The tests run this function too, with
    /// its subscription failing, with scripted samples, and against the
    /// hardware. In production it runs as [`host_probe`], the only
    /// production caller of `probe_with`, whose only caller is the cache in
    /// [`crate::ioreport_status`].
    #[cfg_attr(not(test), allow(dead_code))]
    pub(crate) fn host_status() -> IoReportStatus {
        host_probe().0
    }

    /// [`host_status`], and the evidence its run's rule held when it stopped
    /// (`None` when no subscription opened). The process caches both, once,
    /// so that the cached verdict can be read beside what it was made from
    /// ([`crate::ioreport_probe_evidence`]). Counts itself first.
    pub(crate) fn host_probe() -> (IoReportStatus, Option<liveness::ProbeEvidence>) {
        HOST_PROBE_RUNS.fetch_add(1, Ordering::SeqCst);
        let run = probe_with(EnergyModelSubscription::open, liveness::burn_tick, &HostClocks, crate::CPU_RAIL_LIVENESS_BUDGET);
        (status_of(run.verdict()), run.watch.as_ref().map(|w| w.evidence()))
    }

    /// Whether a channel is a CPU energy aggregate: `CPU Energy`, optionally
    /// `DIE_<n>_`-prefixed, compared case-insensitively.
    fn is_cpu_energy_rail(name: &str) -> bool {
        strip_die_prefix(name).eq_ignore_ascii_case("CPU Energy")
    }

    /// Whether a channel is the GPU energy aggregate, named like
    /// [`is_cpu_energy_rail`]'s.
    fn is_gpu_energy_rail(name: &str) -> bool {
        strip_die_prefix(name).eq_ignore_ascii_case("GPU Energy")
    }

    /// Whether a channel is the ANE energy aggregate: `ANE Energy`, optionally
    /// `DIE_<n>_`-prefixed.
    ///
    /// No Apple part seen here publishes one — see [`ane_uj_of`] for what is
    /// counted instead.
    fn is_ane_energy_rail(name: &str) -> bool {
        strip_die_prefix(name).eq_ignore_ascii_case("ANE Energy")
    }

    /// Whether a channel is a per-engine ANE rail — `ANE0`, `DIE_1_ANE0` —
    /// rather than one of its own summands (`ANE0_0`, `ANE0_1`).
    ///
    /// On an M5 Max this is the *only* ANE channel there is: a single `ANE0` in
    /// mJ, with no `ANE Energy` aggregate above it and no sub-rails below it.
    fn is_ane_base_rail(name: &str) -> bool {
        let base = strip_die_prefix(name);
        let Some(rest) = base
            .strip_prefix("ANE")
            .or_else(|| base.strip_prefix("ane"))
        else {
            return false;
        };
        !rest.is_empty() && rest.bytes().all(|b| b.is_ascii_digit())
    }

    /// Over one delta sample: the energy of every Energy Model rail the
    /// counter sums ([`counts_once`]), and of the CPU energy rails alone
    /// ([`is_cpu_energy_rail`], a share of the first), in µJ.
    unsafe fn sum_energy_uj(delta: CFDictionaryRef) -> IoReportReading {
        let key = CFStringCreateWithCString(
            std::ptr::null_mut(),
            c"IOReportChannels".as_ptr() as *const _,
            K_CFSTRING_ENCODING_UTF8,
        );
        if key.is_null() {
            return IoReportReading::default();
        }
        let arr = CFDictionaryGetValue(delta, key as *const _) as CFArrayRef;
        CFRelease(key as CFTypeRef);
        if arr.is_null() {
            return IoReportReading::default();
        }
        let count = CFArrayGetCount(arr);
        let mut total_uj: u64 = 0;
        let mut cpu_uj: u64 = 0;
        let mut gpu_uj: u64 = 0;
        let mut ane_aggregate_uj: u64 = 0;
        let mut ane_base_uj: u64 = 0;
        let mut saw_ane_aggregate = false;
        for i in 0..count {
            let item = CFArrayGetValueAtIndex(arr, i);
            if item.is_null() {
                continue;
            }
            if !cfstring_eq_ic(IOReportChannelGetGroup(item), "energy model") {
                continue;
            }
            let raw = IOReportSimpleGetIntegerValue(item, 0);
            if raw <= 0 {
                continue;
            }
            let name = match cfstring_to_string(IOReportChannelGetChannelName(item)) {
                Some(s) => s,
                None => continue,
            };
            let unit = cfstring_to_string(IOReportChannelGetUnitLabel(item)).unwrap_or_default();
            if is_ane_base_rail(&name) {
                ane_base_uj = ane_base_uj.saturating_add(energy_to_uj(raw, &unit));
            }
            if !counts_once(&name) {
                continue;
            }
            let uj = energy_to_uj(raw, &unit);
            total_uj = total_uj.saturating_add(uj);
            if is_cpu_energy_rail(&name) {
                cpu_uj = cpu_uj.saturating_add(uj);
            }
            if is_gpu_energy_rail(&name) {
                gpu_uj = gpu_uj.saturating_add(uj);
            }
            if is_ane_energy_rail(&name) {
                ane_aggregate_uj = ane_aggregate_uj.saturating_add(uj);
                saw_ane_aggregate = true;
            }
        }
        // An `ANE Energy` aggregate, where a part has one, is already in
        // `total_uj` via `counts_once`. Where there is none, the per-engine
        // rails are the only ANE count there is, and `counts_once` excludes
        // them — so they are added here, once, and not twice.
        let ane_uj = if saw_ane_aggregate {
            ane_aggregate_uj
        } else {
            total_uj = total_uj.saturating_add(ane_base_uj);
            ane_base_uj
        };
        IoReportReading { total_uj, cpu_uj, gpu_uj, ane_uj }
    }

    fn energy_to_uj(raw: c_long, unit: &str) -> u64 {
        let r = (raw.max(0)) as f64;
        let uj = match unit.trim().to_ascii_lowercase().as_str() {
            "pj" => r / 1_000_000.0,
            "nj" => r / 1_000.0,
            "uj" | "µj" => r,
            "mj" => r * 1_000.0,
            "j" => r * 1_000_000.0,
            _ => r / 1_000.0,
        };
        uj as u64
    }

    fn strip_die_prefix(name: &str) -> &str {
        if let Some(rest) = name.strip_prefix("DIE_") {
            let after = rest.trim_start_matches(|c: char| c.is_ascii_digit());
            if let Some(r) = after.strip_prefix('_') {
                return r;
            }
        }
        name
    }

    /// Whether the counter sums this rail, so that energy is counted once. The
    /// aggregates `CPU Energy`, `GPU Energy` and `ANE Energy` (optionally
    /// `DIE_<n>_`-prefixed) are summed; their summands are not. A summand is
    /// any other rail whose name says CPU, GPU or ANE, and also the CPU
    /// summands whose names do not: per-cluster accumulators (`PACC*`, `EACC*`,
    /// `MACC*`) and CPU power managers (`*CPM*`, with their `_SRAM` rails). In
    /// one absolute sample on an M5 Max, `CPU Energy` = `MCPU0` + `MCPU1` +
    /// `PCPU`, and `PCPU` = `PACC_0..5` + `PCPU0..5_SRAM` + `PCPM` +
    /// `PCPM_SRAM`. On an M3 Ultra, each `DIE_<n>_CPU Energy` is the sum of
    /// its `EACC_CPU`, `PACC0_CPU` and `PACC1_CPU`, and each of those is the
    /// sum of its cores, their SRAM and its `_CPM` rails (all to within 1-9
    /// mJ). Summing `PACC_*` or `*_CPM` beside `CPU Energy` would count that
    /// CPU energy twice. The same rule as eoc-meter's (7aa42418).
    fn counts_once(name: &str) -> bool {
        let base = strip_die_prefix(name);
        if base.eq_ignore_ascii_case("CPU Energy")
            || base.eq_ignore_ascii_case("GPU Energy")
            || base.eq_ignore_ascii_case("ANE Energy")
        {
            return true;
        }
        let u = base.to_ascii_uppercase();
        if u.contains("CPU") || u.contains("GPU") || u.contains("ANE") {
            return false;
        }
        let cpu_summand = ["PACC", "EACC", "MACC"].iter().any(|p| u.starts_with(p)) || u.contains("CPM");
        !cpu_summand
    }

    unsafe fn cfstring_to_string(s: CFStringRef) -> Option<String> {
        if s.is_null() {
            return None;
        }
        let mut buf = [0i8; 256];
        let ok =
            CFStringGetCString(s, buf.as_mut_ptr(), buf.len() as c_long, K_CFSTRING_ENCODING_UTF8);
        if !ok {
            return None;
        }
        let bytes: &[u8] = std::slice::from_raw_parts(buf.as_ptr() as *const u8, buf.len());
        let end = bytes.iter().position(|&b| b == 0).unwrap_or(bytes.len());
        let s = std::str::from_utf8(&bytes[..end]).ok()?.trim();
        if s.is_empty() { None } else { Some(s.to_string()) }
    }

    unsafe fn cfstring_eq_ic(s: CFStringRef, target: &str) -> bool {
        cfstring_to_string(s).map(|x| x.eq_ignore_ascii_case(target)).unwrap_or(false)
    }

    #[cfg(test)]
    mod tests {
        use super::*;
        use crate::liveness::{PROBE_BUDGET_CAP, PROBE_TICK};
        use std::cell::{Cell, RefCell};
        use std::rc::Rc;
        use std::sync::atomic::AtomicBool;

        /// Seams through which the tests reach into the production chain. They
        /// exist only in this crate's unit-test build: the library a dependant
        /// or an integration test links has none of them. Each is
        /// thread-local, so it touches only the test thread that sets it, and
        /// each setter returns a guard that unsets it when dropped, on a panic
        /// too.
        pub(super) mod seam {
            use super::super::{Item, ProbeRun};
            use std::cell::{Cell, RefCell};

            /// Given the real FFI read, returns what the probe gets instead.
            type StandIn = Box<dyn FnMut(&dyn Fn() -> Option<Vec<Item>>) -> Option<Vec<Item>>>;

            thread_local! {
                static OPEN_FAILS: Cell<bool> = const { Cell::new(false) };
                static STAND_IN: RefCell<Option<StandIn>> = const { RefCell::new(None) };
                static TAPPED: RefCell<Option<Vec<ProbeRun>>> = const { RefCell::new(None) };
            }

            /// Asked by `EnergyModelSubscription::open`: fail, as on a host
            /// with no Energy Model group?
            pub fn open_fails() -> bool {
                OPEN_FAILS.with(Cell::get)
            }

            /// Asked by `EnergyModelSubscription::items`: `None` when no
            /// stand-in is set, or what the stand-in makes of the real read.
            pub fn sample(read: &dyn Fn() -> Option<Vec<Item>>) -> Option<Option<Vec<Item>>> {
                STAND_IN.with(|s| s.borrow_mut().as_mut().map(|stand_in| stand_in(read)))
            }

            /// Told by `probe_with` of every run it makes; kept while tapped.
            pub fn deliver(run: &ProbeRun) {
                TAPPED.with(|t| {
                    if let Some(runs) = t.borrow_mut().as_mut() {
                        runs.push(run.clone());
                    }
                });
            }

            /// While alive, every Energy Model subscription this thread opens fails.
            pub struct FailingOpens;

            impl Drop for FailingOpens {
                fn drop(&mut self) {
                    OPEN_FAILS.with(|f| f.set(false));
                }
            }

            pub fn fail_opens() -> FailingOpens {
                OPEN_FAILS.with(|f| f.set(true));
                FailingOpens
            }

            /// While alive, every FFI read of this thread's Energy Model
            /// subscriptions goes through the stand-in.
            pub struct StandingIn;

            impl Drop for StandingIn {
                fn drop(&mut self) {
                    STAND_IN.with(|s| *s.borrow_mut() = None);
                }
            }

            pub fn stand_in(
                f: impl FnMut(&dyn Fn() -> Option<Vec<Item>>) -> Option<Vec<Item>> + 'static,
            ) -> StandingIn {
                STAND_IN.with(|s| *s.borrow_mut() = Some(Box::new(f)));
                StandingIn
            }

            /// While alive, keeps every run `probe_with` makes on this thread.
            pub struct Tap;

            impl Tap {
                pub fn runs(&self) -> Vec<ProbeRun> {
                    TAPPED.with(|t| t.borrow_mut().as_mut().map(std::mem::take).unwrap_or_default())
                }

                /// The one run `of` made, or a failure if it made none or several.
                pub fn one_run(&self, of: &str) -> ProbeRun {
                    let mut runs = self.runs();
                    assert_eq!(runs.len(), 1, "{of} made {} probe runs, not one", runs.len());
                    runs.remove(0)
                }
            }

            impl Drop for Tap {
                fn drop(&mut self) {
                    TAPPED.with(|t| *t.borrow_mut() = None);
                }
            }

            pub fn tap() -> Tap {
                TAPPED.with(|t| *t.borrow_mut() = Some(Vec::new()));
                Tap
            }
        }

        #[test]
        fn energy_to_uj_scales_by_unit() {
            assert_eq!(energy_to_uj(5, "mJ"), 5_000);
            assert_eq!(energy_to_uj(5_000, "nJ"), 5);
            assert_eq!(energy_to_uj(5_000_000, "pJ"), 5);
            assert_eq!(energy_to_uj(5, "uJ"), 5);
            assert_eq!(energy_to_uj(5, "µJ"), 5);
            assert_eq!(energy_to_uj(2, "J"), 2_000_000);
            assert_eq!(energy_to_uj(-5, "mJ"), 0, "a negative raw value is no energy");
        }

        /// The counter sums each aggregate once and none of its summands, on
        /// the real Energy Model channel names of both chips. Checked on one
        /// absolute sample of each, macOS 27.0.1:
        /// - M5 Max: `CPU Energy` = `MCPU0` + `MCPU1` + `PCPU` (2,413,310,607
        ///   vs 2,413,310,605 mJ); `PCPU` = `PACC_0..5` + `PCPU0..5_SRAM` +
        ///   `PCPM` + `PCPM_SRAM` (7 mJ apart); `MCPUn` = its six cores + their
        ///   SRAM + `MCPMn` + `MCPMn_SRAM` (5 mJ apart).
        /// - M3 Ultra: `DIE_n_CPU Energy` = its `EACC_CPU` + `PACC0_CPU` +
        ///   `PACC1_CPU` (1-2 mJ apart), each = its cores + their SRAM + its
        ///   `_CPM` + `_CPM_SRAM` (4-9 mJ apart).
        ///
        /// Before, the counter also summed `PACC_*`, `MCPM*`, `PCPM` and their
        /// `_SRAM` rails (M5 Max) and all twelve `_CPM` rails (M3 Ultra), beside
        /// the aggregate they add up to. The summed lists below are everything
        /// the counter sums on each chip; every other name there is a summand.
        #[test]
        fn counts_once_drops_subrails() {
            let m5_max_summed = [
                "CPU Energy", "GPU Energy", "AFR0", "ISP0", "AVE0", "MSR0", "AMCC0", "DCS0", "DRAM0", "DISP0",
                "DISPEXT0", "FAB0", "PCIe Port 0 Energy", "PCIe Port 1 Energy", "apciec0 Energy", "apciec1 Energy",
                "apciec2 Energy",
            ];
            let m3_ultra_summed = [
                "DIE_0_CPU Energy", "DIE_1_CPU Energy", "GPU Energy", "AMCC0_0", "AMCC0_1", "AVE0_0", "AVE0_1",
                "DCS0_0", "DCS0_1", "DISP0_0", "DISP0_1", "DISPEXT0_0", "DISPEXT0_1", "DRAM0_0", "DRAM0_1", "ISP0_0",
                "ISP0_1", "MSR0_0", "MSR0_1", "PCIe Port 0 Energy", "PCIe Port 1 Energy", "PCIe Port 2 Energy",
                "PCIe Port 3 Energy", "apciec0 Energy", "apciec1 Energy", "apciec2 Energy", "apciec3 Energy",
                "apciec4 Energy", "apciec5 Energy",
            ];
            for name in m5_max_summed.iter().chain(&m3_ultra_summed) {
                assert!(counts_once(name), "{name} is not summed");
            }
            // M5 Max: the summands of `CPU Energy`, every family of them.
            for name in [
                "MCPU0", "MCPU1", "PCPU", "MCPU0_0", "MCPU0_5", "MCPU1_3", "MCPU0_2_SRAM", "MCPU1_5_SRAM",
                "PCPU0_SRAM", "PCPU5_SRAM", "PACC_0", "PACC_1", "PACC_2", "PACC_3", "PACC_4", "PACC_5", "MCPM0",
                "MCPM1", "PCPM", "MCPM0_SRAM", "MCPM1_SRAM", "PCPM_SRAM", "MCPU0DTL00", "MCPU0DTL0e", "MCPU1DTL5e",
                "PCPUDTL00", "PCPUDTL513",
            ] {
                assert!(!counts_once(name), "{name}, a summand of CPU Energy on an M5 Max, is summed beside it");
            }
            // M3 Ultra: the summands of `DIE_n_CPU Energy`, every family of them.
            for name in [
                "DIE_0_EACC_CPU", "DIE_1_EACC_CPU", "DIE_0_PACC0_CPU", "DIE_1_PACC1_CPU", "DIE_0_EACC_CPU3",
                "DIE_1_PACC0_CPU5", "DIE_0_EACC_CPU0_SRAM", "DIE_1_PACC1_CPU4_SRAM", "DIE_0_EACC_CPM",
                "DIE_1_EACC_CPM", "DIE_0_PACC0_CPM", "DIE_1_PACC1_CPM", "DIE_0_EACC_CPM_SRAM",
                "DIE_1_PACC0_CPM_SRAM", "DIE_0_PACC1_CPM_SRAM", "ECPUDTL00", "PCPUDTL00", "PCPU1DTL00",
            ] {
                assert!(!counts_once(name), "{name}, a summand of DIE_n_CPU Energy on an M3 Ultra, is summed beside it");
            }
            // The GPU's own rails, beside the `GPU Energy` aggregate.
            for name in ["GPU0", "GPU0_0", "GPU CS0_0", "GPU SRAM0_0", "GPU CS SRAM0_0"] {
                assert!(!counts_once(name), "{name} is summed beside GPU Energy");
            }
            // Neither chip has an `ANE Energy` aggregate, so `counts_once` —
            // which decides by name alone — says no to every ANE rail. That
            // used to mean ANE energy was counted nowhere, and a Neural Engine
            // workload metered as free. It is now counted in `sum_energy_uj`
            // instead, which can see whether an aggregate is present in the
            // sample and falls back to the per-engine rails when it is not
            // ([`is_ane_base_rail`]). This gate stays as it is so the two
            // paths cannot both count it.
            for name in ["ANE0", "ANE0_0", "ANE0_1"] {
                assert!(!counts_once(name), "{name} is summed");
            }
        }

        /// The per-engine ANE rails, and only those, are what the fallback
        /// counts: `ANE0` yes, its own summands `ANE0_0`/`ANE0_1` no, because
        /// adding both would double-count the engine.
        #[test]
        fn only_a_per_engine_ane_rail_is_the_fallback() {
            assert!(is_ane_base_rail("ANE0"));
            assert!(is_ane_base_rail("ANE1"));
            assert!(is_ane_base_rail("DIE_1_ANE0"));
            for name in ["ANE0_0", "ANE0_1", "ANE Energy", "ANE", "GPU0", "CPU Energy"] {
                assert!(!is_ane_base_rail(name), "{name} must not be the fallback");
            }
            // The aggregate is recognised where a part publishes one, so the
            // fallback is not used then.
            assert!(is_ane_energy_rail("ANE Energy"));
            assert!(is_ane_energy_rail("DIE_0_ANE Energy"));
            assert!(!is_ane_energy_rail("ANE0"));
        }

        /// The Neural Engine probe watches the rails the counter sums: the
        /// `ANE Energy` aggregate where a part has one, else every engine's
        /// `ANE<n>`, never both, and nothing else.
        #[test]
        fn the_npu_probe_watches_the_rails_the_counter_sums() {
            let sample = |names: &[&str]| names.iter().map(|n| (n.to_string(), 7)).collect::<Vec<_>>();
            let keys = |rails: Vec<(RailKey, i64)>| rails.into_iter().map(|(k, _)| k.name).collect::<Vec<_>>();
            assert_eq!(keys(ane_rails(&sample(&["CPU Energy", "ANE0", "GPU Energy", "ANE0_0"]))), ["ANE0"]);
            assert_eq!(keys(ane_rails(&sample(&["ANE0", "ANE1", "DIE_1_ANE0"]))), ["ANE0", "ANE1", "DIE_1_ANE0"]);
            assert_eq!(keys(ane_rails(&sample(&["ANE Energy", "ANE0", "ANE1"]))), ["ANE Energy"]);
            assert!(ane_rails(&sample(&["CPU Energy", "GPU Energy", "GPU0"])).is_empty());
        }

        /// The Neural Engine probe ([`npu_status_with`], the function the
        /// cached liveness runs) on scripted Energy Model samples and a
        /// scripted clock:
        /// - an `ANE0` that holds through the load is Frozen. An unprivileged
        ///   reader's does that on macOS 27.0.1, over 3 s of real ANE work;
        /// - one that advances in every interval is Live;
        /// - one that steps once, a lump, is Frozen;
        /// - one engine advancing beside one that holds is Frozen;
        /// - a part with no ANE rail is Unavailable, never a vacuous Live.
        #[test]
        fn the_npu_probe_is_live_only_when_every_ane_rail_keeps_advancing() {
            struct Script {
                next: std::cell::Cell<usize>,
                values: fn(usize) -> Vec<(String, i64)>,
            }
            impl Sampler for Script {
                fn sample(&self) -> Option<GroupSample> {
                    let i = self.next.get();
                    self.next.set(i + 1);
                    let values = (self.values)(i);
                    Some(GroupSample { channels: values.len(), outside_group: 0, values })
                }
            }
            fn run(values: fn(usize) -> Vec<(String, i64)>) -> crate::CounterStatus {
                let (base, clock) = (Instant::now(), std::cell::Cell::new(Duration::ZERO));
                npu_status_with(
                    || Some(Script { next: std::cell::Cell::new(0), values }),
                    || clock.set(clock.get() + Duration::from_millis(100)),
                    || base + clock.get(),
                )
            }
            fn em(ane0: i64, ane1: Option<i64>, i: usize) -> Vec<(String, i64)> {
                let mut v = vec![
                    ("CPU Energy".to_string(), 541_893_638),
                    ("GPU Energy".to_string(), 14_809 * i as i64),
                    ("ANE0".to_string(), ane0),
                ];
                if let Some(a) = ane1 {
                    v.push(("ANE1".to_string(), a));
                }
                v
            }
            use crate::CounterStatus::{Frozen, Live, Unavailable};
            assert_eq!(run(|i| em(1_234, None, i)), Frozen, "an ANE0 holding through the load, beside a moving GPU rail");
            assert_eq!(run(|i| em(1_234 + 40 * i as i64, None, i)), Live, "an ANE0 advancing in every interval");
            assert_eq!(run(|i| em(1_234 + if i >= 3 { 470 } else { 0 }, None, i)), Frozen, "one lump");
            assert_eq!(run(|i| em(1_234 + 40 * i as i64, Some(9), i)), Frozen, "ANE1 holding beside a live ANE0");
            assert_eq!(run(|i| vec![("GPU Energy".to_string(), i as i64)]), Unavailable, "no ANE rail at all");
        }

        /// The fabrics must not bleed into one another: each classifier claims
        /// only its own rails, so a per-fabric figure is that fabric's.
        #[test]
        fn the_fabric_classifiers_are_disjoint() {
            let rails = [
                "CPU Energy", "DIE_0_CPU Energy", "GPU Energy", "DIE_1_GPU Energy", "ANE Energy",
                "ANE0", "GPU0", "PACC_0", "DRAM0", "DCS0",
            ];
            for name in rails {
                let claims = [
                    is_cpu_energy_rail(name),
                    is_gpu_energy_rail(name),
                    is_ane_energy_rail(name),
                    is_ane_base_rail(name),
                ]
                .iter()
                .filter(|c| **c)
                .count();
                assert!(claims <= 1, "{name} is claimed by {claims} fabrics");
            }
        }

        #[test]
        fn only_the_cpu_energy_aggregate_is_a_cpu_rail() {
            assert!(is_cpu_energy_rail("CPU Energy"));
            assert!(is_cpu_energy_rail("cpu energy"));
            assert!(is_cpu_energy_rail("DIE_0_CPU Energy"));
            assert!(is_cpu_energy_rail("DIE_1_CPU Energy"));
            assert!(is_cpu_energy_rail("DIE_12_CPU Energy"));
            assert!(!is_cpu_energy_rail("GPU Energy"));
            assert!(!is_cpu_energy_rail("DIE_0_GPU Energy"));
            assert!(!is_cpu_energy_rail("ANE Energy"));
            assert!(!is_cpu_energy_rail("PCPU"));
            assert!(!is_cpu_energy_rail("MCPU0"));
            assert!(!is_cpu_energy_rail("PACC_0"));
            assert!(!is_cpu_energy_rail("DIE_0_PACC0_CPU0"));
            assert!(is_gpu_energy_rail("GPU Energy"));
            assert!(is_gpu_energy_rail("DIE_1_GPU Energy"));
            assert!(!is_gpu_energy_rail("GPU0"));
            assert!(!is_gpu_energy_rail("CPU Energy"));
        }

        // ── The liveness rule, on scripted samples and a scripted clock ─────

        /// A probe budget, as in production.
        const BUDGET: Duration = Duration::from_millis(1000);

        /// One scripted tick: a 25 ms spin plus a ~6 ms Energy Model sample, the
        /// interval measured on an idle M5 Max.
        const STEP: Duration = Duration::from_millis(31);

        /// One interval on a loaded host.
        const LOADED_STEP: Duration = Duration::from_millis(75);

        /// The tests' own copies of the rule's thresholds: literals, not the
        /// implementation's constants, so a change to one cannot silently move
        /// the other.
        const TEST_MIN_ADVANCES: u32 = 5;
        const TEST_MIN_WINDOW: Duration = Duration::from_millis(300);

        /// An M5 Max-shaped sample: `CPU Energy` at `cpu`, beside a `GPU
        /// Energy` that rises at every sample, as the M5 Max's does while
        /// anything draws. A rule that counted the GPU rail would call every
        /// host live.
        fn m5(i: usize, cpu: i64) -> Sample {
            vec![
                ("GPU Energy".to_string(), 112_249_654_932_804 + 1_000_000 * i as i64),
                ("CPU Energy".to_string(), cpu),
            ]
        }

        /// An M3 Ultra-shaped sample: each die's `CPU Energy` at its own
        /// value, `d0` and `d1`, among a duplicated unprefixed name
        /// (`ECPUDTL00`, once per die, rising) and a `GPU Energy` rising at
        /// every sample. Neither of those is a CPU rail.
        fn m3(i: usize, d0: i64, d1: i64) -> Sample {
            vec![
                ("ECPUDTL00".to_string(), 7_000 + i as i64),
                ("DIE_0_CPU Energy".to_string(), d0),
                ("ECPUDTL00".to_string(), 9_000 + i as i64),
                ("DIE_1_CPU Energy".to_string(), d1),
                ("GPU Energy".to_string(), 5_000_000 * i as i64),
            ]
        }

        /// One probe run through [`watch`] on a script: sample `i` is
        /// `script(i)`, and each tick moves the clock on by `step`, so sample
        /// `i` is taken at `step * i`. Returns the watch, how many samples were
        /// taken, and the clock when it stopped.
        fn scripted(
            mut script: impl FnMut(usize) -> Option<Sample>,
            step: Duration,
            budget: Duration,
        ) -> (RailWatch, usize, Duration) {
            let clock = Cell::new(Duration::ZERO);
            let mut taken = 0;
            let rail_watch = watch(
                || {
                    let s = script(taken);
                    taken += 1;
                    s
                },
                || clock.set(clock.get() + step),
                || clock.get(),
                budget,
            );
            (rail_watch, taken, clock.get())
        }

        /// Advances per CPU rail, as `("name#ordinal", intervals advanced)`.
        fn advances(w: &RailWatch) -> Vec<(String, u32)> {
            w.rails.iter().map(|(k, n)| (format!("{}#{}", k.name, k.ordinal), *n)).collect()
        }

        fn rail(name: &str, n: u32) -> (String, u32) {
            (name.to_string(), n)
        }

        /// The first interval, counting from 1, after which the rule calls
        /// the rail live when fed `script(0..=max)` by hand, sample `i` at
        /// `step * i`, with no stopping rule; `None` if it never does.
        fn first_live_interval(script: impl Fn(usize) -> Sample, step: Duration, max: usize) -> Option<usize> {
            let mut w = RailWatch::default();
            w.observe(&script(0), Duration::ZERO);
            (1..=max).find(|&i| {
                w.observe(&script(i), step * i as u32);
                w.is_live()
            })
        }

        /// `CPU Energy` through the two-step batch refresh seen on an M5 Max
        /// (macOS 27.0.1) by a group-only watcher sampling every ~16 ms:
        /// 2,643,843,378 -> 2,705,607,863 (+61,764,485), then -> 2,705,611,298
        /// (+3,435) 64 ms later, flat around both. Here the first step lands
        /// by sample `first` and the second by sample `second`.
        fn two_step(i: usize, first: usize, second: usize) -> i64 {
            if i < first {
                2_643_843_378
            } else if i < second {
                2_705_607_863
            } else {
                2_705_611_298
            }
        }

        /// An M5 Max-shaped sample through [`two_step`], with `MCPU0`,
        /// `MCPU1` and `PCPU`, the summands of `CPU Energy`, stepping twice
        /// with it as they were seen to (their values here are made up). They
        /// are not CPU rails, and the rule never reads them.
        fn m5_two_step(i: usize, first: usize, second: usize) -> Sample {
            let steps = i64::from(i >= first) + i64::from(i >= second);
            let mut s = m5(i, two_step(i, first, second));
            for (name, base) in [("MCPU0", 118_503_220), ("MCPU1", 121_847_018), ("PCPU", 2_403_493_140)] {
                s.push((name.to_string(), base + 1_000 * steps));
            }
            s
        }

        /// (a) The refresh seen on an M5 Max: `CPU Energy` steps once, from
        /// 480,083,160 to 541,893,638 mJ, and holds, while `GPU Energy` rises
        /// at every sample. Frozen, with the step counted once, after the whole
        /// budget. Compared with the FIRST sample (dfec5d44's defect), the rail
        /// would show a rise in every interval after the step and read Live.
        #[test]
        fn an_m5_max_batch_refresh_mid_probe_is_frozen() {
            let (w, taken, stopped) =
                scripted(|i| Some(m5(i, if i < 2 { 480_083_160 } else { 541_893_638 })), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a batch refresh read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 1)]);
            // The whole budget: at 31 ms a tick, the clock reaches 1 s at the 33rd.
            assert_eq!((w.intervals, taken, stopped), (33, 34, STEP * 33));
        }

        /// (*) The two-step refresh seen on an M5 Max ([`two_step`]), with
        /// the steps in consecutive intervals and 62 ms apart: two advancing
        /// intervals of one rail, which the two-advance rule called Live.
        /// Frozen, after the whole budget. And on a loaded host, where two
        /// 160 ms intervals span 320 ms and both advanced (100%), two advances
        /// are still not five: Frozen.
        #[test]
        fn the_observed_two_step_refresh_is_frozen() {
            for (first, second) in [(3, 4), (3, 5)] {
                assert_eq!(first_live_interval(|i| m5_two_step(i, first, second), STEP, 200), None);
                let (w, taken, stopped) = scripted(|i| Some(m5_two_step(i, first, second)), STEP, BUDGET);
                assert_eq!(
                    w.verdict(),
                    Some(CpuRail::Frozen),
                    "a two-step refresh (steps by samples {first} and {second}) read as live: {:?}",
                    advances(&w)
                );
                assert_eq!(advances(&w), [rail("CPU Energy#0", 2)]);
                assert_eq!((w.intervals, taken, stopped), (33, 34, STEP * 33));
            }
            assert_eq!(first_live_interval(|i| m5_two_step(i, 1, 2), LOADED_STEP, 200), None);
            let (w, _, _) = scripted(|i| Some(m5_two_step(i, 1, 2)), LOADED_STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a two-step refresh on a loaded host read as live: {:?}", advances(&w));
            assert_eq!((w.intervals, advances(&w)), (14, vec![rail("CPU Energy#0", 2)]));
        }

        /// (*) A refresh published in three, four or five steps within
        /// 150 ms, each landing in its own interval, at the very start of the
        /// window. Three or four are fewer than five advances. Five are five
        /// advances in five intervals (100%), but then the window spans 155 ms;
        /// by the tenth interval, when it first spans 300 ms, five of ten is
        /// 50%. The same five steps later in the window (intervals 11 to 15)
        /// are a third of the intervals. Frozen, each after the whole budget.
        #[test]
        fn a_refresh_published_in_three_to_five_steps_is_frozen() {
            for steps in 3..=5 {
                let refresh = move |i: usize| m5(i, 2_643_843_378 + 1_000_000 * i.min(steps) as i64);
                assert_eq!(first_live_interval(refresh, STEP, 200), None, "{steps} steps at the start");
                let (w, taken, _) = scripted(|i| Some(refresh(i)), STEP, BUDGET);
                assert_eq!(
                    w.verdict(),
                    Some(CpuRail::Frozen),
                    "a refresh in {steps} steps at the start of the window read as live: {:?}",
                    advances(&w)
                );
                assert_eq!((advances(&w), w.intervals, taken), (vec![rail("CPU Energy#0", steps as u32)], 33, 34));
            }
            let later = |i: usize| m5(i, 2_643_843_378 + 1_000_000 * (i.clamp(10, 15) - 10) as i64);
            assert_eq!(first_live_interval(later, STEP, 200), None, "five steps later in the window");
            let (w, _, _) = scripted(|i| Some(later(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a refresh in 5 steps mid-window read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 5)]);
        }

        /// (*) The same two-step publication on both of an M3 Ultra's dies:
        /// each die's `CPU Energy` steps twice within 64 ms (DIE_0 by samples
        /// 3 and 5, DIE_1 by samples 3 and 4), the first steps the sizes seen
        /// there, beside a duplicated unprefixed name and a GPU rail, both
        /// rising. Frozen: two advances per die, where the two-advance rule
        /// called each die live.
        #[test]
        fn an_m3_ultra_refresh_stepping_each_die_twice_is_frozen() {
            // The second step's size is not from a sample: 2,113 mJ stands in.
            let die = |i: usize, base: i64, first_step: i64, second_by: usize| {
                base + i64::from(i >= 3) * first_step + i64::from(i >= second_by) * 2_113
            };
            let (w, _, _) = scripted(
                |i| {
                    Some(vec![
                        ("ECPUDTL00".to_string(), 7_000 + i as i64),
                        ("DIE_0_CPU Energy".to_string(), die(i, 21_170_718, 1_344_869, 5)),
                        ("ECPUDTL00".to_string(), 9_000 + i as i64),
                        ("DIE_1_CPU Energy".to_string(), die(i, 23_300_102, 1_391_637, 4)),
                        ("GPU Energy".to_string(), 5_000_000 * i as i64),
                    ])
                },
                STEP,
                BUDGET,
            );
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "each die stepping twice read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 2), rail("DIE_1_CPU Energy#0", 2)]);
        }

        /// (b) The refresh seen on an M3 Ultra: both dies' `CPU Energy` step in
        /// the same sample, +1,344,869 and +1,391,637 mJ, among a duplicated
        /// unprefixed name (`ECPUDTL00`, once per die, rising) and a rising GPU
        /// rail. Frozen: one advance per die, never summed into a Live.
        #[test]
        fn an_m3_ultra_two_die_refresh_in_one_sample_is_frozen() {
            let (w, _, _) = scripted(
                |i| {
                    let (d0, d1) = if i < 3 { (21_170_718, 23_300_102) } else { (22_515_587, 24_691_739) };
                    Some(vec![
                        ("ECPUDTL00".to_string(), 7_000 + i as i64),
                        ("DIE_0_CPU Energy".to_string(), d0),
                        ("ECPUDTL00".to_string(), 9_000 + i as i64),
                        ("DIE_1_CPU Energy".to_string(), d1),
                        ("GPU Energy".to_string(), 5_000_000 * i as i64),
                    ])
                },
                STEP,
                BUDGET,
            );
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "one refresh of both dies read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 1), rail("DIE_1_CPU Energy#0", 1)]);
        }

        /// (c) Two channels both named `CPU Energy`, stepping together once:
        /// two rails, one advance each, Frozen. Keyed by name alone they would
        /// be one rail, advancing twice in one interval.
        #[test]
        fn two_same_named_rails_stepping_together_once_are_frozen() {
            let (w, _, _) = scripted(
                |i| {
                    let step = if i < 2 { 0 } else { 1_300_000 };
                    Some(vec![
                        ("CPU Energy".to_string(), 21_170_718 + step),
                        ("CPU Energy".to_string(), 23_300_102 + step),
                    ])
                },
                STEP,
                BUDGET,
            );
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "two same-named rails read as one live rail: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 1), rail("CPU Energy#1", 1)]);
        }

        /// (d) A live rail: `CPU Energy` rising by the smallest possible step,
        /// one raw unit, at every sample, 31 ms apart. It has five advances at
        /// the fifth interval, but the window then spans 155 ms. Live at the
        /// tenth, the first interval at which the window spans 300 ms (310 ms),
        /// and the probe stops there: eleven samples, ten ticks. The same on a
        /// two-die part with both dies rising: the second rail does not make it
        /// later.
        #[test]
        fn a_rail_advancing_at_every_interval_is_live_at_five_advances_and_300_ms() {
            let rising = |i: usize| m5(i, 541_893_638 + i as i64);
            assert_eq!(first_live_interval(rising, STEP, 200), Some(10), "31 ms intervals first span 300 ms at the 10th");
            let (w, taken, stopped) = scripted(|i| Some(rising(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "a rail rising at every sample: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 10)]);
            assert_eq!((w.intervals, taken, stopped), (10, 11, STEP * 10), "a live rail must stop the probe at once");
            assert_eq!(w.window, Duration::from_millis(310));
            assert!(w.window >= TEST_MIN_WINDOW && w.window - STEP < TEST_MIN_WINDOW, "live at {:?}", w.window);
            let both_dies = |i: usize| m3(i, 21_170_718 + i as i64, 23_300_102 + i as i64);
            assert_eq!(first_live_interval(both_dies, STEP, 200), Some(10));
            let (w, _, _) = scripted(|i| Some(both_dies(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "{:?}", advances(&w));
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 10), rail("DIE_1_CPU Energy#0", 10)]);
        }

        /// A live rail on a loaded host, 100 ms an interval: the window spans
        /// 300 ms at the third interval, but three advances are not five. Live
        /// at the fifth, 500 ms in, and not before.
        #[test]
        fn a_live_rail_on_a_loaded_host_is_live_after_five_intervals() {
            let rising = |i: usize| m5(i, 541_893_638 + i as i64);
            assert_eq!(first_live_interval(rising, LOADED_STEP, 200), Some(5), "live before its fifth advance");
            let (w, taken, stopped) = scripted(|i| Some(rising(i)), LOADED_STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "{:?}", advances(&w));
            assert_eq!(
                (w.intervals, taken, stopped, w.window),
                (5, 6, Duration::from_millis(375), Duration::from_millis(375))
            );
        }

        /// A live rail that misses one interval in five advances in exactly
        /// 80% of them, and that is enough: Live at the tenth interval (8 of
        /// 10, 310 ms). One that misses two in five advances in 60% or less,
        /// and is never live: Frozen after the whole budget. And on a loaded
        /// host, where the window and the five advances come early, a rail
        /// that missed two of its first five intervals is not yet live at five
        /// advances in seven (71%), nor at 6 of 8 or 7 of 9, and is live once
        /// its share reaches 80%, at 8 of 10.
        #[test]
        fn a_rail_must_advance_in_80_percent_of_the_intervals() {
            // Sample `i` holds how many of intervals 1..=i advanced, so
            // interval `k` advances unless `missed(k)`.
            let missing = |missed: fn(usize) -> bool| {
                move |i: usize| m5(i, 541_893_638 + (1..=i).filter(|&k| !missed(k)).count() as i64)
            };
            let one_in_five = missing(|k| k % 5 == 0);
            assert_eq!(first_live_interval(one_in_five, STEP, 200), Some(10));
            let (w, _, _) = scripted(|i| Some(one_in_five(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "a rail advancing in 80% of the intervals: {:?}", advances(&w));
            assert_eq!((w.intervals, advances(&w)), (10, vec![rail("CPU Energy#0", 8)]));
            let two_in_five = missing(|k| k % 5 == 0 || k % 5 == 1);
            assert_eq!(first_live_interval(two_in_five, STEP, 200), None);
            let (w, _, _) = scripted(|i| Some(two_in_five(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a rail advancing in 60% of the intervals: {:?}", advances(&w));
            assert_eq!((w.intervals, advances(&w)), (33, vec![rail("CPU Energy#0", 20)]));
            let two_early = missing(|k| k == 2 || k == 4);
            assert_eq!(first_live_interval(two_early, LOADED_STEP, 200), Some(10), "live under 80%");
            let (w, taken, _) = scripted(|i| Some(two_early(i)), LOADED_STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "{:?}", advances(&w));
            assert_eq!((w.intervals, taken, advances(&w)), (10, 11, vec![rail("CPU Energy#0", 8)]));
        }

        /// (e) Every sample fails: the probe keeps sampling a tick apart up to
        /// the five-budget cap, and gives no verdict, which reports Unavailable.
        #[test]
        fn failed_samples_keep_sampling_to_the_cap_and_give_no_verdict() {
            let (w, taken, stopped) = scripted(|_| None, PROBE_TICK, BUDGET);
            assert_eq!(w.verdict(), None);
            assert_eq!(status_of(w.verdict()), crate::IoReportStatus::Unavailable);
            assert_eq!(stopped, BUDGET * PROBE_BUDGET_CAP, "the probe stopped at {stopped:?}, not at the cap");
            // 5 s of 25 ms ticks, plus the first sample.
            assert_eq!(taken, 201);
        }

        /// A failed sample is skipped, not a reset: the next usable sample is
        /// compared with the last usable one.
        #[test]
        fn a_failed_sample_is_skipped_and_the_pairing_goes_on() {
            // Usable, failed, +2, failed, +2, ...: each interval spans two
            // ticks, 62 ms, and advances. The window is wall time between
            // usable samples, so it spans 310 ms at the fifth interval: Live
            // there, after eleven samples.
            let (w, taken, _) = scripted(|i| (i % 2 == 0).then(|| m5(i, 541_893_638 + i as i64)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "{:?}", advances(&w));
            assert_eq!((w.intervals, taken, w.window), (5, 11, Duration::from_millis(310)));
            // A refresh between two failures is still one step.
            let (w, _, _) = scripted(
                |i| (i % 3 != 1).then(|| m5(i, if i < 4 { 480_083_160 } else { 541_893_638 })),
                STEP,
                BUDGET,
            );
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "{:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 1)]);
        }

        /// (f) Past the budget, the probe keeps sampling until five intervals
        /// have counted, and stops at the five-budget cap even without them.
        #[test]
        fn past_the_budget_the_probe_stops_only_with_five_counted_intervals_or_at_the_cap() {
            let held = |i| Some(m5(i, 541_893_638));
            // 600 ms a tick: no interval counts, so it samples to the cap, past
            // the budget with fewer than five.
            let (w, taken, stopped) = scripted(held, Duration::from_millis(600), BUDGET);
            assert_eq!(
                (w.verdict(), w.intervals, w.counted, taken, stopped),
                (Some(CpuRail::Frozen), 9, 0, 10, Duration::from_millis(5400)),
                "past the budget with fewer than five counted, the probe must keep sampling"
            );
            // And a rail seen only that slowly is not proved live by it, though
            // it advanced in every interval: a rail stepping twice a second does.
            let (w, _, stopped) = scripted(|i| Some(m5(i, 541_893_638 + i as i64)), Duration::from_millis(600), BUDGET);
            assert_eq!((w.verdict(), w.counted, stopped), (Some(CpuRail::Frozen), 0, Duration::from_millis(5400)));
            // 1.5 s a tick: four intervals reach 6 s, past the 5 s cap: stop,
            // Frozen, with four.
            let (w, taken, stopped) = scripted(held, Duration::from_millis(1500), BUDGET);
            assert_eq!(
                (w.verdict(), w.intervals, taken, stopped),
                (Some(CpuRail::Frozen), 4, 5, Duration::from_millis(6000)),
                "the probe must stop at the cap"
            );
        }

        /// (g) DIE_0 steps once and DIE_1 steps once, in different intervals:
        /// Frozen. Advances are counted per rail, never summed across dies.
        #[test]
        fn one_step_on_each_die_in_different_intervals_is_frozen() {
            let (w, _, _) = scripted(
                |i| {
                    Some(vec![
                        ("DIE_0_CPU Energy".to_string(), if i < 2 { 21_170_718 } else { 22_515_587 }),
                        ("DIE_1_CPU Energy".to_string(), if i < 5 { 23_300_102 } else { 24_691_739 }),
                    ])
                },
                STEP,
                BUDGET,
            );
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "one step per die read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 1), rail("DIE_1_CPU Energy#0", 1)]);
        }

        /// Every CPU rail must keep advancing, not one. The counter sums both
        /// dies' `CPU Energy` on an M3 Ultra-shaped part, so a Live on one die
        /// beside a frozen one would grade a figure that misses the frozen die
        /// as a whole-CPU reading.
        /// - Both dies rising at every interval: Live at the tenth interval
        ///   (310 ms), exactly where one rail alone is (a single-die host is
        ///   judged as before).
        /// - DIE_0 rising at every interval, DIE_1 holding: Frozen after the
        ///   whole budget, DIE_0 advancing in all 33 intervals and DIE_1 in
        ///   none. Fed by hand for 200 intervals, never live. DIE_0 alone meets
        ///   the rule at the tenth interval, so a rule satisfied by any one
        ///   rail calls this Live.
        /// - The mirror, DIE_0 holding and DIE_1 rising: Frozen.
        /// - DIE_0 rising, DIE_1 republished once in a batch refresh: Frozen.
        #[test]
        fn one_live_die_beside_a_frozen_die_is_frozen() {
            let single = |i: usize| m5(i, 541_893_638 + i as i64);
            let both = |i: usize| m3(i, 21_170_718 + i as i64, 23_300_102 + i as i64);
            assert_eq!(first_live_interval(single, STEP, 200), Some(10));
            assert_eq!(first_live_interval(both, STEP, 200), Some(10), "a second live die moved the verdict");
            let (w, _, _) = scripted(|i| Some(both(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Live), "both dies rising: {:?}", advances(&w));

            let die_0_live = |i: usize| m3(i, 21_170_718 + i as i64, 23_300_102);
            assert_eq!(first_live_interval(die_0_live, STEP, 200), None, "DIE_0 beside a frozen DIE_1 became live");
            let (w, taken, _) = scripted(|i| Some(die_0_live(i)), STEP, BUDGET);
            assert_eq!(
                w.verdict(),
                Some(CpuRail::Frozen),
                "DIE_0 live beside a frozen DIE_1 read as live: {:?}",
                advances(&w)
            );
            assert_eq!(status_of(w.verdict()), crate::IoReportStatus::CpuRailFrozen);
            assert_eq!((w.intervals, taken), (33, 34), "a mixed part must be watched for the whole budget");
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 33), rail("DIE_1_CPU Energy#0", 0)]);

            let die_1_live = |i: usize| m3(i, 21_170_718, 23_300_102 + i as i64);
            let (w, _, _) = scripted(|i| Some(die_1_live(i)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "DIE_1 live beside a frozen DIE_0: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 0), rail("DIE_1_CPU Energy#0", 33)]);

            let die_1_refresh = |i: usize| m3(i, 21_170_718 + i as i64, if i < 3 { 23_300_102 } else { 24_691_739 });
            let (w, _, _) = scripted(|i| Some(die_1_refresh(i)), STEP, BUDGET);
            assert_eq!(
                w.verdict(),
                Some(CpuRail::Frozen),
                "DIE_0 live beside a batch-refreshed DIE_1: {:?}",
                advances(&w)
            );
            assert_eq!(advances(&w), [rail("DIE_0_CPU Energy#0", 33), rail("DIE_1_CPU Energy#0", 1)]);
        }

        /// No interval at all is no verdict: a baseline alone is not one.
        /// Intervals with no CPU rail are Absent, however much the GPU moves,
        /// and however long they are watched: over the whole budget, past the
        /// 300 ms window, no rail is not every rail advancing (`all` over no
        /// rails is vacuously true, and would read as Live).
        #[test]
        fn no_interval_is_no_verdict_and_no_cpu_rail_is_absent() {
            let mut w = RailWatch::default();
            assert_eq!(w.verdict(), None);
            w.observe(&[("GPU Energy".to_string(), 1)], Duration::ZERO);
            assert_eq!(w.verdict(), None, "a baseline alone is not an interval");
            w.observe(&[("GPU Energy".to_string(), 2)], STEP);
            w.observe(&[("GPU Energy".to_string(), 3)], STEP * 2);
            assert_eq!(w.verdict(), Some(CpuRail::Absent));
            let (w, taken, _) =
                scripted(|i| Some(vec![("GPU Energy".to_string(), 1_000_000 * i as i64)]), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Absent), "a group with no CPU rail, watched {:?}", w.window);
            assert_eq!(status_of(w.verdict()), crate::IoReportStatus::CpuRailAbsent);
            assert_eq!((w.intervals, taken), (33, 34), "a group with no CPU rail must be watched for the whole budget");
        }

        /// The stopping rule on its own: within the budget keep watching until
        /// the rail proves live; past it only until a live rail could have
        /// advanced five times; never past five budgets.
        #[test]
        fn the_probe_samples_until_live_or_long_enough_to_tell() {
            let budget = BUDGET;
            let held = m5(0, 541_893_638);
            let mut w = RailWatch::default();
            assert!(w.wants_more(Duration::ZERO, budget), "nothing observed yet");
            assert!(w.wants_more(budget * 2, budget), "no interval yet, past the budget");
            for k in 0..=4 {
                w.observe(&held, STEP * k);
            }
            assert_eq!(w.intervals, 4);
            assert!(w.wants_more(budget * 2, budget), "four intervals cannot show five advances");
            assert!(w.wants_more(budget * 5 - Duration::from_millis(1), budget));
            assert!(!w.wants_more(budget * 5, budget), "hard cap: five budgets");
            assert!(!RailWatch::default().wants_more(budget * 5, budget), "hard cap with no interval");
            w.observe(&held, STEP * 5);
            assert!(w.wants_more(budget / 2, budget), "within budget: keep watching");
            assert!(!w.wants_more(budget, budget), "budget spent, five intervals: stop");
            assert_eq!(w.verdict(), Some(CpuRail::Frozen));
            let mut live = RailWatch::default();
            for i in 0..10 {
                live.observe(&m5(i, i as i64), STEP * i as u32);
                assert!(live.wants_more(STEP * i as u32, budget), "sample {i}: not yet live, keep watching");
            }
            live.observe(&m5(10, 10), STEP * 10);
            assert!(!live.wants_more(STEP * 10, budget), "live: stop at once");
        }

        /// Each verdict reports its status, and no verdict (not one interval
        /// observed) is Unavailable, never Live.
        #[test]
        fn each_verdict_reports_its_status() {
            use crate::IoReportStatus as S;
            assert_eq!(status_of(None), S::Unavailable);
            assert_eq!(status_of(Some(CpuRail::Absent)), S::CpuRailAbsent);
            assert_eq!(status_of(Some(CpuRail::Frozen)), S::CpuRailFrozen);
            assert_eq!(status_of(Some(CpuRail::Live)), S::Live);
        }

        /// No verdict is `Unavailable`: not `Live`, and not `CpuRailAbsent`.
        #[test]
        fn no_verdict_is_unavailable() {
            assert_eq!(status_of(None), crate::IoReportStatus::Unavailable);
        }

        /// A rail whose raw value FELL between consecutive samples did not
        /// advance: a reset or a wrap is not energy spent. A rail falling at
        /// every sample is Frozen with no advance; one real rise and one wrap
        /// is one advance, not two.
        #[test]
        fn a_decrease_between_samples_is_not_an_advance() {
            let (w, _, _) = scripted(|i| Some(m5(i, 541_893_638 - i as i64)), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a rail falling at every sample read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 0)], "a fall counted as an advance");
            let wraps = |i: usize| match i {
                0 => 4_294_967_000,
                1 => 4_294_967_200,
                _ => 150,
            };
            let (w, _, _) = scripted(|i| Some(m5(i, wraps(i))), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a rise and a wrap read as live: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 1)], "a wrap counted as an advance");
        }

        /// A rail missing from the previous sample has nothing to be compared
        /// with: the sample it appears in only sets its baseline. A `CPU
        /// Energy` present in every other sample never advances, and a second
        /// die that first shows up mid-probe and holds does not either.
        #[test]
        fn a_rail_missing_from_the_previous_sample_only_sets_its_baseline() {
            let gpu_only = |i: usize| vec![("GPU Energy".to_string(), 1_000_000 * i as i64)];
            let (w, _, _) =
                scripted(|i| Some(if i % 2 == 0 { m5(i, 541_893_638) } else { gpu_only(i) }), STEP, BUDGET);
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "a rail read as live for reappearing: {:?}", advances(&w));
            assert_eq!(advances(&w), [rail("CPU Energy#0", 0)], "a reappearing rail counted as an advance");
            let (w, _, _) = scripted(
                |i| {
                    let mut s = vec![("DIE_0_CPU Energy".to_string(), 21_170_718)];
                    if i >= 5 {
                        s.push(("DIE_1_CPU Energy".to_string(), 23_300_102));
                    }
                    Some(s)
                },
                STEP,
                BUDGET,
            );
            assert_eq!(w.verdict(), Some(CpuRail::Frozen), "{:?}", advances(&w));
            assert_eq!(
                advances(&w),
                [rail("DIE_0_CPU Energy#0", 0), rail("DIE_1_CPU Energy#0", 0)],
                "a rail new in a sample counted as an advance"
            );
        }

        // ── probe_with, with a stand-in for every part ──────────────────────

        /// A channel of the Energy Model group, as the FFI would read it.
        fn item(name: &str, raw: i64) -> Item {
            Item { group: Some("Energy Model".to_string()), name: Some(name.to_string()), raw }
        }

        /// An M5 Max-shaped read: `GPU Energy` rising at every sample beside
        /// `CPU Energy` at `cpu`.
        fn m5_items(i: usize, cpu: i64) -> Vec<Item> {
            vec![item("GPU Energy", m5_gpu(i)), item("CPU Energy", cpu)]
        }

        fn m5_gpu(i: usize) -> i64 {
            112_249_654_932_804 + 1_000_000 * i as i64
        }

        /// The batch refresh seen on an M5 Max: `CPU Energy` steps once, after
        /// the second sample, and holds.
        fn m5_refresh(i: usize) -> i64 {
            if i < 2 { 480_083_160 } else { 541_893_638 }
        }

        /// An M3 Ultra-shaped read in which the two dies' `CPU Energy` advance
        /// in turn: DIE_0 in odd intervals (sample 0 to 1, 2 to 3, ...), DIE_1
        /// in even ones. Each die advances in half the intervals, and is not
        /// live. Summed, the two dies would be one rail advancing in every
        /// interval, which is live. Beside them, a duplicated unprefixed name
        /// rising on both dies and a rising GPU rail.
        fn two_dies_advancing_in_turn(i: usize) -> Vec<Item> {
            vec![
                item("ECPUDTL00", 7_000 + i as i64),
                item("DIE_0_CPU Energy", die_0(i)),
                item("ECPUDTL00", 9_000 + i as i64),
                item("DIE_1_CPU Energy", die_1(i)),
                item("GPU Energy", 5_000_000 * i as i64),
            ]
        }

        /// [`m3`] as the FFI hands it over: each channel an Energy Model item.
        fn m3_items(i: usize, d0: i64, d1: i64) -> Vec<Item> {
            m3(i, d0, d1).into_iter().map(|(name, raw)| item(&name, raw)).collect()
        }

        fn die_0(i: usize) -> i64 {
            21_170_718 + 1_000 * i.div_ceil(2) as i64
        }

        fn die_1(i: usize) -> i64 {
            23_300_102 + 1_000 * (i / 2) as i64
        }

        /// Each die's advances when [`two_dies_advancing_in_turn`] ran for
        /// `intervals` intervals: DIE_0 in the odd ones, DIE_1 in the even.
        fn in_turn_advances(intervals: u32) -> [(String, u32); 2] {
            [rail("DIE_0_CPU Energy#0", intervals.div_ceil(2)), rail("DIE_1_CPU Energy#0", intervals / 2)]
        }

        /// A scripted subscription: read `i` is `script(i)`, made into a
        /// [`GroupSample`] by [`group_sample`] as the real subscription's are.
        /// Its sample calls are counted in `calls`, which the test keeps.
        struct Scripted<F> {
            script: F,
            calls: Rc<Cell<usize>>,
        }

        impl<F: Fn(usize) -> Option<Vec<Item>>> Sampler for Scripted<F> {
            fn sample(&self) -> Option<GroupSample> {
                let i = self.calls.get();
                self.calls.set(i + 1);
                (self.script)(i).map(group_sample)
            }
        }

        /// The subscription type of an opener that never opens one.
        type NoSubscription = Scripted<fn(usize) -> Option<Vec<Item>>>;

        /// Scripted clocks: wall time and thread CPU time stand still, except
        /// when [`fake_tick`] moves them.
        struct FakeClocks {
            base: Instant,
            wall: Cell<Duration>,
            cpu: Cell<Duration>,
        }

        impl FakeClocks {
            fn new() -> Self {
                Self { base: Instant::now(), wall: Cell::new(Duration::ZERO), cpu: Cell::new(Duration::ZERO) }
            }
        }

        impl Clocks for FakeClocks {
            fn now(&self) -> Instant {
                self.base + self.wall.get()
            }

            fn thread_cpu(&self) -> Option<Duration> {
                Some(self.cpu.get())
            }
        }

        /// A scripted tick: [`STEP`] of wall time and [`PROBE_TICK`] of thread
        /// CPU time pass on `clocks`, and `count` goes up.
        fn fake_tick<'a>(clocks: &'a FakeClocks, count: &'a Cell<usize>) -> impl FnMut() + 'a {
            move || {
                clocks.wall.set(clocks.wall.get() + STEP);
                clocks.cpu.set(clocks.cpu.get() + PROBE_TICK);
                count.set(count.get() + 1);
            }
        }

        /// Rails as `("name#ordinal", raw)`.
        fn named(rails: &[(RailKey, i64)]) -> Vec<(String, i64)> {
            rails.iter().map(|(k, v)| (format!("{}#{}", k.name, k.ordinal), *v)).collect()
        }

        /// [`probe_with`], the composition [`host_status`] runs, with an opener
        /// that finds no subscription: the opener is asked once, nothing is
        /// sampled, nothing ticks, and there is no verdict, which is
        /// Unavailable.
        #[test]
        fn probe_with_no_subscription_samples_nothing_and_never_ticks() {
            let (clocks, ticks, opened) = (FakeClocks::new(), Cell::new(0), Cell::new(0));
            let run = probe_with(
                || {
                    opened.set(opened.get() + 1);
                    None::<NoSubscription>
                },
                fake_tick(&clocks, &ticks),
                &clocks,
                BUDGET,
            );
            assert_eq!(opened.get(), 1, "the opener was asked {} times", opened.get());
            assert_eq!(
                (run.samples.len(), ticks.get(), run.ticks.len()),
                (0, 0, 0),
                "sampled or ticked with no subscription"
            );
            assert!(run.watch.is_none(), "watched a subscription that did not open");
            assert_eq!(run.verdict(), None);
            assert_eq!(status_of(run.verdict()), crate::IoReportStatus::Unavailable);
        }

        /// No subscription, or a subscription that never yields a sample: no
        /// verdict, so `Unavailable`, never `Live`, never `CpuRailAbsent`.
        #[test]
        fn no_energy_model_subscription_or_no_sample_is_unavailable() {
            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let no_group = probe_with(|| None::<NoSubscription>, fake_tick(&clocks, &ticks), &clocks, BUDGET);
            assert_eq!(status_of(no_group.verdict()), crate::IoReportStatus::Unavailable, "no Energy Model subscription");
            let silent = Scripted { script: |_| None, calls: Rc::new(Cell::new(0)) };
            let no_sample = probe_with(|| Some(silent), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            assert_eq!(
                status_of(no_sample.verdict()),
                crate::IoReportStatus::Unavailable,
                "a subscription that never samples"
            );
            assert!(no_sample.samples.iter().all(|s| s.taken.is_none()));
        }

        /// One batch refresh through [`probe_with`]: Frozen, after the whole
        /// budget. The record holds, for every sample, exactly the CPU and GPU
        /// values the script gave and the rule was handed, and every tick as
        /// the clocks saw it.
        #[test]
        fn probe_with_one_batch_refresh_is_frozen() {
            let (clocks, ticks, calls) = (FakeClocks::new(), Cell::new(0), Rc::new(Cell::new(0)));
            let sub = Scripted { script: |i| Some(m5_items(i, m5_refresh(i))), calls: Rc::clone(&calls) };
            let run = probe_with(|| Some(sub), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Frozen), "a batch refresh read as live: {:?}", advances(w));
            assert_eq!(status_of(run.verdict()), crate::IoReportStatus::CpuRailFrozen);
            assert_eq!(advances(w), [rail("CPU Energy#0", 1)]);
            // The whole budget: at 31 ms a tick, the clock reaches 1 s at the 33rd.
            assert_eq!((calls.get(), run.samples.len(), ticks.get(), run.ticks.len()), (34, 34, 33, 33));
            for (i, s) in run.samples.iter().enumerate() {
                let t = s.taken.as_ref().expect("every scripted sample is usable");
                assert_eq!((t.channels, t.outside_group), (2, 0), "sample {i}");
                assert_eq!(
                    named(&t.cpu_rails),
                    [("CPU Energy#0".to_string(), m5_refresh(i))],
                    "sample {i}: the record is not what the script gave"
                );
                assert_eq!(named(&t.gpu_rails), [("GPU Energy#0".to_string(), m5_gpu(i))], "sample {i}");
                assert_eq!(s.at, clocks.base + STEP * i as u32, "sample {i} recorded at the wrong time");
            }
            assert!(run.ticks.iter().all(|k| k.cpu == Some(PROBE_TICK) && k.wall == STEP), "{:?}", run.ticks);
        }

        /// A rail advancing at every sample, through [`probe_with`] and its
        /// wall clock: Live at the tenth interval, when the window first spans
        /// 300 ms, with eleven samples and ten ticks; and the run records the
        /// clock reading the rule was handed after each of the eleven sample
        /// calls, the first and last of which span the window.
        #[test]
        fn probe_with_a_sustained_advance_is_live() {
            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let sub = Scripted { script: |i| Some(m5_items(i, 541_893_638 + i as i64)), calls: Rc::new(Cell::new(0)) };
            let run = probe_with(|| Some(sub), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Live), "{:?}", advances(w));
            assert_eq!(status_of(run.verdict()), crate::IoReportStatus::Live);
            assert_eq!((run.samples.len(), ticks.get(), run.ticks.len()), (11, 10, 10));
            assert_eq!((advances(w), w.window), (vec![rail("CPU Energy#0", 10)], Duration::from_millis(310)));
            let expected: Vec<Instant> = (0..11u32).map(|i| clocks.base + STEP * i).collect();
            assert_eq!(run.checks, expected, "the clock readings the rule was handed");
        }

        /// The budget starts once the subscription is open, so a slow open
        /// costs the probe none of it: an open of 950 ms, then a rail advancing
        /// at every sample, is Live exactly where it is with an open that takes
        /// no time. With the budget running from before the open, the probe
        /// would stop at its fifth interval, with 155 ms of intervals counted,
        /// and call the live rail Frozen.
        #[test]
        fn probe_with_starts_its_budget_once_the_subscription_is_open() {
            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let sub = Scripted { script: |i| Some(m5_items(i, 541_893_638 + i as i64)), calls: Rc::new(Cell::new(0)) };
            let open = || {
                clocks.wall.set(Duration::from_millis(950));
                Some(sub)
            };
            let run = probe_with(open, fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Live), "{:?}", advances(w));
            assert_eq!((run.samples.len(), w.intervals), (11, 10));
            assert_eq!(run.started, clocks.base + Duration::from_millis(950), "the budget started before the open returned");
        }

        /// The observed two-step refresh through [`probe_with`]: Frozen, two
        /// advances, after the whole budget.
        #[test]
        fn probe_with_the_observed_two_step_refresh_is_frozen() {
            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let sub = Scripted { script: |i| Some(m5_items(i, two_step(i, 3, 4))), calls: Rc::new(Cell::new(0)) };
            let run = probe_with(|| Some(sub), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Frozen), "a two-step refresh read as live: {:?}", advances(w));
            assert_eq!((advances(w), run.samples.len()), (vec![rail("CPU Energy#0", 2)], 34));
        }

        /// Two dies advancing in turn, through [`probe_with`]: Frozen, each
        /// die advancing in half the intervals, and the record holds each die's
        /// own value. A transform between the sampler and the rule that summed
        /// the dies would see one rail advance in every interval, and say Live.
        #[test]
        fn probe_with_two_dies_advancing_in_turn_is_frozen() {
            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let sub = Scripted { script: |i| Some(two_dies_advancing_in_turn(i)), calls: Rc::new(Cell::new(0)) };
            let run = probe_with(|| Some(sub), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Frozen), "two dies advancing in turn read as live: {:?}", advances(w));
            assert_eq!(w.intervals, 33);
            assert_eq!(advances(w), in_turn_advances(w.intervals));
            for (i, s) in run.samples.iter().enumerate() {
                let t = s.taken.as_ref().expect("every scripted sample is usable");
                assert_eq!(
                    named(&t.cpu_rails),
                    [("DIE_0_CPU Energy#0".to_string(), die_0(i)), ("DIE_1_CPU Energy#0".to_string(), die_1(i))],
                    "sample {i}: the rule was not handed each die's own value"
                );
            }
        }

        /// Two dies through [`probe_with`]: DIE_0 rising at every interval
        /// beside a DIE_1 that holds is Frozen, after the whole budget, with
        /// each die's own advances in the record; both rising is Live at the
        /// tenth interval and stops the probe there, as one rail does.
        #[test]
        fn probe_with_one_live_die_beside_a_frozen_die_is_frozen() {
            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let sub = Scripted {
                script: |i| Some(m3_items(i, 21_170_718 + i as i64, 23_300_102)),
                calls: Rc::new(Cell::new(0)),
            };
            let run = probe_with(|| Some(sub), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Frozen), "one live die beside a frozen one: {:?}", advances(w));
            assert_eq!(status_of(run.verdict()), crate::IoReportStatus::CpuRailFrozen);
            assert_eq!((w.intervals, run.samples.len()), (33, 34));
            assert_eq!(advances(w), [rail("DIE_0_CPU Energy#0", 33), rail("DIE_1_CPU Energy#0", 0)]);

            let (clocks, ticks) = (FakeClocks::new(), Cell::new(0));
            let sub = Scripted {
                script: |i| Some(m3_items(i, 21_170_718 + i as i64, 23_300_102 + i as i64)),
                calls: Rc::new(Cell::new(0)),
            };
            let run = probe_with(|| Some(sub), fake_tick(&clocks, &ticks), &clocks, BUDGET);
            let w = run.watch.as_ref().expect("the scripted subscription opened");
            assert_eq!(run.verdict(), Some(CpuRail::Live), "both dies rising: {:?}", advances(w));
            assert_eq!((run.samples.len(), ticks.get()), (11, 10));
            assert_eq!(advances(w), [rail("DIE_0_CPU Energy#0", 10), rail("DIE_1_CPU Energy#0", 10)]);
        }

        /// [`group_sample`] counts every channel, counts the ones outside the
        /// group, and hands on each in-group channel's own raw value, in order.
        #[test]
        fn group_sample_counts_channels_and_hands_on_each_rails_own_value() {
            let other = |group: Option<&str>, name: Option<&str>, raw| Item {
                group: group.map(str::to_string),
                name: name.map(str::to_string),
                raw,
            };
            let g = group_sample(vec![
                item("DIE_0_CPU Energy", 5),
                other(Some("CPU Stats"), Some("CPU Energy"), 99),
                item("DIE_1_CPU Energy", 7),
                other(None, Some("GPU Energy"), 1),
                other(Some("energy model"), None, 3),
                item("GPU Energy", 11),
            ]);
            assert_eq!((g.channels, g.outside_group), (6, 2));
            assert_eq!(
                g.values,
                [
                    ("DIE_0_CPU Energy".to_string(), 5),
                    ("DIE_1_CPU Energy".to_string(), 7),
                    ("GPU Energy".to_string(), 11)
                ]
            );
        }

        // ── The tests' own clocks ───────────────────────────────────────────

        /// Clock ids from macOS `<time.h>`, the tests' own: not the
        /// implementation's constant, so a wrong id there cannot move the
        /// tests' clocks with it.
        const TEST_CLOCK_PROCESS_CPUTIME_ID: c_int = 12;
        const TEST_CLOCK_THREAD_CPUTIME_ID: c_int = 16;

        unsafe extern "C" {
            fn clock_gettime_nsec_np(clock_id: c_int) -> u64;
        }

        /// A clock read the tests' own way (`clock_gettime_nsec_np`), not
        /// through the probe's [`thread_cpu_time`].
        fn test_clock(id: c_int) -> Duration {
            let ns = unsafe { clock_gettime_nsec_np(id) };
            assert_ne!(ns, 0, "clock_gettime_nsec_np({id}) failed");
            Duration::from_nanos(ns)
        }

        /// CPU time this thread has used, by the tests' own clock.
        fn test_thread_cpu() -> Duration {
            test_clock(TEST_CLOCK_THREAD_CPUTIME_ID)
        }

        /// Spin until this thread has used `cpu` more CPU time, by the tests'
        /// own clock: real work, owing nothing to the implementation's burn.
        fn spin_cpu(cpu: Duration) {
            let start = test_thread_cpu();
            let mut acc: u64 = 0;
            while test_thread_cpu().saturating_sub(start) < cpu {
                for _ in 0..1_000 {
                    acc = std::hint::black_box(acc.wrapping_add(1));
                }
            }
        }

        /// The CPU floor and wall cap the tests hold each tick to: their own
        /// literals, not the implementation's constants.
        const TICK_CPU_FLOOR: Duration = Duration::from_millis(25);
        const TICK_WALL_CAP: Duration = Duration::from_millis(500);

        /// How far a CPU reading may pass the wall time around it: the
        /// granularity of reading two clocks, nothing more.
        const CLOCK_SLACK: Duration = Duration::from_millis(1);

        /// How far the probe's own record of a tick's CPU time may fall short
        /// of the tests' measurement, which spans the tick and the probe's
        /// bookkeeping between two reads.
        const RECORD_SLACK: Duration = Duration::from_millis(2);

        /// A moment by the tests' own clocks: wall time and this thread's CPU
        /// time.
        #[derive(Debug, Clone, Copy)]
        struct Stamp {
            wall: Instant,
            cpu: Duration,
        }

        impl Stamp {
            /// Wall, then CPU: where an interval begins whose CPU time must fit
            /// inside its wall time.
            fn opening() -> Self {
                let wall = Instant::now();
                Self { wall, cpu: test_thread_cpu() }
            }

            /// CPU, then wall: where such an interval ends.
            fn closing() -> Self {
                let cpu = test_thread_cpu();
                Self { wall: Instant::now(), cpu }
            }

            /// (CPU, wall) from `self` to `later`.
            fn until(self, later: Stamp) -> (Duration, Duration) {
                (later.cpu.saturating_sub(self.cpu), later.wall.saturating_duration_since(self.wall))
            }
        }

        /// Each tick between two FFI reads, by the tests' own clocks: the probe
        /// burned [`TICK_CPU_FLOOR`] of this thread's CPU between every two
        /// reads, unless the tick ran into [`TICK_WALL_CAP`] of wall time, and
        /// no tick shows more CPU than wall time. `reads` are the (entered,
        /// left) stamps of each read, in order. Returns each tick's (CPU, wall).
        fn assert_ticks_burned(reads: &[(Stamp, Stamp)], what: &str) -> Vec<(Duration, Duration)> {
            let ticks: Vec<(Duration, Duration)> = reads.windows(2).map(|w| w[0].1.until(w[1].0)).collect();
            for (k, &(cpu, wall)) in ticks.iter().enumerate() {
                assert!(
                    cpu <= wall + CLOCK_SLACK,
                    "{what}: tick {k} shows {cpu:?} of this thread's CPU in {wall:?} of wall time, by the tests' clocks"
                );
                assert!(
                    cpu >= TICK_CPU_FLOOR || wall >= TICK_WALL_CAP,
                    "{what}: tick {k} used {cpu:?} of this thread's CPU in {wall:?}, by the tests' own clock: a tick \
                     must burn {TICK_CPU_FLOOR:?} of thread CPU, and only a {TICK_WALL_CAP:?} wall cap may cut that short"
                );
            }
            ticks
        }

        /// The probe's thread clock ([`thread_cpu_time`], which [`burn`] and
        /// [`HostClocks`] read) is this thread's own CPU time. Checked on the
        /// tests' own clocks, read with their own clock ids:
        /// - not wall time: across a 100 ms sleep it advances under 5 ms;
        /// - not the process's CPU time: while a helper thread burns 100 ms of
        ///   CPU and this thread waits for it, it advances under 5 ms, though
        ///   the process clock advances at least 100 ms;
        /// - it tracks this thread's CPU: across 30 ms of this thread's CPU by
        ///   the tests' clock, it advances the same, within 1 ms.
        #[test]
        fn the_probe_reads_this_threads_own_cpu_clock() {
            let probe = || thread_cpu_time().expect("the probe's thread clock could not be read");
            let before = probe();
            std::thread::sleep(Duration::from_millis(100));
            let slept = probe().saturating_sub(before);

            let (before, process_before) = (probe(), test_clock(TEST_CLOCK_PROCESS_CPUTIME_ID));
            let helper = std::thread::scope(|s| {
                s.spawn(|| {
                    let start = test_thread_cpu();
                    spin_cpu(Duration::from_millis(100));
                    test_thread_cpu().saturating_sub(start)
                })
                .join()
                .expect("the helper thread panicked")
            });
            let waited = probe().saturating_sub(before);
            let process = test_clock(TEST_CLOCK_PROCESS_CPUTIME_ID).saturating_sub(process_before);

            let (before, tests_before) = (probe(), test_thread_cpu());
            spin_cpu(Duration::from_millis(30));
            let (tracked, by_tests) = (probe().saturating_sub(before), test_thread_cpu().saturating_sub(tests_before));

            eprintln!(
                "ioreport thread clock: across a 100ms sleep it advanced {slept:?}; while a helper burned {helper:?} \
                 (process clock +{process:?}) it advanced {waited:?}; across {by_tests:?} of this thread's CPU by \
                 the tests' clock it advanced {tracked:?}"
            );
            assert!(
                slept < Duration::from_millis(5),
                "the probe's thread clock advanced {slept:?} across a 100ms sleep of this thread: it counts time this \
                 thread did not run (wall time, or other threads' CPU)"
            );
            assert!(helper >= Duration::from_millis(100), "the helper burned only {helper:?}");
            assert!(
                process >= Duration::from_millis(100),
                "the process clock advanced only {process:?} while a helper burned {helper:?}, so this test cannot tell a \
                 process clock from a thread clock"
            );
            assert!(
                waited < Duration::from_millis(5),
                "the probe's thread clock advanced {waited:?} while this thread waited on a helper burning {helper:?}: it \
                 reads the process's CPU time"
            );
            assert!(
                tracked.abs_diff(by_tests) <= Duration::from_millis(1),
                "the probe's thread clock advanced {tracked:?} across {by_tests:?} of this thread's CPU by the tests' clock"
            );
        }

        // ── host_status itself, through the seams ───────────────────────────

        /// Runs [`host_status`] itself on this thread with every FFI read
        /// replaced by `script(i)`. Everything else is real: the subscription it
        /// opens, [`burn_tick`], [`HostClocks`] and the budget. Returns the
        /// status, the run (from the tap), each read's (entered, left) stamps
        /// by the tests' own clocks, and how long `host_status` took by the
        /// tests' wall clock.
        fn host_status_on_script(
            script: impl Fn(usize) -> Option<Vec<Item>> + 'static,
        ) -> (crate::IoReportStatus, ProbeRun, Vec<(Stamp, Stamp)>, Duration) {
            let reads = Rc::new(RefCell::new(Vec::new()));
            let (log, next) = (Rc::clone(&reads), Cell::new(0));
            let _script = seam::stand_in(move |_real_read| {
                let entered = Stamp::closing();
                let i = next.get();
                next.set(i + 1);
                let items = script(i);
                log.borrow_mut().push((entered, Stamp::opening()));
                items
            });
            let tap = seam::tap();
            let started = Instant::now();
            let status = host_status();
            let took = started.elapsed();
            let run = tap.one_run("host_status");
            (status, run, reads.take(), took)
        }

        /// No Energy Model subscription opened, so `host_status` never read the
        /// script: the no-subscription case, which must be Unavailable with no
        /// read. Not a pass by default: the oracle, on its own all-channel
        /// subscription, must find no Energy Model channel either, or the
        /// opener failed on a host that has the group.
        fn no_energy_model_group_here(status: crate::IoReportStatus, reads: &[(Stamp, Stamp)]) {
            let census = oracle_census();
            eprintln!(
                "host_status: no Energy Model subscription opened; status={status:?}, {} reads; the oracle counts (in \
                 that group, in all) = {census:?}",
                reads.len()
            );
            assert!(
                census.is_none_or(|(group, _)| group == 0),
                "no Energy Model subscription opened, but the oracle reads that group's channels (in it, in all) = \
                 {census:?}: the opener failed on a host that has the group"
            );
            assert_eq!(status, crate::IoReportStatus::Unavailable, "no Energy Model subscription opened");
            assert!(reads.is_empty(), "read {} samples with no subscription", reads.len());
        }

        /// `host_status` itself, with its Energy Model subscription failing: no
        /// FFI read, no tick, no CPU burned, no verdict, so Unavailable (never
        /// Live, never CpuRailAbsent). A branch put into `host_status` for this
        /// case runs here.
        #[test]
        fn host_status_with_no_energy_model_subscription_is_unavailable() {
            let _fail = seam::fail_opens();
            let reads = Rc::new(Cell::new(0));
            let counted = Rc::clone(&reads);
            let _count = seam::stand_in(move |read| {
                counted.set(counted.get() + 1);
                read()
            });
            let tap = seam::tap();
            let cpu = test_thread_cpu();
            let status = host_status();
            let cpu = test_thread_cpu().saturating_sub(cpu);
            let runs = tap.runs();
            eprintln!(
                "host_status, subscription failing: status={status:?}, {} probe runs, {} reads, {} ticks, {cpu:?} of CPU",
                runs.len(),
                reads.get(),
                runs.iter().map(|r| r.ticks.len()).sum::<usize>()
            );
            assert_eq!(status, crate::IoReportStatus::Unavailable, "no Energy Model subscription");
            assert_eq!(runs.len(), 1, "host_status made {} probe runs, not one: it decides through probe_with", runs.len());
            let run = &runs[0];
            assert!(run.watch.is_none(), "probe_with watched a subscription that did not open");
            assert_eq!((reads.get(), run.samples.len(), run.ticks.len()), (0, 0, 0), "read or ticked with no subscription");
            assert!(cpu < TICK_CPU_FLOOR, "host_status burned {cpu:?} of CPU with no subscription to watch");
        }

        /// `host_status` itself, with the two-step refresh seen on an M5 Max
        /// ([`two_step`], steps in consecutive intervals) in place of its FFI
        /// reads: Frozen, two advances, having burned a tick of CPU between
        /// every two reads, by the tests' own clocks. The two-advance rule
        /// said Live here, through every production link but the FFI read. A
        /// rail that is not live keeps the probe going for its whole budget, so
        /// `host_status` took at least [`crate::CPU_RAIL_LIVENESS_BUDGET`]: a
        /// lower bound, which load can only lengthen.
        #[test]
        fn host_status_on_the_observed_two_step_refresh_is_frozen() {
            let _hw = crate::ioreport_hw_lock();
            let refresh = |i| two_step(i, 3, 4);
            let (status, run, reads, took) = host_status_on_script(move |i| Some(m5_items(i, refresh(i))));
            let Some(w) = &run.watch else {
                return no_energy_model_group_here(status, &reads);
            };
            let ticks = assert_ticks_burned(&reads, "host_status on the two-step refresh");
            eprintln!(
                "host_status, scripted two-step refresh: status={status:?}, advances {:?} in {} intervals over {:?}, {} \
                 reads, median tick CPU by the tests' clock {:?}, took {took:?}",
                advances(w),
                w.intervals,
                w.window,
                reads.len(),
                median(&ticks.iter().map(|t| t.0).collect::<Vec<_>>())
            );
            assert_eq!(status, crate::IoReportStatus::CpuRailFrozen, "a two-step refresh read as live: {:?}", advances(w));
            assert!(
                took >= crate::CPU_RAIL_LIVENESS_BUDGET,
                "host_status gave up on a rail that is not live after {took:?}, before its {:?} budget",
                crate::CPU_RAIL_LIVENESS_BUDGET
            );
            // Every interval's advance, unless the host held one past the cap.
            if w.counted == w.intervals {
                assert_eq!(advances(w), [rail("CPU Energy#0", 2)]);
            }
            assert!(w.intervals >= TEST_MIN_ADVANCES, "Frozen on {} intervals", w.intervals);
            assert_eq!(reads.len(), run.samples.len(), "the record and the reads disagree");
            for (i, s) in run.samples.iter().enumerate() {
                let t = s.taken.as_ref().expect("every scripted sample is usable");
                assert_eq!(named(&t.cpu_rails), [("CPU Energy#0".to_string(), refresh(i))], "sample {i}");
                assert_eq!(named(&t.gpu_rails), [("GPU Energy#0".to_string(), m5_gpu(i))], "sample {i}");
            }
        }

        /// `host_status` itself, with a rail advancing at every read: Live,
        /// once the rail has advanced in at least five intervals and the
        /// window, by the probe's real wall clock, spans 300 ms, each interval
        /// a tick of burned CPU. The window is wall time, not a count or a
        /// constant: it is the span between two of the probe's own clock
        /// readings, and by the tests' own clock each of those readings was
        /// taken after the read before it had returned and before the next
        /// read began (the last, before `host_status` returned). And the probe
        /// stops as soon as it is live: at the check one interval earlier, by
        /// the probe's own readings, the window spanned less than 300 ms or
        /// the rail had fewer than five advances.
        ///
        /// Every assertion is on the probe's own readings, recorded as the
        /// rule was handed them ([`ProbeRun::checks`]), or on the order of
        /// readings of one monotonic clock on one thread; none is on a window
        /// rebuilt from when the sample calls ended. Between the end of a call
        /// and the probe's reading the probe records the call, and a loaded
        /// host can deschedule its thread there for any length of time, so a
        /// rebuilt window is off by the difference of two such delays, which
        /// nothing bounds, in either direction. A 1 ms slack on that rebuild
        /// failed a correct probe on a loaded CI host: rebuilt, the window one
        /// interval before the last was 307 ms, yet the probe went on, which
        /// it does only when its own reading there was under 300 ms.
        #[test]
        fn host_status_on_a_sustained_advance_is_live() {
            let _hw = crate::ioreport_hw_lock();
            let (status, run, reads, took) = host_status_on_script(|i| Some(m5_items(i, 541_893_638 + i as i64)));
            // By the tests' clock, after `host_status` returned: after the
            // probe's last reading.
            let returned = Instant::now();
            let Some(w) = &run.watch else {
                return no_energy_model_group_here(status, &reads);
            };
            let ticks = assert_ticks_burned(&reads, "host_status on a sustained advance");
            let n = w.intervals as usize;
            // The window the rule held at check `k`: from the probe's first
            // reading to its `k`-th (every scripted sample is usable, and
            // below every interval counted).
            let window_at = |k: usize| Some(run.checks.get(k)?.saturating_duration_since(*run.checks.first()?));
            let before_last = n.checked_sub(1).and_then(window_at);
            // For the log only: how far each of the probe's readings trailed
            // the end of its sample call, the error a window rebuilt from
            // call ends would carry.
            let lag =
                run.samples.iter().zip(&run.checks).map(|(s, c)| c.saturating_duration_since(s.at + s.wall)).max();
            eprintln!(
                "host_status, scripted sustained advance: status={status:?}, advances {:?} in {} intervals ({} \
                 counted), window {:?} by the probe's clock ({before_last:?} at the check before), readings up to \
                 {lag:?} after their calls ended, median tick CPU {:?}, took {took:?}",
                advances(w),
                w.intervals,
                w.counted,
                w.window,
                median(&ticks.iter().map(|t| t.0).collect::<Vec<_>>())
            );
            assert_eq!(
                (reads.len(), run.samples.len(), run.ticks.len(), run.checks.len()),
                (n + 1, n + 1, n, n + 1),
                "reads, samples, ticks, checks"
            );
            assert_eq!(
                Some(w.window),
                window_at(n),
                "the rule's window is not the span of the probe's own readings {:?}",
                run.checks
            );
            for (k, &check) in run.checks.iter().enumerate() {
                let (read_returned, next) = (reads[k].1.wall, reads.get(k + 1).map_or(returned, |r| r.0.wall));
                assert!(
                    read_returned <= check && check <= next,
                    "the probe's reading after sample call {k} is {:?} into the run, but by the tests' clock that \
                     call's read returned {:?} in and the next read began (or host_status returned) {:?} in: the \
                     window is not this wall clock, read where the rule is handed each sample",
                    check.saturating_duration_since(run.started),
                    read_returned.saturating_duration_since(run.started),
                    next.saturating_duration_since(run.started)
                );
            }
            // On the real clock, so only while the host left every interval near
            // the tick: one held past the cap proves nothing either way.
            if w.counted < w.intervals {
                assert!(matches!(status, crate::IoReportStatus::Live | crate::IoReportStatus::CpuRailFrozen), "{status:?}");
                eprintln!("host_status: the host held {} interval(s) past the cap, which proves nothing", w.intervals - w.counted);
                return;
            }
            assert_eq!(status, crate::IoReportStatus::Live, "a rail advancing at every read: {:?}", advances(w));
            assert_eq!(advances(w), [rail("CPU Energy#0", w.intervals)]);
            assert!(w.intervals >= TEST_MIN_ADVANCES, "Live after {} intervals", w.intervals);
            assert!(w.window >= TEST_MIN_WINDOW, "Live over a {:?} window", w.window);
            let watched = returned.saturating_duration_since(reads[0].1.wall);
            assert!(
                watched >= TEST_MIN_WINDOW,
                "Live, but by the tests' clock only {watched:?} passed from the first read's return to host_status's"
            );
            let before_last = before_last.expect("fewer than two checks");
            assert!(
                w.intervals - 1 < TEST_MIN_ADVANCES || before_last < TEST_MIN_WINDOW,
                "the probe did not stop as soon as the rail was live: at the check one interval earlier it had {} \
                 advances over {before_last:?} by its own clock",
                w.intervals - 1
            );
        }

        /// `host_status` itself, with a CPU rail that holds at every read, as
        /// every CPU rail does on macOS 27.0.1 between batch refreshes, beside
        /// a GPU rail that rises at every read: Frozen, with no advance, after
        /// its whole budget, having burned a tick of CPU between every two
        /// reads by the tests' own clocks, and ticked once before every
        /// re-read.
        #[test]
        fn host_status_on_a_scripted_constant_rail_is_frozen() {
            let _hw = crate::ioreport_hw_lock();
            let (status, run, reads, took) = host_status_on_script(|i| Some(m5_items(i, 541_893_638)));
            let Some(w) = &run.watch else {
                return no_energy_model_group_here(status, &reads);
            };
            let ticks = assert_ticks_burned(&reads, "host_status on a scripted constant rail");
            eprintln!(
                "host_status, scripted constant rail: status={status:?}, advances {:?}, {} reads, {} ticks, median tick \
                 CPU by the tests' clock {:?}, took {took:?}",
                advances(w),
                reads.len(),
                run.ticks.len(),
                median(&ticks.iter().map(|t| t.0).collect::<Vec<_>>())
            );
            assert_eq!(status, crate::IoReportStatus::CpuRailFrozen, "a constant rail read as {status:?}: {:?}", advances(w));
            assert_eq!(advances(w), [rail("CPU Energy#0", 0)], "a constant rail counted as advancing");
            assert!(
                took >= crate::CPU_RAIL_LIVENESS_BUDGET,
                "host_status gave up on a constant rail after {took:?}, before its {:?} budget",
                crate::CPU_RAIL_LIVENESS_BUDGET
            );
            assert_eq!(reads.len(), run.samples.len(), "the record and the reads disagree");
            assert_eq!(run.ticks.len() + 1, run.samples.len(), "the probe must tick once before every re-read");
            assert!(w.intervals >= TEST_MIN_ADVANCES, "Frozen on {} intervals", w.intervals);
        }

        /// `host_status` itself, with two dies advancing in turn: Frozen, each
        /// die advancing in half the intervals. A transform anywhere between
        /// the FFI read and the rule that summed the dies' rails would see one
        /// rail advance in every interval and say Live.
        #[test]
        fn host_status_on_two_dies_advancing_in_turn_is_frozen() {
            let _hw = crate::ioreport_hw_lock();
            let (status, run, reads, _) = host_status_on_script(|i| Some(two_dies_advancing_in_turn(i)));
            let Some(w) = &run.watch else {
                return no_energy_model_group_here(status, &reads);
            };
            assert_ticks_burned(&reads, "host_status on two dies advancing in turn");
            assert_eq!(status, crate::IoReportStatus::CpuRailFrozen, "two dies advancing in turn read as live: {:?}", advances(w));
            assert!(w.intervals >= TEST_MIN_ADVANCES, "Frozen on {} intervals", w.intervals);
            if w.counted == w.intervals {
                assert_eq!(advances(w), in_turn_advances(w.intervals));
            }
        }

        /// One die live beside a frozen one, through the production
        /// composition [`host_status`] (the real tick and clocks, scripted
        /// reads): `CpuRailFrozen`, DIE_0 advancing in every interval and
        /// DIE_1 in none.
        #[test]
        fn host_status_on_one_live_die_beside_a_frozen_die_is_frozen() {
            let _hw = crate::ioreport_hw_lock();
            let (status, run, reads, _) =
                host_status_on_script(|i| Some(m3_items(i, 21_170_718 + i as i64, 23_300_102)));
            let Some(w) = &run.watch else {
                return no_energy_model_group_here(status, &reads);
            };
            assert_ticks_burned(&reads, "host_status on one live die beside a frozen one");
            assert_eq!(
                status,
                crate::IoReportStatus::CpuRailFrozen,
                "one live die beside a frozen one read as live: {:?}",
                advances(w)
            );
            assert!(w.intervals >= TEST_MIN_ADVANCES, "Frozen on {} intervals", w.intervals);
            if w.counted == w.intervals {
                assert_eq!(advances(w), [rail("DIE_0_CPU Energy#0", w.intervals), rail("DIE_1_CPU Energy#0", 0)]);
            }
        }

        // ── Against the hardware ────────────────────────────────────────────

        /// The median of some durations (the upper one of an even count).
        fn median(of: &[Duration]) -> Option<Duration> {
            let mut v = of.to_vec();
            v.sort();
            v.get(v.len() / 2).copied()
        }

        /// The group-only pin by cost: a group sample takes ~8-9 ms of the
        /// sampling thread's CPU however contended, an all-channel one ~100-125
        /// ms.
        const GROUP_SAMPLE_CPU_CEILING: Duration = Duration::from_millis(50);

        /// How long the oracle may take to read beside the probe before the
        /// test gives up on it.
        const ORACLE_GIVE_UP: Duration = Duration::from_secs(60);

        /// How long the probe's second read is held for the oracle to see a
        /// rail move after its first.
        const WITNESS_WAIT: Duration = Duration::from_secs(3);

        /// What the independent oracle saw on this host.
        #[derive(Debug, PartialEq)]
        enum Oracle {
            NoIoReport,
            NoCpuRail,
            CpuRailMoved(bool),
            /// Fewer than [`ORACLE_MIN_CHANGES`] reads after the first, even
            /// with the window extended: too few for a moving rail to meet the
            /// oracle's bar, so no evidence either way. Every test fails on it.
            TooFewReads,
        }

        /// The oracle's bar for a moving rail: it changed at this many reads at
        /// least, and at 80% of the reads at least ([`oracle_kept_moving`]).
        /// Also the fewest reads after the first that the oracle takes, since a
        /// rail cannot change at more reads than there are. Its own literal,
        /// not the implementation's constant.
        const ORACLE_MIN_CHANGES: u32 = 5;

        /// How many times its window the oracle may keep reading to get the
        /// [`ORACLE_MIN_CHANGES`] reads it needs.
        const ORACLE_WINDOW_CAP: u32 = 5;

        /// Did a rail that changed at `changes` of `reads` reads keep moving?
        /// At least [`ORACLE_MIN_CHANGES`] changes, at least 80% of the reads.
        /// A live rail changes at nearly every read. The batch refreshes seen
        /// were published in one step or two within 64 ms. The oracle's reads
        /// are 0.13 s or more apart, so even a refresh spread over 150 ms holds
        /// at most two of them, and shows as a change at three reads at most:
        /// it cannot vouch for a probe that called it live.
        fn oracle_kept_moving(changes: u32, reads: u32) -> bool {
            changes >= ORACLE_MIN_CHANGES && changes * 5 >= reads * 4
        }

        /// The failure for an oracle run with too little evidence.
        fn too_few_reads(run: &OracleRun, window: Duration) -> ! {
            panic!(
                "oracle evidence: only {} reads after the first in {:?} (window {window:?}, extended up to \
                 {ORACLE_WINDOW_CAP}x): fewer than {ORACLE_MIN_CHANGES} cannot show a rail changing at \
                 {ORACLE_MIN_CHANGES} reads, so this run can neither clear nor convict the probe (the host is too \
                 loaded for an all-channel IOReport sample, or its reads fail)",
                run.reads,
                run.took
            )
        }

        /// One oracle run: its verdict, and what it read to reach it.
        #[derive(Debug)]
        struct OracleRun {
            verdict: Oracle,
            /// Reads taken after the first.
            reads: u32,
            /// How long the oracle read for: its window, or longer if it had
            /// to extend it to get [`ORACLE_MIN_CHANGES`] reads.
            took: Duration,
            /// Per CPU rail, at how many reads its absolute value had changed.
            cpu_changes: Vec<u32>,
            /// The same for `GPU Energy`. When the GPU draws, this shows the
            /// reads are fresh samples; an idle GPU shows few changes or none.
            gpu_changes: Vec<u32>,
        }

        impl OracleRun {
            fn bare(verdict: Oracle) -> Self {
                Self { verdict, reads: 0, took: Duration::ZERO, cpu_changes: Vec::new(), gpu_changes: Vec::new() }
            }
        }

        /// The oracle's own CFString conversion, so it does not share the
        /// implementation's `cfstring_to_string`.
        fn oracle_string(s: CFStringRef) -> Option<String> {
            if s.is_null() {
                return None;
            }
            let mut buf = [0u8; 512];
            let ok = unsafe {
                CFStringGetCString(s, buf.as_mut_ptr() as *mut i8, buf.len() as c_long, K_CFSTRING_ENCODING_UTF8)
            };
            if !ok {
                return None;
            }
            let end = buf.iter().position(|&b| b == 0)?;
            String::from_utf8(buf[..end].to_vec()).ok()
        }

        /// The oracle's own all-channel subscription. `None` if IOReport does
        /// not open. Released by [`oracle_unsubscribe`].
        fn oracle_subscribe() -> Option<(IOReportSubscriptionRef, CFMutableDictionaryRef)> {
            unsafe {
                let all = IOReportCopyAllChannels(0, 0);
                if all.is_null() {
                    return None;
                }
                let mut chans: CFMutableDictionaryRef = std::ptr::null_mut();
                let sub = IOReportCreateSubscription(std::ptr::null(), all, &mut chans, 0, std::ptr::null());
                CFRelease(all as CFTypeRef);
                if sub.is_null() || chans.is_null() {
                    if !sub.is_null() {
                        CFRelease(sub);
                    }
                    if !chans.is_null() {
                        CFRelease(chans as CFTypeRef);
                    }
                    return None;
                }
                Some((sub, chans))
            }
        }

        fn oracle_unsubscribe((sub, chans): (IOReportSubscriptionRef, CFMutableDictionaryRef)) {
            unsafe {
                CFRelease(sub);
                CFRelease(chans as CFTypeRef);
            }
        }

        /// One channel of one oracle read.
        #[derive(Debug, Clone)]
        struct OracleChannel {
            group: String,
            name: String,
            unit: String,
            raw: i64,
        }

        /// From one plain sample (no delta), every channel whose name `keep`s,
        /// in any group, with its ABSOLUTE raw value.
        fn oracle_channels(
            sub: IOReportSubscriptionRef,
            chans: CFMutableDictionaryRef,
            keep: impl Fn(&str) -> bool,
        ) -> Option<Vec<OracleChannel>> {
            unsafe {
                let smp = IOReportCreateSamples(sub, chans, std::ptr::null());
                if smp.is_null() {
                    return None;
                }
                let key = CFStringCreateWithCString(
                    std::ptr::null_mut(),
                    c"IOReportChannels".as_ptr() as *const _,
                    K_CFSTRING_ENCODING_UTF8,
                );
                let mut out = Vec::new();
                if !key.is_null() {
                    let arr = CFDictionaryGetValue(smp, key as *const _) as CFArrayRef;
                    CFRelease(key as CFTypeRef);
                    if !arr.is_null() {
                        for i in 0..CFArrayGetCount(arr) {
                            let it = CFArrayGetValueAtIndex(arr, i);
                            if it.is_null() {
                                continue;
                            }
                            let name = oracle_string(IOReportChannelGetChannelName(it)).unwrap_or_default();
                            if keep(&name) {
                                out.push(OracleChannel {
                                    group: oracle_string(IOReportChannelGetGroup(it)).unwrap_or_default(),
                                    unit: oracle_string(IOReportChannelGetUnitLabel(it)).unwrap_or_default(),
                                    name,
                                    raw: IOReportSimpleGetIntegerValue(it, 0) as i64,
                                });
                            }
                        }
                    }
                }
                CFRelease(smp);
                Some(out)
            }
        }

        /// How many channels the Energy Model group has, and how many there are
        /// in all, by one oracle read on its own all-channel subscription.
        fn oracle_census() -> Option<(usize, usize)> {
            let (sub, chans) = oracle_subscribe()?;
            let all = oracle_channels(sub, chans, |_| true);
            oracle_unsubscribe((sub, chans));
            let all = all?;
            Some((all.iter().filter(|c| c.group.eq_ignore_ascii_case("Energy Model")).count(), all.len()))
        }

        /// The ABSOLUTE cumulative values of every channel whose name ends with
        /// `CPU Energy`, and of every one ending with `GPU Energy`, in any
        /// group, from one plain sample.
        fn oracle_read(sub: IOReportSubscriptionRef, chans: CFMutableDictionaryRef) -> Option<(Vec<i64>, Vec<i64>)> {
            let chans = oracle_channels(sub, chans, |n| n.ends_with("CPU Energy") || n.ends_with("GPU Energy"))?;
            let pick =
                |suffix: &str| chans.iter().filter(|c| c.name.ends_with(suffix)).map(|c| c.raw).collect();
            Some((pick("CPU Energy"), pick("GPU Energy")))
        }

        /// Read until `window` has elapsed, counting per rail at how many reads
        /// the absolute value changed from the read before. Stops early once
        /// one CPU rail meets [`oracle_kept_moving`]. If `window` ends with
        /// fewer than [`ORACLE_MIN_CHANGES`] reads after the first, keeps
        /// reading until it has that many, up to [`ORACLE_WINDOW_CAP`] windows,
        /// and says [`Oracle::TooFewReads`] if it still has not: never
        /// `CpuRailMoved(false)` on too few reads to tell. `read` takes one
        /// read, `elapsed` is the time since the oracle started: the hardware
        /// ([`oracle_watch`]), or a script and a scripted clock.
        fn oracle_watch_with(
            mut read: impl FnMut() -> Option<(Vec<i64>, Vec<i64>)>,
            elapsed: impl Fn() -> Duration,
            window: Duration,
        ) -> OracleRun {
            let Some((mut cpu_prev, mut gpu_prev)) = read() else {
                return OracleRun::bare(Oracle::NoIoReport);
            };
            if cpu_prev.is_empty() {
                return OracleRun::bare(Oracle::NoCpuRail);
            }
            let mut run = OracleRun {
                verdict: Oracle::CpuRailMoved(false),
                reads: 0,
                took: Duration::ZERO,
                cpu_changes: vec![0; cpu_prev.len()],
                gpu_changes: vec![0; gpu_prev.len()],
            };
            while elapsed() < window || (run.reads < ORACLE_MIN_CHANGES && elapsed() < window * ORACLE_WINDOW_CAP) {
                let Some((cpu, gpu)) = read() else {
                    continue;
                };
                run.reads += 1;
                for (n, (now, before)) in run.cpu_changes.iter_mut().zip(cpu.iter().zip(&cpu_prev)) {
                    *n += u32::from(now != before);
                }
                for (n, (now, before)) in run.gpu_changes.iter_mut().zip(gpu.iter().zip(&gpu_prev)) {
                    *n += u32::from(now != before);
                }
                (cpu_prev, gpu_prev) = (cpu, gpu);
                if run.cpu_changes.iter().any(|&n| oracle_kept_moving(n, run.reads)) {
                    run.verdict = Oracle::CpuRailMoved(true);
                    break;
                }
            }
            run.took = elapsed();
            if run.reads < ORACLE_MIN_CHANGES {
                run.verdict = Oracle::TooFewReads;
            }
            run
        }

        /// [`oracle_watch_with`] on the oracle's own subscription, timed from
        /// `started`.
        fn oracle_watch(
            sub: IOReportSubscriptionRef,
            chans: CFMutableDictionaryRef,
            started: Instant,
            window: Duration,
        ) -> OracleRun {
            oracle_watch_with(|| oracle_read(sub, chans), || started.elapsed(), window)
        }

        /// An oracle that shares nothing with the liveness probe but the raw FFI
        /// declarations: it opens its own subscription over every channel (not
        /// the probe's Energy Model group), converts CFStrings itself, reads
        /// ABSOLUTE cumulative values and compares each read with the one
        /// before it itself, matches names with `ends_with("CPU Energy")` in any
        /// group (not the implementation's group filter and die-prefix
        /// stripping), and keeps CPU busy on a HELPER thread for the whole
        /// `window`, so the window is under load even while an all-channel sample
        /// blocks this thread.
        ///
        /// `CpuRailMoved(true)` only if one rail's absolute value changed at
        /// [`ORACLE_MIN_CHANGES`] reads or more, making up at least 80% of its
        /// reads ([`oracle_kept_moving`]). A live rail changes at nearly every
        /// read. A batch-refreshed one changes at three reads at most, even
        /// when the refresh is published in steps, so a refresh that coincides
        /// with the probe cannot vouch for a Live it caused. Its own literal
        /// thresholds, not the implementation's constants, so a change to one
        /// cannot silently move the other.
        fn oracle_cpu_rail(window: Duration) -> OracleRun {
            let Some((sub, chans)) = oracle_subscribe() else {
                return OracleRun::bare(Oracle::NoIoReport);
            };
            let stop = AtomicBool::new(false);
            let run = std::thread::scope(|s| {
                s.spawn(|| {
                    let mut acc: u64 = 0;
                    while !stop.load(Ordering::Relaxed) {
                        acc = acc.wrapping_add(1);
                    }
                    std::hint::black_box(acc);
                });
                let run = oracle_watch(sub, chans, Instant::now(), window);
                stop.store(true, Ordering::Relaxed);
                run
            });
            oracle_unsubscribe((sub, chans));
            run
        }

        /// Every channel whose name ends with `CPU Energy` or `GPU Energy`,
        /// keyed by (name, ordinal among the same-named ones), in order: the
        /// oracle's own matching, applied alike to its reads and the probe's.
        fn keyed_rails(chans: impl IntoIterator<Item = (String, i64)>) -> Vec<((String, u32), i64)> {
            let mut out: Vec<((String, u32), i64)> = Vec::new();
            for (name, raw) in chans {
                if name.ends_with("CPU Energy") || name.ends_with("GPU Energy") {
                    let ordinal = out.iter().filter(|((n, _), _)| *n == name).count() as u32;
                    out.push(((name, ordinal), raw));
                }
            }
            out
        }

        /// The Energy Model group's CPU and GPU rails in one oracle read, keyed
        /// by [`keyed_rails`].
        fn oracle_group_rails(
            sub: IOReportSubscriptionRef,
            chans: CFMutableDictionaryRef,
        ) -> Option<Vec<((String, u32), i64)>> {
            let chans = oracle_channels(sub, chans, |n| n.ends_with("CPU Energy") || n.ends_with("GPU Energy"))?;
            Some(keyed_rails(
                chans.into_iter().filter(|c| c.group.eq_ignore_ascii_case("Energy Model")).map(|c| (c.name, c.raw)),
            ))
        }

        /// [`oracle_watch_with`] on a script: read `i` gives one CPU rail at
        /// `cpu(i)` and a GPU rail changing at every read, and each read moves a
        /// scripted clock on by `per_read`.
        fn oracle_on(cpu: impl Fn(usize) -> i64, per_read: Duration, window: Duration) -> OracleRun {
            let (clock, n) = (Cell::new(Duration::ZERO), Cell::new(0));
            oracle_watch_with(
                || {
                    clock.set(clock.get() + per_read);
                    let i = n.get();
                    n.set(i + 1);
                    Some((vec![cpu(i)], vec![1_000_000 * i as i64]))
                },
                || clock.get(),
                window,
            )
        }

        /// The oracle's verdict, on scripted reads 150 ms apart (an
        /// all-channel read takes 0.13-0.8 s) over its 3 s window:
        /// - (*) the two-step refresh seen on an M5 Max, changing the CPU rail
        ///   at two consecutive reads and then flat: `CpuRailMoved(false)`,
        ///   after the whole window. At two changes the oracle said `true`, and
        ///   a refresh coinciding with the probe vouched for the Live it caused.
        /// - (*) a refresh in three steps across three reads: `false`.
        /// - a rail changing at every read: `true` at the fifth read, not
        ///   before.
        /// - one changing at four reads in five: `true` at the sixth, 5 of 6.
        /// - one changing at three reads in five: `false`.
        #[test]
        fn the_oracle_says_a_rail_moved_only_if_it_kept_moving() {
            let (per_read, window) = (Duration::from_millis(150), Duration::from_millis(3000));
            let run = oracle_on(|i| two_step(i, 3, 4), per_read, window);
            assert_eq!(
                (&run.verdict, run.reads, run.cpu_changes.as_slice()),
                (&Oracle::CpuRailMoved(false), 19, [2].as_slice()),
                "a two-step refresh vouched for a moving rail: {run:?}"
            );
            let run = oracle_on(|i| 2_643_843_378 + 1_000_000 * i.min(3) as i64, per_read, window);
            assert_eq!(
                (&run.verdict, run.cpu_changes.as_slice()),
                (&Oracle::CpuRailMoved(false), [3].as_slice()),
                "a three-step refresh vouched for a moving rail: {run:?}"
            );
            let run = oracle_on(|i| i as i64, per_read, window);
            assert_eq!(
                (&run.verdict, run.reads, run.took),
                (&Oracle::CpuRailMoved(true), 5, Duration::from_millis(900)),
                "a rail changing at every read: {run:?}"
            );
            let missing = |missed: fn(usize) -> bool| move |i: usize| (1..=i).filter(|&k| !missed(k)).count() as i64;
            let run = oracle_on(missing(|k| k % 5 == 0), per_read, window);
            assert_eq!((&run.verdict, run.reads), (&Oracle::CpuRailMoved(true), 6), "four changes in five reads: {run:?}");
            let run = oracle_on(missing(|k| k % 5 == 0 || k % 5 == 1), per_read, window);
            assert_eq!(
                (&run.verdict, run.reads, run.cpu_changes.as_slice()),
                (&Oracle::CpuRailMoved(false), 19, [12].as_slice()),
                "three changes in five reads: {run:?}"
            );
        }

        /// The oracle takes enough reads for a moving rail to meet its bar.
        /// With reads 1 s apart in a 3 s window it reads on past the window
        /// until it has five after the first (at 6 s), and then a frozen rail
        /// is `CpuRailMoved(false)` and a moving one `true`. With reads 4 s
        /// apart it stops at five windows with three, and says `TooFewReads`,
        /// never `CpuRailMoved(false)`. No read is `NoIoReport`; no CPU rail is
        /// `NoCpuRail`.
        #[test]
        fn the_oracle_reads_long_enough_to_tell_or_says_it_cannot() {
            let window = Duration::from_millis(3000);
            let second = Duration::from_secs(1);
            let run = oracle_on(|_| 541_893_638, second, window);
            assert_eq!(
                (&run.verdict, run.reads, run.took),
                (&Oracle::CpuRailMoved(false), 5, Duration::from_secs(6)),
                "slow reads: {run:?}"
            );
            let run = oracle_on(|i| i as i64, second, window);
            assert_eq!((&run.verdict, run.reads), (&Oracle::CpuRailMoved(true), 5), "slow reads: {run:?}");
            let run = oracle_on(|i| i as i64, Duration::from_secs(4), window);
            assert_eq!(
                (&run.verdict, run.reads, run.took),
                (&Oracle::TooFewReads, 3, Duration::from_secs(16)),
                "reads too slow to tell: {run:?}"
            );
            assert_eq!(oracle_watch_with(|| None, || Duration::ZERO, window).verdict, Oracle::NoIoReport);
            let no_cpu = oracle_watch_with(|| Some((Vec::new(), vec![1])), || Duration::ZERO, window);
            assert_eq!(no_cpu.verdict, Oracle::NoCpuRail);
        }

        /// The property that matters: IOReport is **never** selected when its CPU
        /// rail is not live, because then it would report GPU-only energy, zero,
        /// or a whole batch refresh as the energy of CPU work. Deterministic on
        /// any host — it asserts the meter's decision against what the rail
        /// actually did, and every branch asserts; none returns early.
        ///
        /// The oracle gets three times the probe's budget, so a rail too slow for
        /// the probe but moving within the oracle's window is the only case in
        /// which declining is not proven right — and that one fails safe:
        /// estimated, never over-claimed. A batch refresh landing in both
        /// windows does not rescue a probe that called it live, even one
        /// published in steps: the oracle sees it change at three reads at most,
        /// not a moving rail. An oracle with fewer than five reads after the
        /// first is no evidence, and fails the test.
        #[test]
        fn the_ioreport_rung_is_never_selected_on_a_frozen_cpu_rail() {
            let _hw = crate::ioreport_hw_lock();
            let status = crate::ioreport_status();
            // What the cached status was made from, for every message below.
            let first = crate::ioreport_probe_evidence();
            // The IOReport rung's own gate, on this host's cached status, with
            // the rungs above it declined: `detect()` reaches it only then, and
            // on a host whose per-process counter is live it never does.
            let selected =
                matches!(crate::Meter::detect_with(&crate::Ladder::ioreport_only()).0, crate::Meter::IoReport(_));
            let window = crate::CPU_RAIL_LIVENESS_BUDGET * 3;
            let run = oracle_cpu_rail(window);
            // One line, so a CI log says which branch below was actually asserted.
            eprintln!(
                "ioreport liveness: status={status:?} oracle={:?} selected={selected} \
                 (oracle: {} reads over {:?} of a {window:?} window with a helper thread burning CPU; \
                 changes per CPU rail {:?}, per GPU rail {:?}); the first probe's record {first:?}",
                run.verdict, run.reads, run.took, run.cpu_changes, run.gpu_changes
            );
            match run.verdict {
                Oracle::TooFewReads => too_few_reads(&run, window),
                Oracle::NoIoReport => {
                    assert!(!selected, "IOReport selected (status={status:?}) but no subscription opens");
                    assert_eq!(status, crate::IoReportStatus::Unavailable);
                }
                Oracle::NoCpuRail => {
                    assert!(!selected, "IOReport selected (status={status:?}) but it has no CPU rail");
                    // Absent when the Energy Model group opened without one,
                    // Unavailable when there is no such group to open.
                    assert!(
                        matches!(status, crate::IoReportStatus::CpuRailAbsent | crate::IoReportStatus::Unavailable),
                        "the oracle found no CPU rail but the status is {status:?}"
                    );
                }
                Oracle::CpuRailMoved(false) => {
                    assert!(
                        !selected,
                        "IOReport selected (status={status:?}) although its CPU rail did not keep moving \
                         under {window:?} of CPU burn — it would report GPU-only energy, zero, or a batch \
                         refresh as the energy of CPU work; the first probe's record {first:?}"
                    );
                    assert_eq!(
                        status,
                        crate::IoReportStatus::CpuRailFrozen,
                        "the oracle did not see the CPU rail keep moving under {window:?} of CPU burn; the first \
                         probe's record {first:?}"
                    );
                }
                Oracle::CpuRailMoved(true) => {
                    // A live rail. The probe had a third of the oracle's time: if it
                    // saw the rail keep advancing the rung must be selected; if
                    // not, declining is the safe side.
                    assert!(
                        matches!(status, crate::IoReportStatus::Live | crate::IoReportStatus::CpuRailFrozen),
                        "the oracle saw a CPU rail keep moving but the status is {status:?}; the first probe's \
                         record {first:?}"
                    );
                    assert_eq!(selected, status == crate::IoReportStatus::Live, "status={status:?}");
                }
            }
        }

        /// The status the process caches leaves the record it was made from,
        /// and the two agree: where a subscription opened and an interval was
        /// observed, the record is there, its counts are consistent, and the
        /// rule applied to it holds exactly when the status is Live. So a log
        /// that prints the record shows why the status is what it is.
        #[test]
        fn the_cached_status_leaves_the_first_probes_evidence() {
            let _hw = crate::ioreport_hw_lock();
            let status = crate::ioreport_status();
            let first = crate::ioreport_probe_evidence();
            eprintln!("ioreport cached: status={status:?}, the first probe's record {first:?}");
            let Some(e) = first else {
                assert_eq!(status, crate::IoReportStatus::Unavailable, "a status with no record behind it");
                return;
            };
            if e.intervals == 0 {
                assert_eq!(status, crate::IoReportStatus::Unavailable, "no interval observed: {e:?}");
                return;
            }
            assert!(e.counted <= e.intervals && e.counted_for <= e.window, "{e:?}");
            assert!(e.advances.iter().all(|(_, _, n)| *n <= e.counted), "more advances than counted intervals: {e:?}");
            match status {
                crate::IoReportStatus::CpuRailAbsent => assert!(e.advances.is_empty(), "rails, though absent: {e:?}"),
                crate::IoReportStatus::Live | crate::IoReportStatus::CpuRailFrozen => assert_eq!(
                    e.rule_holds(),
                    status == crate::IoReportStatus::Live,
                    "the cached status is {status:?}, but the rule on its record says otherwise: {e:?}"
                ),
                crate::IoReportStatus::Unavailable => panic!("Unavailable with an interval observed: {e:?}"),
            }
        }

        /// The dangerous direction on its own: the probe never calls a rail
        /// Live that the oracle cannot see keep moving. It runs [`host_status`]
        /// itself, uncached — the tap keeps its run, and a stand-in passes every
        /// FFI read through unchanged, stamping it by the tests' own clocks —
        /// beside the cached status `detect()` is gated on, and checks on every
        /// outcome that the two agree with the oracle about what exists.
        ///
        /// It also pins how the real probe samples and burns. Nothing here is
        /// asserted on wall time or a ratio of wall times: this host is also a
        /// loaded CI runner, where other processes' IOReport samples slow every
        /// sample call.
        /// - Group-only subscription, by structure: every sample the probe took
        ///   carried exactly the Energy Model group's channels, as the oracle
        ///   counts them on its own all-channel subscription, and none from
        ///   another group. An all-channel sample carries ~11,900 (M5 Max) or
        ///   ~14,300 (M3 Ultra).
        /// - And by cost: the median THREAD CPU time of the probe's FFI sample
        ///   calls, by the tests' own clock, is under 50 ms. A group sample costs
        ///   ~8-9 ms of CPU however contended; an all-channel one ~100-125 ms.
        /// - Burning, by the tests' own clocks: between every two FFI reads the
        ///   thread burned 25 ms of its CPU, unless that tick ran into a 500 ms
        ///   wall cap, and no tick shows more CPU than wall time. The probe's
        ///   own record agrees, tick by tick. Over the whole probe, at least
        ///   half a tick of CPU per interval, and a whole tick when no tick was
        ///   capped.
        #[test]
        fn the_liveness_probe_never_reports_a_frozen_rail_as_live() {
            let _hw = crate::ioreport_hw_lock();
            // The cached probe first, so it is not burning and sampling beside
            // the probe this test watches.
            let cached = crate::ioreport_status();
            // What the cached status was made from: the run a false Live cached
            // for the process, provable from this log.
            let first = crate::ioreport_probe_evidence();
            let reads = Rc::new(RefCell::new(Vec::<(Stamp, Stamp)>::new()));
            let log = Rc::clone(&reads);
            let pass_through = seam::stand_in(move |read| {
                let entered = Stamp::closing();
                let items = read();
                log.borrow_mut().push((entered, Stamp::opening()));
                items
            });
            let tap = seam::tap();
            let (cpu_before, t) = (test_thread_cpu(), Instant::now());
            let status = host_status();
            let (took, cpu) = (t.elapsed(), test_thread_cpu().saturating_sub(cpu_before));
            let run = tap.one_run("host_status");
            drop((pass_through, tap));
            let reads = reads.take();
            assert_eq!(status, status_of(run.verdict()), "host_status said {status:?} of a run whose verdict is {:?}", run.verdict());
            let probed = run.watch.as_ref().map(RailWatch::verdict);
            let intervals = run.watch.as_ref().map_or(0, |w| w.intervals);
            let taken: Vec<&Taken> = run.samples.iter().filter_map(|s| s.taken.as_ref()).collect();
            let read_cpu: Vec<Duration> = reads.iter().map(|&(entered, left)| entered.until(left).0).collect();
            let record_cpu: Vec<Duration> = run.samples.iter().filter_map(|s| s.cpu).collect();
            let tick_cpu: Vec<Duration> = reads.windows(2).map(|w| w[0].1.until(w[1].0).0).collect();
            let tick_wall: Vec<Duration> = reads.windows(2).map(|w| w[0].1.until(w[1].0).1).collect();
            let record_gap =
                run.ticks.iter().zip(&tick_cpu).filter_map(|(recorded, &by_tests)| Some(by_tests.abs_diff(recorded.cpu?))).max();
            let census = oracle_census();
            let window = crate::CPU_RAIL_LIVENESS_BUDGET * 3;
            let oracle = oracle_cpu_rail(window);
            eprintln!(
                "ioreport probe: probed={probed:?} cached={cached:?} (the first probe's record {first:?}) \
                 took={took:?} thread_cpu={cpu:?} ({:?} per \
                 interval) intervals={intervals}; {} FFI sample calls; ticks={} median tick cpu={:?} wall={:?} by the \
                 tests' clocks (the probe's own record differs by at most {record_gap:?}); advances per CPU rail {:?}; \
                 oracle={:?} ({} reads over {:?})",
                cpu.checked_div(intervals),
                reads.len(),
                run.ticks.len(),
                median(&tick_cpu),
                median(&tick_wall),
                run.watch.as_ref().map(advances).unwrap_or_default(),
                oracle.verdict,
                oracle.reads,
                oracle.took
            );
            eprintln!(
                "ioreport structure: {} probe samples carried {:?} channels, {:?} of them outside the Energy Model \
                 group; the oracle counts (in that group, in all) = {census:?}; thread CPU per FFI sample call: median \
                 {:?} by the tests' clock (max {:?}), median {:?} by the probe's record",
                taken.len(),
                taken.iter().map(|t| t.channels).collect::<std::collections::BTreeSet<_>>(),
                taken.iter().map(|t| t.outside_group).collect::<std::collections::BTreeSet<_>>(),
                median(&read_cpu),
                read_cpu.iter().max(),
                median(&record_cpu)
            );
            if probed == Some(Some(CpuRail::Live)) || cached == crate::IoReportStatus::Live {
                assert_eq!(
                    oracle.verdict,
                    Oracle::CpuRailMoved(true),
                    "the probe said Live (probed={probed:?}, cached={cached:?}), the oracle did not see \
                     the CPU rail keep moving; the fresh probe's record {:?}, the first probe's {first:?}",
                    run.watch.as_ref().map(|w| w.evidence())
                );
            }
            match oracle.verdict {
                Oracle::TooFewReads => too_few_reads(&oracle, window),
                Oracle::NoIoReport => {
                    assert!(matches!(probed, None | Some(None)), "the oracle could not open IOReport, the probe did");
                    assert_eq!(cached, crate::IoReportStatus::Unavailable);
                }
                Oracle::NoCpuRail => assert!(
                    matches!(
                        (probed, cached),
                        (None, crate::IoReportStatus::Unavailable)
                            | (Some(Some(CpuRail::Absent)), crate::IoReportStatus::CpuRailAbsent)
                    ),
                    "the oracle found no CPU rail, the probe reported {probed:?} (cached={cached:?})"
                ),
                Oracle::CpuRailMoved(false) => assert!(
                    probed == Some(Some(CpuRail::Frozen)) && cached == crate::IoReportStatus::CpuRailFrozen,
                    "the CPU rail did not keep moving under the oracle's burn, so the probe must say \
                     Frozen: probed={probed:?}, cached={cached:?}; the first probe's record {first:?}"
                ),
                Oracle::CpuRailMoved(true) => assert!(
                    matches!(probed, Some(Some(CpuRail::Live | CpuRail::Frozen))),
                    "the oracle saw a CPU rail keep moving but the probe reported {probed:?}"
                ),
            }
            if run.watch.is_some() {
                let (group, all) = census.expect("the oracle could not read the channels to count the Energy Model group");
                assert!(!taken.is_empty(), "the probe took no usable sample");
                for (i, t) in taken.iter().enumerate() {
                    assert_eq!(
                        t.outside_group, 0,
                        "probe sample {i} carried {} of its {} channels from outside the Energy Model group: the \
                         probe is not subscribed to that group alone",
                        t.outside_group, t.channels
                    );
                    assert_eq!(
                        t.channels, group,
                        "probe sample {i} carried {} channels; the Energy Model group has {group} (all groups: {all})",
                        t.channels
                    );
                }
                assert!(group < all, "the Energy Model group ({group}) is not smaller than all channels ({all})");
                let m = median(&read_cpu).expect("the probe made no FFI sample call");
                assert!(
                    m < GROUP_SAMPLE_CPU_CEILING,
                    "the median of the probe's {} FFI sample calls took {m:?} of this thread's CPU, by the tests' \
                     own clock, not under {GROUP_SAMPLE_CPU_CEILING:?}: a group sample costs ~8-9 ms, an all-channel \
                     one ~100-125 ms",
                    reads.len()
                );
                assert_eq!(
                    reads.len(),
                    run.samples.len(),
                    "the probe recorded {} sample calls, the FFI was read {} times",
                    run.samples.len(),
                    reads.len()
                );
                assert_eq!(
                    run.ticks.len() + 1,
                    run.samples.len(),
                    "{} ticks between {} sample calls: the probe must tick once before every re-sample",
                    run.ticks.len(),
                    run.samples.len()
                );
                let ticks = assert_ticks_burned(&reads, "the real probe");
                for (k, (recorded, &(cpu, _))) in run.ticks.iter().zip(&ticks).enumerate() {
                    let rec = recorded.cpu.expect("the probe could not read its own thread clock");
                    assert!(
                        rec <= recorded.wall + CLOCK_SLACK,
                        "tick {k}: the probe's record shows {rec:?} of CPU in {:?} of wall time",
                        recorded.wall
                    );
                    assert!(
                        rec <= cpu + CLOCK_SLACK && cpu.saturating_sub(rec) <= RECORD_SLACK,
                        "tick {k}: the probe recorded {rec:?} of CPU; the tests' clock saw {cpu:?} between the two \
                         reads around it"
                    );
                }
            }
            if intervals > 0 {
                let per_interval = cpu / intervals;
                assert!(
                    per_interval >= TICK_CPU_FLOOR / 2,
                    "the probing thread used {cpu:?} of CPU over {intervals} intervals, {per_interval:?} each, under \
                     half of each {TICK_CPU_FLOOR:?} tick: the probe must burn CPU between samples, not wait"
                );
                if tick_wall.iter().all(|&wall| wall < TICK_WALL_CAP) {
                    assert!(
                        per_interval >= TICK_CPU_FLOOR,
                        "the probing thread used {per_interval:?} of CPU per interval, under a whole \
                         {TICK_CPU_FLOOR:?} tick, though no tick ran into the {TICK_WALL_CAP:?} wall cap"
                    );
                }
            }
        }

        /// What the real probe hands the rule is what the hardware held at that
        /// moment. [`host_status`] runs on this thread (the tap keeps its run;
        /// a stand-in passes every FFI read through unchanged and records when
        /// it ran, by the tests' clock). On a helper thread an oracle (its own
        /// all-channel subscription, its own strings, absolute values) reads
        /// the Energy Model group's CPU and GPU rails back to back, from before
        /// the probe's first read until after its last. The rails only count
        /// up, so for each sample the probe handed the rule, an oracle read that
        /// ENDED before that FFI read began is a floor under every rail, and one
        /// that BEGAN after it ended is a ceiling:
        /// - a rail the oracle saw hold across a read must have been handed
        ///   exactly the value the oracle read (a frozen CPU rail is constant);
        /// - a rail that moved must have been handed a value between the two;
        /// - the probe's CPU rails are exactly the oracle's, and so are its GPU
        ///   rails.
        ///
        /// Freshness is not left to chance. The stand-in holds the probe's
        /// second FFI read until the oracle has made a read that began after the
        /// probe's first read ended and saw a rail differ from it, or, failing
        /// that, until the oracle has made two such reads AND 3 s have passed.
        /// That is counted in the oracle's reads, not only in time: on a loaded
        /// host one all-channel read can take seconds. A witness counts only if
        /// it was seen before the second read was released, so it is a floor
        /// under every later probe read: a sampler that repeats a stale sample,
        /// per subscription or process-wide, hands the rule a value below it
        /// and fails. The M5 Max's GPU rail changes every ~28 ms, so there a
        /// witness is always found; on the M3 Ultra the GPU may hold for
        /// seconds, and the printed line says whether a witness was found and
        /// staleness asserted.
        ///
        /// A sampler that sums the CPU rails is caught where there are two (the
        /// M3 Ultra's dies). On one rail (the M5 Max) the sum of the CPU rails
        /// IS the rail; the scripted two-die tests catch a sum there.
        #[test]
        fn the_real_probe_hands_the_rule_what_the_oracle_reads() {
            let _hw = crate::ioreport_hw_lock();
            /// Rails keyed by (name, ordinal), with their raw values.
            type Keyed = Vec<((String, u32), i64)>;
            struct Read {
                start: Instant,
                end: Instant,
                rails: Keyed,
            }
            /// From the probe's thread: when its first FFI read ended and the
            /// rails it read, then that its second read was released. From the
            /// oracle's: how many reads it began after the first read ended,
            /// before that release; whether one of them saw a rail differ from
            /// the first read; and that it has stopped reading.
            #[derive(Default)]
            struct Witness {
                first: Option<(Instant, Keyed)>,
                looked: u32,
                seen: bool,
                released: bool,
                oracle_done: bool,
            }
            let witness = std::sync::Arc::new((Mutex::new(Witness::default()), std::sync::Condvar::new()));
            let windows = Rc::new(RefCell::new(Vec::<(Instant, Instant)>::new()));
            let hold = {
                let (witness, log, n) = (std::sync::Arc::clone(&witness), Rc::clone(&windows), Cell::new(0));
                seam::stand_in(move |read| {
                    let i = n.get();
                    n.set(i + 1);
                    if i == 1 {
                        let (lock, woken) = &*witness;
                        let from = Instant::now();
                        let mut w = lock.lock().unwrap();
                        while !w.seen
                            && !(w.looked >= 2 && from.elapsed() >= WITNESS_WAIT)
                            && !w.oracle_done
                            && from.elapsed() < ORACLE_GIVE_UP
                        {
                            w = woken.wait_timeout(w, Duration::from_millis(50)).unwrap().0;
                        }
                        // From here on the oracle's reads are no floor under
                        // this read, so none of them may count as its witness.
                        w.released = true;
                    }
                    let start = Instant::now();
                    let items = read();
                    let end = Instant::now();
                    log.borrow_mut().push((start, end));
                    if let (0, Some(items)) = (i, &items) {
                        let rails = keyed_rails(
                            items
                                .iter()
                                .filter(|it| it.group.as_deref().is_some_and(|g| g.eq_ignore_ascii_case("Energy Model")))
                                .filter_map(|it| Some((it.name.clone()?, it.raw))),
                        );
                        let (lock, woken) = &*witness;
                        lock.lock().unwrap().first = Some((end, rails));
                        woken.notify_all();
                    }
                    items
                })
            };
            let reads = Mutex::new(Vec::<Read>::new());
            let probe_ended = Mutex::new(None::<Instant>);
            let (first_read, gave_up) = (AtomicBool::new(false), AtomicBool::new(false));
            let (t0, status, t1, runs) = std::thread::scope(|s| {
                let oracle = s.spawn(|| {
                    let Some(o) = oracle_subscribe() else {
                        gave_up.store(true, Ordering::SeqCst);
                        let (lock, woken) = &*witness;
                        lock.lock().unwrap().oracle_done = true;
                        woken.notify_all();
                        return;
                    };
                    let since = Instant::now();
                    loop {
                        let start = Instant::now();
                        let rails = oracle_group_rails(o.0, o.1);
                        let end = Instant::now();
                        let ended = *probe_ended.lock().unwrap();
                        if let Some(rails) = rails {
                            let (lock, woken) = &*witness;
                            let mut w = lock.lock().unwrap();
                            let after_first = w.first.as_ref().is_some_and(|(first_end, _)| start >= *first_end);
                            if after_first && !w.released {
                                w.looked += 1;
                                if w.first.as_ref().is_some_and(|(_, first)| rails != *first) {
                                    w.seen = true;
                                }
                                woken.notify_all();
                            }
                            drop(w);
                            reads.lock().unwrap().push(Read { start, end, rails });
                            first_read.store(true, Ordering::SeqCst);
                            if ended.is_some_and(|t1| start >= t1) {
                                break;
                            }
                        }
                        if since.elapsed() > ORACLE_GIVE_UP {
                            gave_up.store(true, Ordering::SeqCst);
                            break;
                        }
                    }
                    oracle_unsubscribe(o);
                    let (lock, woken) = &*witness;
                    lock.lock().unwrap().oracle_done = true;
                    woken.notify_all();
                });
                // One whole oracle read before the probe starts: the floor under
                // its first sample.
                let waiting = Instant::now();
                while !first_read.load(Ordering::SeqCst)
                    && !gave_up.load(Ordering::SeqCst)
                    && waiting.elapsed() < ORACLE_GIVE_UP
                {
                    std::thread::sleep(Duration::from_millis(1));
                }
                let tap = seam::tap();
                let t0 = Instant::now();
                let status = host_status();
                let t1 = Instant::now();
                *probe_ended.lock().unwrap() = Some(t1);
                oracle.join().expect("the oracle thread panicked");
                (t0, status, t1, tap.runs())
            });
            drop(hold);
            let reads = reads.into_inner().expect("the oracle's reads");
            let windows = windows.take();
            let (witnessed, looked) = {
                let w = witness.0.lock().unwrap();
                (w.seen, w.looked)
            };
            assert_eq!(runs.len(), 1, "host_status made {} probe runs, not one", runs.len());
            let run = &runs[0];
            assert_eq!(status, status_of(run.verdict()), "host_status said {status:?} of a run whose verdict is {:?}", run.verdict());
            if run.watch.is_none() {
                let cpu_rails_seen = reads.iter().flat_map(|r| &r.rails).filter(|((n, _), _)| n.ends_with("CPU Energy")).count();
                eprintln!(
                    "ioreport freshness: no Energy Model subscription opens; status={status:?}; the oracle saw \
                     {cpu_rails_seen} CPU rail readings in that group"
                );
                assert_eq!(status, crate::IoReportStatus::Unavailable);
                assert!(windows.is_empty(), "the probe read {} samples with no subscription", windows.len());
                assert_eq!(cpu_rails_seen, 0, "the oracle reads Energy Model CPU rails, but the probe could not subscribe to that group");
                return;
            }
            assert!(!gave_up.load(Ordering::SeqCst), "the oracle could not keep reading beside the probe ({} reads)", reads.len());
            assert_eq!(
                windows.len(),
                run.samples.len(),
                "the probe recorded {} sample calls, the FFI was read {} times",
                run.samples.len(),
                windows.len()
            );
            assert!(
                run.started >= t0 && run.samples.first().is_none_or(|s| run.started <= s.at),
                "the probe's run is recorded as starting {:?} into host_status's call, after its first sample call",
                run.started.saturating_duration_since(t0)
            );
            for (k, (s, &(start, end))) in run.samples.iter().zip(&windows).enumerate() {
                assert!(
                    t0 <= s.at && s.at <= start && end <= s.at + s.wall && s.at + s.wall <= t1,
                    "probe sample call {k} is recorded at {:?} for {:?} into host_status's call, but its FFI read ran \
                     {:?}..{:?}: the probe's own clock does not contain its read",
                    s.at.saturating_duration_since(t0),
                    s.wall,
                    start.saturating_duration_since(t0),
                    end.saturating_duration_since(t0)
                );
            }
            let taken: Vec<(usize, &Taken)> =
                run.samples.iter().enumerate().filter_map(|(k, s)| s.taken.as_ref().map(|t| (k, t))).collect();
            assert!(taken.len() >= 2, "the probe handed the rule {} samples", taken.len());
            let (first_read_at, last_read_end) = (windows[taken[0].0].0, windows[taken[taken.len() - 1].0].1);
            assert!(reads.first().is_some_and(|r| r.end <= first_read_at), "no oracle read ended before the probe's first read");
            assert!(reads.last().is_some_and(|r| r.start >= last_read_end), "no oracle read began after the probe's last read");
            let keys = |rails: &[((String, u32), i64)], suffix: &str| -> Vec<(String, u32)> {
                rails.iter().filter(|((n, _), _)| n.ends_with(suffix)).map(|(k, _)| k.clone()).collect()
            };
            let (oracle_cpu, oracle_gpu) = (keys(&reads[0].rails, "CPU Energy"), keys(&reads[0].rails, "GPU Energy"));
            for r in &reads {
                assert_eq!(keys(&r.rails, "CPU Energy"), oracle_cpu, "the oracle's CPU rails changed between its reads");
                assert_eq!(keys(&r.rails, "GPU Energy"), oracle_gpu, "the oracle's GPU rails changed between its reads");
            }
            let key_of = |k: &RailKey| (k.name.clone(), k.ordinal);
            let at = |r: &Read, key: &(String, u32)| -> i64 {
                r.rails.iter().find(|(k, _)| k == key).map(|(_, v)| *v).expect("a rail missing from an oracle read")
            };
            let handed = |t: &Taken, key: &(String, u32)| -> i64 {
                t.cpu_rails
                    .iter()
                    .chain(&t.gpu_rails)
                    .find(|(k, _)| key_of(k) == *key)
                    .map(|(_, v)| *v)
                    .expect("a rail missing from a probe sample")
            };
            let (mut held, mut moved) = (0, 0);
            for &(k, t) in &taken {
                let (start, end) = windows[k];
                assert_eq!(
                    t.cpu_rails.iter().map(|(key, _)| key_of(key)).collect::<Vec<_>>(),
                    oracle_cpu,
                    "probe sample {k}: the probe's CPU rails are not the ones the oracle reads"
                );
                assert_eq!(
                    t.gpu_rails.iter().map(|(key, _)| key_of(key)).collect::<Vec<_>>(),
                    oracle_gpu,
                    "probe sample {k}: the probe's GPU rails are not the ones the oracle reads"
                );
                for (key, p) in t.cpu_rails.iter().chain(&t.gpu_rails) {
                    let key = key_of(key);
                    let rail = format!("{}#{}", key.0, key.1);
                    let floor = reads.iter().filter(|r| r.end <= start).map(|r| at(r, &key)).max().expect("a read before");
                    let ceiling = reads.iter().filter(|r| r.start >= end).map(|r| at(r, &key)).min().expect("a read after");
                    if floor == ceiling {
                        held += 1;
                        assert_eq!(
                            *p, floor,
                            "{rail} held at {floor} in the oracle's reads either side of probe read {k}, but the probe \
                             handed the rule {p}"
                        );
                    } else {
                        moved += 1;
                        assert!(
                            (floor..=ceiling).contains(p),
                            "{rail} moved {floor} -> {ceiling} in the oracle's reads either side of probe read {k}, but \
                             the probe handed the rule {p}, outside them: a stale or made-up sample"
                        );
                    }
                }
            }
            // The witness: an oracle read wholly between the probe's first read
            // and its second, which saw a rail differ from the first read.
            let freshness = if witnessed {
                let (first_end, second_start) = (windows[0].1, windows.get(1).map_or(t1, |w| w.0));
                let first = taken.iter().find(|&&(k, _)| k == 0).map(|&(_, t)| t).expect("the probe's first read gave no sample");
                let w = reads
                    .iter()
                    .find(|r| {
                        r.start >= first_end
                            && r.end <= second_start
                            && r.rails.iter().any(|(key, v)| handed(first, key) != *v)
                    })
                    .expect("the oracle said it saw a rail move before the probe's second read, but no such read is recorded");
                let later = taken.iter().find(|&&(k, _)| k >= 1).map(|&(k, t)| (k, t)).expect("no usable probe read after the first");
                let mut asserted = Vec::new();
                for (key, o) in w.rails.iter().filter(|(key, v)| handed(first, key) != *v) {
                    let (p0, p) = (handed(first, key), handed(later.1, key));
                    let rail = format!("{}#{}", key.0, key.1);
                    assert!(
                        p >= *o && p != p0,
                        "{rail}: the probe handed the rule {p0} at its first read, the oracle then read {o}, and the \
                         probe handed the rule {p} at read {}: a stale sample",
                        later.0
                    );
                    asserted.push(format!("{rail}: probe {p0}, then oracle {o}, then probe {p}"));
                }
                format!(
                    "witness found {:?} after the probe's first read, at the oracle's read {looked} since it, staleness \
                     asserted: {asserted:?}",
                    w.start.saturating_duration_since(first_end)
                )
            } else {
                format!(
                    "no rail moved in the oracle's {looked} reads between the probe's first and second reads (held at \
                     least {WITNESS_WAIT:?}), so staleness was not asserted"
                )
            };
            eprintln!(
                "ioreport freshness: status={status:?}; {} probe samples handed to the rule, bracketed by {} oracle reads; \
                 {held} rail readings the oracle saw hold were handed equal, {moved} that moved were handed within the \
                 oracle's reads; {freshness}",
                taken.len(),
                reads.len()
            );
        }

        /// The probe's own FFI sampler reads each CPU rail's true absolute
        /// value. Around each of two probe samples, the oracle reads the same
        /// rails of the Energy Model group absolutely on its own all-channel
        /// subscription, once before and once after. A rail the oracle saw
        /// hold across those two reads (a frozen rail is constant) must read
        /// EQUAL in the probe's sample; one that moved must read within them.
        /// So a sampler that returns a constant, gives a rail a sum of rails, or
        /// reads the wrong channel fails, on a frozen host as on a live one.
        /// `GPU Energy` is held to the same rule; where the GPU draws it moves,
        /// so the probe's sample must also be fresh. And the rails the
        /// implementation calls CPU rails are exactly the oracle's.
        #[test]
        fn the_probe_sampler_reads_each_cpu_rail_as_the_oracle_does() {
            let _hw = crate::ioreport_hw_lock();
            let Some(sub) = EnergyModelSubscription::open() else {
                // No Energy Model subscription, so no sampler to check: the
                // oracle must not find a CPU rail in that group either.
                let found = oracle_subscribe().and_then(|o| {
                    let chans = oracle_channels(o.0, o.1, |n| n.ends_with("CPU Energy"));
                    oracle_unsubscribe(o);
                    chans
                });
                eprintln!("ioreport sampler: no Energy Model subscription opens; the oracle read {found:?}");
                let in_group =
                    found.unwrap_or_default().iter().filter(|c| c.group.eq_ignore_ascii_case("Energy Model")).count();
                assert_eq!(in_group, 0, "the oracle reads CPU rails in the Energy Model group, but the probe cannot subscribe to it");
                return;
            };
            let oracle =
                oracle_subscribe().expect("the probe's Energy Model subscription opened, the oracle's all-channel one did not");
            let read = |when: &str| -> Vec<((String, u32), i64)> {
                oracle_group_rails(oracle.0, oracle.1).unwrap_or_else(|| panic!("the oracle's read {when} the probe's sample failed"))
            };
            let names = |v: &[((String, u32), i64)]| v.iter().map(|(k, _)| k.clone()).collect::<Vec<_>>();
            let mut seen = Vec::new();
            for round in 0..2 {
                let before = read("before");
                let sample = sub.sample().expect("the probe's sampler gave no sample").values;
                let after = read("after");
                let probe = keyed_rails(sample.iter().cloned());
                assert_eq!(names(&probe), names(&before), "the probe's sampler and the oracle read different rails");
                assert_eq!(names(&after), names(&before), "the oracle's rails changed between two of its reads");
                let oracle_cpu: Vec<(String, u32)> =
                    names(&before).into_iter().filter(|(n, _)| n.ends_with("CPU Energy")).collect();
                let implementation: Vec<(String, u32)> =
                    cpu_rails(&sample).into_iter().map(|(k, _)| (k.name, k.ordinal)).collect();
                assert_eq!(implementation, oracle_cpu, "the implementation's CPU rails are not the ones the oracle reads");
                for (((key, b), (_, p)), (_, a)) in before.iter().zip(&probe).zip(&after) {
                    let (b, p, a) = (*b, *p, *a);
                    let rail = format!("{}#{}", key.0, key.1);
                    if b == a {
                        assert_eq!(
                            p, b,
                            "{rail} held at {b} across the oracle's reads either side of the probe's sample, but the \
                             probe's sampler read {p}"
                        );
                    } else {
                        assert!(
                            (b.min(a)..=b.max(a)).contains(&p),
                            "{rail} moved {b} -> {a} across the oracle's reads either side of the probe's sample, but \
                             the probe's sampler read {p}, outside them"
                        );
                    }
                    seen.push(format!("{rail} r{round}: {b} | {p} | {a} ({})", if b == a { "held: equal" } else { "moved: within" }));
                }
            }
            oracle_unsubscribe(oracle);
            eprintln!("ioreport sampler: oracle before | probe | oracle after, per rail: {seen:?}");
        }

        /// When the rung IS selected, its own CPU rail is live on a fresh probe
        /// and a CPU burn advances the CPU rail itself, so `measure` gives the
        /// span as a reading: `HwShunt` with the measured figure, the grade of
        /// RAPL and NVML, not the time×power fallback it degrades to when the
        /// CPU rail holds.
        ///
        /// When it is not, the status says why (never `Live`), and the meter
        /// the ladder fell to still meters real work honestly: 100 ms of CPU
        /// work is the time×power figure, at least 100 ms at the documented
        /// default power, tagged `Estimator` with no measurement — the power
        /// is assumed, not calibrated on this host. Never a floored or zero
        /// figure for work that ran.
        #[test]
        fn a_selected_ioreport_meter_meters_cpu_work() {
            let _hw = crate::ioreport_hw_lock();
            // The rungs above IOReport declined, as `detect()` reaches it.
            let meter = crate::Meter::detect_with(&crate::Ladder::ioreport_only()).0;
            if let crate::Meter::IoReport(io) = &meter {
                assert_eq!(
                    crate::ioreport_status(),
                    crate::IoReportStatus::Live,
                    "detect() selected IOReport although the liveness status is not Live"
                );
                // A fresh probe, at a later moment than the cached one, and on the
                // real clock: only while the host left it near its cadence.
                let _ = crate::liveness::take_held();
                let (fresh, record) = host_probe();
                if crate::liveness::take_held() == 0 {
                    assert_eq!(
                        fresh,
                        crate::IoReportStatus::Live,
                        "IOReport selected but a fresh probe says {fresh:?}: its record {record:?}, the first probe's {:?}",
                        crate::ioreport_probe_evidence()
                    );
                }
                let _ = io.read(); // the first read only sets the baseline sample
                let before = io.read().expect("baseline read");
                spin_cpu(Duration::from_millis(200));
                let after = io.read().expect("work read");
                assert!(
                    after.cpu_uj > before.cpu_uj,
                    "a live CPU rail metered 200 ms of CPU work as zero: before={before:?} after={after:?}"
                );
                let (_, e) = meter.measure(|| spin_cpu(Duration::from_millis(200)));
                eprintln!(
                    "selected meter: 200 ms of CPU work -> {} µJ, provenance={:?}, measured_uj={:?}",
                    e.uj(),
                    e.provenance,
                    e.measured_uj
                );
                e.check_provenance().expect("the selected meter's figure must be internally consistent");
                assert_eq!(
                    e.provenance,
                    jcp_schema::Provenance::HwShunt,
                    "a span of a live IOReport CPU rail was not graded as a hardware reading"
                );
                assert!(e.measured_uj.is_some_and(|uj| uj > 0), "a live reading measured {:?}", e.measured_uj);
                assert!(e.is_whole(), "the SoC total was reported as covering part of the work");
            } else {
                let status = crate::ioreport_status();
                assert_ne!(status, crate::IoReportStatus::Live, "status Live but detect() did not select the IOReport rung");
                let work = Duration::from_millis(100);
                let (_, e) = meter.measure(|| spin_cpu(work));
                let floor = crate::time_power_uj(work.as_nanos(), crate::DEFAULT_ACTIVE_MILLIWATTS);
                eprintln!(
                    "declined meter: status={status:?} meter={meter:?} {work:?} of CPU work -> {} µJ, \
                     provenance={:?}, measured_uj={:?}",
                    e.uj(),
                    e.provenance,
                    e.measured_uj
                );
                e.check_provenance().expect("the declined meter's figure must be internally consistent");
                assert_eq!(e.provenance, jcp_schema::Provenance::Estimator, "the declined meter's figure is not an estimate");
                assert!(e.measured_uj.is_none(), "the declined meter claimed a measurement: {:?}", e.measured_uj);
                assert!(e.uj() > 0, "the declined meter metered {work:?} of CPU work as 0 µJ");
                assert!(
                    e.uj() >= floor,
                    "the declined meter metered {work:?} of CPU work as {} µJ, under the time×power model's \
                     {floor} µJ at {} mW",
                    e.uj(),
                    crate::DEFAULT_ACTIVE_MILLIWATTS
                );
            }
        }

        /// The counter sums what its rails did, value for value. The symptom
        /// seen on 2026-09-19, the counter open and reading 0 µJ across a whole
        /// run, is a reader that returns a constant; a check on its delta alone
        /// passes whenever nothing happened to move.
        ///
        /// So the oracle reads, absolutely on its own all-channel subscription,
        /// every rail the counter sums (the Energy Model group's channels that
        /// `counts_once` admits; that choice is pinned on its own by
        /// `counts_once_drops_subrails`), just before and just after each of the
        /// counter's two reads. The rails only count up, so, rail by rail in
        /// raw units and then converted as the counter converts, what the
        /// counter counted between its two reads is at least the rise between
        /// the two oracle reads inside that window, and at most the rise
        /// between the two outside it. When nothing moved, both are 0 and the
        /// counter must have counted exactly 0.
        ///
        /// The same bounds hold, from the same reads, for the CPU share the
        /// counter reports beside its total — the figure `measure` decides a
        /// reading on — over the CPU energy rails alone, picked by the oracle's
        /// own `ends_with("CPU Energy")`.
        #[test]
        fn the_counter_advances_when_a_rail_it_sums_advanced() {
            let _hw = crate::ioreport_hw_lock();
            let Some(io) = IoReport::open() else {
                // Not a pass by default: the oracle's all-channel subscription
                // must fail to open too, or the counter's opener is broken.
                let oracle_opens = oracle_subscribe().map(oracle_unsubscribe).is_some();
                let selected =
                    matches!(crate::Meter::detect_with(&crate::Ladder::ioreport_only()).0, crate::Meter::IoReport(_));
                eprintln!("ioreport counter: no counter opens on this host; oracle opens={oracle_opens} selected={selected}");
                assert!(!oracle_opens, "the counter does not open, but the oracle's all-channel subscription does");
                assert!(!selected, "detect() selected an IOReport counter that does not open");
                return;
            };
            let oracle = oracle_subscribe().expect("the counter's all-channel subscription opened, the oracle's did not");
            // Every rail the counter sums, keyed by (name, ordinal), with its
            // unit and its absolute raw value.
            let summed = |when: &str| -> Vec<((String, u32), String, i64)> {
                let chans = oracle_channels(oracle.0, oracle.1, counts_once)
                    .unwrap_or_else(|| panic!("the oracle's read {when} failed"));
                let mut out: Vec<((String, u32), String, i64)> = Vec::new();
                for c in chans.into_iter().filter(|c| c.group.eq_ignore_ascii_case("Energy Model")) {
                    let ordinal = out.iter().filter(|((n, _), _, _)| *n == c.name).count() as u32;
                    out.push(((c.name, ordinal), c.unit, c.raw));
                }
                out
            };
            let _ = io.read().expect("the counter's baseline read");
            let before_first = summed("before the counter's first read");
            let first = io.read().expect("the counter's first read");
            let after_first = summed("after the counter's first read");
            spin_cpu(Duration::from_millis(200));
            let before_second = summed("before the counter's second read");
            let second = io.read().expect("the counter's second read");
            let after_second = summed("after the counter's second read");
            oracle_unsubscribe(oracle);
            // The rise, from one oracle read to another, of the summed rails
            // whose names `pick` accepts, in µJ as the counter converts each
            // rail, and how many of them rose.
            let rise = |from: &[((String, u32), String, i64)],
                        to: &[((String, u32), String, i64)],
                        pick: fn(&str) -> bool|
             -> (u64, usize) {
                let keys = |v: &[((String, u32), String, i64)]| v.iter().map(|(k, _, _)| k.clone()).collect::<Vec<_>>();
                assert_eq!(keys(from), keys(to), "the summed rails changed between two oracle reads");
                let mut uj: u64 = 0;
                let mut rose = 0;
                for (((name, _), unit, a), (_, _, b)) in from.iter().zip(to) {
                    if !pick(name) {
                        continue;
                    }
                    let raw = b.saturating_sub(*a).max(0);
                    rose += usize::from(raw > 0);
                    uj = uj.saturating_add(energy_to_uj(raw as c_long, unit));
                }
                (uj, rose)
            };
            let every: fn(&str) -> bool = |_| true;
            let cpu: fn(&str) -> bool = |n| n.ends_with("CPU Energy");
            let (inside, rose_inside) = rise(&after_first, &before_second, every);
            let (around, rose_around) = rise(&before_first, &after_second, every);
            let (cpu_inside, _) = rise(&after_first, &before_second, cpu);
            let (cpu_around, cpu_rose_around) = rise(&before_first, &after_second, cpu);
            let cpu_rails = after_first.iter().filter(|((n, _), _, _)| cpu(n)).count();
            eprintln!(
                "ioreport counter: it sums {} Energy Model rails; between its two reads it counted {} µJ; by the \
                 oracle's absolute reads those rails rose {inside} µJ inside that window ({rose_inside} rails rose) and \
                 {around} µJ around it ({rose_around} rose). Its CPU share, {cpu_rails} CPU rails: it counted {} µJ; \
                 they rose {cpu_inside} µJ inside and {cpu_around} µJ around it ({cpu_rose_around} rose)",
                after_first.len(),
                second.total_uj.saturating_sub(first.total_uj),
                second.cpu_uj.saturating_sub(first.cpu_uj)
            );
            assert!(second.total_uj >= first.total_uj, "the counter ran backwards: {first:?} -> {second:?}");
            assert!(second.cpu_uj >= first.cpu_uj, "the counter's CPU share ran backwards: {first:?} -> {second:?}");
            let counted = second.total_uj - first.total_uj;
            assert!(
                inside <= counted && counted <= around,
                "the counter counted {counted} µJ between its two reads, but the rails it sums rose {inside} µJ inside \
                 that window and {around} µJ around it, by the oracle's absolute reads: it did not sum what its rails did"
            );
            let cpu_counted = second.cpu_uj - first.cpu_uj;
            assert!(
                cpu_inside <= cpu_counted && cpu_counted <= cpu_around,
                "the counter's CPU share rose {cpu_counted} µJ between its two reads, but the CPU energy rails rose \
                 {cpu_inside} µJ inside that window and {cpu_around} µJ around it, by the oracle's absolute reads"
            );
        }
    }
}

/// Why the IOReport rung was or was not selected on this host.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum IoReportStatus {
    /// No subscription to the Energy Model group could be opened (IOReport does
    /// not open — not macOS, not Apple Silicon, or Rosetta — or it has no such
    /// group), or the subscription gave fewer than two usable samples in five
    /// budgets.
    Unavailable,
    /// The Energy Model group was sampled, but it has no `CPU Energy` rail — an
    /// unfamiliar channel naming. Never selected.
    CpuRailAbsent,
    /// A CPU energy rail exists but not every one kept advancing while CPU was
    /// burned: some CPU rail did not advance in at least five separate sample
    /// intervals, making up at least 80% of those that count, over at least
    /// 300 ms (an interval runs from when one sample is in hand to when the
    /// next is, and only one no longer than three of the probe's ticks, 75 ms
    /// at its 25 ms tick, counts: a longer one counts as nothing, neither among
    /// the intervals, nor as an advance, nor towards the 300 ms, which is the
    /// summed length of the intervals that count). It held, or stepped a few
    /// times together — a batch refresh, not a live reading. The platform is
    /// not exposing live CPU energy to this process, so selecting the rung
    /// would grade a whole refresh, landing in one span, as a hardware reading
    /// of that span's CPU work. On a two-die part one die's rail may be live
    /// and the other's not; that is Frozen too, since the counter sums both
    /// dies and would miss the frozen one's energy. A probe the host held, so
    /// that too few of its intervals counted, reads Frozen too: it saw no
    /// evidence of a live rail, so the rung is not selected. Observed on macOS
    /// 27.0.1 on both an M5 Max and an M3 Ultra, where every CPU rail held.
    CpuRailFrozen,
    /// Every CPU energy rail kept advancing under load (`CPU Energy`, or each
    /// die's on a multi-die part): each in at least five separate sample
    /// intervals, making up at least 80% of those that count, over at least
    /// 300 ms (an interval runs from when one sample is in hand to when the
    /// next is, and only one no longer than three of the probe's ticks, 75 ms
    /// at its 25 ms tick, counts: a longer one counts as nothing, neither among
    /// the intervals, nor as an advance, nor towards the 300 ms, which is the
    /// summed length of the intervals that count). The rung is selected.
    Live,
}

/// How long the liveness probe burns CPU, on the calling thread, before
/// concluding the CPU rail is not live. The probe samples its own subscription
/// to the Energy Model group, ~5–12 ms a sample, after every 25 ms of the
/// calling thread's own CPU time (a tick that cannot get that in 500 ms of wall
/// time stops there) — about 30 intervals in the budget on an idle host, fewer
/// under load, each a sample and the one before it. Every CPU rail must keep
/// advancing (each die's, on a multi-die part): each in at least five
/// intervals, making up at least 80% of those observed, over at least 300 ms
/// from the first sample. A live Energy Model
/// rail changes many times a second (the M5 Max GPU rail every ~28 ms), so it
/// is called live about 300 ms in, and one second is generous. A sample that
/// fails is skipped. If samples are slow or failing enough that fewer than five
/// intervals fit, the probe keeps sampling past the budget until it has five,
/// up to five budgets. A slower live rail fails safe — it is estimated, never
/// over-claimed. Paid once per process; see [`ioreport_status`].
#[cfg(target_os = "macos")]
pub const CPU_RAIL_LIVENESS_BUDGET: std::time::Duration = std::time::Duration::from_millis(1000);

/// This host's IOReport status, probed once per process and cached.
///
/// [`Meter::detect`] selects the IOReport rung only when this is
/// [`IoReportStatus::Live`]. On macOS the first call runs the probe on the
/// calling thread: about one `CPU_RAIL_LIVENESS_BUDGET` of wall time burning CPU
/// when the rail is not live (at most five, if IOReport samples are very slow or keep
/// failing), less when it is. Exposed so a caller, or a receipt, can say *why* an Apple
/// Silicon host is being metered by the default-power estimate instead.
pub fn ioreport_status() -> IoReportStatus {
    #[cfg(target_os = "macos")]
    {
        ioreport_probe().0
    }
    #[cfg(not(target_os = "macos"))]
    {
        IoReportStatus::Unavailable
    }
}

/// The process's one IOReport liveness probe, run on first use: its status
/// and its evidence ([`ioreport::host_probe`]).
#[cfg(target_os = "macos")]
fn ioreport_probe() -> &'static (IoReportStatus, Option<liveness::ProbeEvidence>) {
    static PROBE: std::sync::OnceLock<(IoReportStatus, Option<liveness::ProbeEvidence>)> = std::sync::OnceLock::new();
    PROBE.get_or_init(ioreport::host_probe)
}

/// What the probe behind [`ioreport_status`] saw: the record its rule held
/// when it stopped — each CPU rail's advances, the intervals observed and how
/// many counted, the counted time, the window and the longest interval — so
/// that a status cached for the life of the process can be checked from a log.
/// Runs the probe if it has not run. `None` off macOS, or where no
/// subscription opened. The tests print it beside every verdict they hold the
/// status to.
#[cfg_attr(not(all(test, target_os = "macos")), allow(dead_code))]
pub(crate) fn ioreport_probe_evidence() -> Option<&'static liveness::ProbeEvidence> {
    #[cfg(target_os = "macos")]
    {
        ioreport_probe().1.as_ref()
    }
    #[cfg(not(target_os = "macos"))]
    {
        None
    }
}

/// The Neural Engine rail's liveness, probed once per process and cached.
///
/// The first call runs the shared liveness rule over the ANE rails of
/// IOReport's `Energy Model` group, with `load` as the work between samples:
/// `load` must put work on the **Neural Engine** (a Core ML prediction on the
/// ANE, say) and wait for it. Burning CPU does not move an ANE rail, and an
/// idle ANE's rail holds, so no other load can prove it live. Every later call
/// ignores its `load` and returns the cached answer.
///
/// Measured on an M5 Max, macOS 27.0.1, as an unprivileged reader: `ANE0` did
/// not advance in any of 25 sample intervals over 3 s of Core ML inference on
/// the ANE, while root `powermetrics` read 0.47 J of ANE energy over the same
/// span. So a Neural Engine figure from that rail would read 0 J for real
/// work; [`FabricMeter`] reports one only once this has said
/// [`CounterStatus::Live`]. `Unavailable` off macOS and where no ANE rail is
/// published.
pub fn npu_rail_liveness(load: impl FnMut()) -> CounterStatus {
    #[cfg(target_os = "macos")]
    {
        *NPU_RAIL_LIVENESS.get_or_init(|| ioreport::npu_status(load))
    }
    #[cfg(not(target_os = "macos"))]
    {
        let _ = load;
        CounterStatus::Unavailable
    }
}

/// The cached Neural Engine rail liveness, if this process has probed it
/// ([`npu_rail_liveness`]).
pub fn npu_rail_liveness_cached() -> Option<CounterStatus> {
    #[cfg(target_os = "macos")]
    {
        NPU_RAIL_LIVENESS.get().copied()
    }
    #[cfg(not(target_os = "macos"))]
    {
        None
    }
}

#[cfg(target_os = "macos")]
static NPU_RAIL_LIVENESS: std::sync::OnceLock<CounterStatus> = std::sync::OnceLock::new();

/// Whether the Neural Engine rail has been proved live in this process.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn npu_proved_live() -> bool {
    npu_rail_liveness_cached() == Some(CounterStatus::Live)
}

/// Whether a liveness status admits the IOReport rung: [`IoReportStatus::Live`]
/// and nothing else. The one gate the selection path ([`Meter::detect`]) goes
/// through, pure so that every status is checked in a test.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn admits(status: IoReportStatus) -> bool {
    matches!(status, IoReportStatus::Live)
}

/// Test instrumentation, not API: how many times the real IOReport liveness
/// probe has run in this process. [`ioreport_status`] runs it once however
/// many threads ask, and `tests/ioreport_probed_once.rs` pins that, as does a
/// lib test in a fresh process of its own. Always 0 off macOS, where there is
/// no probe.
#[doc(hidden)]
pub fn ioreport_probe_runs() -> usize {
    #[cfg(target_os = "macos")]
    {
        ioreport::host_probe_runs()
    }
    #[cfg(not(target_os = "macos"))]
    {
        0
    }
}

/// Test instrumentation, not API: how many subscriptions to the Energy Model
/// group this process has opened, one per probe whatever ran it. Always 0 off
/// macOS.
#[doc(hidden)]
pub fn ioreport_energy_model_opens() -> usize {
    #[cfg(target_os = "macos")]
    {
        ioreport::energy_model_opens()
    }
    #[cfg(not(target_os = "macos"))]
    {
        0
    }
}

/// A metering backend, in ladder order.
#[derive(Debug)]
pub enum Meter {
    /// Hardware CPU package energy → `Provenance::HwShunt`. [`Meter::detect`]
    /// selects it only while every package counter is live ([`rapl_status`]), and
    /// a span over which no package counter advanced is the default-power
    /// estimate (`counter_span`).
    Rapl(Rapl),
    /// Hardware GPU energy → `Provenance::HwShunt`, `Coverage::Partial`: the
    /// counter reads the GPU, and the CPU's share of the work goes unmetered,
    /// so a figure from it never claims the whole task (SPEC §5).
    /// [`Meter::detect`] selects it only while the counter is live
    /// ([`nvml_status`]), and a span over which it did not advance is the
    /// whole-task default-power estimate.
    #[cfg(feature = "nvml")]
    Nvml(Box<Nvml>),
    /// This process's CPU energy, as the kernel counts it for this process's
    /// threads (`ri_energy_nj`, macOS) → `Provenance::HwShunt`,
    /// `Coverage::Whole` for in-process CPU work. Its domain is this process's
    /// threads' CPU energy, every thread of the process during the span: not
    /// other processes, not child processes, not the GPU, the Neural Engine
    /// or DRAM. Work that stays on this process's CPU threads is covered
    /// whole; work a span hands to a child process or to the GPU is not in
    /// the figure. A span that reaped a child, or ends with one, is graded
    /// `Coverage::Partial`, so the figure never claims the child's share; work
    /// handed to the GPU is not detected. [`Meter::detect`] selects it only
    /// while the counter is live
    /// ([`process_energy_status`]), and a span over which it did not advance is
    /// the default-power estimate (`process_span`). So is a span either of
    /// whose two reads the metering thread was not seen to leave its core
    /// before: the kernel counts a thread's energy into its process's only
    /// when the thread leaves a core, so each read sleeps first and checks.
    #[cfg(target_os = "macos")]
    ProcessEnergy(process_energy::ProcessEnergy),
    /// Apple Silicon IOReport Energy Model energy → `Provenance::HwShunt`, the
    /// grade of RAPL's and NVML's vendor counters. [`Meter::detect`] selects it
    /// only while every CPU energy rail is live, and a span over which no CPU
    /// rail advanced is the default-power estimate (`ioreport_span`).
    #[cfg(target_os = "macos")]
    IoReport(ioreport::IoReport),
    /// Wall-clock × an active power calibrated on this host →
    /// `Provenance::ModelBased` ([`Meter::time_power`]).
    TimePower { milliwatts: u64 },
    /// Wall-clock × an active power no host calibrated — the documented
    /// default ([`DEFAULT_ACTIVE_MILLIWATTS`]), or any other assumed figure →
    /// `Provenance::Estimator` ([`Meter::uncalibrated_time_power`]). The rung
    /// [`Meter::detect`] falls to when no counter rung is admitted: it scales
    /// with the work's duration, but the power it scales by is a constant
    /// nothing measured, so the figure claims no better than an estimate.
    UncalibratedTimePower { milliwatts: u64 },
    /// Fixed per-operation figure → `Provenance::Estimator`.
    Const { per_op_uj: u64 },
}

/// A rung of the metering ladder, in ladder order, best first. Every rung is
/// named on every platform, so a caller can match on it anywhere; a rung the
/// platform does not have is never selected.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Rung {
    /// RAPL package counters (Linux).
    Rapl,
    /// NVML's GPU total-energy counter (feature `nvml`).
    Nvml,
    /// The kernel's count of this process's CPU energy (macOS).
    ProcessEnergy,
    /// IOReport's SoC Energy Model counters (Apple Silicon).
    IoReport,
    /// The time×power model at a host-calibrated power (`ModelBased`).
    TimePower,
    /// The time×power figure at a power no host calibrated (`Estimator`).
    UncalibratedTimePower,
    /// The constant per-operation estimator.
    Constant,
}

/// Why [`Meter::detect_explained`] selected the rung it did: the rung, and the
/// status each counter rung above it was declined on.
///
/// The ladder is walked best first and stops at the first rung admitted, so a
/// status is `Some` for every rung it asked — those above the selected one and
/// the selected one itself — and `None` for every rung below it, which it never
/// asked: asking would have run that rung's liveness probe. A status that
/// admits its rung beside a lower `selected` rung means the counter was live
/// but did not open when the meter was built.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Detection {
    /// The rung the meter was built on.
    pub selected: Rung,
    /// [`rapl_status`], if asked.
    pub rapl: Option<CounterStatus>,
    /// [`nvml_status`], if asked.
    pub nvml: Option<CounterStatus>,
    /// [`process_energy_status`], if asked.
    pub process_energy: Option<CounterStatus>,
    /// [`ioreport_status`], if asked.
    pub ioreport: Option<IoReportStatus>,
}

impl Detection {
    /// This explanation, with `meter`'s rung as the one selected.
    fn selecting(mut self, meter: Meter) -> (Meter, Detection) {
        self.selected = meter.rung();
        (meter, self)
    }
}

/// Where [`Meter::detect`] gets each rung's liveness status, and the counters
/// it opens: the cached host probes ([`Ladder::host`]), or in tests any status
/// and a fake counter, so every gate is driven with every status on a host
/// whose own statuses are one value each.
struct Ladder<'a> {
    rapl: &'a dyn Fn() -> CounterStatus,
    open_rapl: &'a dyn Fn() -> Option<Rapl>,
    nvml: &'a dyn Fn() -> CounterStatus,
    process_energy: &'a dyn Fn() -> CounterStatus,
    #[cfg(target_os = "macos")]
    open_process_energy: &'a dyn Fn() -> Option<process_energy::ProcessEnergy>,
    ioreport: &'a dyn Fn() -> IoReportStatus,
}

impl Ladder<'static> {
    /// The ladder [`Meter::detect`] runs: the cached host probes and the real
    /// openers.
    fn host() -> Self {
        Ladder {
            rapl: &rapl_status,
            open_rapl: &Rapl::open,
            nvml: &nvml_status,
            process_energy: &process_energy_status,
            #[cfg(target_os = "macos")]
            open_process_energy: &process_energy::ProcessEnergy::open,
            ioreport: &ioreport_status,
        }
    }
}

/// CPU time the calling thread has used, user and system
/// (`clock_gettime(CLOCK_THREAD_CPUTIME_ID)`), or `None` where the clock cannot
/// be read. Exact to the nanosecond and live: unlike a process's energy count,
/// which a thread's work joins only when the thread leaves its core, the
/// thread's CPU time is computed at the read. So it divides a span's reading
/// among work that ran in turn on one thread, at no cost to the span.
pub fn thread_cpu_time() -> Option<std::time::Duration> {
    liveness::thread_cpu_time()
}

impl Meter {
    /// Pick the best backend this environment exposes. Never fails: when no
    /// hardware interface exists the result is the time×power figure at the
    /// default power ([`Meter::UncalibratedTimePower`], `Estimator`) — there
    /// is always an estimate, it just says so in its provenance. Nothing here
    /// calibrates a power, so `detect` never selects the `ModelBased`
    /// [`Meter::TimePower`]: a caller holding a power the host measured builds
    /// that rung itself ([`Meter::time_power`]).
    ///
    /// A vendor counter rung is selected only while its counter is live (SPEC
    /// §5): RAPL on [`rapl_status`], NVML on [`nvml_status`], the per-process
    /// counter on [`process_energy_status`], IOReport on [`ioreport_status`],
    /// each probed once per process. Each status is asked for only once every
    /// rung above it is declined, so a process pays for no probe below the
    /// rung it gets. [`Meter::detect_explained`] says which rung was selected
    /// and why the ones above it were declined.
    ///
    /// The per-process counter sits above IOReport. Both are vendor readings,
    /// but they read different domains: the per-process count is the CPU
    /// energy of this process's own threads, so it attributes the work's own
    /// CPU energy, while IOReport's counter is SoC-wide and takes in every
    /// other process's draw and the machine-wide GPU rail. Where both are
    /// live the figure that is the work's own wins.
    pub fn detect() -> Self {
        Self::detect_with(&Ladder::host()).0
    }

    /// [`Meter::detect`], and why: the rung selected and the liveness status
    /// of every rung asked on the way to it ([`Detection`]). The statuses are
    /// the cached ones `detect` reads, so a caller or a receipt can record why
    /// a host is metered by the rung it is, and not by a better one.
    pub fn detect_explained() -> (Self, Detection) {
        Self::detect_with(&Ladder::host())
    }

    /// [`Meter::detect_explained`] on a given ladder. Each counter rung is
    /// opened only when its status admits it ([`select`], [`admits`]).
    fn detect_with(ladder: &Ladder<'_>) -> (Self, Detection) {
        let mut why = Detection {
            selected: Rung::UncalibratedTimePower,
            rapl: None,
            nvml: None,
            process_energy: None,
            ioreport: None,
        };
        // Opening a counter is not enough: it must be live (SPEC §5), or a
        // count republished in lumps landing in one span is graded a hardware
        // reading of that span's work.
        let rapl = (ladder.rapl)();
        why.rapl = Some(rapl);
        if let Some(r) = select(rapl, ladder.open_rapl) {
            return why.selecting(Meter::Rapl(r));
        }
        let nvml = (ladder.nvml)();
        why.nvml = Some(nvml);
        #[cfg(feature = "nvml")]
        if let Some(n) = select(nvml, Nvml::open) {
            return why.selecting(Meter::Nvml(Box::new(n)));
        }
        let process = (ladder.process_energy)();
        why.process_energy = Some(process);
        #[cfg(target_os = "macos")]
        if let Some(p) = select(process, ladder.open_process_energy) {
            return why.selecting(Meter::ProcessEnergy(p));
        }
        let io = (ladder.ioreport)();
        why.ioreport = Some(io);
        #[cfg(target_os = "macos")]
        if admits(io) {
            if let Some(m) = ioreport::IoReport::open() {
                return why.selecting(Meter::IoReport(m));
            }
        }
        why.selecting(Meter::uncalibrated_time_power(DEFAULT_ACTIVE_MILLIWATTS))
    }

    /// The rung this meter is.
    pub fn rung(&self) -> Rung {
        match self {
            Meter::Rapl(_) => Rung::Rapl,
            #[cfg(feature = "nvml")]
            Meter::Nvml(_) => Rung::Nvml,
            #[cfg(target_os = "macos")]
            Meter::ProcessEnergy(_) => Rung::ProcessEnergy,
            #[cfg(target_os = "macos")]
            Meter::IoReport(_) => Rung::IoReport,
            Meter::TimePower { .. } => Rung::TimePower,
            Meter::UncalibratedTimePower { .. } => Rung::UncalibratedTimePower,
            Meter::Const { .. } => Rung::Constant,
        }
    }

    /// A time×power model with an active power calibrated on this host — a
    /// figure a measurement on the deployment host produced, such as its draw
    /// under load read from a shunt or a live counter → `ModelBased` (SPEC
    /// §5.1 rung 5). A power taken from anywhere else (the documented
    /// default, a nameplate or datasheet figure, another host's calibration)
    /// is not a calibration of this host: build
    /// [`Meter::uncalibrated_time_power`] with it, an estimate.
    pub fn time_power(milliwatts: u64) -> Self {
        Meter::TimePower { milliwatts }
    }

    /// A time×power figure with an active power no host calibrated — the
    /// documented default ([`DEFAULT_ACTIVE_MILLIWATTS`]), a nameplate or
    /// datasheet figure → `Estimator` (SPEC §5.1 rung 6).
    pub fn uncalibrated_time_power(milliwatts: u64) -> Self {
        Meter::UncalibratedTimePower { milliwatts }
    }

    /// A constant per-operation estimator.
    pub fn constant(per_op_uj: u64) -> Self {
        Meter::Const { per_op_uj }
    }

    /// The provenance this backend stamps on its readings.
    pub fn provenance(&self) -> Provenance {
        match self {
            Meter::Rapl(_) => Provenance::HwShunt,
            #[cfg(feature = "nvml")]
            Meter::Nvml(_) => Provenance::HwShunt,
            #[cfg(target_os = "macos")]
            Meter::ProcessEnergy(_) => Provenance::HwShunt,
            #[cfg(target_os = "macos")]
            Meter::IoReport(_) => Provenance::HwShunt,
            Meter::TimePower { .. } => Provenance::ModelBased,
            Meter::UncalibratedTimePower { .. } | Meter::Const { .. } => Provenance::Estimator,
        }
    }

    /// Run `work` and meter it. The returned [`Energy`] carries the honest
    /// provenance of however the figure was obtained — including when a
    /// hardware backend fails mid-read and the figure degrades to the
    /// time×power figure at the default power, an `Estimator` figure.
    pub fn measure<T>(&self, work: impl FnOnce() -> T) -> (T, Energy) {
        match self {
            Meter::Rapl(r) => {
                let before = r.read();
                let started = Instant::now();
                let out = work();
                let elapsed = started.elapsed();
                // A read that failed (the interface vanished mid-span) is no
                // rise, and degrades honestly.
                // So is a package that fell with no known wrap.
                let rose = match (before, r.read()) {
                    (Some(b), Some(a)) => r.delta(&b, &a),
                    _ => None,
                };
                (out, counter_span(rose, elapsed.as_nanos(), Energy::measured))
            }
            #[cfg(feature = "nvml")]
            Meter::Nvml(n) => {
                let before = n.read_uj();
                let started = Instant::now();
                let out = work();
                let elapsed = started.elapsed();
                (out, nvml_span(before, n.read_uj(), elapsed.as_nanos()))
            }
            #[cfg(target_os = "macos")]
            Meter::ProcessEnergy(p) => {
                // Each read sleeps first, and is taken only once this thread
                // is seen to have left its core. The sleeps are outside the
                // work's wall time, which the estimate for a span with no
                // reading scales by.
                let before = p.read();
                let started = Instant::now();
                let out = work();
                let elapsed = started.elapsed();
                // The children first, then the count: a child reaped between
                // the two is then listed, or in the reaped children's time.
                let children = process_energy::child_count();
                // No reading at the start is no span: the end is not read.
                let after = before.and_then(|_| p.read());
                (out, process_span(before, after, children, elapsed.as_nanos()))
            }
            #[cfg(target_os = "macos")]
            Meter::IoReport(io) => {
                let before = io.read();
                let started = Instant::now();
                let out = work();
                let elapsed = started.elapsed();
                (out, ioreport_span(before, io.read(), elapsed.as_nanos()))
            }
            Meter::TimePower { milliwatts } => {
                let started = Instant::now();
                let out = work();
                (out, Energy::modeled(time_power_uj(started.elapsed().as_nanos(), *milliwatts)))
            }
            Meter::UncalibratedTimePower { milliwatts } => {
                let started = Instant::now();
                let out = work();
                (out, Energy::estimator(time_power_uj(started.elapsed().as_nanos(), *milliwatts)))
            }
            Meter::Const { per_op_uj } => (work(), Energy::estimator(*per_op_uj)),
        }
    }
}

// ─── Per-fabric energy ──────────────────────────────────────────────────────

/// An on-die fabric whose energy the platform counts separately.
///
/// The metering ladder ([`Meter`]) admits exactly one rung and reports one
/// number, which is right for debiting a budget and wrong for understanding
/// where the energy went. On Apple silicon the two are not the same question:
/// for an unprivileged reader on macOS 27 the `CPU Energy` rails hold their
/// value while the `GPU Energy` rail advances continuously, so the ladder
/// declines the whole IOReport rung and loses a live counter — the one that
/// reads the fabric every local inference actually runs on.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Fabric {
    /// The CPU cores.
    Cpu,
    /// A GPU, discrete or integrated.
    Gpu,
    /// A neural / inference accelerator: Apple's Neural Engine, a Qualcomm or
    /// Intel NPU, a Google TPU, Huawei Ascend, Intel Gaudi, Cambricon.
    Npu,
    /// Reconfigurable logic.
    Fpga,
    /// A DSP block, which on a mobile SoC often runs the quantised path.
    Dsp,
    /// Main memory. Metered separately where a rail exists, because on a large
    /// model the data movement is a large share and attributing it to the
    /// compute fabric overstates that fabric.
    Dram,
    /// The whole package or board, as an external meter or a board rail sees
    /// it. Not a compute fabric: the sum, including losses the on-die counters
    /// never see.
    Package,
}


impl Fabric {
    /// A stable lowercase name, for a receipt or a log.
    pub fn as_str(self) -> &'static str {
        match self {
            Fabric::Cpu => "cpu",
            Fabric::Gpu => "gpu",
            Fabric::Npu => "npu",
            Fabric::Fpga => "fpga",
            Fabric::Dsp => "dsp",
            Fabric::Dram => "dram",
            Fabric::Package => "package",
        }
    }

    /// Every fabric class, for a caller surveying a host.
    pub fn all() -> &'static [Fabric] {
        &[
            Fabric::Cpu,
            Fabric::Gpu,
            Fabric::Npu,
            Fabric::Fpga,
            Fabric::Dsp,
            Fabric::Dram,
            Fabric::Package,
        ]
    }
}

/// Whose work a figure counts — the axis [`Coverage`] cannot express.
///
/// `Coverage` says whether a figure covers the whole *task*; this says whose
/// task. They are independent, and conflating them is what made a live GPU
/// rail unusable: it is a real reading of the whole GPU, and it cannot tell
/// one process's share from another's.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Attribution {
    /// This process's work alone. The kernel attributes it (macOS
    /// `ri_energy_nj`), so another process's load does not inflate it.
    Process,
    /// Every process on the machine. An SoC energy rail counts the fabric, not
    /// the caller, so a figure from one is only this work's energy to the
    /// extent that nothing else was using that fabric. A caller that needs a
    /// per-task figure from a machine-wide rail MUST bracket the span with
    /// idle baselines and say so.
    Machine,
}

/// One fabric's energy over a span.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FabricEnergy {
    /// Which fabric.
    pub fabric: Fabric,
    /// Energy over the span, microjoules.
    pub uj: u64,
    /// Whose work it counts.
    pub attribution: Attribution,
    /// How long the span was. Reported because a vendor energy counter has an
    /// update period, and a figure taken over a span shorter than the counter
    /// can resolve is not a measurement of that span: a published study of one
    /// such counter found it under-reporting integrated power by 95.4% at
    /// 0.5 ms sampling, recovering to 1.6% only at 1 s. A caller MUST compare
    /// this against the counter's period before grading the figure, and a
    /// per-operation figure for work shorter than the period is sound only as
    /// the mean of many operations over a span longer than it.
    pub span_ns: u128,
}

/// Reads each fabric the host exposes separately, over a span.
///
/// Composes two counters rather than choosing between them, because on this
/// platform neither covers the work alone: the kernel's per-process counter
/// attributes CPU energy and explicitly excludes the GPU and the Neural
/// Engine, and IOReport's rails read those fabrics and cannot attribute. Used
/// together they cover the fabrics the work used, each figure carrying which
/// fabric it read and whose work it counts.
#[derive(Debug, Default)]
pub struct FabricMeter {
    #[cfg(target_os = "macos")]
    ioreport: Option<ioreport::IoReport>,
    /// This process's CPU energy count, where the kernel answers for it and
    /// for the reading thread's own count its reads are checked against.
    #[cfg(target_os = "macos")]
    process: Option<process_energy::ProcessEnergy>,
}

impl FabricMeter {
    /// Open every per-fabric counter this host exposes.
    pub fn detect() -> Self {
        #[cfg(target_os = "macos")]
        {
            FabricMeter { ioreport: ioreport::IoReport::open(), process: process_energy::ProcessEnergy::open() }
        }
        #[cfg(not(target_os = "macos"))]
        {
            FabricMeter::default()
        }
    }

    /// Which fabrics this meter can read, and whose work each figure counts.
    pub fn readable(&self) -> Vec<(Fabric, Attribution)> {
        #[cfg(target_os = "macos")]
        {
            let mut out = Vec::new();
            if self.process.is_some() {
                out.push((Fabric::Cpu, Attribution::Process));
            }
            if self.ioreport.is_some() {
                out.push((Fabric::Gpu, Attribution::Machine));
                if npu_proved_live() {
                    out.push((Fabric::Npu, Attribution::Machine));
                }
            }
            out
        }
        #[cfg(not(target_os = "macos"))]
        {
            Vec::new()
        }
    }

    /// Run `work`, and report each fabric's energy over it.
    ///
    /// A fabric whose counter did not advance is reported as zero rather than
    /// omitted: on an idle fabric that is the truth, and the caller can tell
    /// "read zero" from "could not read" by [`Self::readable`]. That holds
    /// only for a counter that is live: the Neural Engine is reported only
    /// once [`npu_rail_liveness`] has proved its rail live, because on macOS
    /// 27.0.1 an unprivileged reader's `ANE0` holds through real ANE work.
    ///
    /// The CPU figure is this process's own count, read at each end only
    /// once the calling thread is seen to have left its core (the kernel
    /// counts a thread's energy into its process's only then). A span with
    /// an end not so read has no CPU figure: it is omitted, not reported
    /// short or with what the thread spent before the span.
    pub fn measure<T>(&self, work: impl FnOnce() -> T) -> (T, Vec<FabricEnergy>) {
        #[cfg(target_os = "macos")]
        let cpu_before = self.process.as_ref().and_then(|p| p.read_energy_nj());
        let started = std::time::Instant::now();
        #[cfg(target_os = "macos")]
        let io_before = self.ioreport.as_ref().and_then(|m| m.read());

        let out = work();

        let span_ns = started.elapsed().as_nanos();
        #[cfg(target_os = "macos")]
        let readings = {
            let mut readings = Vec::new();
            let cpu_after = cpu_before.and_then(|_| self.process.as_ref()?.read_energy_nj());
            if let (Some(b), Some(a)) = (cpu_before, cpu_after) {
                readings.push(FabricEnergy {
                    fabric: Fabric::Cpu,
                    uj: a.saturating_sub(b) / 1_000,
                    attribution: Attribution::Process,
                    span_ns,
                });
            }
            let io_after = self.ioreport.as_ref().and_then(|m| m.read());
            if let (Some(b), Some(a)) = (io_before, io_after) {
                readings.push(FabricEnergy {
                    fabric: Fabric::Gpu,
                    uj: a.gpu_uj.saturating_sub(b.gpu_uj),
                    attribution: Attribution::Machine,
                    span_ns,
                });
                // Only from a rail proved live: an unproven ANE rail's zero is
                // not the Neural Engine's energy ([`npu_rail_liveness`]).
                if npu_proved_live() {
                    readings.push(FabricEnergy {
                        fabric: Fabric::Npu,
                        uj: a.ane_uj.saturating_sub(b.ane_uj),
                        attribution: Attribution::Machine,
                        span_ns,
                    });
                }
            }
            readings
        };
        #[cfg(not(target_os = "macos"))]
        let readings = {
            let _ = span_ns;
            Vec::new()
        };
        (out, readings)
    }
}

// ─── Heterogeneous fabric survey ────────────────────────────────────────────

/// The counter a fabric's energy figure came from.
///
/// Named on every platform so a caller can match on it anywhere, and so a
/// receipt can say *which* counter produced a figure rather than only that it
/// was "hardware". Two figures graded `HwShunt` from different sources are not
/// interchangeable: they have different domains, different update periods and
/// different attribution.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum FabricSource {
    /// macOS `proc_pid_rusage` `ri_energy_nj` — this process's own CPU energy.
    /// The only source here that attributes to a principal.
    ProcRusage,
    /// Apple silicon IOReport `Energy Model` rails.
    IoReport,
    /// macOS `powermetrics`, which exposes rails IOReport withholds from an
    /// unprivileged reader.
    Powermetrics,
    /// Linux `powercap` RAPL (`intel-rapl`, `amd-rapl`): CPU package, and on
    /// some parts DRAM and the integrated GPU.
    Rapl,
    /// NVIDIA `libnvidia-ml` total-energy counter.
    Nvml,
    /// AMD `rocm_smi` `rsmi_dev_energy_count_get`.
    RocmSmi,
    /// Intel oneAPI Level Zero Sysman `zesPowerGetEnergyCounter` — discrete and
    /// integrated GPUs, and the Meteor-Lake-and-later NPU.
    LevelZero,
    /// NVIDIA Jetson INA3221 board rails over hwmon.
    TegraIna,
    /// Qualcomm Power Telemetry, the Snapdragon per-unit stack.
    QualcommQpt,
    /// Huawei `npu-smi` (Ascend).
    AscendSmi,
    /// Intel Gaudi `hl-smi`.
    HabanaSmi,
    /// Cambricon `cnmon`.
    CambriconCnmon,
    /// A meter outside the machine: a shunt, a PDU, a bench DMM. The only
    /// source that sees conversion losses, and the only one that can be
    /// calibrated against a traceable reference.
    ExternalMeter,
}

impl FabricSource {
    /// A stable lowercase name, for a receipt or a log.
    pub fn as_str(self) -> &'static str {
        match self {
            FabricSource::ProcRusage => "proc-rusage",
            FabricSource::IoReport => "ioreport",
            FabricSource::Powermetrics => "powermetrics",
            FabricSource::Rapl => "rapl",
            FabricSource::Nvml => "nvml",
            FabricSource::RocmSmi => "rocm-smi",
            FabricSource::LevelZero => "level-zero",
            FabricSource::TegraIna => "tegra-ina",
            FabricSource::QualcommQpt => "qualcomm-qpt",
            FabricSource::AscendSmi => "ascend-smi",
            FabricSource::HabanaSmi => "habana-smi",
            FabricSource::CambriconCnmon => "cambricon-cnmon",
            FabricSource::ExternalMeter => "external-meter",
        }
    }

    /// Whether this crate has a reader for this source, as opposed to only
    /// knowing it exists.
    ///
    /// Stated rather than implied, because "we did not measure it" and "it
    /// cannot be measured" are different facts and a survey that blurs them is
    /// worthless. See [`FabricStatus::NotImplemented`].
    pub fn has_backend(self) -> bool {
        matches!(self, FabricSource::ProcRusage | FabricSource::IoReport | FabricSource::Rapl)
            || (matches!(self, FabricSource::Nvml) && cfg!(feature = "nvml"))
    }
}

/// Whether this host can meter one fabric from one source — and when it
/// cannot, which of the five different reasons applies.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FabricStatus {
    /// A live counter. `resolution_ns` is the period over which the counter is
    /// documented or measured to update; `None` means the period is
    /// **undeclared**, which is not the same as fast.
    Live { attribution: Attribution, resolution_ns: Option<u64> },
    /// The silicon and the counter are both here, and the counter is not
    /// advancing — so a figure from it would be a reading of nothing. Apple's
    /// CPU rails do this for an unprivileged reader.
    Frozen,
    /// This `(fabric, source)` pair is not available here: either the silicon
    /// is absent, or this source is not an interface to it on this platform
    /// (`ri_energy_nj` off macOS, RAPL off x86 Linux).
    ///
    /// It makes **no** claim that the fabric is unmeasurable by some other
    /// route, and so — unlike [`FabricStatus::NoCounterExists`] — it excuses
    /// nothing. Reporting a counter this process merely cannot read as
    /// `Absent` would assert an absence of hardware; that is
    /// [`FabricStatus::NeedsPrivilege`].
    Absent,
    /// The silicon is here and the counter needs privilege this process does
    /// not have. A legitimate gap, and a fixable one.
    NeedsPrivilege,
    /// The silicon is here, and it exposes **no energy counter at all**. Any
    /// figure for it is modelled, by anyone, and that is a property of the
    /// hardware rather than a gap in this crate. This is the status that makes
    /// an energy-disclosure exemption legitimate.
    NoCounterExists,
    /// A counter exists and this build has no reader for it. Our gap, named.
    NotImplemented,
}

impl FabricStatus {
    /// Whether a span of `span_ns` may be graded as a **hardware reading** from
    /// this source.
    ///
    /// A vendor energy counter has an update period, and a figure taken over a
    /// span shorter than that period is not a measurement of the span: a
    /// 588-run study of one such counter measured it under-reporting
    /// integrated power by 95.4% at 0.5 ms sampling, recovering to 1.6% only
    /// at 1 s. Under-reporting is the unsafe direction at a ceiling, because it
    /// admits work the budget cannot cover.
    ///
    /// A counter whose period is **undeclared** can never grade a span, at any
    /// length: the error direction is unknown, and an unknown direction at a
    /// gate has to be read as possibly-under-reporting. That is deliberately
    /// strict — the alternative is to believe a number nobody characterised.
    pub fn may_grade_span(&self, span_ns: u128) -> bool {
        match self {
            FabricStatus::Live { resolution_ns: Some(period), .. } => {
                span_ns >= u128::from(*period)
            }
            _ => false,
        }
    }
}

/// One `(fabric, source)` pair this crate knows about, and what this host can
/// do with it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct FabricCapability {
    /// The silicon.
    pub fabric: Fabric,
    /// The counter that would read it.
    pub source: FabricSource,
    /// What this host can actually do.
    pub status: FabricStatus,
    /// What the probe was, or why no counter exists — so a reader can check
    /// the claim instead of trusting it.
    pub note: &'static str,
}

/// Which Apple silicon Energy Model rails are advancing on this host, per
/// fabric.
///
/// A direct observation rather than a guess: two reads of the same
/// subscription with a CPU burn between them, so a rail that *would* advance
/// under load is seen to. The CPU rails are expected to be frozen here — they
/// hold their value for an unprivileged reader on macOS 27 — and the point of
/// probing rather than assuming is that this is a per-OS-version fact that
/// should be observed on the host it is claimed about.
#[cfg(target_os = "macos")]
fn ioreport_rail_survey() -> Vec<(Fabric, bool, &'static str)> {
    const NOTES: [(Fabric, &str); 3] = [
        (Fabric::Cpu, "IOReport `Energy Model` / `CPU Energy` (per-die on a multi-die part)"),
        (Fabric::Gpu, "IOReport `Energy Model` / `GPU Energy`"),
        (
            Fabric::Npu,
            "IOReport `Energy Model` / `ANE Energy` where a part has one, else the per-engine `ANE<n>` rails; live only once proved under a Neural Engine load (`npu_rail_liveness`)",
        ),
    ];
    let Some(m) = ioreport::IoReport::open() else {
        return NOTES.iter().map(|(f, n)| (*f, false, *n)).collect();
    };
    let Some(before) = m.read() else {
        return NOTES.iter().map(|(f, n)| (*f, false, *n)).collect();
    };
    // Burn CPU so a live CPU rail has something to count, by this thread's own
    // CPU clock rather than wall time (a loaded host can give a wall-clock
    // spin almost no CPU).
    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(60);
    let mut x: u64 = 0;
    while std::time::Instant::now() < deadline {
        x = x.wrapping_add(deadline.elapsed().subsec_nanos() as u64 ^ (x >> 7));
    }
    std::hint::black_box(x);
    let Some(after) = m.read() else {
        return NOTES.iter().map(|(f, n)| (*f, false, *n)).collect();
    };
    // The CPU and the Neural Engine by the shared liveness rule, never by one
    // advance: a CPU rail republished in lumps advances once now and then, and
    // one advance over 60 ms would call it live. The Neural Engine needs its
    // own load to prove it ([`npu_rail_liveness`]); unproved, it is not live.
    vec![
        (Fabric::Cpu, ioreport_status() == IoReportStatus::Live, NOTES[0].1),
        (Fabric::Gpu, after.gpu_uj > before.gpu_uj, NOTES[1].1),
        (Fabric::Npu, npu_proved_live(), NOTES[2].1),
    ]
}

/// Every `(fabric, source)` pair this crate knows of, with this host's status
/// for each.
///
/// # Why a survey rather than a single number
///
/// A metering ladder picks one rung and reports one figure, which is what a
/// budget needs. It cannot answer the question a heterogeneous host actually
/// raises: *which of my accelerators can be metered at all, by whom, and how
/// well.* On a machine with a CPU, an integrated GPU, a discrete GPU and an
/// NPU, the honest answer differs per fabric and per vendor, and the gaps are
/// not all the same kind of gap.
///
/// The five negative statuses are the point. A disclosure regime that lets a
/// provider skip energy reporting when it "lacks critical information from the
/// compute or hardware provider" is relying on exactly one of them —
/// [`FabricStatus::NoCounterExists`] — and this function distinguishes it from
/// [`FabricStatus::NeedsPrivilege`], [`FabricStatus::Frozen`] and
/// [`FabricStatus::NotImplemented`], which are not the hardware's fault and do
/// not excuse anything.
///
/// Vendor facts below were checked in October 2026 and are the kind that go
/// stale; each carries its own note so a wrong one can be found and corrected.
pub fn survey() -> Vec<FabricCapability> {
    let mut out = Vec::new();
    let mut push = |fabric, source, status, note| {
        out.push(FabricCapability { fabric, source, status, note })
    };

    // ── This process's own CPU energy — the only principal-attributed source.
    #[cfg(target_os = "macos")]
    push(
        Fabric::Cpu,
        FabricSource::ProcRusage,
        match process_energy_status() {
            CounterStatus::Live => FabricStatus::Live {
                attribution: Attribution::Process,
                // Measured on an M5 Max, macOS 27, by burning this thread's
                // CPU for a fixed interval and sampling the counter 60 times
                // per interval. The fraction of intervals in which it
                // advanced: 0% at 10 and 50 µs, 2% at 100 µs, 5% at 500 µs,
                // 35% at 1 ms, 63% at 2 ms, 87% at 5 ms, 100% at 10 ms and
                // above. The crate's liveness criterion is 80%, so 5 ms is
                // where it first clears; 10 ms is declared instead because
                // over-declaring a period refuses spans that would have been
                // fine, and under-declaring grades spans that were not — and
                // at a ceiling only the second error is dangerous.
                //
                // Below 1 ms the counter does not merely lag, it batches: on
                // the intervals where it did advance, the median step was
                // ~20 mJ, the same accrual-in-lumps pathology this crate
                // already refuses on IOReport's CPU rails.
                resolution_ns: Some(10_000_000),
            },
            _ => FabricStatus::Frozen,
        },
        "proc_pid_rusage(RUSAGE_INFO_V6).ri_energy_nj, read in-process",
    );
    #[cfg(not(target_os = "macos"))]
    push(
        Fabric::Cpu,
        FabricSource::ProcRusage,
        FabricStatus::Absent,
        "ri_energy_nj is a macOS interface",
    );

    // ── Apple silicon SoC rails.
    #[cfg(target_os = "macos")]
    {
        let rails = ioreport_rail_survey();
        for (fabric, live, note) in rails {
            push(
                fabric,
                FabricSource::IoReport,
                if live {
                    FabricStatus::Live {
                        attribution: Attribution::Machine,
                        // **1 s, not the 10 ms first declared here.** This
                        // rail has no fixed period: it republishes when there
                        // is activity to report and holds its value when there
                        // is not. Sampled every 2 ms on an M5 Max, the gap
                        // between actual changes was p50 12.7 ms / p90 91 ms /
                        // **max 992 ms** at idle, and p50 13.1 ms / p90 15 ms
                        // / max 42 ms under a sustained MLX matmul.
                        //
                        // So the tight figure is only available to a measurer
                        // who can guarantee the fabric stays busy, and a
                        // measurer cannot. The declared period has to be the
                        // idle worst case, because that is the condition a
                        // short span is most likely to fall inside — a span
                        // that lands entirely within one hold reads zero and
                        // would otherwise be graded as a measurement of zero.
                        //
                        // (An earlier note elsewhere in the fleet put the hold
                        // at 300–600 ms "under load", from a GGUF decode.
                        // That decode is dispatch-bound with idle gaps between
                        // tokens, so it was sampling the idle behaviour; the
                        // two observations agree once the cause is named.)
                        resolution_ns: Some(1_000_000_000),
                    }
                } else {
                    FabricStatus::Frozen
                },
                note,
            );
        }
        push(
            Fabric::Dram,
            FabricSource::IoReport,
            FabricStatus::NotImplemented,
            "`DRAM0` and `DCS0` rails exist in the Energy Model group; this crate does not sum them separately",
        );
        push(
            Fabric::Cpu,
            FabricSource::Powermetrics,
            FabricStatus::NeedsPrivilege,
            "powermetrics exposes the CPU rails IOReport withholds, and needs root",
        );
        push(
            Fabric::Npu,
            FabricSource::Powermetrics,
            FabricStatus::NeedsPrivilege,
            "`sudo powermetrics --samplers ane_power` is the ONLY route to Apple ANE energy, and it is machine-wide: `ANE0` is frozen unprivileged, ANE work runs in `aned` so it is not this process's CPU either, and the H1xANELoadBalancer clients carry no statistics. A span that used the ANE is therefore CPU+GPU only, and Partial",
        );
    }

    // ── x86 CPU package energy.
    //
    // Accessibility is asked **before** liveness, because `Rapl::open` returns
    // `None` for a host with no powercap tree and for a host whose package
    // zone is root-only alike, and this row previously reported both as
    // `Absent` — "this host has no such silicon". On a representative Linux
    // host `energy_uj` carries mode 0440 root:energy, so an unprivileged
    // reader gets `EACCES` from a file that is plainly there. That is
    // `NeedsPrivilege`: a legitimate gap, and a fixable one.
    push(
        Fabric::Cpu,
        FabricSource::Rapl,
        if cfg!(target_os = "linux") {
            rapl_fabric_status(rapl_access(), rapl_status())
        } else {
            FabricStatus::Absent
        },
        "/sys/class/powercap/intel-rapl:*/energy_uj, package zones only; where powercap lists none, each package's \
         energy-status MSR through /dev/cpu/<n>/msr (needs the msr module and CAP_SYS_RAWIO)",
    );
    push(
        Fabric::Dram,
        FabricSource::Rapl,
        FabricStatus::NotImplemented,
        "powercap exposes a top-level `dram` zone on some parts; this crate reads package zones only",
    );

    // ── Discrete accelerators, by vendor.
    push(
        Fabric::Gpu,
        FabricSource::Nvml,
        if cfg!(feature = "nvml") {
            match nvml_status() {
                CounterStatus::Live => FabricStatus::Live {
                    attribution: Attribution::Machine,
                    resolution_ns: Some(10_000_000),
                },
                CounterStatus::Unavailable => FabricStatus::Absent,
                _ => FabricStatus::Frozen,
            }
        } else if probe_path("/dev/nvidiactl") {
            FabricStatus::NotImplemented
        } else {
            FabricStatus::Absent
        },
        "nvmlDeviceGetTotalEnergyConsumption, Volta and later; build with --features nvml",
    );
    push(
        Fabric::Gpu,
        FabricSource::RocmSmi,
        if probe_path("/sys/class/kfd") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "rsmi_dev_energy_count_get; probed by /sys/class/kfd",
    );
    push(
        Fabric::Gpu,
        FabricSource::LevelZero,
        if probe_path("/dev/dri") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "zesPowerGetEnergyCounter; probed by /dev/dri",
    );
    push(
        Fabric::Npu,
        FabricSource::LevelZero,
        if probe_path("/dev/accel/accel0") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "Intel NPU (Meteor Lake and later) via Level Zero Sysman; probed by /dev/accel/accel0",
    );
    push(
        Fabric::Package,
        FabricSource::TegraIna,
        if probe_path("/sys/bus/i2c/drivers/ina3221") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "Jetson INA3221 board rails over hwmon; board rails, so Package not Gpu",
    );
    push(
        Fabric::Npu,
        FabricSource::AscendSmi,
        if probe_path("/dev/davinci0") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "Huawei Ascend via npu-smi; probed by /dev/davinci0",
    );
    push(
        Fabric::Npu,
        FabricSource::HabanaSmi,
        if probe_path("/dev/hl0") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "Intel Gaudi via hl-smi; probed by /dev/hl0",
    );
    push(
        Fabric::Npu,
        FabricSource::CambriconCnmon,
        if probe_path("/dev/cambricon_dev0") { FabricStatus::NotImplemented } else { FabricStatus::Absent },
        "Cambricon via cnmon; probed by /dev/cambricon_dev0",
    );
    push(
        Fabric::Npu,
        FabricSource::QualcommQpt,
        FabricStatus::NotImplemented,
        "Qualcomm Power Telemetry attributes CPU/GPU/NPU on Snapdragon; Android-only, no desktop probe",
    );

    // ── Fabrics that expose nothing, anywhere. The honest exemption.
    push(
        Fabric::Dsp,
        FabricSource::QualcommQpt,
        FabricStatus::NotImplemented,
        "Hexagon DSP energy is in the QPT stack; no reader here",
    );
    push(
        Fabric::Fpga,
        FabricSource::ExternalMeter,
        FabricStatus::NoCounterExists,
        "FPGA energy is board-dependent; no vendor-portable on-die counter exists (Oct 2026)",
    );
    push(
        Fabric::Package,
        FabricSource::ExternalMeter,
        FabricStatus::NoCounterExists,
        "a shunt, PDU or DMM is the only source that sees conversion losses, and the only one calibratable against a traceable reference; not an interface this crate can open",
    );

    out
}

/// The RAPL row's status, from its accessibility and its liveness.
///
/// Extracted from [`survey`] because [`survey`] reads the real
/// `/sys/class/powercap` and so cannot be tested on a host that does not have
/// one — which left this mapping, the whole point of asking about
/// accessibility, unpinned by any test. Taking both answers as arguments makes
/// every combination checkable anywhere.
///
/// Accessibility is asked first: a counter this process cannot read is not an
/// absent counter, and only [`RaplAccess::Readable`] makes the liveness answer
/// meaningful at all — the probe cannot observe a counter it cannot open.
fn rapl_fabric_status(access: RaplAccess, counter: CounterStatus) -> FabricStatus {
    match access {
        RaplAccess::NeedsPrivilege => FabricStatus::NeedsPrivilege,
        RaplAccess::NoInterface => FabricStatus::Absent,
        RaplAccess::Readable => match counter {
            CounterStatus::Live => FabricStatus::Live {
                attribution: Attribution::Machine,
                // The MSR behind powercap updates about every millisecond.
                resolution_ns: Some(1_000_000),
            },
            CounterStatus::Unavailable => FabricStatus::Absent,
            _ => FabricStatus::Frozen,
        },
    }
}

/// Whether a path exists, used only to decide whether silicon is present.
///
/// A presence probe, never a reading: it answers "is there an accelerator
/// here", so the survey can say [`FabricStatus::NotImplemented`] — our gap —
/// instead of [`FabricStatus::Absent`], which would be a false claim about the
/// host.
fn probe_path(p: &str) -> bool {
    std::path::Path::new(p).exists()
}

/// The total of a per-fabric set, and the fabrics it covers.
///
/// Returns the sum and the fabrics it is a sum *of*, so a caller states its
/// coverage instead of implying it. Summing a `Process` figure with a
/// `Machine` one is sound — they read disjoint fabrics — but the result
/// inherits the weaker attribution, which the second element makes visible.
pub fn total_uj(readings: &[FabricEnergy]) -> (u64, Vec<Fabric>) {
    let mut sum = 0u64;
    let mut fabrics: Vec<Fabric> = Vec::new();
    for r in readings {
        sum = sum.saturating_add(r.uj);
        if !fabrics.contains(&r.fabric) {
            fabrics.push(r.fabric);
        }
    }
    fabrics.sort();
    (sum, fabrics)
}

/// One cumulative read of the IOReport counter, in µJ since its first read.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
struct IoReportReading {
    /// Every Energy Model rail the counter sums, CPU included: the SoC total.
    total_uj: u64,
    /// The CPU energy rails alone (`CPU Energy`, or `DIE_<n>_CPU Energy` on
    /// multi-die parts), a share of `total_uj`.
    cpu_uj: u64,
    /// The GPU energy rails alone (`GPU Energy`, or `DIE_<n>_GPU Energy`), a
    /// share of `total_uj`.
    ///
    /// Read separately from `cpu_uj` because on Apple silicon the two rails do
    /// not share a fate: for an unprivileged reader on macOS 27 the CPU rails
    /// hold their value while the GPU rail advances continuously. A metering
    /// ladder that admits or declines the whole counter cannot use the live
    /// half, and GPU-resident work — every local inference on a Mac — is
    /// exactly what the CPU rails would have missed anyway.
    gpu_uj: u64,
    /// The Neural Engine's energy, a share of `total_uj`.
    ///
    /// Counted from the `ANE Energy` aggregate where a part publishes one, and
    /// otherwise from the per-engine `ANE<n>` rails, which on every Apple part
    /// seen here is the only ANE channel that exists. Before this it was
    /// counted from neither, so ANE energy was absent from `total_uj`
    /// altogether and a Neural Engine workload metered as though it were free.
    ane_uj: u64,
}

/// The figure the IOReport rung gives one span, from its reads either side.
///
/// A reading, `HwShunt`, only when the CPU energy rail itself advanced across
/// the span. The figure is then the SoC total's rise: every rail the counter
/// sums, which like a RAPL package counter takes in whatever else ran on the
/// machine meanwhile, so it over-debits the work rather than leave part of it
/// out. A rail that was live at selection can still hold across a span — a
/// span shorter than its update interval, or a rail that has since stopped
/// publishing — and then the total can rise only through rails this work did
/// not drive (the machine-wide GPU rail moves with display compositing). That
/// is not a reading of the work, so the span is the time×power figure at the
/// default power, `Estimator`, as it is when a read fails
/// ([`uncalibrated_span`]). Never `HwShunt` on a figure no counter read.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn ioreport_span(before: Option<IoReportReading>, after: Option<IoReportReading>, elapsed_ns: u128) -> Energy {
    match (before, after) {
        (Some(b), Some(a)) if a.cpu_uj > b.cpu_uj => Energy::measured(a.total_uj.saturating_sub(b.total_uj)),
        _ => uncalibrated_span(elapsed_ns),
    }
}

/// The figure for a span no counter read: its wall-clock duration times the
/// default active power ([`DEFAULT_ACTIVE_MILLIWATTS`]), `Estimator`. The
/// power is assumed, not calibrated on this host, so the figure is an
/// estimate (SPEC §5.1 rung 6), never `ModelBased`: a model's grade is earned
/// by its calibration, and this one has none.
fn uncalibrated_span(elapsed_ns: u128) -> Energy {
    Energy::estimator(time_power_uj(elapsed_ns, DEFAULT_ACTIVE_MILLIWATTS))
}

/// The figure a counter rung gives one span, from how much its counter rose
/// across it: `reading(rise)` only when the counter advanced. A counter that
/// was live at selection can still hold across one span — a span shorter than
/// its update interval, or a counter that has since stopped publishing — and a
/// rise of zero is then not a reading of zero energy: the work ran, and the
/// counter did not publish it. That span, and one whose read failed (`None`),
/// is the time×power figure at the default power, `Estimator`
/// ([`uncalibrated_span`]), as IOReport's held spans are ([`ioreport_span`]).
/// Never `HwShunt` on a figure no counter read.
fn counter_span(rose: Option<u64>, elapsed_ns: u128, reading: fn(u64) -> Energy) -> Energy {
    match rose {
        Some(uj) if uj > 0 => reading(uj),
        _ => uncalibrated_span(elapsed_ns),
    }
}

/// The figure the NVML rung gives one span, from its counter reads either
/// side, in µJ. The counter reads the GPU and nothing else, so a span over
/// which it advanced is a hardware reading that covers only part of the work —
/// the CPU's share is unmetered, not zero — and is graded so:
/// [`Energy::measured_partial`], `HwShunt` with `Coverage::Partial`, which
/// MUST NOT be presented as the task's total (SPEC §5.2). A counter that fell
/// (a driver reload resets it) or held, or a read that failed, is no reading:
/// the whole-task time×power estimate at the default power ([`counter_span`]).
#[cfg_attr(not(feature = "nvml"), allow(dead_code))]
fn nvml_span(before_uj: Option<u64>, after_uj: Option<u64>, elapsed_ns: u128) -> Energy {
    let rose = match (before_uj, after_uj) {
        (Some(b), Some(a)) => a.checked_sub(b),
        _ => None,
    };
    counter_span(rose, elapsed_ns, Energy::measured_partial)
}

/// The figure the per-process rung gives one span, from the process's
/// `rusage_info_v6` read either side of it and its child processes counted at
/// its end (`None`: the count failed).
///
/// A reading, `HwShunt`, only when `ri_energy_nj` advanced across the span:
/// then it is the rise, in µJ rounded **up**, so a span that spent energy never
/// reads as zero and the work is never under-debited by the rounding. Each
/// read is taken once the metering thread is seen to have left its core, so
/// the count holds what that thread spent up to the read; an end where it was
/// not seen to leave has no read (`None`). That span, a span over which the
/// count did not rise, a count that fell, and a failed read are the
/// time×power figure at the default power, `Estimator`, as IOReport's held
/// spans are ([`ioreport_span`]). Never `HwShunt` on a figure no counter
/// read.
///
/// The reading covers the whole span only when no child process can have
/// worked in it unseen: the reaped children's CPU time held across the span,
/// and at its end the process has no child, running or unreaped. A child's
/// energy is its own and never reaches `ri_energy_nj`, so a span that reaped
/// a child, or that leaves one behind, is under-counted by the child's share:
/// [`Energy::measured_partial`], `HwShunt` with `Coverage::Partial`, which MUST
/// NOT be presented as the span's total (SPEC §5.2). So is a span whose child
/// count failed, since nothing then shows the figure whole. A child the
/// process already had before the span counts too: the meter cannot tell
/// whether the span's work drove it. A failed spawn can count as well: the
/// kernel can charge the would-be child's CPU time to the reaped children's
/// time even when `posix_spawn` fails. On an M5 Max (macOS 27.0.1), a
/// `posix_spawn` of a missing path moved it in 2 of 200 attempts (90-127 Mach
/// units). A program spawned by name is looked up by trying each `PATH`
/// directory in turn, so with 12 directories ahead of `/usr/bin`, spawning
/// `yes` by name moved it in 7 of 24 spawns, and by absolute path in none of
/// 12. Such a span is `Partial` on that alone, which errs on the side of
/// claiming less.
#[cfg_attr(not(target_os = "macos"), allow(dead_code))]
fn process_span(
    before: Option<rusage_v6::ProcessEnergyReading>,
    after: Option<rusage_v6::ProcessEnergyReading>,
    children_at_end: Option<usize>,
    elapsed_ns: u128,
) -> Energy {
    let (Some(b), Some(a)) = (before, after) else {
        return counter_span(None, elapsed_ns, Energy::measured);
    };
    let rose_uj = a.energy_nj.checked_sub(b.energy_nj).map(|nj| nj.div_ceil(1_000));
    let whole = children_at_end == Some(0) && a.reaped_children_cpu() == b.reaped_children_cpu();
    counter_span(rose_uj, elapsed_ns, if whole { Energy::measured } else { Energy::measured_partial })
}

/// µJ for a span: `mW × ns` is 10⁻³ W · 10⁻⁹ s = 10⁻¹² J = 10⁻⁶ µJ.
fn time_power_uj(elapsed_ns: u128, milliwatts: u64) -> u64 {
    u64::try_from(elapsed_ns.saturating_mul(milliwatts as u128) / 1_000_000).unwrap_or(u64::MAX)
}

/// Serialises the tests that use IOReport, or burn CPU through the liveness
/// probe, on this host. Otherwise the test harness runs them side by side, and
/// one test's all-channel reads and CPU burn slow another's IOReport samples
/// and thin out its oracle's reads. A test that panics while holding it does
/// not poison the rest.
#[cfg(all(test, target_os = "macos"))]
fn ioreport_hw_lock() -> std::sync::MutexGuard<'static, ()> {
    static HW: std::sync::Mutex<()> = std::sync::Mutex::new(());
    HW.lock().unwrap_or_else(std::sync::PoisonError::into_inner)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detect_always_yields_a_meter_with_honest_provenance() {
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        let meter = Meter::detect();
        let (out, e) = meter.measure(|| 21 * 2);
        assert_eq!(out, 42);
        e.check_provenance().expect("provenance must be internally consistent");
        match e.provenance {
            Provenance::HwShunt => assert!(e.measured_uj.is_some()),
            Provenance::ModelBased | Provenance::Estimator => assert!(e.measured_uj.is_none()),
        }
    }

    #[test]
    fn time_power_scales_with_work() {
        let meter = Meter::time_power(15_000);
        let (_, short) = meter.measure(|| std::thread::sleep(std::time::Duration::from_millis(2)));
        let (_, long) = meter.measure(|| std::thread::sleep(std::time::Duration::from_millis(20)));
        assert_eq!(short.provenance, Provenance::ModelBased);
        assert!(long.uj() > short.uj());
        // 2 ms at 15 W ≈ 30_000 µJ — sanity-band, not exact
        assert!(short.uj() > 10_000 && short.uj() < 1_000_000, "got {}", short.uj());
    }

    /// A time×power figure's grade is its power's: a power calibrated on the
    /// host makes it a model, `ModelBased` (SPEC §5.1 rung 5); the documented
    /// default, which no host calibrated, makes the same arithmetic an
    /// estimate, `Estimator` (rung 6). Both scale with the work's duration and
    /// claim no measurement; the rung, the grade it says it stamps, and the
    /// grade its spans carry agree for each.
    #[test]
    fn only_a_host_calibrated_power_makes_the_time_power_figure_a_model() {
        let calibrated = Meter::time_power(DEFAULT_ACTIVE_MILLIWATTS);
        let default = Meter::uncalibrated_time_power(DEFAULT_ACTIVE_MILLIWATTS);
        for (meter, rung, grade) in [
            (&calibrated, Rung::TimePower, Provenance::ModelBased),
            (&default, Rung::UncalibratedTimePower, Provenance::Estimator),
        ] {
            assert_eq!((meter.rung(), meter.provenance()), (rung, grade), "{meter:?}");
            let (_, short) = meter.measure(|| std::thread::sleep(Duration::from_millis(2)));
            let (_, long) = meter.measure(|| std::thread::sleep(Duration::from_millis(20)));
            for e in [short, long] {
                assert_eq!((e.provenance, e.measured_uj), (grade, None), "{meter:?}: {e:?}");
                assert!(e.is_whole(), "{meter:?}: {e:?}");
                e.check_provenance().unwrap();
            }
            assert!(short.uj() >= time_power_uj(2_000_000, DEFAULT_ACTIVE_MILLIWATTS), "{meter:?}: {short:?}");
            assert!(long.uj() > short.uj(), "{meter:?}: {short:?} then {long:?}");
        }
    }

    /// With no counter rung admitted, `detect()` falls to the time×power
    /// figure at the documented default power, and since nothing on the
    /// ladder calibrated that power the rung, its stamped grade and its
    /// spans' grade are all an estimate's, never `ModelBased`.
    #[test]
    fn the_ladder_falls_to_the_default_power_estimate() {
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        let (meter, why) = Meter::detect_with(&Ladder::none());
        assert!(matches!(meter, Meter::UncalibratedTimePower { milliwatts: DEFAULT_ACTIVE_MILLIWATTS }), "{meter:?}");
        assert_eq!((why.selected, meter.rung()), (Rung::UncalibratedTimePower, Rung::UncalibratedTimePower));
        assert_eq!(meter.provenance(), Provenance::Estimator, "{meter:?}");
        let (_, e) = meter.measure(|| std::thread::sleep(Duration::from_millis(2)));
        assert_eq!((e.provenance, e.measured_uj), (Provenance::Estimator, None), "{e:?}");
        assert!(e.uj() >= time_power_uj(2_000_000, DEFAULT_ACTIVE_MILLIWATTS), "{e:?}");
    }

    /// A span no counter read is the default-power figure for its duration,
    /// graded `Estimator`, whole, with no measurement.
    #[test]
    fn a_span_no_counter_read_is_an_estimate() {
        let e = uncalibrated_span(4_000_000);
        assert_eq!(e, Energy::estimator(time_power_uj(4_000_000, DEFAULT_ACTIVE_MILLIWATTS)));
        assert_eq!(e.uj(), 60_000, "4 ms at 15 W");
        e.check_provenance().unwrap();
    }

    #[test]
    fn constant_estimator_is_constant_and_says_so() {
        let meter = Meter::constant(500);
        let (_, a) = meter.measure(|| ());
        let (_, b) = meter.measure(|| std::thread::sleep(std::time::Duration::from_millis(5)));
        assert_eq!(a.uj(), 500);
        assert_eq!(b.uj(), 500);
        assert_eq!(a.provenance, Provenance::Estimator);
        assert!(a.measured_uj.is_none());
    }

    #[test]
    fn time_power_arithmetic() {
        // 1 s at 1 W = 1 J = 1e6 µJ
        assert_eq!(time_power_uj(1_000_000_000, 1_000), 1_000_000);
        // overflow saturates rather than wrapping
        assert_eq!(time_power_uj(u128::MAX, u64::MAX), u64::MAX);
    }

    #[cfg(not(target_os = "macos"))]
    #[test]
    fn ioreport_is_unavailable_off_macos() {
        assert_eq!(ioreport_status(), IoReportStatus::Unavailable);
    }

    /// Set in the environment of the fresh process that
    /// [`the_liveness_probe_runs_once_in_a_fresh_process`] starts.
    const FRESH_PROCESS: &str = "JCP_ENERGY_FRESH_PROCESS_PIN";

    /// The liveness probe runs once per PROCESS, whoever asks first and
    /// however many ask at once, pinned in the library's own tests: the macOS
    /// CI job runs `cargo test --lib -p jcp-energy`, which does not run
    /// `tests/ioreport_probed_once.rs`. In this process other tests have
    /// already asked for the status, so this test runs its own binary again,
    /// filtered to itself, as a process of its own. There the eight calls
    /// below are the first use of the cache. Counted, not timed.
    #[test]
    fn the_liveness_probe_runs_once_in_a_fresh_process() {
        if std::env::var_os(FRESH_PROCESS).is_some() {
            return probed_once_from_eight_threads();
        }
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        let out = std::process::Command::new(std::env::current_exe().expect("this test binary's path"))
            .args(["tests::the_liveness_probe_runs_once_in_a_fresh_process", "--exact", "--nocapture", "--test-threads=1"])
            .env(FRESH_PROCESS, "1")
            .output()
            .expect("could not run this test binary again");
        let text = format!("{}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
        for line in text.lines().filter(|l| l.starts_with("ioreport cache")) {
            eprintln!("{line}");
        }
        assert!(out.status.success(), "the pin failed in a fresh process:\n{text}");
        // A filter that matched nothing would also exit 0.
        assert!(
            text.contains("running 1 test") && text.contains("1 passed"),
            "the fresh process did not run the pin:\n{text}"
        );
    }

    /// The body [`the_liveness_probe_runs_once_in_a_fresh_process`] runs in
    /// the fresh process. Eight threads, released together, ask for the
    /// status and build the meter, half in each order, then again three
    /// times. The probe must have run, and opened its subscription, once.
    fn probed_once_from_eight_threads() {
        const THREADS: usize = 8;
        assert_eq!(
            (
                ioreport_probe_runs(),
                ioreport_energy_model_opens(),
                rapl_probe_runs(),
                nvml_probe_runs(),
                process_energy_probe_runs()
            ),
            (0, 0, 0, 0, 0),
            "something probed before the pin began, so its calls are not the first use"
        );
        let barrier = std::sync::Barrier::new(THREADS);
        let statuses: Vec<IoReportStatus> = std::thread::scope(|s| {
            let workers: Vec<_> = (0..THREADS)
                .map(|i| {
                    let barrier = &barrier;
                    s.spawn(move || {
                        barrier.wait();
                        let first = if i % 2 == 0 {
                            let _ = Meter::detect();
                            ioreport_status()
                        } else {
                            let status = ioreport_status();
                            let _ = Meter::detect();
                            status
                        };
                        for _ in 0..3 {
                            assert_eq!(ioreport_status(), first, "the cached status changed between calls");
                            let _ = Meter::detect();
                        }
                        first
                    })
                })
                .collect();
            workers.into_iter().map(|w| w.join().expect("a thread panicked")).collect()
        });
        let (runs, opens) = (ioreport_probe_runs(), ioreport_energy_model_opens());
        let (rapl_runs, nvml_runs, process_runs) = (rapl_probe_runs(), nvml_probe_runs(), process_energy_probe_runs());
        eprintln!(
            "ioreport cache (fresh process, lib tests): {THREADS} threads, first use concurrent; they saw {statuses:?}; \
             probe runs = {runs}, Energy Model subscriptions opened = {opens}; RAPL probe runs = {rapl_runs} \
             (status {:?}), NVML probe runs = {nvml_runs} (status {:?}), per-process probe runs = {process_runs} \
             (status {:?})",
            rapl_status(),
            nvml_status(),
            process_energy_status()
        );
        // Every `detect()` asks for the RAPL status first, then, only while
        // no rung above was selected, NVML's, then the per-process counter's:
        // each probe the ladder reached ran once, on whichever thread asked
        // first, and one below the selected rung never ran. On a Linux host
        // whose RAPL is live the ladder stops there, so NVML is never probed;
        // the detection records which statuses were asked. Off macOS there
        // is no per-process probe.
        let (_, why) = Meter::detect_explained();
        assert_eq!(rapl_runs, 1, "the RAPL liveness probe did not run exactly once in this process");
        assert_eq!(
            nvml_runs,
            usize::from(cfg!(feature = "nvml") && why.nvml.is_some()),
            "the NVML liveness probe ran {nvml_runs} times ({why:?})"
        );
        assert_eq!(
            process_runs,
            usize::from(cfg!(target_os = "macos") && why.process_energy.is_some()),
            "the per-process liveness probe ran {process_runs} times ({why:?})"
        );
        assert!(statuses.iter().all(|s| *s == statuses[0]), "threads saw different statuses: {statuses:?}");
        assert_eq!(statuses[0], ioreport_status(), "the spawned threads and this one disagree");
        if cfg!(target_os = "macos") {
            assert_eq!(runs, 1, "the liveness probe did not run exactly once in this process");
            assert_eq!(opens, 1, "{opens} Energy Model subscriptions were opened: something probed besides the cached probe");
        } else {
            assert_eq!((runs, opens), (0, 0), "a probe ran on a platform with no IOReport");
            assert_eq!(statuses[0], IoReportStatus::Unavailable);
        }
    }

    /// The gate itself, on every status: only `Live` admits the IOReport rung.
    #[test]
    fn only_live_admits_the_ioreport_rung() {
        use IoReportStatus as S;
        assert!(admits(S::Live), "Live does not admit the rung");
        for status in [S::Unavailable, S::CpuRailAbsent, S::CpuRailFrozen] {
            assert!(!admits(status), "{status:?} admits the rung");
        }
    }

    /// A span over which the IOReport CPU rail advanced is a vendor-counter
    /// reading, graded as RAPL's and NVML's are: `HwShunt`, the SoC total's
    /// rise as the measured figure, covering the whole of the work.
    #[test]
    fn a_span_the_ioreport_cpu_rail_advanced_over_is_a_hardware_reading() {
        let before = IoReportReading { total_uj: 10_000, cpu_uj: 4_000, gpu_uj: 0, ane_uj: 0 };
        let after = IoReportReading { total_uj: 15_500, cpu_uj: 7_000, gpu_uj: 0, ane_uj: 0 };
        let e = ioreport_span(Some(before), Some(after), 1_000_000);
        assert_eq!(e.provenance, Provenance::HwShunt, "a live span was not graded as a reading: {e:?}");
        assert_eq!(e.measured_uj, Some(5_500), "the reading is not the SoC total's rise: {e:?}");
        assert_eq!(e.uj(), 5_500);
        assert!(e.is_whole(), "the SoC total was reported as partial: {e:?}");
        e.check_provenance().expect("a reading must carry its measured figure");
    }

    /// A span over which the CPU rail held is never a reading, whatever the
    /// SoC total did: the total rising through other rails (the machine-wide
    /// GPU rail) is not this work's energy, and a span that did not move at
    /// all, or whose read failed, measured nothing. Each is the time×power
    /// figure for the span at the default power, `Estimator` (no host
    /// calibrated that power), with no measured figure.
    #[test]
    fn a_span_the_ioreport_cpu_rail_held_over_is_the_models_figure() {
        let elapsed_ns = 2_000_000; // 2 ms
        let model = time_power_uj(elapsed_ns, DEFAULT_ACTIVE_MILLIWATTS);
        assert!(model > 0);
        let b = IoReportReading { total_uj: 10_000, cpu_uj: 4_000, gpu_uj: 0, ane_uj: 0 };
        let cases = [
            ("the GPU rail rose, the CPU rail held", Some(b), Some(IoReportReading { total_uj: 90_000, cpu_uj: 4_000, gpu_uj: 0, ane_uj: 0 })),
            ("nothing moved", Some(b), Some(b)),
            ("the read before failed", None, Some(IoReportReading { total_uj: 15_000, cpu_uj: 7_000, gpu_uj: 0, ane_uj: 0 })),
            ("the read after failed", Some(b), None),
        ];
        for (what, before, after) in cases {
            let e = ioreport_span(before, after, elapsed_ns);
            assert_eq!(e.provenance, Provenance::Estimator, "{what}: {e:?}");
            assert_eq!(e.measured_uj, None, "{what}: an estimate claimed a measurement: {e:?}");
            assert_eq!(e.uj(), model, "{what}: not the time×power figure for the span: {e:?}");
            e.check_provenance().expect("an estimate must be internally consistent");
        }
    }

    /// The grade the IOReport rung says it stamps is the grade its live spans
    /// carry, and it is the hardware grade. Driven through `detect_with`, so
    /// the rung is built on any macOS host whose counter opens, whatever this
    /// host's own liveness status.
    #[cfg(target_os = "macos")]
    #[test]
    fn the_ioreport_rung_stamps_the_hardware_grade() {
        let _hw = ioreport_hw_lock();
        let (meter, _) = Meter::detect_with(&Ladder { ioreport: &|| IoReportStatus::Live, ..Ladder::none() });
        if matches!(meter, Meter::IoReport(_)) {
            let live = ioreport_span(
                Some(IoReportReading { total_uj: 0, cpu_uj: 0, gpu_uj: 0, ane_uj: 0 }),
                Some(IoReportReading { total_uj: 2, cpu_uj: 1, gpu_uj: 0, ane_uj: 0 }),
                1,
            );
            assert_eq!(meter.provenance(), Provenance::HwShunt, "the IOReport rung is not graded as a hardware reading");
            assert_eq!(meter.provenance(), live.provenance, "the rung's grade is not the grade of its live spans");
        } else {
            assert!(ioreport::IoReport::open().is_none(), "a Live status did not build the rung, though the counter opens");
            assert!(matches!(meter, Meter::UncalibratedTimePower { .. }), "{meter:?}");
        }
    }

    /// `detect()` selects the IOReport rung on a `Live` status wherever the
    /// counter opens, and on no other status: the others fall to the
    /// time×power model at the documented default power.
    #[cfg(target_os = "macos")]
    #[test]
    fn only_a_live_status_selects_the_ioreport_rung() {
        let _hw = ioreport_hw_lock();
        use IoReportStatus as S;
        for status in [S::Unavailable, S::CpuRailAbsent, S::CpuRailFrozen] {
            let (meter, _) = Meter::detect_with(&Ladder { ioreport: &|| status, ..Ladder::none() });
            assert!(
                matches!(meter, Meter::UncalibratedTimePower { milliwatts: DEFAULT_ACTIVE_MILLIWATTS }),
                "status {status:?} gave {meter:?}"
            );
        }
        let opens = ioreport::IoReport::open().is_some();
        let (meter, _) = Meter::detect_with(&Ladder { ioreport: &|| S::Live, ..Ladder::none() });
        assert_eq!(
            matches!(meter, Meter::IoReport(_)),
            opens,
            "a Live status gave {meter:?} where the counter {} open",
            if opens { "does" } else { "does not" }
        );
    }

    /// A ladder on which every rung is declined and no counter opens: tests
    /// set the one rung they drive and take the rest from here.
    impl Ladder<'static> {
        fn none() -> Self {
            Ladder {
                rapl: &|| CounterStatus::Unavailable,
                open_rapl: &|| None,
                nvml: &|| CounterStatus::Unavailable,
                process_energy: &|| CounterStatus::Unavailable,
                #[cfg(target_os = "macos")]
                open_process_energy: &|| None,
                ioreport: &|| IoReportStatus::Unavailable,
            }
        }

        /// The ladder as `detect()` walks it on a host where every rung above
        /// IOReport is declined: this host's cached IOReport status, and the
        /// IOReport rung's own gate.
        #[cfg(target_os = "macos")]
        pub(crate) fn ioreport_only() -> Self {
            Ladder { ioreport: &ioreport_status, ..Ladder::none() }
        }
    }

    // ── The counter rungs' gate: RAPL and NVML ──────────────────────────────

    use std::cell::Cell;
    use std::time::Duration;

    /// The gate itself, on every status: only `Live` admits a counter rung,
    /// and a counter whose status does not admit it is not even opened.
    #[test]
    fn only_live_admits_a_counter_rung_and_nothing_else_is_opened() {
        use CounterStatus as S;
        assert!(admits_counter(S::Live), "Live does not admit the rung");
        for status in [S::Unavailable, S::Frozen, S::Implausible] {
            assert!(!admits_counter(status), "{status:?} admits the rung");
            let opened = Cell::new(0);
            let got = select(status, || {
                opened.set(opened.get() + 1);
                Some(())
            });
            assert_eq!((got, opened.get()), (None, 0), "{status:?}: the counter was opened");
        }
        let opened = Cell::new(0);
        let got = select(S::Live, || {
            opened.set(opened.get() + 1);
            Some(())
        });
        assert_eq!((got, opened.get()), (Some(()), 1), "Live did not open the counter once");
        assert_eq!(select(S::Live, || None::<()>), None, "a Live counter that does not open is not selected");
    }

    /// A probe's watch maps to its status: no probe and no interval are
    /// Unavailable, never Live.
    #[test]
    fn each_counter_probe_reports_its_status() {
        assert_eq!(liveness::status_of(None), CounterStatus::Unavailable);
        assert_eq!(liveness::status_of(Some(&liveness::Advances::default())), CounterStatus::Unavailable);
        let mut held = liveness::Advances::default();
        let rail = |v| liveness::every_rail(&[("intel-rapl:0".to_string(), v)]);
        for k in 0..6u32 {
            held.observe(rail(7), Duration::from_millis(100) * k);
        }
        assert_eq!(liveness::status_of(Some(&held)), CounterStatus::Frozen);
        let mut live = liveness::Advances::default();
        for k in 0..6u32 {
            live.observe(rail(i64::from(k)), Duration::from_millis(100) * k);
        }
        assert_eq!(liveness::status_of(Some(&live)), CounterStatus::Live);
        // Samples that carry no rail at all, past the 300 ms window: no rail
        // is not every rail advancing, so never Live.
        let mut empty = liveness::Advances::default();
        for k in 0..12u32 {
            empty.observe(Vec::new(), Duration::from_millis(100) * k);
        }
        assert!(!empty.is_live(), "a counter with no rail read as live over {:?}", empty.window);
        assert_eq!(liveness::status_of(Some(&empty)), CounterStatus::Frozen);
    }

    /// The plausibility rule on a GPU counter, with the readings of the RTX
    /// 4050 Laptop GPU on jetson-hub (driver 595.84, 65 W maximum limit):
    /// polled at the probe's 100 ms wait its counter ran at 58-305 W while the
    /// board drew 5-14 W, which is no count of the board's energy. A counter
    /// that tracks its board passes, a one-second draw lagging a load step by
    /// up to twice still passes, and a bound whose reading is missing is not
    /// applied.
    #[test]
    fn a_gpu_counter_must_count_no_faster_than_its_board_draws() {
        let w = Duration::from_millis(500);
        let p = |mj, draws: &[u32], ceil| plausible_gpu_counter(mj, w, draws, ceil);

        assert!(!p(59_750, &[12_970, 13_520], Some(65_000)).plausible(), "119.5 W against a 13 W draw");
        assert!(!p(22_000, &[10_400; 6], Some(65_000)).plausible(), "44 W against a 10.4 W draw");
        assert!(!p(60_000, &[], Some(65_000)).plausible(), "120 W on a 65 W board");
        assert!(!p(44_000, &[590_000, 10_300], Some(65_000)).plausible(), "88 W against a sane 10.3 W reading");
        assert!(!p(44_000, &[590_000], Some(65_000)).plausible(), "no usable draw reading at all");
        assert!(p(6_500, &[13_000, 13_500], Some(65_000)).plausible(), "13 W against a 13 W draw");
        assert!(p(150_000, &[280_000; 5], Some(700_000)).plausible(), "300 W against a 280 W draw");
        assert!(p(102_500, &[100_000; 5], Some(700_000)).plausible(), "205 W is 2 x 100 W + 5 W");
        assert!(!p(102_501, &[100_000; 5], Some(700_000)).plausible());
        assert!(p(48_750, &[], Some(65_000)).plausible(), "97.5 W is 1.5 x 65 W");
        assert!(!p(48_751, &[], Some(65_000)).plausible());
        assert!(p(1_000_000, &[], None).plausible(), "nothing to judge by");
    }

    /// The verdict carries the magnitude, which a `bool` discarded: a counter
    /// 1.1 times over a bound and one 20 times over were the same answer.
    #[test]
    fn the_verdict_says_which_bound_broke_and_by_how_much() {
        let w = Duration::from_millis(500);

        // The jetson-hub reading: 119.5 W against a mean 13.2 W draw on a 65 W
        // board. Both bounds break — 119.5 W is over the 97.5 W cap *and* over
        // 2 x 13.2 W + 5 W — and the power limit is reported, because it is the
        // harder of the two: a board cannot draw past its limit by
        // construction, while the mean-draw bound is soft (telemetry lags a
        // load step). Naming the harder bound is the more informative
        // diagnosis.
        match plausible_gpu_counter(59_750, w, &[12_970, 13_520], Some(65_000)) {
            GpuPlausibility::CounterOverRate { rate_mw, bound_mw, bound } => {
                assert_eq!(bound, GpuBound::PowerLimit);
                assert_eq!((rate_mw, bound_mw), (119_500, 97_500), "1.5 x 65 W");
            }
            other => panic!("expected an overrun, got {other:?}"),
        }

        // The mean-draw bound alone: 44 W sits inside the 97.5 W cap but is
        // well past 2 x 10.4 W + 5 W, and the verdict names that bound and the
        // factor a bool threw away.
        match plausible_gpu_counter(22_000, w, &[10_400; 6], Some(65_000)) {
            GpuPlausibility::CounterOverRate { rate_mw, bound_mw, bound } => {
                assert_eq!(bound, GpuBound::MeanDraw);
                assert_eq!((rate_mw, bound_mw), (44_000, 2 * 10_400 + 5_000));
                assert!(rate_mw < 97_500, "inside the power cap, so that bound did not bind");
                assert!(rate_mw / bound_mw >= 1, "{rate_mw} mW over a {bound_mw} mW bound");
            }
            other => panic!("expected a mean-draw overrun, got {other:?}"),
        }

        // With no draw readings the power limit is the only bound, and the
        // verdict says so rather than leaving the caller to guess which of the
        // two rejected it.
        match plausible_gpu_counter(60_000, w, &[], Some(65_000)) {
            GpuPlausibility::CounterOverRate { rate_mw, bound_mw, bound } => {
                assert_eq!(bound, GpuBound::PowerLimit);
                assert_eq!((rate_mw, bound_mw), (120_000, 97_500), "1.5 x 65 W");
            }
            other => panic!("expected a power-limit overrun, got {other:?}"),
        }

        // A marginal overrun is the same status and a different finding: one
        // milliwatt over, which is what the magnitude is for.
        match plausible_gpu_counter(48_751, w, &[], Some(65_000)) {
            GpuPlausibility::CounterOverRate { rate_mw, bound_mw, .. } => {
                assert_eq!(rate_mw - bound_mw, 2, "just over the cap, not 20 times over");
            }
            other => panic!("expected an overrun, got {other:?}"),
        }

        // And a pass carries the rate too, so a figure near a bound is visible
        // before it crosses one.
        assert_eq!(
            plausible_gpu_counter(6_500, w, &[13_000, 13_500], Some(65_000)),
            GpuPlausibility::Plausible { rate_mw: 13_000 }
        );
    }

    /// A board reporting past its own power limit leaves no yardstick. That is
    /// an indeterminate, not a finding about the counter — the old code called
    /// it `Implausible`, whose doc then asserted "it is not counting the board's
    /// energy", a conclusion this case does not support.
    #[test]
    fn an_unusable_board_reading_is_an_indeterminate_not_an_indictment() {
        let w = Duration::from_millis(500);
        // A spike beside a sane reading drops the spike, not the judgement.
        // The sane 10.3 W reading still bounds the counter, so an 88 W counter
        // is an overrun against 2 x 10.3 W + 5 W — not an indeterminate. The
        // hardware test on jetson-hub is what forced this: one spike among
        // otherwise sane 14.8 W samples used to turn a counter running
        // persistently at 4-30x the board's draw into "cannot judge".
        match plausible_gpu_counter(44_000, w, &[590_000, 10_300], Some(65_000)) {
            GpuPlausibility::CounterOverRate { rate_mw, bound_mw, bound } => {
                assert_eq!(bound, GpuBound::MeanDraw);
                assert_eq!((rate_mw, bound_mw), (88_000, 2 * 10_300 + 5_000));
            }
            other => panic!("one bad sample voided the bracket: {other:?}"),
        }

        // Dropping the spike also keeps the mean honest. Summing every reading
        // put the mean at 300 W and the bound at 605 W, which would have passed
        // an 88 W counter that the sane reading alone refuses.
        let poisoned_mean = (590_000 + 10_300) / 2;
        assert!(
            44_000u64 * 2 < (2 * poisoned_mean + 5_000),
            "premise: the spike-inflated mean would have admitted this counter"
        );

        // Only when nothing usable is left is there no yardstick at all.
        match plausible_gpu_counter(44_000, w, &[590_000], Some(65_000)) {
            GpuPlausibility::BoardTelemetryUnusable { draw_mw, limit_mw } => {
                assert_eq!((draw_mw, limit_mw), (590_000, 97_500));
            }
            other => panic!("expected an indeterminate, got {other:?}"),
        }
        assert!(!plausible_gpu_counter(44_000, w, &[590_000], Some(65_000)).plausible());

        // And the power limit still binds first: it is a static spec value, not
        // a reading, so a broken draw sample cannot excuse a counter that
        // overran the board's limit outright.
        match plausible_gpu_counter(500_000, w, &[590_000], Some(65_000)) {
            GpuPlausibility::CounterOverRate { bound, bound_mw, .. } => {
                assert_eq!((bound, bound_mw), (GpuBound::PowerLimit, 97_500));
            }
            other => panic!("expected a power-limit overrun, got {other:?}"),
        }
    }

    /// **The bound that was missing: a counter reading LOW.** It still
    /// advances, so liveness calls it live; graded `HwShunt` it would spend a
    /// ceiling it is not measuring. Figures are the jetson-hub RTX 4050's own.
    #[test]
    fn a_gpu_counter_must_count_no_slower_than_its_board_draws() {
        let w = Duration::from_millis(500);
        // floor = (14_800 - 5_000) / 4 = 2_450 mW.
        assert_eq!(
            plausible_gpu_counter(250, w, &[14_800, 14_800], Some(65_000)),
            GpuPlausibility::CounterUnderRate { rate_mw: 500, floor_mw: 2_450, mean_draw_mw: 14_800 },
            "0.5 W counted against a 14.8 W draw"
        );
        assert!(plausible_gpu_counter(1_300, w, &[14_800, 14_800], Some(65_000)).plausible(), "lagging");
        assert!(plausible_gpu_counter(1_225, w, &[14_800, 14_800], Some(65_000)).plausible(), "at the floor");
        // An idle board makes no finding, and nor does a board with no reading.
        for mean in [0u32, 1_000, 5_000] {
            assert!(plausible_gpu_counter(0, w, &[mean, mean], Some(65_000)).plausible(), "{mean} mW");
        }
        assert!(plausible_gpu_counter(0, w, &[], Some(65_000)).plausible());

        // The wiring, not only the verdict: a live counter at 0.1 W beside a
        // 14.8 W board is `Implausible`, and beside a 2 W board stays `Live`.
        let rail = |v| liveness::every_rail(&[("nvml device 0 total energy".to_string(), v)]);
        let mut live = liveness::Advances::default();
        let t0 = Instant::now();
        let watch = |draw| {
            let mut g = GpuWatch { ceiling_mw: Some(65_000), ..GpuWatch::default() };
            for k in 0..6u32 {
                // 10 mJ every 100 ms: 100 mW.
                g.saw(Some(1_000_000 + 10 * u64::from(k)), Some(draw), t0 + Duration::from_millis(100) * k);
            }
            g
        };
        for k in 0..6u32 {
            live.observe(rail(1_000_000 + 10 * i64::from(k)), Duration::from_millis(100) * k);
        }
        assert_eq!(liveness::status_of(Some(&live)), CounterStatus::Live);
        assert_eq!(nvml_status_of(Some(&live), &watch(14_800)), CounterStatus::Implausible);
        assert_eq!(nvml_status_of(Some(&live), &watch(2_000)), CounterStatus::Live);
    }

    /// The NVML probe's status: a live counter that ran past its board is
    /// `Implausible`; one that tracked it stays `Live`; a counter that was not
    /// live keeps its status, whatever its board drew.
    #[test]
    fn a_live_gpu_counter_past_its_board_is_implausible() {
        let rail = |v| liveness::every_rail(&[("nvml device 0 total energy".to_string(), v)]);
        let (mut live, mut held) = (liveness::Advances::default(), liveness::Advances::default());
        let t0 = Instant::now();
        let mut gpu = GpuWatch { ceiling_mw: Some(65_000), ..GpuWatch::default() };
        for k in 0..6u32 {
            // 12 J every 100 ms: 120 W.
            live.observe(rail(1_000_000 + 12_000 * i64::from(k)), Duration::from_millis(100) * k);
            held.observe(rail(1_000_000), Duration::from_millis(100) * k);
            gpu.saw(Some(1_000_000 + 12_000 * u64::from(k)), Some(13_000), t0 + Duration::from_millis(100) * k);
        }
        assert_eq!(liveness::status_of(Some(&live)), CounterStatus::Live);
        assert_eq!(nvml_status_of(Some(&live), &gpu), CounterStatus::Implausible);
        assert_eq!(nvml_status_of(Some(&held), &gpu), CounterStatus::Frozen);
        assert_eq!(nvml_status_of(None, &gpu), CounterStatus::Unavailable);
        let mut big = GpuWatch { ceiling_mw: Some(700_000), ..GpuWatch::default() };
        for k in 0..6u32 {
            big.saw(Some(1_000_000 + 12_000 * u64::from(k)), Some(115_000), t0 + Duration::from_millis(100) * k);
        }
        assert_eq!(nvml_status_of(Some(&live), &big), CounterStatus::Live, "120 W against a 115 W draw on a 700 W board");
        assert_eq!(nvml_status_of(Some(&live), &GpuWatch::default()), CounterStatus::Live, "nothing to judge by");

        // One spike among sane readings is still `Implausible`: the spike is
        // dropped and the sane readings bound the counter, which overran them.
        // This is what the jetson-hub hardware test demanded — the first shape
        // of this code reported the indeterminate here and so disagreed with
        // the oracle on a counter whose overrun is persistent and repeatable.
        let mut spiking = GpuWatch { ceiling_mw: Some(65_000), ..GpuWatch::default() };
        for k in 0..6u32 {
            let draw = if k == 0 { 590_000 } else { 13_000 };
            spiking.saw(
                Some(1_000_000 + 12_000 * u64::from(k)),
                Some(draw),
                t0 + Duration::from_millis(100) * k,
            );
        }
        assert_eq!(nvml_status_of(Some(&live), &spiking), CounterStatus::Implausible);

        // `Unjudgeable` is for a bracket with no usable reading left at all: a
        // board spiking through every sample offers no yardstick. A 60 W
        // counter on a 65 W board is inside the power cap, so nothing else
        // can judge it either.
        let mut all_spikes = GpuWatch { ceiling_mw: Some(65_000), ..GpuWatch::default() };
        for k in 0..6u32 {
            all_spikes.saw(
                Some(1_000_000 + 6_000 * u64::from(k)),
                Some(590_000),
                t0 + Duration::from_millis(100) * k,
            );
        }
        assert_eq!(nvml_status_of(Some(&live), &all_spikes), CounterStatus::Unjudgeable);
        assert!(!admits_counter(CounterStatus::Unjudgeable), "unjudgeable is not admissible");
    }

    /// The tests' interval for a CPU-counter probe: a 25 ms tick and a short
    /// read.
    const COUNTER_STEP: Duration = Duration::from_millis(31);

    /// One counter probe through [`liveness::probe`], the function the RAPL
    /// and NVML probes run, on a scripted counter and a scripted clock: sample
    /// `i` is `script(i)` (`None`: the read failed), and each tick moves the
    /// clock on by `step`. Returns the status, the watch, how many samples
    /// were read and how many ticks ran.
    fn scripted_counter(
        script: impl Fn(usize) -> Option<Vec<(String, i64)>>,
        step: Duration,
    ) -> (CounterStatus, Option<liveness::Advances>, usize, usize) {
        let (base, clock, reads, ticks) = (std::time::Instant::now(), Cell::new(Duration::ZERO), Cell::new(0), Cell::new(0));
        let watch = liveness::probe(
            || Some(()),
            |_| {
                let i = reads.get();
                reads.set(i + 1);
                script(i).map(|named| liveness::every_rail(&named))
            },
            || {
                clock.set(clock.get() + step);
                ticks.set(ticks.get() + 1);
            },
            || base + clock.get(),
            liveness::BUDGET,
        );
        (liveness::status_of(watch.as_ref()), watch, reads.get(), ticks.get())
    }

    /// The budget starts once the counter is open, so a slow open costs the
    /// probe none of it: an open of 950 ms, then a rail advancing at every
    /// sample, is live exactly where it is with an open that takes no time.
    /// With the budget running from before the open, the probe would stop at
    /// its fifth interval, with 155 ms of intervals, and call a live rail
    /// frozen.
    #[test]
    fn the_budget_starts_once_the_counter_is_open() {
        let (base, clock, reads) = (std::time::Instant::now(), Cell::new(Duration::ZERO), Cell::new(0));
        let watch = liveness::probe(
            || {
                clock.set(Duration::from_millis(950));
                Some(())
            },
            |_| {
                reads.set(reads.get() + 1);
                Some(liveness::every_rail(&[("intel-rapl:0".to_string(), 1_000 + 13 * reads.get() as i64)]))
            },
            || clock.set(clock.get() + COUNTER_STEP),
            || base + clock.get(),
            liveness::BUDGET,
        );
        let w = watch.expect("the scripted counter opened");
        assert!(w.is_live(), "{w:?}");
        assert_eq!((w.intervals, reads.get()), (10, 11));
    }

    /// A RAPL-shaped sample: two packages' `energy_uj`, in µJ.
    fn packages(p0: i64, p1: i64) -> Option<Vec<(String, i64)>> {
        Some(vec![("intel-rapl:0".to_string(), p0), ("intel-rapl:1".to_string(), p1)])
    }

    /// The RAPL gate on scripted package counters, through the probe the RAPL
    /// rung runs. Live only when every package keeps advancing; one package
    /// advancing beside one that holds, a counter that holds (a frozen or
    /// virtualised powercap tree), one republished in a lump or two steps,
    /// packages stepping in turn, and a wrap are all Frozen; a tree that does
    /// not open is Unavailable without a sample or a tick.
    #[test]
    fn the_rapl_gate_on_scripted_package_counters() {
        let ms = Duration::from_millis;
        // Live: package 0 rises ~0.4 J every interval under the burn, package 1
        // idles but rises too. Live at the tenth interval, when the window
        // first spans 300 ms (310 ms), and the probe stops there.
        let (status, w, reads, ticks) =
            scripted_counter(|i| packages(1_000_000 + 400_000 * i as i64, 9_000_000 + 30_000 * i as i64), COUNTER_STEP);
        let w = w.expect("an opened counter was not watched");
        assert_eq!(status, CounterStatus::Live, "{:?}", w.rails);
        assert_eq!((w.intervals, reads, ticks, w.window), (10, 11, 10, ms(310)), "a live counter must stop the probe at once");
        // Frozen: package 0 rises at every interval, package 1 holds. A span's
        // figure sums both, so it would leave package 1's energy out.
        let (status, w, reads, _) =
            scripted_counter(|i| packages(1_000_000 + 400_000 * i as i64, 9_000_000), COUNTER_STEP);
        let w = w.unwrap();
        assert_eq!(status, CounterStatus::Frozen, "one live package beside a held one read as live: {:?}", w.rails);
        assert_eq!((w.intervals, reads), (33, 34));
        assert_eq!(w.rails.iter().map(|(_, n)| *n).collect::<Vec<_>>(), [33, 0], "{:?}", w.rails);
        // Frozen: a counter that holds, after the whole budget (33 intervals).
        let (status, w, reads, _) = scripted_counter(|_| packages(1_000_000, 9_000_000), COUNTER_STEP);
        let w = w.unwrap();
        assert_eq!((status, w.intervals, reads), (CounterStatus::Frozen, 33, 34), "{:?}", w.rails);
        // Frozen: every package republished once, in one lump.
        let lump = |i: usize| if i < 3 { 0 } else { 1_300_000_000 };
        let (status, w, _, _) = scripted_counter(|i| packages(lump(i), 9_000_000 + lump(i)), COUNTER_STEP);
        assert_eq!(status, CounterStatus::Frozen, "one lump read as live: {:?}", w.unwrap().rails);
        // Frozen: a lump in two steps, and in five quick steps at the start.
        for steps in [2usize, 5] {
            let (status, w, _, _) =
                scripted_counter(|i| packages(1_000_000 + 61_000_000 * i.min(steps) as i64, 9_000_000), COUNTER_STEP);
            assert_eq!(status, CounterStatus::Frozen, "a lump in {steps} steps read as live: {:?}", w.unwrap().rails);
        }
        // Frozen: the packages advance in turn, each in half the intervals.
        // Summed, they would be one counter advancing in every interval.
        let (status, w, _, _) =
            scripted_counter(|i| packages(1_000 * i.div_ceil(2) as i64, 9_000 + 1_000 * (i / 2) as i64), COUNTER_STEP);
        let w = w.unwrap();
        assert_eq!(status, CounterStatus::Frozen, "packages in turn read as live: {:?}", w.rails);
        assert!(w.rails.iter().all(|(_, n)| *n <= w.intervals.div_ceil(2)), "{:?}", w.rails);
        // A wrap is a fall, not an advance: rising, then wrapping at every
        // other sample, is never 80%.
        let (status, _, _, _) =
            scripted_counter(|i| packages(if i % 2 == 0 { 262_143_000 } else { 100 }, 9_000_000), COUNTER_STEP);
        assert_eq!(status, CounterStatus::Frozen, "a counter wrapping at every other sample read as live");
        // Unavailable: every read fails, to the five-budget cap.
        let (status, w, reads, _) = scripted_counter(|_| None, COUNTER_STEP);
        assert_eq!((status, w.unwrap().intervals), (CounterStatus::Unavailable, 0));
        assert!(reads > 100, "the probe gave up on failing reads after {reads}");
        // Unavailable: no tree, no sample, no tick.
        let (reads, ticks) = (Cell::new(0), Cell::new(0));
        let watch = liveness::probe(
            || None::<()>,
            |_| {
                reads.set(reads.get() + 1);
                None
            },
            || ticks.set(ticks.get() + 1),
            std::time::Instant::now,
            liveness::BUDGET,
        );
        assert!(watch.is_none());
        assert_eq!((liveness::status_of(watch.as_ref()), reads.get(), ticks.get()), (CounterStatus::Unavailable, 0, 0));
    }

    /// A rail that advances at every sample, folded into `a` with the gaps
    /// between samples `gaps` gives.
    fn advancing(mut a: liveness::Advances, gaps: impl IntoIterator<Item = u64>) -> liveness::Advances {
        let rail = |v: i64| liveness::every_rail(&[("rail".to_string(), v)]);
        let (mut at, mut raw) = (Duration::ZERO, 1_000);
        a.observe(rail(raw), at);
        for gap in gaps {
            (at, raw) = (at + Duration::from_millis(gap), raw + 13);
            a.observe(rail(raw), at);
        }
        a
    }

    /// A rail that steps twice a second advances in every interval once
    /// sampling has slowed to 500 ms, and the probe asked for 25 ms. So an
    /// interval past [`liveness::MAX_INTERVAL_TICKS`] ticks is no evidence,
    /// whatever the rail did in it, for the cases measured on an M3 Ultra.
    #[test]
    fn an_interval_past_the_cap_is_no_evidence() {
        for step in [500, 800] {
            let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), [step; 40]);
            assert!(!a.is_live(), "{step} ms intervals of a 25 ms tick proved a rail live: {a:?}");
            assert_eq!((a.intervals, a.counted, liveness::status_of(Some(&a))), (40, 0, CounterStatus::Frozen));
        }
        let cap = (liveness::PROBE_TICK * liveness::MAX_INTERVAL_TICKS).as_millis() as u64;
        assert!(advancing(liveness::Advances::asking(liveness::PROBE_TICK), [cap; 6]).is_live(), "{cap} ms counts");
        assert!(!advancing(liveness::Advances::asking(liveness::PROBE_TICK), [cap + 1; 40]).is_live(), "{} ms does not", cap + 1);
    }

    /// A live rail stays Live under contention: its intervals wander around the
    /// tick, and some are held far past it. Those are evidence neither way.
    #[test]
    fn a_live_rail_is_live_though_contention_stretches_some_intervals() {
        let jitter = [31, 44, 38, 92, 31, 60, 400, 33, 75, 31, 900, 48, 100, 31, 36];
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), jitter.iter().copied().cycle().take(30));
        assert!(a.is_live(), "a rail advancing in every interval, some held long, was not Live: {a:?}");
        assert!(a.counted < a.intervals, "the script holds some intervals past the cap: {a:?}");
    }

    /// Only time that counted fills the window: a refresh's five quick steps
    /// beside one long interval span 550 ms of wall time, and are still a burst.
    #[test]
    fn a_long_interval_cannot_fill_the_window_for_a_burst() {
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), [30, 30, 400, 30, 30, 30]);
        assert!(!a.is_live(), "a burst beside one long interval was called Live: {a:?}");
        assert_eq!((a.intervals, a.counted, a.counted_for), (6, 5, Duration::from_millis(150)));
        assert_eq!(a.window, Duration::from_millis(550), "the wall time is still reported");
    }

    /// The cap is the tick the probe asked for, not a figure of its own: an
    /// interval a 100 ms probe may count is one a 25 ms probe may not.
    #[test]
    fn the_cap_follows_the_tick_the_probe_asked_for() {
        let slow = Duration::from_millis(100);
        assert!(advancing(liveness::Advances::asking(slow), [300; 8]).is_live(), "near a 100 ms tick");
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), [300; 8]);
        assert!(!a.is_live() && a.counted == 0, "not near a 25 ms tick: {a:?}");
        assert!(!advancing(liveness::Advances::asking(slow), [301; 8]).is_live(), "past three 100 ms ticks");
    }

    /// A vendor counter has no cap: it publishes at least as often as its probe
    /// ticks, so an interval a contended host stretched is still its advance, and
    /// it stays Live where IOReport's rails decline ([`liveness::probe`]).
    #[test]
    fn a_vendor_counter_has_no_cap() {
        let a = advancing(liveness::Advances::asking(Duration::MAX), [600; 8]);
        assert!(a.is_live(), "{a:?}");
        assert_eq!(a.counted, a.intervals);
    }

    /// The rule hands over what it held, for the record a cached status
    /// keeps: each rail's advances, the intervals observed and how many
    /// counted, the counted time, the window and the longest interval. And the
    /// record's own rule agrees with the rule's verdict, Live or not, held
    /// intervals or none.
    #[test]
    fn the_rule_hands_over_its_evidence() {
        let ms = Duration::from_millis;
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), [30, 30, 400, 30, 30, 30]);
        let e = a.evidence();
        assert_eq!(
            e,
            liveness::ProbeEvidence {
                advances: vec![("rail".to_string(), 0, 5)],
                intervals: 6,
                counted: 5,
                counted_for: ms(150),
                window: ms(550),
                longest_interval: ms(400),
            }
        );
        assert_eq!((a.is_live(), e.rule_holds()), (false, false), "a burst beside one long interval");
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), [31; 10]);
        assert_eq!((a.is_live(), a.evidence().rule_holds()), (true, true), "a rail advancing at every 31 ms sample");
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), [500; 40]);
        assert_eq!((a.is_live(), a.evidence().rule_holds()), (false, false), "a rail seen only at 500 ms");
        assert_eq!((a.evidence().counted, a.evidence().longest_interval), (0, ms(500)));
        let held = [31, 44, 38, 92, 31, 60, 400, 33, 75, 31, 900, 48, 100, 31, 36];
        let a = advancing(liveness::Advances::asking(liveness::PROBE_TICK), held.iter().copied().cycle().take(30));
        assert_eq!((a.is_live(), a.evidence().rule_holds()), (true, true), "a live rail with some intervals held");
        assert_eq!(a.evidence().longest_interval, ms(900));
        assert!(!liveness::Advances::asking(liveness::PROBE_TICK).evidence().rule_holds(), "no rail is no evidence");
    }

    /// The NVML gate's rule on scripted device counters, in mJ, sampled every
    /// 100 ms as the NVML probe waits. A counter the driver refreshes at least
    /// every 100 ms advances in every interval and is Live after five (500
    /// ms); one refreshed every fourth interval advances in a quarter of them
    /// and is declined; one that holds is Frozen.
    #[test]
    fn the_nvml_gate_on_scripted_device_counters() {
        let step = Duration::from_millis(100);
        let device = |mj: i64| Some(vec![("nvml device 0 total energy".to_string(), mj)]);
        let (status, w, reads, _) = scripted_counter(|i| device(48_000_000 + 2_000 * i as i64), step);
        let w = w.unwrap();
        assert_eq!((status, w.intervals, reads, w.window), (CounterStatus::Live, 5, 6, Duration::from_millis(500)));
        let (status, w, _, _) = scripted_counter(|i| device(48_000_000 + 8_000 * (i / 4) as i64), step);
        assert_eq!(status, CounterStatus::Frozen, "a counter advancing in 1 of 4 intervals: {:?}", w.unwrap().rails);
        let (status, _, _, _) = scripted_counter(|_| device(48_000_000), step);
        assert_eq!(status, CounterStatus::Frozen);
    }

    /// A fake powercap tree in the OS temp directory, removed when dropped:
    /// zone directories each with a `name`, an `energy_uj` and a
    /// `max_energy_range_uj`, as sysfs lays them out.
    struct FakePowercap {
        root: std::path::PathBuf,
    }

    /// One zone of a [`FakePowercap`]: its directory, its `name` file (`None`:
    /// no such file), its `energy_uj`, and its `max_energy_range_uj` (`None`:
    /// no such file).
    type FakeZone<'a> = (&'a str, Option<&'a str>, &'a str, Option<&'a str>);

    impl FakePowercap {
        /// `intel-rapl:N` zones named `package-N`, one per value, wrapping at
        /// 262,143,328,850 µJ, and an `intel-rapl:0:0` `core` subzone the
        /// reader must skip.
        fn new(packages: &[&str]) -> Self {
            let dirs: Vec<(String, String)> =
                (0..packages.len()).map(|k| (format!("intel-rapl:{k}"), format!("package-{k}"))).collect();
            let mut zones: Vec<FakeZone<'_>> = dirs
                .iter()
                .zip(packages)
                .map(|((dir, name), value)| (dir.as_str(), Some(name.as_str()), *value, Some("262143328850")))
                .collect();
            zones.push(("intel-rapl:0:0", Some("core"), "5", Some("262143328850")));
            Self::with_zones(&zones)
        }

        /// A tree of exactly these zones.
        fn with_zones(zones: &[FakeZone<'_>]) -> Self {
            static N: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
            let n = N.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
            let root = std::env::temp_dir().join(format!("jcp-energy-powercap-{}-{n}", std::process::id()));
            // A test process that was killed never dropped its trees, and a
            // later one with the same pid would build on top of them.
            let _ = std::fs::remove_dir_all(&root);
            let fake = FakePowercap { root };
            std::fs::create_dir_all(&fake.root).expect("create a fake powercap tree");
            for (dir, name, value, range) in zones {
                let zone = fake.root.join(dir);
                std::fs::create_dir_all(&zone).expect("create a fake zone");
                if let Some(name) = name {
                    std::fs::write(zone.join("name"), format!("{name}\n")).unwrap();
                }
                if let Some(range) = range {
                    std::fs::write(zone.join("max_energy_range_uj"), format!("{range}\n")).unwrap();
                }
                fake.write_zone(dir, value);
            }
            fake
        }

        /// Replace package `k`'s `energy_uj` (zone `intel-rapl:k`).
        fn write(&self, k: usize, value: &str) {
            self.write_zone(&format!("intel-rapl:{k}"), value);
        }

        /// Replace zone `dir`'s `energy_uj`, atomically, so a reader sees the
        /// old value or the new one.
        fn write_zone(&self, dir: &str, value: &str) {
            let dir = self.root.join(dir);
            std::fs::write(dir.join("energy_uj.tmp"), format!("{value}\n")).unwrap();
            std::fs::rename(dir.join("energy_uj.tmp"), dir.join("energy_uj")).unwrap();
        }
    }

    impl Drop for FakePowercap {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.root);
        }
    }

    /// RAPL's probe — its opener on `tree`, its sampler, the CPU-burning tick,
    /// the real clock, one budget — with `advance` run after each tick: the
    /// fake hardware's rise for that interval. These tests once advanced the
    /// zones from another thread on a 2 ms timer instead, which a loaded CI
    /// host starved while the tick burned CPU: intervals went flat, and two
    /// live packages read Frozen. On the probe's own thread the rise lands in
    /// every interval, so the verdict is the rule's, not the scheduler's.
    fn rapl_status_ticking(tree: &FakePowercap, mut advance: impl FnMut()) -> CounterStatus {
        crate::liveness::status_of(
            crate::liveness::probe(
                || Rapl::open_in(&tree.root),
                Rapl::liveness_sample,
                || {
                    crate::liveness::burn_tick();
                    advance();
                },
                std::time::Instant::now,
                crate::liveness::BUDGET,
            )
            .as_ref(),
        )
    }

    /// The real RAPL probe — the real reader on files, the CPU-burning tick,
    /// the real clock, one budget — on fake powercap trees. A tree whose
    /// counters hold is Frozen; one whose two packages advance 4 mJ every tick
    /// is Live; one where package 0 advances alone, package 1 holding, is
    /// Frozen; no tree, or a tree whose `energy_uj` is not a number, is
    /// Unavailable, as RAPL was declined before.
    #[test]
    fn the_rapl_probe_on_fake_powercap_trees() {
        /// The probe on `tree`, the packages in `advancing` rising by 4 mJ at
        /// every tick ([`rapl_status_ticking`]).
        fn probe_while_advancing(tree: &FakePowercap, advancing: &[usize]) -> CounterStatus {
            let mut uj: u64 = 1_000;
            let started = std::time::Instant::now();
            let status = rapl_status_ticking(tree, || {
                uj += 4_000;
                for &k in advancing {
                    tree.write(k, &uj.to_string());
                }
            });
            eprintln!(
                "rapl probe: a fake tree with packages {advancing:?} advancing every tick -> {status:?} in {:?}",
                started.elapsed()
            );
            status
        }
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        let frozen = FakePowercap::new(&["73176481", "1000"]);
        let started = std::time::Instant::now();
        let status = rapl_status_on(|| Rapl::open_in(&frozen.root));
        eprintln!("rapl probe: a fake tree that holds -> {status:?} in {:?}", started.elapsed());
        assert_eq!(status, CounterStatus::Frozen, "a powercap tree whose counters hold was not declined");

        let live = FakePowercap::new(&["1000", "1000"]);
        let status = probe_while_advancing(&live, &[0, 1]);
        assert_eq!(status, CounterStatus::Live, "two packages advancing every 2 ms were not live");
        let half = FakePowercap::new(&["1000", "1000"]);
        assert_eq!(
            probe_while_advancing(&half, &[0]),
            CounterStatus::Frozen,
            "package 0 advancing beside a held package 1 was not declined"
        );

        let gone = FakePowercap::new(&[]);
        assert_eq!(rapl_status_on(|| Rapl::open_in(&gone.root.join("absent"))), CounterStatus::Unavailable);
        let garbled = FakePowercap::new(&["not a number"]);
        assert!(Rapl::open_in(&garbled.root).is_none(), "a package whose energy_uj does not parse was opened");
        assert_eq!(rapl_status_on(|| Rapl::open_in(&garbled.root)), CounterStatus::Unavailable);
    }

    /// `detect()` selects the RAPL rung on a `Live` status and on no other,
    /// and opens no counter it does not select. Driven with a counter on a
    /// fake tree, so it runs on hosts with no RAPL.
    #[test]
    fn only_a_live_status_selects_the_rapl_rung() {
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        let fake = FakePowercap::new(&["1000"]);
        for status in [
            CounterStatus::Unavailable,
            CounterStatus::Frozen,
            CounterStatus::Implausible,
            CounterStatus::Unjudgeable,
            CounterStatus::Live,
        ] {
            let opened = Cell::new(0);
            let open = || {
                opened.set(opened.get() + 1);
                Rapl::open_in(&fake.root)
            };
            let (meter, _) = Meter::detect_with(&Ladder { rapl: &|| status, open_rapl: &open, ..Ladder::none() });
            let live = status == CounterStatus::Live;
            assert_eq!(matches!(meter, Meter::Rapl(_)), live, "status {status:?} gave {meter:?}");
            assert_eq!(opened.get(), usize::from(live), "status {status:?} opened the counter {} times", opened.get());
            if !live {
                assert!(matches!(meter, Meter::UncalibratedTimePower { milliwatts: DEFAULT_ACTIVE_MILLIWATTS }), "{meter:?}");
            }
        }
    }

    /// The RAPL rung's spans, through `measure` itself on a fake tree. A span
    /// over which a package counter rose is a reading of the rise, `HwShunt`
    /// and whole, wraparound-corrected; a span over which no counter rose is
    /// the default-power estimate, not a hardware reading of zero.
    #[test]
    fn a_rapl_span_is_a_reading_only_if_a_counter_rose() {
        let fake = FakePowercap::new(&["1000", "50"]);
        let meter = Meter::Rapl(Rapl::open_in(&fake.root).expect("the fake tree opens"));
        assert_eq!(meter.provenance(), Provenance::HwShunt);
        let (_, e) = meter.measure(|| fake.write(0, "5500"));
        assert_eq!((e.provenance, e.measured_uj, e.is_whole()), (Provenance::HwShunt, Some(4_500), true), "{e:?}");
        e.check_provenance().unwrap();
        // Package 1 wraps at 262,143,328,850 µJ: 262,143,328,000 -> 150.
        fake.write(1, "262143328000");
        let (_, e) = meter.measure(|| fake.write(1, "150"));
        assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(1_000)), "{e:?}");
        let ((), held) = meter.measure(|| std::thread::sleep(Duration::from_millis(2)));
        assert_eq!((held.provenance, held.measured_uj), (Provenance::Estimator, None), "{held:?}");
        assert!(held.uj() >= time_power_uj(2_000_000, DEFAULT_ACTIVE_MILLIWATTS), "{held:?}");
        held.check_provenance().unwrap();
    }

    /// The figure a counter rung gives a span: a reading only when the
    /// counter rose; a rise of zero and a failed read are the default-power
    /// estimate, `Estimator`.
    #[test]
    fn a_counter_span_is_a_reading_only_when_the_counter_rose() {
        let model = time_power_uj(3_000_000, DEFAULT_ACTIVE_MILLIWATTS);
        assert_eq!(counter_span(Some(7), 3_000_000, Energy::measured), Energy::measured(7));
        for rose in [Some(0), None] {
            let e = counter_span(rose, 3_000_000, Energy::measured);
            assert_eq!((e.provenance, e.measured_uj, e.uj()), (Provenance::Estimator, None, model), "{rose:?}: {e:?}");
        }
    }

    /// An NVML span over which the GPU counter advanced is a hardware reading
    /// of PART of the work: `HwShunt`, `Coverage::Partial`, the counter's
    /// rise as the measured figure — never a whole-task figure, since the
    /// CPU's share is unmetered. A counter that held, fell (a driver reload)
    /// or failed to read is the whole-task default-power estimate.
    #[test]
    fn an_nvml_span_is_a_partial_reading_of_the_work() {
        let e = nvml_span(Some(48_000_000_000), Some(48_000_350_000), 10_000_000);
        assert_eq!(e.provenance, Provenance::HwShunt, "{e:?}");
        assert_eq!(e.measured_uj, Some(350_000), "{e:?}");
        assert_eq!(e.coverage, jcp_schema::Coverage::Partial, "a GPU-only figure claimed the whole task: {e:?}");
        assert!(!e.is_whole());
        e.check_provenance().unwrap();
        let model = time_power_uj(10_000_000, DEFAULT_ACTIVE_MILLIWATTS);
        let b = Some(48_000_000_000);
        for (what, before, after) in [("held", b, b), ("fell", b, Some(1_000)), ("before failed", None, b), ("after failed", b, None)] {
            let e = nvml_span(before, after, 10_000_000);
            assert_eq!((e.provenance, e.measured_uj, e.uj()), (Provenance::Estimator, None, model), "{what}: {e:?}");
            assert!(e.is_whole(), "{what}: the default-power estimate is a whole-task figure: {e:?}");
        }
    }

    // ── The per-process CPU energy rung ─────────────────────────────────────

    /// `struct rusage_info_v6`, transcribed field by field from
    /// `<sys/resource.h>` in the macOS 27 SDK: an independent statement of the
    /// layout, for the tests to hold the implementation's offsets to and for
    /// their own oracle to read through.
    #[allow(dead_code)]
    #[repr(C)]
    struct RusageInfoV6Mirror {
        ri_uuid: [u8; 16],
        ri_user_time: u64,
        ri_system_time: u64,
        ri_pkg_idle_wkups: u64,
        ri_interrupt_wkups: u64,
        ri_pageins: u64,
        ri_wired_size: u64,
        ri_resident_size: u64,
        ri_phys_footprint: u64,
        ri_proc_start_abstime: u64,
        ri_proc_exit_abstime: u64,
        ri_child_user_time: u64,
        ri_child_system_time: u64,
        ri_child_pkg_idle_wkups: u64,
        ri_child_interrupt_wkups: u64,
        ri_child_pageins: u64,
        ri_child_elapsed_abstime: u64,
        ri_diskio_bytesread: u64,
        ri_diskio_byteswritten: u64,
        ri_cpu_time_qos_default: u64,
        ri_cpu_time_qos_maintenance: u64,
        ri_cpu_time_qos_background: u64,
        ri_cpu_time_qos_utility: u64,
        ri_cpu_time_qos_legacy: u64,
        ri_cpu_time_qos_user_initiated: u64,
        ri_cpu_time_qos_user_interactive: u64,
        ri_billed_system_time: u64,
        ri_serviced_system_time: u64,
        ri_logical_writes: u64,
        ri_lifetime_max_phys_footprint: u64,
        ri_instructions: u64,
        ri_cycles: u64,
        ri_billed_energy: u64,
        ri_serviced_energy: u64,
        ri_interval_max_phys_footprint: u64,
        ri_runnable_time: u64,
        ri_flags: u64,
        ri_user_ptime: u64,
        ri_system_ptime: u64,
        ri_pinstructions: u64,
        ri_pcycles: u64,
        ri_energy_nj: u64,
        ri_penergy_nj: u64,
        ri_secure_time_in_system: u64,
        ri_secure_ptime_in_system: u64,
        ri_neural_footprint: u64,
        ri_lifetime_max_neural_footprint: u64,
        ri_interval_max_neural_footprint: u64,
        ri_conclave_footprint: u64,
        ri_page_wait_time_mach: u64,
        ri_page_cache_hits: u64,
        ri_reserved: [u64; 6],
    }

    /// The decoder's layout is the SDK's, two ways: the literals the C
    /// compiler printed for `sizeof` and `offsetof` on the header (the same
    /// in the macOS 26, 26.5 and 27 SDKs; the child-time offsets printed
    /// against the 27 SDK), and `offset_of!` on the field-by-field
    /// transcription of the 27 SDK's.
    #[test]
    fn the_rusage_v6_layout_is_the_sdks() {
        assert_eq!(
            (rusage_v6::FLAVOR, rusage_v6::SIZE, rusage_v6::ENERGY_NJ, rusage_v6::PENERGY_NJ),
            (6, 464, 336, 344),
            "not RUSAGE_INFO_V6 and the C compiler's sizeof/offsetof of struct rusage_info_v6"
        );
        assert_eq!(
            (rusage_v6::CHILD_USER_TIME, rusage_v6::CHILD_SYSTEM_TIME),
            (96, 104),
            "not the C compiler's offsetof of ri_child_user_time and ri_child_system_time"
        );
        assert_eq!(std::mem::size_of::<RusageInfoV6Mirror>(), rusage_v6::SIZE);
        assert_eq!(std::mem::offset_of!(RusageInfoV6Mirror, ri_energy_nj), rusage_v6::ENERGY_NJ);
        assert_eq!(std::mem::offset_of!(RusageInfoV6Mirror, ri_penergy_nj), rusage_v6::PENERGY_NJ);
        assert_eq!(std::mem::offset_of!(RusageInfoV6Mirror, ri_child_user_time), rusage_v6::CHILD_USER_TIME);
        assert_eq!(std::mem::offset_of!(RusageInfoV6Mirror, ri_child_system_time), rusage_v6::CHILD_SYSTEM_TIME);
    }

    /// The decoding, on fixed byte layouts. Every byte holding its own index
    /// (mod 251) makes every word distinct, so a decoder reading any other
    /// word, or straddling two, reads other bytes. And a literal buffer:
    /// `ri_energy_nj` = 2,400,000,000 nJ, `ri_penergy_nj` = 1,
    /// `ri_child_user_time` = 446,368 and `ri_child_system_time` = 4,119,493
    /// (a reaped `yes`'s, as read on an M5 Max), little-endian as on every
    /// macOS target, with every other byte 0xFF.
    #[test]
    fn rusage_v6_decoding_reads_its_four_words_and_nothing_else() {
        let mut info = [0u8; rusage_v6::SIZE];
        for (i, b) in info.iter_mut().enumerate() {
            *b = (i % 251) as u8;
        }
        let at = |start: u8| u64::from_ne_bytes(std::array::from_fn(|k| start + k as u8));
        let r = rusage_v6::decode(&info);
        assert_eq!((r.energy_nj, r.penergy_nj), (at(85), at(93)), "bytes 336..344 and 344..352 are 85..93 and 93..101");
        assert_eq!((r.child_user_time, r.child_system_time), (at(96), at(104)), "bytes 96..104 and 104..112");

        let mut info = [0xFFu8; rusage_v6::SIZE];
        info[336..344].copy_from_slice(&[0x00, 0x18, 0x0D, 0x8F, 0x00, 0x00, 0x00, 0x00]);
        info[344..352].copy_from_slice(&[0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]);
        info[96..104].copy_from_slice(&[0xA0, 0xCF, 0x06, 0x00, 0x00, 0x00, 0x00, 0x00]);
        info[104..112].copy_from_slice(&[0xC5, 0xDB, 0x3E, 0x00, 0x00, 0x00, 0x00, 0x00]);
        let r = rusage_v6::decode(&info);
        if cfg!(target_endian = "little") {
            assert_eq!((r.energy_nj, r.penergy_nj), (2_400_000_000, 1));
            assert_eq!((r.child_user_time, r.child_system_time), (446_368, 4_119_493));
            assert_eq!(r.reaped_children_cpu(), 4_565_861);
        } else {
            assert_eq!((r.energy_nj, r.penergy_nj), (0x0018_0D8F_0000_0000, 0x0100_0000_0000_0000));
        }
    }

    /// One `rusage_info_v6` as a span reads it: `ri_energy_nj` = `nj` and the
    /// reaped children's CPU time = `children_cpu`, split across user and
    /// system time as a reaped `yes`'s was.
    fn usage(nj: u64, children_cpu: u64) -> rusage_v6::ProcessEnergyReading {
        let user = children_cpu / 10;
        rusage_v6::ProcessEnergyReading {
            energy_nj: nj,
            penergy_nj: nj / 2,
            child_user_time: user,
            child_system_time: children_cpu - user,
        }
    }

    /// A per-process span is a reading only when `ri_energy_nj` advanced:
    /// `HwShunt` and whole (no child reaped, none at the end), the rise in µJ
    /// rounded up, so a rise under 1 µJ is 1 µJ and never 0. A count that held
    /// or fell, or a failed read, is the default-power estimate.
    #[test]
    fn a_process_span_is_a_reading_only_when_the_count_advanced() {
        let (none, kids) = (Some(0), 4_565_861);
        let e = process_span(Some(usage(1_000_000, kids)), Some(usage(481_000_001, kids)), none, 200_000_000);
        assert_eq!((e.provenance, e.measured_uj, e.is_whole()), (Provenance::HwShunt, Some(480_001), true), "{e:?}");
        e.check_provenance().unwrap();
        let e = process_span(Some(usage(5, 0)), Some(usage(505, 0)), none, 1_000);
        assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(1)), "a sub-µJ rise read as zero: {e:?}");
        let model = time_power_uj(200_000_000, DEFAULT_ACTIVE_MILLIWATTS);
        let b = Some(usage(9_000_000_000, 0));
        for (what, before, after) in
            [("held", b, b), ("fell", b, Some(usage(1, 0))), ("before failed", None, b), ("after failed", b, None)]
        {
            let e = process_span(before, after, none, 200_000_000);
            assert_eq!((e.provenance, e.measured_uj, e.uj()), (Provenance::Estimator, None, model), "{what}: {e:?}");
        }
    }

    /// A span a child process may have worked in unseen is a `Partial`
    /// reading, never whole: the child's energy is its own and is not in
    /// `ri_energy_nj`. Each on a count that rose 0.48 J:
    /// - the reaped children's CPU time rose across the span (a child was
    ///   reaped in it): `Partial`, though no child is left at its end;
    /// - a child is left at its end (running, or exited and unreaped):
    ///   `Partial`, though no child was reaped;
    /// - both: `Partial`;
    /// - the child count failed: `Partial`, since nothing shows it whole;
    /// - neither, the reaped time held at a nonzero value: whole.
    ///
    /// The figure stays the count's rise either way: `Partial` changes what it
    /// claims to cover, not what it read. A span whose count held is the
    /// whole-task default-power estimate whatever the children did.
    #[test]
    fn a_span_a_child_may_have_worked_in_is_a_partial_reading() {
        let (b, kids) = (1_000_000, 4_565_861);
        let span = |children_after: u64, at_end: Option<usize>| {
            process_span(Some(usage(b, kids)), Some(usage(481_000_001, kids + children_after)), at_end, 200_000_000)
        };
        for (what, e) in [
            ("a child reaped", span(4_565_861, Some(0))),
            ("a child left at the end", span(0, Some(1))),
            ("a child reaped and one left", span(1, Some(3))),
            ("the child count failed", span(0, None)),
        ] {
            assert_eq!(
                (e.provenance, e.measured_uj, e.coverage),
                (Provenance::HwShunt, Some(480_001), jcp_schema::Coverage::Partial),
                "{what}: the figure claimed a child's share: {e:?}"
            );
            assert!(!e.is_whole(), "{what}: {e:?}");
            e.check_provenance().unwrap();
        }
        let e = span(0, Some(0));
        assert_eq!((e.provenance, e.measured_uj, e.is_whole()), (Provenance::HwShunt, Some(480_001), true), "{e:?}");
        let held = process_span(Some(usage(b, kids)), Some(usage(b, kids + 9)), Some(2), 200_000_000);
        assert_eq!((held.provenance, held.measured_uj), (Provenance::Estimator, None), "{held:?}");
        assert!(held.is_whole(), "the default-power estimate is a whole-task figure: {held:?}");
    }

    /// The per-process probe's rule on a scripted `ri_energy_nj`: rising
    /// ~60 mJ every interval, as under the probe's burn, Live at the tenth
    /// interval; held, Frozen.
    #[test]
    fn the_process_energy_gate_on_a_scripted_count() {
        let count = |nj: i64| Some(vec![("ri_energy_nj".to_string(), nj)]);
        let (status, w, _, _) = scripted_counter(|i| count(2_529_044 + 60_000_000 * i as i64), COUNTER_STEP);
        assert_eq!((status, w.unwrap().intervals), (CounterStatus::Live, 10));
        let (status, _, _, _) = scripted_counter(|_| count(2_529_044), COUNTER_STEP);
        assert_eq!(status, CounterStatus::Frozen);
    }

    /// The per-process rung is selected on a `Live` status and on no other,
    /// and its counter is opened only then. Declined, the ladder goes on to
    /// IOReport, and the explanation says so.
    #[cfg(target_os = "macos")]
    #[test]
    fn only_a_live_status_selects_the_process_energy_rung() {
        use CounterStatus as S;
        for status in [S::Unavailable, S::Frozen, S::Live] {
            let opened = Cell::new(0);
            let open = || {
                opened.set(opened.get() + 1);
                process_energy::ProcessEnergy::open()
            };
            let ladder = Ladder { process_energy: &|| status, open_process_energy: &open, ..Ladder::none() };
            let (meter, why) = Meter::detect_with(&ladder);
            let live = status == S::Live;
            assert_eq!(matches!(meter, Meter::ProcessEnergy(_)), live, "status {status:?} gave {meter:?}");
            assert_eq!(opened.get(), usize::from(live), "status {status:?} opened the counter {} times", opened.get());
            let expect = Detection {
                selected: if live { Rung::ProcessEnergy } else { Rung::UncalibratedTimePower },
                rapl: Some(S::Unavailable),
                nvml: Some(S::Unavailable),
                process_energy: Some(status),
                ioreport: if live { None } else { Some(IoReportStatus::Unavailable) },
            };
            assert_eq!(why, expect, "status {status:?}");
            assert_eq!(meter.rung(), why.selected);
        }
    }

    /// The order of the rungs: RAPL above the per-process counter, which is
    /// above IOReport. A rung below the selected one is never asked, so its
    /// probe never runs.
    #[cfg(target_os = "macos")]
    #[test]
    fn the_process_energy_rung_sits_between_rapl_and_ioreport() {
        let _hw = ioreport_hw_lock();
        use CounterStatus as S;
        let asked = Cell::new(0);
        let ioreport = || {
            asked.set(asked.get() + 1);
            IoReportStatus::Live
        };
        let (meter, why) = Meter::detect_with(&Ladder {
            process_energy: &|| S::Live,
            open_process_energy: &process_energy::ProcessEnergy::open,
            ioreport: &ioreport,
            ..Ladder::none()
        });
        assert!(matches!(meter, Meter::ProcessEnergy(_)), "{meter:?}");
        assert_eq!((why.ioreport, asked.get()), (None, 0), "IOReport was asked below a selected per-process rung");
        let (meter, why) = Meter::detect_with(&Ladder {
            process_energy: &|| S::Frozen,
            open_process_energy: &process_energy::ProcessEnergy::open,
            ioreport: &ioreport,
            ..Ladder::none()
        });
        assert_eq!((why.process_energy, why.ioreport), (Some(S::Frozen), Some(IoReportStatus::Live)));
        assert_eq!(matches!(meter, Meter::IoReport(_)), ioreport::IoReport::open().is_some(), "{meter:?}");
        let fake = FakePowercap::new(&["1000"]);
        let process_asked = Cell::new(0);
        let process = || {
            process_asked.set(process_asked.get() + 1);
            S::Live
        };
        let (meter, why) = Meter::detect_with(&Ladder {
            rapl: &|| S::Live,
            open_rapl: &|| Rapl::open_in(&fake.root),
            process_energy: &process,
            open_process_energy: &process_energy::ProcessEnergy::open,
            ..Ladder::none()
        });
        assert!(matches!(meter, Meter::Rapl(_)), "{meter:?}");
        assert_eq!(
            why,
            Detection { selected: Rung::Rapl, rapl: Some(S::Live), nvml: None, process_energy: None, ioreport: None }
        );
        assert_eq!(process_asked.get(), 0, "the per-process status was asked below a selected RAPL rung");
    }

    /// Off macOS there is no per-process counter: a `Live` status (which the
    /// host never reports there) still selects nothing, and the explanation
    /// shows a status that admitted its rung beside a lower selected one.
    #[cfg(not(target_os = "macos"))]
    #[test]
    fn the_process_energy_rung_is_never_selected_off_macos() {
        assert_eq!(process_energy_status(), CounterStatus::Unavailable);
        let (meter, why) = Meter::detect_with(&Ladder { process_energy: &|| CounterStatus::Live, ..Ladder::none() });
        assert!(matches!(meter, Meter::UncalibratedTimePower { .. }), "{meter:?}");
        assert_eq!((why.selected, why.process_energy), (Rung::UncalibratedTimePower, Some(CounterStatus::Live)));
    }

    /// Each meter names its rung.
    #[test]
    fn each_meter_names_its_rung() {
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        assert_eq!(Meter::time_power(1).rung(), Rung::TimePower);
        assert_eq!(Meter::uncalibrated_time_power(1).rung(), Rung::UncalibratedTimePower);
        assert_eq!(Meter::constant(1).rung(), Rung::Constant);
        let fake = FakePowercap::new(&["1"]);
        assert_eq!(Meter::Rapl(Rapl::open_in(&fake.root).unwrap()).rung(), Rung::Rapl);
        #[cfg(target_os = "macos")]
        {
            assert_eq!(Meter::ProcessEnergy(process_energy::ProcessEnergy::open().unwrap()).rung(), Rung::ProcessEnergy);
            if let Some(io) = ioreport::IoReport::open() {
                assert_eq!(Meter::IoReport(io).rung(), Rung::IoReport);
            }
        }
    }

    // ── The per-process rung against the hardware (macOS) ───────────────────

    /// Set in the environment of a fresh process that [`in_a_fresh_process`]
    /// starts, to the one test it runs.
    #[cfg(target_os = "macos")]
    const FRESH_TEST: &str = "JCP_ENERGY_FRESH_PROCESS_TEST";

    /// Runs `body` as the only test of a fresh process: this test binary
    /// again, filtered to `test` exactly, on one test thread. The count read
    /// is the whole process's, so tests running beside it in this process
    /// would land in its spans. Lines the body prints that begin with "process
    /// energy" are echoed here.
    #[cfg(target_os = "macos")]
    fn in_a_fresh_process(test: &str, body: fn()) {
        if std::env::var(FRESH_TEST).as_deref() == Ok(test) {
            return body();
        }
        let _hw = ioreport_hw_lock();
        let out = std::process::Command::new(std::env::current_exe().expect("this test binary's path"))
            .args([test, "--exact", "--nocapture", "--test-threads=1"])
            .env(FRESH_TEST, test)
            .output()
            .expect("could not run this test binary again");
        let text = format!("{}{}", String::from_utf8_lossy(&out.stdout), String::from_utf8_lossy(&out.stderr));
        for line in text.lines().filter(|l| l.starts_with("process energy")) {
            eprintln!("{line}");
        }
        assert!(out.status.success(), "{test} failed in a fresh process:\n{text}");
        // A filter that matched nothing would also exit 0.
        assert!(text.contains("running 1 test") && text.contains("1 passed"), "the fresh process did not run {test}:\n{text}");
    }

    /// `_CLOCK_THREAD_CPUTIME_ID` in macOS `<time.h>`, the tests' own copy.
    #[cfg(target_os = "macos")]
    const TESTS_THREAD_CPU_CLOCK: std::os::raw::c_int = 16;

    /// The most wall time a test's burn of its own CPU may take. A thread that
    /// gets less than 1/25 of a core for a 200 ms burn fails its test with a
    /// message that says so, rather than spinning on unbounded.
    #[cfg(target_os = "macos")]
    const TESTS_BURN_WALL_CAP: Duration = Duration::from_secs(5);

    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    unsafe extern "C" {
        fn clock_gettime_nsec_np(clock_id: std::os::raw::c_int) -> u64;
        fn proc_pid_rusage(pid: std::os::raw::c_int, flavor: std::os::raw::c_int, buffer: *mut std::ffi::c_void) -> std::os::raw::c_int;
        fn proc_listchildpids(
            ppid: std::os::raw::c_int,
            buffer: *mut std::ffi::c_void,
            buffersize: std::os::raw::c_int,
        ) -> std::os::raw::c_int;
        fn proc_pidinfo(
            pid: std::os::raw::c_int,
            flavor: std::os::raw::c_int,
            arg: u64,
            buffer: *mut std::ffi::c_void,
            buffersize: std::os::raw::c_int,
        ) -> std::os::raw::c_int;
        fn pthread_threadid_np(thread: *mut std::ffi::c_void, thread_id: *mut u64) -> std::os::raw::c_int;
    }

    /// This thread's CPU time, by the tests' own clock.
    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    fn tests_thread_cpu() -> Duration {
        Duration::from_nanos(unsafe { clock_gettime_nsec_np(TESTS_THREAD_CPU_CLOCK) })
    }

    /// Spin until this thread has used `cpu` more CPU time, by the tests' own
    /// clock, and return the wall time that took. The work is fixed in CPU
    /// time, so a loaded host stretches the spin but never shrinks it.
    /// Panics, failing the test, if [`TESTS_BURN_WALL_CAP`] of wall time
    /// passes first.
    ///
    /// The energy of that work is not fixed: it follows the core tier and the
    /// clock the scheduler gives the thread. The thread does not ask for a
    /// higher QoS, because asking changes nothing here: XNU clamps
    /// user-interactive and user-initiated QoS to the default in a process
    /// with no application role, as a test binary run by `cargo test` is. On
    /// an M5 Max, macOS 27.0.1, a burn after
    /// `pthread_set_qos_class_self_np(QOS_CLASS_USER_INTERACTIVE, 0)`, which
    /// returned 0, was accounted all in the process's
    /// `ri_cpu_time_qos_legacy` (the default QoS) and none in
    /// `ri_cpu_time_qos_user_interactive`. A request for user-initiated QoS
    /// landed in the default too; one for utility or background QoS did not.
    #[cfg(target_os = "macos")]
    fn burn_thread_cpu(cpu: Duration) -> Duration {
        let (start, wall) = (tests_thread_cpu(), std::time::Instant::now());
        let mut acc: u64 = 0;
        loop {
            for _ in 0..1_000 {
                acc = std::hint::black_box(acc.wrapping_add(1));
            }
            let used = tests_thread_cpu().saturating_sub(start);
            if used >= cpu {
                return wall.elapsed();
            }
            assert!(
                wall.elapsed() < TESTS_BURN_WALL_CAP,
                "this thread got only {used:?} of the {cpu:?} of CPU it was to burn in {TESTS_BURN_WALL_CAP:?} of wall \
                 time: the host is too loaded to meter a fixed amount of CPU work"
            );
        }
    }

    /// The tests' own read of any process's `ri_energy_nj`, through their own
    /// FFI declaration and the transcribed struct: the oracle.
    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    fn oracle_energy_nj(pid: u32) -> Option<(u64, u64)> {
        let mut info = std::mem::MaybeUninit::<RusageInfoV6Mirror>::zeroed();
        let rc = unsafe { proc_pid_rusage(pid as std::os::raw::c_int, 6, info.as_mut_ptr().cast()) };
        (rc == 0).then(|| {
            let info = unsafe { info.assume_init() };
            (info.ri_energy_nj, info.ri_penergy_nj)
        })
    }

    /// `proc_pidinfo` flavor 34, `PROC_PIDTHREADCOUNTS` in the kernel's
    /// `<sys/proc_info.h>` (the SDK's copy of that header leaves it out): one
    /// thread's counts, asked by its 64-bit thread id. The kernel writes a
    /// `uint16_t` count of CPU performance levels and six bytes of padding,
    /// then for each level five `uint64_t`: instructions, cycles, user time,
    /// system time, and the thread's CPU energy in nJ. On the dev host: two
    /// levels, 88 bytes.
    #[cfg(target_os = "macos")]
    const TESTS_PIDTHREADCOUNTS: std::os::raw::c_int = 34;

    /// The tests' own read of the calling thread's own CPU energy count, in
    /// nJ, summed over the performance levels it ran on: the per-thread
    /// oracle, through their own FFI declarations. The meter reads the whole
    /// process's count by another call, and the kernel keeps that count as
    /// its threads' counts added up, an exited thread's included. On the dev
    /// host, under a load average near 100, a span in which one thread burned
    /// rose by exactly that thread's own rise, and one in which two did, by
    /// their sum and a little more (spawning and joining the second): never
    /// less, in every span measured.
    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    fn oracle_this_thread_energy_nj() -> u64 {
        const LEVELS: usize = 8;
        let mut tid = 0u64;
        let rc = unsafe { pthread_threadid_np(std::ptr::null_mut(), &mut tid) };
        assert_eq!(rc, 0, "the tests' pthread_threadid_np failed");
        let mut counts = [0u64; 1 + 5 * LEVELS];
        let bytes = std::mem::size_of_val(&counts) as std::os::raw::c_int;
        let me = std::process::id() as std::os::raw::c_int;
        let wrote = unsafe { proc_pidinfo(me, TESTS_PIDTHREADCOUNTS, tid, counts.as_mut_ptr().cast(), bytes) };
        let head = counts[0].to_ne_bytes();
        let levels = usize::from(u16::from_ne_bytes([head[0], head[1]]));
        assert!(
            (1..=LEVELS).contains(&levels) && usize::try_from(wrote) == Ok(8 + 40 * levels),
            "the tests' per-thread counts: {wrote} bytes written for {levels} performance level(s)"
        );
        (0..levels).map(|level| counts[1 + 5 * level + 4]).sum()
    }

    /// [`burn_thread_cpu`], with the rise of this thread's own energy count
    /// across the burn by the per-thread oracle, in nJ: the wall time the burn
    /// took, and that rise.
    #[cfg(target_os = "macos")]
    fn burn_thread_cpu_counted(cpu: Duration) -> (Duration, u64) {
        let before = oracle_this_thread_energy_nj();
        let wall = burn_thread_cpu(cpu);
        let after = oracle_this_thread_energy_nj();
        (wall, after.checked_sub(before).expect("this thread's own energy count fell"))
    }

    /// The tests' own read of a process's reaped children's CPU time
    /// (`ri_child_user_time` + `ri_child_system_time`), through their own FFI
    /// declaration and the transcribed struct.
    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    fn oracle_reaped_children_cpu(pid: u32) -> Option<u64> {
        let mut info = std::mem::MaybeUninit::<RusageInfoV6Mirror>::zeroed();
        let rc = unsafe { proc_pid_rusage(pid as std::os::raw::c_int, 6, info.as_mut_ptr().cast()) };
        (rc == 0).then(|| {
            let info = unsafe { info.assume_init() };
            info.ri_child_user_time + info.ri_child_system_time
        })
    }

    /// The tests' own list of this process's child processes, through their
    /// own FFI declaration: the nonzero pids the kernel wrote into a zeroed
    /// buffer, whatever the call returns.
    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    fn oracle_child_pids() -> Vec<i32> {
        let mut pids = [0i32; 256];
        let bytes = std::mem::size_of_val(&pids) as std::os::raw::c_int;
        let me = std::process::id() as std::os::raw::c_int;
        let rc = unsafe { proc_listchildpids(me, pids.as_mut_ptr().cast(), bytes) };
        assert!(rc >= 0, "the tests' proc_listchildpids failed: {rc}");
        pids.into_iter().filter(|&p| p > 0).collect()
    }

    /// A child process that is killed and reaped when dropped, so a test that
    /// fails while one runs never leaves it behind.
    #[cfg(target_os = "macos")]
    struct Reaped(std::process::Child);

    #[cfg(target_os = "macos")]
    impl Drop for Reaped {
        fn drop(&mut self) {
            let _ = self.0.kill();
            let _ = self.0.wait();
        }
    }

    /// `yes > /dev/null`, started as a child of this process. By its absolute
    /// path: spawned by name, it is looked up by trying each `PATH` directory
    /// in turn, and a failed try can move this process's reaped children's CPU
    /// time (by 54-289 Mach units in 7 of 24 spawns on an M5 Max, never by
    /// absolute path; see `process_span`). That makes a span `Partial` too,
    /// and would blur which check a test isolates.
    #[cfg(target_os = "macos")]
    fn spawn_yes() -> Reaped {
        Reaped(
            std::process::Command::new("/usr/bin/yes")
                .stdout(std::process::Stdio::null())
                .spawn()
                .expect("could not spawn yes"),
        )
    }

    /// The meter `detect()` builds here, which must be the per-process rung.
    #[cfg(target_os = "macos")]
    fn process_meter() -> Meter {
        let (meter, why) = Meter::detect_explained();
        assert!(matches!(meter, Meter::ProcessEnergy(_)), "detect() did not select the per-process rung: {why:?}");
        meter
    }

    /// J, for the log.
    #[cfg(target_os = "macos")]
    fn joules(uj: u64) -> f64 {
        uj as f64 / 1e6
    }

    /// The per-process counter is live on this host, by the cached probe that
    /// `detect()` reads and by a fresh probe on the real parts; `detect()`
    /// selects the rung, and never asks IOReport, whose probe below it never
    /// runs. The counter it reads is this process's: between two reads of the
    /// tests' own oracle for this pid, its count sits between theirs.
    #[cfg(target_os = "macos")]
    #[test]
    fn the_process_energy_rung_is_live_here() {
        in_a_fresh_process("tests::the_process_energy_rung_is_live_here", || {
            let started = std::time::Instant::now();
            let status = process_energy_status();
            let first_call = started.elapsed();
            let (meter, why) = Meter::detect_explained();
            let started = std::time::Instant::now();
            let fresh = process_energy_probe().expect("the per-process counter does not open");
            let fresh_took = started.elapsed();
            eprintln!(
                "process energy: status={status:?} (first call took {first_call:?}); a fresh probe: {:?} after {} \
                 intervals over a {:?} window, advances {:?}, in {fresh_took:?}; detect_explained: {why:?}; IOReport \
                 probe runs = {}",
                liveness::status_of(Some(&fresh)),
                fresh.intervals,
                fresh.window,
                fresh.rails.iter().map(|(k, n)| (k.name.clone(), *n)).collect::<Vec<_>>(),
                ioreport_probe_runs()
            );
            assert_eq!(status, CounterStatus::Live, "the per-process counter is not live here");
            assert_eq!(liveness::status_of(Some(&fresh)), CounterStatus::Live, "a fresh probe says otherwise");
            assert!(matches!(meter, Meter::ProcessEnergy(_)), "{meter:?}");
            assert_eq!(meter.provenance(), Provenance::HwShunt);
            assert_eq!(
                why,
                Detection {
                    selected: Rung::ProcessEnergy,
                    rapl: Some(CounterStatus::Unavailable),
                    nvml: Some(CounterStatus::Unavailable),
                    process_energy: Some(CounterStatus::Live),
                    ioreport: None,
                }
            );
            assert_eq!(ioreport_probe_runs(), 0, "IOReport was probed below a live per-process rung");
            let me = std::process::id();
            let before = oracle_energy_nj(me).expect("the oracle cannot read this process");
            let read = process_energy::read().expect("the reader cannot read this process");
            let after = oracle_energy_nj(me).expect("the oracle cannot read this process");
            eprintln!(
                "process energy: oracle {before:?} <= reader ({}, {}) <= oracle {after:?} (ri_energy_nj, ri_penergy_nj)",
                read.energy_nj, read.penergy_nj
            );
            assert!(
                before.0 <= read.energy_nj && read.energy_nj <= after.0,
                "the reader's ri_energy_nj {} is not this process's ({} .. {})",
                read.energy_nj,
                before.0,
                after.0
            );
            assert!(before.1 <= read.penergy_nj && read.penergy_nj <= after.1, "ri_penergy_nj is not this process's");
            assert!(before.0 > 0, "this process's count is zero after its own probe burned CPU");
        });
    }

    /// 200 ms of one thread's CPU is a hardware reading of it: `HwShunt`,
    /// whole, between 0.1 J and 20 J. A pure in-process burn in a process with
    /// no child, before or after (by the tests' own listing), so nothing is
    /// left out of the figure and it claims the whole span.
    ///
    /// The 200 ms are of the thread's own CPU clock (see [`burn_thread_cpu`]),
    /// so the work is the same however loaded the host. Its energy is not. On
    /// an M5 Max, macOS 27.0.1, at the default QoS, it read from 0.20 J to
    /// 1.24 J, idle to 30 busy spinners; held on the slower cores by
    /// background QoS, 0.18 J. A floor of 0.2 J sat at the bottom of that
    /// range and failed on it. 0.1 J is half the lowest reading. It meets the
    /// 0.1 J ceiling of `sleeping_200_ms_meters_under_a_tenth_of_a_joule`, so
    /// no counter that reads wall time at a fixed power passes both. A counter
    /// that holds fails here before the floor: `detect()` declines it, and a
    /// span over which it held is the default-power estimate, not `HwShunt`. A
    /// counter that advances, but by a fixed step per read rather than with the
    /// work, fails the floor.
    #[cfg(target_os = "macos")]
    #[test]
    fn one_thread_burning_200_ms_is_a_whole_hardware_reading() {
        in_a_fresh_process("tests::one_thread_burning_200_ms_is_a_whole_hardware_reading", || {
            let meter = process_meter();
            assert_eq!(oracle_child_pids(), Vec::<i32>::new(), "the fresh process already has a child");
            let (wall, e) = meter.measure(|| burn_thread_cpu(Duration::from_millis(200)));
            assert_eq!(oracle_child_pids(), Vec::<i32>::new(), "a child at the end of a pure in-process burn");
            eprintln!(
                "process energy: 200 ms of one thread's CPU, in {wall:?} of wall time -> {} µJ ({:.3} J), {:?}, \
                 coverage {:?}",
                e.uj(),
                joules(e.uj()),
                e.provenance,
                e.coverage
            );
            e.check_provenance().unwrap();
            assert_eq!(e.provenance, Provenance::HwShunt, "{e:?}");
            assert!(e.is_whole(), "{e:?}");
            assert!((100_000..=20_000_000).contains(&e.uj()), "200 ms of one thread's CPU metered {} µJ", e.uj());
        });
    }

    /// 200 ms asleep meters under 0.1 J: the counter reads this process's
    /// CPU, not wall time at a guessed power.
    #[cfg(target_os = "macos")]
    #[test]
    fn sleeping_200_ms_meters_under_a_tenth_of_a_joule() {
        in_a_fresh_process("tests::sleeping_200_ms_meters_under_a_tenth_of_a_joule", || {
            let meter = process_meter();
            let ((), e) = meter.measure(|| std::thread::sleep(Duration::from_millis(200)));
            eprintln!("process energy: 200 ms asleep -> {} µJ ({:.6} J), {:?}", e.uj(), joules(e.uj()), e.provenance);
            assert!(e.uj() < 100_000, "200 ms asleep metered {} µJ: {e:?}", e.uj());
            assert_eq!(e.provenance, Provenance::HwShunt, "{e:?}");
        });
    }

    /// One `proc_threadcounts` as the kernel writes it into a read's buffer:
    /// `levels` in its first two bytes, six bytes of padding, then for each
    /// of `energy_nj` a record of five `uint64_t` whose fifth is that level's
    /// energy and whose first four are other counts.
    fn thread_counts_bytes(levels: u16, energy_nj: &[u64]) -> [u8; thread_counts::SIZE] {
        let mut counts = [0u8; thread_counts::SIZE];
        counts[..2].copy_from_slice(&levels.to_ne_bytes());
        for (level, nj) in energy_nj.iter().enumerate() {
            let record = thread_counts::HEADER + level * thread_counts::LEVEL;
            for (field, word) in [1_111u64, 2_222, 3_333, 4_444, *nj].into_iter().enumerate() {
                counts[record + field * 8..record + field * 8 + 8].copy_from_slice(&word.to_ne_bytes());
            }
        }
        counts
    }

    /// The layout constants are the kernel header's: flavor 34, an 8-byte
    /// header, 40 bytes a level, the energy 32 bytes into a level. The
    /// decoding reads each level's energy and nothing else, and reads no
    /// count at all from a result of any size but the header and one record
    /// for each level it names: a failed call, a short or long result, no
    /// level, more levels than the buffer holds.
    #[test]
    fn thread_counts_decoding_reads_each_levels_energy_in_the_one_layout_it_knows() {
        assert_eq!(
            (thread_counts::FLAVOR, thread_counts::HEADER, thread_counts::LEVEL, thread_counts::ENERGY_NJ),
            (34, 8, 40, 32)
        );
        // Two levels, 88 bytes: what an M5 Max and an M3 Ultra write.
        assert_eq!(thread_counts::energy_nj(&thread_counts_bytes(2, &[3_000_000, 250]), 88), Some(3_000_250));
        assert_eq!(thread_counts::energy_nj(&thread_counts_bytes(1, &[77]), 48), Some(77));
        assert_eq!(thread_counts::energy_nj(&thread_counts_bytes(3, &[1, 2, 4]), 128), Some(7));
        assert_eq!(thread_counts::energy_nj(&thread_counts_bytes(2, &[u64::MAX, 5]), 88), Some(u64::MAX), "saturates");
        let two = thread_counts_bytes(2, &[3_000_000, 250]);
        for (wrote, why) in [(-1, "the call failed"), (0, "nothing written"), (48, "one record for two levels"), (80, "short"), (96, "long")]
        {
            assert_eq!(thread_counts::energy_nj(&two, wrote), None, "{why}");
        }
        assert_eq!(thread_counts::energy_nj(&thread_counts_bytes(0, &[]), 8), None, "no performance level");
        let too_many = u16::try_from(thread_counts::MAX_LEVELS + 1).unwrap();
        assert_eq!(
            thread_counts::energy_nj(&thread_counts_bytes(too_many, &[]), 8 + 40 * i32::from(too_many)),
            None,
            "more levels than the buffer holds"
        );
    }

    /// The rule for reading one's own process: the reading thread is seen
    /// off its core only when its own energy count rose across a sleep. The
    /// sleeps are taken in turn until one does; a count that held across
    /// them all, or fell, is not a thread seen to leave, and a count that
    /// cannot be read ends the wait at once.
    #[test]
    fn a_thread_is_seen_off_its_core_only_by_its_own_count_rising_across_a_sleep() {
        use std::cell::RefCell;
        let sleeps = [Duration::from_micros(50), Duration::from_micros(200), Duration::from_millis(1)];
        // The thread's count at each read in turn; the sleeps taken.
        let seen = |counts: &[Option<u64>]| {
            let mut counts = counts.iter().copied();
            let slept = RefCell::new(Vec::new());
            let seen = off_core::seen(&sleeps, || counts.next().flatten(), |pause| slept.borrow_mut().push(pause));
            (seen, slept.into_inner())
        };
        assert_eq!(seen(&[Some(10), Some(11)]), (true, vec![sleeps[0]]), "rose across the first sleep");
        assert_eq!(
            seen(&[Some(10), Some(10), Some(10), Some(10), Some(10), Some(4_000)]),
            (true, sleeps.to_vec()),
            "held across two sleeps, rose across the third"
        );
        assert_eq!(seen(&[Some(10); 6]), (false, sleeps.to_vec()), "held across every sleep");
        assert_eq!(seen(&[Some(10), Some(9), Some(9), Some(8), Some(8), Some(7)]), (false, sleeps.to_vec()), "fell");
        assert_eq!(seen(&[None]), (false, vec![]), "unreadable before any sleep");
        assert_eq!(seen(&[Some(10), None]), (false, vec![sleeps[0]]), "unreadable after a sleep");
        assert!(!off_core::seen(&[], || Some(1), |_| panic!("slept")), "no sleep, nothing seen");
        assert_eq!(
            off_core::SLEEPS,
            [Duration::from_micros(50), Duration::from_micros(200), Duration::from_millis(1), Duration::from_millis(5)]
        );
    }

    /// On this host the metering thread's own count reads, in the layout
    /// `thread_counts` knows: between two reads of the tests' own per-thread
    /// oracle (their own FFI declaration and decoding), the meter's read of
    /// it sits between theirs. And a span's read sees the thread leave its
    /// core: the path every figure of the rung takes.
    ///
    /// A thread that has not left a core since it started has a count of
    /// zero (seen on an idle M3 Ultra), which would make the comparison one
    /// of zeros. So the thread first burns and sleeps until the oracle's
    /// count is above zero.
    #[cfg(target_os = "macos")]
    #[test]
    fn the_metering_threads_own_count_reads_here_and_a_span_read_sees_it_leave_its_core() {
        for ms in [1, 2, 4, 8] {
            burn_thread_cpu(Duration::from_millis(1));
            std::thread::sleep(Duration::from_millis(ms));
            if oracle_this_thread_energy_nj() > 0 {
                break;
            }
        }
        let before = oracle_this_thread_energy_nj();
        let mine = process_energy::thread_energy_nj().expect("the meter cannot read this thread's own count");
        let after = oracle_this_thread_energy_nj();
        eprintln!("process energy: this thread's own count: oracle {before} <= meter {mine} <= oracle {after} nJ");
        assert!(before > 0, "this thread's own count is still zero after four burns and sleeps");
        assert!(before <= mine && mine <= after, "the meter's count {mine} nJ is not this thread's ({before} .. {after})");
        let counter = process_energy::ProcessEnergy::open().expect("the per-process counter does not open");
        assert!(counter.read().is_some(), "this thread was not seen to leave its core within {:?}", off_core::SLEEPS);
    }

    /// A span whose metering thread is never seen to leave its core is not a
    /// reading: the rung's figure for it is the default-power estimate,
    /// `Estimator`, with no measured figure — never a zero, and never a
    /// figure graded `HwShunt` on a count that may lack what the thread
    /// spent. The work still runs, once, and the read gives up only after
    /// every sleep. The per-fabric meter reports no CPU figure for such a
    /// span, while it still lists the CPU as a fabric it reads.
    #[cfg(target_os = "macos")]
    #[test]
    fn a_span_whose_thread_is_never_seen_off_its_core_is_an_estimate() {
        let meter = Meter::ProcessEnergy(process_energy::ProcessEnergy::never_off_core());
        let mut runs = 0;
        let started = std::time::Instant::now();
        let ((), e) = meter.measure(|| runs += 1);
        let took = started.elapsed();
        assert_eq!(runs, 1, "the work ran {runs} times");
        assert_eq!((e.provenance, e.measured_uj), (Provenance::Estimator, None), "{e:?}");
        e.check_provenance().unwrap();
        let every_sleep: Duration = off_core::SLEEPS.iter().sum();
        assert!(took >= every_sleep, "the read gave up after {took:?}, before all of {:?}", off_core::SLEEPS);

        let fabrics = FabricMeter { ioreport: None, process: Some(process_energy::ProcessEnergy::never_off_core()) };
        assert_eq!(fabrics.readable(), vec![(Fabric::Cpu, Attribution::Process)]);
        let ((), readings) = fabrics.measure(|| ());
        assert!(readings.is_empty(), "a CPU figure for a span no end of which was read: {readings:?}");
    }

    /// `proc_pidinfo` flavor 4, `PROC_PIDTASKINFO` in `<sys/proc_info.h>`: a
    /// process's task counts, 96 bytes — six `uint64_t` (sizes and CPU
    /// times), then twelve `int32_t`, the ninth of them `pti_csw`, how many
    /// times the process's threads have been switched off a core.
    #[cfg(target_os = "macos")]
    const TESTS_PIDTASKINFO: std::os::raw::c_int = 4;

    /// The tests' own count of this process's context switches (`pti_csw`,
    /// the `int32_t` at byte 80 of `proc_taskinfo`), through their own FFI
    /// declaration.
    #[cfg(target_os = "macos")]
    #[allow(unsafe_code)]
    fn oracle_context_switches() -> i32 {
        let mut info = [0i32; 24];
        let bytes = std::mem::size_of_val(&info) as std::os::raw::c_int;
        let me = std::process::id() as std::os::raw::c_int;
        let wrote = unsafe { proc_pidinfo(me, TESTS_PIDTASKINFO, 0, info.as_mut_ptr().cast(), bytes) };
        assert_eq!(wrote, bytes, "the tests' proc_pidinfo(PROC_PIDTASKINFO) wrote {wrote} of {bytes} bytes");
        info[80 / 4]
    }

    /// The tests' own read of this process's `ri_energy_nj`, taken once the
    /// calling thread has left its core by the tests' own rule: a sleep of
    /// 1 ms, then 2, 4 and 8, until the process's context-switch count rose
    /// across one. In a fresh process running one test on one thread, a rise
    /// is this thread's switch. The kernel adds a thread's energy to its
    /// process's count when the thread leaves a core, so this read holds all
    /// the thread spent before it. The meter's own check shares nothing with
    /// it: another call, another count, sleeps a twentieth as long.
    #[cfg(target_os = "macos")]
    fn oracle_energy_nj_off_core() -> u64 {
        let left = [1, 2, 4, 8].into_iter().any(|ms| {
            let before = oracle_context_switches();
            std::thread::sleep(Duration::from_millis(ms));
            oracle_context_switches() > before
        });
        assert!(left, "the tests' oracle never saw this thread leave its core across sleeps of 1, 2, 4 and 8 ms");
        oracle_energy_nj(std::process::id()).expect("the oracle cannot read this process").0
    }

    /// A span of a millisecond of the metering thread's CPU is that work's
    /// reading, and a sleep metered straight after a burn is not given the
    /// burn. Each `HwShunt` figure is held against the tests' own window
    /// around its span, whose two ends are read once this thread has left
    /// its core by the tests' own rule.
    ///
    /// - 1 ms of this thread's CPU, 40 times: a `HwShunt` figure is no more
    ///   than the oracle's window (which holds the span and both readers'
    ///   own reads and wake-ups) and at least two thirds of it. Those reads
    ///   do not shrink with the burn's cost: under 2% of the window on an
    ///   idle M3 Ultra, up to 16% under 40 busy loops (the lowest of 4,400
    ///   spans). A span the meter could not read is the default-power
    ///   estimate, which claims no reading. At most a tenth of the spans
    ///   may be that or fall short of the band; none may be over the
    ///   oracle's window.
    /// - a 2 ms sleep straight after 8 ms of this thread's CPU that the span
    ///   does not cover, 40 times: the oracle's window is the burn and the
    ///   sleep, and a `HwShunt` figure for the sleep is under a quarter of
    ///   it (it was under 1% idle, and at most 6% under the busy loops), in
    ///   at least nine spans of ten.
    ///
    /// No joule figure and no timing is asserted: what a millisecond of CPU
    /// costs follows the core that ran it. A meter that reads its own
    /// process's count from a thread still on its core fails both: the count
    /// lacks what that thread spent since it last left one, so the first
    /// kind of span reads nothing or part of the burn, and the second reads
    /// the burn before it as the sleep's energy.
    #[cfg(target_os = "macos")]
    #[test]
    fn a_short_span_is_its_own_reading_by_an_oracle_that_leaves_its_core_its_own_way() {
        in_a_fresh_process("tests::a_short_span_is_its_own_reading_by_an_oracle_that_leaves_its_core_its_own_way", || {
            const TRIES: usize = 40;
            let meter = process_meter();

            // (try, the figure in µJ, the oracle's window in nJ) of each
            // HwShunt figure that is short of its span's, and of each that is
            // over the oracle's window, which no read of this process's
            // count can be.
            let (mut agreed, mut estimated, mut wrong, mut over) = (Vec::new(), 0usize, Vec::new(), Vec::new());
            for i in 0..TRIES {
                let before = oracle_energy_nj_off_core();
                let (_, e) = meter.measure(|| burn_thread_cpu(Duration::from_millis(1)));
                let oracle_nj = oracle_energy_nj_off_core() - before;
                let nj = e.uj().saturating_mul(1_000);
                match e.provenance {
                    // The meter rounds a rise up to the next whole µJ.
                    Provenance::HwShunt if nj >= oracle_nj + 1_000 => over.push((i, e.uj(), oracle_nj)),
                    Provenance::HwShunt if nj * 3 >= oracle_nj * 2 => agreed.push(nj * 1_000 / oracle_nj.max(1)),
                    Provenance::HwShunt => wrong.push((i, e.uj(), oracle_nj)),
                    Provenance::ModelBased | Provenance::Estimator => estimated += 1,
                }
            }
            eprintln!(
                "process energy: 1 ms of this thread's CPU x {TRIES}: {} HwShunt within the oracle's window (at least \
                 {}/1000 of it), {estimated} estimated, {} HwShunt and short of the span's {wrong:?}, {} HwShunt and \
                 over the oracle's window {over:?} (try, µJ, oracle nJ)",
                agreed.len(),
                agreed.iter().min().copied().unwrap_or(0),
                wrong.len(),
                over.len()
            );

            let (mut small, mut slept_estimated, mut leaked) = (Vec::new(), 0usize, Vec::new());
            for i in 0..TRIES {
                let before = oracle_energy_nj_off_core();
                burn_thread_cpu(Duration::from_millis(8));
                let ((), e) = meter.measure(|| std::thread::sleep(Duration::from_millis(2)));
                let oracle_nj = oracle_energy_nj_off_core() - before;
                let nj = e.uj().saturating_mul(1_000);
                match e.provenance {
                    Provenance::HwShunt if nj * 4 < oracle_nj => small.push(nj * 1_000 / oracle_nj.max(1)),
                    Provenance::HwShunt => leaked.push((i, e.uj(), oracle_nj)),
                    Provenance::ModelBased | Provenance::Estimator => slept_estimated += 1,
                }
            }
            eprintln!(
                "process energy: a 2 ms sleep after an 8 ms burn x {TRIES}: {} HwShunt under a quarter of the oracle's \
                 window (at most {}/1000 of it), {slept_estimated} estimated, {} HwShunt with the burn before the span \
                 in them {leaked:?} (try, µJ, oracle nJ)",
                small.len(),
                small.iter().max().copied().unwrap_or(0),
                leaked.len()
            );

            // What a read of the count costs: reported, not asserted.
            let counter = process_energy::ProcessEnergy::open().expect("the per-process counter does not open");
            let mut micros: Vec<u128> = (0..200)
                .map(|_| {
                    let started = std::time::Instant::now();
                    let _ = counter.read();
                    started.elapsed().as_micros()
                })
                .collect();
            micros.sort_unstable();
            eprintln!(
                "process energy: one read of the count for a span costs {} µs at the median, {} µs at the 95th \
                 percentile, {} µs at most (200 reads)",
                micros[100], micros[190], micros[199]
            );

            assert!(over.is_empty(), "a span was graded HwShunt on more than the process spent around it: {over:?}");
            // A tenth of the spans may miss the band. On a loaded host the
            // oracle's own reads can land on a costlier core than the burn
            // did, which shrinks a correct figure's share of the oracle's
            // window; and a span the meter could not read is an estimate by
            // design. A meter that does not take the metering thread off
            // its core misses on every span of an idle host.
            assert!(
                (estimated + wrong.len()) * 10 <= TRIES,
                "{estimated} of {TRIES} 1 ms spans were not read and {} were graded HwShunt short of the work: {wrong:?}",
                wrong.len()
            );
            assert!(
                leaked.len() * 10 <= TRIES,
                "{} of {TRIES} sleeps were graded HwShunt on the energy of the burn before them: {leaked:?}",
                leaked.len()
            );
        });
    }

    /// Two threads burning 200 ms of CPU each meter more than one: every
    /// thread of the process is in the count. Each thread's 200 ms are of its
    /// own CPU clock (see [`burn_thread_cpu`]). Both burn in one span, and the
    /// tests' per-thread oracle reads each one's own count across its burn.
    /// The span's figure must be at least the two counts added up, and so
    /// more than either one's: what one thread burning that CPU would meter.
    ///
    /// The figures compared come from the same span, so whichever cores and
    /// clocks a loaded host gives the threads, they count the same work. Two
    /// spans one after the other do not: the CPU is the same in both, but its
    /// energy follows the core type and clock each span ran on, and on a
    /// loaded host one thread's 200 ms read 0.92 J and two threads' 0.59 J.
    /// A meter that counts only the thread that calls it reads one thread
    /// here, and fails.
    #[cfg(target_os = "macos")]
    #[test]
    fn two_threads_burning_meter_more_than_one() {
        in_a_fresh_process("tests::two_threads_burning_meter_more_than_one", || {
            let meter = process_meter();
            let cpu = Duration::from_millis(200);
            let (((wall_mine, mine_nj), (wall_other, other_nj)), two) = meter.measure(|| {
                std::thread::scope(|s| {
                    let other = s.spawn(|| burn_thread_cpu_counted(cpu));
                    let mine = burn_thread_cpu_counted(cpu);
                    (mine, other.join().expect("the second burning thread panicked"))
                })
            });
            let threads_nj = mine_nj + other_nj;
            eprintln!(
                "process energy: 200 ms of CPU on each of 2 threads, in {wall_mine:?} and {wall_other:?} of wall \
                 time -> {} µJ ({:.3} J); the threads' own counts rose {mine_nj} + {other_nj} nJ ({:.3} J), ratio \
                 {:.3}",
                two.uj(),
                joules(two.uj()),
                threads_nj as f64 / 1e9,
                two.uj() as f64 * 1e3 / threads_nj.max(1) as f64
            );
            assert_eq!(two.provenance, Provenance::HwShunt, "{two:?}");
            assert!(mine_nj > 0 && other_nj > 0, "a burning thread's own count did not rise: {mine_nj} and {other_nj} nJ");
            let metered_nj = two.uj().saturating_mul(1_000);
            assert!(
                metered_nj > mine_nj.max(other_nj),
                "two threads metered {} µJ, no more than one of them alone ({mine_nj} and {other_nj} nJ)",
                two.uj()
            );
            assert!(
                metered_nj >= threads_nj,
                "two threads metered {} µJ, under their own counts added up, {mine_nj} + {other_nj} = {threads_nj} nJ: \
                 a thread of the process is not in the count",
                two.uj()
            );
        });
    }

    /// A span that runs `yes > /dev/null`, then kills and reaps it, is a
    /// `Partial` reading. The child's work is not in the figure: the span
    /// meters under 0.1 J, though the child's own count, by the tests' oracle,
    /// shows it spent at least that much. So the figure must not claim it. By
    /// the tests' own reads, the reaped children's CPU time rose across the
    /// span and no child is left at its end: the reap alone is what makes
    /// this span `Partial`.
    ///
    /// The child runs for at least 200 ms and until its own count reads
    /// 0.1 J, not for a fixed wall time, so a loaded host stretches its run
    /// but never leaves it too little energy to tell. It fails the test if
    /// that takes [`TESTS_BURN_WALL_CAP`].
    #[cfg(target_os = "macos")]
    #[test]
    fn a_span_that_runs_and_reaps_a_child_is_partial() {
        in_a_fresh_process("tests::a_span_that_runs_and_reaps_a_child_is_partial", || {
            const ENOUGH_NJ: u64 = 100_000_000;
            let meter = process_meter();
            let me = std::process::id();
            let reaped_before = oracle_reaped_children_cpu(me).expect("the oracle cannot read this process");
            let mut child_nj = None;
            let ((), e) = meter.measure(|| {
                let mut child = spawn_yes();
                let started = std::time::Instant::now();
                loop {
                    std::thread::sleep(Duration::from_millis(10));
                    let ran = started.elapsed();
                    child_nj = oracle_energy_nj(child.0.id()).map(|(nj, _)| (nj, ran));
                    let enough = child_nj.is_some_and(|(nj, _)| nj >= ENOUGH_NJ);
                    if (enough && ran >= Duration::from_millis(200)) || ran >= TESTS_BURN_WALL_CAP {
                        break;
                    }
                }
                child.0.kill().expect("could not kill yes");
                child.0.wait().expect("could not reap yes");
            });
            let reaped_after = oracle_reaped_children_cpu(me).expect("the oracle cannot read this process");
            let left = oracle_child_pids();
            let (child_nj, ran) = child_nj.expect("the oracle could not read the child's count");
            eprintln!(
                "process energy: a span running `yes > /dev/null` for {ran:?}, then reaping it -> {} µJ ({:.6} J), \
                 {:?}, coverage {:?}; the child's own count {child_nj} nJ ({:.3} J); reaped children's CPU \
                 {reaped_before} -> {reaped_after} Mach units; children left {left:?}",
                e.uj(),
                joules(e.uj()),
                e.provenance,
                e.coverage,
                child_nj as f64 / 1e9
            );
            assert!(
                child_nj >= ENOUGH_NJ,
                "the child spent only {child_nj} nJ in {ran:?} of wall time, too little to tell: the host is too \
                 loaded"
            );
            assert!(e.uj() < 100_000, "the span metered {} µJ: the child's work was attributed to it", e.uj());
            assert!(reaped_after > reaped_before, "the reap did not raise the reaped children's CPU time");
            assert!(left.is_empty(), "children left at the span's end: {left:?}");
            assert_eq!(
                (e.provenance, e.coverage),
                (Provenance::HwShunt, jcp_schema::Coverage::Partial),
                "a span that reaped a child claimed to cover it: {e:?}"
            );
            e.check_provenance().unwrap();
        });
    }

    /// A span that starts `yes > /dev/null` and leaves it running at its end
    /// is a `Partial` reading: the child is still working, and none of its
    /// energy is in the count. The closure also burns 20 ms of its own CPU,
    /// so the count advances. By the tests' own reads, nothing was reaped in
    /// the span (the reaped children's CPU time held) and the child is listed
    /// at its end: the child left behind alone is what makes this span
    /// `Partial`. The child is killed and reaped after the span, and on any
    /// failure.
    #[cfg(target_os = "macos")]
    #[test]
    fn a_span_that_leaves_a_child_running_is_partial() {
        in_a_fresh_process("tests::a_span_that_leaves_a_child_running_is_partial", || {
            let meter = process_meter();
            let me = std::process::id();
            let reaped_before = oracle_reaped_children_cpu(me).expect("the oracle cannot read this process");
            let mut running = None;
            let ((), e) = meter.measure(|| {
                running = Some(spawn_yes());
                burn_thread_cpu(Duration::from_millis(20));
                std::thread::sleep(Duration::from_millis(50));
            });
            let reaped_after = oracle_reaped_children_cpu(me).expect("the oracle cannot read this process");
            let listed = oracle_child_pids();
            let child = running.expect("the span did not start the child");
            let pid = child.0.id() as i32;
            drop(child);
            eprintln!(
                "process energy: a span leaving `yes > /dev/null` running -> {} µJ ({:.6} J), {:?}, coverage {:?}; \
                 children at its end {listed:?} (the child {pid}); reaped children's CPU {reaped_before} -> \
                 {reaped_after} Mach units",
                e.uj(),
                joules(e.uj()),
                e.provenance,
                e.coverage
            );
            assert!(listed.contains(&pid), "the running child {pid} was not listed: {listed:?}");
            assert_eq!(reaped_after, reaped_before, "a child was reaped in the span: the left child is not isolated");
            assert_eq!(
                (e.provenance, e.coverage),
                (Provenance::HwShunt, jcp_schema::Coverage::Partial),
                "a span that left a child running claimed to cover it: {e:?}"
            );
            e.check_provenance().unwrap();
        });
    }

    impl Rapl {
        /// A reader over powercap packages that wrap at `ranges`, read from
        /// nowhere: for the delta arithmetic.
        fn with_ranges(ranges: &[Option<u64>]) -> Self {
            let packages = ranges
                .iter()
                .enumerate()
                .map(|(i, &range)| RaplPackage { rail: format!("intel-rapl:{i}"), path: "/dev/null".into(), range, msr: None })
                .collect();
            Self { packages }
        }
    }

    #[test]
    fn rapl_wraparound_delta() {
        let r = Rapl::with_ranges(&[Some(1_000)]);
        assert_eq!(r.delta(&[100], &[400]), Some(300));
        // counter wrapped at 1_000: 900 → 50 means 150 spent
        assert_eq!(r.delta(&[900], &[50]), Some(150));
        // a snapshot that does not match the packages is no figure
        assert_eq!(r.delta(&[900, 1], &[950, 2]), None);
    }

    /// One zone's delta, modulo its own wrap: a rise is the rise; a fall
    /// wrapped at the zone's range; a fall with no known range, or from above
    /// the range, is unknown, never an invented figure.
    #[test]
    fn a_rapl_zone_wraps_at_its_own_range_or_gives_no_figure() {
        assert_eq!(rapl_zone_delta(100, 400, None), Some(300));
        assert_eq!(rapl_zone_delta(7, 7, Some(1_000)), Some(0));
        assert_eq!(rapl_zone_delta(900, 50, Some(1_000)), Some(150));
        assert_eq!(rapl_zone_delta(65_532_600_000, 500, Some(65_532_610_987)), Some(11_487));
        assert_eq!(rapl_zone_delta(900, 50, None), None, "a fall with no known range gave a figure");
        assert_eq!(rapl_zone_delta(2_000, 50, Some(1_000)), None, "a fall from above the range gave a figure");
        // Each package at its own range, summed: package 0 rose 1,000 µJ,
        // package 1 wrapped at its own (smaller) range.
        let r = Rapl::with_ranges(&[Some(262_143_328_850), Some(65_532_610_987)]);
        assert_eq!(r.delta(&[5_000, 65_532_600_000], &[6_000, 500]), Some(12_487));
        // One package's delta unknown: no figure for the span.
        let r = Rapl::with_ranges(&[Some(262_143_328_850), None]);
        assert_eq!(r.delta(&[5_000, 900], &[6_000, 50]), None);
    }

    /// The package zones by their `name` file, and no other: `package-<n>`,
    /// and `package-<n>-die-<m>`, one zone per die of a multi-die Intel
    /// package.
    #[test]
    fn a_rapl_package_is_a_zone_named_package_n() {
        for name in ["package-0", "package-1\n", "package-12", " package-3 \n", "package-0-die-0", "package-0-die-1\n", "package-12-die-3"] {
            assert!(is_rapl_package_name(name), "{name:?}");
        }
        for name in [
            "psys",
            "dram",
            "core",
            "uncore",
            "package-",
            "package-x",
            "package-0a",
            "Package-0",
            "package0",
            "",
            "package-0-die-",
            "package--die-0",
            "package-0-die-x",
            "package-0-die-1-die-2",
            "package-0-core-0",
            "package-0-die",
            "package-0-",
        ] {
            assert!(!is_rapl_package_name(name), "{name:?}");
        }
        assert_eq!(rapl_top_level_zone("intel-rapl:0"), Some(0));
        assert_eq!(rapl_top_level_zone("intel-rapl:12"), Some(12));
        for dir in ["intel-rapl", "intel-rapl:", "intel-rapl:0:0", "intel-rapl:1:2", "intel-rapl-mmio:0", "intel-rapl:x"] {
            assert_eq!(rapl_top_level_zone(dir), None, "{dir:?}");
        }
    }

    /// A multi-die Intel package, as the kernel lists it: one top-level zone
    /// per die, `package-0-die-0` and `package-0-die-1`. Both are package
    /// zones; the reader holds both, probes both, and a span's figure is both
    /// dies' rise — reading one die would leave the other's energy out.
    #[test]
    fn a_multi_die_package_sums_every_die_zone() {
        let tree = FakePowercap::with_zones(&[
            ("intel-rapl:0", Some("package-0-die-0"), "1000", Some("262143328850")),
            ("intel-rapl:1", Some("package-0-die-1"), "2000", Some("262143328850")),
            ("intel-rapl:0:0", Some("core"), "700", Some("262143328850")),
            ("intel-rapl:2", Some("psys"), "90000", Some("262143328850")),
        ]);
        let r = Rapl::open_in(&tree.root).expect("a tree with two die zones opens");
        let rails: Vec<&str> = r.packages.iter().map(|p| p.rail.as_str()).collect();
        assert_eq!(rails, ["intel-rapl:0", "intel-rapl:1"], "the reader did not hold both die zones and only them");
        let meter = Meter::Rapl(r);
        let (_, e) = meter.measure(|| {
            tree.write_zone("intel-rapl:0", "4000");
            tree.write_zone("intel-rapl:1", "7000");
            tree.write_zone("intel-rapl:0:0", "2700");
            tree.write_zone("intel-rapl:2", "190000");
        });
        assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(8_000)), "not both dies' rise: {e:?}");
        assert_eq!(rapl_access_in(&tree.root), RaplAccess::Readable);
    }

    /// A tree laid out as a two-socket Intel host with a platform zone: two
    /// packages (`intel-rapl:0`, `intel-rapl:2`), `psys` (`intel-rapl:1`), a
    /// top-level `dram` zone (`intel-rapl:3`), each package's `core` and
    /// `dram` subzones, and the MMIO interface to package 0. Each package
    /// wraps at a range of its own.
    fn two_sockets_with_psys_and_dram() -> FakePowercap {
        FakePowercap::with_zones(&[
            ("intel-rapl:0", Some("package-0"), "1000", Some("262143328850")),
            ("intel-rapl:1", Some("psys"), "90000", Some("262143328850")),
            ("intel-rapl:2", Some("package-1"), "2000", Some("65532610987")),
            ("intel-rapl:3", Some("dram"), "30000", Some("65532610987")),
            ("intel-rapl:0:0", Some("core"), "700", Some("262143328850")),
            ("intel-rapl:0:1", Some("dram"), "800", Some("65532610987")),
            ("intel-rapl:2:0", Some("core"), "900", Some("262143328850")),
            ("intel-rapl-mmio:0", Some("package-0"), "1000", Some("262143328850")),
        ])
    }

    /// The figure and the probe take the package zones and nothing else. On
    /// a tree with two packages, `psys`, a top-level `dram` zone, subzones and
    /// an MMIO interface: the reader holds the two packages, in zone order;
    /// the liveness sample names those two; a span's figure is their rise
    /// alone, although every other zone rose too; a package wrapping at its own
    /// range is corrected at that range. And the real probe is Live while the
    /// two packages advance with `psys` and `dram` holding, Frozen while
    /// `psys`, `dram` and one package advance with the other package holding
    /// (each advancing at every tick of the probe, [`rapl_status_ticking`]).
    #[test]
    fn rapl_sums_and_probes_the_package_zones_only() {
        #[cfg(target_os = "macos")]
        let _hw = ioreport_hw_lock();
        let tree = two_sockets_with_psys_and_dram();
        let r = Rapl::open_in(&tree.root).expect("a tree with two package zones opens");
        let opened: Vec<_> = r.packages.iter().map(|p| (p.path.strip_prefix(&tree.root).unwrap().to_owned(), p.range)).collect();
        assert_eq!(
            opened,
            [
                (std::path::PathBuf::from("intel-rapl:0/energy_uj"), Some(262_143_328_850)),
                (std::path::PathBuf::from("intel-rapl:2/energy_uj"), Some(65_532_610_987)),
            ],
            "the reader did not hold exactly the two package zones"
        );
        let sample = r.liveness_sample().expect("the packages read");
        let probed: Vec<(&str, i64)> = sample.iter().map(|(k, v)| (k.name.as_str(), *v)).collect();
        assert_eq!(probed, [("intel-rapl:0", 1_000), ("intel-rapl:2", 2_000)], "the probe watched other zones");

        let meter = Meter::Rapl(r);
        let (_, e) = meter.measure(|| {
            tree.write_zone("intel-rapl:0", "4000");
            tree.write_zone("intel-rapl:1", "190000");
            tree.write_zone("intel-rapl:2", "7000");
            tree.write_zone("intel-rapl:3", "80000");
            tree.write_zone("intel-rapl:0:0", "2700");
            tree.write_zone("intel-rapl:0:1", "1800");
            tree.write_zone("intel-rapl-mmio:0", "4000");
        });
        assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(8_000)), "not the packages' rise alone: {e:?}");
        // Package 1 wraps at its own range, 65,532,610,987 µJ, as psys and
        // dram wrap too: 65,532,600,000 -> 500 is 11,487 µJ, plus package 0's
        // 1,000.
        tree.write_zone("intel-rapl:2", "65532600000");
        let (_, e) = meter.measure(|| {
            tree.write_zone("intel-rapl:0", "5000");
            tree.write_zone("intel-rapl:2", "500");
            tree.write_zone("intel-rapl:1", "10");
            tree.write_zone("intel-rapl:3", "10");
        });
        assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(12_487)), "{e:?}");
        drop(meter);

        /// The probe on `tree`, the zones in `advancing` rising by 4 mJ at
        /// every tick ([`rapl_status_ticking`]).
        fn probe_advancing(tree: &FakePowercap, advancing: &[&str]) -> CounterStatus {
            let mut uj: u64 = 100_000;
            let status = rapl_status_ticking(tree, || {
                uj += 4_000;
                for dir in advancing {
                    tree.write_zone(dir, &uj.to_string());
                }
            });
            eprintln!("rapl probe: zones {advancing:?} advancing, the rest holding -> {status:?}");
            status
        }
        let tree = two_sockets_with_psys_and_dram();
        assert_eq!(
            probe_advancing(&tree, &["intel-rapl:0", "intel-rapl:2"]),
            CounterStatus::Live,
            "both packages advancing, psys and dram holding, was not live"
        );
        let tree = two_sockets_with_psys_and_dram();
        assert_eq!(
            probe_advancing(&tree, &["intel-rapl:0", "intel-rapl:1", "intel-rapl:3", "intel-rapl-mmio:0"]),
            CounterStatus::Frozen,
            "package 1 holding beside a live psys, dram and package 0 was not declined"
        );
    }

    /// **A counter this process cannot read is not an absent counter.**
    ///
    /// `Rapl::open` returns `None` for a missing tree and for a root-only
    /// `energy_uj` alike, and `survey` reported both as `Absent` — "this host
    /// has no such silicon". On a representative Linux host `energy_uj`
    /// carries mode 0440 root:energy, so an unprivileged reader gets `EACCES`
    /// from a file that is plainly there.
    ///
    /// The permission is injected rather than applied with `chmod`, which
    /// would prove nothing in a container running as root.
    #[test]
    fn a_rapl_counter_needing_privilege_is_not_reported_absent() {
        let tree = FakePowercap::new(&["1000", "2000"]);
        let denied = |p: &std::path::Path| -> std::io::Result<String> {
            if p.ends_with("energy_uj") {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::PermissionDenied,
                    "EACCES",
                ));
            }
            std::fs::read_to_string(p)
        };

        // The discriminating pair: the same tree, read two ways.
        assert_eq!(
            rapl_access_in(&tree.root),
            RaplAccess::Readable,
            "a readable package zone is readable"
        );
        assert_eq!(
            rapl_access_with(&tree.root, denied),
            RaplAccess::NeedsPrivilege,
            "a package zone whose energy_uj is root-only is a privilege gap, not absent hardware"
        );

        // And the fact `Rapl::open` erases: both reads leave it unable to open,
        // which is why the access question has to be asked separately.
        assert!(Rapl::open_in(&tree.root).is_some(), "the readable tree opens");
    }

    /// The mapping the whole fix turns on, and it was unpinned until a
    /// mutation flipping it back to `Absent` broke no test at all.
    ///
    /// `NeedsPrivilege` must survive **every** liveness answer: the probe
    /// cannot observe a counter it cannot open, so a `Unavailable` reading
    /// beside an unreadable counter says nothing about the hardware.
    #[test]
    fn a_privilege_gap_is_reported_as_such_by_the_survey() {
        for counter in
            [CounterStatus::Live, CounterStatus::Unavailable, CounterStatus::Frozen]
        {
            assert_eq!(
                rapl_fabric_status(RaplAccess::NeedsPrivilege, counter),
                FabricStatus::NeedsPrivilege,
                "a counter that cannot be read is not absent hardware, whatever \
                 the probe says ({counter:?})"
            );
        }

        // Only an absent interface is `Absent`.
        assert_eq!(
            rapl_fabric_status(RaplAccess::NoInterface, CounterStatus::Unavailable),
            FabricStatus::Absent
        );

        // And a readable counter is graded on its liveness as before.
        assert_eq!(
            rapl_fabric_status(RaplAccess::Readable, CounterStatus::Live),
            FabricStatus::Live {
                attribution: Attribution::Machine,
                resolution_ns: Some(1_000_000)
            }
        );
        assert_eq!(
            rapl_fabric_status(RaplAccess::Readable, CounterStatus::Frozen),
            FabricStatus::Frozen
        );
        assert_eq!(
            rapl_fabric_status(RaplAccess::Readable, CounterStatus::Unavailable),
            FabricStatus::Absent
        );

        // `NeedsPrivilege` excuses nothing: it is not `NoCounterExists`.
        assert_ne!(
            rapl_fabric_status(RaplAccess::NeedsPrivilege, CounterStatus::Unavailable),
            FabricStatus::NoCounterExists,
            "a permission gap must never read as a hardware exemption"
        );
    }

    /// A zone this process cannot even identify may be a package, so an
    /// unreadable `name` is a privilege gap too rather than a skipped zone.
    #[test]
    fn a_zone_whose_name_needs_privilege_is_a_privilege_gap() {
        let tree = FakePowercap::new(&["1000"]);
        let name_denied = |p: &std::path::Path| -> std::io::Result<String> {
            if p.ends_with("name") {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::PermissionDenied,
                    "EACCES",
                ));
            }
            std::fs::read_to_string(p)
        };
        assert_eq!(rapl_access_with(&tree.root, name_denied), RaplAccess::NeedsPrivilege);
    }

    /// One unreadable package beside a readable one still decides the answer:
    /// a figure claims the whole CPU, so it is every package zone or none.
    #[test]
    fn one_package_needing_privilege_decides_the_whole_answer() {
        let tree = FakePowercap::new(&["1000", "2000"]);
        let one_denied = |p: &std::path::Path| -> std::io::Result<String> {
            if p.ends_with("energy_uj") && p.to_string_lossy().contains("intel-rapl:1") {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::PermissionDenied,
                    "EACCES",
                ));
            }
            std::fs::read_to_string(p)
        };
        assert_eq!(
            rapl_access_with(&tree.root, one_denied),
            RaplAccess::NeedsPrivilege,
            "a readable package does not excuse one that is not"
        );
    }

    /// No tree, and no package zone in a tree, are both an absent interface —
    /// which is the one case `Absent` really describes.
    #[test]
    fn an_absent_interface_is_distinguished_from_a_privilege_gap() {
        let tree = FakePowercap::new(&["1000"]);
        assert_eq!(
            rapl_access_in(&tree.root.join("no-such-dir")),
            RaplAccess::NoInterface,
            "a missing powercap tree exposes no interface"
        );

        let psys_only = FakePowercap::with_zones(&[
            ("intel-rapl:0", Some("psys"), "90000", Some("262143328850")),
            ("intel-rapl:1", Some("dram"), "30000", Some("65532610987")),
        ]);
        assert_eq!(
            rapl_access_in(&psys_only.root),
            RaplAccess::NoInterface,
            "a tree with no package zone exposes no package interface"
        );
    }

    /// Accessibility is not liveness. A readable counter that is frozen is
    /// still readable — the two questions have separate answers and separate
    /// statuses.
    #[test]
    fn accessibility_is_not_liveness() {
        let frozen = FakePowercap::new(&["1000"]);
        assert_eq!(rapl_access_in(&frozen.root), RaplAccess::Readable);
        // The counter never moves, so the liveness probe declines it.
        assert_eq!(rapl_status_on(|| Rapl::open_in(&frozen.root)), CounterStatus::Frozen);
    }

    /// No package zone, no RAPL counter: a host exposing only `psys` (and a
    /// `dram` zone) is Unavailable without a probe, never a figure. Nor does
    /// the reader open with a package left out: one whose `energy_uj` does
    /// not read, or a top-level zone whose `name` does not (it may be a
    /// package). A package whose range does not read opens, and a span over
    /// which it fell is the default-power estimate, not an invented reading.
    #[test]
    fn a_rapl_figure_never_leaves_a_package_out_or_takes_another_zone() {
        let psys_only = FakePowercap::with_zones(&[
            ("intel-rapl:0", Some("psys"), "90000", Some("262143328850")),
            ("intel-rapl:1", Some("dram"), "30000", Some("65532610987")),
            ("intel-rapl:0:0", Some("package-0"), "1000", Some("262143328850")),
        ]);
        assert!(Rapl::open_in(&psys_only.root).is_none(), "a tree with no package zone opened");
        let started = std::time::Instant::now();
        assert_eq!(rapl_status_on(|| Rapl::open_in(&psys_only.root)), CounterStatus::Unavailable);
        assert!(started.elapsed() < Duration::from_millis(250), "a tree with no package burned {:?}", started.elapsed());

        let package_unreadable = FakePowercap::with_zones(&[
            ("intel-rapl:0", Some("package-0"), "1000", Some("262143328850")),
            ("intel-rapl:1", Some("package-1"), "not a number", Some("262143328850")),
        ]);
        assert!(Rapl::open_in(&package_unreadable.root).is_none(), "a package that does not read was left out");
        let unnamed = FakePowercap::with_zones(&[
            ("intel-rapl:0", Some("package-0"), "1000", Some("262143328850")),
            ("intel-rapl:1", None, "2000", Some("262143328850")),
        ]);
        assert!(Rapl::open_in(&unnamed.root).is_none(), "a zone whose name does not read was left out");

        let no_range = FakePowercap::with_zones(&[("intel-rapl:0", Some("package-0"), "900", None)]);
        let meter = Meter::Rapl(Rapl::open_in(&no_range.root).expect("a package with no range opens"));
        let (_, e) = meter.measure(|| no_range.write(0, "950"));
        assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(50)), "{e:?}");
        let (_, e) = meter.measure(|| no_range.write(0, "50"));
        assert_eq!((e.provenance, e.measured_uj), (Provenance::Estimator, None), "a fall with no range: {e:?}");
        e.check_provenance().unwrap();
    }

    /// The MSR path, over fake device files: a regular file whose bytes at a
    /// register's offset are that register is read exactly as the `msr`
    /// driver's device file is.
    #[cfg(unix)]
    mod msr {
        use super::*;
        use std::os::unix::fs::FileExt;

        const INTEL: &str = "processor\t: 0\nvendor_id\t: GenuineIntel\ncpu family\t: 6\nmodel\t\t: 85\n";
        const AMD: &str = "processor\t: 0\nvendor_id\t: AuthenticAMD\ncpu family\t: 26\nmodel\t\t: 112\n";
        /// A power-unit MSR whose energy-status unit (bits 12:8) is 2^-14 J,
        /// the common Intel value (0xA0E03).
        const UNIT_14: u64 = 0xA_0E03;
        /// 2^-16 J, as on AMD Zen.
        const UNIT_16: u64 = 0x10 << 8;

        /// A fake filesystem root, removed when dropped: its `proc/cpuinfo`,
        /// each CPU's `physical_package_id`, and the CPUs' `dev/cpu/<n>/msr`
        /// files.
        struct MsrRoot(std::path::PathBuf);

        impl MsrRoot {
            /// `package_of_cpu[n]` is CPU `n`'s package.
            fn new(cpuinfo: &str, package_of_cpu: &[u32]) -> Self {
                static N: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
                let n = N.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
                let root = std::env::temp_dir().join(format!("jcp-energy-msr-{}-{n}", std::process::id()));
                let _ = std::fs::remove_dir_all(&root);
                std::fs::create_dir_all(root.join("proc")).expect("create proc");
                std::fs::write(root.join("proc/cpuinfo"), cpuinfo).expect("write cpuinfo");
                for (cpu, package) in package_of_cpu.iter().enumerate() {
                    let topology = root.join(format!("sys/devices/system/cpu/cpu{cpu}/topology"));
                    std::fs::create_dir_all(&topology).expect("create a CPU's topology");
                    std::fs::write(topology.join("physical_package_id"), format!("{package}\n")).expect("write its package");
                }
                Self(root)
            }

            /// List CPU `cpu` on die `die` of its package (`topology/die_id`).
            fn die(&self, cpu: u32, die: u32) -> &Self {
                let topology = self.0.join(format!("sys/devices/system/cpu/cpu{cpu}/topology"));
                std::fs::write(topology.join("die_id"), format!("{die}\n")).expect("write its die");
                self
            }

            /// Set CPU `cpu`'s MSR `register` to `value`.
            fn set(&self, cpu: u32, register: u64, value: u64) -> &Self {
                let dir = self.0.join(format!("dev/cpu/{cpu}"));
                std::fs::create_dir_all(&dir).expect("create dev/cpu/<n>");
                let file = std::fs::OpenOptions::new()
                    .create(true)
                    .truncate(false)
                    .write(true)
                    .open(dir.join("msr"))
                    .expect("open the fake msr file");
                file.write_all_at(&value.to_le_bytes(), register).expect("write the register");
                self
            }

            /// An Intel host whose CPUs `cpus` each have the 2^-14 J unit and
            /// the energy-status count `count`.
            fn intel(package_of_cpu: &[u32], cpus: &[u32], count: u64) -> Self {
                let host = Self::new(INTEL, package_of_cpu);
                for &cpu in cpus {
                    host.set(cpu, MSR_RAPL_POWER_UNIT, UNIT_14).set(cpu, MSR_PKG_ENERGY_STATUS, count);
                }
                host
            }
        }

        impl Drop for MsrRoot {
            fn drop(&mut self) {
                let _ = std::fs::remove_dir_all(&self.0);
            }
        }

        /// A powercap tree that lists no package zone: only a subzone, which
        /// is never a package.
        fn no_package_zone() -> FakePowercap {
            FakePowercap::new(&[])
        }

        /// A two-socket Intel host (CPUs 0–1 on package 0, 2–3 on package 1)
        /// with no powercap package zone: each package read on its first CPU,
        /// at its unit, summed, a span over it a whole hardware reading.
        #[test]
        fn a_two_socket_host_without_powercap_reads_each_packages_msr() {
            let host = MsrRoot::new(INTEL, &[0, 0, 1, 1]);
            host.set(0, MSR_RAPL_POWER_UNIT, UNIT_14).set(0, MSR_PKG_ENERGY_STATUS, 1_000);
            host.set(2, MSR_RAPL_POWER_UNIT, UNIT_14).set(2, MSR_PKG_ENERGY_STATUS, 2_000);
            let powercap = no_package_zone();
            let r = Rapl::open_from(&powercap.root, Some(&host.0)).expect("the MSRs open where powercap lists no package");
            let devices: Vec<_> = r.packages.iter().map(|p| (p.rail.as_str(), p.path.clone())).collect();
            assert_eq!(
                devices,
                vec![("package-0 msr", host.0.join("dev/cpu/0/msr")), ("package-1 msr", host.0.join("dev/cpu/2/msr"))],
                "package 1 is read on its first CPU, 2"
            );
            assert!(r.packages.iter().all(|p| p.msr == Some(Msr { register: MSR_PKG_ENERGY_STATUS, unit_shift: 14 })));
            assert!(r.packages.iter().all(|p| p.range == Some(262_144_000_000)), "2^32 counts of 2^-14 J");
            // 1,000 and 2,000 counts of 61.035 µJ, each floored.
            assert_eq!(r.read(), Some(vec![61_035, 122_070]));
            let sample = r.liveness_sample().expect("the packages read");
            let probed: Vec<(&str, i64)> = sample.iter().map(|(k, v)| (k.name.as_str(), *v)).collect();
            assert_eq!(probed, [("package-0 msr", 61_035), ("package-1 msr", 122_070)]);

            let meter = Meter::Rapl(r);
            let (_, e) = meter.measure(|| {
                host.set(0, MSR_PKG_ENERGY_STATUS, 3_000).set(2, MSR_PKG_ENERGY_STATUS, 2_100);
            });
            // 183,105 - 61,035 on package 0, 128,173 - 122,070 on package 1.
            assert_eq!((e.provenance, e.measured_uj, e.is_whole()), (Provenance::HwShunt, Some(128_173), true), "{e:?}");
            e.check_provenance().unwrap();
        }

        /// Intel's RAPL MSRs are die-scope: a package with two dies is two
        /// counter domains, each read on its own first CPU, and summed; a
        /// package with one die stays `package-<n> msr`. Every domain or none,
        /// and the access answer is over the same domains.
        #[test]
        fn an_intel_package_with_two_dies_is_read_on_each_die() {
            // Package 0: CPUs 0–1 on die 0, 2–3 on die 1. Package 1: CPUs 4–5, one die.
            let host = MsrRoot::new(INTEL, &[0, 0, 0, 0, 1, 1]);
            for (cpu, die) in [(0, 0), (1, 0), (2, 1), (3, 1), (4, 0), (5, 0)] {
                host.die(cpu, die);
            }
            for (cpu, count) in [(0, 1_000), (2, 2_000), (4, 4_000)] {
                host.set(cpu, MSR_RAPL_POWER_UNIT, UNIT_14).set(cpu, MSR_PKG_ENERGY_STATUS, count);
            }
            let r = Rapl::open_from(&no_package_zone().root, Some(&host.0)).expect("every die's MSR reads");
            let domains: Vec<_> = r.packages.iter().map(|p| (p.rail.as_str(), p.path.clone())).collect();
            assert_eq!(
                domains,
                vec![
                    ("package-0-die-0 msr", host.0.join("dev/cpu/0/msr")),
                    ("package-0-die-1 msr", host.0.join("dev/cpu/2/msr")),
                    ("package-1 msr", host.0.join("dev/cpu/4/msr")),
                ],
                "die 1 is read on its own first CPU, 2"
            );
            assert_eq!(r.read(), Some(vec![61_035, 122_070, 244_140]));
            let meter = Meter::Rapl(r);
            let (_, e) = meter.measure(|| {
                host.set(0, MSR_PKG_ENERGY_STATUS, 2_000).set(2, MSR_PKG_ENERGY_STATUS, 3_000);
            });
            // 61,035 on die 0 and 61,035 on die 1 (122,070 -> 183,105).
            assert_eq!((e.provenance, e.measured_uj), (Provenance::HwShunt, Some(122_070)), "both dies summed: {e:?}");

            let die_1_denied = |p: &std::path::Path, r: u64| -> std::io::Result<u64> {
                if p.ends_with("cpu/2/msr") {
                    Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "EPERM"))
                } else {
                    read_msr(p, r)
                }
            };
            assert_eq!(msr_access_with(&host.0, read_msr), RaplAccess::Readable);
            assert_eq!(msr_access_with(&host.0, die_1_denied), RaplAccess::NeedsPrivilege, "die 1 is a domain of its own");

            let one_die_missing = MsrRoot::new(INTEL, &[0, 0]);
            one_die_missing.die(0, 0).die(1, 1);
            one_die_missing.set(0, MSR_RAPL_POWER_UNIT, UNIT_14).set(0, MSR_PKG_ENERGY_STATUS, 5);
            assert!(
                Rapl::open_from(&no_package_zone().root, Some(&one_die_missing.0)).is_none(),
                "die 1 has no device file: a figure without it would under-count the package"
            );
        }

        /// AMD's and Hygon's counter is per package: CPUs on different dies of
        /// one package are one domain, read on the package's first CPU.
        #[test]
        fn an_amd_package_is_one_domain_whatever_its_dies() {
            let host = MsrRoot::new(AMD, &[0, 0, 0, 0]);
            host.die(0, 0).die(1, 0).die(2, 1).die(3, 1);
            host.set(0, MSR_AMD_RAPL_POWER_UNIT, UNIT_16).set(0, MSR_AMD_PKG_ENERGY_STATUS, 65_536);
            let r = Rapl::open_from(&no_package_zone().root, Some(&host.0)).expect("the package's MSR reads");
            let domains: Vec<_> = r.packages.iter().map(|p| (p.rail.as_str(), p.path.clone())).collect();
            assert_eq!(domains, vec![("package-0 msr", host.0.join("dev/cpu/0/msr"))], "one per-package counter");
            assert_eq!(msr_access_with(&host.0, read_msr), RaplAccess::Readable, "CPU 2's die is not a domain");
        }

        /// An Intel host whose kernel lists no `die_id` is read per package, as
        /// before: each package one domain, `package-<n> msr`.
        #[test]
        fn an_intel_host_without_die_ids_is_read_per_package() {
            let host = MsrRoot::intel(&[0, 0, 1, 1], &[0, 2], 1_000);
            let r = Rapl::open_from(&no_package_zone().root, Some(&host.0)).expect("opens");
            let rails: Vec<&str> = r.packages.iter().map(|p| p.rail.as_str()).collect();
            assert_eq!(rails, ["package-0 msr", "package-1 msr"]);
            assert_eq!(r.read(), Some(vec![61_035, 61_035]));
        }

        /// The 32-bit count wraps at 2^32 counts, so the µJ figure wraps at
        /// that range, losing at most a microjoule; bits above the count are
        /// not energy.
        #[test]
        fn the_count_wraps_at_2_to_the_32_counts() {
            let host = MsrRoot::intel(&[0], &[0], 0xFFFF_FFF0);
            let r = Rapl::open_from(&no_package_zone().root, Some(&host.0)).expect("opens");
            let before = r.read().expect("reads");
            host.set(0, MSR_PKG_ENERGY_STATUS, 0xABCD_0000_0000_0010);
            let after = r.read().expect("reads");
            // 32 counts of 61.035 µJ is 1,953.125 µJ.
            assert_eq!(r.delta(&before, &after), Some(1_953));
        }

        /// AMD Zen reads its own power-unit and energy-status MSRs.
        #[test]
        fn amd_zen_reads_its_own_msrs() {
            let host = MsrRoot::new(AMD, &[0, 0]);
            host.set(0, MSR_AMD_RAPL_POWER_UNIT, UNIT_16).set(0, MSR_AMD_PKG_ENERGY_STATUS, 65_536);
            let r = Rapl::open_from(&no_package_zone().root, Some(&host.0)).expect("opens");
            assert_eq!(r.packages.len(), 1);
            assert_eq!(r.packages[0].msr, Some(Msr { register: MSR_AMD_PKG_ENERGY_STATUS, unit_shift: 16 }));
            assert_eq!(r.read(), Some(vec![1_000_000]), "65,536 counts of 2^-16 J is one joule");
        }

        /// No MSR reader where the power-unit MSR reads a zero unit (a
        /// hypervisor's stand-in, seen under KVM), where the CPU is not one
        /// whose MSRs are known, where a package's device file is missing, or
        /// where the energy-status register does not read.
        #[test]
        fn a_zero_unit_an_unknown_cpu_or_a_missing_device_is_no_counter() {
            let powercap = no_package_zone();
            let opens = |host: &MsrRoot| Rapl::open_from(&powercap.root, Some(&host.0)).is_some();

            let zero = MsrRoot::new(INTEL, &[0]);
            zero.set(0, MSR_RAPL_POWER_UNIT, 0).set(0, MSR_PKG_ENERGY_STATUS, 0);
            assert!(!opens(&zero), "a zero unit");

            let arm = MsrRoot::new("processor\t: 0\nCPU implementer\t: 0x41\n", &[0]);
            assert!(!opens(&arm), "no vendor_id");

            let netburst = MsrRoot::new("vendor_id\t: GenuineIntel\ncpu family\t: 15\n", &[0]);
            netburst.set(0, MSR_RAPL_POWER_UNIT, UNIT_14).set(0, MSR_PKG_ENERGY_STATUS, 5);
            assert!(!opens(&netburst), "not family 6");

            let missing = MsrRoot::intel(&[0, 1], &[0], 5);
            assert!(!opens(&missing), "package 1 has no device file");

            let no_counter = MsrRoot::new(INTEL, &[0]);
            no_counter.set(0, MSR_RAPL_POWER_UNIT, UNIT_14);
            assert!(!opens(&no_counter), "the energy-status register does not read");

            let no_topology = MsrRoot::new(INTEL, &[]);
            assert!(!opens(&no_topology), "no CPU topology");
        }

        /// Powercap zones are preferred, and the MSRs are read only where
        /// powercap lists no package: not where it lists one this process
        /// cannot read, and not off Linux (no root to read under).
        #[test]
        fn powercap_is_preferred_and_the_msrs_are_the_fallback() {
            let host = MsrRoot::intel(&[0], &[0], 5);
            let zones = FakePowercap::new(&["1000", "2000"]);
            let preferred = Rapl::open_from(&zones.root, Some(&host.0)).expect("powercap opens");
            assert_eq!(preferred.packages.len(), 2);
            assert!(preferred.packages.iter().all(|p| p.msr.is_none()), "powercap's zones were listed");

            let fallback = Rapl::open_from(&no_package_zone().root, Some(&host.0)).expect("the MSR opens");
            assert!(fallback.packages[0].msr.is_some(), "powercap listed no package, so the MSR is read");
            let absent = no_package_zone();
            assert!(Rapl::open_from(&absent.root.join("no-such-dir"), Some(&host.0)).is_some(), "no powercap tree at all");

            let garbled = FakePowercap::new(&["not a number"]);
            assert!(Rapl::open_from(&garbled.root, Some(&host.0)).is_none(), "a listed package that does not read fell back");
            assert!(Rapl::open_from(&no_package_zone().root, None).is_none(), "no root to read MSRs under");
        }

        /// The probe over the production opener, the CPU-burning tick and the
        /// real clock on MSR packages: live when every package's count keeps
        /// advancing, frozen when one holds.
        #[test]
        fn the_production_probe_judges_msr_packages_by_the_same_rule() {
            #[cfg(target_os = "macos")]
            let _hw = ioreport_hw_lock();
            let run = |moving: &[u32]| {
                let host = MsrRoot::intel(&[0, 1], &[0, 1], 1_000_000);
                let powercap = no_package_zone();
                let mut count = 1_000_000u64;
                crate::liveness::status_of(
                    crate::liveness::probe(
                        || Rapl::open_from(&powercap.root, Some(&host.0)),
                        Rapl::liveness_sample,
                        || {
                            crate::liveness::burn_tick();
                            count += 18_432; // 45 W over a 25 ms tick, in 61.035 µJ counts
                            for &cpu in moving {
                                host.set(cpu, MSR_PKG_ENERGY_STATUS, count);
                            }
                        },
                        std::time::Instant::now,
                        crate::liveness::BUDGET,
                    )
                    .as_ref(),
                )
            };
            assert_eq!(run(&[0, 1]), CounterStatus::Live);
            assert_eq!(run(&[0]), CounterStatus::Frozen, "package 1 held its count");
        }

        /// An MSR this process may not open is a privilege gap, not absent
        /// hardware, and one such package decides the answer beside a readable
        /// one. No device file, a zero unit or an unknown CPU is no interface.
        /// Where powercap has a package zone, its answer stands and no MSR is
        /// read. The permission is injected, as for powercap: `chmod` proves
        /// nothing under root.
        #[test]
        fn an_msr_host_needing_privilege_is_not_reported_absent() {
            let denied = |_: &std::path::Path, _: u64| -> std::io::Result<u64> {
                Err(std::io::Error::new(std::io::ErrorKind::PermissionDenied, "EPERM"))
            };
            let none = no_package_zone();
            let host = MsrRoot::intel(&[0, 0, 1, 1], &[0, 2], 1_000);
            assert_eq!(rapl_access_from(&none.root, Some(&host.0), read_msr), RaplAccess::Readable);
            assert_eq!(rapl_access_from(&none.root, Some(&host.0), denied), RaplAccess::NeedsPrivilege);
            let package_1_denied = |p: &std::path::Path, r: u64| {
                if p.ends_with("cpu/2/msr") { denied(p, r) } else { read_msr(p, r) }
            };
            assert_eq!(msr_access_with(&host.0, package_1_denied), RaplAccess::NeedsPrivilege, "one package decides");
            assert_eq!(rapl_access_from(&none.root, None, denied), RaplAccess::NoInterface, "no root, no MSR");

            let missing = MsrRoot::intel(&[0, 1], &[0], 1_000);
            assert_eq!(msr_access_with(&missing.0, read_msr), RaplAccess::NoInterface, "no device file for package 1");
            let zero = MsrRoot::new(INTEL, &[0]);
            zero.set(0, MSR_RAPL_POWER_UNIT, 0).set(0, MSR_PKG_ENERGY_STATUS, 0);
            assert_eq!(msr_access_with(&zero.0, read_msr), RaplAccess::NoInterface, "a zero unit");
            let arm = MsrRoot::new("processor\t: 0\n", &[0]);
            assert_eq!(msr_access_with(&arm.0, denied), RaplAccess::NoInterface, "a CPU whose MSRs are unknown");

            let zones = FakePowercap::new(&["1000"]);
            let untouched = |_: &std::path::Path, _: u64| -> std::io::Result<u64> { panic!("an MSR was read beside a package zone") };
            assert_eq!(rapl_access_from(&zones.root, Some(&host.0), untouched), RaplAccess::Readable);
            assert_eq!(rapl_fabric_status(RaplAccess::NeedsPrivilege, CounterStatus::Unavailable), FabricStatus::NeedsPrivilege);
        }
    }
}

#[cfg(test)]
mod fabric_tests {
    use super::*;

    /// A sum must say what it is a sum of, so a caller cannot imply coverage
    /// it does not have.
    #[test]
    fn a_total_names_the_fabrics_it_covers() {
        let r = [
            FabricEnergy {
                fabric: Fabric::Cpu,
                uj: 7_536,
                attribution: Attribution::Process,
                span_ns: 2_606_000_000,
            },
            FabricEnergy {
                fabric: Fabric::Gpu,
                uj: 96_591,
                attribution: Attribution::Machine,
                span_ns: 2_606_000_000,
            },
        ];
        // The measured figure for one typed decision on an M5 Max.
        assert_eq!(total_uj(&r), (104_127, vec![Fabric::Cpu, Fabric::Gpu]));
        // An empty set totals zero and claims nothing.
        assert_eq!(total_uj(&[]), (0, vec![]));
    }

    /// The two counters read disjoint fabrics, which is what makes summing
    /// them sound; the names are stable because a receipt carries them.
    #[test]
    fn fabric_names_are_stable() {
        assert_eq!(Fabric::Cpu.as_str(), "cpu");
        assert_eq!(Fabric::Gpu.as_str(), "gpu");
        assert_eq!(Fabric::Npu.as_str(), "npu");
    }

    /// On a host that exposes them, a span reports a figure per fabric, each
    /// carrying its own attribution — and the GPU figure is machine-wide, so
    /// it must never be reported as this process's.
    #[cfg(target_os = "macos")]
    #[test]
    fn a_span_reports_each_fabric_with_its_own_attribution() {
        let m = FabricMeter::detect();
        let readable = m.readable();
        if readable.is_empty() {
            println!("SKIPPED: this host exposes no per-fabric counter");
            return;
        }
        let (out, readings) = m.measure(|| {
            // Enough CPU work that the process counter has something to show.
            let mut x = 0u64;
            for i in 0..8_000_000u64 {
                x = x.wrapping_add(i ^ (x >> 7));
            }
            x
        });
        assert_ne!(out, 0);
        for r in &readings {
            assert!(r.span_ns > 0, "a span must have a duration");
            match r.fabric {
                Fabric::Cpu => assert_eq!(r.attribution, Attribution::Process),
                // Every other fabric here is read from an SoC rail, which
                // counts the silicon and cannot tell one process from another.
                _ => assert_eq!(
                    r.attribution,
                    Attribution::Machine,
                    "an SoC rail cannot attribute to a process"
                ),
            }
        }
        // CPU work must show on the CPU fabric where that counter is live.
        if readable.contains(&(Fabric::Cpu, Attribution::Process)) {
            let cpu = readings.iter().find(|r| r.fabric == Fabric::Cpu).expect("a cpu figure");
            assert!(cpu.uj > 0, "8M iterations of CPU work metered as free: {cpu:?}");
        }
        println!("per-fabric over the span: {readings:?} -> total {:?}", total_uj(&readings));
    }
}

#[cfg(test)]
mod survey_tests {
    use super::*;

    /// The survey must never say two different things about one
    /// (fabric, source) pair, or a reader cannot act on it.
    #[test]
    fn the_survey_names_each_fabric_source_pair_once() {
        let s = survey();
        assert!(!s.is_empty());
        let mut seen: Vec<(Fabric, FabricSource)> = Vec::new();
        for c in &s {
            let key = (c.fabric, c.source);
            assert!(!seen.contains(&key), "{:?}/{:?} appears twice", c.fabric, c.source);
            seen.push(key);
            assert!(!c.note.is_empty(), "{:?}/{:?} has no note", c.fabric, c.source);
        }
    }

    /// `Absent` is a claim about the host and `NotImplemented` is a claim about
    /// us. A source we have no reader for must never be reported as `Live`,
    /// because that would be a figure from nowhere.
    #[test]
    fn a_source_without_a_backend_is_never_live() {
        for c in survey() {
            if !c.source.has_backend() {
                assert!(
                    !matches!(c.status, FabricStatus::Live { .. }),
                    "{:?}/{:?} is Live with no backend",
                    c.fabric,
                    c.source
                );
            }
        }
    }

    /// The refusal the whole survey exists to support: an undeclared update
    /// period can never grade a span, and a declared one grades only a span at
    /// least that long.
    #[test]
    fn an_undeclared_update_period_can_never_grade_a_span() {
        let undeclared = FabricStatus::Live {
            attribution: Attribution::Machine,
            resolution_ns: None,
        };
        for span in [0u128, 1_000, 1_000_000, 1_000_000_000, u128::MAX] {
            assert!(
                !undeclared.may_grade_span(span),
                "an uncharacterised counter graded a {span} ns span"
            );
        }

        let declared = FabricStatus::Live {
            attribution: Attribution::Machine,
            resolution_ns: Some(10_000_000), // 10 ms
        };
        // The 11.85 ms of one typed decision is above a 10 ms period; the
        // 0.5 ms that under-reported by 95.4% in the published study is not.
        assert!(declared.may_grade_span(11_850_000));
        assert!(declared.may_grade_span(10_000_000), "the boundary is inclusive");
        assert!(!declared.may_grade_span(9_999_999));
        assert!(!declared.may_grade_span(500_000));

        // No negative status grades anything, whatever the span.
        for st in [
            FabricStatus::Frozen,
            FabricStatus::Absent,
            FabricStatus::NeedsPrivilege,
            FabricStatus::NoCounterExists,
            FabricStatus::NotImplemented,
        ] {
            assert!(!st.may_grade_span(u128::MAX), "{st:?} graded a span");
        }
    }

    /// Source names are stable and distinct: a receipt carries them, so two
    /// sources sharing a name would make two different domains look like one.
    #[test]
    fn source_names_are_stable_and_distinct() {
        let all = [
            FabricSource::ProcRusage,
            FabricSource::IoReport,
            FabricSource::Powermetrics,
            FabricSource::Rapl,
            FabricSource::Nvml,
            FabricSource::RocmSmi,
            FabricSource::LevelZero,
            FabricSource::TegraIna,
            FabricSource::QualcommQpt,
            FabricSource::AscendSmi,
            FabricSource::HabanaSmi,
            FabricSource::CambriconCnmon,
            FabricSource::ExternalMeter,
        ];
        let mut names: Vec<&str> = all.iter().map(|s| s.as_str()).collect();
        names.sort_unstable();
        let n = names.len();
        names.dedup();
        assert_eq!(names.len(), n, "two sources share a name");
        for f in Fabric::all() {
            assert!(!f.as_str().is_empty());
        }
    }

    /// Exactly one source attributes to a principal. If a second ever claims
    /// to, that is a real change and should be a deliberate one: an SoC rail
    /// counts silicon and cannot tell one process from another.
    #[test]
    fn only_the_per_process_counter_attributes_to_a_principal() {
        for c in survey() {
            if let FabricStatus::Live { attribution: Attribution::Process, .. } = c.status {
                assert_eq!(
                    c.source,
                    FabricSource::ProcRusage,
                    "{:?} claims per-process attribution",
                    c.source
                );
            }
        }
    }

    /// What this host can actually meter, printed. Not an assertion about the
    /// fleet — a record of the machine the test ran on.
    #[test]
    fn report_this_hosts_fabrics() {
        println!("{:<9} {:<16} {:<48} note", "fabric", "source", "status");
        for c in survey() {
            println!("{:<9} {:<16} {:<48} {}", c.fabric.as_str(), c.source.as_str(), format!("{:?}", c.status), c.note);
        }
    }
}

#[cfg(all(test, target_os = "macos"))]
mod process_counter_resolution {
    use super::*;

    /// The per-process CPU counter's declared period must be the measured one,
    /// and it must be strict enough to refuse the spans the measurement showed
    /// it cannot resolve.
    ///
    /// This is the counter our one principal-attributed figure comes from, so
    /// if its period were left undeclared, the only whole-coverage,
    /// process-attributed reading on Apple silicon could never be graded.
    #[test]
    fn the_per_process_counter_grades_only_spans_it_can_resolve() {
        let Some(cap) = survey()
            .into_iter()
            .find(|c| c.source == FabricSource::ProcRusage && c.fabric == Fabric::Cpu)
        else {
            panic!("the survey must name the per-process CPU counter");
        };
        let FabricStatus::Live { attribution, resolution_ns } = cap.status else {
            println!("SKIPPED: the per-process counter is not live on this host");
            return;
        };
        assert_eq!(attribution, Attribution::Process);
        assert_eq!(resolution_ns, Some(10_000_000), "the declared period is the measured one");

        // The spans the measurement showed it cannot resolve are refused.
        assert!(!cap.status.may_grade_span(50_000), "50 µs: measured 0% advancing");
        assert!(!cap.status.may_grade_span(500_000), "500 µs: measured 5% advancing");
        assert!(!cap.status.may_grade_span(1_000_000), "1 ms: measured 35% advancing");
        assert!(!cap.status.may_grade_span(5_000_000), "5 ms: 87%, below the declared period");

        // The GPU rail's declared period is the idle worst case, so a span
        // shorter than a second cannot be graded from it however busy the
        // fabric happened to be.
        if let Some(gpu) = survey()
            .into_iter()
            .find(|c| c.source == FabricSource::IoReport && c.fabric == Fabric::Gpu)
        {
            if let FabricStatus::Live { resolution_ns, .. } = gpu.status {
                assert_eq!(
                    resolution_ns,
                    Some(1_000_000_000),
                    "the GPU rail holds up to 992 ms at idle; a shorter declared period grades spans it never covered"
                );
                assert!(!gpu.status.may_grade_span(42_000_000), "42 ms was the max gap under load, not a safe span");
                assert!(!gpu.status.may_grade_span(992_000_000), "992 ms was the observed max hold");
                assert!(gpu.status.may_grade_span(2_606_000_000), "the 2.6 s span the figure was taken over");
            }
        }

        // And the span the morning's figure was actually taken over is graded:
        // 200 decisions over 2.606 s, which is why that figure stands.
        assert!(cap.status.may_grade_span(2_606_000_000));
        // A single 11.85 ms decision is above the period too, but one decision
        // is not how that figure was obtained — see the harness.
        assert!(cap.status.may_grade_span(11_850_000));
    }
}
