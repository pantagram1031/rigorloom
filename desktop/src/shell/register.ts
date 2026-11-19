/** The shell's own slot entries. Loaded by `registrations.ts` like every package's. */
import { FilesPane } from "./FilesPane";
import { registerSlot } from "./slots";

registerSlot("pane:files", FilesPane, { owner: "shell", order: 100 });
