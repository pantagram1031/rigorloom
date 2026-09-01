/**
 * Agent view, centre: what happened TO THE DOCUMENT, as calm cards.
 *
 * The source changed in Phase 4 and the change is the point. This used to show
 * this shell's own protocol traffic, because `event/subscribe` was GAP and a
 * panel that showed nothing would have been worse than one that showed
 * something honest. It now shows the session's own `events.jsonl`, live:
 * `session.opened`, `plan.proposed`, `plan.validated`, `approval.requested`,
 * `approval.resolved`, `plan.applied`, `candidate.published`, `pdf.prepared`.
 *
 * Three properties inherited from the protocol, used rather than assumed:
 *
 * - **`seq` is the line index in the file**, not an allocated counter, so it
 *   is monotonic and gap-free by construction. The order on screen is the
 *   order on disk, and the store de-duplicates on it so a replay after a
 *   reconnect cannot make one event look like two.
 * - **The replay is from the beginning** (`after: -1`), so opening a document
 *   shows everything that ever happened to it, including in a previous launch.
 *   A history that started when the window opened would be a log, not a
 *   history.
 * - **The file remains authoritative.** A notification is a projection of an
 *   appended line (§3.13); nothing here is a second source of truth.
 *
 * The shell's own protocol chatter did not disappear — it moved behind a
 * disclosure at the bottom, which is where diagnostics belong once there is
 * something real to show above them.
 */
import { runAgentProposal } from "../actions";
import { useWorkspace } from "../store";
import type { Activity, RuntimeEvent } from "../types";
import { Tag } from "./Tag";

/** Korean product language for each event kind the Runtime appends. */
const SAID: Record<string, (d: Record<string, unknown>) => string> = {
  "session.opened": (d) =>
    `문서를 열었습니다 — ${String(d.sourceName ?? "")} (${String(d.documentKind ?? "")})`,
  "plan.proposed": (d) =>
    `작업 ${String(d.ops ?? "?")}건을 제안했습니다 — ${String(d.proposer ?? "알 수 없음")}`,
  "plan.validated": (d) =>
    d.ok === true
      ? "쓰기 전 확인을 통과했습니다"
      : `쓰기 전 확인에서 막혔습니다 — ${((d.hard as string[]) ?? []).join(", ")}`,
  "approval.requested": (d) => `승인을 요청했습니다 — ${String(d.requestedBy ?? "")}`,
  "approval.resolved": (d) =>
    d.state === "approved"
      ? `${String(d.approver ?? "사람")}이(가) 승인했습니다`
      : `${String(d.approver ?? "사람")}이(가) 거절했습니다`,
  "plan.applied": () => "계획을 사본에 적용했습니다",
  "candidate.published": (d) =>
    `후보본을 남겼습니다 — ${String(d.sha256 ?? "").slice(0, 12)} · 검사 ${
      d.acceptance === true ? "통과" : "미통과"
    }`,
  "pdf.prepared": (d) => `페이지 그림용 PDF를 만들었습니다 — ${String(d.sha256 ?? "").slice(0, 12)}`,
};

/**
 * No vermilion here, deliberately.
 *
 * `approval.requested` in a history is a record of something that happened,
 * not a gate demanding a response — the gate itself is in the review queue and
 * that is where the point colour is spent. Spending it on a log line would
 * make the timeline compete with the one thing the user actually has to act
 * on, which is exactly how a reserved colour stops being reserved.
 */
const TONE: Record<string, "ok" | "warn" | "none"> = {
  "approval.resolved": "ok",
  "candidate.published": "ok",
  "plan.validated": "none",
};

function EventCard({ event }: { event: RuntimeEvent }) {
  const detail = (event.detail ?? event) as Record<string, unknown>;
  const said = SAID[event.kind]?.(detail) ?? event.kind;
  const tone =
    event.kind === "plan.validated" && detail.ok === false
      ? "warn"
      : (TONE[event.kind] ?? "none");
  return (
    <article className="card" data-testid={`event-${event.seq}`}>
      <div className="head">
        <Tag tone={tone}>{event.kind}</Tag>
        <span className="when mono">#{event.seq}</span>
        <span className="when mono">{event.at}</span>
      </div>
      <p className="said">{said}</p>
      <details>
        <summary>원본 기록</summary>
        <pre>{JSON.stringify(event, null, 2)}</pre>
      </details>
    </article>
  );
}

function describeActivity(item: Activity): string {
  if (item.kind === "lifecycle" || item.kind === "log") return item.text ?? "";
  const frame = item.frame as { kind?: string; method?: string } | null;
  return frame?.method ?? frame?.kind ?? "알림";
}

export function Timeline() {
  const events = useWorkspace((s) => s.events);
  const eventPhase = useWorkspace((s) => s.eventPhase);
  const eventError = useWorkspace((s) => s.eventError);
  const subscription = useWorkspace((s) => s.eventSubscription);
  const activity = useWorkspace((s) => s.activity);
  const agentTool = useWorkspace((s) => s.agentTool);
  const agentPhase = useWorkspace((s) => s.agentPhase);
  const agentError = useWorkspace((s) => s.agentError);
  const agentRun = useWorkspace((s) => s.agentRun);
  const sessionId = useWorkspace((s) => s.activeSessionId);

  const newestFirst = [...events].reverse();

  return (
    <div className="timeline" data-testid="timeline">
      <div className="panel-head">
        <span className="panel-title">문서에 일어난 일</span>
        {subscription ? (
          <Tag tone="ok" title={`구독 ${subscription}`}>
            실시간
          </Tag>
        ) : eventPhase === "failed" ? (
          <Tag tone="bad">끊김</Tag>
        ) : (
          <Tag tone="none">대기</Tag>
        )}
        {/* NOT `event-count`: the cards are `event-<seq>`, and a harness
            selecting `[data-testid^="event-"]` would count this element as a
            twentieth card. The design slice already lost a cycle to a
            prefix-selector picking up the wrong node. */}
        <span className="count" data-testid="events-total">
          {events.length}
        </span>
      </div>

      {/* The dev-mode agent door. Present only where its script is reachable;
          a shipped installation without a checkout simply does not show it,
          rather than showing a button that cannot work. */}
      {agentTool?.available && sessionId ? (
        <div className="agent-door" data-testid="agent-door">
          <button
            className="action"
            data-testid="run-agent"
            disabled={agentPhase === "starting"}
            title={agentTool.script ?? undefined}
            onClick={() => void runAgentProposal()}
          >
            {agentPhase === "starting" ? "에이전트가 문서를 보는 중…" : "에이전트 제안 받기"}
          </button>
          <span className="tiny">
            에이전트 권한 연결로 계획만 냅니다. 승인과 적용은 그 연결에 아예 없는 기능입니다.
          </span>
        </div>
      ) : null}

      {agentRun ? (
        <div className="agent-result" data-testid="agent-result">
          <div className="head">
            <Tag tone="ok">제안 도착</Tag>
            <span className="mono tiny">{agentRun.door} · exit {agentRun.exitCode}</span>
          </div>
          <p className="said">
            <strong>{agentRun.proposer}</strong>이(가) 계획{" "}
            <span className="mono">{agentRun.planId.slice(0, 12)}</span> 을(를) 냈고, 승인은{" "}
            <strong>{agentRun.approvalState === "pending" ? "받지 못한 채" : agentRun.approvalState}</strong>{" "}
            멈췄습니다. 오른쪽 검토 대기열에서 사람이 직접 승인해야 합니다.
          </p>
          <p className="tiny">
            이 연결에 없는 기능:{" "}
            <span className="mono">{agentRun.neverCalled.join(", ")}</span>
          </p>
        </div>
      ) : null}

      {agentError ? (
        <div className="refusal" data-testid="agent-error">
          <Tag tone="bad">에이전트를 돌리지 못했습니다</Tag>
          <p className="prose">{agentError.message}</p>
          <p className="mono tiny">{agentError.code}</p>
        </div>
      ) : null}

      <div className="cards">
        {eventError ? (
          <div className="refusal">
            <Tag tone="bad">사건 기록을 구독하지 못했습니다</Tag>
            <p className="prose">{eventError.message}</p>
            <p className="mono tiny">{eventError.code}</p>
          </div>
        ) : null}
        {newestFirst.length === 0 ? (
          <p className="empty">아직 이 문서에 일어난 일이 없습니다.</p>
        ) : (
          newestFirst.map((event) => <EventCard key={event.seq} event={event} />)
        )}

        <details className="disclosure" data-testid="protocol-chatter">
          <summary>이 셸과 런타임이 주고받은 것 ({activity.length})</summary>
          <p className="prose tiny">
            위쪽은 문서에 일어난 일이고, 여기는 그 일을 하려고 오간 말입니다. 진단용입니다.
          </p>
          <ul className="chatter">
            {activity
              .slice(-60)
              .reverse()
              .map((item) => (
                <li key={item.seq} className="mono tiny">
                  +{(item.atMs / 1000).toFixed(1)}s {describeActivity(item)}
                </li>
              ))}
          </ul>
        </details>
      </div>
    </div>
  );
}
