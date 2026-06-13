// 1회용/로컬 재시드: CNN 탐욕지수 + 섹터 ETF 등락을 받아 site/src/data/sentiment.json 생성.
// 평상시 갱신은 scripts/fetch_data.py의 build_sentiment()가 담당(CI에서 매일).
import { writeFileSync } from "node:fs";

const US = [
  ["XLK", "기술"], ["XLF", "금융"], ["XLE", "에너지"], ["XLV", "헬스케어"],
  ["XLY", "자유소비재"], ["XLP", "필수소비재"], ["XLI", "산업재"], ["XLB", "소재"],
  ["XLU", "유틸리티"], ["XLRE", "부동산"], ["XLC", "커뮤니케이션"],
];
const KR = [
  ["091160.KS", "반도체"], ["305720.KS", "2차전지"], ["091180.KS", "자동차"],
  ["091170.KS", "은행"], ["102970.KS", "증권"], ["266420.KS", "헬스케어"],
  ["244580.KS", "바이오"], ["266360.KS", "콘텐츠"], ["117460.KS", "에너지화학"],
  ["117680.KS", "철강"], ["117700.KS", "건설"], ["140710.KS", "운송"],
];
const FNG_LABELS = {
  "extreme fear": "극단적 공포", fear: "공포", neutral: "중립",
  greed: "탐욕", "extreme greed": "극단적 탐욕",
};

async function changePct(ticker) {
  const url = `https://query1.finance.yahoo.com/v8/finance/chart/${encodeURIComponent(ticker)}?range=5d&interval=1d`;
  const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
  const j = await r.json();
  const cl = (j.chart?.result?.[0]?.indicators?.quote?.[0]?.close || []).filter((c) => c != null && Number.isFinite(c));
  if (cl.length < 2) return null;
  const last = cl[cl.length - 1], prev = cl[cl.length - 2];
  return Math.round((last / prev - 1) * 1000) / 10;
}

async function basket(list) {
  const out = [];
  for (const [ticker, name] of list) {
    try {
      const cp = await changePct(ticker);
      if (cp != null) out.push({ ticker, name, change_pct: cp });
    } catch (e) { console.log(ticker, "ERR", e.message); }
  }
  return out;
}

async function fng() {
  try {
    const r = await fetch("https://production.dataviz.cnn.io/index/fearandgreed/graphdata", {
      headers: {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        Accept: "application/json, text/plain, */*",
        Referer: "https://www.cnn.com/markets/fear-and-greed",
        Origin: "https://www.cnn.com",
      },
    });
    const j = await r.json();
    const fg = j.fear_and_greed;
    const rating = String(fg.rating || "").toLowerCase();
    return { score: Math.round(fg.score * 10) / 10, rating, label: FNG_LABELS[rating] || rating };
  } catch (e) { console.log("fng ERR", e.message); return null; }
}

const us = await basket(US);
const kr = await basket(KR);
const f = await fng();
const out = { asOf: new Date().toISOString().slice(0, 10), fng: f, us, kr };
writeFileSync(new URL("../site/src/data/sentiment.json", import.meta.url), JSON.stringify(out));
console.log(`us=${us.length} kr=${kr.length} fng=${f ? f.score + " " + f.label : "none"}`);
