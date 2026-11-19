//! The developer-setting gate for the bundled test agent, shared by every
//! native launch command.
//!
//! The browser bridge (`runtime/scripts/rt_ui.py`, `mock_agent_allowed`) runs
//! the test agent only when `RIGORLOOM_DEV_MOCK_AGENT` is on or the
//! `devMockAgent` preference is `true`. The native shell applies the SAME rule
//! before it spawns `mock_agent.py` or an agent-host turn with the mock
//! provider, so neither host can launch test values with the setting off.
//!
//! Pure on purpose: no Tauri types, so `rustc --test src/devgate.rs` checks it
//! without building the app.

/// The environment variable the browser bridge reads (`DEV_MOCK_AGENT_ENV`).
pub const DEV_MOCK_AGENT_ENV: &str = "RIGORLOOM_DEV_MOCK_AGENT";

/// The preference key the browser bridge reads (`DEV_MOCK_AGENT_PREF`).
pub const DEV_MOCK_AGENT_PREF: &str = "devMockAgent";

/// `env` is the raw value of `RIGORLOOM_DEV_MOCK_AGENT`, `pref` the
/// `devMockAgent` preference when it is a boolean.
pub fn mock_agent_allowed(env: Option<&str>, pref: Option<bool>) -> bool {
    if let Some(raw) = env {
        let value = raw.trim().to_ascii_lowercase();
        if matches!(value.as_str(), "1" | "true" | "yes" | "on") {
            return true;
        }
    }
    pref == Some(true)
}

/// Whether a launch with this provider needs the developer setting.
pub fn provider_needs_dev_setting(provider: &str) -> bool {
    provider == "mock"
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn off_by_default() {
        assert!(!mock_agent_allowed(None, None));
        assert!(!mock_agent_allowed(Some(""), Some(false)));
        assert!(!mock_agent_allowed(Some("0"), None));
        assert!(!mock_agent_allowed(Some("off"), Some(false)));
    }

    #[test]
    fn env_or_pref_turns_it_on() {
        for raw in ["1", "true", "YES", " on "] {
            assert!(mock_agent_allowed(Some(raw), None), "{raw}");
        }
        assert!(mock_agent_allowed(None, Some(true)));
    }

    #[test]
    fn only_the_mock_provider_is_gated() {
        assert!(provider_needs_dev_setting("mock"));
        assert!(!provider_needs_dev_setting("anthropic"));
        assert!(!provider_needs_dev_setting("router"));
    }
}
