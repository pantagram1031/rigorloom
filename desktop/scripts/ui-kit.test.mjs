import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
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

function loadUi(file) {
  if (cache.has(file)) return cache.get(file);
  const module = { exports: {} };
  cache.set(file, module.exports);
  const rel = `../src/ui/${file}`;
  vm.runInNewContext(compile(rel, file), {
    module,
    exports: module.exports,
    require: (id) => {
      if (id === "react/jsx-runtime" || id === "react") return nodeRequire(id);
      if (id === "react-dom") return nodeRequire(id);
      if (id.startsWith("./")) {
        const name = id.slice(2);
        const candidates = [`${name}.tsx`, `${name}.ts`, name];
        for (const c of candidates) {
          try {
            readFileSync(new URL(`../src/ui/${c}`, import.meta.url));
            return loadUi(c);
          } catch {
            /* try next */
          }
        }
      }
      throw new Error(`unexpected import in ${file}: ${id}`);
    },
  });
  cache.set(file, module.exports);
  return module.exports;
}

function html(type, props) {
  return renderToStaticMarkup(React.createElement(type, props));
}

test("button variants, sizes, loading data-state", () => {
  const { Button } = loadUi("Button.tsx");
  const primary = html(Button, { variant: "primary", children: "열기" });
  assert.match(primary, /data-variant="primary"/);
  assert.match(primary, />열기</);
  const loading = html(Button, { loading: true, children: "저장" });
  assert.match(loading, /data-state="loading"/);
  assert.match(loading, /disabled/);
  const sm = html(Button, { size: "sm", children: "sm" });
  assert.match(sm, /data-size="sm"/);
});

test("input textarea select expose the native control", () => {
  const { Input } = loadUi("Input.tsx");
  const { Textarea } = loadUi("Textarea.tsx");
  const { Select } = loadUi("Select.tsx");
  assert.match(html(Input, { "aria-label": "이름" }), /<input/);
  assert.match(html(Textarea, { "aria-label": "메모" }), /<textarea/);
  const select = html(Select, {
    "aria-label": "엔진",
    children: React.createElement("option", { value: "xml" }, "xml"),
  });
  assert.match(select, /<select/);
  assert.match(select, /ui-select-chevron/);
});

test("switch space toggle: role=switch and data-state", () => {
  const { Switch } = loadUi("Switch.tsx");
  const off = html(Switch, { "aria-label": "알림" });
  assert.match(off, /role="switch"/);
  assert.match(off, /aria-checked="false"/);
  assert.match(off, /data-state="unchecked"/);
  const on = html(Switch, { checked: true, "aria-label": "알림" });
  assert.match(on, /aria-checked="true"/);
  assert.match(on, /data-state="checked"/);
  const src = readFileSync(new URL("../src/ui/Switch.tsx", import.meta.url), "utf8");
  assert.match(src, /isActivateKey|" "/);
});

test("checkbox role and checked state", () => {
  const { Checkbox } = loadUi("Checkbox.tsx");
  const node = html(Checkbox, { defaultChecked: true, children: "채움" });
  assert.match(node, /role="checkbox"/);
  assert.match(node, /aria-checked="true"/);
});

test("radio group roving tabindex roles", () => {
  const { RadioGroup, RadioGroupItem } = loadUi("RadioGroup.tsx");
  const node = html(RadioGroup, {
    defaultValue: "xml",
    "aria-label": "엔진",
    children: [
      React.createElement(RadioGroupItem, { key: "xml", value: "xml", children: "xml" }),
      React.createElement(RadioGroupItem, { key: "native", value: "native", children: "native" }),
    ],
  });
  assert.match(node, /role="radiogroup"/);
  assert.match(node, /role="radio"/);
  assert.match(node, /aria-checked="true"/);
  const src = readFileSync(new URL("../src/ui/RadioGroup.tsx", import.meta.url), "utf8");
  assert.match(src, /ArrowDown/);
  assert.match(src, /moveRoving/);
});

test("toggle group single select aria-pressed", () => {
  const { ToggleGroup, ToggleGroupItem } = loadUi("ToggleGroup.tsx");
  const node = html(ToggleGroup, {
    value: "document",
    "aria-label": "보기",
    children: [
      React.createElement(ToggleGroupItem, { key: "document", value: "document", children: "문서" }),
      React.createElement(ToggleGroupItem, { key: "agent", value: "agent", children: "에이전트" }),
    ],
  });
  assert.match(node, /role="group"/);
  assert.match(node, /aria-pressed="true"/);
  assert.match(node, /data-state="on"/);
  assert.match(node, /data-state="off"/);
  const src = readFileSync(new URL("../src/ui/ToggleGroup.tsx", import.meta.url), "utf8");
  assert.match(src, /setValue\(v\)/);
});

test("tabs arrows, aria-controls, tabpanel", () => {
  const { Tabs, TabsList, TabsTrigger, TabsContent } = loadUi("Tabs.tsx");
  const node = html(Tabs, {
    defaultValue: "one",
    children: [
      React.createElement(TabsList, {
        key: "list",
        children: [
          React.createElement(TabsTrigger, { key: "one", value: "one", children: "선택" }),
          React.createElement(TabsTrigger, { key: "two", value: "two", children: "검토" }),
        ],
      }),
      React.createElement(TabsContent, { key: "c1", value: "one", children: "A" }),
      React.createElement(TabsContent, { key: "c2", value: "two", children: "B" }),
    ],
  });
  assert.match(node, /role="tablist"/);
  assert.match(node, /role="tab"/);
  assert.match(node, /aria-controls=/);
  assert.match(node, /role="tabpanel"/);
  assert.match(node, /aria-selected="true"/);
  const src = readFileSync(new URL("../src/ui/Tabs.tsx", import.meta.url), "utf8");
  assert.match(src, /ArrowRight|ArrowLeft|moveRoving/);
});

test("tooltip open adds aria-describedby and role=tooltip", () => {
  const { Tooltip } = loadUi("Tooltip.tsx");
  const node = html(Tooltip, {
    content: "홈으로",
    open: true,
    disablePortal: true,
    children: React.createElement("button", { type: "button" }, "홈"),
  });
  assert.match(node, /role="tooltip"/);
  assert.match(node, /aria-describedby=/);
  assert.match(node, /홈으로/);
});

test("collapsible aria-expanded and aria-controls", () => {
  const { Collapsible, CollapsibleTrigger, CollapsibleContent } = loadUi("Collapsible.tsx");
  const closed = html(Collapsible, {
    children: [
      React.createElement(CollapsibleTrigger, { key: "t", children: "기술 정보" }),
      React.createElement(CollapsibleContent, { key: "c", children: "본문" }),
    ],
  });
  assert.match(closed, /aria-expanded="false"/);
  assert.match(closed, /aria-controls=/);
  assert.match(closed, /data-state="closed"/);
  const opened = html(Collapsible, {
    open: true,
    children: [
      React.createElement(CollapsibleTrigger, { key: "t", children: "기술 정보" }),
      React.createElement(CollapsibleContent, { key: "c", children: "본문" }),
    ],
  });
  assert.match(opened, /aria-expanded="true"/);
  assert.match(opened, /data-state="open"/);
});

test("dropdown menu roles: menu, menuitem, separator, shortcut", () => {
  const {
    DropdownMenu,
    DropdownMenuTrigger,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuShortcut,
  } = loadUi("DropdownMenu.tsx");
  const node = html(DropdownMenu, {
    open: true,
    disablePortal: true,
    children: [
      React.createElement(DropdownMenuTrigger, { key: "t", children: "열기" }),
      React.createElement(DropdownMenuContent, {
        key: "c",
        children: [
          React.createElement(DropdownMenuLabel, { key: "l", children: "문서" }),
          React.createElement(DropdownMenuItem, {
            key: "i",
            children: ["열기", React.createElement(DropdownMenuShortcut, { key: "s" }, "Ctrl+O")],
          }),
          React.createElement(DropdownMenuSeparator, { key: "sep" }),
        ],
      }),
    ],
  });
  assert.match(node, /role="menu"/);
  assert.match(node, /role="menuitem"/);
  assert.match(node, /role="separator"/);
  assert.match(node, /aria-haspopup="menu"/);
  assert.match(node, /aria-expanded="true"/);
});

test("dialog trap surface: role=dialog, aria-modal, labelledby", () => {
  const {
    Dialog,
    DialogTrigger,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
  } = loadUi("Dialog.tsx");
  const node = html(Dialog, {
    open: true,
    disablePortal: true,
    children: [
      React.createElement(DialogTrigger, { key: "t", children: "열기" }),
      React.createElement(DialogContent, {
        key: "c",
        children: [
          React.createElement(DialogHeader, {
            key: "h",
            children: [
              React.createElement(DialogTitle, { key: "title", children: "적용할까요?" }),
              React.createElement(DialogDescription, { key: "d", children: "설명" }),
            ],
          }),
          React.createElement(DialogFooter, { key: "f", children: "확인" }),
        ],
      }),
    ],
  });
  assert.match(node, /role="dialog"/);
  assert.match(node, /aria-modal="true"/);
  assert.match(node, /aria-labelledby=/);
  assert.match(node, /적용할까요\?/);
});

test("sheet is a side dialog with data-side", () => {
  const { Sheet, SheetTrigger, SheetContent, SheetTitle } = loadUi("Sheet.tsx");
  const node = html(Sheet, {
    open: true,
    disablePortal: true,
    side: "right",
    children: [
      React.createElement(SheetTrigger, { key: "t", children: "설정" }),
      React.createElement(SheetContent, {
        key: "c",
        children: React.createElement(SheetTitle, null, "설정"),
      }),
    ],
  });
  assert.match(node, /role="dialog"/);
  assert.match(node, /data-side="right"/);
});

test("badge variants, kbd, separator orientation", () => {
  const { Badge } = loadUi("Badge.tsx");
  const { Kbd } = loadUi("Kbd.tsx");
  const { Separator } = loadUi("Separator.tsx");
  assert.match(html(Badge, { variant: "destructive", children: "실패" }), /data-variant="destructive"/);
  assert.match(html(Kbd, { children: "Ctrl+K" }), /<kbd/);
  assert.match(html(Separator, { orientation: "vertical" }), /data-orientation="vertical"/);
  assert.match(html(Separator, { orientation: "vertical" }), /role="separator"/);
});

test("progress determinate and indeterminate", () => {
  const { Progress } = loadUi("Progress.tsx");
  const det = html(Progress, { value: 64 });
  assert.match(det, /role="progressbar"/);
  assert.match(det, /aria-valuenow="64"/);
  assert.match(det, /data-state="determinate"/);
  const ind = html(Progress, {});
  assert.match(ind, /data-state="indeterminate"/);
});

test("alert variants with title", () => {
  const { Alert } = loadUi("Alert.tsx");
  const node = html(Alert, { variant: "warning", title: "주의", children: "원본은 그대로입니다." });
  assert.match(node, /role="alert"/);
  assert.match(node, /data-variant="warning"/);
});

test("table hairline structure", () => {
  const { Table, TableHeader, TableBody, TableRow, TableHead, TableCell } = loadUi("Table.tsx");
  const node = html(Table, {
    children: [
      React.createElement(TableHeader, {
        key: "h",
        children: React.createElement(TableRow, {
          children: React.createElement(TableHead, null, "칸"),
        }),
      }),
      React.createElement(TableBody, {
        key: "b",
        children: React.createElement(TableRow, {
          children: React.createElement(TableCell, null, "값"),
        }),
      }),
    ],
  });
  assert.match(node, /<table/);
  assert.match(node, /칸/);
});

test("card item skeleton toast empty command", () => {
  const { Card, CardHeader, CardTitle, CardContent } = loadUi("Card.tsx");
  const { Item } = loadUi("Item.tsx");
  const { Skeleton } = loadUi("Skeleton.tsx");
  const { Toast } = loadUi("Toast.tsx");
  const { EmptyState } = loadUi("EmptyState.tsx");
  const { Command } = loadUi("Command.tsx");
  assert.match(
    html(Card, {
      children: [
        React.createElement(CardHeader, { key: "h", children: React.createElement(CardTitle, null, "계획") }),
        React.createElement(CardContent, { key: "c", children: "본문" }),
      ],
    }),
    /계획/,
  );
  assert.match(html(Item, { title: "최근", description: "어제", active: true }), /data-state="active"/);
  assert.match(html(Skeleton, {}), /aria-hidden="true"/);
  assert.match(html(Toast, { variant: "destructive", children: "실패" }), /role="alert"/);
  assert.match(html(EmptyState, { title: "없음", body: "비어 있음" }), /ui-empty/);
  const cmd = html(Command, { items: [{ id: "open", label: "열기", shortcut: "Ctrl+O" }] });
  assert.match(cmd, /role="dialog"/);
  assert.match(cmd, /role="listbox"/);
  assert.match(cmd, /role="option"/);
});

test("popover open content has dialog role and arrow", () => {
  const { Popover, PopoverTrigger, PopoverContent } = loadUi("Popover.tsx");
  const node = html(Popover, {
    open: true,
    disablePortal: true,
    children: [
      React.createElement(PopoverTrigger, { key: "t", children: "자세히" }),
      React.createElement(PopoverContent, { key: "c", children: "내용" }),
    ],
  });
  assert.match(node, /role="dialog"/);
  assert.match(node, /ui-layer-arrow/);
});

test("scroll area is overflow-only (no JS class besides ui-scroll)", () => {
  const { ScrollArea } = loadUi("ScrollArea.tsx");
  const node = html(ScrollArea, { children: "긴 내용" });
  assert.match(node, /ui-scroll/);
  const src = readFileSync(new URL("../src/ui/ScrollArea.tsx", import.meta.url), "utf8");
  assert.doesNotMatch(src, /addEventListener/);
});

test("kit styles use tokens and shadow-popover; gallery route is mounted", () => {
  const css = readFileSync(new URL("../src/styles.css", import.meta.url), "utf8");
  const app = readFileSync(new URL("../src/App.tsx", import.meta.url), "utf8");
  const capture = readFileSync(new URL("../../docs/demo/desktop/capture.mjs", import.meta.url), "utf8");
  assert.match(css, /\/\* kit \*\//);
  assert.match(css, /--shadow-popover/);
  assert.match(css, /\.ui-btn-primary/);
  assert.match(app, /get\("kit"\)/);
  assert.match(app, /KitGallery/);
  assert.match(capture, /kit-dark/);
  assert.match(capture, /kit-gallery/);
});
