import { registerSlot } from "../shell/slots";
import { HistoryPane } from "./HistoryPane";

registerSlot("pane:history", HistoryPane, { order: 1000, owner: "editor" });
