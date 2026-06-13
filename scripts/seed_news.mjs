// 1회용/로컬 재시드: Google News RSS에서 헤드라인을 받아 site/src/data/news.json 생성.
// 평상시 갱신은 scripts/fetch_data.py의 build_news()가 담당(CI에서 매일).
import { writeFileSync } from "node:fs";

const QUERIES = [
  { q: "미국 증시 마감", lang: "ko", cat: "해외증시" },
  { q: "코스피 삼성전자 SK하이닉스", lang: "ko", cat: "국내증시" },
  { q: "Nvidia stock", lang: "en", cat: "엔비디아" },
  { q: "Oracle stock", lang: "en", cat: "오라클" },
  { q: "Tesla stock", lang: "en", cat: "테슬라" },
  { q: "OpenAI OR Anthropic OR xAI funding IPO", lang: "en", cat: "AI·테크" },
  { q: "원달러 환율", lang: "ko", cat: "환율" },
];
const PER = 4;

function decode(s) {
  return (s || "")
    .replace(/<!\[CDATA\[([\s\S]*?)\]\]>/g, "$1")
    .replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
    .replace(/&#39;|&apos;/g, "'").replace(/&quot;/g, '"').replace(/&nbsp;/g, " ")
    .trim();
}
function splitSource(t) {
  const i = t.lastIndexOf(" - ");
  return i > 0 ? [t.slice(0, i).trim(), t.slice(i + 3).trim()] : [t, ""];
}

async function fetchQ(item) {
  const params = item.lang === "ko" ? "hl=ko&gl=KR&ceid=KR:ko" : "hl=en-US&gl=US&ceid=US:en";
  const url = `https://news.google.com/rss/search?q=${encodeURIComponent(item.q)}&${params}`;
  const r = await fetch(url, { headers: { "User-Agent": "Mozilla/5.0" } });
  const xml = await r.text();
  const blocks = [...xml.matchAll(/<item>([\s\S]*?)<\/item>/g)].slice(0, PER);
  return blocks.map((m) => {
    const blk = m[1];
    const title = decode((blk.match(/<title>([\s\S]*?)<\/title>/) || [])[1] || "");
    const link = decode((blk.match(/<link>([\s\S]*?)<\/link>/) || [])[1] || "");
    const pub = decode((blk.match(/<pubDate>([\s\S]*?)<\/pubDate>/) || [])[1] || "");
    let source = decode((blk.match(/<source[^>]*>([\s\S]*?)<\/source>/) || [])[1] || "");
    const [headline, src2] = splitSource(title);
    if (!source) source = src2;
    return { title: headline, source, link, pub, cat: item.cat };
  });
}

const per = await Promise.all(QUERIES.map(fetchQ));
const ordered = [];
let i = 0;
while (per.some((arr) => i < arr.length)) {
  for (const arr of per) if (i < arr.length) ordered.push(arr[i]);
  i++;
}
const seen = new Set();
const out = [];
for (const n of ordered) {
  if (!n.title || seen.has(n.title)) continue;
  seen.add(n.title);
  out.push(n);
  if (out.length >= 10) break;
}
const date = new Date().toISOString().slice(0, 10);
writeFileSync(new URL("../site/src/data/news.json", import.meta.url), JSON.stringify({ asOf: date, items: out }));
console.log("news:", out.length, "—", out.map((n) => n.source).join(", "));
