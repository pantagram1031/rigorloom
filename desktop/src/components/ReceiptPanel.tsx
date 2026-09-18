/**
 * 영수증 보기 — a human summary first, then what changed, who approved, files,
 * and the full JSON under 기술 정보.
 */
import { openReceipt } from "../actions";
import { formatBytes, humanCellAddress, quoteKo, shortHash, stampWhen } from "../label";
import { showToast, useWorkspace } from "../store";
import type { Receipt } from "../types";
import { Tag } from "./Tag";
import { Button } from "../ui/Button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/Card";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "../ui/Collapsible";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "../ui/Sheet";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/Table";
import { Tooltip } from "../ui/Tooltip";

function stepTitle(step: { kind: string; result?: unknown; subcommand?: string }): string {
  const result =
    step.result && typeof step.result === "object"
      ? (step.result as Record<string, unknown>)
      : {};
  if (step.kind === "fill_cell") {
    if (typeof result.table === "number" && typeof result.row === "number" && typeof result.col === "number") {
      return `${humanCellAddress(result.table, result.row, result.col)}에 값 넣기`;
    }
    return "칸에 값 넣기";
  }
  if (step.kind === "replace_all") {
    const find = String(result.find ?? "");
    const next = String(result.replace ?? "");
    if (find || next) return `${quoteKo(find)}을 ${quoteKo(next)}로 바꾸기`;
    return "글 바꾸기";
  }
  if (step.kind === "insert_text") return "한 문장 넣기";
  if (step.kind === "goto_text") return "자리로 이동";
  if (step.kind === "set_run") return "문단 바꾸기";
  return step.subcommand || step.kind;
}

function copyValue(value: string): void {
  const clip = navigator.clipboard;
  if (!clip) {
    showToast("복사하지 못했습니다", 1400);
    return;
  }
  void clip.writeText(value).then(
    () => showToast("복사했습니다", 1400),
    () => showToast("복사하지 못했습니다", 1400),
  );
}

function CopyHash({ value, testId }: { value: string; testId?: string }) {
  return (
    <span className="hash-copy">
      <Tooltip content={value}>
        <span className="mono hash">{shortHash(value)}</span>
      </Tooltip>
      <Tooltip content="복사">
        <Button variant="link" data-testid={testId} onClick={() => copyValue(value)}>
          복사
        </Button>
      </Tooltip>
    </span>
  );
}

function Checks({ receipt }: { receipt: Receipt }) {
  const report = receipt.checks;
  return (
    <div className="receipt-block">
      <h4>검사</h4>
      <div className="receipt-verdict">
        {report.acceptance ? (
          <Tag tone="ok">받아들일 수 있음</Tag>
        ) : (
          <span data-testid="receipt-acceptance-refusal">
            <Tag tone="warn">받아들일 수 없음</Tag>
          </span>
        )}
        {report.ranAll ? (
          <Tag tone="ok">필수 검사 모두 실행됨</Tag>
        ) : (
          <Tag tone="bad">실행되지 않은 필수 검사 있음</Tag>
        )}
      </div>
      {report.reason ? <p className="prose">{report.reason}</p> : null}
      {receipt.residue ? (
        <dl className="kv" data-testid="receipt-residue">
          <dt>판정 기준</dt>
          <dd className="mono">
            {receipt.residue.profileSource === "bound_form"
              ? `연결된 양식${receipt.residue.sha256 ? ` (${receipt.residue.sha256.slice(0, 12)})` : ""}`
              : receipt.residue.profileSource === "self_derived"
                ? "문서 자체 추정"
                : receipt.residue.profileSource}
          </dd>
          {receipt.residue.declaration?.keep && receipt.residue.declaration.keep.length > 0 ? (
            <>
              <dt>남긴 항목</dt>
              <dd data-testid="receipt-declaration-keep">
                {receipt.residue.declaration.keep.join(", ")}
              </dd>
            </>
          ) : null}
        </dl>
      ) : null}
      <ul className="receipt-checks">
        {report.checks.map((row) => (
          <li key={String(row.checker)} data-testid={`receipt-check-${row.checker}`}>
            <span className="mono">{String(row.checker)}</span>
            {row.state === "ran" ? (
              row.ok === true ? (
                <Tag tone="ok">걸림 없음</Tag>
              ) : (
                <Tag tone="bad">걸림 있음</Tag>
              )
            ) : (
              <Tag tone="none">실행 안 됨</Tag>
            )}
            {row.state !== "ran" && row.reason ? (
              <span className="dim">{String(row.reason)}</span>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

function summaryLine(receipt: Receipt): string {
  const when = stampWhen(receipt.approval.resolvedUtc ?? receipt.createdUtc);
  const who = receipt.approval.approver ?? receipt.approval.requestedBy;
  const decision = receipt.approval.state === "approved" ? "승인" : receipt.approval.state;
  const xmlish = receipt.backend === "xml" ? "xml 편집" : `${receipt.backend} 편집`;
  return `${when} · ${who} ${decision} · ${xmlish} ${receipt.steps.length}건 · 후보본 ${formatBytes(receipt.candidate.bytes)}`;
}

export function ReceiptPanel() {
  const runId = useWorkspace((s) => s.receiptOpen);
  const receipt = useWorkspace((s) => (s.receiptOpen ? s.receipts[s.receiptOpen] : undefined));
  const error = useWorkspace((s) => s.receiptError);

  return (
    <Sheet open={!!runId} onOpenChange={(open) => { if (!open) openReceipt(null); }}>
      <SheetContent className="sheet receipt" data-testid="receipt-panel" aria-label="영수증">
      <SheetHeader className="sheet-head">
        <SheetTitle>영수증</SheetTitle>
        <SheetClose data-testid="close-receipt" />
      </SheetHeader>

      <div className="sheet-body">
        {error ? (
          <div className="refusal" data-testid="receipt-error">
            <Tag tone="bad">영수증을 읽지 못했습니다</Tag>
            <p className="prose">{error.message}</p>
            <p className="mono tiny">{error.code}</p>
            <p className="prose tiny">영수증은 묶어 둔 바이트가 그대로일 때만 내용을 내놓습니다.</p>
          </div>
        ) : !receipt ? (
          <p className="empty">영수증을 읽는 중입니다.</p>
        ) : (
          <>
            <Card className="receipt-summary" data-testid="receipt-summary">
              <CardHeader>
                <CardTitle>요약</CardTitle>
              </CardHeader>
              <CardContent>{summaryLine(receipt)}</CardContent>
            </Card>
            <p className="prose tiny" data-testid="receipt-honesty">
              이 영수증은 바이트와 오프라인 검사만 증명합니다. 페이지 그림은 증거가 아닙니다.
            </p>

            <div className="receipt-block">
              <h4>무엇이 바뀌었나</h4>
              <ol className="receipt-steps">
                {receipt.steps.map((step) => (
                  <li key={step.opId}>
                    <span>{stepTitle(step)}</span>
                    {step.exitCode === 3 ? (
                      <Tag tone="bad">거절 exit 3</Tag>
                    ) : (
                      <Tag tone={step.exitCode === 0 ? "ok" : "bad"}>
                        {step.exitCode === 0 ? "됨" : `exit ${step.exitCode}`}
                      </Tag>
                    )}
                  </li>
                ))}
              </ol>
              {receipt.steps.some((step) => step.exitCode === 3) ? (
                <div className="refusal" data-testid="receipt-exit3-refusal">
                  <Tag tone="bad">거절 exit 3</Tag>
                  <p className="prose tiny">이 단계는 성공으로 표시하지 않습니다.</p>
                </div>
              ) : null}
            </div>

            <div className="receipt-block">
              <h4>누가·언제</h4>
              <dl className="kv">
                <dt>결정</dt>
                <dd>
                  <Tag tone={receipt.approval.state === "approved" ? "ok" : "bad"}>
                    {receipt.approval.state === "approved" ? "승인" : receipt.approval.state}
                  </Tag>
                </dd>
                <dt>승인한 사람</dt>
                <dd>{receipt.approval.approver ?? "—"}</dd>
                <dt>요청한 쪽</dt>
                <dd>{receipt.approval.requestedBy}</dd>
                <dt>결정 시각</dt>
                <dd>{stampWhen(receipt.approval.resolvedUtc) || "—"}</dd>
              </dl>
            </div>

            <div className="receipt-block">
              <h4>파일</h4>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>구분</TableHead>
                    <TableHead>이름</TableHead>
                    <TableHead>해시</TableHead>
                    <TableHead>크기</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  <TableRow>
                    <TableCell>원본</TableCell>
                    <TableCell>{receipt.source.name}</TableCell>
                    <TableCell>
                      <CopyHash value={receipt.source.sha256} />
                    </TableCell>
                    <TableCell>{formatBytes(receipt.source.bytes)}</TableCell>
                  </TableRow>
                  <TableRow>
                    <TableCell>후보본</TableCell>
                    <TableCell>{receipt.candidate.path}</TableCell>
                    <TableCell>
                      <CopyHash value={receipt.candidate.sha256} />
                    </TableCell>
                    <TableCell>{formatBytes(receipt.candidate.bytes)}</TableCell>
                  </TableRow>
                </TableBody>
              </Table>
            </div>

            <Checks receipt={receipt} />

            <Collapsible className="disclosure" data-testid="receipt-raw">
        <CollapsibleTrigger>기술 정보</CollapsibleTrigger>
        <CollapsibleContent>
<p className="mono tiny">{runId}</p>
              <p className="mono tiny">{receipt.backend} · {receipt.planHash}</p>
              <p className="prose tiny">
                <Tag tone="none">{receipt.evidence.class}</Tag> {receipt.evidence.note}
              </p>
              <pre>{JSON.stringify(receipt, null, 2)}</pre>
      </CollapsibleContent>
      </Collapsible>
          </>
        )}
      </div>
      </SheetContent>
    </Sheet>
  );
}
