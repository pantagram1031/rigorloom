/**
 * 작업 팩 — the distribution modules this installation declares, and now runs.
 *
 * WHAT CHANGED. Until this slice the panel was a declaration viewer with a
 * 준비 중 label, because there was no method behind a button: the Runtime
 * protocol had no way to run a module's checker against a session. `module/check`
 * (§13) is that method, so the button exists now — and the whole difficulty of
 * this component moved from "do not draw a control that does nothing" to "do
 * not draw a verdict the runtime did not give".
 *
 * THE RULES THE REPORT IS DRAWN TO:
 *
 * **1. `skipped` is never a pass.** Twelve of the eighteen declared checkers
 * take a report WORKSPACE directory, and a session holds a document — so on
 * every document session they come back `skipped: needs_workspace`. They are
 * drawn as skipped, in the neutral vocabulary, with the runtime's own reason
 * translated to a fixed Korean line per reason CODE, never per checker. A
 * green tick there would be the single most misleading thing this panel could
 * print: twelve rules that did not look, reported as twelve rules that passed.
 *
 * **2. A rule the checker could not decide is a finding, not a silence.** The
 * runtime keeps `severity: "skipped"` findings (§13.4) precisely because "this
 * rule did not decide" is the fact a reader needs most and the one a bare pass
 * hides. So they are listed, with their code, at the same weight as a warning.
 *
 * **3. `ok: true` is not acceptance.** A checker can run clean and still leave
 * `acceptance` false, because it ran without an input it declares it needs —
 * on this corpus, every document checker `wants: [baseline]` and a session
 * with no candidate has no baseline to give it. The header shows acceptance,
 * and the row shows 입력 부족 beside its own clean verdict; they do not
 * contradict each other, they are two different facts.
 *
 * **4. Enablement has two readers and this panel prints both.** The list comes
 * from `module_registry.py` through a child process (`taskpacks.rs`); the
 * authority for RUNNING is `capabilities.modules.enabled`, the runtime's own
 * read of the same `enabled.yaml`, because that is the reader `module/check`
 * consults. When they disagree the panel says so rather than picking one.
 */
import {
  locateFindingAddress,
  openPack,
  packEnablementDisagrees,
  runModuleCheck,
  runtimeEnabledModules,
} from "../actions";
import { useWorkspace } from "../store";
import type { ModuleCheckReport, ModuleCheckRow, ModuleFinding, TaskPack } from "../types";
import { Tag } from "./Tag";

/** What each pack does once it is running. Intent, marked as such. */
const PLANNED: Record<string, string> = {
  report:
    "주제에서 제출본까지를 단계로 나눠 진행하고, 단계마다 아래 검사기를 게이트로 겁니다. 이 앱이 지금 돌릴 수 있는 것은 문서를 대상으로 하는 검사기뿐입니다.",
  gongmun: "공문 서식의 필수 항목과 표기 규칙을 채움 자리 검사에 얹습니다.",
  grant: "지원 사업 양식의 분량 제한과 항목 누락을 제출 전에 잡습니다.",
  hr: "인사 서식의 항목·표기 규칙을 검사에 얹습니다.",
  minwon: "민원 회신문의 구조와 어투를 검사에 얹습니다.",
  style: "본문 문체를 검사하고, 번역투를 걷어내는 윤문을 겁니다.",
};

/**
 * One Korean line per not-`ran` reason CODE.
 *
 * Keyed on the closed set in `rt_codes`, never on a checker's name, and never
 * written to contradict the runtime's own `detail` — which is printed beside
 * it. Where a reason arrives that this table does not know, the code itself is
 * shown: an unrecognised refusal must still be legible as a refusal.
 */
const NOT_RUN_REASON: Record<string, string> = {
  needs_workspace:
    "보고서 작업 폴더를 대상으로 하는 검사기입니다. 세션이 들고 있는 것은 문서 한 개라서, 돌리지 않고 건너뛰었습니다.",
  subject_undeclared:
    "이 검사기는 무엇을 받는지 선언에 적혀 있지 않습니다. 문서를 넘겨도 되는지 알 수 없어 건너뛰었습니다.",
  spawn_failed: "검사기를 실행조차 하지 못했습니다.",
  timed_out: "제한 시간을 넘겨 강제로 끊었습니다.",
  missing_dependency: "이 기계에 없는 것을 불러오다 죽었습니다.",
  usage_error: "검사기를 잘못된 방식으로 불렀습니다.",
  no_verdict: "실행은 됐지만 판정으로 읽을 만한 것을 내놓지 않았습니다.",
};

const SEVERITY_LABEL: Record<string, string> = {
  hard: "막힘",
  warn: "주의",
  skipped: "판정 안 함",
};

function severityTone(severity: string): "bad" | "warn" | "none" {
  if (severity === "hard") return "bad";
  if (severity === "warn") return "warn";
  return "none";
}

function addressLabel(address: NonNullable<ModuleFinding["address"]>): string {
  if (address.table != null && address.row != null && address.col != null) {
    return `표${address.table} (${address.row},${address.col})`;
  }
  if (address.atPara != null) return `문단 ${address.atPara}`;
  return "주소 없음";
}

function Finding({ finding, index }: { finding: ModuleFinding; index: number }) {
  const address = finding.address;
  return (
    <li className="pack-finding" data-testid={`module-check-finding-${index}`} data-severity={finding.severity}>
      <Tag tone={severityTone(finding.severity)}>
        {SEVERITY_LABEL[finding.severity] ?? finding.severity}
      </Tag>
      <span className="mono tiny">{finding.code ?? "—"}</span>
      <span className="what">{finding.message ?? ""}</span>
      {/* An address is a place the tree view can go to. A finding whose place
          the runtime could not translate gets NO link — a half address would
          select the wrong cell, and §13.4 returns null rather than half. */}
      {address ? (
        <button
          className="linkish mono tiny"
          data-testid={`module-check-address-${index}`}
          title="본문 보기에서 이 자리로 갑니다"
          onClick={() => locateFindingAddress(address)}
        >
          {addressLabel(address)}
        </button>
      ) : finding.location != null ? (
        <span className="dim tiny" title="런타임이 이 자리를 주소로 옮기지 못했습니다">
          {typeof finding.location === "string"
            ? finding.location
            : JSON.stringify(finding.location)}
        </span>
      ) : null}
    </li>
  );
}

function CheckerRow({ row, index }: { row: ModuleCheckRow; index: number }) {
  const ran = row.state === "ran";
  const findings = row.findings ?? [];
  return (
    <li className="pack-check" data-testid={`module-check-row-${index}`} data-checker={row.checker}
        data-state={row.state} data-reason={row.reason ?? ""}>
      <div className="pack-check-head">
        <span className="mono">{row.checker}</span>
        {ran ? (
          <Tag
            tone={row.ok === true ? "ok" : "bad"}
            title={`검사기가 내놓은 판정: ${row.verdict ?? "—"}`}
          >
            {row.verdict ?? (row.ok === true ? "pass" : "fail")}
          </Tag>
        ) : (
          <Tag tone="none" title={row.reason ?? undefined}>
            {row.state === "skipped" ? "건너뜀" : "실행 못 함"}
          </Tag>
        )}
        {/* §13.3. A clean verdict reached without an input the checker
            declares it needs is not the same as a clean verdict. Both are
            shown; neither is allowed to hide the other. */}
        {ran && row.partial ? (
          <Tag tone="warn" title={`선언한 입력 중 받지 못한 것: ${(row.wantsUnsatisfied ?? []).join(", ")}`}>
            입력 부족
          </Tag>
        ) : null}
      </div>

      {!ran ? (
        <p className="tiny pack-check-reason" data-testid={`module-check-why-${index}`}>
          {NOT_RUN_REASON[row.reason ?? ""] ?? `런타임이 ${row.reason ?? "이유 없이"} 로 넘겼습니다.`}
          {row.detail ? <span className="dim"> — {row.detail}</span> : null}
        </p>
      ) : null}

      {ran && row.partial ? (
        <p className="tiny pack-check-reason">
          {(row.wantsUnsatisfied ?? []).join(", ")} 없이 돌았습니다. 후보본이 아직 없어 견줄 원본
          양식을 넘겨줄 수 없었고, 그래서 이 판정은 완전하지 않습니다.
        </p>
      ) : null}

      {findings.length > 0 ? (
        <ul className="pack-findings">
          {findings.map((finding, i) => (
            <Finding key={`${finding.code}-${i}`} finding={finding} index={i} />
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function Report({ report }: { report: ModuleCheckReport }) {
  const counts = report.counts;
  return (
    <div className="pack-report" data-testid="module-check-report" data-module={report.module}>
      <div className="head">
        <Tag tone={report.acceptance ? "ok" : "warn"}>
          {report.acceptance ? "통과" : "통과 아님"}
        </Tag>
        <span className="mono tiny" data-testid="module-check-counts">
          검사기 {counts.selected} · 돌았음 {counts.ran} · 건너뜀 {counts.skipped} · 실행 못 함{" "}
          {counts.unavailable} · 막힘 {counts.hard} · 주의 {counts.warn}
        </span>
      </div>
      {report.reason ? (
        <p className="tiny dim" data-testid="module-check-summary">
          {report.reason}
        </p>
      ) : null}
      <ul className="pack-checks">
        {report.checks.map((row, i) => (
          <CheckerRow key={row.checker} row={row} index={i} />
        ))}
      </ul>
      <p className="tiny dim">
        {report.evidence.note} · 대상은 세션 사본의 또 다른 사본입니다({report.subject.kind}),
        원본도 세션 사본도 검사기에 넘어가지 않습니다.
      </p>
    </div>
  );
}

function RunPanel({ pack }: { pack: TaskPack }) {
  const run = useWorkspace((s) => s.packRun);
  const sessionId = useWorkspace((s) => s.activeSessionId);
  const runtimeEnabled = runtimeEnabledModules();
  // The runtime's own answer, because it is the reader `module/check` uses.
  // `null` means this connection reported no module capability at all, which
  // is older-runtime shaped; the registry's flag is then all there is.
  const runnable = runtimeEnabled === null ? pack.enabled : runtimeEnabled.includes(pack.name);
  const mine = run && run.module === pack.name ? run : null;

  return (
    <>
      <div className="pack-run" data-testid="pack-run">
        <button
          className="action primary"
          data-testid="pack-run-button"
          disabled={!runnable || !sessionId || mine?.phase === "running"}
          title={
            !runnable
              ? "이 팩은 켜져 있지 않습니다. 켜는 것은 enabled.yaml 에 적는 설치 시점의 일이고, 앱에서 할 수 있는 일이 아닙니다."
              : !sessionId
                ? "검사할 문서를 먼저 여십시오."
                : "이 팩의 검사기를 지금 열려 있는 문서에 대해 돌립니다. 문서는 바뀌지 않습니다."
          }
          onClick={() => void runModuleCheck(pack.name)}
        >
          {mine?.phase === "running" ? "검사 중…" : "실행"}
        </button>
        <span className="tiny dim">
          {!runnable
            ? "꺼져 있는 팩은 아무도 돌릴 수 없습니다"
            : !sessionId
              ? "문서를 열면 돌릴 수 있습니다"
              : "문서를 읽기만 합니다. 계획도 승인도 만들지 않습니다"}
        </span>
      </div>

      {mine?.phase === "failed" && mine.error ? (
        <div className="pack-refusal" data-testid="pack-refusal">
          <div className="head">
            <Tag tone="bad">검사를 돌리지 못했습니다</Tag>
            <code className="mono">{mine.error.code}</code>
          </div>
          <p className="tiny">{mine.error.message}</p>
        </div>
      ) : null}

      {mine?.phase === "done" && mine.report ? <Report report={mine.report} /> : null}
    </>
  );
}

function PackDetail({ pack }: { pack: TaskPack }) {
  const runtimeEnabled = runtimeEnabledModules();
  const disagrees = packEnablementDisagrees().includes(pack.name);

  return (
    <div className="pack-detail" data-testid="pack-detail">
      <div className="head">
        <h3>{pack.title}</h3>
        {pack.enabled ? <Tag tone="ok">켜짐</Tag> : <Tag tone="none">꺼짐</Tag>}
      </div>
      <p className="prose">{PLANNED[pack.name] ?? pack.blurb}</p>

      <h4>지금 이 설치본에 실제로 있는 것</h4>
      <ul className="tiny">
        <li>
          선언 상태:{" "}
          {pack.enabled ? (
            <>
              <Tag tone="ok">켜짐</Tag> <span className="mono">enabled.yaml</span> 에 들어 있습니다
            </>
          ) : (
            <>
              <Tag tone="none">꺼짐</Tag> 디스크에는 있지만 켜져 있지 않습니다
            </>
          )}
        </li>
        {/* Two readers of one file. Silence here would mean the button's state
            and the label above it could disagree with nothing to explain it. */}
        {disagrees ? (
          <li data-testid="pack-enablement-split">
            <Tag tone="warn">읽은 값이 다름</Tag> 목록을 읽은 등록기는{" "}
            {pack.enabled ? "켜짐" : "꺼짐"} 이라 하고, 검사를 실제로 돌리는 런타임은{" "}
            {runtimeEnabled?.includes(pack.name) ? "켜짐" : "꺼짐"} 이라 합니다. 실행 여부는
            런타임 쪽을 따릅니다
          </li>
        ) : null}
        {pack.requiresModules && pack.requiresModules.length > 0 ? (
          <li>
            다른 팩에 기댑니다: <span className="mono">{pack.requiresModules.join(", ")}</span>{" "}
            — 그 팩이 꺼져 있으면 이 팩도 켜지지 않습니다
          </li>
        ) : null}
        <li>
          검사기 {pack.checkers.length}개
          {pack.checkers.length > 0 ? (
            <span className="mono"> — {pack.checkers.map((c) => c.name).join(", ")}</span>
          ) : null}
        </li>
        <li>
          명령 {pack.cli.length}개
          {pack.cli.length > 0 ? (
            <span className="mono"> — {pack.cli.map((c) => c.name).join(", ")}</span>
          ) : null}
        </li>
      </ul>

      <h4>검사</h4>
      <RunPanel pack={pack} />

      <h4>아직 없는 것</h4>
      <p className="prose tiny">
        보고서 작업 폴더를 대상으로 하는 검사기는 여기서 돌릴 수 없습니다. 런타임에 작업 폴더라는
        개념 자체가 없어서, 문서 세션에 대고 부르면 건너뛰었다고 답합니다 — 통과가 아닙니다.
        팩 설정(<span className="mono">--pack</span>, <span className="mono">--vocabulary</span>)을
        고르는 방법도 아직 없어, 검사기는 각자의 기본값으로 돕니다.
      </p>
      <button className="action" data-testid="pack-close" onClick={() => openPack(null)}>
        닫기
      </button>
    </div>
  );
}

export function TaskPacks() {
  const packs = useWorkspace((s) => s.taskPacks);
  const open = useWorkspace((s) => s.packOpen);

  const selected = packs?.packs.find((pack) => pack.name === open) ?? null;

  return (
    <div className="section" data-testid="task-packs">
      <h3>
        작업 팩{" "}
        <span className="count">{packs?.available ? packs.packs.length : 0}</span>
      </h3>

      {!packs ? (
        <p className="empty">읽는 중입니다.</p>
      ) : !packs.available ? (
        <p className="empty" data-testid="task-packs-unavailable">
          {packs.reason}
        </p>
      ) : (
        <div className="rows">
          {packs.packs.map((pack) => (
            <button
              key={pack.name}
              className="row"
              aria-selected={pack.name === open}
              data-testid={`pack-${pack.name}`}
              onClick={() => openPack(pack.name === open ? null : pack.name)}
            >
              <span className="primary">
                {pack.title}
                {pack.enabled ? null : <span className="secondary"> · 꺼짐</span>}
              </span>
              <span className="secondary">{pack.blurb || pack.name}</span>
            </button>
          ))}
        </div>
      )}

      {selected ? <PackDetail pack={selected} /> : null}

      {packs?.available ? (
        <p className="empty" style={{ padding: "var(--s2) 0 0" }}>
          이 목록은 <span className="mono">enabled.yaml</span> 과 각 팩의 선언에서 그대로 읽은
          것입니다. 켜져 있는 팩만 돌릴 수 있고, 켜는 것은 설치 시점의 일입니다.
        </p>
      ) : null}
    </div>
  );
}
