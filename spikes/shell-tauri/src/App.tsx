import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { open } from "@tauri-apps/plugin-dialog";

type Resp = Record<string, unknown>;

// One pending-request table keyed by id; the sidecar echoes `id` back.
const pending = new Map<number, (r: Resp) => void>();
let nextId = 1;

function stat(values: number[]) {
  if (!values.length) return { median: 0, p99: 0, min: 0, max: 0 };
  const s = [...values].sort((a, b) => a - b);
  const at = (q: number) => s[Math.min(s.length - 1, Math.floor(q * s.length))];
  return { median: at(0.5), p99: at(0.99), min: s[0], max: s[s.length - 1] };
}

export default function App() {
  const [log, setLog] = useState<string[]>([]);
  const [ready, setReady] = useState(false);
  const [pids, setPids] = useState<{ shell?: number; sidecar?: number }>({});
  const [firstPaintMs, setFirstPaintMs] = useState<number | null>(null);
  const [readyMs, setReadyMs] = useState<number | null>(null);
  const [m3, setM3] = useState<string>("—");
  const [m4, setM4] = useState<string>("—");
  const [m5, setM5] = useState<string>("—");
  const [png, setPng] = useState<string | null>(null);
  const [dialogResult, setDialogResult] = useState<string>("—");
  const [hangul, setHangul] = useState("");
  const [rows, setRows] = useState(() =>
    Array.from({ length: 40 }, (_, i) => ({ id: i, text: "" })),
  );
  const [dpr, setDpr] = useState(window.devicePixelRatio);
  const painted = useRef(false);

  const say = useCallback((m: string) => {
    setLog((l) => [`${new Date().toISOString().slice(11, 23)}  ${m}`, ...l].slice(0, 60));
  }, []);

  // ── first paint (M1, in-process half) ──────────────────────────────
  useEffect(() => {
    if (painted.current) return;
    painted.current = true;
    requestAnimationFrame(() => {
      invoke<number>("mark_first_paint").then((ms) => {
        setFirstPaintMs(ms);
        say(`first paint at ${ms} ms after rust main()`);
      });
    });
  }, [say]);

  // ── sidecar stream ─────────────────────────────────────────────────
  useEffect(() => {
    const un = listen<string>("sidecar-line", (e) => {
      let obj: Resp;
      try {
        obj = JSON.parse(e.payload);
      } catch {
        return;
      }
      const id = obj.id as number | undefined;
      if (typeof id === "number" && pending.has(id)) {
        pending.get(id)!(obj);
        pending.delete(id);
        return;
      }
      if (obj.event === "ready") {
        setReady(true);
        setPids((p) => ({ ...p, sidecar: obj.pid as number }));
        invoke<number>("sidecar_ready_ms").then((ms) => {
          setReadyMs(ms);
          say(`sidecar ready at ${ms} ms after rust main() (pid ${obj.pid})`);
        });
      }
    });
    const unErr = listen<string>("sidecar-stderr", (e) => say(`stderr: ${e.payload}`));
    const unExit = listen<string>("sidecar-exit", (e) => {
      setReady(false);
      say(`SIDECAR EXITED: ${e.payload}`);
    });
    invoke<number>("shell_pid").then((pid) => setPids((p) => ({ ...p, shell: pid })));
    return () => {
      un.then((f) => f());
      unErr.then((f) => f());
      unExit.then((f) => f());
    };
  }, [say]);

  useEffect(() => {
    const on = () => setDpr(window.devicePixelRatio);
    window.addEventListener("resize", on);
    return () => window.removeEventListener("resize", on);
  }, []);

  const call = useCallback((op: string, extra: Resp = {}): Promise<Resp> => {
    const id = nextId++;
    return new Promise((resolve) => {
      pending.set(id, resolve);
      invoke("sidecar_send", { line: JSON.stringify({ op, id, ...extra }) });
    });
  }, []);

  // ── M3: 1000 pings ─────────────────────────────────────────────────
  const runM3 = useCallback(async () => {
    setM3("running…");
    const samples: number[] = [];
    for (let i = 0; i < 1000; i++) {
      const t = performance.now();
      await call("ping");
      samples.push(performance.now() - t);
    }
    const s = stat(samples);
    const out = `median ${s.median.toFixed(2)} ms · p99 ${s.p99.toFixed(2)} ms · min ${s.min.toFixed(2)} · max ${s.max.toFixed(2)} (n=1000)`;
    setM3(out);
    say(`M3 ${out}`);
  }, [call, say]);

  // ── M4: throughput ─────────────────────────────────────────────────
  const runM4 = useCallback(async () => {
    setM4("running…");
    const N = 10000;
    const t = performance.now();
    let seen = 0;
    let bytes = 0;
    await new Promise<void>((resolve) => {
      const un = listen<string>("sidecar-line", (e) => {
        bytes += e.payload.length + 1;
        if (++seen >= N) {
          un.then((f) => f());
          resolve();
        }
      });
      un.then(() => invoke("sidecar_send", { line: JSON.stringify({ op: "echo", n: N, pad: 80 }) }));
    });
    const ms = performance.now() - t;
    const perEvent = `per-event IPC: ${N} lines / ${(bytes / 1048576).toFixed(2)} MiB in ${ms.toFixed(0)} ms = ${(bytes / 1048576 / (ms / 1000)).toFixed(1)} MiB/s`;
    setM4(perEvent + " · measuring rust-side…");
    say(`M4 ${perEvent}`);

    // Second arm: identical work, but Rust counts the lines and emits ONE
    // event. Difference between the two = Tauri's per-event IPC cost.
    const r = await new Promise<{ ms: number; bytes: number }>((resolve) => {
      const un = listen<{ ms: number; bytes: number }>("bench-done", (e) => {
        un.then((f) => f());
        resolve(e.payload);
      });
      un.then(() => invoke("bench_echo", { n: N, pad: 80 }));
    });
    const rustOut = `rust-side (1 event): ${N} lines / ${(r.bytes / 1048576).toFixed(2)} MiB in ${r.ms} ms = ${(r.bytes / 1048576 / (r.ms / 1000)).toFixed(1)} MiB/s`;
    setM4(`${perEvent}  ||  ${rustOut}`);
    say(`M4 ${rustOut}`);
  }, [say]);

  // ── M5: large payload ──────────────────────────────────────────────
  const runM5 = useCallback(async () => {
    setM5("running…");
    const t = performance.now();
    const r = await call("render_page", { zoom: 3.0, page: 0 });
    const ms = performance.now() - t;
    const b64 = r.png_b64 as string | undefined;
    if (!b64) {
      setM5("FAILED — no payload");
      return;
    }
    setPng(`data:image/png;base64,${b64}`);
    const out = `${((r.bytes as number) / 1024).toFixed(0)} KiB PNG (b64 ${(b64.length / 1024).toFixed(0)} KiB) round-trip ${ms.toFixed(0)} ms, fitz ${r.ms} ms`;
    setM5(out);
    say(`M5 ${out}`);
  }, [call, say]);

  // ── native file dialog ─────────────────────────────────────────────
  const runDialog = useCallback(async () => {
    const picked = await open({
      multiple: false,
      filters: [{ name: "한글 문서 (HWPX)", extensions: ["hwpx", "hwp", "pdf", "txt", "*"] }],
    });
    if (!picked) {
      setDialogResult("cancelled");
      return;
    }
    const r = await call("open_path", { path: picked });
    const out = `${r.path} · exists=${r.exists} · ${r.bytes} bytes`;
    setDialogResult(out);
    say(`dialog round-trip: ${out}`);
  }, [call, say]);

  const scalePct = useMemo(() => Math.round(dpr * 100), [dpr]);

  return (
    <main>
      <h1>Rigorloom 데스크톱 셸 스파이크 — Tauri 2 arm</h1>
      <p className="sub">
        Throwaway measurement harness. 사이드카는 PyInstaller로 동결한 CPython
        3.12이며 stdio 위에서 JSONL로만 대화한다.
      </p>

      <section>
        <h2>Status</h2>
        <div className="row">
          <span className={`badge ${ready ? "ok" : "bad"}`}>
            sidecar {ready ? "ready" : "down"}
          </span>
          <span className="badge">shell pid {pids.shell ?? "?"}</span>
          <span className="badge">sidecar pid {pids.sidecar ?? "?"}</span>
          <span className="badge dpi">
            devicePixelRatio {dpr} → {scalePct}%
          </span>
          <span className="badge dpi">
            {window.innerWidth}×{window.innerHeight} css
          </span>
        </div>
        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>M1 first paint (in-process)</dt>
          <dd>{firstPaintMs === null ? "—" : `${firstPaintMs} ms after rust main()`}</dd>
          <dt>M2 sidecar ready</dt>
          <dd>{readyMs === null ? "—" : `${readyMs} ms after rust main()`}</dd>
        </dl>
      </section>

      <div className="grid2">
        <section>
          <h2>Measurements</h2>
          <div className="row">
            <button onClick={runM3}>M3 ping ×1000</button>
            <button onClick={runM4}>M4 throughput</button>
            <button onClick={runM5}>M5 large payload</button>
          </div>
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt>M3 round-trip</dt>
            <dd className="mono">{m3}</dd>
            <dt>M4 throughput</dt>
            <dd className="mono">{m4}</dd>
            <dt>M5 payload</dt>
            <dd className="mono">{m5}</dd>
          </dl>
        </section>

        <section>
          <h2>Native dialog · crash</h2>
          <div className="row">
            <button className="primary" onClick={runDialog}>
              파일 열기 (native)
            </button>
            <button
              className="danger"
              onClick={() => {
                say("requesting sidecar crash");
                invoke("sidecar_send", { line: JSON.stringify({ op: "crash" }) });
              }}
            >
              M12 kill sidecar
            </button>
            <button onClick={() => invoke("restart_sidecar").then(() => say("restart requested"))}>
              restart sidecar
            </button>
          </div>
          <dl className="kv" style={{ marginTop: 12 }}>
            <dt>dialog → sidecar</dt>
            <dd className="mono">{dialogResult}</dd>
          </dl>
        </section>
      </div>

      <section>
        <h2>M13 · M14 Korean IME</h2>
        <p className="sub" style={{ marginBottom: 10 }}>
          아래 칸에 <b>안녕하세요</b>를 두벌식으로 입력한다. 조합 중 Backspace,
          한/영 전환, 리스트 스크롤 중 입력까지 확인한다.
        </p>
        <input
          type="text"
          value={hangul}
          placeholder="여기에 한글을 입력하세요"
          onChange={(e) => setHangul(e.target.value)}
        />
        <dl className="kv" style={{ marginTop: 10 }}>
          <dt>value</dt>
          <dd className="mono">{JSON.stringify(hangul)}</dd>
          <dt>code points</dt>
          <dd className="mono">
            {[...hangul].map((c) => "U+" + c.codePointAt(0)!.toString(16).toUpperCase()).join(" ") || "—"}
          </dd>
          <dt>length</dt>
          <dd className="mono">{hangul.length}</dd>
        </dl>
        <h2 style={{ marginTop: 16 }}>M14 controlled inputs in a scrolling list</h2>
        <ul className="list">
          {rows.map((r) => (
            <li key={r.id}>
              <span className="mono">row {r.id}</span>
              <input
                type="text"
                value={r.text}
                placeholder="한글 입력"
                onChange={(e) =>
                  setRows((prev) =>
                    prev.map((p) => (p.id === r.id ? { ...p, text: e.target.value } : p)),
                  )
                }
              />
            </li>
          ))}
        </ul>
      </section>

      {png && (
        <section>
          <h2>M5 rendered page (PyMuPDF via sidecar, zoom 3.0)</h2>
          <img className="page" src={png} alt="rendered sample page" />
        </section>
      )}

      <section>
        <h2>Log</h2>
        <pre className="log">{log.join("\n")}</pre>
      </section>
    </main>
  );
}
