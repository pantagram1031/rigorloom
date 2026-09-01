/**
 * 작업 팩 — the distribution modules this installation declares.
 *
 * A SEED, and it says so. The user asked for report-writing features; the
 * pipeline UI is a later slice. What exists today is real and worth showing:
 * six modules are declared on disk, each contributing named checkers and CLI
 * commands, and `report` really does depend on `style` and really is refused
 * without it. So the list is the registry's own answer and the detail panel is
 * an honest 준비 중 — what the pack will do, and what of it exists now, with
 * the actual contribution names beside it.
 *
 * NO FAKE WORKFLOW UI. There is no "run this pack" button, because there is no
 * method behind one: the Runtime protocol has no way to run a module's checker
 * against a session, and drawing the control first is how a product acquires a
 * surface it then has to keep honest.
 */
import { setState, useWorkspace } from "../store";
import type { TaskPack } from "../types";
import { Tag } from "./Tag";

/** What each pack will do once there is a way to run it. Intent, marked as such. */
const PLANNED: Record<string, string> = {
  report:
    "주제에서 제출본까지를 단계로 나눠 진행하고, 단계마다 아래 검사기를 게이트로 겁니다. 지금 이 앱이 할 수 있는 것은 문서 한 칸을 고쳐 승인·적용·영수증까지 남기는 데까지입니다.",
  gongmun: "공문 서식의 필수 항목과 표기 규칙을 채움 자리 검사에 얹습니다.",
  grant: "지원 사업 양식의 분량 제한과 항목 누락을 제출 전에 잡습니다.",
  hr: "인사 서식의 항목·표기 규칙을 검사에 얹습니다.",
  minwon: "민원 회신문의 구조와 어투를 검사에 얹습니다.",
  style: "본문 문체를 검사하고, 번역투를 걷어내는 윤문을 겁니다.",
};

function PackDetail({ pack }: { pack: TaskPack }) {
  return (
    <div className="pack-detail" data-testid="pack-detail">
      <div className="head">
        <h3>{pack.title}</h3>
        <Tag tone="none">준비 중</Tag>
      </div>
      <p className="prose">{PLANNED[pack.name] ?? pack.blurb}</p>

      <h4>지금 이 설치본에 실제로 있는 것</h4>
      <ul className="tiny">
        <li>
          선언 상태:{" "}
          {pack.enabled ? (
            <>
              <Tag tone="ok">켜짐</Tag> <span className="mono">modules/enabled.yaml</span> 에
              들어 있습니다
            </>
          ) : (
            <>
              <Tag tone="none">꺼짐</Tag> 디스크에는 있지만 켜져 있지 않습니다
            </>
          )}
        </li>
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

      <h4>아직 없는 것</h4>
      <p className="prose tiny">
        이 앱에서 저 검사기를 돌리는 방법이 없습니다. 런타임 프로토콜에 모듈 검사기를
        세션에 대해 실행하는 메서드가 아직 없어서, 버튼을 먼저 그리지 않았습니다.
      </p>
      <button className="action" data-testid="pack-close" onClick={() => setState({ packOpen: null })}>
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
              onClick={() => setState({ packOpen: pack.name === open ? null : pack.name })}
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
          이 목록은 <span className="mono">modules/enabled.yaml</span> 과 각 팩의 선언에서
          그대로 읽은 것입니다. 아직 여기서 돌릴 수 있는 것은 없습니다.
        </p>
      ) : null}
    </div>
  );
}
