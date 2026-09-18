/**
 * 에이전트 tab: a chat with a plan-aware assistant.
 *
 * User bubbles sit on the right, agent bubbles on the left. Tool/protocol
 * events collapse into one expandable step row per turn. A plan arrival is a
 * compact card that sends the person to 검토. NOTHING HERE CAN APPROVE.
 */
import { runAgentProposal, stopInstruction } from "../actions";
import { selectInspectorTab, setState, useWorkspace } from "../store";
import type { HostEvent, Turn } from "../types";
import { EmptyIconChat, EmptyState } from "./EmptyState";
import { Icon } from "./Icon";
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
  "runtime.refused": (d) => `엔진이 거절했습니다 — ${String(d.message ?? d.code ?? "")}`,
  "host.note": (d) => String(d.message ?? ""),
  "run.finished": (d) => (d.ok === true ? "지시를 마쳤습니다" : "여기서 멈췄습니다"),
};

const SYSTEM_KINDS = new Set([
  "tool.requested",
  "tool.refused",
  "tool.compiled",
  "runtime.result",
  "runtime.refused",
  "host.note",
]);

function describe(event: HostEvent): string {
  return SAID[event.kind]?.(event.detail ?? {}) ?? event.kind;
}

function progressLine(turn: Turn): string {
  const newest = turn.events[turn.events.length - 1];
  if (!newest) return "에이전트 호스트를 띄우는 중…";
  return describe(newest);
}

function assistantText(turn: Turn): string {
  const chunks = turn.events
    .filter((event) => event.kind === "provider.stream.chunk")
    .map((event) => String((event.detail ?? {}).text ?? ""));
  if (chunks.length > 0) return chunks.join("");
  return turn.payload?.closingText ?? "";
}

function ToolIcon() {
  return <Icon name="bot" className="system-icon" />;
}

function PlanArrivalCard({
  count,
  planHash,
  testId,
}: {
  count: number;
  planHash?: string | null;
  testId: string;
}) {
  return (
    <div className="plan-arrival-wrap">
      <button
        type="button"
        className="plan-arrival"
        data-testid={testId}
        onClick={() => selectInspectorTab("review")}
      >
        계획 {count}건 · 검토에서 보기
      </button>
      {planHash ? (
        <span className="mono tiny" hidden data-testid="plan-arrival-hash">
          {planHash}
        </span>
      ) : null}
    </div>
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
          </div>

          {turn.phase === "starting" ? (
            <p className="progress" data-testid="turn-progress">
              <i className="pulse" aria-hidden="true" />
              {progressLine(turn)}
            </p>
          ) : null}

          {system.length > 0 ? (
            <details className="disclosure turn-steps" data-testid={`turn-steps-${turn.id}`}>
              <summary>{system.length}단계 작업</summary>
              {system.map((event) => (
                <p key={event.seq} className="system-row" data-testid={`system-row-${event.seq}`}>
                  <ToolIcon />
                  <span>{describe(event)}</span>
                </p>
              ))}
            </details>
          ) : null}

          {said ? (
            <div className="bubble bubble-agent" data-testid="turn-said">
              <p>{said}</p>
            </div>
          ) : null}

          {fault ? (
            <div className="refusal" data-testid="turn-fault">
              <p className="prose">{String(fault.message ?? "")}</p>
              <p className="tiny">문서에 대한 판정이 아닙니다.</p>
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
            </div>
          ) : null}

          {payload?.plan ? (
            <>
              <PlanArrivalCard
                count={planOps}
                planHash={payload.plan.planHash}
                testId={`plan-arrival-${turn.id}`}
              />
              <p className="gate" hidden data-testid="turn-gate">
                승인은 사람이 합니다.
              </p>
            </>
          ) : null}

          {payload ? (
            <p className="tiny" hidden data-testid="turn-never">
              이 연결에 없는 기능:{" "}
              <span className="mono">{payload.neverCompiled.join(", ")}</span>
            </p>
          ) : null}

          <details className="disclosure">
            <summary>기술 정보</summary>
            <p className="tiny">
              {turn.provider}
              {payload?.provider?.model ? ` · ${payload.provider.model}` : ""}
              {payload ? ` · ${payload.turns}턴` : ""}
              {turn.exitCode !== null ? ` · exit ${turn.exitCode}` : ""}
            </p>
            <p className="tiny">단계 {compiled.length}건 · 기록 {turn.events.length}</p>
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
          <div data-testid="composer-note">
            <EmptyState
              testId="conversation-empty"
              icon={<EmptyIconChat />}
              title="아직 시킨 일이 없습니다"
              body="에이전트는 계획만 냅니다. 승인은 사람이 합니다."
            />
          </div>
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
        </div>
      ) : null}

      {agentRun ? (
        <div className="agent-result" data-testid="agent-result">
          <div className="head">
            <Tag tone="ok">제안 도착</Tag>
          </div>
          <PlanArrivalCard count={queued} testId="plan-arrival-mock" />
          <p className="said">
            <strong>{agentRun.proposer}</strong>이(가) 계획을 냈고, 승인은{" "}
            <strong>
              {agentRun.approvalState === "pending" ? "받지 못한 채" : agentRun.approvalState}
            </strong>{" "}
            멈췄습니다.
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
