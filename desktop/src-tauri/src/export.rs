//! Dest-preserving publish of a candidate + receipt pair.
//!
//! `artifact/exportTo` is still GAP, so the shell copies the pair out of the
//! workspace. The copy is not allowed to:
//!
//! - destroy pre-existing destination bytes on a failed, crashed, or
//!   receipt-less attempt;
//! - return success unless both files landed (a complete new pair);
//! - treat a source/destination alias as a copy (Windows path spellings,
//!   hard links, and symlinks included).
//!
//! Staging writes the pair beside the destination first. The destination
//! itself is replaced last, and only after the receipt sidecar is already
//! in place. A failure after that point restores the destination from a
//! backup taken before the replace.

use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::path::{Component, Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

use crate::digest;

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct ExportOk {
    pub path: PathBuf,
    pub sha256: String,
    pub bytes: u64,
    pub receipt_path: PathBuf,
}

#[derive(Debug, Clone)]
#[allow(dead_code)]
pub struct ExportErr {
    pub code: &'static str,
    pub message: String,
    pub data: Vec<(String, String)>,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CrashAfter {
    Staged,
    ReceiptPublished,
    DestReplaced,
}

fn field(key: &str, value: impl std::fmt::Display) -> (String, String) {
    (key.to_string(), value.to_string())
}

fn err(code: &'static str, message: String, data: Vec<(String, String)>) -> ExportErr {
    ExportErr {
        code,
        message,
        data,
    }
}

pub fn receipt_sidecar(destination: &Path) -> PathBuf {
    destination.with_file_name(format!(
        "{}.receipt.json",
        destination
            .file_name()
            .map(|n| n.to_string_lossy().into_owned())
            .unwrap_or_else(|| "candidate".into())
    ))
}

/// Windows-aware alias: lexical spelling, then live filesystem identity.
pub fn paths_are_aliases(left: &Path, right: &Path) -> bool {
    let left_text = left.as_os_str().to_string_lossy();
    let right_text = right.as_os_str().to_string_lossy();
    if left_text.is_empty() || right_text.is_empty() {
        return false;
    }
    if looks_windows_path(&left_text) || looks_windows_path(&right_text) {
        if normalize_windows_path_text(&left_text) == normalize_windows_path_text(&right_text) {
            return true;
        }
    } else if normalize_posix_path_text(&left_text) == normalize_posix_path_text(&right_text) {
        return true;
    }
    same_filesystem_node(left, right)
}

fn looks_windows_path(text: &str) -> bool {
    let bytes = text.as_bytes();
    if text.contains('\\') {
        return true;
    }
    if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
        return true;
    }
    let lower = text.to_ascii_lowercase();
    lower.starts_with("\\\\") || lower.starts_with("//") || lower.starts_with("\\\\?\\")
}

fn strip_extended_prefix(text: &str) -> String {
    let lower = text.to_ascii_lowercase();
    if lower.starts_with("\\\\?\\unc\\") || lower.starts_with("//?/unc/") {
        return format!("\\\\{}", text.get(8..).unwrap_or(""));
    }
    if lower.starts_with("\\\\?\\") || lower.starts_with("//?/") {
        return text.get(4..).unwrap_or("").to_string();
    }
    text.to_string()
}

fn normalize_windows_path_text(text: &str) -> String {
    let stripped = strip_extended_prefix(text);
    let unified = stripped.replace('/', "\\");
    let lower = unified.to_ascii_lowercase();
    rebuild_windows_parts(lower.trim_end_matches([' ', '.']))
}

fn rebuild_windows_parts(trimmed: &str) -> String {
    let mut out = String::new();
    let mut rest = trimmed;
    if rest.starts_with("\\\\") {
        out.push_str("\\\\");
        rest = &rest[2..];
    }
    let mut stack: Vec<&str> = Vec::new();
    for piece in rest.split('\\') {
        if piece.is_empty() || piece == "." {
            continue;
        }
        if piece == ".." {
            if stack.last().is_some_and(|p| !p.ends_with(':')) {
                stack.pop();
            }
            continue;
        }
        stack.push(piece);
    }
    out.push_str(&stack.join("\\"));
    out
}

fn normalize_posix_path_text(text: &str) -> String {
    let path = Path::new(text);
    let mut out = PathBuf::new();
    for component in path.components() {
        match component {
            Component::CurDir => {}
            Component::ParentDir => {
                out.pop();
            }
            other => out.push(other.as_os_str()),
        }
    }
    out.to_string_lossy().into_owned()
}

fn same_filesystem_node(left: &Path, right: &Path) -> bool {
    match (fs::metadata(left), fs::metadata(right)) {
        (Ok(a), Ok(b)) => {
            #[cfg(unix)]
            {
                use std::os::unix::fs::MetadataExt;
                a.dev() == b.dev() && a.ino() == b.ino()
            }
            #[cfg(windows)]
            {
                use std::os::windows::fs::MetadataExt;
                a.volume_serial_number() == b.volume_serial_number()
                    && a.file_index() == b.file_index()
                    && a.volume_serial_number().is_some()
                    && a.file_index().is_some()
            }
            #[cfg(not(any(unix, windows)))]
            {
                let _ = (a, b);
                false
            }
        }
        _ => false,
    }
}

fn unique_tag() -> String {
    let ns = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    format!("{ns}-{}", std::process::id())
}

fn copy_durable(from: &Path, to: &Path) -> io::Result<u64> {
    let mut src = File::open(from)?;
    let mut dst = OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(to)?;
    let n = io::copy(&mut src, &mut dst)?;
    dst.flush()?;
    dst.sync_all()?;
    Ok(n)
}

fn atomic_replace(from: &Path, to: &Path) -> io::Result<()> {
    #[cfg(windows)]
    {
        windows_replace(from, to)
    }
    #[cfg(not(windows))]
    {
        fs::rename(from, to)
    }
}

#[cfg(windows)]
fn windows_replace(from: &Path, to: &Path) -> io::Result<()> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Foundation::GetLastError;
    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
    };

    fn wide(path: &Path) -> Vec<u16> {
        path.as_os_str()
            .encode_wide()
            .chain(std::iter::once(0))
            .collect()
    }
    if !to.exists() {
        return fs::rename(from, to);
    }
    let src = wide(from);
    let dst = wide(to);
    let ok = unsafe {
        MoveFileExW(
            src.as_ptr(),
            dst.as_ptr(),
            MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
        )
    };
    if ok == 0 {
        Err(io::Error::from_raw_os_error(unsafe { GetLastError() } as i32))
    } else {
        Ok(())
    }
}

fn remove_if_exists(path: &Path) {
    let _ = fs::remove_file(path);
}

/// Publish artifact + receipt to `destination` / `destination.receipt.json`.
///
/// `crash` is test-only: it stops after a named step so the matrix can
/// assert dest bytes and the absence of a success return.
pub fn publish_export_pair(
    artifact: &Path,
    receipt: &Path,
    destination: &Path,
) -> Result<ExportOk, ExportErr> {
    publish_export_pair_at(artifact, receipt, destination, None)
}

pub fn publish_export_pair_at(
    artifact: &Path,
    receipt: &Path,
    destination: &Path,
    crash: Option<CrashAfter>,
) -> Result<ExportOk, ExportErr> {
    let dest = destination;
    let receipt_dest = receipt_sidecar(dest);

    if dest.as_os_str().is_empty() || dest.file_name().is_none() {
        return Err(err(
            "export_failed",
            "저장할 파일 이름이 없습니다.".into(),
            vec![field("destination", dest.to_string_lossy())],
        ));
    }

    let parent = dest.parent().filter(|p| !p.as_os_str().is_empty());
    if let Some(parent) = parent {
        if !parent.is_dir() {
            return Err(err(
                "export_failed",
                "저장할 폴더가 없습니다.".into(),
                vec![field("parent", parent.to_string_lossy())],
            ));
        }
    }

    for (left, right, why) in [
        (artifact, dest, "destination aliases the candidate"),
        (artifact, receipt_dest.as_path(), "receipt destination aliases the candidate"),
        (receipt, dest, "destination aliases the source receipt"),
        (receipt, receipt_dest.as_path(), "receipt destination aliases the source receipt"),
        (dest, receipt_dest.as_path(), "destination and receipt sidecar are the same file"),
    ] {
        if paths_are_aliases(left, right) {
            return Err(err(
                "export_alias",
                format!("같은 파일이라 내보낼 수 없습니다 ({why})."),
                vec![
                    field("left", left.to_string_lossy()),
                    field("right", right.to_string_lossy()),
                    field("reason", why),
                ],
            ));
        }
    }

    if dest.is_dir() {
        return Err(err(
            "export_failed",
            "대상이 폴더입니다.".into(),
            vec![field("destination", dest.to_string_lossy())],
        ));
    }

    let dest_existed = dest.is_file();
    let receipt_existed = receipt_dest.is_file();
    let prior_dest = if dest_existed {
        match fs::read(dest) {
            Ok(bytes) => Some(bytes),
            Err(e) => {
                return Err(err(
                    "export_failed",
                    format!("기존 대상 파일을 읽지 못했습니다: {e}"),
                    vec![field("destination", dest.to_string_lossy())],
                ));
            }
        }
    } else {
        None
    };

    let tag = unique_tag();
    let stem = dest
        .file_name()
        .map(|n| n.to_string_lossy().into_owned())
        .unwrap_or_else(|| "candidate".into());
    let stage_parent = parent
        .map(Path::to_path_buf)
        .unwrap_or_else(|| PathBuf::from("."));
    let dest_tmp = stage_parent.join(format!(".{stem}.export-{tag}"));
    let receipt_tmp = stage_parent.join(format!(".{stem}.export-{tag}.receipt.json"));
    let dest_bak = stage_parent.join(format!(".{stem}.export-bak-{tag}"));
    let receipt_bak = stage_parent.join(format!(".{stem}.export-bak-{tag}.receipt.json"));

    let cleanup_temps = || {
        remove_if_exists(&dest_tmp);
        remove_if_exists(&receipt_tmp);
        remove_if_exists(&dest_bak);
        remove_if_exists(&receipt_bak);
    };

    if let Err(e) = copy_durable(artifact, &dest_tmp) {
        cleanup_temps();
        return Err(err(
            "export_failed",
            format!("후보본을 저장하지 못했습니다: {e}"),
            vec![field("destination", dest.to_string_lossy())],
        ));
    }
    if let Err(e) = copy_durable(receipt, &receipt_tmp) {
        cleanup_temps();
        return Err(err(
            "export_failed",
            format!("영수증을 저장하지 못했습니다: {e}"),
            vec![field("destination", receipt_dest.to_string_lossy())],
        ));
    }

    let (sha256, bytes) = match digest::sha256_file(&dest_tmp) {
        Ok(pair) => pair,
        Err(e) => {
            cleanup_temps();
            return Err(err(
                "export_failed",
                format!("내보낸 파일을 다시 읽지 못했습니다: {e}"),
                vec![field("destination", dest.to_string_lossy())],
            ));
        }
    };

    if crash == Some(CrashAfter::Staged) {
        // Destination bytes are untouched. Temps are a recoverable pair
        // until this handled failure cleans them; a real crash would leave them.
        cleanup_temps();
        return Err(err(
            "export_failed",
            "export crashed after staging".into(),
            vec![field("stage", "staged")],
        ));
    }

    if dest_existed {
        if let Err(e) = copy_durable(dest, &dest_bak) {
            cleanup_temps();
            return Err(err(
                "export_failed",
                format!("기존 대상 파일을 보존하지 못했습니다: {e}"),
                vec![field("destination", dest.to_string_lossy())],
            ));
        }
    }
    if receipt_existed {
        if let Err(e) = copy_durable(&receipt_dest, &receipt_bak) {
            cleanup_temps();
            return Err(err(
                "export_failed",
                format!("기존 영수증을 보존하지 못했습니다: {e}"),
                vec![field("destination", receipt_dest.to_string_lossy())],
            ));
        }
    }

    let restore = |dest_replaced: bool, receipt_replaced: bool| {
        if dest_existed {
            if dest_bak.is_file() {
                let _ = atomic_replace(&dest_bak, dest);
            } else if let Some(bytes) = &prior_dest {
                let _ = fs::write(dest, bytes);
            }
        } else if dest_replaced {
            remove_if_exists(dest);
        }
        if receipt_existed {
            if receipt_bak.is_file() {
                let _ = atomic_replace(&receipt_bak, &receipt_dest);
            }
        } else if receipt_replaced {
            remove_if_exists(&receipt_dest);
        }
        cleanup_temps();
    };

    if let Err(e) = atomic_replace(&receipt_tmp, &receipt_dest) {
        restore(false, false);
        return Err(err(
            "export_failed",
            format!("영수증을 저장하지 못했습니다: {e}"),
            vec![field("destination", receipt_dest.to_string_lossy())],
        ));
    }

    if crash == Some(CrashAfter::ReceiptPublished) {
        restore(false, true);
        return Err(err(
            "export_failed",
            "export crashed after receipt publish".into(),
            vec![field("stage", "receipt")],
        ));
    }

    if let Err(e) = atomic_replace(&dest_tmp, dest) {
        restore(false, true);
        return Err(err(
            "export_failed",
            format!("후보본을 저장하지 못했습니다: {e}"),
            vec![field("destination", dest.to_string_lossy())],
        ));
    }

    if crash == Some(CrashAfter::DestReplaced) {
        restore(true, true);
        return Err(err(
            "export_failed",
            "export crashed after destination replace".into(),
            vec![field("stage", "dest")],
        ));
    }

    remove_if_exists(&dest_bak);
    remove_if_exists(&receipt_bak);
    remove_if_exists(&dest_tmp);
    remove_if_exists(&receipt_tmp);

    if !dest.is_file() || !receipt_dest.is_file() {
        restore(true, true);
        return Err(err(
            "export_failed",
            "내보낸 쌍이 완전하지 않습니다.".into(),
            vec![
                field("destination", dest.to_string_lossy()),
                field("receipt", receipt_dest.to_string_lossy()),
            ],
        ));
    }

    Ok(ExportOk {
        path: dest.to_path_buf(),
        sha256,
        bytes,
        receipt_path: receipt_dest,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use std::path::PathBuf;
    use std::sync::atomic::{AtomicU64, Ordering};

    static TMP_SEQ: AtomicU64 = AtomicU64::new(0);

    fn scratch() -> PathBuf {
        let n = TMP_SEQ.fetch_add(1, Ordering::Relaxed);
        let dir = std::env::temp_dir().join(format!(
            "rigorloom-export-safety-{}-{}",
            std::process::id(),
            n
        ));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    fn setup(dir: &Path) -> (PathBuf, PathBuf, PathBuf) {
        let artifact = dir.join("artifact.hwpx");
        let receipt = dir.join("receipt.json");
        let dest = dir.join("out.hwpx");
        fs::write(&artifact, b"NEW-ARTIFACT-BYTES").unwrap();
        fs::write(&receipt, b"{\"ok\":true}").unwrap();
        (artifact, receipt, dest)
    }

    #[test]
    fn windows_drive_and_slash_spellings_are_aliases() {
        assert!(paths_are_aliases(
            Path::new(r"C:\Users\a\out.hwpx"),
            Path::new("c:/users/a/out.hwpx"),
        ));
        assert!(paths_are_aliases(
            Path::new(r"\\?\C:\Users\a\out.hwpx"),
            Path::new(r"C:\Users\a\out.hwpx"),
        ));
        assert!(paths_are_aliases(
            Path::new(r"C:\Users\a\out.hwpx"),
            Path::new(r"C:\Users\a\.\out.hwpx"),
        ));
        assert!(!paths_are_aliases(
            Path::new(r"C:\Users\a\out.hwpx"),
            Path::new(r"C:\Users\a\other.hwpx"),
        ));
    }

    #[test]
    fn posix_dot_and_hardlink_are_aliases() {
        let dir = scratch();
        let a = dir.join("file.hwpx");
        fs::write(&a, b"same").unwrap();
        assert!(paths_are_aliases(&a, &dir.join("./file.hwpx")));
        let linked = dir.join("hard.hwpx");
        fs::hard_link(&a, &linked).unwrap();
        assert!(paths_are_aliases(&a, &linked));
        let other = dir.join("other.hwpx");
        fs::write(&other, b"same").unwrap();
        assert!(!paths_are_aliases(&a, &other));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn symlink_to_the_candidate_is_an_alias() {
        let dir = scratch();
        let a = dir.join("file.hwpx");
        fs::write(&a, b"same").unwrap();
        let link = dir.join("alias.hwpx");
        #[cfg(unix)]
        {
            std::os::unix::fs::symlink(&a, &link).unwrap();
            assert!(paths_are_aliases(&a, &link));
        }
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn same_path_destination_is_refused() {
        let dir = scratch();
        let (artifact, receipt, _) = setup(&dir);
        let err = publish_export_pair(&artifact, &receipt, &artifact).unwrap_err();
        assert_eq!(err.code, "export_alias");
        assert_eq!(fs::read(&artifact).unwrap(), b"NEW-ARTIFACT-BYTES");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn hardlink_destination_is_refused() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::hard_link(&artifact, &dest).unwrap();
        let err = publish_export_pair(&artifact, &receipt, &dest).unwrap_err();
        assert_eq!(err.code, "export_alias");
        assert_eq!(fs::read(&artifact).unwrap(), b"NEW-ARTIFACT-BYTES");
        assert_eq!(fs::read(&dest).unwrap(), b"NEW-ARTIFACT-BYTES");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn receipt_failure_leaves_existing_dest() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::write(&dest, b"OLD-DESTINATION-BYTES").unwrap();
        // Make the sidecar a directory so the receipt replace cannot land.
        fs::create_dir(receipt_sidecar(&dest)).unwrap();
        let err = publish_export_pair(&artifact, &receipt, &dest).unwrap_err();
        assert_eq!(err.code, "export_failed");
        assert_eq!(fs::read(&dest).unwrap(), b"OLD-DESTINATION-BYTES");
        assert!(!dest
            .parent()
            .unwrap()
            .read_dir()
            .unwrap()
            .any(|e| e
                .unwrap()
                .file_name()
                .to_string_lossy()
                .contains(".export-")));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn crash_after_stage_leaves_existing_dest() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::write(&dest, b"OLD-DESTINATION-BYTES").unwrap();
        let err =
            publish_export_pair_at(&artifact, &receipt, &dest, Some(CrashAfter::Staged)).unwrap_err();
        assert_eq!(err.code, "export_failed");
        assert_eq!(fs::read(&dest).unwrap(), b"OLD-DESTINATION-BYTES");
        assert!(!receipt_sidecar(&dest).exists() || !receipt_sidecar(&dest).is_file());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn crash_after_receipt_restores_existing_dest() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::write(&dest, b"OLD-DESTINATION-BYTES").unwrap();
        let err = publish_export_pair_at(
            &artifact,
            &receipt,
            &dest,
            Some(CrashAfter::ReceiptPublished),
        )
        .unwrap_err();
        assert_eq!(err.code, "export_failed");
        assert_eq!(fs::read(&dest).unwrap(), b"OLD-DESTINATION-BYTES");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn crash_after_dest_replace_restores_existing_dest() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::write(&dest, b"OLD-DESTINATION-BYTES").unwrap();
        let err = publish_export_pair_at(
            &artifact,
            &receipt,
            &dest,
            Some(CrashAfter::DestReplaced),
        )
        .unwrap_err();
        assert_eq!(err.code, "export_failed");
        assert_eq!(fs::read(&dest).unwrap(), b"OLD-DESTINATION-BYTES");
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn new_dest_receipt_failure_does_not_leave_a_success_pair() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::create_dir(receipt_sidecar(&dest)).unwrap();
        let err = publish_export_pair(&artifact, &receipt, &dest).unwrap_err();
        assert_eq!(err.code, "export_failed");
        assert!(!dest.exists());
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn success_is_a_complete_hashed_pair() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::write(&dest, b"OLD-DESTINATION-BYTES").unwrap();
        let ok = publish_export_pair(&artifact, &receipt, &dest).unwrap();
        assert_eq!(fs::read(&dest).unwrap(), b"NEW-ARTIFACT-BYTES");
        assert_eq!(fs::read(&ok.receipt_path).unwrap(), b"{\"ok\":true}");
        assert_eq!(ok.bytes, b"NEW-ARTIFACT-BYTES".len() as u64);
        let (sha, _) = digest::sha256_file(&dest).unwrap();
        assert_eq!(ok.sha256, sha);
        assert!(ok.receipt_path.ends_with("out.hwpx.receipt.json"));
        let _ = fs::remove_dir_all(&dir);
    }

    #[test]
    fn crash_points_never_return_ok() {
        let dir = scratch();
        let (artifact, receipt, dest) = setup(&dir);
        fs::write(&dest, b"OLD").unwrap();
        for point in [
            CrashAfter::Staged,
            CrashAfter::ReceiptPublished,
            CrashAfter::DestReplaced,
        ] {
            assert!(publish_export_pair_at(&artifact, &receipt, &dest, Some(point)).is_err());
            assert_eq!(fs::read(&dest).unwrap(), b"OLD");
        }
        let _ = fs::remove_dir_all(&dir);
    }
}
