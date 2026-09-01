//! 작업 팩 — the distribution modules this installation actually declares.
//!
//! WHY A CHILD PROCESS AND NOT A PARSER HERE. `modules/<name>/module.yaml` is a
//! strict pure-literal YAML subset with its own validator, version gate and
//! inter-module dependency gate (`pipeline/scripts/module_registry.py`), and
//! that script already prints the whole thing as JSON on `list`. Writing a
//! second reader in Rust would mean two definitions of what a module is, and
//! the Rust one would be the wrong one the first time a manifest used a shape
//! it did not anticipate. So this asks the registry.
//!
//! It runs through the same dual-role entry the Runtime's own children use:
//! `rigorloomd.exe <script.py> …` behaves exactly like `python script.py …`
//! (`sidecar/rigorloomd.py`, job 2), so a packaged installation needs no
//! interpreter on the machine and a dev checkout needs no bundle.
//!
//! WHAT IS AND IS NOT CLAIMED. This lists what is DECLARED — the module's name,
//! whether it is enabled, what checkers and CLI commands it contributes, and
//! what it depends on. It does not run any of them, and the Runtime protocol
//! has no method that does: the pack detail panel says 준비 중 and names the
//! real contributions rather than drawing a workflow that does not exist.

use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};

use serde_json::{json, Value};

struct RegistryLaunch {
    program: PathBuf,
    script: PathBuf,
    modules_root: PathBuf,
    pyproject: PathBuf,
    mode: &'static str,
}

fn resolve(resource_dir: Option<&Path>, repo_root: &Path) -> Result<RegistryLaunch, String> {
    let exe_name = if cfg!(windows) { "rigorloomd.exe" } else { "rigorloomd" };
    // An explicit modules root wins wherever it is set, which is how the
    // scripted evidence points a PACKAGED build at the repo's declarations.
    let override_root = std::env::var_os("RIGORLOOM_MODULES_ROOT").map(PathBuf::from);

    if let Some(dir) = resource_dir {
        for base in [
            dir.join("resources").join("rigorloomd"),
            dir.join("rigorloomd"),
        ] {
            let exe = base.join(exe_name);
            let repo = base.join("_internal").join("repo");
            let script = repo.join("pipeline").join("scripts").join("module_registry.py");
            if exe.is_file() && script.is_file() {
                return Ok(RegistryLaunch {
                    program: exe,
                    script,
                    modules_root: override_root
                        .clone()
                        .unwrap_or_else(|| repo.join("modules")),
                    pyproject: repo.join("pyproject.toml"),
                    mode: "packaged",
                });
            }
        }
    }

    let script = repo_root
        .join("pipeline")
        .join("scripts")
        .join("module_registry.py");
    if !script.is_file() {
        return Err("이 설치본에는 작업 팩 선언을 읽을 등록기가 없습니다.".into());
    }
    let python = std::env::var("RIGORLOOM_PYTHON").unwrap_or_else(|_| "python".into());
    Ok(RegistryLaunch {
        program: PathBuf::from(python),
        script,
        modules_root: override_root.unwrap_or_else(|| repo_root.join("modules")),
        pyproject: repo_root.join("pyproject.toml"),
        mode: "interpreter",
    })
}

/// Korean product names and one honest line each.
///
/// Held here rather than in the manifests because the manifests are the
/// program's own contract with its modules and do not carry UI copy — adding a
/// `displayName` to them would be editing a tree this slice does not own. The
/// consequence is stated where it matters: a module with no entry here shows
/// its declared name verbatim rather than a made-up Korean one.
fn describe(name: &str) -> Option<(&'static str, &'static str)> {
    Some(match name {
        "report" => (
            "탐구·보고서",
            "긴 보고서를 단계로 나눠 쓰고, 단계마다 검사를 걸어 두는 팩입니다.",
        ),
        "gongmun" => (
            "공문",
            "기관 공문 서식의 항목과 말투를 검사하는 팩입니다.",
        ),
        "grant" => (
            "사업계획·지원서",
            "지원 사업 양식의 분량·항목 누락을 검사하는 팩입니다.",
        ),
        "hr" => (
            "인사 문서",
            "인사 관련 서식의 항목과 표기를 검사하는 팩입니다.",
        ),
        "minwon" => (
            "민원 회신",
            "민원 답변문의 구조와 어투를 검사하는 팩입니다.",
        ),
        "style" => (
            "문체",
            "번역투와 AI 티를 걷어내는 문체 검사·윤문 팩입니다. 보고서 팩이 이 팩을 씁니다.",
        ),
        _ => return None,
    })
}

/// Reshape the registry's JSON into what the left rail draws.
///
/// Every field below comes from the registry's own output. Nothing is invented
/// except the Korean display name, and a module without one keeps its declared
/// name so the absence is visible rather than papered over.
fn shape(summary: &Value) -> Value {
    let discovered = summary["discovered"].as_array().cloned().unwrap_or_default();
    let enabled: Vec<String> = summary["enabled"]
        .as_array()
        .map(|rows| {
            rows.iter()
                .filter_map(|v| v.as_str().map(str::to_string))
                .collect()
        })
        .unwrap_or_default();

    let collect = |member: &str, id_key: &str| -> std::collections::HashMap<String, Vec<Value>> {
        let mut out: std::collections::HashMap<String, Vec<Value>> = Default::default();
        if let Some(rows) = summary[member].as_array() {
            for row in rows {
                let Some(module) = row["module"].as_str() else { continue };
                out.entry(module.to_string()).or_default().push(json!({
                    "name": row[id_key],
                    "script": row["script"],
                }));
            }
        }
        out
    };
    let checkers = collect("checkers", "name");
    let cli = collect("cli", "command");

    let packs: Vec<Value> = discovered
        .iter()
        .filter_map(|v| v.as_str())
        .map(|name| {
            let (title, blurb) = describe(name).unwrap_or((name, ""));
            json!({
                "name": name,
                "title": title,
                "blurb": blurb,
                "named": describe(name).is_some(),
                "enabled": enabled.iter().any(|e| e == name),
                "requiresModules": summary["requires_modules"][name],
                "checkers": checkers.get(name).cloned().unwrap_or_default(),
                "cli": cli.get(name).cloned().unwrap_or_default(),
            })
        })
        .collect();

    json!({
        "available": true,
        "schema": summary["schema"],
        "version": summary["version"],
        "modulesRoot": summary["modules_root"],
        "packs": packs,
        "reason": Value::Null,
    })
}

pub fn list(resource_dir: Option<&Path>, repo_root: &Path) -> Value {
    let launch = match resolve(resource_dir, repo_root) {
        Ok(launch) => launch,
        Err(reason) => {
            return json!({ "available": false, "packs": [], "reason": reason, "mode": Value::Null })
        }
    };
    if !launch.modules_root.is_dir() {
        return json!({
            "available": false,
            "packs": [],
            "mode": launch.mode,
            "reason": format!(
                "이 설치본에는 작업 팩 선언이 들어 있지 않습니다 ({}).",
                launch.modules_root.display()
            ),
        });
    }

    let mut command = Command::new(&launch.program);
    command
        .arg(&launch.script)
        .arg("--modules-root")
        .arg(&launch.modules_root)
        .arg("--pyproject")
        .arg(&launch.pyproject)
        .arg("list")
        .env("PYTHONIOENCODING", "utf-8")
        .env("PYTHONUTF8", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        command.creation_flags(0x0800_0000);
    }

    let output = match command.output() {
        Ok(output) => output,
        Err(e) => {
            return json!({
                "available": false, "packs": [], "mode": launch.mode,
                "reason": format!("작업 팩 등록기를 실행하지 못했습니다: {e}"),
            })
        }
    };
    let stdout = String::from_utf8_lossy(&output.stdout);
    let summary: Value = match serde_json::from_str(stdout.trim()) {
        Ok(value) => value,
        Err(_) => {
            return json!({
                "available": false, "packs": [], "mode": launch.mode,
                "reason": "작업 팩 등록기가 JSON을 내놓지 않았습니다.",
                "stderr": String::from_utf8_lossy(&output.stderr).chars().rev().take(600)
                    .collect::<String>().chars().rev().collect::<String>(),
            })
        }
    };
    if summary["ok"] != json!(true) {
        return json!({
            "available": false, "packs": [], "mode": launch.mode,
            "reason": summary["error"].as_str().unwrap_or("작업 팩 선언이 올바르지 않습니다."),
        });
    }
    let mut shaped = shape(&summary);
    shaped["mode"] = json!(launch.mode);
    shaped
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_shape_carries_the_registrys_own_facts() {
        let summary = json!({
            "schema": "rigorloom-module-registry/v1",
            "version": "0.17.0",
            "modules_root": "/x/modules",
            "discovered": ["report", "style", "unheardof"],
            "enabled": ["report", "style"],
            "requires_modules": { "report": ["style"], "style": [], "unheardof": [] },
            "checkers": [
                { "name": "check_style", "script": "/x/s.py", "module": "style" },
                { "name": "check_refs", "script": "/x/r.py", "module": "report" }
            ],
            "cli": [{ "command": "humanize", "script": "/x/h.py", "module": "style" }]
        });
        let shaped = shape(&summary);
        let packs = shaped["packs"].as_array().unwrap();
        assert_eq!(packs.len(), 3);
        assert_eq!(packs[0]["name"], "report");
        assert_eq!(packs[0]["title"], "탐구·보고서");
        assert_eq!(packs[0]["enabled"], true);
        assert_eq!(packs[0]["requiresModules"][0], "style");
        assert_eq!(packs[0]["checkers"][0]["name"], "check_refs");
        assert_eq!(packs[1]["cli"][0]["name"], "humanize");
        // A module nobody wrote copy for keeps its declared name and says so,
        // rather than being dropped or given an invented one.
        assert_eq!(packs[2]["name"], "unheardof");
        assert_eq!(packs[2]["title"], "unheardof");
        assert_eq!(packs[2]["named"], false);
    }
}
