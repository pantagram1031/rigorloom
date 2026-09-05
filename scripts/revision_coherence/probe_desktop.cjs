/* Execute production TypeScript functions with controlled Runtime responses.
 * Not a browser, IME, Tauri or type-checking test. No npm install or networking.
 */
'use strict';
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');

const [root, runtimeReport, typescriptOverride, intervention = "none"] = process.argv.slice(2);
if (!root || !runtimeReport) throw new Error('repo root and runtime report required');
const ts = require(typescriptOverride || path.join(root, 'desktop/node_modules/typescript'));
const file = path.join(root, 'desktop/src/actions.ts');
const text = fs.readFileSync(file, 'utf8');
const parsed = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
if (parsed.parseDiagnostics.length) throw new Error('actions.ts has parse errors');
const wanted = ['looselySameText', 'caretOffsetAt', 'beginParagraphEdit', 'clickOverlaySpan'];
const selected = wanted.map(name => {
  const matches = parsed.statements.filter(n => ts.isFunctionDeclaration(n) && n.name?.text === name);
  if (matches.length !== 1) throw new Error(`expected one ${name}; do not guess after refactor`);
  return matches[0].getText(parsed);
});
const baseline = selected.join('\n\n');
let program = baseline;
if (['frontend-routing-only','coherent-guard','public-guard'].includes(intervention)) {
  const needle = 'const sessionId = getState().activeSessionId;';
  if (program.split(needle).length !== 2) throw new Error('rebase the source intervention');
  program = program.replace(needle,
    'const captured = getState();\n' +
    '  const expectedRunId = captured.geometry?.source?.runId ?? null;\n' +
    '  const sessionId = captured.activeSessionId;');
  const read = 'const answer = await rt.readRegion(sessionId, [{ atPara }]);';
  if (program.split(read).length !== 2) throw new Error('rebase read intervention');
  let replacement = 'const answer = await rt.readRegion(sessionId, [{ atPara }], expectedRunId);';
  if (['coherent-guard','public-guard'].includes(intervention)) replacement += `
    if (getState().activeSessionId !== sessionId ||
        getState().geometry !== captured.geometry ||
        getState().render !== captured.render ||
        (answer.subject?.runId ?? null) !== expectedRunId) return 'stale_context';`;
  program = program.replace(read, replacement);
}
if (intervention === 'public-guard') {
  // Causal control only. A shipping implementation should pass one explicit
  // edit lease through both functions, not duplicate counters as this probe does.
  program = 'let probeBeginEpoch = 0; let probeClickEpoch = 0;\n' + program;
  program = program.replace('const captured = getState();',
    'const captured = getState(); const beginEpoch = ++probeBeginEpoch;');
  program = program.replace('if (getState().activeSessionId !== sessionId ||',
    'if (beginEpoch !== probeBeginEpoch || getState().activeSessionId !== sessionId ||');
  program = program.replace('  const id = `span-${span.index}`;',
    '  const clickSnapshot = getState(); const clickEpoch = ++probeClickEpoch;\n' +
    '  const id = `span-${span.index}`;');
  program = program.replace('const refusal = await beginParagraphEdit(span, fraction);',
    `const refusal = await beginParagraphEdit(span, fraction);
    if (clickEpoch !== probeClickEpoch ||
        getState().activeSessionId !== clickSnapshot.activeSessionId ||
        getState().geometry !== clickSnapshot.geometry ||
        getState().render !== clickSnapshot.render) return;`);
}
const emitted = ts.transpileModule(program, {
  compilerOptions: {target: ts.ScriptTarget.ES2020, module: ts.ModuleKind.CommonJS}
}).outputText;
const sourceHashes = Object.fromEntries(wanted.map((name, i) => [name,
  crypto.createHash('sha256').update(selected[i]).digest('hex')]));
const clone = value => JSON.parse(JSON.stringify(value));
const runtime = JSON.parse(fs.readFileSync(runtimeReport, 'utf8')).runtime;
const failures = [];

function span(text, atPara=0) {
  return {index: 0, text, confidence:'unique', address:{kind:'anchor', atPara},
          rect:[0.1,0.1,0.4,0.2], sizePt:12};
}
function initial(candidate=true) {
  return {activeSessionId:'session-a', texts:{}, selection:null, inlineEdit:null,
          overlayPick:null,
          head: candidate ? {sessionId:'session-a', runId:'candidate-a', sha256:'candidate-sha'} : null,
          render:{sessionId:'session-a', available:true,
                  source:{kind:'prepared_pdf', sha256:'pdf-sha',
                          ...(candidate ? {runId:'candidate-a'} : {})}},
          geometry:{sessionId:'session-a', source:{runId:candidate ? 'candidate-a' : undefined}}};
}
async function run(name, clicked, options, expectation) {
  let state = initial(options.candidate !== false);
  const writes = [];
  const reads = [];
  let release;
  const waiting = new Promise(resolve => { release = resolve; });
  const targetTexts = options.targetTexts || ['GAMMA','BETA'];
  const sourceTexts = options.sourceTexts || ['ALPHA','BETA'];
  const rt = {readRegion: async (sid, addresses, runId) => {
    reads.push({sessionId:sid, addresses:clone(addresses), runId:runId ?? null});
    if (options.defer && reads.length === 1) await waiting;
    if (options.noInventory) return {subject:{kind:'session_source',sha256:'source-sha'}, regions:[]};
    const isCandidate = runId === 'candidate-a' && !options.forceWrongSubject;
    const texts = isCandidate ? targetTexts : sourceTexts;
    return {subject:{kind:isCandidate ? 'candidate' : 'session_source',
                     sha256:isCandidate ? 'candidate-sha' : 'source-sha',
                     ...(isCandidate ? {runId:'candidate-a'} : {})},
            regions:addresses.map(({atPara}) => ({at_para:atPara,
                runs:[{index:0, text:texts[atPara]}]}))};
  }};
  const exports = {};
  const context = vm.createContext({exports, module:{exports}, rt,
    getState:()=>state,
    setState:patch=>{ writes.push(Object.keys(patch)); state={...state,...patch}; },
    queuedRunOpAt:()=>null,
    addressIsCaretTarget:address=>address.atPara != null,
    addressIsEditable:()=>false,
    addressLabel:address=>`paragraph ${address.atPara}`,
    caretRefusalText:reason=>reason,
    setSelection:selection=>{ writes.push(['selection']); state={...state,selection}; },
    openAddress:()=>{throw new Error('unexpected cell path in paragraph-only probe');},
  });
  new vm.Script(emitted, {filename:'extracted-actions.js'}).runInContext(context);
  const entry = options.publicEntry ? exports.clickOverlaySpan : exports.beginParagraphEdit;
  const pending = entry(clone(clicked));
  if (options.defer) {
    // Explicit scheduler step, not an arbitrary sleep.
    await Promise.resolve();
    state = {...state, ...(options.switchTo || {})};
    if (options.secondClick) await exports.clickOverlaySpan(clone(options.secondClick));
    release();
  }
  const refusal = await pending;
  const result = {name, refusal, reads, writes, activeSessionId:state.activeSessionId,
                  selection:state.selection, inlineEdit:state.inlineEdit, overlayPick:state.overlayPick};
  result.contract_passed = !!expectation(result);
  failures.push(result);
}

(async () => {
  await run('source_caret_control', span('ALPHA'), {candidate:false},
            r=>r.refusal===null && r.inlineEdit?.atPara===0);
  await run('missing_inventory_control', span('ALPHA'), {candidate:false,noInventory:true},
            r=>r.refusal==='no_inventory' && r.inlineEdit===null);
  await run('text_mismatch_control', span('NOT_THE_RUN'), {candidate:false},
            r=>r.refusal==='run_text_differs' && r.inlineEdit===null);
  await run('candidate_read_routes_same_revision', span('BETA',1), {},
            r=>r.reads[0]?.runId==='candidate-a');
  await run('candidate_new_text_reopens_for_edit', span('GAMMA'), {},
            r=>r.refusal===null && r.inlineEdit?.atPara===0 && r.inlineEdit?.before==='GAMMA');
  // Same text is intentionally present in both versions: it is NOT an identity check.
  await run('wrong_subject_same_text_is_rejected', span('BETA',1), {forceWrongSubject:true},
            r=>r.refusal!==null && r.inlineEdit===null);
  const wrong = runtime.scenes.candidate_collision_is_not_false_unique[0];
  await run('runtime_to_desktop_wrong_target_is_not_accepted', wrong,
            {targetTexts:['BETA','BETA']},
            r=>r.refusal!==null || r.inlineEdit?.atPara===0);
  await run('late_reply_does_not_edit_another_session', span('ALPHA'),
            {candidate:false, defer:true, switchTo:{activeSessionId:'session-b'}},
            r=>r.refusal!==null && r.inlineEdit===null && r.selection===null);
  await run('late_reply_does_not_reopen_replaced_view', span('ALPHA'),
            {candidate:false, defer:true,
             switchTo:{render:null, geometry:null, inlineEdit:null, selection:null}},
            r=>r.refusal!==null && r.inlineEdit===null);
  await run('public_click_source_control', span('ALPHA'), {candidate:false,publicEntry:true},
            r=>r.inlineEdit?.atPara===0 && r.overlayPick?.kind==='caret');
  await run('public_click_ignores_other_session_reply', span('ALPHA'),
            {candidate:false,publicEntry:true,defer:true,switchTo:{activeSessionId:'session-b'}},
            r=>r.inlineEdit===null && r.selection===null && r.overlayPick===null);
  await run('public_click_ignores_replaced_view_reply', span('ALPHA'),
            {candidate:false,publicEntry:true,defer:true,switchTo:{render:null,geometry:null}},
            r=>r.inlineEdit===null && r.selection===null && r.overlayPick===null);
  await run('public_click_latest_intent_wins', span('ALPHA'),
            {candidate:false,publicEntry:true,defer:true,secondClick:span('BETA',1)},
            r=>r.inlineEdit?.atPara===1 && r.selection?.atPara===1 &&
               r.overlayPick?.address?.atPara===1);
  console.log(JSON.stringify({typescriptVersion:ts.version,
    intervention,
    executed:intervention === 'none' ? 'transpiled production function bodies with controlled responses' : 'counterfactual: transformed function bodies; no product fix applied',
    function_text_sha256:sourceHashes, cases:failures}));
})().catch(error => { console.error(error.stack); process.exitCode=2; });
