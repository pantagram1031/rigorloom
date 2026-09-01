//! M11 mitigation — Windows Job Object with KILL_ON_JOB_CLOSE.
//!
//! Measured behaviour that makes this necessary (see the Decision section of
//! docs/desktop-shell-spike.md): a PyInstaller `--console` sidecar happens to
//! die when the shell is hard-killed, because tearing down the shell's console
//! takes its console group with it. A `--noconsole` sidecar — which is what a
//! shipping app uses, to avoid a conhost process and a console flash — orphans
//! permanently, and stdin-EOF handling inside the sidecar does NOT save it.
//!
//! A job object with `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE` is enforced by the
//! kernel: when the last handle to the job closes (which happens when the
//! shell process dies, however it dies), every process in the job is
//! terminated. Child processes inherit job membership, so assigning the
//! PyInstaller bootloader also covers the extracted child it spawns.
//!
//! The handle is intentionally leaked: its lifetime must equal the shell
//! process's lifetime, and letting the OS close it on exit is exactly the
//! semantics we want.

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
