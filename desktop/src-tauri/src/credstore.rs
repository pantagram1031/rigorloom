//! The OS credential store, and the only place in this program a secret rests.
//!
//! WHY THIS EXISTS AT ALL. The Agent Host takes a credential *reference* — the
//! name of an environment variable or an OS store key — and refuses a config
//! that carries a value (`ah_router._reject_secret_shaped`, by member name,
//! whatever the value looks like). That contract is only worth something if the
//! desktop has somewhere real to put the secret. Without one, the honest
//! options were "ask the user to set an environment variable in a terminal",
//! which is not a product, or "write it to a JSON file", which is the thing the
//! contract exists to prevent.
//!
//! WHY NOT A CRATE. `keyring` pulls a tree (windows-sys, byteorder, and on
//! other platforms secret-service and its DBus stack) to wrap four calls this
//! file makes directly. `windows-sys` is ALREADY a dependency of this crate for
//! `jobkill.rs`; this adds one feature flag to it and no new crate. Same
//! reasoning as `digest.rs`: a dependency for sixty lines is not one.
//!
//! WHAT THIS FILE PROMISES.
//!
//! - a secret arrives once, from the webview, on its way in — and is never
//!   returned to the webview afterwards. `status` answers present/absent and a
//!   byte count, never the value;
//! - a secret is never written to a settings file, an event, a log line, a
//!   process argument or an error message. The one place it goes after the
//!   store is the ENVIRONMENT OF THE CHILD the Agent Host runs in, set on that
//!   `Command` alone (`agenthost.rs`), which is what makes the reference the
//!   host resolves (`credential.source == "env"`) point at something;
//! - every error string here names the Win32 error code and the target, and
//!   never the blob.
//!
//! WINDOWS ONLY, and it says so rather than pretending. On any other platform
//! every function returns `credential_store_unavailable`, which is a state the
//! UI draws — not a silent success that loses the key.

/// The namespace every target name gets. A generic credential's target is a
/// flat global string; without a prefix, "ANTHROPIC_API_KEY" would collide with
/// whatever else on the machine picked the same obvious name.
const PREFIX: &str = "rigorloom-desktop:";

/// Windows caps a generic credential blob at 5 × 512 bytes. Refuse above it
/// here, with the limit named, rather than letting `CredWriteW` fail with a
/// bare error code.
const MAX_BLOB: usize = 2560;

/// What a store key may be spelled with.
///
/// The key travels into a JSON config and, for the env-reference handoff, into
/// an environment variable NAME. Restricting it to the shape of an environment
/// variable means neither of those can be injected into.
pub fn valid_key(key: &str) -> bool {
    !key.is_empty()
        && key.len() <= 128
        && key
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '_' || c == '-' || c == '.')
}

fn target(key: &str) -> String {
    format!("{PREFIX}{key}")
}

#[cfg(windows)]
fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn last_error() -> u32 {
    unsafe { windows_sys::Win32::Foundation::GetLastError() }
}

/// Write (or replace) the secret stored under `key`.
///
/// The blob is the secret's UTF-8 bytes. Windows treats the blob as opaque and
/// this program is its only reader, so no encoding convention is inherited; the
/// choice is written down here because a future reader with `cmdkey` in hand
/// will want to know.
#[cfg(windows)]
pub fn set(key: &str, secret: &str) -> Result<usize, String> {
    use windows_sys::Win32::Security::Credentials::{
        CredWriteW, CREDENTIALW, CRED_PERSIST_LOCAL_MACHINE, CRED_TYPE_GENERIC,
    };

    if !valid_key(key) {
        return Err("자격 증명 이름은 영문·숫자·_-. 로만 쓸 수 있습니다.".into());
    }
    if secret.is_empty() {
        return Err("빈 값은 저장하지 않습니다.".into());
    }
    let bytes = secret.as_bytes();
    if bytes.len() > MAX_BLOB {
        return Err(format!(
            "자격 증명이 너무 깁니다: {} 바이트 (한도 {MAX_BLOB})",
            bytes.len()
        ));
    }

    let mut target_wide = wide(&target(key));
    let mut user_wide = wide("rigorloom");
    let mut comment_wide = wide("Rigorloom Desktop provider credential");
    let mut blob = bytes.to_vec();

    let credential = CREDENTIALW {
        Flags: 0,
        Type: CRED_TYPE_GENERIC,
        TargetName: target_wide.as_mut_ptr(),
        Comment: comment_wide.as_mut_ptr(),
        LastWritten: unsafe { std::mem::zeroed() },
        CredentialBlobSize: blob.len() as u32,
        CredentialBlob: blob.as_mut_ptr(),
        Persist: CRED_PERSIST_LOCAL_MACHINE,
        AttributeCount: 0,
        Attributes: std::ptr::null_mut(),
        TargetAlias: std::ptr::null_mut(),
        UserName: user_wide.as_mut_ptr(),
    };
    let ok = unsafe { CredWriteW(&credential, 0) };
    if ok == 0 {
        return Err(format!(
            "Windows 자격 증명 관리자에 쓰지 못했습니다 (오류 {})",
            last_error()
        ));
    }
    Ok(bytes.len())
}

/// Read the secret back. **Never crosses IPC** — only `agenthost.rs` calls it,
/// and only to put the value in one child process's environment.
#[cfg(windows)]
pub fn get(key: &str) -> Result<String, String> {
    use windows_sys::Win32::Security::Credentials::{
        CredFree, CredReadW, CREDENTIALW, CRED_TYPE_GENERIC,
    };

    if !valid_key(key) {
        return Err("자격 증명 이름이 올바르지 않습니다.".into());
    }
    let target_wide = wide(&target(key));
    let mut out: *mut CREDENTIALW = std::ptr::null_mut();
    let ok = unsafe { CredReadW(target_wide.as_ptr(), CRED_TYPE_GENERIC, 0, &mut out) };
    if ok == 0 || out.is_null() {
        return Err(format!(
            "이 기계의 자격 증명 저장소에 '{key}' 항목이 없습니다 (오류 {})",
            last_error()
        ));
    }
    // SAFETY: CredReadW succeeded, so `out` points at a CREDENTIALW Windows
    // allocated and we own until CredFree.
    let secret = unsafe {
        let cred = &*out;
        let len = cred.CredentialBlobSize as usize;
        let value = if len == 0 || cred.CredentialBlob.is_null() {
            String::new()
        } else {
            let slice = std::slice::from_raw_parts(cred.CredentialBlob, len);
            String::from_utf8_lossy(slice).into_owned()
        };
        CredFree(out as *const _);
        value
    };
    if secret.is_empty() {
        return Err(format!("'{key}' 항목이 비어 있습니다."));
    }
    Ok(secret)
}

#[cfg(windows)]
pub fn delete(key: &str) -> Result<bool, String> {
    use windows_sys::Win32::Security::Credentials::{CredDeleteW, CRED_TYPE_GENERIC};

    if !valid_key(key) {
        return Err("자격 증명 이름이 올바르지 않습니다.".into());
    }
    let target_wide = wide(&target(key));
    let ok = unsafe { CredDeleteW(target_wide.as_ptr(), CRED_TYPE_GENERIC, 0) };
    Ok(ok != 0)
}

// --- everywhere else ---------------------------------------------------------
// Not a stub that succeeds. A key the app claimed to have saved and did not
// would be worse than an honest refusal.

#[cfg(not(windows))]
pub fn set(_key: &str, _secret: &str) -> Result<usize, String> {
    Err("이 운영체제에는 아직 자격 증명 저장소를 붙이지 않았습니다.".into())
}

#[cfg(not(windows))]
pub fn get(_key: &str) -> Result<String, String> {
    Err("이 운영체제에는 아직 자격 증명 저장소를 붙이지 않았습니다.".into())
}

#[cfg(not(windows))]
pub fn delete(_key: &str) -> Result<bool, String> {
    Err("이 운영체제에는 아직 자격 증명 저장소를 붙이지 않았습니다.".into())
}

/// Present / absent, and how many bytes — never the value.
///
/// The byte count is deliberate: it is enough for a person to tell "I pasted
/// the whole key" from "I pasted half of it", and not enough to be a leak.
pub fn status(key: &str) -> serde_json::Value {
    if !valid_key(key) {
        return serde_json::json!({
            "key": key, "state": "invalid",
            "reason": "자격 증명 이름은 영문·숫자·_-. 로만 쓸 수 있습니다.",
        });
    }
    match get(key) {
        Ok(secret) => serde_json::json!({
            "key": key, "state": "present", "bytes": secret.len(), "reason": null,
        }),
        Err(reason) => serde_json::json!({
            "key": key, "state": "absent", "bytes": 0, "reason": reason,
        }),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn key_shape_is_environment_variable_shaped() {
        assert!(valid_key("RIGORLOOM_ANTHROPIC"));
        assert!(valid_key("my-router.key"));
        assert!(!valid_key(""));
        // The two that matter: a key becomes an env var name and a JSON member.
        assert!(!valid_key("has space"));
        assert!(!valid_key("has\"quote"));
        assert!(!valid_key("has=equals"));
        assert!(!valid_key(&"x".repeat(129)));
    }

    #[cfg(windows)]
    #[test]
    fn a_secret_round_trips_and_status_never_shows_it() {
        let key = "RIGORLOOM_TEST_CREDSTORE";
        let secret = "not-a-real-key-0123456789";
        let _ = delete(key);
        assert_eq!(set(key, secret).unwrap(), secret.len());
        assert_eq!(get(key).unwrap(), secret);
        let reported = status(key);
        assert_eq!(reported["state"], "present");
        assert_eq!(reported["bytes"], secret.len());
        // The load-bearing line: what crosses IPC never carries the value.
        assert!(!reported.to_string().contains(secret));
        assert!(delete(key).unwrap());
        assert_eq!(status(key)["state"], "absent");
    }
}
