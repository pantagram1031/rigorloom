"""Record the guard's answer for the bundled 24-change 기안문 plan.

The fixture `scripts/fixtures/gongmun-24-guard.json` holds the runtime's own
copy of `examples/gongmun/expected/plan.json` proposed on
`tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx`, and the
`/api/guard/diff` result for it, so the node tests can run the attribution in
`workspace/guardHelper.ts` on the real paragraphs. The inspect and region
texts the attribution also needs are `src/fixtures/corpus.json`.

Run from the repository root: python desktop/scripts/record-gongmun-guard.py
"""
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "runtime" / "scripts"))

import rt_core  # noqa: E402
import rt_ui  # noqa: E402

FORM = REPO / "tests" / "corpus" / "forms" / "converted" / "gianmun-byeolji-1ho.hwpx"
PLAN = REPO / "examples" / "gongmun" / "expected" / "plan.json"
OUT = REPO / "desktop" / "scripts" / "fixtures" / "gongmun-24-guard.json"

expected = json.loads(PLAN.read_text(encoding="utf-8"))
root = Path(tempfile.mkdtemp(prefix="rlguard"))
core = rt_core.RuntimeCore(root, engine_root=REPO)
opened = core.open_path(str(FORM))
session_id = (opened.get("session") or opened)["sessionId"]
ops = [{"opId": op["opId"], "kind": op["kind"], **op["params"]} for op in expected["ops"]]
plan = core.plan_propose(session_id, "preedit", ops, proposer="gongmun-fixture", declares=expected["declares"])["plan"]
bridge = rt_ui.BridgeApplication(root=root, engine_root=REPO, token="fixture", explicit_root=True, prefs_path=root / "prefs.json")
guard = bridge.guard_diff({"sessionId": session_id, "planId": plan["planId"]})

fixture = {
    "_note": "The runtime's copy of examples/gongmun/expected/plan.json on "
             "tests/corpus/forms/converted/gianmun-byeolji-1ho.hwpx and its /api/guard/diff "
             "result. Regenerate with desktop/scripts/record-gongmun-guard.py.",
    "plan": plan,
    "guard": guard,
}
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text(json.dumps(fixture, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
print("wrote", OUT, OUT.stat().st_size, "bytes")
