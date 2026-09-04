# Codex private preview release train

Status: Epoch 0 intake reduced; C0 complete, C1 coherent snapshot committed, C2 pending
Owner: Codex private-preview integration steward
Updated: 2026-09-04 (Asia/Seoul)

This is compact durable state for the private Windows preview. Detailed test
logs and generated artifacts belong under the ignored `private/epoch-0/`
evidence root. This file records no personal path, credential, private document,
or proprietary asset.

## Epoch 0 pinned graph

Verified baseline: `origin/main`
`a635289dd054341b882c8e8b3c262a7f538efa5f`.

The specification proposed these sources in order:

1. PR #176 `claude/e5-ci-desktop-gate`
   `cb89cb4417ecfc81002818dba29b33fb3eba251b`
2. PR #184 `claude/desktop-e1-undo`
   `2a7bfabef454bc48e51add641bc79c13f32dd4f8`
3. PR #150 `docs/product-direction-desktop`
   `2594c1031cd8f119d81e0456fe497282d971ddee`
4. PR #153 `claude/threat-model-acceptance`
   `285121ff4a80506b19d275bf062c95a668f31f40`

Accepted Epoch 0 integration after semantic review:

1. PR #176 `cb89cb4417ecfc81002818dba29b33fb3eba251b`
2. PR #184 `2a7bfabef454bc48e51add641bc79c13f32dd4f8`
3. PR #150 `2594c1031cd8f119d81e0456fe497282d971ddee`

PR #153 is retained as immutable security/acceptance research input but is not
an ancestor of the accepted branch. Its acceptance condition C3 requires an
`authority_denied` refusal distinguishable from `unknown_method`; the #176/#184
implemented Runtime contract deliberately exposes no host-only method on an
agent connection and returns `unknown_method` with
`knownOnHostEntry: true`. The implemented protocol document explicitly says
`authority_denied` is not implemented and should be dropped. This is a semantic
authority-contract conflict despite a clean textual merge. Release-train §5
requires reducing the candidate instead of inventing a new protocol or silently
editing either source, so decision E0-D1 excludes #153 for this epoch.

Dependency facts:

- #176 and #184 diverge from Desktop Phase 6; merge base
  `c14a8bccc7e67292316ec57931a3829ff60ca4c1`.
- #184 contains PR #175; #175 is not merged separately.
- #150 descends directly from the verified main baseline.
- #153 is stacked on the Runtime protocol design; its merge base with the
  integrated Runtime/Desktop stack is
  `eee9725b78573a7f7675e0e0f33837ccc7f68635`, but E0-D1 excludes it.

Intake is frozen to the accepted three-head graph plus this state document.
PR #153, PRs #179–#183 and #185–#197, renderer/layout/font/line-breaking/
pagination/writer/Hancom-fidelity branches, Runtime workspace PRs #182/#185,
Agent Host #181, and every other unpinned ref are excluded. PR #184 is the sole
exception inside the numeric #179–#197 range. Claude-owned algorithms and
branches are immutable inputs.

## Verified C0 truth

- GitHub repository and remote main agree on `a635289…`.
- GitHub reports 48 open draft PRs.
- #176, #184, #150, and #153 remain OPEN/DRAFT, their heads match the pins,
  and GitHub reports each MERGEABLE/CLEAN.
- #176 has seven successful CI checks, including the Windows Desktop gate.
- #184, #150, and #153 have successful published matrix/render checks. Their
  historical logs are intake evidence only and will not count as Epoch 0 test
  proof.
- PR #196 remains excluded and UNSTABLE: its four Python matrix jobs failed;
  render-smoke passed.
- Latest published GitHub Release remains v0.16.0 while tag/package version
  v0.17.0 exists. Repository description and package description still use the
  report-pipeline identity. No outward-facing correction is authorized here.
- No remote `codex/private-preview-epoch-0` branch existed at intake.

Read completely before C1: repository `AGENTS.md`, `CONTRIBUTING.md`, product
Goal, product direction/program, Desktop README, Runtime protocol, Desktop
architecture, threat model, Desktop acceptance tasks, root/docs/security/
architecture/design/support/release/module/Studio/Engine documents, and the
four pinned PR bodies.

## Merge-tree evidence

Read-only sequential merge-tree from the verified baseline, before this state
commit, found no textual conflicts:

| Step | Exit | Tree |
|---|---:|---|
| main + #176 | 0 | `00eda1333a6bf2fce8e706e16e32a2416f0f3ecc` |
| previous + #184 | 0 | `3c69d865132b7e9c03210f25362b55a155a584ef` |
| previous + #150 | 0 | `bf1f10cf13fca55a10edc201d371a4cacf380c97` |
| previous + #153 | 0 | `94b224c3808c38d09146aba93c8caf9bf882cbb3` |

The four unique change sets have no overlapping paths: #176 has 5 unique
paths, #184 has 59 relative to their Phase 6 merge base (51 are #184-only),
#150 has 4, and #153 has 2. The clean merge-tree did not detect E0-D1's semantic
authority conflict.

Merge-tree was repeated after state commit
`c4ddedfc5c2c691fd7b0228d59c0a5145e9cdbda`:

| Accepted step | Exit | Tree |
|---|---:|---|
| state + #176 | 0 | `d4293ae33bd37001d767c50d2b6c013bd27356d2` |
| previous + #184 | 0 | `7eec7bb6834c218522b1d2e9dc29939741ccd8e2` |
| previous + #150 | 0 | `6806296de25a757c487ebb7391550f7165f13918` |

Accepted integration commits:

- #176 merge `f7642ec439d9a81053421ca3260e471a60971780`
- #184 merge `2a946e3397075a309135a5bdcdb5abcf02e2461b`
- #150 merge `21c5823ca694173fe737592f7aba353a2376c7e5`

The accepted integrated snapshot is `21c5823ca694173fe737592f7aba353a2376c7e5`,
tree `6806296de25a757c487ebb7391550f7165f13918`. All three accepted heads are
ancestors. #153 and every frozen-out head checked are not ancestors. The branch
has not been pushed.

## Decisions and boundaries

- Epoch 0 is a private installable preview, not a new feature wave.
- **E0-D1 accepted:** exclude PR #153 from the executable snapshot because its
  `authority_denied` acceptance requirement contradicts the implemented
  registry-absence contract. Use the release-train acceptance requirements and
  actual #176/#184 protocol/tests for Epoch 0; do not edit #153 or claim its C3
  passed.
- **E0-D2 accepted:** #176/#184's Runtime protocol implementation section,
  `rt_codes.py`, and authority/MCP tests agree on registry absence plus
  `unknown_method`/`knownOnHostEntry`, while two earlier design paragraphs still
  named `authority_denied`. The integration branch aligns those paragraphs and
  the transport-code inventory to the already implemented contract. No Runtime
  behavior, authority surface, or test expectation changes.
- **E0-S1 fixed:** a receipt with a recomputed `bodySha256` could redirect
  `candidate.path` outside its run directory. Candidate paths are now fixed to
  the canonical leaf `plan/apply` emits, and every file-opening candidate
  consumer shares that resolver. This is a preview security defect exposed by
  C5 receipt-tamper acceptance, not a renderer/writer or protocol-surface
  expansion.
- **E0-S2 fixed:** C5 terminated the Runtime during inspect, apply, and the
  post-apply residue check. Before the fix one ordinary child `cmd.exe`
  survived each Runtime death. Engine and module-checker children now start in
  a Windows kill-on-close Job (POSIX uses a process group for managed cleanup).
  The claim remains deliberately narrow: brokered/deliberately escaped
  processes and resource/filesystem/network isolation are not established.
- **E0-S3 fixed:** C5 transplanted a valid receipt onto an equal-byte candidate
  in another session. Before the fix `receipt/read` accepted it because only
  the artifact digest was checked. Receipt reads now cross-bind the containing
  session/run, exact source descriptor, plan identity/hash, and approved
  approval record. `bodySha256` remains explicitly integrity, not
  authentication.
- Fix only integration, packaging/installer, false-reporting harness, or
  accepted-preview-flow defects.
- Do not change renderer, writer, layout, font metrics, line breaking,
  pagination, Hancom-fidelity algorithms, or proof thresholds.
- Do not merge main, publish/tag/release/upload, alter branch protection, send
  the Hancom inquiry, or use real credentials/private documents.
- **User boundary, 2026-09-04:** do no further security work for now. Preserve
  the already completed E0-S1/E0-S2/E0-S3 fixes and evidence, but do not add,
  investigate, or iterate on further security findings. Continue only the
  non-security release train: packaging, ordinary regression verification,
  installed-preview acceptance when the desktop is available, and licensing/
  provenance work. Running the repository's unchanged general test suites is
  verification, not authorization for new security development.
- At most one draft integration PR may be created after evidence is complete;
  none exists now.
- The earlier `codex/private-desktop-preview` installer and its logs are prior
  regression evidence only. Epoch 0 reruns every required gate on the exact new
  integrated HEAD.

## Test state

Completed for this epoch:

- C0 document and PR-body intake: complete.
- Remote-head, PR-state, CI, merge-base, unique-path, and baseline merge-tree
  verification: complete.
- C1 reduced integration snapshot: complete at `21c5823…`; no product fix was
  invented and PR #153 was removed from branch ancestry.
- C1 authority-contract documentation fix: focused Runtime authority + MCP
  tests 39 passed, exit 0.
- C2 baseline on exact pre-harness-fix HEAD `b12c0d0…`, from git archive
  `3DA5AB8B…` under `private/epoch-0/b12c0d0/`:
  - archive privacy: exit 0, HARD=0, WARN=43;
  - compile sweep: exit 0, 125 files, 0 failures;
  - core-only full suite: exit 0, 3,431 passed / 1,199 skipped / 63 subtests,
    1,292.63 s (`pytest-core.xml`);
  - all-modules full suite: exit 0, 4,484 passed / 146 skipped / 81 subtests,
    1,698.20 s (`pytest-all.xml`); all six discovered modules enabled and
    `report -> style` resolved;
  - Runtime focused suite: exit 0, 413 passed, 467.99 s
    (`pytest-runtime.xml`);
  - Agent Host focused suite: exit 0, 168 passed, 90.25 s
    (`pytest-agenthost.xml`).
- `desktop/scripts/agent_roundtrip.py` first clean core-only invocation: exit 1,
  36 passed / 2 failed. The document/agent/authority/candidate/receipt path
  passed; pack checks falsely depended on absent untracked enablement.
- E0-H1 harness fix: red test failed 1/1 before the fix; after the fix the test
  passes 1/1 and the round trip passes 39/39, exit 0, using only a private
  scratch enablement file. Final full matrices must be rerun on the post-fix
  HEAD before C2 is complete.
- Post-E0-H1 package baseline on `68e25f6…`: npm ci 72 packages exit 0;
  TypeScript exit 0; sidecar freeze exit 0 (63.5 MiB, all role checks including
  `candidate/compare`); Rust release 11/11 exit 0; Tauri/NSIS exit 0. The
  private installer is 26,630,650 bytes, SHA-256 `F95B3AF5…`, unsigned. This
  build predates E0-S1 and is regression evidence only; rebuild is required.
- E0-S1 candidate-path containment: two red cases (traversal and absolute)
  both demonstrated receipt redirection before the fix; post-fix
  apply/lineage/module-check focused suite 64 passed, exit 0, and refusals do
  not echo the forged path.
- E0-S2 Runtime child cleanup at `4a04d5d…`:
  - committed parent-death regression: red before the fix (the late-write child
    survived), then 2/2 passed after the fix;
  - apply/module/transport/process focused suite: 81 passed, exit 0;
  - private hard-kill harness report
    `private/epoch-0/c5/runtime-kill-20260904-032232/summary.json`, SHA-256
    `53534018F12BE698C810AD52842773558C3131E86F5E9CB916A394C74493FC44`:
    inspect/apply/verification each had zero child survivors one second after
    Runtime death, zero canonical candidates before recovery, unchanged source
    bytes, and successful restart. Inspect reran successfully; apply and
    verification scenarios retried the still-approved plan and each published
    exactly one canonical candidate.
- Incomplete publication remains fail-closed: the verification-kill case left
  an artifact without a receipt on disk, and `candidate/list` exposed zero
  candidates after restart. The subsequent retry used a new run id. Orphan
  cleanup is not yet implemented and must remain a recorded storage-hygiene
  limitation rather than be described as a canonical candidate.
- E0-S3 stale-receipt identity at `f9fb6d8…`: the cross-session equal-byte
  transplant failed before the fix and then passed its refusal regression;
  apply/lineage/module-check focused suite 65 passed, exit 0.
- Private C5 hostile/credential/stale report
  `private/epoch-0/c5/adversarial-20260904-033314/summary.json`, SHA-256
  `BB2D41930D12B9023A425AF34C979A58C205359A7F61136BD3ABE620350DD132`,
  exact code HEAD `f9fb6d8e703bb55a98f5a3793dad8487c87aaf3a`:
  - a synthetic HWPX carried exact instructions to read an unrelated file,
    use network, self-approve, self-apply, export arbitrarily, and relabel proof;
    the simulated compromised provider observed the exact text through
    `document/readRegion`, but all six requested actions were refused at the
    compile gate, none compiled or reached Runtime, no plan/approval/candidate/
    export appeared, and source plus unrelated-file bytes were unchanged;
  - a fake credential reached only the Authorization header of a loopback fake
    HTTP server and was absent from request body, provider profile, and event
    log. No real credential or external network was used;
  - changed session bytes made validation stale, approval refused
    `plan_stale`, and no candidate appeared; equal-byte cross-session receipt
    reuse refused `receipt_body_mismatch`, and candidate byte drift refused
    `candidate_hash_mismatch`.
- C2 clean-archive verification on exact HEAD
  `d9800f4e52c4f84df00b5a7768c3f325106d0b59`, archive
  `private/epoch-0/d9800f4/source-d9800f4.zip` (14,121,455 bytes, SHA-256
  `B7BE0132A84CBD384CAAF9C272F3AD836DD44DDF23A2BD4B8065AAF46E445726`):
  - archive privacy exit 0, `HARD=0 / WARN=43`;
  - compile sweep exit 0, 125 files / 0 failures;
  - explicit core-only enablement wrote zero enabled modules;
  - explicit all-modules enablement discovered/enabled all six modules and
    resolved `report -> style`;
  - core-only full suite exit 0: 3,437 passed / 1,199 skipped / 63 subtests,
    pytest 3,180.98 s, wrapper 3,203.56 s. Full skip reasons and JUnit are in
    `pytest-core.txt` and `pytest-core.xml`.

C2 blocker on the same exact HEAD:

- The first all-modules run reached 4% with multiple failures/errors while C:
  reported zero free bytes. It was stopped; the partial log/XML are preserved
  as `pytest-all-disk-full-partial.*`. Only this run's five verified
  `pytest-of-SAMSUNG/pytest-*` temporary directories and the temporary current
  link were removed; no user documents or other application data were touched.
- A second run used the fresh dedicated basetemp
  `E:/rigorloom-epoch0-pytest-all-d9800f4` with 8.26 GiB still free. It passed
  the first run's 4% failure point, then emitted multiple genuine failures at
  45% (continued to 47% before interruption). The partial log is
  `pytest-all.txt`. The basetemp was removed after the process stopped; the log
  remains. No failure node/root-cause claim is made because the interrupted
  quiet run produced no traceback summary.
- Per the user's 2026-09-04 no-further-security-work boundary, do not diagnose
  or modify the newly exposed regression now. The all-modules gate is red and
  Epoch 0 is not packageable/acceptable until that boundary is lifted or the
  user gives separate direction.
- Source-only C6 draft on exact source HEAD `020d0b8…` (private and gitignored):
  - `private/epoch-0/020d0b8/compliance/source-inventory.json`, 129 npm / 242
    Windows-target Cargo / 9 sidecar-build Python packages, SHA-256
    `B0FDD7DB27879F73B539DA8EB1EBF199585DA493A113D6BE912081D0CB42C9AE`;
    all nine Python rows now carry their effective license and recorded
    license-file list, including the split standard/runtime-hook terms for
    `pyinstaller-hooks-contrib`;
  - `provenance-table.csv`, 57 item-level rows (32 corpus + 25 screenshots),
    SHA-256
    `2B389CB01109E437ECDC32E3245B732E2B496045BBF1CBF273D13F960C7FC683`;
  - `licensing-audit-draft.md`, SHA-256
    `5FF6A7FA45674AECC68B0C46D1283C8D10CE7DB66EA24F815ADEC8D16462B2DA`;
  - `THIRD_PARTY_NOTICES.draft.txt`, SHA-256
    `A453A32859C3F5A39654C48EDEF9A845340079CDA8D6C106C0046D858F778EB8`;
  - `evidence-index.json`, 2,335 bytes, SHA-256
    `6A10F51DA7EE50B356F7FC9C2B382125067C0E546807131A02A37730C71E2262`;
    all four indexed artifacts rehashed with zero mismatches, and the 57-row
    provenance table revalidated against current tracked bytes with zero
    path/hash/size mismatches.
  The audit is not legal clearance and the notice is explicitly blocked/incomplete
  until a green final installer is unpacked and reconciled.
- C6 stop-ship draft findings: the exact Hancom public-format attribution is
  absent from UI/manual/help/source; the bundled Pretendard font's OFL text was
  absent from the prior regression installer; PyMuPDF/MuPDF requires an
  AGPL-or-commercial decision and final notices; six non-law.go.kr corpus
  sources have unverified KOGL terms; derived Hancom conversion/render outputs,
  screenshots, and Rigorloom icon provenance need clarification. No tracked
  Hancom binary/SDK/font/template/icon/clipart/dictionary/security module or
  standalone local EULA was found, and no reverse-engineering implementation
  was found. The Hancom inquiry is drafted but not sent.
- Requirement-by-requirement completion audit on `ca2bc51…`:
  `private/epoch-0/ca2bc51/release/acceptance-matrix.json`, 10,669 bytes,
  SHA-256
  `18E6A0FC90FAE96C691B81460C91532C14FAB77F2D8A825EEB102E3999B993DC`.
  It classifies 34 requirements as 14 proven, 4 partial, 2 failed, 9 not run,
  4 blocked, and 1 policy-satisfied. All four evidence-file entries rehashed
  with zero mismatches. The matrix records `releaseDisposition: BLOCKED` and
  does not convert a narrow/unit/old result into installed-preview evidence.
  `f9fb6d8…` remains the latest behavior change; every later tracked change is
  only this durable state document.
- Current Git custody recheck: #176/#184/#150 and nested #175 are ancestors;
  the recorded E0-D1 #153 head is not. Current local tips of
  `own-renderer-mvp`, `engine-e2-typography`, `engine-e2-linebreak`, and
  `engine-e3-owpml-writer` are not ancestors. The worktree is clean and no
  remote integration branch exists.

Not yet complete on the final Epoch 0 HEAD:

- sidecar freeze, npm/TypeScript, Rust release tests, Tauri build, Desktop
  smoke, undo/lineage, Korean IME on the final post-security-fix HEAD;
- final core-only/all-modules/archive-privacy/compile re-run after E0-H1;
- installed-user flow and external Codex MCP acceptance;
- compliance/provenance pack generation for the actual Epoch 0 installer.

Known acceptance constraints:

- Desktop smoke is a packaged-executable test with checkout overrides, not a
  clean installed-user proof.
- Korean IME is foreground-only and cannot run while the operator is using the
  shared desktop.
- PR #184 screenshot captures are one sequential shared-root run, not
  independent clean reproductions; the evidence pack must preserve that limit.
- The packaged sidecar historically lacked pyhwpx and must report live HWPX
  conversion unavailable rather than fabricate a page.

## Compliance carry-forward to reverify

- PyMuPDF/MuPDF AGPL-or-commercial terms and missing bundled notices.
- Project MIT and Pretendard OFL notice inclusion in the built installer.
- Hancom public-format attribution placement, OLE licensing boundary,
  compatibility/non-affiliation wording, and local EULA summary only.
- Per-dependency inventory, corpus/sample/screenshot provenance, prohibited
  assets/practices, and an unsent Hancom inquiry.

No prior audit finding is treated as current until checked against the Epoch 0
tree and installer.

## User-only decisions / blockers

- Foreground GUI/IME acceptance needs the shared desktop to be free or an
  authorized isolated Windows environment.
- Any public branch push/draft PR, installer sharing, signing, publication,
  release, or GitHub metadata change requires the applicable user authority.
- A live provider leg needs legitimate user credentials; otherwise it remains
  `NOT RUN` while fake-server and boundary tests continue.
- The all-modules general regression run is red with adequate disk space. No
  installer build, installed preview, or acceptance claim is allowed while it
  remains red. Further investigation is paused by the user's no-security-work
  instruction; ask for separate direction rather than assuming scope.
- Current C: free space is approximately 0.31 GiB. Do not start a final
  sidecar/Tauri build until adequate headroom is available; prior build docs
  record multi-gigabyte pressure. E: test basetemp was deleted after the failed
  run and is not a persistent build destination.

## Next executable actions

1. Do not perform further security diagnosis or fixes. The all-modules failure
   is a release blocker awaiting user direction; do not build or present an
   installer from this red snapshot.
2. The non-security source-only C6 draft is complete; defer installer-content
   finalization until a passing build exists.
3. After the blocker is separately authorized and resolved, rebuild sidecar/
   installer and rerun the full Python, archive privacy, compile, Runtime, Agent
   Host, and package gates on the then-final tracked HEAD.
4. Generate the C6 compliance/provenance pack against the actual final
   installer contents; keep it private and do not claim legal clearance.
5. Keep foreground smoke/IME/install acceptance deferred while the operator is
   using the shared desktop; continue only non-security compliance work.
