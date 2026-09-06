<#
.SYNOPSIS
    Run-Cards PowerShell runner for unattended QA evidence collection.

.DESCRIPTION
    Lightweight, read-only preflight and card execution script designed for unattended
    test runners and local Windows environments.
    Conforms to the Astra Pro FIRST_72H QA contract:
    - Records environment preflight JSON (OS, disk free, tools present).
    - Runs card test paths (c1 export safety, c2 revision coherence, c3 run-scoped edit).
    - Skips interactive Windows GUI/IME/Installer tests with deterministic NOT_RUN status.
    - Writes Junit XML, JSONL stubs, and verdict JSON under the evidence directory.
    - Never claims GUI/IME success.

.PARAMETER JobFile
    Path to the job.json specification file. Defaults to "qa/job.json".

.PARAMETER WorkspaceRoot
    Path to the repository root. Defaults to current directory.

.EXAMPLE
    pwsh -File qa/Run-Cards.ps1 -JobFile qa/job.json
#>
param(
    [string]$JobFile = "qa/job.json",
    [string]$WorkspaceRoot = "."
)

$ErrorActionPreference = "Continue"

$ws = Resolve-Path $WorkspaceRoot
$jobPath = Join-Path $ws $JobFile

if (-not (Test-Path $jobPath)) {
    Write-Error "Job file not found at: $jobPath"
    exit 2
}

$job = Get-Content $jobPath -Raw -Encoding utf8 | ConvertFrom-Json

$evidenceDir = $job.evidence_dir
if (-not [System.IO.Path]::IsPathRooted($evidenceDir)) {
    $evidenceDir = Join-Path $ws $evidenceDir
}
New-Item -ItemType Directory -Force -Path $evidenceDir | Out-Null

# --- 1. Environment Preflight (READ-ONLY) ---
$drive = Get-PSDrive -PSProvider FileSystem | Select-Object -First 1
$freeBytes = 0
if ($drive -and $drive.Free) { $freeBytes = $drive.Free }

function Test-ToolPresent([string]$cmd) {
    return ($null -ne (Get-Command $cmd -ErrorAction SilentlyContinue))
}

$tools = [ordered]@{
    python3 = (Test-ToolPresent "python3") -or (Test-ToolPresent "python")
    pytest  = (Test-ToolPresent "pytest")
    rustc   = (Test-ToolPresent "rustc")
    cargo   = (Test-ToolPresent "cargo")
    pwsh    = (Test-ToolPresent "pwsh")
    git     = (Test-ToolPresent "git")
    node    = (Test-ToolPresent "node")
    npm     = (Test-ToolPresent "npm")
}

$gitSha = $null
$gitBranch = $null
if (Test-ToolPresent "git") {
    $gitSha = (& git -C $ws rev-parse HEAD 2>$null)
    $gitBranch = (& git -C $ws rev-parse --abbrev-ref HEAD 2>$null)
}

$preflight = [ordered]@{
    timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    platform = [ordered]@{
        os_version = [System.Environment]::OSVersion.VersionString
        is_64bit = [System.Environment]::Is64BitOperatingSystem
        machine_name = [System.Environment]::MachineName
    }
    disk_free_bytes = $freeBytes
    tools_present = $tools
    git = [ordered]@{
        sha = $gitSha
        branch = $gitBranch
    }
    runner_capabilities = [ordered]@{
        supports_windows_gui = $false
        supports_windows_ime = $false
        supports_windows_installer = $false
        supports_headless_cli = $true
    }
}

$preflightPath = Join-Path $evidenceDir "preflight.json"
$preflight | ConvertTo-Json -Depth 5 | Set-Content $preflightPath -Encoding utf8

# --- 2. Execute Cards ---
$allowed = $job.allowed_commands
$targetCards = $job.cards
if ($null -eq $targetCards -or $targetCards.Count -eq 0) {
    $targetCards = @("c1", "c2", "c3")
}

$verdicts = @()

foreach ($card in $targetCards) {
    $isAllowed = ($allowed -contains $card) -or ($allowed -contains "all")
    if (-not $isAllowed) {
        $verdicts += [ordered]@{
            card_id = $card
            status = "BLOCKED"
            exit_code = $null
            reason = "Card '$card' not in allowed_commands whitelist"
            gui_claimed = $false
        }
        continue
    }

    $junitFile = Join-Path $evidenceDir "junit-$card.xml"
    $logFile = Join-Path $evidenceDir "$card.log"
    $jsonlFile = Join-Path $evidenceDir "$card.jsonl"

    if ($card -eq "c1") {
        $pyTests = @(
            (Join-Path $ws "tests/test_desktop_export_safety.py"),
            (Join-Path $ws "engine/tests/test_hwpx_write_export_safety.py")
        )
        $existingTests = $pyTests | Where-Object { Test-Path $_ }
        $rustHarness = Join-Path $ws "tests/desktop_export_safety_harness.rs"
        $hasRust = (Test-Path $rustHarness) -and (Test-ToolPresent "rustc")

        if ($existingTests.Count -eq 0 -and -not $hasRust) {
            $verdicts += [ordered]@{
                card_id = $card
                status = "NOT_RUN"
                exit_code = $null
                reason = "Card 1 test files not present in tree"
                gui_claimed = $false
            }
            continue
        }

        # Run pytest
        $pyCmd = if (Test-ToolPresent "python3") { "python3" } else { "python" }
        & $pyCmd -m pytest $existingTests "--junitxml=$junitFile" -q *>&1 | Set-Content $logFile -Encoding utf8
        $ec = $LASTEXITCODE

        $status = if ($ec -eq 0) { "PASS" } else { "FAIL" }
        $rec = [ordered]@{
            timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            card_id = $card
            runner = "pytest"
            exit_code = $ec
            status = $status
            gui_ime_claimed = $false
        }
        $rec | ConvertTo-Json -Compress | Add-Content $jsonlFile -Encoding utf8

        $verdicts += [ordered]@{
            card_id = $card
            status = $status
            exit_code = $ec
            reason = "Card 1 test execution finished"
            gui_claimed = $false
        }
    }
    elseif ($card -eq "c2") {
        $pyTests = @(
            (Join-Path $ws "tests/test_runtime_revision_coherence.py"),
            (Join-Path $ws "tests/test_desktop_revision_coherence.py")
        )
        $existingTests = $pyTests | Where-Object { Test-Path $_ }
        if ($existingTests.Count -eq 0) {
            $verdicts += [ordered]@{
                card_id = $card
                status = "NOT_RUN"
                exit_code = $null
                reason = "Card 2 test files not present in tree"
                gui_claimed = $false
            }
            continue
        }
        $pyCmd = if (Test-ToolPresent "python3") { "python3" } else { "python" }
        & $pyCmd -m pytest $existingTests "--junitxml=$junitFile" -q *>&1 | Set-Content $logFile -Encoding utf8
        $ec = $LASTEXITCODE
        $status = if ($ec -eq 0) { "PASS" } else { "FAIL" }
        $rec = [ordered]@{
            timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            card_id = $card
            runner = "pytest"
            exit_code = $ec
            status = $status
            gui_ime_claimed = $false
        }
        $rec | ConvertTo-Json -Compress | Add-Content $jsonlFile -Encoding utf8

        $verdicts += [ordered]@{
            card_id = $card
            status = $status
            exit_code = $ec
            reason = "Card 2 test execution finished"
            gui_claimed = $false
        }
    }
    elseif ($card -eq "c3") {
        $pyTests = @(
            (Join-Path $ws "tests/test_desktop_run_scoped_edit.py"),
            (Join-Path $ws "tests/test_desktop_revision_coherence.py")
        )
        $existingTests = $pyTests | Where-Object { Test-Path $_ }
        if ($existingTests.Count -eq 0) {
            $verdicts += [ordered]@{
                card_id = $card
                status = "NOT_RUN"
                exit_code = $null
                reason = "Card 3 test files not present in tree"
                gui_claimed = $false
            }
            continue
        }
        $pyCmd = if (Test-ToolPresent "python3") { "python3" } else { "python" }
        & $pyCmd -m pytest $existingTests "--junitxml=$junitFile" -q *>&1 | Set-Content $logFile -Encoding utf8
        $ec = $LASTEXITCODE
        $status = if ($ec -eq 0) { "PASS" } else { "FAIL" }
        $rec = [ordered]@{
            timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            card_id = $card
            runner = "pytest"
            exit_code = $ec
            status = $status
            gui_ime_claimed = $false
        }
        $rec | ConvertTo-Json -Compress | Add-Content $jsonlFile -Encoding utf8

        $verdicts += [ordered]@{
            card_id = $card
            status = $status
            exit_code = $ec
            reason = "Card 3 test execution finished"
            gui_claimed = $false
        }
    }
    elseif ($card -in @("c4", "c5", "gui", "ime", "installer")) {
        $rec = [ordered]@{
            timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
            card_id = $card
            runner = "not_run"
            exit_code = 0
            status = "NOT_RUN"
            gui_ime_claimed = $false
        }
        $rec | ConvertTo-Json -Compress | Add-Content $jsonlFile -Encoding utf8

        $verdicts += [ordered]@{
            card_id = $card
            status = "NOT_RUN"
            exit_code = $null
            reason = "Card '$card' requires local interactive Windows GUI/IME runner"
            gui_claimed = $false
        }
    }
    else {
        $verdicts += [ordered]@{
            card_id = $card
            status = "BLOCKED"
            exit_code = $null
            reason = "Unknown card id '$card'"
            gui_claimed = $false
        }
    }
}

# --- 3. Summary & Verdict ---
$overall = "PASS"
$failCount = ($verdicts | Where-Object { $_.status -eq "FAIL" }).Count
$blockedCount = ($verdicts | Where-Object { $_.status -eq "BLOCKED" }).Count
$passCount = ($verdicts | Where-Object { $_.status -eq "PASS" }).Count
$notRunCount = ($verdicts | Where-Object { $_.status -eq "NOT_RUN" }).Count

if ($failCount -gt 0) { $overall = "FAIL" }
elseif ($blockedCount -gt 0) { $overall = "BLOCKED" }
elseif ($passCount -eq 0 -and $notRunCount -gt 0) { $overall = "NOT_RUN" }

$summary = [ordered]@{
    candidate_id = $job.candidate_id
    run_id = $job.run_id
    sha = $job.sha
    requested_model = if ($job.requested_model) { $job.requested_model } else { "gemini-3.8-flash" }
    overall_status = $overall
    counts = [ordered]@{
        PASS = $passCount
        FAIL = $failCount
        NOT_RUN = $notRunCount
        BLOCKED = $blockedCount
    }
    gui_ime_claimed = $false
    verdicts = $verdicts
}

$verdictPath = Join-Path $evidenceDir "verdict.json"
$summary | ConvertTo-Json -Depth 5 | Set-Content $verdictPath -Encoding utf8

$summary | ConvertTo-Json -Depth 5
if ($overall -in @("PASS", "NOT_RUN")) { exit 0 } else { exit 1 }
