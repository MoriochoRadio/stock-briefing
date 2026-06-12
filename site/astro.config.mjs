import { defineConfig } from "astro/config";
import tailwindcss from "@tailwindcss/vite";

// GitHub Pages 프로젝트 사이트는 /<레포명>/ 하위에 배포됨.
// 워크플로가 BASE_PATH 환경변수로 레포명을 자동 주입함. 로컬 dev에서는 '/'.
export default defineConfig({
  site: process.env.SITE_URL || "https://example.github.io",
  base: process.env.BASE_PATH || "/",
  vite: {
    plugins: [tailwindcss()],
  },
});
