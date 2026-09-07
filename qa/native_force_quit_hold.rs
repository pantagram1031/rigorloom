//! Standalone hold-after-stage exporter for the native force-quit Run-Card.
//!
//! Compiles `digest.rs` + `export.rs` without the Tauri crate graph, same
//! as `tests/desktop_export_safety_harness.rs`. After staging, the process
//! parks so Windows `taskkill` / `Stop-Process` can kill it mid-flight.
//!
//! ```text
//! rustc --edition 2021 -o hold qa/native_force_quit_hold.rs
//! hold --artifact A --receipt R --dest D --ready READY
//! ```

#[path = "../desktop/src-tauri/src/digest.rs"]
mod digest;

#[path = "../desktop/src-tauri/src/export.rs"]
mod export;

use std::env;
use std::path::PathBuf;
use std::process;

fn required_path(flag: &str) -> PathBuf {
    let mut args = env::args().skip(1);
    while let Some(arg) = args.next() {
        if arg == flag {
            if let Some(value) = args.next() {
                return PathBuf::from(value);
            }
            eprintln!("missing value for {flag}");
            process::exit(2);
        }
    }
    eprintln!("missing {flag}");
    process::exit(2);
}

fn main() {
    let artifact = required_path("--artifact");
    let receipt = required_path("--receipt");
    let dest = required_path("--dest");
    let ready = required_path("--ready");
    let result = export::publish_export_pair_hold(
        &artifact,
        &receipt,
        &dest,
        export::CrashAfter::Staged,
        &ready,
    );
    match result {
        Ok(_) => {
            eprintln!("hold helper returned Ok; force-quit did not fire");
            process::exit(3);
        }
        Err(err) => {
            eprintln!("hold helper returned {}: {}", err.code, err.message);
            process::exit(1);
        }
    }
}
