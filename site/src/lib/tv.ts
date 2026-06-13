// yfinance 티커 → TradingView 심볼 매핑 (실시간 상세 차트 모달용).
// 심볼이 안 맞으면 TradingView가 "invalid symbol"을 보여주므로, 그때 이 표만 고치면 된다.
export const TV_SYMBOLS: Record<string, string> = {
  "^DJI": "TVC:DJI", // 다우 (TradingView 정식 심볼)
  "^GSPC": "TVC:SPX", // S&P 500
  "^IXIC": "NASDAQ:IXIC", // 나스닥 종합
  "^KS11": "KRX:KOSPI", // 코스피
  "KRW=X": "FX_IDC:USDKRW", // 원/달러
  NVDA: "NASDAQ:NVDA",
  ORCL: "NYSE:ORCL",
  TSLA: "NASDAQ:TSLA",
  "005930.KS": "KRX:005930", // 삼성전자
  "000660.KS": "KRX:000660", // SK하이닉스
};

export function tvSymbol(ticker: string): string | null {
  return TV_SYMBOLS[ticker] ?? null;
}
