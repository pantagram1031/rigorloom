//! rustc --test harness for the export-safety matrix.
//!
//! Compiles `digest.rs` + `export.rs` without the Tauri crate graph so the
//! card-1 tests run on a rustc that cannot rebuild the desktop lockfile.

#[path = "../desktop/src-tauri/src/digest.rs"]
mod digest;

#[path = "../desktop/src-tauri/src/export.rs"]
mod export;
