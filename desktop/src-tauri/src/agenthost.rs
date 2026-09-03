//! Spawning the Agent Host, and tailing what it does while it does it.
//!
//! ## Why a process per turn, and not one long-lived host
//!
//! `agenthost/scripts/host.py` is a one-shot CLI: parse argv, open a door, run
//! ONE `AgentHost.run(instruction)` turn loop, print one JSON document, exit.
//! It has no stdin command loop and no resume — `resumableThread` is `no`
//! everywhere and the host resends the whole history each turn *inside* one
//! run. Keeping such a process alive between the user's messages would mean
//! inventing a shell↔host protocol that does not exist, in a tree this slice
//! does not own (`agenthost/**` is read-only here). So: one process per
//! conversation turn, exactly as `run_mock_agent` already does for the mock
//! agent, and the conversation is stitched together on this side.
//!
//! The cost is honest and small: a cold Python start per message (measured in
//! the smoke, ~2 s here). The benefit is that a hung provider cannot wedge the
//! shell — the process is killed and the next message starts clean — and that
//! the agent's authority boundary is a process boundary, which is the property
//! the whole design rests on.
//!
//! ## Why the events file is tailed rather than waited for
//!
//! The run payload arrives only when the process exits, and a live provider
//! turn loop can take tens of seconds. `--events FILE` mirrors the ordered
//! event log to JSONL *as it happens* (`ah_events.EventLog.append` opens,
//! writes and closes per line, so a reader never sees a partial line). A reader
//! thread polls that file, batches whole lines on a 120 ms timer, and emits
//! arrays — the spike's measured rule, restated: emitting per line costs
//! 1.1 MiB/s against 7.0 MiB/s for batching in Rust.
//!
//! ## Where the secret is, and where it is not
//!
//! The config file this writes carries a credential REFERENCE only, and the
//! Agent Host refuses a config with a secret-shaped member by name anyway. The
//! value is read from the OS credential store (`credstore.rs`) and set as an
//! environment variable **on this one child's `Command`** — never on this
//! process, never in a file, never in an argument, never in an event. The
//! reference in the config names that variable, so the two halves meet in the
//! child's environment and nowhere else.
//!
//! (The Agent Host declares an `os_store` credential source and refuses it —
//! `credential_source_unsupported`, "not implemented in this slice". Handing it
//! an env reference whose variable exists only in its own environment is the
//! same guarantee reached through the door that IS implemented. Recorded as a
//! runtime gap in the README rather than worked around silently.)

use std::io::Read;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};

use serde_json::{json, Value};
use tauri::{AppHandle, Emitter};

use crate::credstore;

/// Batched Agent Host events. One channel, arrays, same rule as the sidecar's.
pub const EVENT_AGENT: &str = "agenthost://events";

/// How often the tail thread flushes what it has read.
const FLUSH_MS: u64 = 120;

/// A run that outlives this is not working; it is stuck. The Anthropic adapter
/// bounds its own HTTP at 120 s and retries once, and eight turns of that is
/// the worst honest case, so this sits above it rather than under it.
const RUN_TIMEOUT_SECS: u64 = 20 * 60;

/// Where `host.py` is and what will run it.
pub struct HostLaunch {
    pub program: PathBuf,
    /// Everything before the run's own flags: the script path, when the
    /// program is an interpreter rather than the script's own runner.
    pub prefix: Vec<String>,
    pub script: PathBuf,
    pub engine_root: PathBuf,
    pub mode: &'static str,
}

/// Resolve the Agent Host without guessing, and report which way it went.
///
/// Three ways, in order:
///
/// 1. `RIGORLOOM_AGENT_HOST` names `host.py` outright. This is how the scripted
///    evidence points a PACKAGED build at a repo checkout.
/// 2. The bundled one-dir sidecar carries `repo/agenthost/scripts/host.py`, and
///    `rigorloomd.exe` runs a `.py` first argument exactly like `python
///    script.py` does (`sidecar/rigorloomd.py`, job 2). A shipped install needs
///    no interpreter on the machine.
/// 3. The compiled-in repo root has it — a dev run, through `RIGORLOOM_PYTHON`
///    or whatever `python` resolves to.
///
/// None of the three: the composer says so and stays honest rather than
/// offering a send button that cannot send.
pub fn resolve_host(resource_dir: Option<&Path>, repo_root: &Path) -> Result<HostLaunch, String> {
    let python = std::env::var("RIGORLOOM_PYTHON").unwrap_or_else(|_| "python".into());

    if let Some(explicit) = std::env::var_os("RIGORLOOM_AGENT_HOST") {
        let script = PathBuf::from(explicit);
        if script.is_file() {
            // parents: scripts -> agenthost -> repo root
            let engine_root = script
                .parent()
                .and_then(Path::parent)
                .and_then(Path::parent)
                .map(PathBuf::from)
                .unwrap_or_else(|| repo_root.to_path_buf());
            return Ok(HostLaunch {
                program: PathBuf::from(&python),
                prefix: vec![script.to_string_lossy().into_owned()],
                script,
                engine_root,
                mode: "explicit",
            });
        }
    }

    let exe_name = if cfg!(windows) { "rigorloomd.exe" } else { "rigorloomd" };
    if let Some(dir) = resource_dir {
        for base in [
            dir.join("resources").join("rigorloomd"),
            dir.join("rigorloomd"),
        ] {
            let exe = base.join(exe_name);
            let script = base
                .join("_internal")
                .join("repo")
                .join("agenthost")
                .join("scripts")
                .join("host.py");
            if exe.is_file() && script.is_file() {
                return Ok(HostLaunch {
                    program: exe,
                    prefix: vec![script.to_string_lossy().into_owned()],
                    engine_root: base.join("_internal").join("repo"),
                    script,
                    mode: "packaged",
                });
            }
        }
    }

    let script = repo_root
        .join("agenthost")
        .join("scripts")
        .join("host.py");
    if script.is_file() {
        return Ok(HostLaunch {
            program: PathBuf::from(&python),
            prefix: vec![script.to_string_lossy().into_owned()],
            script,
            engine_root: repo_root.to_path_buf(),
            mode: "interpreter",
        });
    }
    Err("이 설치본에서 에이전트 호스트를 찾지 못했습니다.".into())
}

pub fn status(resource_dir: Option<&Path>, repo_root: &Path) -> Value {
    match resolve_host(resource_dir, repo_root) {
        Ok(launch) => json!({
            "available": true,
            "mode": launch.mode,
            "script": launch.script.to_string_lossy(),
            "program": launch.program.to_string_lossy(),
            "reason": Value::Null,
        }),
        Err(reason) => json!({
            "available": false,
            "mode": Value::Null,
            "script": Value::Null,
            "program": Value::Null,
            "reason": reason,
        }),
    }
}

// --- provider configuration ---------------------------------------------------

/// The env var name a stored credential is handed to the child under.
///
/// Fixed rather than derived from the store key: the config the host reads must
/// name a variable, and pinning it here means the config is identical whatever
/// the user called their store entry — one fewer place a name can drift.
pub const CHILD_CREDENTIAL_ENV: &str = "RIGORLOOM_PROVIDER_CREDENTIAL";

/// Members the webview may put in a provider config. Anything else is refused
/// here, before the file is written, so a secret cannot ride in under a name
/// the Agent Host would only catch at load time.
const ALLOWED_CONFIG_KEYS: &[&str] = &[
    "providerId",
    "baseUrl",
    "model",
    "capabilities",
    "maxTokens",
    "timeoutSeconds",
    "anthropicVersion",
];

/// Member names that must never appear, whatever they hold.
///
/// This is `ah_router.SECRET_SHAPED_KEYS` enforced one layer earlier. The Agent
/// Host would refuse them too; a boundary that relies on the far side catching
/// everything is not a boundary.
fn is_secret_shaped(name: &str) -> bool {
    let flat = name.to_ascii_lowercase().replace('_', "");
    matches!(
        flat.as_str(),
        "apikey"
            | "key"
            | "token"
            | "secret"
            | "password"
            | "authorization"
            | "bearer"
            | "credentialvalue"
            | "accesstoken"
            | "clientsecret"
    )
}

/// Build the config the Agent Host will read, from what the settings UI sent.
///
/// Returns the JSON document. `credential` is composed HERE, never accepted
/// from the webview: the webview says which store key to use, and this decides
/// that the host will find it as an environment reference.
fn compose_config(provider: &str, settings: &Value, has_credential: bool) -> Result<Value, String> {
    let mut config = serde_json::Map::new();
    let Some(fields) = settings.as_object() else {
        return Err("설정이 객체가 아닙니다.".into());
    };
    for (name, value) in fields {
        if is_secret_shaped(name) {
            return Err(format!(
                "설정 항목 '{name}' 은(는) 비밀값 이름입니다. 설정 파일에는 이름만 들어갑니다."
            ));
        }
        if !ALLOWED_CONFIG_KEYS.contains(&name.as_str()) {
            return Err(format!("설정에 모르는 항목이 있습니다: {name}"));
        }
        if value.is_null() {
            continue;
        }
        if let Some(text) = value.as_str() {
            if text.trim().is_empty() {
                continue;
            }
        }
        config.insert(name.clone(), value.clone());
    }
    if has_credential {
        // The header and scheme are NOT defaults to be left off.
        // `CredentialRef` falls back to `Authorization: Bearer <value>`, which
        // is right for an OpenAI-compatible router and WRONG for Anthropic —
        // the Messages API wants a bare `x-api-key`. Omitting them produced a
        // config that looked correct and would have authenticated against
        // nothing; `agent_roundtrip.py` is what caught it, by reading the
        // reference back out of the adapter instead of trusting the write.
        let (header, scheme) = if provider == "anthropic" {
            ("x-api-key", "raw")
        } else {
            ("Authorization", "bearer")
        };
        config.insert(
            "credential".into(),
            json!({
                "source": "env",
                "key": CHILD_CREDENTIAL_ENV,
                "header": header,
                "scheme": scheme,
            }),
        );
    } else if provider == "anthropic" {
        // The adapter's default is `ANTHROPIC_API_KEY`. Leaving it there when
        // the user has stored nothing is right: `--capabilities` then reports
        // the credential as missing, which is the honest state, and a machine
        // that really does have the variable set still works.
    }
    Ok(Value::Object(config))
}

/// Where a provider's config file lives. Under the app data dir, one per
/// provider, so switching providers does not lose the other's settings.
fn config_path(app_data: &Path, provider: &str) -> PathBuf {
    app_data.join("agenthost").join(format!("{provider}.json"))
}

/// Write the config, refusing anything secret-shaped first.
///
/// Returns the path AND the document, so the caller can assert (and the smoke
/// can read) that what landed on disk carries a reference and not a value.
pub fn write_config(
    app_data: &Path,
    provider: &str,
    settings: &Value,
    has_credential: bool,
) -> Result<(PathBuf, Value), String> {
    let document = compose_config(provider, settings, has_credential)?;
    let path = config_path(app_data, provider);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_string_pretty(&document).map_err(|e| e.to_string())?;
    std::fs::write(&path, body).map_err(|e| e.to_string())?;
    Ok((path, document))
}

/// `mock` takes no config at all; `router` requires one; `anthropic`'s is
/// optional. Reflected here so the caller does not pass `--config` where the
/// CLI would reject it.
fn config_for(provider: &str, path: &Path) -> Option<PathBuf> {
    if provider == "mock" {
        return None;
    }
    path.is_file().then(|| path.to_path_buf())
}

// --- running ------------------------------------------------------------------

/// One in-flight run, so a second send cannot start on top of the first and so
/// the UI can stop one that is taking too long.
#[derive(Default)]
pub struct RunSlot {
    pub child: Mutex<Option<std::process::Child>>,
    pub busy: AtomicBool,
}

fn base_command(launch: &HostLaunch) -> Command {
    let mut command = Command::new(&launch.program);
    for arg in &launch.prefix {
        command.arg(arg);
    }
    command
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
    }
    command
}

/// Attach the stored credential to THIS command's environment, and nowhere
/// else. Returns whether one was attached, never the value.
fn attach_credential(command: &mut Command, store_key: Option<&str>) -> Result<bool, String> {
    let Some(key) = store_key.filter(|k| !k.is_empty()) else {
        return Ok(false);
    };
    let secret = credstore::get(key)?;
    command.env(CHILD_CREDENTIAL_ENV, secret);
    Ok(true)
}

/// `--capabilities`: what the provider says it can do, without a document and
/// without needing a key.
///
/// The credential IS attached when one is stored, because the payload's
/// `notes.credential.state` then reports `present` rather than `missing` — the
/// difference between "you have not set this up" and "you have", which is the
/// whole reason a 연결 확인 button is worth pressing. Nothing is sent over the
/// network either way: this is a local describe.
pub fn capabilities(
    launch: &HostLaunch,
    app_data: &Path,
    provider: &str,
    store_key: Option<&str>,
) -> Result<Value, String> {
    let mut command = base_command(launch);
    command.arg("--capabilities").arg("--provider").arg(provider);
    if let Some(path) = config_for(provider, &config_path(app_data, provider)) {
        command.arg("--config").arg(path);
    }
    let credential = attach_credential(&mut command, store_key).unwrap_or(false);

    let output = command
        .output()
        .map_err(|e| format!("에이전트 호스트를 시작하지 못했습니다: {e}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).into_owned();
    let payload: Value = serde_json::from_str(stdout.trim()).unwrap_or_else(|_| {
        json!({
            "ok": false,
            "error": {
                "code": "host_output_unreadable",
                "message": "에이전트 호스트가 JSON을 내놓지 않았습니다.",
            },
        })
    });
    Ok(json!({
        "exitCode": output.status.code().unwrap_or(-1),
        "payload": payload,
        "credentialAttached": credential,
        "stderr": tail(&String::from_utf8_lossy(&output.stderr), 1200),
    }))
}

fn tail(text: &str, max: usize) -> String {
    if text.len() <= max {
        return text.to_string();
    }
    text[text.len() - max..].to_string()
}

/// Run one turn: spawn, tail the event file live, wait, return the payload.
#[allow(clippy::too_many_arguments)]
pub fn run_turn(
    app: &AppHandle,
    slot: &RunSlot,
    launch: &HostLaunch,
    app_data: &Path,
    root: &Path,
    session_id: &str,
    provider: &str,
    instruction: &str,
    store_key: Option<&str>,
    scenario: Option<&str>,
    turn_id: &str,
) -> Result<Value, Value> {
    let fail = |code: &str, message: String, data: Value| {
        json!({ "code": code, "message": message, "data": data })
    };

    if slot.busy.swap(true, Ordering::SeqCst) {
        return Err(fail(
            "agent_busy",
            "에이전트가 아직 앞의 지시를 처리하고 있습니다.".into(),
            Value::Null,
        ));
    }
    // From here on every exit must clear the flag.
    let guard = BusyGuard(slot);

    let events_path = app_data
        .join("agenthost")
        .join("runs")
        .join(format!("{turn_id}.jsonl"));
    if let Some(parent) = events_path.parent() {
        let _ = std::fs::create_dir_all(parent);
    }
    let _ = std::fs::write(&events_path, b"");

    let mut command = base_command(launch);
    command
        .arg("--root")
        .arg(root)
        .arg("--session")
        .arg(session_id)
        .arg("--provider")
        .arg(provider)
        .arg("--door")
        .arg("protocol")
        .arg("--engine-root")
        .arg(&launch.engine_root)
        .arg("--instruction")
        .arg(instruction)
        .arg("--events")
        .arg(&events_path);
    if provider == "mock" {
        command.arg("--scenario").arg(scenario.unwrap_or("propose-one"));
    }
    if let Some(path) = config_for(provider, &config_path(app_data, provider)) {
        command.arg("--config").arg(path);
    }
    let credential = match attach_credential(&mut command, store_key) {
        Ok(value) => value,
        Err(message) => {
            drop(guard);
            return Err(fail(
                "credential_unavailable",
                message,
                json!({ "storeKey": store_key }),
            ));
        }
    };

    let mut child = match command.spawn() {
        Ok(child) => child,
        Err(e) => {
            drop(guard);
            return Err(fail(
                "agent_spawn_failed",
                format!("에이전트 호스트를 시작하지 못했습니다: {e}"),
                json!({ "program": launch.program.to_string_lossy() }),
            ));
        }
    };
    let pid = child.id();
    let mut stdout = child.stdout.take();
    let mut stderr = child.stderr.take();
    *slot.child.lock().unwrap() = Some(child);

    // The tail thread. It stops when the run is done, not when the file stops
    // growing: a provider that thinks for thirty seconds writes nothing in
    // between, and giving up on quiet would truncate the log.
    let done = Arc::new(AtomicBool::new(false));
    let tailer = spawn_tail(app.clone(), events_path.clone(), turn_id.to_string(), done.clone());

    // Drain both pipes on their own threads. A child that fills a 4 KiB pipe
    // buffer while nobody reads it blocks forever, and `wait()` then waits
    // forever with it.
    let out_handle = std::thread::spawn(move || read_all(&mut stdout));
    let err_handle = std::thread::spawn(move || read_all(&mut stderr));

    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(RUN_TIMEOUT_SECS);
    let status = loop {
        let mut held = slot.child.lock().unwrap();
        let Some(child) = held.as_mut() else {
            break None;
        };
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) => {}
            Err(_) => break None,
        }
        if std::time::Instant::now() > deadline {
            let _ = child.kill();
            let _ = child.wait();
            break None;
        }
        drop(held);
        std::thread::sleep(std::time::Duration::from_millis(80));
    };
    *slot.child.lock().unwrap() = None;

    done.store(true, Ordering::SeqCst);
    let _ = tailer.join();
    let stdout_text = out_handle.join().unwrap_or_default();
    let stderr_text = err_handle.join().unwrap_or_default();
    drop(guard);

    let exit_code = status.and_then(|s| s.code()).unwrap_or(-1);
    let payload: Value = match serde_json::from_str(stdout_text.trim()) {
        Ok(value) => value,
        Err(_) => {
            return Err(fail(
                "host_output_unreadable",
                "에이전트 호스트가 JSON을 내놓지 않았습니다.".into(),
                json!({
                    "exitCode": exit_code,
                    "stderr": tail(&stderr_text, 1600),
                    "pid": pid,
                }),
            ))
        }
    };
    Ok(json!({
        "exitCode": exit_code,
        "payload": payload,
        "credentialAttached": credential,
        "eventsPath": events_path.to_string_lossy(),
        "stderr": tail(&stderr_text, 1600),
        "turnId": turn_id,
    }))
}

/// Kill the run in flight, if there is one. The Agent Host holds no document
/// lock and writes nothing to the workspace itself — every mutation goes
/// through the Runtime's agent door, which refuses apply — so stopping it can
/// never leave a half-written document.
pub fn stop(slot: &RunSlot) -> bool {
    let mut held = slot.child.lock().unwrap();
    match held.as_mut() {
        Some(child) => {
            let killed = child.kill().is_ok();
            let _ = child.wait();
            *held = None;
            killed
        }
        None => false,
    }
}

struct BusyGuard<'a>(&'a RunSlot);

impl Drop for BusyGuard<'_> {
    fn drop(&mut self) {
        self.0.busy.store(false, Ordering::SeqCst);
    }
}

fn read_all<R: Read>(source: &mut Option<R>) -> String {
    let Some(reader) = source.as_mut() else {
        return String::new();
    };
    let mut buffer = Vec::new();
    let _ = reader.read_to_end(&mut buffer);
    String::from_utf8_lossy(&buffer).into_owned()
}

/// Poll the JSONL mirror and emit whole lines, batched.
///
/// Only COMPLETE lines are emitted. `EventLog.append` writes one line per
/// `open`/`write`/`close`, so a trailing fragment means the writer is mid-line
/// rather than that a line is malformed, and holding it until the newline
/// arrives is the difference between a live log and a corrupted one.
fn spawn_tail(
    app: AppHandle,
    path: PathBuf,
    turn_id: String,
    done: Arc<AtomicBool>,
) -> std::thread::JoinHandle<()> {
    std::thread::spawn(move || {
        let mut offset: u64 = 0;
        let mut partial = String::new();
        loop {
            let finished = done.load(Ordering::SeqCst);
            let mut batch: Vec<Value> = Vec::new();
            if let Ok(bytes) = read_from(&path, offset) {
                offset += bytes.len() as u64;
                partial.push_str(&String::from_utf8_lossy(&bytes));
                while let Some(index) = partial.find('\n') {
                    let line: String = partial.drain(..=index).collect();
                    let line = line.trim();
                    if line.is_empty() {
                        continue;
                    }
                    if let Ok(event) = serde_json::from_str::<Value>(line) {
                        batch.push(json!({ "turnId": turn_id, "event": event }));
                    }
                }
            }
            if !batch.is_empty() {
                let _ = app.emit(EVENT_AGENT, batch);
            }
            if finished {
                // One last pass happened above with `finished` already true, so
                // nothing written before the exit can be missed.
                return;
            }
            std::thread::sleep(std::time::Duration::from_millis(FLUSH_MS));
        }
    })
}

fn read_from(path: &Path, offset: u64) -> std::io::Result<Vec<u8>> {
    use std::io::{Seek, SeekFrom};
    let mut file = std::fs::File::open(path)?;
    let len = file.metadata()?.len();
    if len <= offset {
        return Ok(Vec::new());
    }
    file.seek(SeekFrom::Start(offset))?;
    let mut buffer = Vec::with_capacity((len - offset) as usize);
    file.read_to_end(&mut buffer)?;
    Ok(buffer)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_secret_shaped_member_is_refused_by_name() {
        for name in ["apiKey", "api_key", "token", "SECRET", "authorization"] {
            let settings = json!({ name: "anything" });
            let error = compose_config("router", &settings, false).unwrap_err();
            assert!(error.contains(name), "{error}");
        }
    }

    #[test]
    fn the_config_carries_a_reference_and_never_a_value() {
        let settings = json!({ "baseUrl": "https://gateway.example.invalid/v1",
                               "model": "some-model" });
        let document = compose_config("router", &settings, true).unwrap();
        assert_eq!(document["credential"]["source"], "env");
        assert_eq!(document["credential"]["key"], CHILD_CREDENTIAL_ENV);
        let text = document.to_string();
        assert!(!text.contains("sk-"));
        assert!(!text.to_lowercase().contains("apikey"));
    }

    #[test]
    fn each_provider_gets_the_header_its_api_actually_wants() {
        let anthropic = compose_config("anthropic", &json!({}), true).unwrap();
        assert_eq!(anthropic["credential"]["header"], "x-api-key");
        assert_eq!(anthropic["credential"]["scheme"], "raw");
        let router = compose_config("router", &json!({}), true).unwrap();
        assert_eq!(router["credential"]["header"], "Authorization");
        assert_eq!(router["credential"]["scheme"], "bearer");
    }

    #[test]
    fn an_unknown_member_is_refused_before_the_file_is_written() {
        let settings = json!({ "somethingElse": 1 });
        assert!(compose_config("router", &settings, false)
            .unwrap_err()
            .contains("somethingElse"));
    }

    #[test]
    fn no_credential_means_no_credential_member() {
        let document = compose_config("anthropic", &json!({ "model": "m" }), false).unwrap();
        assert!(document.get("credential").is_none());
    }
}
