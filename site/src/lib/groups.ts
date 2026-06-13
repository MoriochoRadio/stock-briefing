// 종목 분류 — 시장(미국/한국)·종류(지수/개별주/환율)는 티커에서 자동 판별하고,
// 분야(섹터)만 아래 표로 매핑한다. 관심종목을 config.yaml에 추가하면 여기 SECTORS에도
// 한 줄 넣어주면 된다(없으면 '기타'로 분류됨).
export type Market = "us" | "kr";
export type Kind = "index" | "stock" | "fx";

/** 환율은 null(분위기 집계 제외) */
export function marketOf(ticker: string): Market | null {
  if (ticker === "KRW=X") return null;
  if (ticker.endsWith(".KS") || ticker === "^KS11") return "kr";
  return "us";
}

export function kindOf(ticker: string): Kind {
  if (ticker === "KRW=X") return "fx";
  if (ticker.startsWith("^")) return "index";
  return "stock";
}

export const SECTORS: Record<string, string> = {
  NVDA: "반도체",
  "005930.KS": "반도체",
  "000660.KS": "반도체",
  ORCL: "소프트웨어",
  TSLA: "모빌리티",
};

/** 개별주만 분야를 가진다(지수·환율은 null) */
export function sectorOf(ticker: string): string | null {
  if (kindOf(ticker) !== "stock") return null;
  return SECTORS[ticker] ?? "기타";
}
