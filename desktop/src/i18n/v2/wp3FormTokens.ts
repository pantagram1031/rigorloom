/**
 * Korean form-structure matching tokens for WP3 outline, blanks, and font-map
 * resolution (never rendered directly as UI copy).
 */

export const KOREAN_SUBCLAUSE_LINE_RE = /^([\uAC00-\uD7A3]\.\s+.+)$/;

export const AGENCY_USE_TOKENS = [
  "접수",
  "접수일",
  "접수번호",
  "접수기관",
  "접수 기관",
] as const;

export const FORM_OUTLINE_TOKENS = {
  rulePrefix: "시행규칙",
  formNumberPrefix: "별지",
  orgName: "행정기관명",
  recipient: "수신",
  subject: "제목",
  body: "본문",
  sender: "발신명의",
  drafter: "기안자",
  reviewer: "검토자",
  approver: "결재권자",
  coop: "협조자",
  dispatch: "시행",
  receipt: "접수",
  postal: "도로명주소",
  phone: "전화번호",
  fax: "팩스번호",
  email: "전자우편",
  disclosure: "공개 구분",
  note: "비고",
  attachment: "붙임",
  seal: "직인",
} as const;

export const SERIF_FONT_TOKENS = [
  "바탕",
  "명조",
  "Batang",
  "Myeongjo",
] as const;

export const SANS_FONT_TOKENS = [
  "돋움",
  "고딕",
  "굴림",
  "Dotum",
  "Gothic",
  "Gulim",
] as const;

/** Faces the repository ships (engine/references/fonts: NanumGothic, NanumMyeongjo). */
export const BUNDLED_FACE_NAMES = new Set<string>([
  "나눔명조",
  "나눔고딕",
  "NanumMyeongjo",
  "NanumMyeongjo-Regular",
  "NanumMyeongjo-Bold",
  "NanumGothic",
  "NanumGothic-Regular",
  "NanumGothic-Bold",
  "Nanum Myeongjo",
  "Nanum Gothic",
]);
