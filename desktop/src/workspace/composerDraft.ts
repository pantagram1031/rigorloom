/** Workspace-owned input survives replacement of the Agent view subtree. */
export interface ComposerDraft {
  text: string;
}

export interface ComposerDraftPort {
  read(): ComposerDraft;
  write(draft: ComposerDraft): void;
  send(text: string): Promise<boolean>;
}

/** Restore a refused send only while it still owns the cleared input. */
export async function submitComposerDraft(port: ComposerDraftPort): Promise<boolean> {
  const submitted = port.read();
  if (!submitted.text.trim()) return false;
  const cleared = { text: "" };
  port.write(cleared);
  let sent = false;
  try {
    sent = await port.send(submitted.text);
    return sent;
  } finally {
    // Identity also distinguishes typing followed by an intentional clear.
    if (!sent && port.read() === cleared) port.write(submitted);
  }
}
