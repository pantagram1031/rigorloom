/**
 * The ways a person opens something: 파일 열기, 폴더 열기, a sample, a recent.
 * Each goes through `tabs.ts`, so the tab appears at once with the file name
 * and keeps it if opening fails.
 */
import { open as openDialog } from "@tauri-apps/plugin-dialog";

import * as rt from "../runtime";
import { getState } from "../store";
import type { CorpusFileEntry, Recent } from "../types";
import { corpusFormDisplayInfo } from "../workspace/openHelpers";
import { S } from "../i18n/v2/shell";
import { setShell } from "./shellState";
import { openDocumentPath, openDocumentUpload } from "./tabs";

export const OPENABLE_EXTENSIONS = ["hwpx", "hwp", "docx", "md"] as const;
const OPENABLE_RE = /\.(hwpx|hwp|docx|md)$/i;

export function isOpenable(name: string): boolean {
  return OPENABLE_RE.test(name);
}

let fileInput: HTMLInputElement | null = null;

function browserFileInput(): HTMLInputElement {
  if (fileInput && document.body.contains(fileInput)) return fileInput;
  const input = document.createElement("input");
  input.type = "file";
  input.accept = OPENABLE_EXTENSIONS.map((e) => `.${e}`).join(",");
  input.style.display = "none";
  input.setAttribute("data-testid", "shell-file-input");
  input.addEventListener("change", () => {
    const file = input.files?.[0];
    input.value = "";
    if (file) void openDocumentUpload(file);
  });
  document.body.appendChild(input);
  fileInput = input;
  return input;
}

/** 파일 열기 (Ctrl+O): the native dialog in Tauri, the browser's picker otherwise. */
export async function pickAndOpenFile(): Promise<void> {
  if (!rt.isTauri()) {
    browserFileInput().click();
    return;
  }
  const chosen = await openDialog({
    multiple: false,
    directory: false,
    filters: [{ name: S.t("shell_open_filter", getState().language), extensions: [...OPENABLE_EXTENSIONS] }],
  });
  if (typeof chosen === "string") await openDocumentPath(chosen);
}

/**
 * 폴더 열기 (Ctrl+Shift+O): choose the 문서 폴더 shown in 파일. In a browser
 * the folder is the server's workspace root, so this only shows the pane.
 */
export async function pickFolder(): Promise<void> {
  if (rt.isTauri()) {
    const chosen = await openDialog({ multiple: false, directory: true });
    if (typeof chosen !== "string") return;
    setShell({ docFolder: chosen });
    void rt.savePrefs({ docFolder: chosen }).catch(() => {});
  }
  setShell({ leftOpen: true, lastOpened: "left" });
  const { showLeftPane } = await import("./bindings");
  showLeftPane("files");
}

export async function openSample(entry: CorpusFileEntry): Promise<string | null> {
  const title = corpusFormDisplayInfo(entry, getState().language).title;
  return openDocumentPath(entry.path, { name: title });
}

export async function openRecent(recent: Recent): Promise<string | null> {
  return openDocumentPath(recent.path, { name: recent.name });
}

/** Files dropped anywhere on the window. The first openable one opens. */
export async function openDroppedFileList(files: File[]): Promise<void> {
  const first = files.find((f) => isOpenable(f.name)) ?? files[0];
  if (first) await openDocumentUpload(first);
}

export async function openDroppedPaths(paths: string[]): Promise<void> {
  const first = paths.find((p) => isOpenable(p)) ?? paths[0];
  if (first) await openDocumentPath(first);
}
