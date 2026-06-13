// 시장 데이터 공용 헬퍼 (MarketMood·QuoteCards·대시보드 공유).

export type Q = { ticker?: string; name?: string; change_pct: number };

export function summarize(items: { change_pct: number }[]) {
  const ups = items.filter((q) => q.change_pct > 0).length;
  const downs = items.filter((q) => q.change_pct < 0).length;
  const avg = items.length ? items.reduce((s, q) => s + q.change_pct, 0) / items.length : 0;
  const decided = ups + downs;
  const upPct = decided ? Math.round((ups / decided) * 100) : 50;
  let tone = "flat";
  let label = "혼조";
  if ((upPct >= 60 && avg > 0) || avg >= 0.4) { tone = "up"; label = "강세"; }
  else if ((upPct <= 40 && avg < 0) || avg <= -0.4) { tone = "down"; label = "약세"; }
  return { count: items.length, ups, downs, avg, upPct, downPct: 100 - upPct, tone, label };
}

export const avgText = (v: number) => (v >= 0 ? "+" : "") + v.toFixed(2) + "%";
export const toneOf = (v: number) => (v > 0 ? "up" : v < 0 ? "down" : "flat");

// 히트맵 타일 색: 등락 강도(|%|, 4%에서 최대)로 채도. 한국식 빨강=상승.
export function heatStyle(cp: number) {
  const toneVar = cp > 0 ? "var(--up)" : cp < 0 ? "var(--down)" : "var(--sub)";
  const pct = Math.round(Math.min(1, Math.abs(cp) / 4) * 70) + 14; // 14~84%
  const text = pct >= 46 ? "#fff" : "var(--text)";
  return `background:color-mix(in srgb, ${toneVar} ${pct}%, var(--card)); color:${text};`;
}

// 미니 스파크라인 SVG 경로
export function sparkPath(values: number[], w = 120, h = 32, pad = 3) {
  if (!values || values.length < 2) return null;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const step = (w - pad * 2) / (values.length - 1);
  const xy = values.map((v, i) => [
    +(pad + i * step).toFixed(2),
    +(h - pad - ((v - min) / span) * (h - pad * 2)).toFixed(2),
  ]);
  const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x},${y}`).join(" ");
  const area = `${line} L${xy[xy.length - 1][0]},${h} L${xy[0][0]},${h} Z`;
  return { line, area };
}

// 52주(≈1년) 고/저 대비 현재가 위치
export function range52(series: [string, number][] | undefined) {
  if (!series || series.length < 10) return null;
  const closes = series.map((p) => p[1]).filter((n) => Number.isFinite(n));
  const lo = Math.min(...closes);
  const hi = Math.max(...closes);
  if (!(hi > lo)) return null;
  const cur = closes[closes.length - 1];
  const pos = Math.max(0, Math.min(100, ((cur - lo) / (hi - lo)) * 100));
  return { lo, hi, cur, pos };
}

export function fmtNum(n: number) {
  const s = String(n);
  const i = s.indexOf(".");
  const d = i < 0 ? 0 : Math.min(2, s.length - i - 1);
  return n.toLocaleString("ko-KR", { minimumFractionDigits: d, maximumFractionDigits: d });
}
