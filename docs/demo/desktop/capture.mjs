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
const URL = "http://localhost:5184";
const PORT = 9333;
const CHROME = [
  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
  "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
].find((p) => existsSync(p));

if (!CHROME) {
  console.error("No Chrome/Edge found. See README.md for the fallback commands.");
  process.exit(1);
}

const STATES = ["home", "workspace", "review", "history", "agent", "popover"];
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
    ws.addEventListener("message", (ev) => {
      const msg = JSON.parse(String(ev.data));
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
  async eval(expression) {
    const result = await this.send("Runtime.evaluate", {
      expression,
      returnByValue: true,
      userGesture: true,
      awaitPromise: true,
    });
    if (result.exceptionDetails) {
      throw new Error(result.exceptionDetails.text || "evaluate failed");
    }
    return result.result?.value;
  }
}

async function waitFor(cdp, expression, timeout = 12000) {
  const start = Date.now();
  while (Date.now() - start < timeout) {
    const value = await cdp.eval(expression);
    if (value) return value;
    await sleep(80);
  }
  throw new Error(`timeout waiting for ${expression}`);
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
  }

  if (state === "history") {
    await click(cdp, '[data-testid="inspector-tab-history"]');
    await waitFor(cdp, `document.querySelector('[data-testid="inspector-panel"]')?.dataset.tab === "history"`);
  }

  if (state === "agent") {
    await click(cdp, '[data-testid="inspector-tab-agent"]');
    await waitFor(cdp, `document.querySelector('[data-testid="inspector-panel"]')?.dataset.tab === "agent"`);
  }

  if (state === "popover") {
    await click(cdp, '[data-testid="verify-details-toggle"]');
    await waitFor(cdp, `document.querySelector('[data-testid="verify-details-toggle"]')?.getAttribute("aria-expanded") === "true"`);
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
  await cdp.send("Page.navigate", { url: URL });
  await waitFor(cdp, `document.readyState === "complete"`);
  await sleep(450);
  await prepareState(cdp, state);
  await sleep(180);
  const shot = await cdp.send("Page.captureScreenshot", { format: "png", fromSurface: true });
  const file = path.join(OUT, `${state}-${width}x${height}-${theme}.png`);
  await writeFile(file, Buffer.from(shot.data, "base64"));
  console.log("wrote", path.basename(file));
}

async function main() {
  await mkdir(OUT, { recursive: true });
  const profile = path.join(os.tmpdir(), "rigorloom-r6-chrome");
  const child = spawn(
    CHROME,
    [
      "--headless=new",
      "--disable-gpu",
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profile}`,
      "--no-first-run",
      "--no-default-browser-check",
      `--window-size=1920,1080`,
      "about:blank",
    ],
    { stdio: ["ignore", "ignore", "pipe"] },
  );
  let pageWs = "";
  for (let i = 0; i < 50; i++) {
    try {
      const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
      const list = await res.json();
      const page = list.find((t) => t.type === "page" && t.webSocketDebuggerUrl);
      if (page) {
        pageWs = page.webSocketDebuggerUrl;
        break;
      }
    } catch {
      /* chrome still booting */
    }
    await sleep(100);
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
    for (const theme of THEMES) {
      for (const [width, height] of SIZES) {
        for (const state of STATES) {
          await captureOne(cdp, width, height, theme, state);
        }
      }
    }
  } finally {
    ws.close();
    child.kill();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
