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
