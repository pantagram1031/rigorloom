import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import { stripTypeScriptTypes } from "node:module";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}

function loadClass(file, startMarker, endMarker, className) {
  const source = readFileSync(new URL(file, import.meta.url), "utf8");
  const start = source.indexOf(startMarker);
  const end = endMarker === null ? source.length : source.indexOf(endMarker, start);
  assert.ok(start >= 0 && end > start, `${className} source boundary changed`);
  const context = vm.createContext({ Map, Set, Promise });
  const implementation = stripTypeScriptTypes(source.slice(start, end)).replace(
    `export class ${className}`,
    `class ${className}`,
  );
  vm.runInContext(`${implementation}\nglobalThis.LoadedClass = ${className};`, context);
  return context.LoadedClass;
}

const RuntimeSubscriptionScope = loadClass(
  "../src/runtimeSubscriptions.ts",
  "export class RuntimeSubscriptionScope",
  null,
  "RuntimeSubscriptionScope",
);

const DocumentEventOwner = loadClass(
  "../src/documentEvents.ts",
  "export class DocumentEventOwner",
  "\nconst owner =",
  "DocumentEventOwner",
);

function loadPushEvents() {
  const source = readFileSync(new URL("../src/store.ts", import.meta.url), "utf8");
  const start = source.indexOf("export function pushEvents(");
  const end = source.indexOf("// --- the conversation", start);
  assert.ok(start >= 0 && end > start, "pushEvents source boundary changed");
  let state = {
    activeSessionId: "A",
    eventSubscription: "current-A",
    events: [],
  };
  const context = vm.createContext({
    Map,
    state,
    EVENT_CAP: 1000,
    setState: (patch) => {
      state = { ...state, ...patch };
      context.state = state;
    },
  });
  const implementation = stripTypeScriptTypes(source.slice(start, end)).replace(
    "export function pushEvents",
    "function pushEvents",
  );
  vm.runInContext(`${implementation}\nglobalThis.invokePushEvents = pushEvents;`, context);
  return { push: context.invokePushEvents, read: () => state };
}

test("effect disposal immediately unlistens a registration that resolves late", async () => {
  const registration = deferred();
  const calls = [];
  const scope = new RuntimeSubscriptionScope();
  const added = scope.add(registration.promise);
  scope.dispose();
  registration.resolve(() => calls.push("off"));
  assert.equal(await added, false);
  assert.deepEqual(calls, ["off"]);
});

function eventFixture() {
  let state = { activeSessionId: "A", eventSubscription: null };
  const subscriptions = [];
  const unsubscribed = [];
  const published = [];
  const owner = new DocumentEventOwner({
    read: () => state,
    patch: (patch) => {
      state = { ...state, ...patch };
    },
    subscribe: (sessionId) => {
      const request = deferred();
      subscriptions.push({ ...request, sessionId });
      return request.promise;
    },
    unsubscribe: async (subscriptionId) => {
      unsubscribed.push(subscriptionId);
    },
    publish: (batch) => published.push(...batch),
    runtimeError: (error) => ({ code: "test", message: String(error) }),
  });
  return {
    owner,
    subscriptions,
    unsubscribed,
    published,
    read: () => state,
    select: (sessionId) => {
      state = { ...state, activeSessionId: sessionId };
    },
    tick: () => new Promise((resolve) => setImmediate(resolve)),
  };
}

const delivery = (sessionId, subscriptionId, seq) => ({
  sessionId,
  subscriptionId,
  event: { seq, at: "2026-09-08T00:00:00Z", kind: "test" },
});

test("the first batch is held until the subscribe response authenticates it", async () => {
  const f = eventFixture();
  const starting = f.owner.start("A");
  f.owner.deliver([
    delivery("A", "retired-A", 0),
    delivery("A", "current-A", 1),
  ]);
  assert.equal(f.published.length, 0);
  f.subscriptions[0].resolve({ subscriptionId: "current-A" });
  await starting;
  assert.deepEqual(
    f.published.map((row) => row.subscriptionId),
    ["current-A"],
  );
  // The owner preserves the accepted delivery's full envelope for the store.
  assert.equal(f.read().eventSubscription, "current-A");
});

test("pending batches are bounded per subscription without foreign eviction", async () => {
  const f = eventFixture();
  const starting = f.owner.start("A");
  f.owner.deliver([delivery("A", "current-A", 7)]);
  f.owner.deliver(
    Array.from({ length: 1005 }, (_, seq) => delivery("A", "retired-A", seq)),
  );
  f.subscriptions[0].resolve({ subscriptionId: "current-A" });
  await starting;
  assert.equal(f.published.length, 1);
  assert.equal(f.published[0].event.seq, 7);

  const next = f.owner.start("A");
  f.owner.deliver(
    Array.from({ length: 1005 }, (_, seq) => delivery("A", "current-A-2", seq)),
  );
  f.subscriptions[1].resolve({ subscriptionId: "current-A-2" });
  await next;
  assert.equal(f.published.length, 1001);
  assert.equal(f.published[1].event.seq, 5);
  assert.equal(f.published.at(-1).event.seq, 1004);
});

test("the store rejects retired session and subscription envelopes before seq dedup", () => {
  const f = loadPushEvents();
  f.push([
    delivery("A", "retired-A", 0),
    delivery("B", "current-A", 0),
    delivery("A", "current-A", 1),
    delivery("A", "current-A", 1),
  ]);
  assert.equal(f.read().events.map((event) => event.seq).join(","), "1");
});

test("A to B to A supersession retires both stale subscribe responses", async () => {
  const f = eventFixture();
  const firstA = f.owner.start("A");
  f.select("B");
  const b = f.owner.start("B");
  f.select("A");
  const latestA = f.owner.start("A");

  f.subscriptions[2].resolve({ subscriptionId: "latest-A" });
  await latestA;
  f.subscriptions[0].resolve({ subscriptionId: "old-A" });
  f.subscriptions[1].resolve({ subscriptionId: "old-B" });
  await Promise.all([firstA, b]);
  await f.tick();

  assert.equal(f.read().eventSubscription, "latest-A");
  assert.deepEqual(f.unsubscribed.sort(), ["old-A", "old-B"]);
});

test("stopping while subscribe is pending cleans up its late id", async () => {
  const f = eventFixture();
  const starting = f.owner.start("A");
  f.owner.stop();
  f.subscriptions[0].resolve({ subscriptionId: "late-A" });
  await starting;
  await f.tick();
  assert.deepEqual(f.unsubscribed, ["late-A"]);
  assert.equal(f.read().eventSubscription, null);
});
