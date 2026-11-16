/**
 * Korean form-structure tokens used purely for programmatic cell and
 * placeholder classification (never rendered directly as UI copy).
 */
export const INSTRUCTION_PHRASES = [
  "서식에 포함하지 아니한다",
  "표시하지 아니하고",
  "작성할 때",
] as const;

export const SLOT_PLACEHOLDER_MARKERS = [
  "연도별일련번호",
  "직위(직급)서명",
] as const;
