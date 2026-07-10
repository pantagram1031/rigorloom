# Rigorloom Studio

Rigorloom Studio is a local-only, read-only view of report workspaces. It shows
the live stage graph, gates, next action, redacted personalization lock,
evidence, drafts, PDF iterations, provenance, anomalies, and scorecards.

```sh
python -m pip install -r studio/requirements.txt
python studio/main.py
```

By default it reads `workspaces/`. Set `STUDIO_WORKSPACE_ROOT` to inspect a
different local workspace root. The server binds only to `127.0.0.1` and does
not call model providers or external services.
