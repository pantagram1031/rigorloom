/**
 * Agent view — for working through the agent.
 *
 * left: the open documents and the 작업 팩 · centre: the conversation and the
 * composer, with the document's own history behind the second tab ·
 * right: the document as context · bottom: the same verification bar.
 *
 * Same store, different arrangement. The verification bar is deliberately the
 * same component with the same props: proof state has one home, and it must
 * read identically wherever the user is standing.
 *
 * WHY TWO TABS AND NOT TWO STACKED PANES. Phase 5 gave the centre a second
 * thing to hold, and the two are different kinds of record: the conversation is
 * what a person and an agent said, and `문서 기록` is the session's own
 * `events.jsonl` — appended by the Runtime, replayed from the beginning,
 * authoritative. Interleaving them would make the document's history untrue,
 * and stacking them would halve both. The tab lives in the store like every
 * other piece of navigation, so switching views does not lose it.
 */
import { Composer } from "../components/Composer";
import { Conversation } from "../components/Conversation";
import { DocumentContext } from "../components/DocumentContext";
import { Findings } from "../components/Findings";
import { ReceiptPanel } from "../components/ReceiptPanel";
import { SessionList } from "../components/SessionList";
import { Timeline } from "../components/Timeline";
import { VerificationBar } from "../components/VerificationBar";
import {
  activeCandidates,
  activeInspect,
  activeSession,
  setState,
  useWorkspace,
} from "../store";

function CentreTabs() {
  const tab = useWorkspace((s) => s.agentTab);
  const turns = useWorkspace((s) => s.turns.length);
  const events = useWorkspace((s) => s.events.length);
  return (
    <div className="tabs" role="tablist" aria-label="가운데 화면">
      <button
        role="tab"
        aria-selected={tab === "conversation"}
        data-testid="tab-conversation"
        onClick={() => setState({ agentTab: "conversation" })}
      >
        대화 <span className="count">{turns}</span>
      </button>
      <button
        role="tab"
        aria-selected={tab === "history"}
        data-testid="tab-history"
        onClick={() => setState({ agentTab: "history" })}
      >
        문서 기록 <span className="count">{events}</span>
      </button>
    </div>
  );
}

export function AgentView({
  onOpen,
  onSelectSession,
}: {
  onOpen: () => void;
  onSelectSession: (sessionId: string) => void;
}) {
  const inspect = useWorkspace(activeInspect);
  const session = useWorkspace(activeSession);
  const candidates = useWorkspace(activeCandidates);
  const tab = useWorkspace((s) => s.agentTab);

  return (
    <div className="view view-agent" data-testid="view-agent">
      <div className="columns stagger">
        <SessionList onSelect={onSelectSession} onOpen={onOpen} />

        <main className="panel center" aria-label="작업">
          <CentreTabs />
          {tab === "conversation" ? <Conversation /> : <Timeline />}
          <Composer />
        </main>

        <DocumentContext />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
      {/* The same sheets. A check or a receipt opened in either view is
          readable in both, because there is one Workspace and one of each. */}
      <Findings />
      <ReceiptPanel />
    </div>
  );
}
