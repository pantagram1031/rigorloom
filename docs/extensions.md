# Data-only extension packs

Rigorloom extension pack v1 makes local reporting knowledge portable without
letting an installed pack execute code. A pack may contribute validated prose,
figure, structure, saeteuk, glossary, and constants preference data.

## Manifest

Each source directory contains `manifest.json` and only the pack files declared
by that manifest are installed. The contract is
[`pipeline/references/extension_pack.schema.json`](../pipeline/references/extension_pack.schema.json).

```json
{
  "schema": "rigorloom/extension-pack-v1",
  "id": "school.physics-report",
  "version": "1.0.0",
  "kind": "data-pack",
  "rigorloom_api": 1,
  "priority": 100,
  "description": "Physics report preferences",
  "packs": {
    "prose_rules": "packs/prose_rules.json"
  }
}
```

`entrypoints`, hooks, executable backends, and policy-floor changes are rejected.
They need a separate capability and trust model and are not part of v1.

## Commands

```powershell
python scripts/extension_pack.py validate C:\path\to\pack
python scripts/extension_pack.py install C:\path\to\pack --profile C:\path\to\profile --dry-run
python scripts/extension_pack.py install C:\path\to\pack --profile C:\path\to\profile
python scripts/extension_pack.py list --profile C:\path\to\profile
python scripts/extension_pack.py doctor --profile C:\path\to\profile
python scripts/extension_pack.py activate school.physics-report 1.0.0 --profile C:\path\to\profile
```

Installed versions are immutable and receipt-backed at
`<profile>/extensions/<id>/<version>`. Installing a new version keeps the old
one, activates the new one, and allows an explicit rollback with `activate`.
`doctor` is read-only and detects missing, modified, or unexpected files.

## Resolution and privacy

Pack precedence is deterministic:

```text
public defaults < extensions (priority, then id) < operator global
                < subject < form < policy floors
```

Glossary terms and constants are additive allowlists: every layer may add
entries, but it cannot erase the public baseline. Other pack content follows
normal higher-precedence replacement/deep-merge semantics.

Resolved rule content stays in the private profile-side effective document.
Workspace locks contain only hashes and extension receipt provenance. The
canonical resolver is used by personalization, content audit, and humanization,
so an installed extension changes report checks rather than merely appearing in
a registry.

`scripts/sync_local.py` remains the Rigorloom checkout-to-local-skill deployment
tool. It is not the extension package installer.
