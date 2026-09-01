// Throwaway measurement harness for the rigorloom desktop shell spike.
// Not product code: error handling is deliberately shallow so the numbers are
// not hidden behind plumbing.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use std::time::Instant;

use tauri::{AppHandle, Emitter, Manager, State};
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;

mod jobkill;

/// M4 diagnostic arm: count sidecar lines in Rust and emit ONE event at the
/// end, instead of one IPC event per line. Isolates pipe throughput from
/// Tauri's per-event IPC cost, which is the number that actually decides
/// whether the timeline can tail JSONL naively.
struct Bench {
    remaining: u64,
    bytes: u64,
    t0: Instant,
}

struct Spike {
    t0: Instant,
    child: Mutex<Option<CommandChild>>,
    ready_ms: Mutex<Option<u128>>,
    bench: Mutex<Option<Bench>>,
}

fn spawn_sidecar(app: &AppHandle) {
    let state = app.state::<Spike>();
    // A/B switch for the packaging comparison: RIGORLOOM_SPIKE_SIDECAR=<abs
    // path> runs that executable instead of the bundled externalBin, so the
    // one-file and one-dir builds can be measured end-to-end from ONE shell
    // binary (otherwise the two numbers would differ by build as well as by
    // packaging mode).
    let cmd = match std::env::var("RIGORLOOM_SPIKE_SIDECAR") {
        Ok(path) if !path.is_empty() => {
            let _ = app.emit("sidecar-stderr", format!("[shell] external sidecar: {path}"));
            app.shell().command(path)
        }
        _ => match app.shell().sidecar("rigorloomd") {
            Ok(c) => c,
            Err(e) => {
                let _ = app.emit("sidecar-exit", format!("sidecar() failed: {e}"));
                return;
            }
        },
    };
    let (mut rx, child) = match cmd.spawn() {
        Ok(v) => v,
        Err(e) => {
            let _ = app.emit("sidecar-exit", format!("spawn failed: {e}"));
            return;
        }
    };
    // M11: confine the sidecar to a kill-on-close job object unless the spike
    // is explicitly measuring the unmitigated arm.
    if std::env::var("RIGORLOOM_SPIKE_NOJOB").as_deref() != Ok("1") {
        match jobkill::confine_to_job(child.pid()) {
            Ok(()) => {
                let _ = app.emit("sidecar-stderr", format!("[shell] sidecar pid {} confined to kill-on-close job", child.pid()));
            }
            Err(e) => {
                let _ = app.emit("sidecar-stderr", format!("[shell] JOB OBJECT FAILED: {e}"));
            }
        }
    } else {
        let _ = app.emit("sidecar-stderr", "[shell] job object DISABLED (RIGORLOOM_SPIKE_NOJOB=1)".to_string());
    }

    *state.child.lock().unwrap() = Some(child);

    let handle = app.clone();
    tauri::async_runtime::spawn(async move {
        while let Some(ev) = rx.recv().await {
            match ev {
                CommandEvent::Stdout(bytes) => {
                    // Bench arm: swallow the line in Rust, never touch IPC.
                    {
                        let st = handle.state::<Spike>();
                        let mut guard = st.bench.lock().unwrap();
                        let mut finished: Option<(u128, u64)> = None;
                        if let Some(b) = guard.as_mut() {
                            b.bytes += bytes.len() as u64 + 1;
                            b.remaining = b.remaining.saturating_sub(1);
                            if b.remaining == 0 {
                                finished = Some((b.t0.elapsed().as_millis(), b.bytes));
                            }
                        }
                        if let Some((ms, total)) = finished {
                            *guard = None;
                            drop(guard);
                            let _ = handle.emit("bench-done", serde_json::json!({
                                "ms": ms, "bytes": total,
                            }));
                            continue;
                        }
                        if guard.is_some() {
                            continue;
                        }
                    }
                    let line = String::from_utf8_lossy(&bytes).trim_end().to_string();
                    if line.is_empty() {
                        continue;
                    }
                    if line.contains("\"event\": \"ready\"") || line.contains("\"event\":\"ready\"")
                    {
                        let st = handle.state::<Spike>();
                        let ms = st.t0.elapsed().as_millis();
                        *st.ready_ms.lock().unwrap() = Some(ms);
                        record("sidecar_ready_ms", ms);
                    }
                    let _ = handle.emit("sidecar-line", line);
                }
                CommandEvent::Stderr(bytes) => {
                    let line = String::from_utf8_lossy(&bytes).trim_end().to_string();
                    let _ = handle.emit("sidecar-stderr", line);
                }
                CommandEvent::Terminated(payload) => {
                    let _ = handle.emit(
                        "sidecar-exit",
                        format!("code={:?} signal={:?}", payload.code, payload.signal),
                    );
                }
                CommandEvent::Error(e) => {
                    let _ = handle.emit("sidecar-exit", format!("error: {e}"));
                }
                _ => {}
            }
        }
    });
}

/// Append a timing to %TEMP%\rigorloom-spike-timings.txt so M1/M2 can be
/// collected across repeated launches by a script instead of being read off
/// screenshots one run at a time.
fn record(kind: &str, ms: u128) {
    use std::io::Write;
    let path = std::env::temp_dir().join("rigorloom-spike-timings.txt");
    if let Ok(mut f) = std::fs::OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(f, "pid={} {}={}", std::process::id(), kind, ms);
    }
}

#[tauri::command]
fn mark_first_paint(state: State<Spike>) -> u128 {
    let ms = state.t0.elapsed().as_millis();
    record("first_paint_ms", ms);
    ms
}

#[tauri::command]
fn sidecar_ready_ms(state: State<Spike>) -> Option<u128> {
    *state.ready_ms.lock().unwrap()
}

#[tauri::command]
fn shell_pid() -> u32 {
    std::process::id()
}

#[tauri::command]
fn sidecar_send(state: State<Spike>, line: String) -> Result<(), String> {
    let mut guard = state.child.lock().unwrap();
    let child = guard.as_mut().ok_or("sidecar not running")?;
    child
        .write(format!("{line}\n").as_bytes())
        .map_err(|e| e.to_string())
}

/// Start the M4 diagnostic arm, then push the echo request.
#[tauri::command]
fn bench_echo(state: State<Spike>, n: u64, pad: u64) -> Result<(), String> {
    *state.bench.lock().unwrap() = Some(Bench {
        remaining: n,
        bytes: 0,
        t0: Instant::now(),
    });
    let mut guard = state.child.lock().unwrap();
    let child = guard.as_mut().ok_or("sidecar not running")?;
    child
        .write(format!("{{\"op\":\"echo\",\"n\":{n},\"pad\":{pad}}}\n").as_bytes())
        .map_err(|e| e.to_string())
}

#[tauri::command]
fn restart_sidecar(app: AppHandle) {
    {
        let st = app.state::<Spike>();
        let mut g = st.child.lock().unwrap();
        if let Some(c) = g.take() {
            let _ = c.kill();
        }
        *st.ready_ms.lock().unwrap() = None;
    }
    spawn_sidecar(&app);
}

fn main() {
    let t0 = Instant::now();
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(Spike {
            t0,
            child: Mutex::new(None),
            ready_ms: Mutex::new(None),
            bench: Mutex::new(None),
        })
        .invoke_handler(tauri::generate_handler![
            mark_first_paint,
            sidecar_ready_ms,
            shell_pid,
            sidecar_send,
            bench_echo,
            restart_sidecar
        ])
        .setup(|app| {
            spawn_sidecar(&app.handle().clone());
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
