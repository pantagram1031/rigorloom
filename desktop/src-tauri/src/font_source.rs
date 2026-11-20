const FONT_SOURCE: &str = include_str!("../../src/model/hancomFontSource.json");

#[tauri::command]
pub async fn open_hancom_font_source() -> Result<(), String> {
    let url: &str = serde_json::from_str(FONT_SOURCE).map_err(|err| err.to_string())?;
    let parsed = tauri::Url::parse(url).map_err(|err| err.to_string())?;
    if parsed.scheme() != "https"
        || parsed.host_str() != Some("www.hancom.com")
        || parsed.port().is_some()
        || !parsed.username().is_empty()
        || parsed.password().is_some()
    {
        return Err("Unexpected font distribution host".into());
    }
    tauri::async_runtime::spawn_blocking(move || open_in_browser(url))
        .await
        .map_err(|err| err.to_string())?
}

#[cfg(windows)]
fn open_in_browser(url: &str) -> Result<(), String> {
    use std::ptr::{null, null_mut};
    use windows_sys::Win32::UI::{Shell::ShellExecuteW, WindowsAndMessaging::SW_SHOWNORMAL};

    let url: Vec<u16> = url.encode_utf16().chain([0]).collect();
    let result = unsafe {
        ShellExecuteW(
            null_mut(),
            null(),
            url.as_ptr(),
            null(),
            null(),
            SW_SHOWNORMAL,
        )
    };
    if result as usize <= 32 {
        return Err("Could not open the default browser".into());
    }
    Ok(())
}

#[cfg(not(windows))]
fn open_in_browser(url: &str) -> Result<(), String> {
    use std::process::{Command, Stdio};

    #[cfg(target_os = "macos")]
    let opener = "open";
    #[cfg(not(target_os = "macos"))]
    let opener = "xdg-open";

    let status = Command::new(opener)
        .arg(url)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map_err(|err| err.to_string())?;
    if !status.success() {
        return Err("Could not open the default browser".into());
    }
    Ok(())
}
