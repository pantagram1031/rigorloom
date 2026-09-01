/**
 * Agent view, centre: what the runtime actually did, as calm cards.
 *
 * Two rules from the audit are load-bearing here.
 *
 * *Cards summarize document work, not raw JSON or shell logs* (product
 * direction §4) — so each card leads with a Korean sentence and the technical
 * frame sits behind a disclosure.
 *
 * *Receipts render as receipts* — argv, exit code, digest — because that is
 * what makes a timeline evidence rather than narration. Nothing in this build
 * emits a receipt yet, so no receipt card is faked.
 *
 * The source is the batched activity channel: notifications and stderr lines
 * counted in Rust and delivered as arrays (spike finding 2). The workspace
 * `events.jsonl` stream is NOT here, and cannot be: `event/subscribe` is GAP.
 * The panel says so rather than presenting protocol chatter as if it were the
 * document's history.
 */
import { useWorkspace } from "../store";
import type { Activity } from "../types";
import { Tag } from "./Tag";

function describe(item: Activity): { title: string; tone: "ok" | "warn" | "none"; said: string } {
  if (item.kind === "lifecycle") {
    return { title: "런타임", tone: "none", said: item.text ?? "" };
  }
  if (item.kind === "log") {
    const text = item.text ?? "";
    const bad = /error|traceback|refus|fail/i.test(text);
    return { title: "런타임 기록", tone: bad ? "warn" : "none", said: text };
  }
  const frame = item.frame as { kind?: string; method?: string } | null;
  const method = frame?.method ?? frame?.kind ?? "알림";
  return { title: "알림", tone: "none", said: `${method}` };
}

function Card({ item }: { item: Activity }) {
  const { title, tone, said } = describe(item);
  const seconds = (item.atMs / 1000).toFixed(1);
  return (
    <article className="card">
      <div className="head">
        <Tag tone={tone}>{title}</Tag>
        <span className="when">+{seconds}초</span>
      </div>
      <p className="said">{said}</p>
      {item.frame ? (
        <details>
          <summary>원본 프레임</summary>
          <pre>{JSON.stringify(item.frame, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

export function Timeline() {
  const activity = useWorkspace((s) => s.activity);
  const recent = activity.slice(-120).reverse();

  return (
    <div className="timeline" data-testid="timeline">
      <div className="panel-head">
        <span className="panel-title">기록</span>
        <span className="count" data-testid="activity-count">
          {activity.length}
        </span>
      </div>
      <div className="cards">
        {recent.length === 0 ? (
          <p className="empty">아직 기록이 없습니다.</p>
        ) : (
          recent.map((item) => <Card key={item.seq} item={item} />)
        )}
        <p className="empty">
          여기 보이는 것은 이 셸과 런타임이 주고받은 내용입니다. 작업 폴더의 사건
          기록(events.jsonl)은 아직 못 읽습니다 — 런타임에 구독하는 방법이 없습니다.
        </p>
      </div>
    </div>
  );
}
