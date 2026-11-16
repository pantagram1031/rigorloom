import { readFileSync } from "node:fs";
export { agentPlanCellAddresses, projectAgentPlan } from "../src/agent/planProjection.ts";
export { opKindLabel, t } from "../src/i18n/vocabulary.ts";
const source = readFileSync(new URL("../src/workspace/reviewSummary.ts", import.meta.url), "utf8");
export const approvalHelpers = source.slice(source.indexOf("export function activeApprovalBinding("), source.indexOf("/** Pending operations")).replaceAll("export ", "");
