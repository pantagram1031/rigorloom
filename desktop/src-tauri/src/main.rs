// Rigorloom Desktop — Phase 3 foundation (read-only).
//
// The shell owns three things and nothing else: the window, the sidecar
// process, and the protocol. Product state lives in one store in the webview
// (`src/store.ts`); document truth lives in the Runtime.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod jobkill;
mod prefs;
mod sidecar;

use std::path::PathBuf;
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};

use sidecar::{resolve_launch, Sidecar, SidecarStatus, EVENT_STATUS};

/// Baked in at compile time so a dev build can find `runtime/scripts/serve.py`
/// without a config file. Ignored by a packaged build, which uses the bundled
/// one-dir sidecar under `bundle.resources`.
const MANIFEST_DIR: &str = env!("CARGO_MANIFEST_DIR");

struct Runtime(Mutex<Sidecar>);

fn repo_root() -> PathBuf {
    // desktop/src-tauri -> desktop -> repo root
    PathBuf::from(MANIFEST_DIR)
        .parent()
        .and_then(|p| p.parent())
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(MANIFEST_DIR))
}

/// Where this build keeps prefs and the runtime root.
///
/// `RIGORLOOM_APPDATA` overrides it, and the harness depends on that: Tauri
/// resolves `app_local_data_dir()` through `SHGetKnownFolderPath`, which reads
/// the user profile from the OS and ignores the `LOCALAPPDATA` environment
/// variable entirely. `smoke.ps1` had been setting that variable and believing
/// it, so every "clean user" run was in fact reading and writing the
/// developer's real prefs — which is how the smoke came to boot with a session
/// left over from the previous run and never show the welcome screen at all.
///
/// An explicit variable the code honours is the only redirection that is
/// actually true.
pub fn app_data_dir(app: &AppHandle) -> PathBuf {
    if let Some(dir) = std::env::var_os("RIGORLOOM_APPDATA") {
        return PathBuf::from(dir);
    }
    app.path()
        .app_local_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("rigorloom"))
}

fn default_root(app: &AppHandle) -> PathBuf {
    app_data_dir(app).join("runtime-root")
}

// --- commands ---------------------------------------------------------------

/// Start (or restart) the sidecar and complete the `initialize` handshake.
///
/// The handshake is not optional and not deferred: `docs/runtime-protocol-v0.md`
/// §1.3 makes `initialize` the first request, and any other method before it is
/// refused with `not_initialized`.
#[tauri::command]
fn runtime_start(
    app: AppHandle,
    state: State<'_, Runtime>,
    root: Option<String>,
) -> Result<Value, Value> {
    let root = root
        .filter(|r| !r.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| default_root(&app));
    if let Err(e) = std::fs::create_dir_all(&root) {
        return Err(json!({
            "code": "root_unusable",
            "message": format!("작업 폴더를 만들지 못했습니다: {e}"),
            "data": { "root": root.to_string_lossy() },
        }));
    }

    let resource_dir = app.path().resource_dir().ok();
    let launch = resolve_launch(resource_dir.as_deref(), &repo_root(), &root)
        .map_err(|m| json!({ "code": "sidecar_missing", "message": m }))?;

    let mut guard = state.0.lock().unwrap();
    guard
        .spawn(&app, launch, &root)
        .map_err(|m| json!({ "code": "sidecar_spawn_failed", "message": m }))?;
    guard.watch_exit(&app);

    let handshake = guard.call(
        "initialize",
        Some(json!({
            "protocolVersion": "0",
            "client": { "name": "rigorloom-desktop", "version": env!("CARGO_PKG_VERSION") },
            // The host client's only correct value (§2 of the protocol): an
            // unknown member must be a refusal, not a silently dropped field.
            "unknownFieldPolicy": "reject",
        })),
    )?;
    guard.mark_initialized();
    let status = guard.status();
    drop(guard);

    let _ = app.emit(EVENT_STATUS, status.clone());
    let _ = prefs::save_root(&app, &root);
    Ok(json!({ "handshake": handshake, "status": status }))
}

#[tauri::command]
fn runtime_call(
    state: State<'_, Runtime>,
    method: String,
    params: Option<Value>,
) -> Result<Value, Value> {
    state.0.lock().unwrap().call(&method, params)
}

#[tauri::command]
fn runtime_status(state: State<'_, Runtime>) -> SidecarStatus {
    state.0.lock().unwrap().status()
}

#[tauri::command]
fn runtime_stop(state: State<'_, Runtime>) {
    state.0.lock().unwrap().shutdown();
}

/// What the shell remembers between launches: the runtime root and the session
/// that was open. Both views restore from this — objective 5.
#[tauri::command]
fn prefs_load(app: AppHandle) -> Value {
    prefs::load(&app)
}

#[tauri::command]
fn prefs_save(app: AppHandle, patch: Value) -> Result<Value, String> {
    prefs::merge(&app, patch)
}

#[tauri::command]
fn default_runtime_root(app: AppHandle) -> String {
    default_root(&app).to_string_lossy().into_owned()
}

// --- scripted evidence -------------------------------------------------------

/// What the launcher asked for. A webview cannot read environment variables, so
/// the smoke's intent arrives through here. Every field is `None` in a normal
/// launch and the harness then does nothing.
#[tauri::command]
fn smoke_config() -> Value {
    json!({
        "phase": std::env::var("RIGORLOOM_SMOKE").ok().filter(|v| !v.is_empty()),
        "corpus": std::env::var("RIGORLOOM_SMOKE_CORPUS").ok().filter(|v| !v.is_empty()),
        "reportPath": std::env::var("RIGORLOOM_SMOKE_REPORT").ok().filter(|v| !v.is_empty()),
    })
}

/// Signal that a `hold` phase has finished arranging the UI, without exiting.
///
/// The screenshot script cannot time this from outside: how long a cold start
/// plus `document/inspect` takes varies, and a fixed sleep produced captures of
/// the loading screen. This is the app telling the script it is done.
#[tauri::command]
fn smoke_ready(detail: Value) -> Result<(), String> {
    let Ok(path) = std::env::var("RIGORLOOM_SMOKE_REPORT") else {
        return Ok(());
    };
    if let Some(parent) = std::path::Path::new(&path).parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let body = serde_json::to_string_pretty(&json!({ "ready": true, "detail": detail }))
        .unwrap_or_else(|_| "{\"ready\":true}".into());
    std::fs::write(&path, body).map_err(|e| e.to_string())
}

/// Write the smoke report and close. Exit code carries the verdict so the
/// PowerShell driver can branch on it without parsing anything.
#[tauri::command]
fn smoke_finish(app: AppHandle, state: State<'_, Runtime>, report: Value) {
    let failed = report.get("failed").and_then(Value::as_u64).unwrap_or(1);
    if let Ok(path) = std::env::var("RIGORLOOM_SMOKE_REPORT") {
        let body = serde_json::to_string_pretty(&report).unwrap_or_else(|_| "{}".into());
        if let Some(parent) = std::path::Path::new(&path).parent() {
            let _ = std::fs::create_dir_all(parent);
        }
        let _ = std::fs::write(&path, body);
    }
    state.0.lock().unwrap().shutdown();
    let _ = app;
    std::process::exit(if failed == 0 { 0 } else { 3 });
}

// --- crash visibility --------------------------------------------------------

/// Spike obligation 5 (M17). A release build is `windows_subsystem = "windows"`,
/// so a Rust panic would otherwise be a silent disappearance with no console and
/// no dialog. `panic = "abort"` is deliberately NOT set in Cargo.toml, so the
/// hook runs; it writes a crash log and tries to put the error on screen before
/// the process goes away.
fn install_panic_hook(app: AppHandle) {
    let previous = std::panic::take_hook();
    let dir = app_data_dir(&app);
    std::panic::set_hook(Box::new(move |info| {
        let location = info
            .location()
            .map(|l| format!("{}:{}:{}", l.file(), l.line(), l.column()))
            .unwrap_or_else(|| "위치 미상".into());
        let message = info
            .payload()
            .downcast_ref::<&str>()
            .map(|s| s.to_string())
            .or_else(|| info.payload().downcast_ref::<String>().cloned())
            .unwrap_or_else(|| "알 수 없는 패닉".into());
        let backtrace = std::backtrace::Backtrace::force_capture();
        let body = format!("rigorloom-desktop panic\nat {location}\n{message}\n\n{backtrace}\n");
        let _ = std::fs::create_dir_all(&dir);
        let _ = std::fs::write(dir.join("crash.log"), &body);
        eprintln!("{body}");
        let _ = app.emit(
            "runtime://panic",
            json!({ "location": location, "message": message,
                    "logPath": dir.join("crash.log").to_string_lossy() }),
        );
        previous(info);
    }));
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_dialog::init())
        .manage(Runtime(Mutex::new(Sidecar::default())))
        .invoke_handler(tauri::generate_handler![
            runtime_start,
            runtime_call,
            runtime_status,
            runtime_stop,
            prefs_load,
            prefs_save,
            default_runtime_root,
            smoke_config,
            smoke_ready,
            smoke_finish,
        ])
        .setup(|app| {
            install_panic_hook(app.handle().clone());
            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                if let Some(state) = window.app_handle().try_state::<Runtime>() {
                    state.0.lock().unwrap().shutdown();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to start the Rigorloom desktop shell");
}
