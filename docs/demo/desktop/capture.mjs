/**
 * Capture R6 reference PNGs from the vite dev-mock on :5184.
 * Uses Chrome (or Edge) headless CDP. No extra npm packages.
 */
import { spawn } from "node:child_process";
import { mkdir, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)));
const OUT = ROOT;
const URL = "http://127.0.0.1:5184";
const PORT = 9333;
const CHROME = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].find((p) => existsSync(p));

if (!CHROME) {
  console.error("No Chrome/Edge found. See README.md for the fallback commands.");
  process.exit(1);
}

const STATES = ["home", "workspace", "review", "history", "agent", "popover", "palette", "settings"];
const KIT_STATES = {
  kit: { theme: "light", query: "?kit=1" },
  "kit-dark": { theme: "dark", query: "?kit=1&theme=dark" },
};
const SIZES = [
  [1280, 800],
  [1920, 1080],
];
const THEMES = ["light", "dark"];

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

class Cdp {
  constructor(ws) {
    this.ws = ws;
    this.seq = 0;
    this.pending = new Map();
    this.events = new Map();
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(String(ev.data));
      if (msg.method) {
        const waiters = this.events.get(msg.method);
        if (waiters && waiters.length) waiters.shift()(msg.params);
        return;
      }
      const wait = this.pending.get(msg.id);
      if (!wait) return;
      this.pending.delete(msg.id);
      if (msg.error) wait.reject(new Error(JSON.stringify(msg.error)));
      else wait.resolve(msg.result);
    });
  }
  send(method, params = {}) {
    const id = ++this.seq;
    this.ws.send(JSON.stringify({ id, method, params }));
    return new Promise((resolve, reject) => this.pending.set(id, { resolve, reject }));
  }
  once(method) {
    return new Promise((resolve) => {
      const list = this.events.get(method) ?? [];
      list.push(resolve);
      this.events.set(method, list);
    });
  }
  async eval(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      userGesture: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.exception?.description || result.exceptionDetails.text || "evaluate failed");
    }
    return result.result?.value;
  }
}

async function waitFor(cdp, expression, timeout = 12000) {
  const start = Date.now();
  let last = null;
  while (Date.now() - start < timeout) {
    try {
      const value = await cdp.eval(expression);
      last = value;
      if (value) return value;
    } catch (err) {
      last = String(err);
    }
    await sleep(80);
  }
  let where = "";
  try {
    where = await cdp.eval(`location.href + " | " + document.readyState + " | " + (document.body ? document.body.innerText.slice(0, 160) : "nobody")`);
  } catch (err) {
    where = String(err);
  }
  throw new Error(`timeout waiting for ${expression} (last=${last}; page=${where})`);
}

async function click(cdp, selector) {
  await waitFor(cdp, `!!document.querySelector(${JSON.stringify(selector)})`);
  await cdp.eval(`document.querySelector(${JSON.stringify(selector)}).click()`);
}

async function prepareState(cdp, state) {
  await cdp.eval(`{
    const splash = document.querySelector('[data-testid="splash"]');
    if (splash) splash.click();
    true;
  }`);
  await waitFor(cdp, `!!document.querySelector('[data-testid="welcome"], [data-testid="view-document"]')`);
  await sleep(80);

  if (state === "home") {
    const onHome = await cdp.eval(`!!document.querySelector('[data-testid="welcome"]')`);
    if (!onHome) await click(cdp, '[data-testid="header-home"]');
    await waitFor(cdp, `!!document.querySelector('[data-testid="welcome"]')`);
    return;
  }

  if (state === "settings") {
    const onHome = await cdp.eval(`!!document.querySelector('[data-testid="welcome"]')`);
    if (!onHome) await click(cdp, '[data-testid="header-home"]');
    await waitFor(cdp, `!!document.querySelector('[data-testid="welcome"]')`);
    await click(cdp, '[data-testid="home-settings"]');
    await waitFor(cdp, `!!document.querySelector('[data-testid="settings"]')`);
    return;
  }

  const onHome = await cdp.eval(`!!document.querySelector('[data-testid="welcome"]')`);
  if (onHome) {
    const hasTab = await cdp.eval(`!!document.querySelector('[data-testid="doc-tab"]')`);
    if (hasTab) await click(cdp, '[data-testid="doc-tab"]');
    else await click(cdp, '[data-testid="recent-row"]');
  }
  await waitFor(cdp, `!!document.querySelector('[data-testid="left-rail"]')`);
  await waitFor(cdp, `!!document.querySelector('[data-testid="paper"], [data-testid="text-view"]')`);

  if (state === "workspace") {
    await click(cdp, '[data-testid="inspector-tab-selection"]');
    return;
  }

  if (state === "review" || state === "popover") {
    await waitFor(cdp, `!!document.querySelector('[data-testid="doc-cell-0-0-14"]')`);
    const queued = await cdp.eval(`!!document.querySelector('[data-testid="queue-op-0-0-14"], [data-testid="queued-0-0-14"]')`);
    if (!queued) {
      await click(cdp, '[data-testid="doc-cell-0-0-14"]');
      await waitFor(cdp, `!!document.querySelector('[data-testid="seat-input"]')`);
      await cdp.eval(`{
        const input = document.querySelector('[data-testid="seat-input"]');
        const last = input.value;
        const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
        setter.call(input, "행정안전부");
        const tracker = input._valueTracker;
        if (tracker) tracker.setValue(last);
        input.dispatchEvent(new Event("input", { bubbles: true }));
        input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
        input.blur();
        true;
      }`);
      await waitFor(
        cdp,
        `!!document.querySelector('[data-testid="queued-0-0-14"], [data-testid="badge-review"]')`,
      );
    }
    await click(cdp, '[data-testid="inspector-tab-review"]');
    await waitFor(cdp, `!!document.querySelector('[data-testid="queue-op-0-0-14"], [data-testid="review-queue"]')`);
    await waitFor(cdp, `!!document.querySelector('[data-testid="approve-and-apply"]')`);
  }

  if (state === "history") {
    await click(cdp, '[data-testid="inspector-tab-history"]');
    await waitFor(cdp, `document.querySelector('[data-testid="inspector-panel"]')?.dataset.tab === "history"`);
  }

  if (state === "agent") {
    await click(cdp, '[data-testid="inspector-tab-agent"]');
    await waitFor(cdp, `document.querySelector('[data-testid="inspector-panel"]')?.dataset.tab === "agent"`);
  }

  if (state === "palette") {
    const sendPalette = () =>
      cdp.eval(`{
        window.dispatchEvent(new KeyboardEvent("keydown", {
          key: "k",
          code: "KeyK",
          ctrlKey: true,
          bubbles: true,
          cancelable: true,
        }));
        true;
      }`);
    await sendPalette();
    const opened = await cdp.eval(`!!document.querySelector('[data-testid="command-palette"]')`);
    if (!opened) await sendPalette();
    await waitFor(cdp, `!!document.querySelector('[data-testid="command-palette"]')`);
  }

  if (state === "popover") {
    await click(cdp, '[data-testid="verify-details-toggle"]');
    const opened = await cdp.eval(
      `document.querySelector('[data-testid="verify-details-toggle"]')?.getAttribute("aria-expanded") === "true"`,
    );
    if (!opened) await click(cdp, '[data-testid="verify-details-toggle"]');
    await waitFor(
      cdp,
      `document.querySelector('[data-testid="verify-details-toggle"]')?.getAttribute("aria-expanded") === "true" && !!document.querySelector('[data-testid="verify-details"]')`,
    );
  }
}

async function captureOne(cdp, width, height, theme, state) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width,
    height,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-color-scheme", value: theme }],
  });
  await navigate(cdp);
  await sleep(450);
  await prepareState(cdp, state);
  await sleep(180);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const file = path.join(OUT, `${state}-${width}x${height}-${theme}.png`);
  await writeFile(file, Buffer.from(shot.data, "base64"));
  console.log("wrote", path.basename(file));
}

async function navigate(cdp) {
  const href = await cdp.eval(`location.href`).catch(() => "");
  const onKit = typeof href === "string" && href.includes("kit=");
  const onApp =
    !onKit &&
    typeof href === "string" &&
    (href === URL || href.startsWith(`${URL}/`));
  const loaded = cdp.once("Page.loadEventFired");
  if (onApp) {
    await cdp.send("Page.reload", { ignoreCache: false });
  } else {
    const nav = await cdp.send("Page.navigate", { url: URL });
    if (nav.errorText) throw new Error(`navigate failed: ${nav.errorText}`);
  }
  await Promise.race([
    loaded,
    sleep(15000).then(() => {
      throw new Error("timeout waiting for Page.loadEventFired");
    }),
  ]);
  await waitFor(
    cdp,
    `location.port === "5184" && !location.search.includes("kit=") && !!document.querySelector('[data-testid="splash"], [data-testid="welcome"], [data-testid="view-document"]')`,
    20000,
  );
}

async function typeInto(cdp, selector, value) {
  await waitFor(cdp, `!!document.querySelector(${JSON.stringify(selector)})`);
  await cdp.eval(`{
    const el = document.querySelector(${JSON.stringify(selector)});
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const last = el.value;
    const setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(el, ${JSON.stringify(value)});
    const tracker = el._valueTracker;
    if (tracker) tracker.setValue(last);
    el.dispatchEvent(new Event("input", { bubbles: true }));
    true;
  }`);
}

async function shotFrame(cdp, frames, name) {
  await sleep(400);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const file = path.join(OUT, `_gif-${name}.png`);
  await writeFile(file, Buffer.from(shot.data, "base64"));
  frames.push(file);
  console.log("frame", name);
  await sleep(1200);
}

async function captureGif(cdp) {
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-color-scheme", value: "light" }],
  });
  await navigate(cdp);
  await sleep(200);
  await cdp.eval(`{
    const splash = document.querySelector('[data-testid="splash"]');
    if (splash) splash.click();
    true;
  }`);
  await waitFor(
    cdp,
    `!!document.querySelector('[data-testid="welcome"], [data-testid="view-document"]')`,
    20000,
  );
  const frames = [];
  await shotFrame(cdp, frames, "home");

  await click(cdp, 'button[data-testid="recent-row"]');
  await waitFor(cdp, `!!document.querySelector('[data-testid="left-rail"]')`);
  await waitFor(cdp, `!!document.querySelector('[data-testid="paper"], [data-testid="text-view"]')`);
  await shotFrame(cdp, frames, "open");

  await waitFor(cdp, `!!document.querySelector('[data-testid="doc-cell-0-0-14"]')`);
  await click(cdp, '[data-testid="doc-cell-0-0-14"]');
  await waitFor(cdp, `!!document.querySelector('[data-testid="seat-input"]')`);
  await cdp.eval(`{
    const input = document.querySelector('[data-testid="seat-input"]');
    const last = input.value;
    const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value").set;
    setter.call(input, "행정안전부");
    const tracker = input._valueTracker;
    if (tracker) tracker.setValue(last);
    input.dispatchEvent(new Event("input", { bubbles: true }));
    true;
  }`);
  await shotFrame(cdp, frames, "seat");
  await cdp.eval(`{
    const input = document.querySelector('[data-testid="seat-input"]');
    input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true }));
    input.blur();
    true;
  }`);
  await waitFor(
    cdp,
    `!!document.querySelector('[data-testid="queued-0-0-14"], [data-testid="badge-review"], [data-testid="queue-op-0-0-14"]')`,
  );
  await click(cdp, '[data-testid="inspector-tab-review"]');
  await waitFor(cdp, `!!document.querySelector('[data-testid="approve-and-apply"]')`);
  await waitFor(
    cdp,
    `document.querySelector('[data-testid="approve-and-apply"]').disabled === false`,
  );
  await shotFrame(cdp, frames, "review");

  await click(cdp, '[data-testid="approve-and-apply"]');
  await waitFor(
    cdp,
    `document.querySelector('[data-testid="inspector-panel"]')?.dataset.tab === "history" || !!document.querySelector('[data-testid="badge-history"], [data-testid^="history-"]')`,
    20000,
  );
  await click(cdp, '[data-testid="inspector-tab-history"]');
  await waitFor(cdp, `document.querySelector('[data-testid="inspector-panel"]')?.dataset.tab === "history"`);
  await waitFor(cdp, `!!document.querySelector('[data-testid^="history-"]')`);
  const openedReceipt = await cdp.eval(`!!document.querySelector('[data-testid="candidate-hash"], [data-testid^="history-receipt-"]')`);
  if (openedReceipt) {
    const hashBtn = await cdp.eval(`!!document.querySelector('[data-testid="candidate-hash"]')`);
    if (hashBtn) await click(cdp, '[data-testid="candidate-hash"]');
    else await click(cdp, '[data-testid^="history-receipt-"]');
    await waitFor(cdp, `!!document.querySelector('[data-testid="receipt-panel"]')`, 8000).catch(() => null);
  }
  await shotFrame(cdp, frames, "receipt");

  const listPath = path.join(OUT, "_gif-frames.txt");
  await writeFile(listPath, frames.join("\n") + "\n");
  console.log("frames", frames.length);
  return frames;
}

async function assembleGif(frames) {
  const script = path.resolve(ROOT, "..", "..", "..", "desktop", "scripts", "assemble-demo-gif.py");
  const out = path.join(OUT, "demo.gif");
  await new Promise((resolve, reject) => {
    const child = spawn("python", [script, "--out", out, ...frames], { stdio: "inherit" });
    child.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`assemble-demo-gif.py exit ${code}`));
    });
    child.on("error", reject);
  });
}

async function withCdp(fn) {
  await mkdir(OUT, { recursive: true });
  const profile = path.join(os.tmpdir(), `rigorloom-r8-chrome-${Date.now()}`);
  const port = PORT + Math.floor(Math.random() * 50);
  const child = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      "--remote-allow-origins=*",
      "--allow-insecure-localhost",
      `--remote-debugging-port=${port}`,
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "--no-default-browser-check",
      `--window-size=1920,1080`,
      URL,
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  let pageWs = "";
  for (let i = 0; i < 80; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${port}/json/list`);
      const list = await res.json();
      const page =
        list.find((t) => t.type === "page" && String(t.url || "").includes(":5184") && t.webSocketDebuggerUrl) ||
        (i > 20 ? list.find((t) => t.type === "page" && t.webSocketDebuggerUrl) : null);
      if (page) {
        pageWs = page.webSocketDebuggerUrl;
        break;
      }
    } catch {
      /* chrome still booting */
    }
    await sleep(150);
  }
  if (!pageWs) {
    child.kill();
    throw new Error("Chrome page target did not come up");
  }
  const ws = new WebSocket(pageWs);
  await new Promise((resolve, reject) => {
    ws.addEventListener("open", resolve);
    ws.addEventListener("error", reject);
  });
  const cdp = new Cdp(ws);
  await cdp.send("Page.enable");
  await cdp.send("Runtime.enable");
  try {
    await fn(cdp);
  } finally {
    ws.close();
    child.kill();
  }
}

async function captureKit(cdp, state) {
  const spec = KIT_STATES[state];
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: 800,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await cdp.send("Emulation.setEmulatedMedia", {
    features: [{ name: "prefers-color-scheme", value: spec.theme }],
  });
  const loaded = cdp.once("Page.loadEventFired");
  const nav = await cdp.send("Page.navigate", { url: `${URL}/${spec.query}` });
  if (nav.errorText) throw new Error(`navigate failed: ${nav.errorText}`);
  await Promise.race([
    loaded,
    sleep(15000).then(() => {
      throw new Error("timeout waiting for kit Page.loadEventFired");
    }),
  ]);
  await waitFor(cdp, `!!document.querySelector('[data-testid="kit-gallery"]')`, 20000);
  await cdp.eval(`document.documentElement.dataset.theme = ${JSON.stringify(spec.theme)}`);
  await sleep(250);
  const height = await cdp.eval(
    `Math.ceil((document.querySelector('[data-testid="kit-gallery"]')?.scrollHeight || 800) + 16)`,
  );
  const shotHeight = Math.min(Math.max(Number(height) || 800, 800), 4200);
  await cdp.send("Emulation.setDeviceMetricsOverride", {
    width: 1280,
    height: shotHeight,
    deviceScaleFactor: 1,
    mobile: false,
  });
  await sleep(250);
  const shot = await cdp.send("Page.captureScreenshot", {
    format: "png",
    fromSurface: true,
    captureBeyondViewport: true,
  });
  const file = path.join(OUT, `${state}-1280x800-${spec.theme}.png`);
  await writeFile(file, Buffer.from(shot.data, "base64"));
  console.log("wrote", path.basename(file));
}

async function main() {
  const args = process.argv.slice(2);
  if (args.includes("gif")) {
    let frames = [];
    await withCdp(async (cdp) => {
      frames = await captureGif(cdp);
    });
    await assembleGif(frames);
    return;
  }
  const kitArgs = args.filter((a) => a === "kit" || a === "kit-dark");
  const rest = args.filter((a) => a !== "kit" && a !== "kit-dark");
  await withCdp(async (cdp) => {
    if (kitArgs.length || args.length === 0) {
      const which = kitArgs.length ? kitArgs : ["kit", "kit-dark"];
      for (const state of which) await captureKit(cdp, state);
    }
    if (args.length && kitArgs.length && rest.length === 0) return;
    const filter = new Set(rest);
    for (const theme of THEMES) {
      for (const [width, height] of SIZES) {
        for (const state of STATES) {
          const name = `${state}-${width}x${height}-${theme}.png`;
          if (filter.size && !filter.has(name) && !filter.has(state)) continue;
          await captureOne(cdp, width, height, theme, state);
        }
      }
    }
  });
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
