//! Kill-on-close Windows Job Object for the sidecar.
//!
//! Ported unchanged in substance from `spikes/shell-tauri/src-tauri/src/jobkill.rs`
//! on branch `claude/desktop-shell-spike`. The spike measured why it is not
//! optional (Decision section of `docs/desktop-shell-spike.md`, finding 1):
//!
//! | Sidecar build | stdin-EOF handling | Job object | Hard kill of the shell |
//! |---|---|---|---|
//! | `--console`   | exits on EOF | no  | clean, ~1 s |
//! | `--console`   | ignores EOF  | no  | clean, ~1 s |
//! | `--noconsole` | ignores EOF  | no  | **orphaned, alive at 25 s** |
//! | `--noconsole` | exits on EOF | no  | **orphaned, alive at 25 s** |
//! | `--noconsole` | ignores EOF  | yes | **clean, 1 s** |
//!
//! Two things that table settles. A `--console` sidecar only looked safe
//! because console-group teardown was doing the work, not the sidecar's own
//! logic — and a shipping app freezes `--noconsole` to avoid dragging a
//! `conhost.exe` into the process tree. And the sidecar's own stdin-EOF
//! handling does NOT save it: rows 3 and 4 differ in exactly that and orphan
//! identically. Treat EOF handling as defence in depth; the job object is the
//! mechanism.
//!
//! `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is enforced by the kernel: when the
//! last handle to the job closes — which happens when the shell process dies,
//! however it dies, including `Stop-Process -Force` where no Rust cleanup runs
//! — every process in the job is terminated. Child processes inherit job
//! membership, so confining the sidecar also covers the `form_inspect` and
//! `preedit` children the Runtime spawns per call
//! (`runtime/scripts/rt_engine.py:192`).
//!
//! The handle is intentionally leaked: its lifetime must equal the shell
//! process's lifetime, and letting the OS close it on exit is exactly the
//! semantics wanted.

#[cfg(windows)]
pub fn confine_to_job(pid: u32) -> Result<(), String> {
    use std::mem::size_of;
    use windows_sys::Win32::Foundation::{CloseHandle, HANDLE};
    use windows_sys::Win32::System::JobObjects::{
        AssignProcessToJobObject, CreateJobObjectW, SetInformationJobObject,
        JobObjectExtendedLimitInformation, JOBOBJECT_EXTENDED_LIMIT_INFORMATION,
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE,
    };
    use windows_sys::Win32::System::Threading::{
        OpenProcess, PROCESS_SET_QUOTA, PROCESS_TERMINATE,
    };

    unsafe {
        let job: HANDLE = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() {
            return Err("CreateJobObjectW failed".into());
        }

        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        let ok = SetInformationJobObject(
            job,
            JobObjectExtendedLimitInformation,
            &info as *const _ as *const core::ffi::c_void,
            size_of::<JOBOBJECT_EXTENDED_LIMIT_INFORMATION>() as u32,
        );
        if ok == 0 {
            CloseHandle(job);
            return Err("SetInformationJobObject failed".into());
        }

        let proc = OpenProcess(PROCESS_SET_QUOTA | PROCESS_TERMINATE, 0, pid);
        if proc.is_null() {
            CloseHandle(job);
            return Err(format!("OpenProcess({pid}) failed"));
        }

        let assigned = AssignProcessToJobObject(job, proc);
        CloseHandle(proc);
        if assigned == 0 {
            CloseHandle(job);
            return Err("AssignProcessToJobObject failed".into());
        }
        // `job` is deliberately never closed — see the module comment. It is a
        // raw HANDLE with no Drop, so simply not calling CloseHandle leaks it
        // for the life of the process, which is exactly the intended lifetime.
        let _ = job;
        Ok(())
    }
}

#[cfg(not(windows))]
pub fn confine_to_job(_pid: u32) -> Result<(), String> {
    Err("job objects are Windows-only".into())
}
