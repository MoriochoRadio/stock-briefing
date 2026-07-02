// BASE_URL 트레일링 슬래시 보정 — 모든 페이지·컴포넌트가 이걸 공유한다.
// (GitHub Pages 프로젝트 사이트는 /<레포명>/ 하위 배포라 base 처리가 필수)
const raw = import.meta.env.BASE_URL;
export const base = raw.endsWith("/") ? raw : raw + "/";
export const withBase = (path = "") => base + path.replace(/^\//, "");
