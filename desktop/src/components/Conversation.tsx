/**
 * Agent view, centre: the conversation, as calm cards.
 *
 * One card per turn, and a turn is one Agent Host process. What it shows, in
 * the order a person reads it:
 *
 *   the instruction, verbatim   what was asked
 *   what the agent said         `closingText`, the provider's own words
 *   what it did                 the compiled tool calls, as one line each
 *   where it stopped            the gate, always, because it always stops
 *   원본 기록                    every raw event, behind a disclosure
 *
 * THE TECHNICAL DETAIL IS BEHIND THE DISCLOSURE AND THE OUTCOME IS NOT. A card
 * that led with `tool.compiled plan/propose` would be a log; a card that hid
 * the tool calls entirely would be unauditable. Both are on screen and only one
 * of them is unfolded.
 *
 * NOTHING HERE CAN APPROVE, and the card says so in words rather than leaving
 * it to be inferred from the absence of a button. `neverCompiled` comes from
 * the host's own payload — the host-only methods its compile gate will never
 * emit — so the sentence is a quotation, not a claim this component makes.
 *
 * STREAMING, HONESTLY. `provider.stream.chunk` is a declared event kind and
 * this renders it when it arrives, but `AgentHost.run` only ever calls
 * `provider.complete()`: no adapter's `stream()` is reached through `host.py`
 * today, so a provider whose profile says `streaming: yes` still delivers its
 * text in one piece at the end of a turn. The card therefore streams the
 * host's PROGRESS — its events arrive live while the process runs — and says
 * plainly that the assistant text does not. Drawing a fake typing animation
 * over a batch response would be the exact dishonesty this application is
 * built to avoid. Recorded as agenthost gap 1 in the README.
 */
import { runAgentProposal, stopInstruction } from "../actions";
import { useWorkspace } from "../store";
import type { HostEvent, Turn } from "../types";
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

function TurnCard({ turn }: { turn: Turn }) {
  const payload = turn.payload;
  const compiled = turn.events.filter((event) => event.kind === "tool.compiled");
  const refused = turn.events.filter(
    (event) => event.kind === "tool.refused" || event.kind === "runtime.refused",
  );
  const fault = payload?.providerFault ?? null;
  const said = assistantText(turn);

  return (
    <article className="turn" data-testid={`turn-${turn.id}`}>
      <div className="asked" data-testid="turn-instruction">
        <span className="who latin-caps">you</span>
        <p>{turn.instruction}</p>
      </div>

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

        {said ? (
          <p className="said" data-testid="turn-said">
            {said}
          </p>
        ) : null}

        {/* A provider fault is a PROVIDER fault. It never becomes a statement
            about the document, and the plan state is left exactly as far as
            the run actually got — which is what `ah_host` guarantees on its
            side and what this refuses to blur on ours. */}
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
          <p className="gate" data-testid="turn-gate">
            계획 <span className="mono">{payload.plan.planId.slice(0, 12)}</span> 을(를) 냈고,{" "}
            {turn.planId ? (
              <>
                승인은 <strong>받지 못한 채</strong> 멈췄습니다. 오른쪽 검토 대기열에서 사람이
                직접 승인해야 합니다.
              </>
            ) : (
              <>
                도착하는 동안 문서나 검토 대기열이 바뀌어 <strong>대기열에는 넣지 않았습니다.</strong>{" "}
                현재 상태에서 다시 요청해야 합니다.
              </>
            )}
          </p>
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

  return (
    <div className="conversation" data-testid="conversation">
      {turns.length === 0 ? (
        <p className="empty" data-testid="conversation-empty">
          아직 시킨 일이 없습니다. 아래 칸에 문서로 할 일을 쓰면, 에이전트가 문서를 살펴보고
          계획을 냅니다. 계획은 사람이 승인해야만 문서에 닿습니다.
        </p>
      ) : (
        turns.map((turn) => <TurnCard key={turn.id} turn={turn} />)
      )}

      {activeTurn ? (
        <button className="action" data-testid="stop-turn" onClick={() => void stopInstruction()}>
          멈추기
        </button>
      ) : null}

      {/* The dev-mode mock agent, unchanged in substance and moved here from
          the document-history pane: it is a thing an agent does, not a thing
          that happened to the document. Present only where its script is
          reachable — a shipped installation without a checkout does not show
          a button that cannot work. */}
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
