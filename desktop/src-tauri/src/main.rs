// Rigorloom Desktop — Phase 3 foundation (read-only).
//
// The shell owns three things and nothing else: the window, the sidecar
// process, and the protocol. Product state lives in one store in the webview
// (`src/store.ts`); document truth lives in the Runtime.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod digest;
mod jobkill;
mod prefs;
mod sidecar;

use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};

use sidecar::{resolve_launch, CancelHandle, Sidecar, SidecarStatus, EVENT_STATUS};

/// Baked in at compile time so a dev build can find `runtime/scripts/serve.py`
/// without a config file. Ignored by a packaged build, which uses the bundled
/// one-dir sidecar under `bundle.resources`.
const MANIFEST_DIR: &str = env!("CARGO_MANIFEST_DIR");

struct Runtime(Mutex<Sidecar>);

/// The cancel handles, managed separately from `Runtime` on purpose — see
/// `sidecar::CancelHandle`. Taking the manager lock to cancel a call the
/// manager lock is already held for is a deadlock, not a cancel.
struct Cancels(Mutex<Option<CancelHandle>>);

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
    cancels: State<'_, Cancels>,
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
    // Refresh before the first call, so a cancel can reach THIS process's pipe
    // and never a dead one's.
    *cancels.0.lock().unwrap() = Some(guard.cancel_handle());

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

/// One protocol call.
///
/// NOTE the lock. `Sidecar::call_tagged` takes `&self`, so the mutex is held
/// for the whole round trip — which serialises every call in the app. That was
/// fine for a read-only phase and is now the reason `plan/apply` blocks the
/// UI's other requests while it runs; the honest fix is to scope the lock to
/// the write rather than the wait, and it is recorded as a known risk rather
/// than papered over. Cancellation is the mitigation that matters today:
/// `runtime_cancel` takes its own short-lived lock and can therefore reach the
/// stdin handle while an apply is still in flight.
#[tauri::command]
fn runtime_call(
    state: State<'_, Runtime>,
    method: String,
    params: Option<Value>,
    tag: Option<String>,
) -> Result<Value, Value> {
    state.0.lock().unwrap().call_tagged(&method, params, tag)
}

/// Send the protocol's cancel frame for the call carrying `tag`.
#[tauri::command]
fn runtime_cancel(cancels: State<'_, Cancels>, tag: String) -> bool {
    let handle = cancels.0.lock().unwrap().clone();
    match handle {
        Some(h) => h.cancel(&tag),
        None => false,
    }
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

// --- export ------------------------------------------------------------------

fn refuse(code: &str, message: String, data: Value) -> Value {
    json!({ "code": code, "message": message, "data": data })
}

/// Copy a candidate and its receipt out of the workspace, hashing the copy.
///
/// `artifact/exportTo` is GAP (protocol §11.5): everything the Runtime writes
/// today stays inside `--root`. So this is the shell's own work, and it is
/// deliberately narrow:
///
/// - the SOURCE path is composed from the runtime root plus the session and
///   run ids, never taken from the webview. A caller cannot ask this command
///   to copy an arbitrary file out of the machine;
/// - `candidatePath` is checked to be a bare file name, which is what the
///   receipt actually carries (`rt_apply` writes `artifact.hwpx`), so it
///   cannot walk out of the run directory;
/// - the receipt travels with the artifact, always. A candidate without its
///   receipt is a document with no account of where it came from;
/// - the bytes written are hashed and returned, so the UI can assert they
///   equal the digest the receipt bound rather than trusting the copy.
#[tauri::command]
fn export_candidate(
    state: State<'_, Runtime>,
    session_id: String,
    run_id: String,
    candidate_path: String,
    destination: String,
) -> Result<Value, Value> {
    let bare = |s: &str| {
        !s.is_empty()
            && !s.contains('/')
            && !s.contains('\\')
            && s != "."
            && s != ".."
    };
    for (name, value) in [
        ("sessionId", &session_id),
        ("runId", &run_id),
        ("candidatePath", &candidate_path),
    ] {
        if !bare(value) {
            return Err(refuse(
                "invalid_params",
                format!("{name}은(는) 경로가 아니라 이름이어야 합니다."),
                json!({ "field": name, "value": value }),
            ));
        }
    }

    let root = state.0.lock().unwrap().status().root.ok_or_else(|| {
        refuse(
            "sidecar_down",
            "런타임 작업 폴더를 알 수 없습니다.".into(),
            Value::Null,
        )
    })?;
    let run_dir = Path::new(&root)
        .join("sessions")
        .join(&session_id)
        .join("candidates")
        .join(&run_id);
    let artifact = run_dir.join(&candidate_path);
    let receipt = run_dir.join("receipt.json");
    for path in [&artifact, &receipt] {
        if !path.is_file() {
            return Err(refuse(
                "artifact_missing",
                "후보본이나 영수증이 제자리에 없습니다.".into(),
                json!({ "path": path.to_string_lossy() }),
            ));
        }
    }

    let target = PathBuf::from(&destination);
    if let Some(parent) = target.parent() {
        if !parent.as_os_str().is_empty() && !parent.is_dir() {
            return Err(refuse(
                "export_failed",
                "저장할 폴더가 없습니다.".into(),
                json!({ "parent": parent.to_string_lossy() }),
            ));
        }
    }
    // The receipt lands beside the artifact under a name that names it, so the
    // pair cannot be separated by accident on the way to somebody's email.
    let receipt_target = target.with_file_name(format!(
        "{}.receipt.json",
        target
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "candidate".into())
    ));

    std::fs::copy(&artifact, &target).map_err(|e| {
        refuse(
            "export_failed",
            format!("후보본을 저장하지 못했습니다: {e}"),
            json!({ "destination": destination }),
        )
    })?;
    std::fs::copy(&receipt, &receipt_target).map_err(|e| {
        // Leave nothing half-exported: an artifact whose receipt failed to
        // land is exactly the unaccountable file this whole path exists to
        // prevent.
        let _ = std::fs::remove_file(&target);
        refuse(
            "export_failed",
            format!("영수증을 저장하지 못했습니다: {e}"),
            json!({ "destination": receipt_target.to_string_lossy() }),
        )
    })?;

    let (sha256, bytes) = digest::sha256_file(&target).map_err(|e| {
        refuse(
            "export_failed",
            format!("내보낸 파일을 다시 읽지 못했습니다: {e}"),
            json!({ "destination": destination }),
        )
    })?;
    Ok(json!({
        "path": target.to_string_lossy(),
        "sha256": sha256,
        "bytes": bytes,
        "receiptPath": receipt_target.to_string_lossy(),
    }))
}

// --- the dev-mode agent door ---------------------------------------------------

/// Where `mock_agent.py` is, if it is reachable from this build.
///
/// Two ways: `RIGORLOOM_MOCK_AGENT` names it outright (which is how the
/// scripted evidence points a PACKAGED build at a repo checkout), or the
/// compiled-in repo root has it (a dev run). A shipped installation on a
/// machine with no checkout finds neither, and the button is simply absent —
/// not present and broken.
fn mock_agent_script() -> Option<PathBuf> {
    if let Some(explicit) = std::env::var_os("RIGORLOOM_MOCK_AGENT") {
        let path = PathBuf::from(explicit);
        return path.is_file().then_some(path);
    }
    let path = repo_root()
        .join("runtime")
        .join("scripts")
        .join("mock_agent.py");
    path.is_file().then_some(path)
}

fn agent_python() -> String {
    std::env::var("RIGORLOOM_PYTHON").unwrap_or_else(|_| "python".into())
}

#[tauri::command]
fn agent_tool_status() -> Value {
    match mock_agent_script() {
        Some(path) => json!({
            "available": true,
            "script": path.to_string_lossy(),
            "reason": "개발용 에이전트 스크립트를 찾았습니다.",
        }),
        None => json!({
            "available": false,
            "script": Value::Null,
            "reason": "이 설치본에는 개발용 에이전트 스크립트가 없습니다. \
                       저장소 체크아웃에서 실행하거나 RIGORLOOM_MOCK_AGENT를 지정하십시오.",
        }),
    }
}

/// Run the mock agent on its OWN agent-authority connection to the same root.
///
/// It is a separate process speaking `serve.py --entry agent`, which is the
/// point: the plan it proposes reaches this shell through the shared `--root`
/// store, not through any privileged back channel, and the methods that would
/// let it approve or apply are absent from its registry. The Desktop cannot
/// grant them and does not try.
#[tauri::command]
fn run_mock_agent(
    state: State<'_, Runtime>,
    session_id: String,
    marker: String,
) -> Result<Value, Value> {
    let script = mock_agent_script().ok_or_else(|| {
        refuse(
            "agent_unavailable",
            "개발용 에이전트 스크립트를 찾지 못했습니다.".into(),
            Value::Null,
        )
    })?;
    let root = state.0.lock().unwrap().status().root.ok_or_else(|| {
        refuse(
            "sidecar_down",
            "런타임 작업 폴더를 알 수 없습니다.".into(),
            Value::Null,
        )
    })?;

    let mut command = std::process::Command::new(agent_python());
    command
        .arg(&script)
        .arg("--root")
        .arg(&root)
        .arg("--session")
        .arg(&session_id)
        .arg("--scenario")
        .arg("propose-then-wait")
        .arg("--door")
        .arg("protocol")
        .arg("--marker")
        .arg(&marker)
        .arg("--engine-root")
        .arg(repo_root())
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdin(std::process::Stdio::null())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }

    let output = command.output().map_err(|e| {
        refuse(
            "agent_spawn_failed",
            format!("에이전트를 시작하지 못했습니다: {e}"),
            json!({ "python": agent_python(), "script": script.to_string_lossy() }),
        )
    })?;
    Ok(json!({
        "exitCode": output.status.code().unwrap_or(-1),
        "stdout": String::from_utf8_lossy(&output.stdout),
        "stderr": String::from_utf8_lossy(&output.stderr),
    }))
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
        .manage(Cancels(Mutex::new(None)))
        .invoke_handler(tauri::generate_handler![
            runtime_start,
            runtime_call,
            runtime_cancel,
            runtime_status,
            runtime_stop,
            prefs_load,
            prefs_save,
            default_runtime_root,
            export_candidate,
            agent_tool_status,
            run_mock_agent,
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
