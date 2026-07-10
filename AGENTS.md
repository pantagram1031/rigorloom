# Agent instructions

Read `docs/pipeline-master-v0.6.md` before operating a workspace.

1. Run `python pipeline/scripts/pipeline_ctl.py resume <absolute-workspace>`.
2. Open the returned stage playbook under `pipeline/references/playbooks/`.
3. Satisfy its entry conditions and produce only its declared artifacts.
4. Resolve gates through `pipeline_ctl.py`; never edit PIPELINE.md state by hand.
5. After a transition, read the regenerated `NEXT_TASK.md` or
   `.pipeline/handoff.json` before beginning another task.

Provider rule: assign roles by capability (`high-reasoning`, `research`,
`vision`, `mechanical`, `independent-review`), not by vendor name. If a listed
backend is unavailable, select an equivalent backend and record it in events.

Do not commit workspaces, private forms, credentials, personal style profiles,
or generated reports to this repository.
