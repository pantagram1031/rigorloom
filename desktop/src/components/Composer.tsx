/**
 * The instruction composer. Live since Phase 5, and honest about when it is not.
 *
 * Phase 4 shipped this disabled with a sentence saying there was nowhere to
 * send. That sentence is gone because the destination exists; what replaced it
 * is a set of sentences, one per reason a send would not work, because "the
 * button is grey" is not information. Each blocker names the missing thing and
 * offers the one control that fixes it.
 *
 * A real `<textarea>`, and Enter does NOT send while a syllable is composing.
 * Ctrl+Enter sends; bare Enter inserts a newline. Both halves of that matter:
 * pressing Enter to confirm a composing 두벌식 syllable is ordinary Korean
 * typing, and a composer that sent there would cut the instruction mid-word —
 * the same failure the inline seat editor was built around, in a box people
 * will type paragraphs into.
 */
import { useRef, useState } from "react";

import { sendInstruction } from "../actions";
import { activeStoreKey, composerBlocker, setState, useWorkspace } from "../store";

/** One sentence and one way out, per reason. Never a bare disabled control. */
function Blocked({ reason }: { reason: string }) {
  const provider = useWorkspace((s) => s.provider);
  const host = useWorkspace((s) => s.agentHost);
  const key = activeStoreKey(provider);
  const settings = (
    <button className="linkish" data-testid="composer-open-settings" onClick={() => setState({ settingsOpen: true })}>
      설정 열기
    </button>
  );

  switch (reason) {
    case "no_document":
      return <>문서를 먼저 열어야 합니다. 에이전트는 열려 있는 문서에만 손을 댑니다.</>;
    case "no_host":
      return (
        <>
          이 설치본에서 에이전트 호스트를 찾지 못했습니다. {host?.reason ?? ""} 저장소
          체크아웃에서 실행하거나 <span className="mono">RIGORLOOM_AGENT_HOST</span> 를
          지정하십시오.
        </>
      );
    case "busy":
      return <>앞의 지시를 아직 처리하고 있습니다. 한 번에 하나만 돕니다.</>;
    case "no_credential_name":
      return <>이 제공자에 쓸 자격 증명 이름이 비어 있습니다. {settings}</>;
    case "no_credential":
      return (
        <>
          이 기계의 자격 증명 저장소에 <span className="mono">{key}</span> 항목이 없습니다.
          열쇠 없이 유료 제공자를 부르지는 않습니다. {settings}
        </>
      );
    case "no_base_url":
      return <>커스텀 라우터의 주소가 비어 있습니다. {settings}</>;
    default:
      return <>지금은 보낼 수 없습니다.</>;
  }
}

export function Composer() {
  const blocker = useWorkspace(composerBlocker);
  const provider = useWorkspace((s) => s.provider.provider);
  const activeTurn = useWorkspace((s) => s.activeTurn);
  const [text, setText] = useState("");
  const composing = useRef(false);
  const field = useRef<HTMLTextAreaElement | null>(null);

  const canSend = blocker === null && text.trim() !== "";

  async function send() {
    if (!canSend) return;
    const instruction = text;
    setText("");
    const ok = await sendInstruction(instruction);
    // A refused send must not eat what the person wrote.
    if (!ok && getComposerEmpty(field.current)) setText(instruction);
  }

  return (
    <div className="composer" data-testid="composer">
      <textarea
        ref={field}
        data-testid="composer-input"
        value={text}
        disabled={blocker === "no_document" || blocker === "no_host"}
        placeholder={
          blocker === null
            ? "문서에 시킬 일을 여기에 씁니다. Ctrl+Enter 로 보냅니다."
            : "문서에 시킬 일을 여기에 씁니다."
        }
        aria-describedby="composer-note"
        onChange={(e) => setText(e.target.value)}
        onCompositionStart={() => {
          composing.current = true;
        }}
        onCompositionEnd={() => {
          composing.current = false;
        }}
        onKeyDown={(e) => {
          // Never while a syllable is still being built. `isComposing` is the
          // browser's own answer; the ref is the fallback for the one WebView2
          // path that fires keydown after compositionend without the flag.
          if (e.nativeEvent.isComposing || composing.current) return;
          if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
            e.preventDefault();
            void send();
          }
        }}
      />
      <div className="composer-actions">
        <span className="tiny mono" data-testid="composer-provider">
          {provider}
        </span>
        <span className="spacer" />
        <button
          className="action primary"
          data-testid="composer-send"
          disabled={!canSend}
          title="Ctrl+Enter"
          onClick={() => void send()}
        >
          {activeTurn ? "보내는 중…" : "보내기"}
        </button>
      </div>
      <p className="note" id="composer-note" data-testid="composer-note">
        {blocker === null ? (
          <>
            에이전트는 계획만 냅니다. 승인과 적용은 에이전트 연결에 아예 없는 기능이라,
            사람이 대기열에서 직접 승인해야 문서에 닿습니다.
          </>
        ) : (
          <Blocked reason={blocker} />
        )}
      </p>
    </div>
  );
}

/** Whether the field is still empty, so restoring a refused draft is safe. */
function getComposerEmpty(field: HTMLTextAreaElement | null): boolean {
  return !field || field.value.trim() === "";
}
