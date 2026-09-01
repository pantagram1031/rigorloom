//! What the shell remembers between launches.
//!
//! Objective 5: close and reopen the workspace without a terminal. Runtime
//! sessions already persist on disk under `--root` (the Runtime keys sessions,
//! plans and approvals there — `docs/runtime-protocol-v0.md` §9 correction 3),
//! so the shell only has to remember *which* root and *which* session, then
//! reattach by calling `session/list`.
//!
//! Deliberately a plain JSON file and not a settings framework: three keys, and
//! a corrupt or missing file must degrade to defaults rather than block launch.

use std::path::PathBuf;

use serde_json::{json, Value};
use tauri::{AppHandle, Manager};

const FILE: &str = "desktop-prefs.json";

fn path(app: &AppHandle) -> PathBuf {
    app.path()
        .app_local_data_dir()
        .unwrap_or_else(|_| std::env::temp_dir().join("rigorloom"))
        .join(FILE)
}

pub fn load(app: &AppHandle) -> Value {
    let file = path(app);
    let Ok(text) = std::fs::read_to_string(&file) else {
        return json!({});
    };
    // Absence is not failure, and neither is corruption: a prefs file that
    // cannot be parsed must not stop the app from opening.
    serde_json::from_str::<Value>(&text)
        .ok()
        .filter(Value::is_object)
        .unwrap_or_else(|| json!({}))
}

pub fn merge(app: &AppHandle, patch: Value) -> Result<Value, String> {
    let mut current = load(app);
    let Some(target) = current.as_object_mut() else {
        return Err("prefs 파일이 객체가 아닙니다".into());
    };
    if let Some(fields) = patch.as_object() {
        for (key, value) in fields {
            if value.is_null() {
                target.remove(key);
            } else {
                target.insert(key.clone(), value.clone());
            }
        }
    }
    let file = path(app);
    if let Some(parent) = file.parent() {
        std::fs::create_dir_all(parent).map_err(|e| e.to_string())?;
    }
    let body = serde_json::to_string_pretty(&current).map_err(|e| e.to_string())?;
    std::fs::write(&file, body).map_err(|e| e.to_string())?;
    Ok(current)
}

pub fn save_root(app: &AppHandle, root: &std::path::Path) -> Result<Value, String> {
    merge(app, json!({ "root": root.to_string_lossy() }))
}
