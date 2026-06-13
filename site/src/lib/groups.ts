// 티커 기반 분류 헬퍼.
export type Kind = "index" | "stock" | "fx";

export function kindOf(ticker: string): Kind {
  if (ticker === "KRW=X") return "fx";
  if (ticker.startsWith("^")) return "index";
  return "stock";
}
