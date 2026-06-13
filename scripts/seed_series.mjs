// 1회용: Yahoo 차트 API로 1년치 일봉 종가를 받아 site/src/data/series.json 시드 생성.
// 평상시 갱신은 scripts/fetch_data.py의 build_series()가 담당(CI에서 매일).
import { writeFileSync } from "node:fs";

const TICKERS = ["^DJI", "^GSPC", "^IXIC", "^KS11", "KRW=X", "NVDA", "ORCL", "TSLA", "005930.KS", "000660.KS"];

const out = {};
for (const t of TICKERS) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(t)}?range=1y&interval=1d`;
  const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
  const j = await r.json();
  const res = j.chart?.result?.[0];
  if (!res) { console.log(t, "no data"); continue; }
  const ts = res.timestamp || [];
  const cl = res.indicators?.quote?.[0]?.close || [];
  const arr = [];
  for (let i = 0; i < ts.length; i++) {
    const c = cl[i];
    if (c == null || !Number.isFinite(c)) continue;
    const d = new Date(ts[i] * 1000).toISOString().slice(0, 10);
    arr.push([d, Math.round(c * 100) / 100]);
  }
  out[t] = arr;
  console.log(t, arr.length);
}

const dest = new URL("../site/src/data/series.json", import.meta.url);
writeFileSync(dest, JSON.stringify(out));
console.log("wrote", dest.pathname);
