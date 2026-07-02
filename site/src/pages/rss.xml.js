import rss from "@astrojs/rss";
import { getCollection } from "astro:content";
import { base } from "../lib/base";

// 최근 브리핑 RSS 피드 — 피드 리더 구독용.
export async function GET(context) {
  const all = (await getCollection("briefings"))
    .sort((a, b) => b.id.localeCompare(a.id))
    .slice(0, 30);
  return rss({
    title: "아침 시장 브리핑",
    description: "미국·한국 증시 일일 맞춤 브리핑 — 반도체 중심",
    site: context.site,
    items: all.map((b) => ({
      title: `아침 시장 브리핑 — ${b.id}`,
      link: `${base}briefings/${b.id}/`,
      pubDate: new Date(`${b.id}T07:00:00+09:00`),
      description: (b.body || "").split("\n").slice(0, 12).join("\n"),
    })),
    customData: "<language>ko</language>",
  });
}
