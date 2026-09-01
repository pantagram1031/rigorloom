//! The Runtime Protocol v0 client. All protocol I/O lives here, in Rust.
//!
//! Two spike findings shape this module (Decision section of
//! `docs/desktop-shell-spike.md`):
//!
//! - **Finding 2 — batch before crossing IPC.** Emitting one Tauri event per
//!   JSONL line measured 1.1 MiB/s; counting the same lines in Rust and
//!   emitting once measured 7.0 MiB/s. Every notification and every stderr
//!   line therefore lands in `pending_out` and leaves on a timer as an array
//!   (`EMIT_INTERVAL`), never one event per line.
//! - **Finding 1 — confine the child.** `spawn` calls `jobkill::confine_to_job`
//!   immediately after the process exists and reports the outcome honestly in
//!   `SidecarStatus::job_confined`; the UI shows it rather than assuming it.
//!
//! The wire contract is `docs/runtime-protocol-v0.md`: one JSON object per
//! line, UTF-8, stdout frames only, stderr diagnostics only, `initialize`
//! first, and a `response`/`error` frame always echoing the request id.

use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::mpsc::{channel, Receiver, Sender};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use serde::Serialize;
use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::jobkill;

/// Batch window for outbound notifications. Spike finding 2.
const EMIT_INTERVAL: Duration = Duration::from_millis(100);

/// Tauri event names. One channel for batched activity, one for status changes.
pub const EVENT_ACTIVITY: &str = "runtime://activity";
pub const EVENT_STATUS: &str = "runtime://status";

/// A single request may not outlive this. `tests/_runtime_client.py` uses 180 s
/// for the same reason: the Runtime spawns `form_inspect` children of its own,
/// and `tests/test_subprocess_bounds.py` measured a loaded cold repo-script
/// spawn at a 9.00 s median with a 36.46 s worst case.
const CALL_TIMEOUT: Duration = Duration::from_secs(180);

/// How the sidecar was resolved. Surfaced to the UI: a user who is running the
/// interpreter directly should be able to see that.
#[derive(Clone, Copy, Debug, Serialize, PartialEq)]
#[serde(rename_all = "camelCase")]
pub enum SidecarMode {
    /// The PyInstaller one-dir bundle under `bundle.resources`.
    Packaged,
    /// A development checkout driven through a system interpreter.
    Interpreter,
}

#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SidecarStatus {
    pub running: bool,
    pub pid: Option<u32>,
    pub mode: Option<SidecarMode>,
    pub root: Option<String>,
    /// `Some(true)` confined, `Some(false)` the attempt failed (reason in
    /// `job_error`), `None` not attempted. Never silently assumed.
    pub job_confined: Option<bool>,
    pub job_error: Option<String>,
    /// Set once the sidecar has exited; `None` while it is alive.
    pub exit_code: Option<i32>,
    /// Why the shell believes the sidecar is unusable, in product language.
    pub failure: Option<String>,
    pub initialized: bool,
}

impl Default for SidecarStatus {
    fn default() -> Self {
        SidecarStatus {
            running: false,
            pid: None,
            mode: None,
            root: None,
            job_confined: None,
            job_error: None,
            exit_code: None,
            failure: None,
            initialized: false,
        }
    }
}

/// One batched activity record. `kind` is `frame` for a protocol notification,
/// `log` for a sidecar stderr line, `lifecycle` for spawn/exit.
#[derive(Clone, Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Activity {
    pub seq: u64,
    pub at_ms: u64,
    pub kind: &'static str,
    pub text: Option<String>,
    pub frame: Option<Value>,
}

struct Pending {
    tx: Sender<Value>,
}

pub struct Sidecar {
    child: Option<Child>,
    /// Behind its own mutex so `call` can take `&self` and still serialise
    /// writes: Tauri dispatches commands from a pool, and two interleaved
    /// half-written frames would corrupt the stream.
    stdin: Arc<Mutex<Option<ChildStdin>>>,
    pending: Arc<Mutex<HashMap<String, Pending>>>,
    next_id: AtomicU64,
    status: Arc<Mutex<SidecarStatus>>,
    stop_flag: Arc<AtomicBool>,
    out_buf: Arc<Mutex<Vec<Activity>>>,
    seq: Arc<AtomicU64>,
    started: Instant,
}

impl Default for Sidecar {
    fn default() -> Self {
        Sidecar {
            child: None,
            stdin: Arc::new(Mutex::new(None)),
            pending: Arc::new(Mutex::new(HashMap::new())),
            next_id: AtomicU64::new(0),
            status: Arc::new(Mutex::new(SidecarStatus::default())),
            stop_flag: Arc::new(AtomicBool::new(false)),
            out_buf: Arc::new(Mutex::new(Vec::new())),
            seq: Arc::new(AtomicU64::new(0)),
            started: Instant::now(),
        }
    }
}

/// Where the sidecar executable or script lives, and how to invoke it.
pub struct Launch {
    pub program: PathBuf,
    pub args: Vec<String>,
    pub mode: SidecarMode,
}

/// Resolve the sidecar without guessing.
///
/// The packaged one-dir bundle wins when it is present; a dev checkout falls
/// back to the interpreter. Both are reported to the UI (`SidecarStatus.mode`)
/// so "why is this slow / why does this work on my machine" is answerable.
pub fn resolve_launch(resource_dir: Option<&Path>, repo_root: &Path, root: &Path) -> Result<Launch, String> {
    let exe_name = if cfg!(windows) { "rigorloomd.exe" } else { "rigorloomd" };
    if let Some(dir) = resource_dir {
        // `bundle.resources` keeps the path as written in tauri.conf.json, so
        // "resources/rigorloomd/**/*" lands at <resource_dir>/resources/
        // rigorloomd/. The bare form is tried too, so moving the declaration
        // later does not silently fall back to the dev interpreter.
        for candidate in [
            dir.join("resources").join("rigorloomd").join(exe_name),
            dir.join("rigorloomd").join(exe_name),
        ] {
            if candidate.is_file() {
                return Ok(Launch {
                    program: candidate,
                    args: vec![
                        "--entry".into(),
                        "host".into(),
                        "--root".into(),
                        root.to_string_lossy().into_owned(),
                    ],
                    mode: SidecarMode::Packaged,
                });
            }
        }
    }
    let serve = repo_root.join("runtime").join("scripts").join("serve.py");
    if !serve.is_file() {
        return Err(format!(
            "런타임을 찾지 못했습니다. 패키지된 사이드카도 없고 개발용 스크립트도 없습니다 ({}).",
            serve.display()
        ));
    }
    let python = std::env::var("RIGORLOOM_PYTHON").unwrap_or_else(|_| "python".into());
    Ok(Launch {
        program: PathBuf::from(python),
        args: vec![
            serve.to_string_lossy().into_owned(),
            "--entry".into(),
            "host".into(),
            "--root".into(),
            root.to_string_lossy().into_owned(),
            "--engine-root".into(),
            repo_root.to_string_lossy().into_owned(),
        ],
        mode: SidecarMode::Interpreter,
    })
}

impl Sidecar {
    pub fn status(&self) -> SidecarStatus {
        self.status.lock().unwrap().clone()
    }

    fn push(&self, kind: &'static str, text: Option<String>, frame: Option<Value>) {
        let seq = self.seq.fetch_add(1, Ordering::Relaxed);
        let at_ms = self.started.elapsed().as_millis() as u64;
        self.out_buf.lock().unwrap().push(Activity { seq, at_ms, kind, text, frame });
    }

    pub fn spawn(&mut self, app: &AppHandle, launch: Launch, root: &Path) -> Result<SidecarStatus, String> {
        self.shutdown();
        self.stop_flag = Arc::new(AtomicBool::new(false));
        self.started = Instant::now();

        let mut command = Command::new(&launch.program);
        command
            .args(&launch.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            // The cp949 lesson (engine/scripts/cli_io.py:3): a Korean-locale
            // console kills non-ASCII JSON unless UTF-8 is forced.
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1");
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            // CREATE_NO_WINDOW: no console flash, and no conhost.exe in the
            // process tree (spike obligation 4).
            command.creation_flags(0x0800_0000);
        }

        let mut child = command
            .spawn()
            .map_err(|e| format!("사이드카를 시작하지 못했습니다: {e} ({})", launch.program.display()))?;
        let pid = child.id();

        // Spike finding 1. Do this before anything else can fail.
        let (confined, job_error) = match jobkill::confine_to_job(pid) {
            Ok(()) => (Some(true), None),
            Err(e) => (Some(false), Some(e)),
        };

        let stdin = child.stdin.take().ok_or("사이드카 stdin을 열지 못했습니다")?;
        let stdout = child.stdout.take().ok_or("사이드카 stdout을 열지 못했습니다")?;
        let stderr = child.stderr.take().ok_or("사이드카 stderr를 열지 못했습니다")?;

        {
            let mut status = self.status.lock().unwrap();
            *status = SidecarStatus {
                running: true,
                pid: Some(pid),
                mode: Some(launch.mode),
                root: Some(root.to_string_lossy().into_owned()),
                job_confined: confined,
                job_error: job_error.clone(),
                exit_code: None,
                failure: None,
                initialized: false,
            };
        }
        self.push("lifecycle", Some(format!("사이드카 시작 pid={pid}")), None);

        // --- reader: protocol frames -------------------------------------
        {
            let pending = Arc::clone(&self.pending);
            let out_buf = Arc::clone(&self.out_buf);
            let seq = Arc::clone(&self.seq);
            let started = self.started;
            std::thread::spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines() {
                    let Ok(line) = line else { break };
                    if line.trim().is_empty() {
                        continue;
                    }
                    let frame: Value = match serde_json::from_str(&line) {
                        Ok(v) => v,
                        Err(e) => {
                            let n = seq.fetch_add(1, Ordering::Relaxed);
                            out_buf.lock().unwrap().push(Activity {
                                seq: n,
                                at_ms: started.elapsed().as_millis() as u64,
                                kind: "log",
                                text: Some(format!("프레임을 해석하지 못했습니다: {e}")),
                                frame: None,
                            });
                            continue;
                        }
                    };
                    let kind = frame.get("kind").and_then(Value::as_str).unwrap_or("");
                    if kind == "response" || kind == "error" {
                        let id = frame.get("id").and_then(Value::as_str).unwrap_or("").to_string();
                        let waiter = pending.lock().unwrap().remove(&id);
                        if let Some(p) = waiter {
                            let _ = p.tx.send(frame);
                            continue;
                        }
                    }
                    // Notifications, and any answer nobody is waiting for, are
                    // activity. Batched, never one IPC event per line.
                    let n = seq.fetch_add(1, Ordering::Relaxed);
                    out_buf.lock().unwrap().push(Activity {
                        seq: n,
                        at_ms: started.elapsed().as_millis() as u64,
                        kind: "frame",
                        text: None,
                        frame: Some(frame),
                    });
                }
            });
        }

        // --- reader: stderr diagnostics ----------------------------------
        {
            let out_buf = Arc::clone(&self.out_buf);
            let seq = Arc::clone(&self.seq);
            let started = self.started;
            std::thread::spawn(move || {
                let reader = BufReader::new(stderr);
                for line in reader.lines() {
                    let Ok(line) = line else { break };
                    if line.trim().is_empty() {
                        continue;
                    }
                    let n = seq.fetch_add(1, Ordering::Relaxed);
                    out_buf.lock().unwrap().push(Activity {
                        seq: n,
                        at_ms: started.elapsed().as_millis() as u64,
                        kind: "log",
                        text: Some(line),
                        frame: None,
                    });
                }
            });
        }

        // --- emitter: the only place activity crosses IPC ----------------
        {
            let app = app.clone();
            let out_buf = Arc::clone(&self.out_buf);
            let stop = Arc::clone(&self.stop_flag);
            std::thread::spawn(move || loop {
                std::thread::sleep(EMIT_INTERVAL);
                let batch: Vec<Activity> = {
                    let mut guard = out_buf.lock().unwrap();
                    if guard.is_empty() {
                        if stop.load(Ordering::Relaxed) {
                            return;
                        }
                        continue;
                    }
                    std::mem::take(&mut *guard)
                };
                let _ = app.emit(EVENT_ACTIVITY, batch);
                if stop.load(Ordering::Relaxed) {
                    return;
                }
            });
        }

        *self.stdin.lock().unwrap() = Some(stdin);
        self.child = Some(child);
        Ok(self.status())
    }

    /// Watch for the sidecar exiting and surface it. Spike gate M12: a dead
    /// sidecar must be visible and recoverable, never a silent zombie.
    pub fn watch_exit(&mut self, app: &AppHandle) {
        let Some(child) = self.child.as_mut() else { return };
        let pid = child.id();
        let app = app.clone();
        let status = Arc::clone(&self.status);
        let pending = Arc::clone(&self.pending);
        let out_buf = Arc::clone(&self.out_buf);
        let seq = Arc::clone(&self.seq);
        let started = self.started;
        std::thread::spawn(move || {
            // The Child is owned by the manager; poll the OS instead of taking
            // it, so `runtime_call` can still write while this thread waits.
            loop {
                std::thread::sleep(Duration::from_millis(250));
                let alive = process_alive(pid);
                if alive {
                    let still_ours = status.lock().unwrap().pid == Some(pid);
                    if !still_ours {
                        return;
                    }
                    continue;
                }
                let mut guard = status.lock().unwrap();
                if guard.pid != Some(pid) {
                    return; // replaced by a restart; this watcher is stale
                }
                guard.running = false;
                guard.initialized = false;
                guard.failure = Some(
                    "사이드카가 종료되었습니다. 문서 상태는 남아 있습니다. 다시 시작할 수 있습니다."
                        .into(),
                );
                let snapshot = guard.clone();
                drop(guard);
                // Anyone waiting will otherwise hang until CALL_TIMEOUT.
                pending.lock().unwrap().clear();
                let n = seq.fetch_add(1, Ordering::Relaxed);
                out_buf.lock().unwrap().push(Activity {
                    seq: n,
                    at_ms: started.elapsed().as_millis() as u64,
                    kind: "lifecycle",
                    text: Some(format!("사이드카 종료 pid={pid}")),
                    frame: None,
                });
                let _ = app.emit(EVENT_STATUS, snapshot);
                return;
            }
        });
    }

    pub fn mark_initialized(&self) {
        self.status.lock().unwrap().initialized = true;
    }

    /// One request, one answer. Returns the `result` object, or the protocol's
    /// own `error` object — passed through intact, because
    /// `docs/runtime-protocol-v0.md` §3.7 requires it: the refusal payload is
    /// what makes the refusal fixable, and flattening it to a message is the
    /// documented mistake.
    pub fn call(&self, method: &str, params: Option<Value>) -> Result<Value, Value> {
        {
            let status = self.status.lock().unwrap();
            if !status.running {
                return Err(json!({
                    "code": "sidecar_down",
                    "message": status.failure.clone().unwrap_or_else(||
                        "사이드카가 실행 중이 아닙니다.".into()),
                }));
            }
        }
        let n = self.next_id.fetch_add(1, Ordering::Relaxed) + 1;
        let id = format!("d{n}");
        let mut frame = json!({ "kind": "request", "id": id, "method": method });
        if let Some(p) = params {
            frame["params"] = p;
        }
        let (tx, rx): (Sender<Value>, Receiver<Value>) = channel();
        self.pending.lock().unwrap().insert(id.clone(), Pending { tx });

        let line = serde_json::to_string(&frame).map_err(|e| {
            json!({ "code": "frame_malformed", "message": format!("요청을 직렬화하지 못했습니다: {e}") })
        })?;
        {
            let mut guard = self.stdin.lock().unwrap();
            let Some(w) = guard.as_mut() else {
                self.pending.lock().unwrap().remove(&id);
                return Err(json!({ "code": "sidecar_down", "message": "사이드카 stdin이 없습니다." }));
            };
            let res = w
                .write_all(line.as_bytes())
                .and_then(|_| w.write_all(b"\n"))
                .and_then(|_| w.flush());
            if let Err(e) = res {
                drop(guard);
                self.pending.lock().unwrap().remove(&id);
                return Err(json!({
                    "code": "sidecar_down",
                    "message": format!("사이드카에 쓰지 못했습니다: {e}"),
                }));
            }
        }

        match rx.recv_timeout(CALL_TIMEOUT) {
            Ok(frame) => {
                if frame.get("kind").and_then(Value::as_str) == Some("response") {
                    Ok(frame.get("result").cloned().unwrap_or(Value::Null))
                } else {
                    Err(frame.get("error").cloned().unwrap_or_else(
                        || json!({ "code": "frame_malformed", "message": "error 프레임에 error가 없습니다." }),
                    ))
                }
            }
            Err(_) => {
                self.pending.lock().unwrap().remove(&id);
                let status = self.status.lock().unwrap();
                Err(json!({
                    "code": if status.running { "timeout" } else { "sidecar_down" },
                    "message": if status.running {
                        format!("{method} 요청이 {}초 안에 응답하지 않았습니다.", CALL_TIMEOUT.as_secs())
                    } else {
                        status.failure.clone().unwrap_or_else(|| "사이드카가 종료되었습니다.".into())
                    },
                }))
            }
        }
    }

    /// Graceful shutdown: EOF on stdin is what `serve.py` documents as a clean
    /// stop (exit 0). The job object is the guarantee, not this.
    pub fn shutdown(&mut self) {
        self.stop_flag.store(true, Ordering::Relaxed);
        self.stdin.lock().unwrap().take();
        if let Some(mut child) = self.child.take() {
            let deadline = Instant::now() + Duration::from_secs(5);
            loop {
                match child.try_wait() {
                    Ok(Some(_)) => break,
                    Ok(None) if Instant::now() < deadline => {
                        std::thread::sleep(Duration::from_millis(50));
                    }
                    _ => {
                        let _ = child.kill();
                        let _ = child.wait();
                        break;
                    }
                }
            }
        }
        self.pending.lock().unwrap().clear();
        let mut status = self.status.lock().unwrap();
        status.running = false;
        status.initialized = false;
        status.pid = None;
    }
}

#[cfg(windows)]
fn process_alive(pid: u32) -> bool {
    use windows_sys::Win32::Foundation::{CloseHandle, STILL_ACTIVE};
    use windows_sys::Win32::System::Threading::{
        GetExitCodeProcess, OpenProcess, PROCESS_QUERY_LIMITED_INFORMATION,
    };
    unsafe {
        let handle = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid);
        if handle.is_null() {
            return false;
        }
        let mut code: u32 = 0;
        let ok = GetExitCodeProcess(handle, &mut code);
        CloseHandle(handle);
        ok != 0 && code == STILL_ACTIVE as u32
    }
}

#[cfg(not(windows))]
fn process_alive(_pid: u32) -> bool {
    true
}
