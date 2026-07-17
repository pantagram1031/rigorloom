# Personalization contract v1

Personalization is private local state, not a repository artifact. Create it
with `pipeline/scripts/personalization_ctl.py init`; the default location is
`.local/personalization/`, which is ignored by Git. A shared or existing
workspace may instead use an external `--profile-root`.

## Store and privacy

The store separates identity, writing preferences/rules, academic profile,
form-specific records, feedback, and troubleshooting. Identity is disabled by
default and is never inferred from reports, filenames, or templates. Raw form
inspection data remains local. The public repository ships only this contract
and generic defaults.

Generated report prose is forbidden as style evidence. An agent observation,
detector score, or single correction is a `candidate` until a human approves
it. A workspace records only a redacted, reproducible effective configuration
in `.pipeline/personalization.lock.json`.

## Resolution order

`request explicit > form user override > form extracted conditions > subject
profile > global profile > public defaults`

```sh
python pipeline/scripts/personalization_ctl.py --profile-root <PRIVATE_ROOT> init
python pipeline/scripts/personalization_ctl.py --profile-root <PRIVATE_ROOT> register-form --form <FORM> --form-profile <WS>/form_profile.json --subject <SUBJECT>
python pipeline/scripts/personalization_ctl.py --profile-root <PRIVATE_ROOT> resolve --workspace <WS> --form <FORM> --subject <SUBJECT> --request <WS>/request.yaml --form-profile <WS>/form_profile.json
python pipeline/scripts/personalization_ctl.py --profile-root <PRIVATE_ROOT> collect-feedback --workspace <WS>
```

`import-legacy` migrates only known local knowledge files and form hashes. It
does not copy reports, templates, names, student IDs, or generated prose into
the public repository, and it does not infer identity.

## Preference packs v2

A *preference pack* is a validated, versioned data file that encodes one facet
of operator taste. The public repository ships JSON Schemas
(`pipeline/references/preference_packs/*.schema.json`) and one neutral default
instance per type (`.../defaults/*.json`). The operator's real taste packs live
only under a private `--profile-root` (e.g. `~/.report-profile`), never in any
repository. Taste is data; the engine is code.

### Pack types

| Pack | Encodes |
|---|---|
| `prose_rules` | banned regex patterns (`hard`/`warn`), signature-phrase caps, endings policy per doc type, advisory notes |
| `figure_style` | plotting look (background, spines, grid, tick direction, color cycle, font, dpi, legend), colormap whitelist, banned aesthetics, caption-source policy |
| `report_structure` | title template, section policies, abstract mode, citation style (sources + in-text), curriculum-anchor-first, hedge cap, preferred sections |
| `saeteuk` | short-record char target, byte ceiling, special-char and numeric-overclaim bans, style |
| `gloss_allowlist` | terms allowed as a parenthetical gloss despite a general gloss ban |
| `constants_allowlist` | numeric constants that may bypass `unbacked_numeral` when value and optional unit match |
| `backends` | council seating; every command is an `args_argv` array, never a shell string |
| `policy_floors` | privacy/fidelity/safety floors that lower layers cannot weaken |

### Commands

```sh
python pipeline/scripts/personalization_ctl.py --profile-root <ROOT> register-pack --type prose_rules --file <PACK.yaml|.json>
python pipeline/scripts/personalization_ctl.py --profile-root <ROOT> list-packs
python pipeline/scripts/personalization_ctl.py --profile-root <ROOT> show-pack --type figure_style
```

`register-pack` parses `.json` or a documented `.yaml` subset (see
`load_pack_file`/`parse_yaml` in `personalization_ctl.py`), validates against
the type's schema, and stores a canonical copy at `<ROOT>/packs/<type>.json`.

`constants_allowlist.json` is intentionally a root JSON list rather than a
metadata wrapper. Each item has a numeric `value`, an optional `unit`, and a
human-readable `label`:

    [
      {"value": 9.81, "unit": "m/s^2", "label": "standard gravity"},
      {"value": 3.14159, "label": "pi approximation"}
    ]

When `unit` is present, both value and normalized unit must match the body
numeral. When it is absent, the exemption is value-only. The neutral public
default contains only universal constants and common conversions. Private
operator constants live at
`<PROFILE_ROOT>/packs/constants_allowlist.json` and are schema-validated
before the content audit runs.

The public `gloss_allowlist` is always the baseline. Operator gloss terms
extend it; they do not remove neutral software names. Unit-symbol exemptions
come from the shared `claim_extraction` unit dictionary rather than a second
list in the style checker.

### Schema validator subset

The bundled validator is stdlib-only and intentionally small. It honours
`type` (object/array/string/number/integer/boolean/null), `required`,
`properties`, `items`, `enum`, and `additionalProperties: false`. A schema node
with no `type` accepts any value (used for floor `value`). All other JSON Schema
keywords and draft 2020-12 meta keywords are ignored.

### Resolution and floors

`resolve` merges packs by the existing precedence — public defaults < global
profile < subject < form (< request) — and then merges **`policy_floors` LAST**.
Each floor entry `{pack, key, value}` wins unconditionally: if a
higher-precedence layer set that key to a different value, the floor value is
enforced and a `floor-override-warning` event is appended to the feedback log
and listed under `floor_warnings` in the lock. Request- and form-level
preferences therefore cannot weaken a privacy/fidelity/safety floor.

### Hash-only lock

`.pipeline/personalization.lock.json` records, for each pack type, only
`{pack_type, source, name, version, sha256}` — **never rule content**. The
sha256 is taken over the resolved-and-floored pack. The resolved ("effective")
configuration itself is written to the **private** profile side only, at
`<profile_root>/resolved/<workspace-name>.json`; the lock carries just its
`effective_sha256` plus a `resolved_path_hint`, never the resolved text.
`floor_warnings` in the lock keep only the key path and severity — the attempted
and floor values are reduced to `sha256:` prefixes. Consumers re-resolve the
actual rule content from the profile root at runtime and verify it against the
recorded hashes; the lock stays safe to keep inside a workspace because it leaks
no taste text and no identity.
