/**
 * Agent view — for working through the agent.
 *
 * left: the open documents · centre: the timeline and the composer ·
 * right: the document as context · bottom: the same verification bar.
 *
 * Same store, different arrangement. The verification bar is deliberately the
 * same component with the same props: proof state has one home, and it must
 * read identically wherever the user is standing.
 */
import { Composer } from "../components/Composer";
import { DocumentContext } from "../components/DocumentContext";
import { Findings } from "../components/Findings";
import { SessionList } from "../components/SessionList";
import { Timeline } from "../components/Timeline";
import { VerificationBar } from "../components/VerificationBar";
import { activeCandidates, activeInspect, activeSession, useWorkspace } from "../store";

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

  return (
    <div className="view view-agent" data-testid="view-agent">
      <div className="columns stagger">
        <SessionList onSelect={onSelectSession} onOpen={onOpen} />

        <main className="panel center" aria-label="작업 기록">
          <Timeline />
          <Composer />
        </main>

        <DocumentContext session={session} inspect={inspect} candidates={candidates} />
      </div>

      <VerificationBar session={session} inspect={inspect} candidates={candidates} />
      {/* The same sheet. A check run from either view is readable in both. */}
      <Findings />
    </div>
  );
}
