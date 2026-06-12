import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

// briefings/ 폴더(레포 루트)의 마크다운을 그대로 콘텐츠로 사용
const briefings = defineCollection({
  loader: glob({ pattern: "*.md", base: "../briefings" }),
  schema: z.object({}).passthrough(),
});

export const collections = { briefings };
