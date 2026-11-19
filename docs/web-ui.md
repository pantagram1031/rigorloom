# Local web UI (`rigorloom ui`)

`rigorloom ui` opens the desktop review workspace in your browser. It is the
same React code as the desktop shell (`desktop/src`), served by a small
Python bridge (`runtime/scripts/rt_ui.py`) that talks to the Runtime. Nothing
leaves your machine, and the UI needs no Node.js at runtime: the prebuilt
bundle ships in `runtime/scripts/ui_dist/`.

## Running it

```sh
rigorloom ui                 # http://127.0.0.1:8765/, opens a browser
rigorloom ui --port 0        # pick a free port
rigorloom ui --no-open       # print the URL only
rigorloom ui --root DIR      # use DIR as the Runtime root
python runtime/scripts/cli.py ui   # from a checkout
```

The default root is `$XDG_DATA_HOME/rigorloom/runtime-root` (or
`~/.local/share/rigorloom/runtime-root`). Stop the server with Ctrl+C.

What you can do there:

- open a form in the Open workspace from the bundled corpus or upload your own `.hwpx`;
- review and queue edits (`fill_cell`, `replace_at_cell`, `set_run`, `delete_guides`),
  by hand or from an agent plan, in the Review workspace with each edit's
  address and before/after text;
- fill empty cells in the Fill workspace and read the guard diff for each
  edited paragraph with the protected expressions that were kept, removed or
  added (the same check as [`guard --mode block-diff`](guard-block-diff.md));
- approve a plan in the approval dialog, inspect revisions or undo history
  in the History workspace, and export the result as `.hwpx`;
- choose the interface language, theme and workspace folder in Settings
  (agent provider, model and credentials live in the operator dialog, opened
  from the command palette, 명령창, Ctrl+K);
- resolve human pipeline gates from the 자세히 section of the approval
  dialog, which writes `APPROVALS.md` (see below). The gate routes are
  unchanged; none of the five screens shows them outside that section.

## Security model

The bridge is meant for one person on their own computer.

- It binds to `127.0.0.1` only. Requests whose `Host` header is not a
  loopback name are refused, which blocks DNS rebinding. Requests a browser
  marks `Sec-Fetch-Site: cross-site` are refused too, and so is any request
  whose `Origin` is not a loopback `http` page or the desktop app's webview
  (`tauri://localhost`, `http://tauri.localhost`); an opaque `null` origin is
  refused.
- Every API call needs a per-run random token (`X-Rigorloom-Token`, compared
  in constant time). The token is written into the `index.html` served on
  `GET /`. **Any other program on the same computer can fetch that page and
  read the token**, just as it could read your files. Web pages from other
  origins cannot: the bridge sends no CORS headers, so a browser will not
  hand them the response.
- The event stream (`/events`) and staged export download
  (`/api/export-download`) accept the per-launch token via `?token=`.
  `EventSource` cannot send custom headers, so `/events` requires `?token=`.
  For export download, `export_candidate` returns a tokenized `downloadUrl`,
  and `desktop/src/actions.ts` fetches it via `fetch()` into an in-memory
  `Blob`, checks the bytes' SHA-256 against the applied candidate, and triggers
  a download from a `blob:` URL rather than navigating a plain `<a href>` link.
  Because `?token=` can appear in local proxy or request logs for the life of
  the server process, `rigorloom ui` rotates the token on every launch.
- An agent runs as a separate Runtime process (`--entry agent`) and cannot
  call host-only methods such as approval or apply.

### Why export download uses a query token

Keeping `GET /api/export-download?token=...` is acceptable for this local
bridge because four independent controls limit exposure:

- **Loopback bind**: `create_bridge_server` (`runtime/scripts/rt_ui.py`) binds
  exclusively to `127.0.0.1`, never a public or LAN interface.
- **Host allowlist and cross-site refusal**: `_check_origin_guards` runs on
  every `GET` and `POST`, rejecting any `Host` outside `ALLOWED_HOSTS`
  (`127.0.0.1` or `localhost`, blocking DNS rebinding), refusing requests
  with `Sec-Fetch-Site: cross-site`, and refusing an `Origin` other than a
  loopback `http` page or the Tauri webview (`invalid_origin`).
- **Per-launch token and directory confinement**: `_require_query_token`
  compares `?token=` against the per-launch random token with
  `hmac.compare_digest`, and `resolve_export_download` validates the filename
  against `VALID_UPLOAD_NAME_RE` (`^[A-Za-z0-9._-]+$`, no `..`) and
  `is_relative_to(<root>/exports/)` so only staged `.hwpx` exports can be read.
- **No `Referer` leak to other origins**: the UI downloads via `fetch()` into
  an in-memory `Blob` rather than navigating a tab to `/api/export-download`,
  and the endpoint responds with `application/octet-stream`,
  `Content-Disposition: attachment`, and `Cache-Control: no-store` — never an
  HTML document that could render outbound links or subresources carrying a
  `Referer` header.

## Approval is bound to the plan you saw

The approval dialog shows the plan id, its hash and the SHA-256 of the
document it was proposed against. Approving records exactly that plan hash.
If the document's bytes or the queued edits change after you approved, the
approval no longer matches: the queue shows a re-approval banner and apply is
refused until you approve again.

## Pipeline gates and `APPROVALS.md`

Resolving a human gate from the UI appends a line such as
`topic_pick: approved by NAME via ui at=TIMESTAMP` to the workspace's
`APPROVALS.md`, then runs `pipeline_ctl gate`. Because `pipeline_ctl` treats
any `rejected` line for a gate as winning over every `approved` line, earlier
decisions for the same gate are not deleted: they are kept as
`# superseded ...` comments, which `pipeline_ctl` ignores. Script gates
cannot be resolved here; they run through `pipeline_ctl check`.

## Rebuilding the bundle

```sh
npm --prefix desktop ci
npm --prefix desktop run build:web
```

This writes `runtime/scripts/ui_dist/`. CI rebuilds it on Linux and fails if
the result differs from the committed files, so the bundle is always the
output of the reviewed source. The build was byte-identical on Node 20 and
Node 22 with Vite 5.4.

## Not yet

- Agent plans that use `goto_text` or `normalize_clones` are refused with a
  reason; the review queue cannot show them faithfully yet.
- The browser end-to-end test (`tests/test_ui_playwright.py`) is skipped
  when Playwright is not installed, which includes CI.
- There is no multi-user or remote mode, and none is planned for this bridge.
