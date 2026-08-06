# Data-only extension packs

Rigorloom extension pack v1 makes local reporting knowledge portable without
letting an installed pack execute code. A pack may contribute validated prose,
figure, structure, saeteuk, and glossary preference data.

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
`constants_allowlist` is also rejected (v0.13.1 policy boundary): it relaxes the
deterministic numeric checker (`check_numbers`), so it remains a profile-level
pack managed through `personalization_ctl` and is never installable from an
extension pack. `tone_rules` is rejected for the same reason (v0.16 W4.1
ruling): it configures the thresholds and severities of the deterministic
tone checker (`check_tone_rules`) — the same relaxation-vector class, so it
too stays profile-level only.

The allowed set is computed, not hardcoded (v0.16 W4.1 pack split): every
pack type known to the install — core's general types plus enabled
distribution modules' declared types — minus the trust-sensitive set
(`backends`, `policy_floors`, `constants_allowlist`, `tone_rules`). A pack
type whose declaring module is not enabled is likewise refused, at both
install and resolve time.

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
normal higher-precedence replacement/deep-merge semantics. Constants layers
can only come from the profile itself (global/subject/form), never from an
installed extension.

Resolved rule content stays in the private profile-side effective document.
Workspace locks contain only hashes and extension receipt provenance. The
canonical resolver is used by personalization, content audit, and humanization,
so an installed extension changes report checks rather than merely appearing in
a registry.

`scripts/sync_local.py` remains the Rigorloom checkout-to-local-skill deployment
tool. It is not the extension package installer.
