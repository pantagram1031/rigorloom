/**
 * 에이전트 tab: a chat with a plan-aware assistant.
 *
 * User bubbles sit on the right, agent bubbles on the left, and tool/plan
 * events are compact system rows. A plan arrival is a card that sends the
 * person to 검토 — this host still cannot approve. NOTHING HERE CAN APPROVE.
 *
 * STREAMING, HONESTLY. `provider.stream.chunk` is rendered when it arrives, but
 * `AgentHost.run` only ever calls `provider.complete()`, so assistant text
 * still arrives in one piece. Drawing a fake typing animation would be the
 * exact dishonesty this application is built to avoid.
 */
import { runAgentProposal, stopInstruction } from "../actions";
import { selectInspectorTab, setState, useWorkspace } from "../store";
import type { HostEvent, Turn } from "../types";
import { EmptyIconChat, EmptyState } from "./EmptyState";
import { Tag } from "./Tag";

/** Korean product language for each Agent Host event kind. Closed set. */
const SAID: Record<string, (d: Record<string, unknown>) => string> = {
  "run.started": () => "지시를 받았습니다",
  "provider.selected": (d) => {
    const provider = (d.provider ?? {}) as Record<string, unknown>;
    return `모델 쪽 준비 — ${String(provider.providerId ?? "")} ${String(provider.model ?? "")}`;
  },
  "provider.request": (d) => `모델에 물었습니다 (${String(d.turn ?? "?")}번째)`,
  "provider.response": (d) => {
    const calls = (d.toolCalls as unknown[]) ?? [];
    return calls.length === 0
      ? "모델이 답했습니다"
      : `모델이 ${calls.length}건을 하겠다고 했습니다`;
  },
  "provider.failed": (d) => `모델 쪽이 실패했습니다 — ${String(d.message ?? d.code ?? "")}`,
  "provider.stream.chunk": () => "모델이 글자를 흘려보내는 중",
  "tool.requested": (d) => `${String(d.name ?? "")} 를 요청했습니다`,
  "tool.refused": (d) => `막았습니다 — ${String(d.message ?? d.code ?? "")}`,
  "tool.compiled": (d) => `${String(d.method ?? "")} 로 옮겼습니다`,
  "runtime.result": (d) => `${String(d.tool ?? "")} 가 돌아왔습니다`,
  "runtime.refused": (d) => `런타임이 거절했습니다 — ${String(d.message ?? d.code ?? "")}`,
  "host.note": (d) => String(d.message ?? ""),
  "run.finished": (d) => (d.ok === true ? "지시를 마쳤습니다" : "여기서 멈췄습니다"),
};

const SYSTEM_KINDS = new Set([
  "tool.requested",
  "tool.refused",
  "tool.compiled",
  "runtime.result",
  "runtime.refused",
]);

function describe(event: HostEvent): string {
  return SAID[event.kind]?.(event.detail ?? {}) ?? event.kind;
}

/** What the run is doing right now, from the newest event it has emitted. */
function progressLine(turn: Turn): string {
  const newest = turn.events[turn.events.length - 1];
  if (!newest) return "에이전트 호스트를 띄우는 중…";
  return describe(newest);
}

/**
 * Assistant text as it exists. When chunks arrived, they are joined; otherwise
 * the turn's closing text is what there is. No placeholder either way.
 */
function assistantText(turn: Turn): string {
  const chunks = turn.events
    .filter((event) => event.kind === "provider.stream.chunk")
    .map((event) => String((event.detail ?? {}).text ?? ""));
  if (chunks.length > 0) return chunks.join("");
  return turn.payload?.closingText ?? "";
}

function ToolIcon() {
  return (
    <svg className="system-icon" width="12" height="12" viewBox="0 0 12 12" aria-hidden="true">
      <circle cx="6" cy="6" r="4.5" fill="none" stroke="currentColor" strokeWidth="1.2" />
      <path d="M6 3.8v2.4M6 8.2h.01" fill="none" stroke="currentColor" strokeWidth="1.2" />
    </svg>
  );
}

function PlanArrivalCard({
  count,
  testId,
}: {
  count: number;
  testId: string;
}) {
  return (
    <button
      type="button"
      className="plan-arrival"
      data-testid={testId}
      onClick={() => selectInspectorTab("review")}
    >
      계획 {count}개 편집 도착 → 검토 탭에서 승인
    </button>
  );
}

function TurnCard({ turn }: { turn: Turn }) {
  const payload = turn.payload;
  const compiled = turn.events.filter((event) => event.kind === "tool.compiled");
  const refused = turn.events.filter(
    (event) => event.kind === "tool.refused" || event.kind === "runtime.refused",
  );
  const system = turn.events.filter((event) => SYSTEM_KINDS.has(event.kind));
  const fault = payload?.providerFault ?? null;
  const said = assistantText(turn);
  const planOps = payload?.plan?.ops.length ?? 0;

  return (
    <article className="turn" data-testid={`turn-${turn.id}`}>
      <div className="bubble-row is-user">
        <div className="bubble bubble-user" data-testid="turn-instruction">
          <p>{turn.instruction}</p>
        </div>
      </div>

      <div className="bubble-row is-agent">
        <div className="answered">
          <div className="head">
            {turn.phase === "starting" ? (
              <Tag tone="fill">일하는 중</Tag>
            ) : fault ? (
              <Tag tone="bad">모델 쪽 문제</Tag>
            ) : turn.error ? (
              <Tag tone="bad">돌리지 못했습니다</Tag>
            ) : payload?.plan ? (
              <Tag tone="ok">제안 도착</Tag>
            ) : (
              <Tag tone="none">제안 없음</Tag>
            )}
            <span className="when mono">
              {turn.provider}
              {payload?.provider?.model ? ` · ${payload.provider.model}` : ""}
              {payload ? ` · ${payload.turns}턴` : ""}
              {turn.exitCode !== null ? ` · exit ${turn.exitCode}` : ""}
            </span>
          </div>

          {turn.phase === "starting" ? (
            <p className="progress" data-testid="turn-progress">
              <i className="pulse" aria-hidden="true" />
              {progressLine(turn)}
            </p>
          ) : null}

          {system.map((event) => (
            <p key={event.seq} className="system-row" data-testid={`system-row-${event.seq}`}>
              <ToolIcon />
              <span>{describe(event)}</span>
            </p>
          ))}

          {said ? (
            <div className="bubble bubble-agent" data-testid="turn-said">
              <p>{said}</p>
            </div>
          ) : null}

          {fault ? (
            <div className="refusal" data-testid="turn-fault">
              <p className="prose">{String(fault.message ?? "")}</p>
              <p className="mono tiny">{String(fault.code ?? "")}</p>
              <p className="tiny">
                문서에 대한 판정이 아닙니다. 계획과 승인 상태는 그대로입니다.
              </p>
            </div>
          ) : null}

          {turn.error ? (
            <div className="refusal" data-testid="turn-error">
              <p className="prose">{turn.error.message}</p>
              <p className="mono tiny">{turn.error.code}</p>
            </div>
          ) : null}

          {refused.length > 0 ? (
            <div className="refusal" data-testid="turn-refused">
              <Tag tone="warn">{refused.length}건을 문 앞에서 막았습니다</Tag>
              <ul className="tiny">
                {refused.map((event) => (
                  <li key={event.seq} className="mono">
                    {String((event.detail ?? {}).code ?? event.kind)} —{" "}
                    {String((event.detail ?? {}).message ?? "")}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}

          {payload?.plan ? (
            <>
              <PlanArrivalCard count={planOps} testId={`plan-arrival-${turn.id}`} />
              <p className="gate" data-testid="turn-gate">
                계획 <span className="mono">{payload.plan.planId.slice(0, 12)}</span> 을(를) 냈고,{" "}
                {turn.planId ? (
                  <>
                    승인은 <strong>받지 못한 채</strong> 멈췄습니다. 오른쪽 검토 대기열에서 사람이
                    직접 승인해야 합니다.
                  </>
                ) : turn.error ? (
                  <>
                    검토 대기열에 넣지 <strong>못했습니다.</strong> 위 오류를 확인한 뒤 다시 요청해야
                    합니다.
                  </>
                ) : (
                  <>
                    도착하는 동안 문서나 검토 대기열이 바뀌어 <strong>대기열에는 넣지 않았습니다.</strong>{" "}
                    현재 상태에서 다시 요청해야 합니다.
                  </>
                )}
              </p>
            </>
          ) : null}

          {payload ? (
            <p className="tiny" data-testid="turn-never">
              이 연결에 아예 없는 기능:{" "}
              <span className="mono">{payload.neverCompiled.join(", ")}</span>
            </p>
          ) : null}

          <details className="disclosure">
            <summary>
              무엇을 했는지 ({compiled.length}건) · 원본 기록 ({turn.events.length})
            </summary>
            <ul className="chatter">
              {turn.events.map((event) => (
                <li key={event.seq} className="tiny">
                  <span className="mono">#{event.seq}</span> {describe(event)}
                </li>
              ))}
            </ul>
            <pre>{JSON.stringify(turn.payload ?? turn.events, null, 2)}</pre>
          </details>
        </div>
      </div>
    </article>
  );
}

export function Conversation() {
  const turns = useWorkspace((s) => s.turns);
  const activeTurn = useWorkspace((s) => s.activeTurn);
  const agentTool = useWorkspace((s) => s.agentTool);
  const agentPhase = useWorkspace((s) => s.agentPhase);
  const agentError = useWorkspace((s) => s.agentError);
  const agentRun = useWorkspace((s) => s.agentRun);
  const sessionId = useWorkspace((s) => s.activeSessionId);
  const hostReady = useWorkspace((s) => s.agentHost?.available === true);
  const queued = useWorkspace((s) => s.draft?.ops?.length ?? 0);

  return (
    <div className="conversation" data-testid="conversation">
      {turns.length === 0 ? (
        hostReady ? (
          <EmptyState
            testId="conversation-empty"
            icon={<EmptyIconChat />}
            title="아직 시킨 일이 없습니다"
            body="아래 칸에 문서로 할 일을 쓰면 에이전트가 계획을 냅니다."
          />
        ) : (
          <EmptyState
            testId="conversation-empty"
            icon={<EmptyIconChat />}
            title="에이전트가 연결되어 있지 않습니다"
            body="설정에서 에이전트 호스트를 연결하면 지시를 보낼 수 있습니다."
            action={{ label: "설정 열기", onClick: () => setState({ settingsOpen: true }) }}
          />
        )
      ) : (
        turns.map((turn) => <TurnCard key={turn.id} turn={turn} />)
      )}

      {activeTurn ? (
        <button className="action" data-testid="stop-turn" onClick={() => void stopInstruction()}>
          멈추기
        </button>
      ) : null}

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
            지시 없이, 내장 목 에이전트가 뻔한 한 칸을 채워 봅니다. 위 대화와 같은 대기열로
            들어갑니다.
          </span>
        </div>
      ) : null}

      {agentRun ? (
        <div className="agent-result" data-testid="agent-result">
          <div className="head">
            <Tag tone="ok">제안 도착</Tag>
            <span className="mono tiny">
              {agentRun.door} · exit {agentRun.exitCode}
            </span>
          </div>
          <PlanArrivalCard count={queued} testId="plan-arrival-mock" />
          <p className="said">
            <strong>{agentRun.proposer}</strong>이(가) 계획{" "}
            <span className="mono">{agentRun.planId.slice(0, 12)}</span> 을(를) 냈고, 승인은{" "}
            <strong>
              {agentRun.approvalState === "pending" ? "받지 못한 채" : agentRun.approvalState}
            </strong>{" "}
            멈췄습니다. 오른쪽 검토 대기열에서 사람이 직접 승인해야 합니다.
          </p>
          <p className="tiny">
            이 연결에 없는 기능: <span className="mono">{agentRun.neverCalled.join(", ")}</span>
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
    </div>
  );
}
