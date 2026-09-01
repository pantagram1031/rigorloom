/**
 * The persistent instruction composer, present and honestly disabled.
 *
 * It is here because product direction §4 makes it part of Agent view, and it
 * is disabled because there is no agent host to send anything to. A composer
 * that accepted text and silently dropped it would be worse than no composer.
 */
export function Composer() {
  return (
    <div className="composer" data-testid="composer">
      <textarea
        disabled
        data-testid="composer-input"
        placeholder="문서에 시킬 일을 여기에 씁니다."
        aria-describedby="composer-note"
      />
      <p className="note" id="composer-note">
        아직 보낼 곳이 없습니다. 에이전트를 붙이는 일은 다음 단계입니다. 그때까지 이 칸은
        잠겨 있습니다.
      </p>
    </div>
  );
}
