import type { wp3t } from "../i18n/v2/wp3";
import type { RasterSource } from "../model/enginePage";

export const SOURCE_COPY: Record<RasterSource, Parameters<typeof wp3t>[0]> = {
  engine: "page_source_engine",
  hancom: "page_source_hancom",
  pdf: "page_source_pdf",
  "own-uncertified": "page_source_own",
};
