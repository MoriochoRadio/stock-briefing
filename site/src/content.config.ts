import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// briefings/ 폴더(레포 루트)의 마크다운을 그대로 콘텐츠로 사용
const briefings = defineCollection({
  loader: glob({ pattern: "*.md", base: "../briefings" }),
  schema: z.object({}).passthrough(),
});

// 결정론적으로 생성된 주간·월간 회고. 일일 브리핑과 분리해 기간별 기록임을 명확히 한다.
const weeklyReviews = defineCollection({
  loader: glob({ pattern: "*.md", base: "../reviews/weekly" }),
  schema: z.object({}).passthrough(),
});

const monthlyReviews = defineCollection({
  loader: glob({ pattern: "*.md", base: "../reviews/monthly" }),
  schema: z.object({}).passthrough(),
});

export const collections = { briefings, weeklyReviews, monthlyReviews };
