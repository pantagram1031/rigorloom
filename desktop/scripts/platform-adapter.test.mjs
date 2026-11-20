// Integration: PLATFORM `rigorloom.changeset/1` and `rigorloom.events/1` through the panel adapter.
// The examples are checked against the runtime schemas.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const adapter = await import("../src/panel/adapter.ts");
const model = await import("../src/model/changes.ts");

const FIX = new URL("./fixtures/platform/", import.meta.url);
const RUNTIME_SCHEMAS = new URL("../../runtime/schemas/", import.meta.url);

function loadSchema(name) {
  const own = new URL(name, RUNTIME_SCHEMAS);
  return JSON.parse(readFileSync(own, "utf8"));
}
const SCHEMAS = { "changeset.schema.json": loadSchema("changeset.schema.json"), "events.schema.json": loadSchema("events.schema.json") };
const json = (f) => JSON.parse(readFileSync(new URL(f, FIX), "utf8"));

// A subset of JSON Schema 2020-12: type, const, enum, pattern, minimum, minLength,
// required, properties, items, $ref (local and cross-file $defs), allOf with if/then.
function validate(value, schema, root, where = "$", errors = []) {
  if (schema.$ref) {
    const [file, frag] = schema.$ref.split("#");
    const doc = file ? SCHEMAS[file] : root;
    const target = frag.split("/").filter(Boolean).reduce((o, k) => o[k], doc);
    return validate(value, target, doc, where, errors);
  }
  const types = schema.type ? [].concat(schema.type) : null;
  const typeOf = (v) => (v === null ? "null" : Array.isArray(v) ? "array" : Number.isInteger(v) ? "integer" : typeof v);
  if (types) {
    const t = typeOf(value);
    if (!types.includes(t) && !(t === "integer" && types.includes("number"))) {
      errors.push(`${where}: type ${t} not in ${types}`);
      return errors;
    }
  }
  if ("const" in schema && value !== schema.const) errors.push(`${where}: not ${schema.const}`);
  if (schema.enum && !schema.enum.includes(value)) errors.push(`${where}: ${value} not in enum`);
  if (schema.pattern && typeof value === "string" && !new RegExp(schema.pattern).test(value)) errors.push(`${where}: pattern ${schema.pattern}`);
  if (typeof schema.minimum === "number" && typeof value === "number" && value < schema.minimum) errors.push(`${where}: < ${schema.minimum}`);
  if (typeof schema.minLength === "number" && typeof value === "string" && value.length < schema.minLength) errors.push(`${where}: too short`);
  if (value && typeof value === "object" && !Array.isArray(value)) {
    for (const k of schema.required ?? []) if (!(k in value)) errors.push(`${where}: missing ${k}`);
    for (const [k, sub] of Object.entries(schema.properties ?? {})) if (k in value) validate(value[k], sub, root, `${where}.${k}`, errors);
  }
  if (Array.isArray(value) && schema.items) value.forEach((v, i) => validate(v, schema.items, root, `${where}[${i}]`, errors));
  for (const part of schema.allOf ?? []) {
    if (part.if && validate(value, part.if, root, where, []).length === 0 && part.then) validate(value, part.then, root, where, errors);
  }
  return errors;
}

test("the examples are valid rigorloom.changeset/1 and rigorloom.events/1", () => {
  const cs = SCHEMAS["changeset.schema.json"];
  for (const f of ["changeset-example.json", "changeset-p0-stale.json"]) {
    assert.deepEqual(validate(json(f), cs, cs), [], f);
  }
  const ev = SCHEMAS["events.schema.json"];
  const lines = readFileSync(new URL("events-example.jsonl", FIX), "utf8").trim().split("\n");
  for (const line of lines) assert.deepEqual(validate(JSON.parse(line), ev, ev), [], line);
  // The validator itself refuses what the schema refuses.
  assert.notDeepEqual(validate({ ...json("changeset-example.json"), status: "accepted" }, cs, cs), []);
  assert.notDeepEqual(validate({ ...json("changeset-p0-stale.json"), reason: "plan_behind_head" }, cs, cs), []);
  assert.notDeepEqual(validate(JSON.parse(lines[4].replace(',"reason": "superseded_by_newer_candidate"', "").replace(', "reason": "superseded_by_newer_candidate"', "")), ev, ev), []);
});

test("a schema-valid change set maps onto the panel's view", () => {
  const view = adapter.fromPlatformChangeSet(json("changeset-example.json"), { planHash: "f".repeat(64) });
  assert.equal(view.id, "cs-0002-a1b2c3");
  assert.equal(view.stale, null);
  assert.equal(view.closed, null);
  assert.deepEqual(view.base, { kind: "candidate", revision: 1, sha256: "1".repeat(64) });
  assert.equal(view.provenance.mock, false);
  assert.equal(view.provenance.agent, "rigorloom-agent");
  // Item status pending|accepted|rejected is the decision; null before/after read as empty.
  assert.deepEqual(view.items.map((i) => [i.id, i.n, i.decision, i.source]), [
    ["i1", 1, "accepted", "agent"],
    ["i2", 2, "pending", "agent"],
    ["i3", 3, "rejected", "agent"],
  ]);
  assert.equal(view.items[0].before, "");
  assert.deepEqual(view.items[0].rects, [{ page: 1, x: 72, y: 96, w: 180, h: 14 }]);
  // Per-item guard with the real values; `expected` is neutral.
  assert.equal(view.items[1].guard.status, "changed");
  assert.deepEqual(view.items[1].guard.facts[0], { kind: "number", before: "80", after: "100", expected: false });
  assert.equal(view.items[2].guard.status, "expected");
  assert.deepEqual(view.returnedItems, ["i3"]);
  assert.deepEqual(view.supersedes, ["cs-0001-ffeedd"]);
  // The gate reads it like any other view: one item still 대기.
  const gate = model.gateState(view);
  assert.equal(gate.canApprove, false);
  assert.deepEqual(gate.block, { kind: "remaining", count: 1 });
  assert.equal(model.canDecide(view), true);
});

test("P0 sets without items, stale reasons and closed sets", () => {
  const stale = adapter.fromPlatformChangeSet(json("changeset-p0-stale.json"), { currentRevision: 2 });
  assert.deepEqual(stale.items, []);
  assert.deepEqual(stale.stale, { reason: "superseded_by_newer_candidate", current: 2 });
  assert.equal(stale.provenance.mock, true);
  assert.equal(stale.provenance.agent, "mcp:desktop");
  assert.deepEqual(stale.base, { kind: "source", revision: 0, sha256: "" });
  assert.equal(model.canDecide(stale), false);

  for (const reason of ["source_changed", "target_changed", "declined_by_person"]) {
    const v = adapter.fromPlatformChangeSet({ ...json("changeset-example.json"), status: "stale", reason });
    assert.equal(v.stale.reason, reason);
    assert.equal(v.stale.current, 2);
    assert.equal(model.canDecide(v), false);
  }
  for (const status of ["applied", "rejected", "withdrawn"]) {
    const v = adapter.fromPlatformChangeSet({ ...json("changeset-example.json"), status });
    assert.equal(v.closed, status);
    assert.equal(model.canDecide(v), false);
    assert.equal(model.gateState(v).canApprove, false);
  }
  // A mock set labels every item 시험용.
  const mock = adapter.fromPlatformChangeSet({ ...json("changeset-example.json"), provenance: { mock: true } });
  assert.ok(mock.items.every((i) => i.source === "test"));
});

test("events map onto what the panel does with them", () => {
  const lines = readFileSync(new URL("events-example.jsonl", FIX), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  const fx = lines.map((l) => adapter.fromPlatformEvent(l));
  assert.deepEqual(fx[0], { kind: "run", turnId: "t-1", phase: "started" });
  assert.deepEqual(fx[1], { kind: "step", turnId: "t-1", step: "rendering_pages" });
  assert.equal(fx[2].kind, "text");
  assert.deepEqual(fx[3], { kind: "proposed", turnId: "t-1", changesetId: "cs-0002-a1b2c3", itemIds: ["i1", "i2", "i3"], mock: false });
  assert.deepEqual(fx[4], { kind: "stale", turnId: "t-1", changesetId: "cs-0001-ffeedd", reason: "superseded_by_newer_candidate" });
  assert.deepEqual(fx[5], { kind: "closed", turnId: "t-1", changesetId: "cs-0002-a1b2c3", status: "applied" });
  // Today's host events (no schema) take the old path.
  assert.equal(adapter.fromPlatformEvent({ seq: 1, kind: "message.delta", text: "x" }), null);
});
