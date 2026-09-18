/**
 * Load desktop/src/ui modules inside the node:test vm harness.
 */
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import vm from "node:vm";
import ts from "typescript";

const nodeRequire = createRequire(import.meta.url);
const cache = new Map();

function compile(relPath, fileName) {
  const source = readFileSync(new URL(relPath, import.meta.url), "utf8");
  return ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2021,
      jsx: ts.JsxEmit.ReactJSX,
    },
    fileName,
  }).outputText;
}

export function loadUi(file) {
  const key = file.replace(/\.(tsx|ts)$/, "");
  if (cache.has(key)) return cache.get(key);
  const module = { exports: {} };
  cache.set(key, module.exports);
  const candidates = [`${key}.tsx`, `${key}.ts`, file];
  let chosen = null;
  for (const c of candidates) {
    try {
      readFileSync(new URL(`../src/ui/${c}`, import.meta.url));
      chosen = c;
      break;
    } catch {
      /* try next */
    }
  }
  if (!chosen) throw new Error(`ui module not found: ${file}`);
  vm.runInNewContext(compile(`../src/ui/${chosen}`, chosen), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
      if (id === "react-dom") return nodeRequire(id);
      if (id.startsWith("./")) return loadUi(id.slice(2));
      throw new Error(`unexpected import in ${chosen}: ${id}`);
    },
  });
  cache.set(key, module.exports);
  return module.exports;
}

export function uiFromImport(id) {
  const prefixes = ["../ui/", "./ui/", "../../ui/"];
  for (const prefix of prefixes) {
    if (id.startsWith(prefix)) return loadUi(id.slice(prefix.length));
  }
  return null;
}

export function withUi(requireImpl) {
  return (id) => {
    const ui = uiFromImport(id);
    if (ui) return ui;
    return requireImpl(id);
  };
}
