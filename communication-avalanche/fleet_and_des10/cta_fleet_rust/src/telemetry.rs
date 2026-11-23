use serde::Serialize;
use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread::{self, JoinHandle};
use std::time::{Duration, Instant};

#[derive(Clone, Debug, Default, Serialize)]
pub struct WindowTelemetry {
    pub elapsed_s: f64,
    pub board_metered: bool,
    // Physical shunt rails (NVIDIA Jetson AGX Thor INA238 + INA3221) -> measured_j
    pub l1_vin_ina238_measured_j: Option<f64>,
    pub l2_vdd_cpu_soc_mss_measured_j: Option<f64>,
    pub l2_vdd_gpu_measured_j: Option<f64>,
    pub l1_vin_sys_5v0_measured_j: Option<f64>,
    pub shunt_samples: usize,
    // On-chip / driver counters -> reported_j
    pub pkg_reported_j: Option<f64>,
    pub core_reported_j: Option<f64>,
    pub psys_reported_j: Option<f64>,
    pub amdgpu_ppt_reported_j: Option<f64>,
    pub darwin_ri_energy_reported_j: Option<f64>,
    pub win_nvml_gpu_reported_j: Option<f64>,
    // L3 activity counters
    pub cpu_time_ms: f64,
    pub win_process_cycles: Option<u64>,
    pub voluntary_ctxt_switches: u64,
    pub nonvoluntary_ctxt_switches: u64,
}

fn read_u64_trim(p: &Path) -> Option<u64> {
    fs::read_to_string(p).ok()?.trim().parse::<u64>().ok()
}

fn read_i64_trim(p: &Path) -> Option<i64> {
    fs::read_to_string(p).ok()?.trim().parse::<i64>().ok()
}

#[derive(Clone)]
struct LinuxHwPaths {
    rapl_pkg: Option<PathBuf>,
    rapl_core: Option<PathBuf>,
    rapl_psys: Option<PathBuf>,
    rapl_max_uj: u64,
    ina238_dir: Option<PathBuf>,
    ina3221_dir: Option<PathBuf>,
    amdgpu_power: Option<PathBuf>,
}

impl LinuxHwPaths {
    fn discover() -> Self {
        let p_pkg = PathBuf::from("/sys/class/powercap/intel-rapl:0/energy_uj");
        let p_core = PathBuf::from("/sys/class/powercap/intel-rapl:0:0/energy_uj");
        let p_psys = PathBuf::from("/sys/class/powercap/intel-rapl:1/energy_uj");
        let p_max = PathBuf::from("/sys/class/powercap/intel-rapl:0/max_energy_range_uj");
        let rapl_max_uj = read_u64_trim(&p_max).unwrap_or(262_143_328_850);

        let mut ina238_dir = None;
        let mut ina3221_dir = None;
        let mut amdgpu_power = None;
        let hwmon_root = Path::new("/sys/class/hwmon");
        if hwmon_root.exists() {
            if let Ok(entries) = fs::read_dir(hwmon_root) {
                let mut dirs: Vec<PathBuf> = entries.flatten().map(|e| e.path()).collect();
                dirs.sort();
                for h in dirs {
                    let nm = fs::read_to_string(h.join("name"))
                        .unwrap_or_default()
                        .trim()
                        .to_string();
                    if nm == "ina238" && h.join("power1_input").exists() {
                        ina238_dir = Some(h);
                    } else if nm == "ina3221" && h.join("in2_input").exists() {
                        ina3221_dir = Some(h);
                    } else if nm == "amdgpu" {
                        if h.join("power1_input").exists() {
                            amdgpu_power = Some(h.join("power1_input"));
                        } else if h.join("power1_average").exists() {
                            amdgpu_power = Some(h.join("power1_average"));
                        }
                    }
                }
            }
        }
        Self {
            rapl_pkg: if read_u64_trim(&p_pkg).is_some() { Some(p_pkg) } else { None },
            rapl_core: if read_u64_trim(&p_core).is_some() { Some(p_core) } else { None },
            rapl_psys: if read_u64_trim(&p_psys).is_some() { Some(p_psys) } else { None },
            rapl_max_uj,
            ina238_dir,
            ina3221_dir,
            amdgpu_power,
        }
    }
}

#[derive(Clone, Copy, Default)]
struct ShuntSample {
    t_s: f64,
    vin_w: f64,
    gpu_w: f64,
    cpu_soc_w: f64,
    sys5v_w: f64,
    amdgpu_w: f64,
}

fn read_linux_ctxt_switches() -> (u64, u64) {
    let mut vol = 0u64;
    let mut nonvol = 0u64;
    let task_dir = Path::new("/proc/self/task");
    if let Ok(entries) = fs::read_dir(task_dir) {
        for ent in entries.flatten() {
            if let Ok(txt) = fs::read_to_string(ent.path().join("status")) {
                for line in txt.lines() {
                    if let Some(r) = line.strip_prefix("voluntary_ctxt_switches:") {
                        vol += r.trim().parse::<u64>().unwrap_or(0);
                    } else if let Some(r) = line.strip_prefix("nonvoluntary_ctxt_switches:") {
                        nonvol += r.trim().parse::<u64>().unwrap_or(0);
                    }
                }
            }
        }
    }
    (vol, nonvol)
}

#[cfg(unix)]
fn read_unix_cpu_ms_and_ctxt() -> (f64, u64, u64) {
    unsafe {
        let mut ru: libc::rusage = std::mem::zeroed();
        libc::getrusage(libc::RUSAGE_SELF, &mut ru);
        let u_ms = (ru.ru_utime.tv_sec as f64) * 1000.0 + (ru.ru_utime.tv_usec as f64) / 1000.0;
        let s_ms = (ru.ru_stime.tv_sec as f64) * 1000.0 + (ru.ru_stime.tv_usec as f64) / 1000.0;
        #[cfg(target_os = "linux")]
        {
            let (v, nv) = read_linux_ctxt_switches();
            (u_ms + s_ms, v, nv)
        }
        #[cfg(not(target_os = "linux"))]
        {
            (u_ms + s_ms, ru.ru_nvcsw.max(0) as u64, ru.ru_nivcsw.max(0) as u64)
        }
    }
}

#[cfg(target_os = "macos")]
fn read_darwin_ri_energy_nj() -> Option<u64> {
    #[link(name = "proc")]
    extern "C" {
        fn proc_pid_rusage(pid: libc::c_int, flavor: libc::c_int, buffer: *mut u8) -> libc::c_int;
    }
    // Verified on M3 Ultra Darwin 27.2.0 arm64: sizeof(rusage_info_v6)=464, offsetof(ri_energy_nj)=336
    let mut buf = [0u8; 512];
    let rc = unsafe { proc_pid_rusage(libc::getpid(), 6, buf.as_mut_ptr()) };
    if rc == 0 {
        let mut bytes = [0u8; 8];
        bytes.copy_from_slice(&buf[336..344]);
        Some(u64::from_ne_bytes(bytes))
    } else {
        None
    }
}

#[cfg(windows)]
pub mod win_hw {
    use std::ffi::c_void;
    use std::ptr::{null, null_mut};

    #[repr(C)]
    #[derive(Copy, Clone, Default)]
    pub struct FileTime {
        pub low: u32,
        pub high: u32,
    }

    #[link(name = "kernel32")]
    extern "system" {
        pub fn GetCurrentProcess() -> *mut c_void;
        pub fn QueryProcessCycleTime(proc_h: *mut c_void, cycles: *mut u64) -> i32;
        pub fn GetProcessTimes(
            proc_h: *mut c_void,
            create: *mut FileTime,
            exit: *mut FileTime,
            kernel: *mut FileTime,
            user: *mut FileTime,
        ) -> i32;
        pub fn LoadLibraryA(name: *const u8) -> *mut c_void;
        pub fn GetProcAddress(module: *mut c_void, proc_name: *const u8) -> *mut c_void;
        pub fn CreateEventW(
            attr: *const c_void,
            manual_reset: i32,
            initial_state: i32,
            name: *const u16,
        ) -> *mut c_void;
        pub fn SetEvent(handle: *mut c_void) -> i32;
        pub fn WaitForSingleObject(handle: *mut c_void, ms: u32) -> u32;
        pub fn CloseHandle(handle: *mut c_void) -> i32;
        pub fn CreateWaitableTimerExW(
            attr: *const c_void,
            name: *const u16,
            flags: u32,
            access: u32,
        ) -> *mut c_void;
        pub fn SetWaitableTimer(
            timer: *mut c_void,
            due_time: *const i64,
            period: i32,
            comp: *const c_void,
            arg: *const c_void,
            resume: i32,
        ) -> i32;
    }

    #[link(name = "winmm")]
    extern "system" {
        pub fn timeBeginPeriod(period: u32) -> u32;
        pub fn timeEndPeriod(period: u32) -> u32;
    }

    pub fn read_win_nvml_mj() -> Option<u64> {
        unsafe {
            let lib = LoadLibraryA(b"nvml.dll\0".as_ptr());
            if lib.is_null() {
                return None;
            }
            let p_init = GetProcAddress(lib, b"nvmlInit_v2\0".as_ptr());
            let p_hnd = GetProcAddress(lib, b"nvmlDeviceGetHandleByIndex_v2\0".as_ptr());
            let p_eng = GetProcAddress(lib, b"nvmlDeviceGetTotalEnergyConsumption\0".as_ptr());
            if p_init.is_null() || p_hnd.is_null() || p_eng.is_null() {
                return None;
            }
            let f_init: extern "C" fn() -> i32 = std::mem::transmute(p_init);
            let f_hnd: extern "C" fn(u32, *mut *mut c_void) -> i32 = std::mem::transmute(p_hnd);
            let f_eng: extern "C" fn(*mut c_void, *mut u64) -> i32 = std::mem::transmute(p_eng);
            if f_init() != 0 {
                return None;
            }
            let mut h: *mut c_void = null_mut();
            if f_hnd(0, &mut h) != 0 {
                return None;
            }
            let mut mj: u64 = 0;
            if f_eng(h, &mut mj) != 0 {
                return None;
            }
            Some(mj)
        }
    }

    pub fn read_win_proc_l3() -> (f64, u64) {
        unsafe {
            let h = GetCurrentProcess();
            let mut cyc = 0u64;
            let _ = QueryProcessCycleTime(h, &mut cyc);
            let (mut c, mut e, mut k, mut u) = (
                FileTime::default(),
                FileTime::default(),
                FileTime::default(),
                FileTime::default(),
            );
            let _ = GetProcessTimes(h, &mut c, &mut e, &mut k, &mut u);
            let kt = ((k.high as u64) << 32) | (k.low as u64);
            let ut = ((u.high as u64) << 32) | (u.low as u64);
            let cpu_ms = ((kt + ut) as f64) / 10_000.0; // 100ns units -> ms
            (cpu_ms, cyc)
        }
    }

    pub fn sleep_1khz_tick(timer_h: *mut c_void) {
        unsafe {
            if !timer_h.is_null() {
                let due: i64 = -10_000; // -1.0 ms in 100ns relative intervals
                if SetWaitableTimer(timer_h, &due, 0, null(), null(), 0) != 0 {
                    let _ = WaitForSingleObject(timer_h, 5);
                    return;
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(1));
        }
    }
}

pub struct FleetMeterSession {
    t0: Instant,
    paths: LinuxHwPaths,
    rapl_last: (u64, u64, u64),
    rapl_acc_uj: (u128, u128, u128),
    stop_sampler: Arc<AtomicBool>,
    samples: Arc<Mutex<Vec<ShuntSample>>>,
    sampler_thr: Option<JoinHandle<()>>,
    #[cfg(unix)]
    unix_pre: (f64, u64, u64),
    #[cfg(target_os = "macos")]
    darwin_nj_pre: Option<u64>,
    #[cfg(windows)]
    win_pre: (f64, u64, Option<u64>),
}

impl FleetMeterSession {
    pub fn start() -> Self {
        let paths = LinuxHwPaths::discover();
        let pkg0 = paths.rapl_pkg.as_ref().and_then(|p| read_u64_trim(p)).unwrap_or(0);
        let core0 = paths.rapl_core.as_ref().and_then(|p| read_u64_trim(p)).unwrap_or(0);
        let psys0 = paths.rapl_psys.as_ref().and_then(|p| read_u64_trim(p)).unwrap_or(0);

        let stop_sampler = Arc::new(AtomicBool::new(false));
        let samples: Arc<Mutex<Vec<ShuntSample>>> = Arc::new(Mutex::new(Vec::with_capacity(2048)));
        let t0 = Instant::now();

        let need_bg = (paths.ina238_dir.is_some() && paths.ina3221_dir.is_some())
            || paths.amdgpu_power.is_some();
        let sampler_thr = if need_bg {
            let p_c = paths.clone();
            let st_c = Arc::clone(&stop_sampler);
            let sm_c = Arc::clone(&samples);
            let origin = t0;
            Some(thread::spawn(move || {
                while !st_c.load(Ordering::Relaxed) {
                    let ts = origin.elapsed().as_secs_f64();
                    let mut s = ShuntSample { t_s: ts, ..Default::default() };
                    if let (Some(d238), Some(d3221)) = (&p_c.ina238_dir, &p_c.ina3221_dir) {
                        let vin_uw = read_i64_trim(&d238.join("power1_input")).unwrap_or(0);
                        let v1 = read_i64_trim(&d3221.join("in1_input")).unwrap_or(0);
                        let c1 = read_i64_trim(&d3221.join("curr1_input")).unwrap_or(0);
                        let v2 = read_i64_trim(&d3221.join("in2_input")).unwrap_or(0);
                        let c2 = read_i64_trim(&d3221.join("curr2_input")).unwrap_or(0);
                        let v3 = read_i64_trim(&d3221.join("in3_input")).unwrap_or(0);
                        let c3 = read_i64_trim(&d3221.join("curr3_input")).unwrap_or(0);
                        s.vin_w = (vin_uw as f64) / 1e6;
                        s.gpu_w = ((v1 * c1) as f64) / 1e6;
                        s.cpu_soc_w = ((v2 * c2) as f64) / 1e6;
                        s.sys5v_w = ((v3 * c3) as f64) / 1e6;
                    }
                    if let Some(ap) = &p_c.amdgpu_power {
                        let uw = read_u64_trim(ap).unwrap_or(0);
                        s.amdgpu_w = (uw as f64) / 1e6;
                    }
                    sm_c.lock().unwrap().push(s);
                    thread::sleep(Duration::from_millis(5)); // 200 Hz physical/PPT rail trace
                }
            }))
        } else {
            None
        };

        Self {
            t0,
            paths,
            rapl_last: (pkg0, core0, psys0),
            rapl_acc_uj: (0, 0, 0),
            stop_sampler,
            samples,
            sampler_thr,
            #[cfg(unix)]
            unix_pre: read_unix_cpu_ms_and_ctxt(),
            #[cfg(target_os = "macos")]
            darwin_nj_pre: read_darwin_ri_energy_nj(),
            #[cfg(windows)]
            win_pre: {
                let (ms, cyc) = win_hw::read_win_proc_l3();
                let mj = win_hw::read_win_nvml_mj();
                (ms, cyc, mj)
            },
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

    pub fn sample_rapl(&mut self) {
        if self.paths.rapl_pkg.is_none() {
            return;
        }
        let m = self.paths.rapl_max_uj;
        let pkg = self.paths.rapl_pkg.as_ref().and_then(|p| read_u64_trim(p)).unwrap_or(0);
        let core = self.paths.rapl_core.as_ref().and_then(|p| read_u64_trim(p)).unwrap_or(0);
        let psys = self.paths.rapl_psys.as_ref().and_then(|p| read_u64_trim(p)).unwrap_or(0);
        self.rapl_acc_uj.0 += Self::delta_wrap(self.rapl_last.0, pkg, m);
        self.rapl_acc_uj.1 += Self::delta_wrap(self.rapl_last.1, core, m);
        self.rapl_acc_uj.2 += Self::delta_wrap(self.rapl_last.2, psys, m);
        self.rapl_last = (pkg, core, psys);
    }

    pub fn finish(mut self) -> WindowTelemetry {
        self.sample_rapl();
        let elapsed_s = self.t0.elapsed().as_secs_f64().max(1e-9);
        self.stop_sampler.store(true, Ordering::Relaxed);
        if let Some(h) = self.sampler_thr.take() {
            let _ = h.join();
        }
        let trace = self.samples.lock().unwrap();
        let has_shunt = self.paths.ina238_dir.is_some() && self.paths.ina3221_dir.is_some();

        let mut vin_j = 0.0;
        let mut gpu_j = 0.0;
        let mut cpu_j = 0.0;
        let mut sys5_j = 0.0;
        let mut amd_j = 0.0;
        if trace.len() >= 2 {
            for i in 0..(trace.len() - 1) {
                let dt = (trace[i + 1].t_s - trace[i].t_s).max(0.0);
                vin_j += 0.5 * (trace[i].vin_w + trace[i + 1].vin_w) * dt;
                gpu_j += 0.5 * (trace[i].gpu_w + trace[i + 1].gpu_w) * dt;
                cpu_j += 0.5 * (trace[i].cpu_soc_w + trace[i + 1].cpu_soc_w) * dt;
                sys5_j += 0.5 * (trace[i].sys5v_w + trace[i + 1].sys5v_w) * dt;
                amd_j += 0.5 * (trace[i].amdgpu_w + trace[i + 1].amdgpu_w) * dt;
            }
            // Extrapolate small boundary tails (t=0..t_first and t_last..elapsed_s) cleanly
            let head_dt = trace[0].t_s.max(0.0);
            let tail_dt = (elapsed_s - trace[trace.len() - 1].t_s).max(0.0);
            let f = trace[0];
            let l = trace[trace.len() - 1];
            vin_j += f.vin_w * head_dt + l.vin_w * tail_dt;
            gpu_j += f.gpu_w * head_dt + l.gpu_w * tail_dt;
            cpu_j += f.cpu_soc_w * head_dt + l.cpu_soc_w * tail_dt;
            sys5_j += f.sys5v_w * head_dt + l.sys5v_w * tail_dt;
            amd_j += f.amdgpu_w * head_dt + l.amdgpu_w * tail_dt;
        } else if trace.len() == 1 {
            let f = trace[0];
            vin_j = f.vin_w * elapsed_s;
            gpu_j = f.gpu_w * elapsed_s;
            cpu_j = f.cpu_soc_w * elapsed_s;
            sys5_j = f.sys5v_w * elapsed_s;
            amd_j = f.amdgpu_w * elapsed_s;
        }

        #[cfg(unix)]
        let (cpu_ms, vol_cs, nonvol_cs) = {
            let (m1, v1, nv1) = read_unix_cpu_ms_and_ctxt();
            (
                (m1 - self.unix_pre.0).max(0.0),
                v1.saturating_sub(self.unix_pre.1),
                nv1.saturating_sub(self.unix_pre.2),
            )
        };
        #[cfg(windows)]
        let (cpu_ms, vol_cs, nonvol_cs, win_cycles, win_nvml_j) = {
            let (m1, c1) = win_hw::read_win_proc_l3();
            let mj1 = win_hw::read_win_nvml_mj();
            let dj = match (self.win_pre.2, mj1) {
                (Some(a), Some(b)) if b >= a => Some(((b - a) as f64) / 1000.0),
                _ => None,
            };
            (
                (m1 - self.win_pre.0).max(0.0),
                0u64,
                0u64,
                Some(c1.saturating_sub(self.win_pre.1)),
                dj,
            )
        };

        #[cfg(target_os = "macos")]
        let darwin_j = match (self.darwin_nj_pre, read_darwin_ri_energy_nj()) {
            (Some(a), Some(b)) if b >= a => Some(((b - a) as f64) / 1e9),
            _ => None,
        };
        #[cfg(not(target_os = "macos"))]
        let darwin_j: Option<f64> = None;

        #[cfg(not(windows))]
        let (win_cycles, win_nvml_j): (Option<u64>, Option<f64>) = (None, None);

        WindowTelemetry {
            elapsed_s,
            board_metered: has_shunt,
            l1_vin_ina238_measured_j: if has_shunt { Some(vin_j) } else { None },
            l2_vdd_cpu_soc_mss_measured_j: if has_shunt { Some(cpu_j) } else { None },
            l2_vdd_gpu_measured_j: if has_shunt { Some(gpu_j) } else { None },
            l1_vin_sys_5v0_measured_j: if has_shunt { Some(sys5_j) } else { None },
            shunt_samples: trace.len(),
            pkg_reported_j: self.paths.rapl_pkg.as_ref().map(|_| self.rapl_acc_uj.0 as f64 / 1e6),
            core_reported_j: self.paths.rapl_core.as_ref().map(|_| self.rapl_acc_uj.1 as f64 / 1e6),
            psys_reported_j: self.paths.rapl_psys.as_ref().map(|_| self.rapl_acc_uj.2 as f64 / 1e6),
            amdgpu_ppt_reported_j: self.paths.amdgpu_power.as_ref().map(|_| amd_j),
            darwin_ri_energy_reported_j: darwin_j,
            win_nvml_gpu_reported_j: win_nvml_j,
            cpu_time_ms: cpu_ms,
            win_process_cycles: win_cycles,
            voluntary_ctxt_switches: vol_cs,
            nonvoluntary_ctxt_switches: nonvol_cs,
        }
    }
}

pub fn measure_fleet_idle(seconds: f64) -> Value {
    let mut sess = FleetMeterSession::start();
    let steps = ((seconds / 0.25).ceil() as usize).max(1);
    let step_dur = Duration::from_secs_f64(seconds / steps as f64);
    for _ in 0..steps {
        thread::sleep(step_dur);
        sess.sample_rapl();
    }
    let tel = sess.finish();
    json!(tel)
}

// ============================================================================
// Cross-Platform Kernel-Blocked Zero-Clock Event Primitive
//   - Linux:   eventfd(0, EFD_CLOEXEC)
//   - macOS:   kqueue() + EVFILT_READ over POSIX pipe
//   - Windows: CreateEventW + WaitForSingleObject(..., INFINITE)
// ============================================================================

pub struct OsEventHandle {
    #[cfg(target_os = "linux")]
    fd: i32,
    #[cfg(target_os = "macos")]
    kq_and_pipe: (i32, i32, i32),
    #[cfg(windows)]
    ev_ptr: usize,
}

unsafe impl Send for OsEventHandle {}
unsafe impl Sync for OsEventHandle {}

impl OsEventHandle {
    pub fn new_active() -> Self {
        #[cfg(target_os = "linux")]
        {
            let fd = unsafe { libc::eventfd(0, libc::EFD_CLOEXEC) };
            Self { fd }
        }
        #[cfg(target_os = "macos")]
        {
            unsafe {
                let mut fds = [-1i32; 2];
                let _ = libc::pipe(fds.as_mut_ptr());
                let flags = libc::fcntl(fds[0], libc::F_GETFL, 0);
                let _ = libc::fcntl(fds[0], libc::F_SETFL, flags | libc::O_NONBLOCK);
                let kq = libc::kqueue();
                let kev = libc::kevent {
                    ident: fds[0] as usize,
                    filter: libc::EVFILT_READ,
                    flags: libc::EV_ADD | libc::EV_ENABLE,
                    fflags: 0,
                    data: 0,
                    udata: std::ptr::null_mut(),
                };
                let _ = libc::kevent(kq, &kev, 1, std::ptr::null_mut(), 0, std::ptr::null());
                Self {
                    kq_and_pipe: (kq, fds[0], fds[1]),
                }
            }
        }
        #[cfg(windows)]
        {
            let h = unsafe { win_hw::CreateEventW(std::ptr::null(), 0, 0, std::ptr::null()) };
            Self { ev_ptr: h as usize }
        }
    }

    pub fn new_disabled() -> Self {
        #[cfg(target_os = "linux")]
        {
            Self { fd: -1 }
        }
        #[cfg(target_os = "macos")]
        {
            Self {
                kq_and_pipe: (-1, -1, -1),
            }
        }
        #[cfg(windows)]
        {
            Self { ev_ptr: 0 }
        }
    }

    pub fn signal(&self) {
        #[cfg(target_os = "linux")]
        {
            if self.fd >= 0 {
                let val: u64 = 1;
                unsafe {
                    let _ = libc::write(self.fd, &val as *const u64 as *const libc::c_void, 8);
                }
            }
        }
        #[cfg(target_os = "macos")]
        {
            let (_, _, pw) = self.kq_and_pipe;
            if pw >= 0 {
                let b: u8 = 1;
                unsafe {
                    let _ = libc::write(pw, &b as *const u8 as *const libc::c_void, 1);
                }
            }
        }
        #[cfg(windows)]
        {
            if self.ev_ptr != 0 {
                unsafe {
                    let _ = win_hw::SetEvent(self.ev_ptr as *mut std::ffi::c_void);
                }
            }
        }
    }

    pub fn wait(&self) {
        #[cfg(target_os = "linux")]
        {
            if self.fd >= 0 {
                let mut val: u64 = 0;
                unsafe {
                    let _ = libc::read(self.fd, &mut val as *mut u64 as *mut libc::c_void, 8);
                }
            }
        }
        #[cfg(target_os = "macos")]
        {
            let (kq, pr, _) = self.kq_and_pipe;
            if kq >= 0 {
                unsafe {
                    let mut out_ev: libc::kevent = std::mem::zeroed();
                    let _ = libc::kevent(
                        kq,
                        std::ptr::null(),
                        0,
                        &mut out_ev,
                        1,
                        std::ptr::null(),
                    );
                    let mut drain = [0u8; 64];
                    while libc::read(pr, drain.as_mut_ptr() as *mut libc::c_void, 64) > 0 {}
                }
            }
        }
        #[cfg(windows)]
        {
            if self.ev_ptr != 0 {
                unsafe {
                    let _ = win_hw::WaitForSingleObject(
                        self.ev_ptr as *mut std::ffi::c_void,
                        0xFFFF_FFFF,
                    );
                }
            }
        }
    }

    pub fn mechanism_name() -> &'static str {
        #[cfg(target_os = "linux")]
        {
            "linux_eventfd"
        }
        #[cfg(target_os = "macos")]
        {
            "darwin_kqueue_pipe"
        }
        #[cfg(windows)]
        {
            "win32_event_wait"
        }
    }
}

impl Drop for OsEventHandle {
    fn drop(&mut self) {
        #[cfg(target_os = "linux")]
        {
            if self.fd >= 0 {
                unsafe {
                    let _ = libc::close(self.fd);
                }
            }
        }
        #[cfg(target_os = "macos")]
        {
            let (kq, pr, pw) = self.kq_and_pipe;
            unsafe {
                if kq >= 0 {
                    let _ = libc::close(kq);
                }
                if pr >= 0 {
                    let _ = libc::close(pr);
                }
                if pw >= 0 {
                    let _ = libc::close(pw);
                }
            }
        }
        #[cfg(windows)]
        {
            if self.ev_ptr != 0 {
                unsafe {
                    let _ = win_hw::CloseHandle(self.ev_ptr as *mut std::ffi::c_void);
                }
            }
        }
    }
}
