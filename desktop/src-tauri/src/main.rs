// Rigorloom Desktop — Phase 3 foundation (read-only).
//
// The shell owns three things and nothing else: the window, the sidecar
// process, and the protocol. Product state lives in one store in the webview
// (`src/store.ts`); document truth lives in the Runtime.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod agenthost;
mod credstore;
mod digest;
mod jobkill;
mod prefs;
mod sidecar;
mod taskpacks;

use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter, Manager, State};

use sidecar::{resolve_launch, CancelHandle, Sidecar, SidecarStatus, EVENT_STATUS};

/// Baked in at compile time so a dev build can find `runtime/scripts/serve.py`
/// without a config file. Ignored by a packaged build, which uses the bundled
/// one-dir sidecar under `bundle.resources`.
const MANIFEST_DIR: &str = env!("CARGO_MANIFEST_DIR");

struct Runtime(Mutex<Sidecar>);

/// The Agent Host run in flight, if any. One at a time, by construction: a
/// second instruction while the first is still running would produce two plans
/// racing for the same queue.
struct AgentRun(agenthost::RunSlot);

/// Throttle for the window-geometry writes. A drag emits a `Moved` per frame
/// and a prefs file is not a place to write sixty times a second.
struct GeometryClock(Mutex<std::time::Instant>);

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

static EXPORT_STAGE_COUNTER: AtomicU64 = AtomicU64::new(0);

struct ExportStage {
    path: PathBuf,
}

fn receipt_target_for(target: &Path) -> PathBuf {
    target.with_file_name(format!(
        "{}.receipt.json",
        target
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "candidate".into())
    ))
}

fn is_canonical_candidate_name(name: &str) -> bool {
    name.strip_prefix("artifact.")
        .is_some_and(|suffix| !suffix.is_empty() && !suffix.contains('.') && !suffix.contains('/') && !suffix.contains('\\'))
}

fn path_exists_no_follow(path: &Path) -> Result<bool, Value> {
    match std::fs::symlink_metadata(path) {
        Ok(_) => Ok(true),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(false),
        Err(error) => Err(refuse(
            "export_failed",
            format!("저장 경로를 확인하지 못했습니다: {error}"),
            json!({ "destination": path.to_string_lossy() }),
        )),
    }
}

fn is_regular_file_no_follow(path: &Path) -> bool {
    let Ok(metadata) = std::fs::symlink_metadata(path) else {
        return false;
    };
    if !metadata.file_type().is_file() {
        return false;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x400;
        if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return false;
        }
    }
    true
}

fn create_export_stage(parent: &Path) -> Result<ExportStage, Value> {
    let now = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    for _ in 0..32 {
        let counter = EXPORT_STAGE_COUNTER.fetch_add(1, Ordering::Relaxed);
        let path = parent.join(format!(
            ".rigorloom-export-{}-{now}-{counter}.tmp",
            std::process::id()
        ));
        match std::fs::create_dir(&path) {
            Ok(()) => {
                return Ok(ExportStage { path })
            }
            Err(error) if error.kind() == std::io::ErrorKind::AlreadyExists => continue,
            Err(error) => {
                return Err(refuse(
                    "export_failed",
                    format!("임시 저장 폴더를 만들지 못했습니다: {error}"),
                    json!({ "parent": parent.to_string_lossy() }),
                ))
            }
        }
    }
    Err(refuse(
        "export_failed",
        "고유한 임시 저장 폴더를 만들지 못했습니다.".into(),
        json!({ "parent": parent.to_string_lossy() }),
    ))
}

fn stage_file(source: &Path, target: &Path, role: &str) -> Result<(), Value> {
    use std::io::{Read, Write};

    let mut reader = std::fs::File::open(source).map_err(|error| {
        refuse(
            "export_failed",
            format!("{role} 원본을 읽지 못했습니다: {error}"),
            json!({ "source": source.to_string_lossy() }),
        )
    })?;
    let mut writer = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(target)
        .map_err(|error| {
            refuse(
                "export_failed",
                format!("{role} 임시 파일을 만들지 못했습니다: {error}"),
                json!({ "destination": target.to_string_lossy() }),
            )
        })?;
    let mut buffer = vec![0u8; 1024 * 1024];
    loop {
        let count = reader.read(&mut buffer).map_err(|error| {
            refuse(
                "export_failed",
                format!("{role} 원본을 읽지 못했습니다: {error}"),
                json!({ "source": source.to_string_lossy() }),
            )
        })?;
        if count == 0 {
            break;
        }
        writer.write_all(&buffer[..count]).map_err(|error| {
            refuse(
                "export_failed",
                format!("{role} 임시 파일을 쓰지 못했습니다: {error}"),
                json!({ "destination": target.to_string_lossy() }),
            )
        })?;
    }
    writer.flush().and_then(|_| writer.sync_all()).map_err(|error| {
        refuse(
            "export_failed",
            format!("{role} 임시 파일을 디스크에 기록하지 못했습니다: {error}"),
            json!({ "destination": target.to_string_lossy() }),
        )
    })
}

fn publish_new(staged: &Path, target: &Path, role: &str) -> Result<(), Value> {
    // Both files live in the same directory. Creating a hard link is an atomic
    // no-replace publish on NTFS and the CI filesystems: it fails when the
    // destination already exists instead of replacing somebody else's bytes.
    std::fs::hard_link(staged, target).map_err(|error| {
        let code = if error.kind() == std::io::ErrorKind::AlreadyExists {
            "export_exists"
        } else {
            "export_failed"
        };
        refuse(
            code,
            format!("{role}을(를) 게시하지 못했습니다: {error}"),
            json!({ "destination": target.to_string_lossy() }),
        )
    })
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum ExportStep {
    Staged,
    ArtifactPublished,
    ReceiptPublished,
}

fn export_candidate_files_with_observer<F>(
    runtime_root: &Path,
    artifact: &Path,
    receipt: &Path,
    verified_receipt: Option<&Value>,
    session_id: &str,
    run_id: &str,
    candidate_path: &str,
    target: &Path,
    mut observe: F,
) -> Result<Value, Value>
where
    F: FnMut(ExportStep, &Path, &Path),
{
    if !is_canonical_candidate_name(candidate_path) {
        return Err(refuse(
            "invalid_params",
            "후보본 이름이 Runtime의 canonical artifact 이름이 아닙니다.".into(),
            json!({ "candidatePath": candidate_path }),
        ));
    }
    if !target.is_absolute() {
        return Err(refuse(
            "invalid_params",
            "내보낼 경로는 절대 경로여야 합니다.".into(),
            json!({ "destination": target.to_string_lossy() }),
        ));
    }
    let target_name = target.file_name().filter(|name| !name.is_empty()).ok_or_else(|| {
        refuse(
            "invalid_params",
            "내보낼 파일 이름이 없습니다.".into(),
            json!({ "destination": target.to_string_lossy() }),
        )
    })?;
    let parent = target.parent().filter(|path| !path.as_os_str().is_empty()).ok_or_else(|| {
        refuse(
            "export_failed",
            "저장할 폴더가 없습니다.".into(),
            json!({ "destination": target.to_string_lossy() }),
        )
    })?;
    if !parent.is_dir() {
        return Err(refuse(
            "export_failed",
            "저장할 폴더가 없습니다.".into(),
            json!({ "parent": parent.to_string_lossy() }),
        ));
    }
    let lexical_receipt_target = receipt_target_for(target);
    for path in [target, lexical_receipt_target.as_path()] {
        if path_exists_no_follow(path)? {
            return Err(refuse(
                "export_exists",
                "기존 파일은 덮어쓰지 않습니다. 새 이름을 선택하세요.".into(),
                json!({ "destination": path.to_string_lossy() }),
            ));
        }
    }

    let root = std::fs::canonicalize(runtime_root).map_err(|error| {
        refuse(
            "export_failed",
            format!("Runtime 작업 폴더를 확인하지 못했습니다: {error}"),
            json!({ "root": runtime_root.to_string_lossy() }),
        )
    })?;
    let resolved_parent = std::fs::canonicalize(parent).map_err(|error| {
        refuse(
            "export_failed",
            format!("저장할 폴더를 확인하지 못했습니다: {error}"),
            json!({ "parent": parent.to_string_lossy() }),
        )
    })?;
    if resolved_parent.starts_with(&root) {
        return Err(refuse(
            "export_alias",
            "Runtime 작업 폴더 안으로는 내보낼 수 없습니다.".into(),
            json!({ "destination": target.to_string_lossy() }),
        ));
    }

    // Operate through the resolved directory rather than re-resolving a
    // user-supplied junction/symlink spelling for every publication step.
    let target = resolved_parent.join(target_name);
    let receipt_target = receipt_target_for(&target);
    for path in [target.as_path(), receipt_target.as_path()] {
        if path_exists_no_follow(path)? {
            return Err(refuse(
                "export_exists",
                "기존 파일은 덮어쓰지 않습니다. 새 이름을 선택하세요.".into(),
                json!({ "destination": path.to_string_lossy() }),
            ));
        }
    }

    let stage = create_export_stage(&resolved_parent)?;
    let staged_artifact = stage.path.join("artifact.stage");
    let staged_receipt = stage.path.join("receipt.stage");
    stage_file(artifact, &staged_artifact, "후보본")?;
    stage_file(receipt, &staged_receipt, "영수증")?;

    let receipt_value: Value = serde_json::from_slice(
        &std::fs::read(&staged_receipt).map_err(|error| {
            refuse(
                "export_failed",
                format!("임시 영수증을 읽지 못했습니다: {error}"),
                Value::Null,
            )
        })?,
    )
    .map_err(|error| {
        refuse(
            "export_receipt_mismatch",
            format!("영수증 형식이 올바르지 않습니다: {error}"),
            Value::Null,
        )
    })?;
    if verified_receipt.is_some_and(|verified| verified != &receipt_value) {
        return Err(refuse(
            "export_receipt_mismatch",
            "Runtime이 검증한 영수증과 디스크의 영수증이 다릅니다.".into(),
            json!({ "sessionId": session_id, "runId": run_id }),
        ));
    }
    let declared = &receipt_value["candidate"];
    let declared_path = declared["path"].as_str();
    let declared_sha256 = declared["sha256"].as_str();
    let declared_bytes = declared["bytes"].as_u64();
    if receipt_value["sessionId"].as_str() != Some(session_id)
        || receipt_value["runId"].as_str() != Some(run_id)
        || declared_path != Some(candidate_path)
        || declared_sha256.is_none()
        || declared_bytes.is_none()
    {
        return Err(refuse(
            "export_receipt_mismatch",
            "영수증의 후보본 결합 정보가 현재 후보본과 맞지 않습니다.".into(),
            json!({
                "sessionId": session_id,
                "runId": run_id,
                "candidatePath": candidate_path,
            }),
        ));
    }

    let (sha256, bytes) = digest::sha256_file(&staged_artifact).map_err(|error| {
        refuse(
            "export_failed",
            format!("임시 후보본을 다시 읽지 못했습니다: {error}"),
            Value::Null,
        )
    })?;
    if declared_sha256 != Some(sha256.as_str()) || declared_bytes != Some(bytes) {
        return Err(refuse(
            "export_hash_mismatch",
            "후보본 바이트가 영수증에 기록된 해시 또는 크기와 다릅니다.".into(),
            json!({ "sha256": sha256, "bytes": bytes }),
        ));
    }
    let (receipt_sha256, receipt_bytes) =
        digest::sha256_file(&staged_receipt).map_err(|error| {
            refuse(
                "export_failed",
                format!("임시 영수증을 다시 읽지 못했습니다: {error}"),
                Value::Null,
            )
        })?;

    // This is deliberately not called a two-file atomic transaction. The
    // artifact is published first and the receipt last, both no-replace, like
    // Runtime publication where receipt presence marks a complete pair. A hard
    // process stop can leave a new orphan artifact/staging directory, but it
    // cannot overwrite or delete a file that existed before this export began.
    observe(ExportStep::Staged, &target, &receipt_target);
    publish_new(&staged_artifact, &target, "후보본")?;
    observe(ExportStep::ArtifactPublished, &target, &receipt_target);
    publish_new(&staged_receipt, &receipt_target, "영수증")?;
    observe(ExportStep::ReceiptPublished, &target, &receipt_target);

    let (published_sha256, published_bytes) = digest::sha256_file(&target).map_err(|error| {
        refuse(
            "export_failed",
            format!("게시한 후보본을 다시 읽지 못했습니다: {error}"),
            json!({ "destination": target.to_string_lossy() }),
        )
    })?;
    let (published_receipt_sha256, published_receipt_bytes) =
        digest::sha256_file(&receipt_target).map_err(|error| {
            refuse(
                "export_failed",
                format!("게시한 영수증을 다시 읽지 못했습니다: {error}"),
                json!({ "destination": receipt_target.to_string_lossy() }),
            )
        })?;
    if published_sha256 != sha256
        || published_bytes != bytes
        || published_receipt_sha256 != receipt_sha256
        || published_receipt_bytes != receipt_bytes
    {
        return Err(refuse(
            "export_hash_mismatch",
            "게시된 후보본 또는 영수증이 staging에서 검증한 바이트와 다릅니다.".into(),
            json!({
                "destination": target.to_string_lossy(),
                "receiptDestination": receipt_target.to_string_lossy(),
            }),
        ));
    }
    Ok(json!({
        "path": target.to_string_lossy(),
        "sha256": published_sha256,
        "bytes": published_bytes,
        "receiptPath": receipt_target.to_string_lossy(),
        "staging": {
            "state": "retained_anchor",
            "path": stage.path.to_string_lossy(),
            "note": "identity-bound cleanup is not implemented; hard links do not duplicate content bytes",
        },
    }))
}

fn export_candidate_files(
    runtime_root: &Path,
    artifact: &Path,
    receipt: &Path,
    session_id: &str,
    run_id: &str,
    candidate_path: &str,
    target: &Path,
) -> Result<Value, Value> {
    export_candidate_files_with_observer(
        runtime_root,
        artifact,
        receipt,
        None,
        session_id,
        run_id,
        candidate_path,
        target,
        |_, _, _| {},
    )
}

fn export_candidate_files_verified(
    runtime_root: &Path,
    artifact: &Path,
    receipt: &Path,
    verified_receipt: &Value,
    session_id: &str,
    run_id: &str,
    candidate_path: &str,
    target: &Path,
) -> Result<Value, Value> {
    export_candidate_files_with_observer(
        runtime_root,
        artifact,
        receipt,
        Some(verified_receipt),
        session_id,
        run_id,
        candidate_path,
        target,
        |_, _, _| {},
    )
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
/// - a successful return means the receipt travelled with the artifact. A hard
///   stop can leave an artifact without a receipt, which is incomplete rather
///   than a successful export;
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
    let runtime_id = |value: &str| {
        value.len() == 32
            && value
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    };
    for (name, value) in [("sessionId", &session_id), ("runId", &run_id)] {
        if !runtime_id(value) {
            return Err(refuse(
                "invalid_params",
                format!("{name}은(는) Runtime의 32자리 식별자여야 합니다."),
                json!({ "field": name, "value": value }),
            ));
        }
    }
    if !is_canonical_candidate_name(&candidate_path) {
        return Err(refuse(
            "invalid_params",
            "candidatePath가 Runtime의 canonical artifact 이름이 아닙니다.".into(),
            json!({ "field": "candidatePath", "value": candidate_path }),
        ));
    }

    // A direct webview invoke must cross the same verified receipt boundary as
    // the UI path. Runtime receipt/read validates the receipt body, identities,
    // canonical candidate role, and artifact digest before the shell copies.
    let (root, verified_receipt) = {
        let guard = state.0.lock().unwrap();
        let root = guard.status().root.ok_or_else(|| {
            refuse(
                "sidecar_down",
                "런타임 작업 폴더를 알 수 없습니다.".into(),
                Value::Null,
            )
        })?;
        let verified = guard.call(
            "receipt/read",
            Some(json!({ "sessionId": session_id, "runId": run_id })),
        )?;
        let receipt = verified.get("receipt").cloned().ok_or_else(|| {
            refuse(
                "export_receipt_mismatch",
                "Runtime receipt/read 응답에 영수증이 없습니다.".into(),
                json!({ "sessionId": session_id, "runId": run_id }),
            )
        })?;
        (root, receipt)
    };
    let run_dir = Path::new(&root)
        .join("sessions")
        .join(&session_id)
        .join("candidates")
        .join(&run_id);
    let artifact_path = run_dir.join(&candidate_path);
    let receipt_path = run_dir.join("receipt.json");
    for path in [&artifact_path, &receipt_path] {
        if !is_regular_file_no_follow(path) {
            return Err(refuse(
                "artifact_missing",
                "후보본이나 영수증이 제자리에 없습니다.".into(),
                json!({ "path": path.to_string_lossy() }),
            ));
        }
    }
    let canonical_root = std::fs::canonicalize(&root).map_err(|_| {
        refuse(
            "artifact_missing",
            "Runtime 작업 폴더를 확인하지 못했습니다.".into(),
            Value::Null,
        )
    })?;
    let canonical_run = std::fs::canonicalize(&run_dir).map_err(|_| {
        refuse(
            "artifact_missing",
            "후보본 작업 폴더를 확인하지 못했습니다.".into(),
            Value::Null,
        )
    })?;
    if !canonical_run.starts_with(&canonical_root) {
        return Err(refuse(
            "export_alias",
            "후보본 작업 폴더가 Runtime 작업 폴더 밖을 가리킵니다.".into(),
            Value::Null,
        ));
    }
    let artifact = std::fs::canonicalize(&artifact_path).map_err(|_| {
        refuse(
            "artifact_missing",
            "후보본을 확인하지 못했습니다.".into(),
            Value::Null,
        )
    })?;
    let receipt = std::fs::canonicalize(&receipt_path).map_err(|_| {
        refuse(
            "artifact_missing",
            "영수증을 확인하지 못했습니다.".into(),
            Value::Null,
        )
    })?;
    if artifact.parent() != Some(canonical_run.as_path())
        || receipt.parent() != Some(canonical_run.as_path())
    {
        return Err(refuse(
            "export_alias",
            "후보본 또는 영수증이 canonical run 폴더 밖을 가리킵니다.".into(),
            Value::Null,
        ));
    }

    export_candidate_files_verified(
        &canonical_root,
        &artifact,
        &receipt,
        &verified_receipt,
        &session_id,
        &run_id,
        &candidate_path,
        &PathBuf::from(destination),
    )
}

#[cfg(test)]
mod export_tests {
    use super::*;
    use std::time::{SystemTime, UNIX_EPOCH};

    struct TestDir(PathBuf);

    impl TestDir {
        fn new(label: &str) -> Self {
            let nonce = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .expect("clock after epoch")
                .as_nanos();
            let path = std::env::temp_dir().join(format!(
                "rigorloom-export-{label}-{}-{nonce}",
                std::process::id()
            ));
            std::fs::create_dir(&path).expect("create test directory");
            Self(path)
        }
    }

    impl Drop for TestDir {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    fn source_pair(dir: &Path) -> (PathBuf, PathBuf) {
        std::fs::create_dir_all(dir).unwrap();
        let artifact = dir.join("artifact.hwpx");
        let receipt = dir.join("receipt.json");
        std::fs::write(&artifact, b"new candidate").unwrap();
        let (sha256, bytes) = digest::sha256_file(&artifact).unwrap();
        std::fs::write(
            &receipt,
            serde_json::to_vec_pretty(&json!({
                "sessionId": "session",
                "runId": "run",
                "candidate": {
                    "path": "artifact.hwpx",
                    "sha256": sha256,
                    "bytes": bytes,
                }
            }))
            .unwrap(),
        )
        .unwrap();
        (artifact, receipt)
    }

    fn layout(label: &str) -> (TestDir, PathBuf, PathBuf, PathBuf, PathBuf) {
        let temp = TestDir::new(label);
        let runtime_root = temp.0.join("runtime-root");
        let export_dir = temp.0.join("exports");
        std::fs::create_dir(&runtime_root).unwrap();
        std::fs::create_dir(&export_dir).unwrap();
        let (artifact, receipt) = source_pair(&runtime_root.join("candidate"));
        (temp, runtime_root, export_dir, artifact, receipt)
    }

    fn has_stage_residue(export_dir: &Path) -> bool {
        std::fs::read_dir(export_dir).unwrap().any(|entry| {
            entry
                .unwrap()
                .file_name()
                .to_string_lossy()
                .starts_with(".rigorloom-export-")
        })
    }

    #[test]
    fn a_new_name_exports_a_verified_pair() {
        let (_temp, runtime_root, export_dir, artifact, receipt) = layout("new-pair");
        let target = export_dir.join("chosen.hwpx");

        let result = export_candidate_files(
            &runtime_root,
            &artifact,
            &receipt,
            "session",
            "run",
            "artifact.hwpx",
            &target,
        )
        .unwrap();

        assert_eq!(std::fs::read(&target).unwrap(), b"new candidate");
        assert_eq!(
            std::fs::read(export_dir.join("chosen.hwpx.receipt.json")).unwrap(),
            std::fs::read(&receipt).unwrap()
        );
        assert_eq!(result["sha256"], digest::sha256_file(&target).unwrap().0);
        assert!(has_stage_residue(&export_dir));
    }

    #[test]
    fn export_refuses_to_overwrite_an_existing_pair() {
        let (_temp, runtime_root, export_dir, artifact, receipt) = layout("existing-pair");
        let target = export_dir.join("chosen.hwpx");
        let receipt_target = export_dir.join("chosen.hwpx.receipt.json");
        std::fs::write(&target, b"existing document").unwrap();
        std::fs::write(&receipt_target, b"existing receipt").unwrap();

        let error = export_candidate_files(
            &runtime_root,
            &artifact,
            &receipt,
            "session",
            "run",
            "artifact.hwpx",
            &target,
        )
        .unwrap_err();

        assert_eq!(error["code"], "export_exists");
        assert_eq!(std::fs::read(&target).unwrap(), b"existing document");
        assert_eq!(std::fs::read(&receipt_target).unwrap(), b"existing receipt");
        assert!(!has_stage_residue(&export_dir));
    }

    #[test]
    fn a_receipt_directory_refuses_before_the_artifact_is_published() {
        let (_temp, runtime_root, export_dir, artifact, receipt) = layout("receipt-directory");
        let target = export_dir.join("chosen.hwpx");
        let receipt_target = export_dir.join("chosen.hwpx.receipt.json");
        std::fs::create_dir(&receipt_target).unwrap();

        assert!(export_candidate_files(
            &runtime_root,
            &artifact,
            &receipt,
            "session",
            "run",
            "artifact.hwpx",
            &target,
        )
        .is_err());
        assert!(!target.exists());
        assert!(receipt_target.is_dir());
        assert!(!has_stage_residue(&export_dir));
    }

    #[test]
    fn a_hash_mismatch_publishes_nothing() {
        let (_temp, runtime_root, export_dir, artifact, receipt) = layout("hash-mismatch");
        let mut value: Value = serde_json::from_slice(&std::fs::read(&receipt).unwrap()).unwrap();
        value["candidate"]["sha256"] = Value::String("0".repeat(64));
        std::fs::write(&receipt, serde_json::to_vec_pretty(&value).unwrap()).unwrap();
        let target = export_dir.join("chosen.hwpx");

        let error = export_candidate_files(
            &runtime_root,
            &artifact,
            &receipt,
            "session",
            "run",
            "artifact.hwpx",
            &target,
        )
        .unwrap_err();

        assert_eq!(error["code"], "export_hash_mismatch");
        assert!(!target.exists());
        assert!(!receipt_target_for(&target).exists());
        assert!(has_stage_residue(&export_dir));
    }

    #[test]
    fn a_receipt_changed_after_runtime_verification_is_refused() {
        let (_temp, runtime_root, export_dir, artifact, receipt) =
            layout("verified-receipt-drift");
        let verified: Value =
            serde_json::from_slice(&std::fs::read(&receipt).unwrap()).unwrap();
        let mut changed = verified.clone();
        changed["sessionId"] = Value::String("another-session".into());
        std::fs::write(&receipt, serde_json::to_vec_pretty(&changed).unwrap()).unwrap();
        let target = export_dir.join("chosen.hwpx");

        let error = export_candidate_files_verified(
            &runtime_root,
            &artifact,
            &receipt,
            &verified,
            "session",
            "run",
            "artifact.hwpx",
            &target,
        )
        .unwrap_err();

        assert_eq!(error["code"], "export_receipt_mismatch");
        assert!(!target.exists());
        assert!(!receipt_target_for(&target).exists());
        assert!(has_stage_residue(&export_dir));
    }

    #[test]
    fn a_runtime_internal_destination_is_refused() {
        let (_temp, runtime_root, _export_dir, artifact, receipt) = layout("runtime-alias");
        let target = runtime_root.join("new-export.hwpx");

        let error = export_candidate_files(
            &runtime_root,
            &artifact,
            &receipt,
            "session",
            "run",
            "artifact.hwpx",
            &target,
        )
        .unwrap_err();

        assert_eq!(error["code"], "export_alias");
        assert!(!target.exists());
    }

    #[test]
    fn the_runtime_receipt_cannot_be_exported_as_the_document() {
        let (_temp, runtime_root, export_dir, _artifact, receipt) = layout("role-alias");
        let target = export_dir.join("chosen.json");

        let error = export_candidate_files(
            &runtime_root,
            &receipt,
            &receipt,
            "session",
            "run",
            "receipt.json",
            &target,
        )
        .unwrap_err();

        assert_eq!(error["code"], "invalid_params");
        assert!(!target.exists());
    }

    #[test]
    fn a_second_publish_failure_never_deletes_other_bytes() {
        let (_temp, runtime_root, export_dir, artifact, receipt) = layout("second-publish");
        let target = export_dir.join("chosen.hwpx");
        let sentinel = export_dir.join("existing-unrelated.hwpx");
        std::fs::write(&sentinel, b"keep me").unwrap();

        let error = export_candidate_files_with_observer(
            &runtime_root,
            &artifact,
            &receipt,
            None,
            "session",
            "run",
            "artifact.hwpx",
            &target,
            |step, _target, receipt_target| {
                if step == ExportStep::Staged {
                    std::fs::create_dir(receipt_target).unwrap();
                }
            },
        )
        .unwrap_err();

        assert_eq!(error["code"], "export_exists");
        assert_eq!(std::fs::read(&sentinel).unwrap(), b"keep me");
        assert_eq!(std::fs::read(&target).unwrap(), b"new candidate");
        assert!(receipt_target_for(&target).is_dir());
        assert!(has_stage_residue(&export_dir));
    }

    #[test]
    fn final_rehash_detects_bytes_changed_after_publication() {
        let (_temp, runtime_root, export_dir, artifact, receipt) =
            layout("published-drift");
        let target = export_dir.join("chosen.hwpx");
        let sentinel = export_dir.join("existing-unrelated.hwpx");
        std::fs::write(&sentinel, b"keep me").unwrap();

        let error = export_candidate_files_with_observer(
            &runtime_root,
            &artifact,
            &receipt,
            None,
            "session",
            "run",
            "artifact.hwpx",
            &target,
            |step, target, _| {
                if step == ExportStep::ReceiptPublished {
                    std::fs::write(target, b"changed after publication").unwrap();
                }
            },
        )
        .unwrap_err();

        assert_eq!(error["code"], "export_hash_mismatch");
        assert_eq!(std::fs::read(&sentinel).unwrap(), b"keep me");
        assert!(has_stage_residue(&export_dir));
    }

    const ABORT_STEP_ENV: &str = "RIGORLOOM_EXPORT_ABORT_STEP";

    #[test]
    fn export_abort_worker() {
        let Ok(abort_at) = std::env::var(ABORT_STEP_ENV) else {
            return;
        };
        let runtime_root = PathBuf::from(std::env::var("RIGORLOOM_EXPORT_TEST_ROOT").unwrap());
        let artifact = PathBuf::from(std::env::var("RIGORLOOM_EXPORT_TEST_ARTIFACT").unwrap());
        let receipt = PathBuf::from(std::env::var("RIGORLOOM_EXPORT_TEST_RECEIPT").unwrap());
        let target = PathBuf::from(std::env::var("RIGORLOOM_EXPORT_TEST_TARGET").unwrap());

        let _ = export_candidate_files_with_observer(
            &runtime_root,
            &artifact,
            &receipt,
            None,
            "session",
            "run",
            "artifact.hwpx",
            &target,
            |step, _, _| {
                let name = match step {
                    ExportStep::Staged => "staged",
                    ExportStep::ArtifactPublished => "artifact",
                    ExportStep::ReceiptPublished => "receipt",
                };
                if name == abort_at {
                    std::process::abort();
                }
            },
        );
        panic!("abort worker passed the requested step without terminating");
    }

    #[test]
    fn hard_termination_at_each_publication_step_preserves_existing_bytes() {
        for step in ["staged", "artifact", "receipt"] {
            let (_temp, runtime_root, export_dir, artifact, receipt) =
                layout(&format!("abort-{step}"));
            let target = export_dir.join("chosen.hwpx");
            let receipt_target = receipt_target_for(&target);
            let sentinel = export_dir.join("existing-unrelated.hwpx");
            std::fs::write(&sentinel, b"keep me").unwrap();

            let status = std::process::Command::new(std::env::current_exe().unwrap())
                .arg("--exact")
                .arg("export_tests::export_abort_worker")
                .arg("--nocapture")
                .env(ABORT_STEP_ENV, step)
                .env("RIGORLOOM_EXPORT_TEST_ROOT", &runtime_root)
                .env("RIGORLOOM_EXPORT_TEST_ARTIFACT", &artifact)
                .env("RIGORLOOM_EXPORT_TEST_RECEIPT", &receipt)
                .env("RIGORLOOM_EXPORT_TEST_TARGET", &target)
                .status()
                .unwrap();

            assert!(!status.success(), "worker did not terminate at {step}");
            assert_eq!(std::fs::read(&sentinel).unwrap(), b"keep me");
            match step {
                "staged" => {
                    assert!(!target.exists());
                    assert!(!receipt_target.exists());
                }
                "artifact" => {
                    assert_eq!(std::fs::read(&target).unwrap(), b"new candidate");
                    assert!(!receipt_target.exists());
                }
                "receipt" => {
                    assert_eq!(std::fs::read(&target).unwrap(), b"new candidate");
                    assert!(receipt_target.is_file());
                }
                _ => unreachable!(),
            }
            assert!(
                has_stage_residue(&export_dir),
                "hard termination should leave owned staging evidence at {step}"
            );
        }
    }
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

// --- the Agent Host ------------------------------------------------------------
//
// Phase 5. The composer sends here, and what comes back lands in the SAME
// review queue as a manual edit and the mock button. The authority split is not
// enforced by this file: `host.py` opens an AGENT-authority door, where
// `approval/resolve` and `plan/apply` are absent from the registry (protocol
// §4). The shell could not grant them if it wanted to.

fn resource_dir(app: &AppHandle) -> Option<PathBuf> {
    app.path().resource_dir().ok()
}

#[tauri::command]
fn agent_host_status(app: AppHandle) -> Value {
    agenthost::status(resource_dir(&app).as_deref(), &repo_root())
}

/// `--capabilities`: the three-state profile, keyless-honest.
///
/// No document and no network. When a credential IS stored it is attached, so
/// the payload's `notes.credential.state` can say `present` — which is the one
/// thing a 연결 확인 button exists to answer.
#[tauri::command]
fn agent_host_capabilities(
    app: AppHandle,
    provider: String,
    store_key: Option<String>,
) -> Result<Value, Value> {
    let launch = agenthost::resolve_host(resource_dir(&app).as_deref(), &repo_root())
        .map_err(|m| refuse("agent_host_missing", m, Value::Null))?;
    agenthost::capabilities(
        &launch,
        &app_data_dir(&app),
        &provider,
        store_key.as_deref(),
    )
    .map_err(|m| refuse("agent_host_failed", m, Value::Null))
}

/// Write a provider config. References only — a secret-shaped member is refused
/// here by NAME, before the file exists, and the Agent Host refuses it again at
/// load. Returns what landed, so the caller (and the smoke) can read it back.
#[tauri::command]
fn agent_host_save_config(
    app: AppHandle,
    provider: String,
    settings: Value,
    has_credential: bool,
) -> Result<Value, Value> {
    let (path, document) =
        agenthost::write_config(&app_data_dir(&app), &provider, &settings, has_credential)
            .map_err(|m| refuse("config_invalid", m, json!({ "provider": provider })))?;
    Ok(json!({ "path": path.to_string_lossy(), "config": document }))
}

/// Read a provider config back off disk, verbatim.
#[tauri::command]
fn agent_host_read_config(app: AppHandle, provider: String) -> Value {
    let path = app_data_dir(&app)
        .join("agenthost")
        .join(format!("{provider}.json"));
    let config = std::fs::read_to_string(&path)
        .ok()
        .and_then(|text| serde_json::from_str::<Value>(&text).ok());
    json!({
        "path": path.to_string_lossy(),
        "exists": path.is_file(),
        "config": config,
    })
}

#[tauri::command]
#[allow(clippy::too_many_arguments)]
fn agent_host_run(
    app: AppHandle,
    state: State<'_, Runtime>,
    run: State<'_, AgentRun>,
    session_id: String,
    instruction: String,
    provider: String,
    store_key: Option<String>,
    scenario: Option<String>,
    turn_id: String,
) -> Result<Value, Value> {
    let launch = agenthost::resolve_host(resource_dir(&app).as_deref(), &repo_root())
        .map_err(|m| refuse("agent_host_missing", m, Value::Null))?;
    let root = state.0.lock().unwrap().status().root.ok_or_else(|| {
        refuse(
            "sidecar_down",
            "런타임 작업 폴더를 알 수 없습니다.".into(),
            Value::Null,
        )
    })?;
    agenthost::run_turn(
        &app,
        &run.0,
        &launch,
        &app_data_dir(&app),
        Path::new(&root),
        &session_id,
        &provider,
        &instruction,
        store_key.as_deref(),
        scenario.as_deref(),
        &turn_id,
    )
}

#[tauri::command]
fn agent_host_stop(run: State<'_, AgentRun>) -> bool {
    agenthost::stop(&run.0)
}

// --- the credential store --------------------------------------------------------
//
// One direction only. A secret goes in from the webview and never comes back
// out to it: `credential_status` answers present/absent and a byte count, and
// the value is read exactly once per run, inside `agenthost::run_turn`, into
// one child process's environment.

#[tauri::command]
fn credential_set(key: String, secret: String) -> Result<Value, Value> {
    let bytes = credstore::set(&key, &secret)
        .map_err(|m| refuse("credential_store_failed", m, json!({ "key": key })))?;
    Ok(json!({ "key": key, "state": "present", "bytes": bytes }))
}

#[tauri::command]
fn credential_status(key: String) -> Value {
    credstore::status(&key)
}

#[tauri::command]
fn credential_delete(key: String) -> Result<Value, Value> {
    let removed = credstore::delete(&key)
        .map_err(|m| refuse("credential_store_failed", m, json!({ "key": key })))?;
    Ok(json!({ "key": key, "removed": removed, "state": "absent" }))
}

// --- 작업 팩 ---------------------------------------------------------------------

#[tauri::command]
fn task_packs(app: AppHandle) -> Value {
    taskpacks::list(resource_dir(&app).as_deref(), &repo_root())
}

// --- the window ------------------------------------------------------------------

/// Remember where the window was, so reopening lands where the user left it.
///
/// Physical pixels, plus the scale factor they were measured at, because a
/// position restored on a differently-scaled monitor without that number lands
/// somewhere else. `visible_on_any_monitor` is checked on restore rather than
/// trusted: a saved position on a monitor that is no longer attached would put
/// the window off-screen with no way to drag it back.
fn save_geometry(window: &tauri::Window, clock: &GeometryClock) {
    {
        let mut last = clock.0.lock().unwrap();
        if last.elapsed() < std::time::Duration::from_millis(700) {
            return;
        }
        *last = std::time::Instant::now();
    }
    let (Ok(size), Ok(position)) = (window.inner_size(), window.outer_position()) else {
        return;
    };
    let maximized = window.is_maximized().unwrap_or(false);
    // A maximized window's size is the screen's, and restoring THAT as a
    // non-maximized size is how an app comes back subtly wrong. Remember the
    // flag and leave the last restored size alone.
    let patch = if maximized {
        json!({ "window": { "maximized": true } })
    } else {
        json!({ "window": {
            "width": size.width, "height": size.height,
            "x": position.x, "y": position.y,
            "scale": window.scale_factor().unwrap_or(1.0),
            "maximized": false,
        }})
    };
    let app = window.app_handle();
    let current = prefs::load(app);
    let mut merged = current
        .get("window")
        .and_then(Value::as_object)
        .cloned()
        .unwrap_or_default();
    if let Some(fields) = patch["window"].as_object() {
        for (key, value) in fields {
            merged.insert(key.clone(), value.clone());
        }
    }
    let _ = prefs::merge(app, json!({ "window": merged }));
}

fn restore_geometry(window: &tauri::WebviewWindow) {
    let saved = prefs::load(&window.app_handle().clone());
    let Some(geometry) = saved.get("window").and_then(Value::as_object) else {
        return;
    };
    if let (Some(width), Some(height)) = (
        geometry.get("width").and_then(Value::as_u64),
        geometry.get("height").and_then(Value::as_u64),
    ) {
        // Never smaller than the editor minimum: a prefs file written by an
        // older build, or edited by hand, must not be able to produce a window
        // too small to use.
        let _ = window.set_size(tauri::PhysicalSize::new(
            width.max(1024) as u32,
            height.max(640) as u32,
        ));
    }
    if let (Some(x), Some(y)) = (
        geometry.get("x").and_then(Value::as_i64),
        geometry.get("y").and_then(Value::as_i64),
    ) {
        let position = tauri::PhysicalPosition::new(x as i32, y as i32);
        let _ = window.set_position(position);
        // Off every monitor: centre instead, rather than leaving a window the
        // user cannot reach.
        if !on_a_monitor(window, x as i32, y as i32) {
            let _ = window.center();
        }
    }
    if geometry.get("maximized").and_then(Value::as_bool) == Some(true) {
        let _ = window.maximize();
    }
}

fn on_a_monitor(window: &tauri::WebviewWindow, x: i32, y: i32) -> bool {
    let Ok(monitors) = window.available_monitors() else {
        return true;
    };
    monitors.iter().any(|monitor| {
        let position = monitor.position();
        let size = monitor.size();
        x >= position.x
            && y >= position.y
            && x < position.x + size.width as i32
            && y < position.y + size.height as i32
    })
}

/// What the window is right now. Read-only; the harness compares it against
/// what the previous launch left in prefs, which is the only way to prove a
/// restore actually restored rather than landing on the default by chance.
#[tauri::command]
fn window_geometry(app: AppHandle) -> Value {
    let Some(window) = app.get_webview_window("main") else {
        return Value::Null;
    };
    let size = window.inner_size().ok();
    let position = window.outer_position().ok();
    json!({
        "width": size.map(|s| s.width),
        "height": size.map(|s| s.height),
        "x": position.map(|p| p.x),
        "y": position.map(|p| p.y),
        "maximized": window.is_maximized().unwrap_or(false),
        "fullscreen": window.is_fullscreen().unwrap_or(false),
        "scale": window.scale_factor().unwrap_or(1.0),
    })
}

/// F11. Reported back so the UI can label the control rather than guess.
#[tauri::command]
fn toggle_fullscreen(app: AppHandle) -> Result<bool, String> {
    let Some(window) = app.get_webview_window("main") else {
        return Err("창을 찾지 못했습니다".into());
    };
    let next = !window.is_fullscreen().map_err(|e| e.to_string())?;
    window.set_fullscreen(next).map_err(|e| e.to_string())?;
    Ok(next)
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
        // A second, genuinely different form. The editing phase opens it while
        // a queue is pending, which is how staleness is exercised without ever
        // touching a session copy.
        "corpus2": std::env::var("RIGORLOOM_SMOKE_CORPUS2").ok().filter(|v| !v.is_empty()),
        // Where the export phase may write, inside the harness run directory.
        // Passed in rather than chosen, because the native save dialog cannot
        // be driven from here and a headless run must not open one.
        "exportPath": std::env::var("RIGORLOOM_SMOKE_EXPORT").ok().filter(|v| !v.is_empty()),
        // The IME harness types into a field that must start empty, so the
        // screenshot phase's pre-filled value is suppressed for that run.
        "imeEmpty": std::env::var("RIGORLOOM_IME_EMPTY").is_ok(),
        // A session the harness put under --root BEFORE the app started, already
        // carrying the corpus's own Hancom render of its form. The overlay phase
        // needs a page with real geometry on it, and `document/renderPrepare`
        // cannot produce one on a machine that already has Hancom open — it
        // refuses `com_busy` and will not terminate somebody else's session. The
        // app is told the id rather than discovering it, so nothing in the shell
        // has to know about the substitution to find its way to the document.
        // See desktop/scripts/stage-rendered-session.py for the provenance.
        "stagedSession": std::env::var("RIGORLOOM_SMOKE_STAGED").ok().filter(|v| !v.is_empty()),
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

/// A second report file, written without exiting.
///
/// The IME harness needs two moments from one process: "the field is open,
/// start typing" and "here is what the field ended up with". `smoke_ready`
/// covers the first; this covers the second, at `RIGORLOOM_SMOKE_FINAL`.
#[tauri::command]
fn smoke_final(detail: Value) -> Result<(), String> {
    let Ok(path) = std::env::var("RIGORLOOM_SMOKE_FINAL") else {
        return Ok(());
    };
    if let Some(parent) = std::path::Path::new(&path).parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let body = serde_json::to_string_pretty(&json!({ "final": true, "detail": detail }))
        .unwrap_or_else(|_| "{\"final\":true}".into());
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
        .manage(AgentRun(agenthost::RunSlot::default()))
        .manage(GeometryClock(Mutex::new(
            std::time::Instant::now() - std::time::Duration::from_secs(5),
        )))
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
            agent_host_status,
            agent_host_capabilities,
            agent_host_save_config,
            agent_host_read_config,
            agent_host_run,
            agent_host_stop,
            credential_set,
            credential_status,
            credential_delete,
            task_packs,
            toggle_fullscreen,
            window_geometry,
            smoke_config,
            smoke_ready,
            smoke_final,
            smoke_finish,
        ])
        .setup(|app| {
            install_panic_hook(app.handle().clone());
            if let Some(window) = app.get_webview_window("main") {
                restore_geometry(&window);
                // Persist once at startup, past the throttle. Without this a
                // launch that is never resized leaves nothing behind, and
                // "the window remembers" would only be true for a user who
                // happened to drag it — which is not a property, it is luck.
                if let Some(clock) = app.try_state::<GeometryClock>() {
                    *clock.0.lock().unwrap() =
                        std::time::Instant::now() - std::time::Duration::from_secs(5);
                    save_geometry(&window.as_ref().window(), &clock);
                }
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            match event {
                // Where the window is, remembered as it moves. Throttled in
                // `save_geometry`: a drag emits one of these per frame.
                tauri::WindowEvent::Resized(_) | tauri::WindowEvent::Moved(_) => {
                    if let Some(clock) = window.app_handle().try_state::<GeometryClock>() {
                        save_geometry(window, &clock);
                    }
                }
                // The throttle would otherwise swallow the last nudge before a
                // close. Reset the clock so this one write always lands.
                tauri::WindowEvent::CloseRequested { .. } => {
                    if let Some(clock) = window.app_handle().try_state::<GeometryClock>() {
                        *clock.0.lock().unwrap() =
                            std::time::Instant::now() - std::time::Duration::from_secs(5);
                        save_geometry(window, &clock);
                    }
                }
                tauri::WindowEvent::Destroyed => {
                    // Stop the Agent Host before the sidecar: it holds its own
                    // door onto the same root, and an orphaned turn loop would
                    // keep writing events after the window is gone.
                    if let Some(run) = window.app_handle().try_state::<AgentRun>() {
                        agenthost::stop(&run.0);
                    }
                    if let Some(state) = window.app_handle().try_state::<Runtime>() {
                        state.0.lock().unwrap().shutdown();
                    }
                }
                _ => {}
            }
        })
        .run(tauri::generate_context!())
        .expect("failed to start the Rigorloom desktop shell");
}
