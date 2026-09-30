"""data.json → LLM 분석 → briefings/YYYY-MM-DD.md
엔진 우선순위: GEMINI_API_KEY → ANTHROPIC_API_KEY → (둘 다 없으면) 데이터만으로 기본 브리핑
"""
import json
import os
import time
import re
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
KST = timezone(timedelta(hours=9))

# 일시적 오류(과부하·레이트리밋)로 한 번에 실패하지 않도록 재시도하는 코드들.
_RETRY_CODES = {429, 500, 502, 503, 529}


def _quota_is_model_level(detail):
    """429라도 '이 모델의 무료 할당량이 0'이거나 '일일 한도 소진'이면 기다려도 풀리지 않는다.
    재시도 대신 곧바로 다음 모델 후보로 넘어가게 판별한다."""
    low = (detail or "").lower()
    return "limit: 0" in low or "perday" in low


def _urlopen_json(req, timeout, tries=6):
    """urlopen + JSON 파싱. 일시적 HTTP 오류/네트워크 오류는 지수 백오프로 재시도.
    무료 LLM 엔드포인트의 일시 과부하(503) 창을 한 실행 안에서 넘기도록 넉넉히 재시도.
    HTTP 오류 본문은 e.detail에 남겨 호출부가 원인(키/모델/할당량)을 가를 수 있게 한다."""
    for i in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            try:
                e.detail = e.read().decode("utf-8", "replace")
            except Exception:
                e.detail = ""
            if e.code in _RETRY_CODES and i < tries - 1 and not _quota_is_model_level(e.detail):
                wait = min(2 ** (i + 1), 32)  # 2,4,8,16,32초 (총 ~60초)
                print(f"[warn] LLM HTTP {e.code} — {wait}s 후 재시도 {i + 1}/{tries - 1}")
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as e:
            if i < tries - 1:
                wait = min(2 ** (i + 1), 32)
                print(f"[warn] LLM 네트워크 오류({e}) — {wait}s 후 재시도 {i + 1}/{tries - 1}")
                time.sleep(wait)
                continue
            raise
    # 모든 재시도 소진(방어적): None을 반환해 호출부가 NoneType 첨자 오류로 죽지 않게 명시적 실패.
    raise RuntimeError("LLM 요청 재시도 모두 소진")

PROMPT_TEMPLATE = """당신은 한국 개인투자자를 위한 아침 시장 브리핑을 쓰는 시니어 시장 분석가다. 규율 있는 거시·기술적 사고를 하되, 근거 없는 단정은 절대 하지 않는다. 아래 데이터와 뉴스 헤드라인만 근거로 한국어 브리핑을 마크다운으로 작성하라.

[독자 프로필]
{profile}

[시세 데이터 (종가·전일대비)]
{quotes}

[시장 분위기]
{mood}

[뉴스 헤드라인]
{news}

[분석 원칙]
- 제공된 데이터에 없는 수치(장중 고저, RSI·MACD 등 보조지표, 거래량 등)는 절대 지어내지 말 것. 오직 종가·등락률·시장 분위기·헤드라인이 담은 정보만 사용한다.
- 헤드라인으로 확인되지 않는 원인은 "~로 추정"이라고 명시하고, 상관(같이 움직임)과 인과(원인-결과)를 구분한다. 기사 제목만으로 확정할 수 없는 세부 수치·일정·수급·실적·목표가는 쓰지 않는다.
- 뉴스에서 가져온 고유 사실 또는 해석 문장 끝에는 제공된 기사 ID만 사용해 [N01]처럼 인용한다. 존재하지 않는 기사 ID를 만들지 말고, 인용할 근거가 없으면 그 사실을 삭제한다.
- 노이즈 제거: 가격에 의미 있는 이슈만 다룬다. 헤드라인 단순 나열 금지 — 항상 "이게 관심종목·지수에 어떤 의미인가"로 해석한다.
- 확증편향 경계: 하나의 서사에 끼워 맞추지 말 것. 반대 시나리오가 성립하면 함께 짚는다.
- 투자 권유·매수매도 단정 금지. 시사점은 단정이 아니라 "관찰 포인트" 수준으로 제시한다.

[구성] (제목 줄은 쓰지 말고 아래 소제목부터 본문 시작):
  ## ⏱ 1분 요약  (핵심 3~5줄, 번호 목록. 첫 줄에 오늘 시장 성격을 한 단어로 — 위험선호 / 중립 / 위험회피 중 하나 — 명시)
  ## 🇺🇸 밤사이 미국장  (지수 표 포함. 관심종목별 등락과 그 의미를 1~2줄씩 해석)
  ## 🇰🇷 한국장 영향 포인트  (미국장→한국장 전이 경로: 반도체·환율·외국인 수급 관점. 마지막에 "**연결고리 한 줄:**" 포함)
  ## 🤖 AI 업계 동향  (비상장 포함, 관련 헤드라인 있을 때만)
  ## 🧭 리스크 레이더  (오늘 주의할 변동성 요인·관찰 포인트 2~3개. 예정된 일정·지표·이벤트 우선)
  ## 📅 오늘의 체크포인트
  ## 📚 오늘의 개념  (오늘 뉴스 속 용어 하나를 초보자용으로 해설)
"""


def load(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def load_sentiment():
    """site/src/data/sentiment.json (CNN 공포탐욕지수 + 섹터 ETF 등락)을 읽어온다. 없으면 {}."""
    path = ROOT / "site" / "src" / "data" / "sentiment.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def build_mood(sent):
    """공포탐욕 지수 + 분야별(섹터) 강약 상·하위를 LLM이 쓸 수 있게 요약 문자열로."""
    if not sent:
        return "(시장 분위기 데이터 없음)"
    lines = []
    fng = sent.get("fng")
    if fng:
        lines.append(f"- 미국 공포·탐욕 지수: {fng.get('score')} ({fng.get('label', fng.get('rating', ''))})")

    def _ranked(label, arr):
        rows = [s for s in (arr or []) if isinstance(s.get("change_pct"), (int, float))]
        if not rows:
            return
        rows.sort(key=lambda s: s["change_pct"], reverse=True)
        top = ", ".join(f"{s['name']}({s['change_pct']:+.2f}%)" for s in rows[:3])
        bot = ", ".join(f"{s['name']}({s['change_pct']:+.2f}%)" for s in rows[-3:])
        lines.append(f"- {label} 강세 상위: {top}")
        lines.append(f"- {label} 약세 하위: {bot}")

    # 이번 수집에 실패해 직전 값을 재사용한 섹터는 기준일을 밝혀 오늘 흐름으로 오해하지 않게 한다.
    for key, label in (("us", "미국 섹터"), ("kr", "한국 섹터")):
        if sent.get(f"{key}Stale"):
            label += f"(기준일 {sent.get(f'{key}AsOf')} — 최신 수집 실패, 오늘 흐름 아님)"
        _ranked(label, sent.get(key))
    return "\n".join(lines) or "(시장 분위기 데이터 없음)"


def build_news_evidence(data):
    """수집된 기사 헤드라인에 안정적인 근거 ID를 붙인다.

    기사 전문을 읽지 않는 RSS 파이프라인이므로 제목에서 확인할 수 없는 구체 수치나
    인과를 모델이 확대 해석하지 않도록, 제목·출처·링크를 하나의 증거 단위로 취급한다.
    """
    evidence = []
    seen = set()
    for item in data.get("news", []):
        raw_title = str(item.get("title", "")).strip()
        link = str(item.get("link", "")).strip()
        # Google News RSS 제목의 마지막 ' - 매체명' 접미사를 분리한다. 대시가 포함된
        # 제목은 rsplit(마지막 한 번)으로 보존한다.
        title, sep, publisher = raw_title.rpartition(" - ")
        title = title.strip() if sep and title.strip() else raw_title
        publisher = publisher.strip() if sep else ""
        if not title or title in seen:
            continue
        seen.add(title)
        evidence.append({
            "id": f"N{len(evidence) + 1:02d}",
            "title": title,
            "source": publisher or str(item.get("query", "뉴스 검색")).strip(),
            "link": link,
        })
    return evidence


def build_prompt(data, cfg):
    quotes = []
    for group, label in [("indices", "지수/환율"), ("watchlist_us", "미국 관심종목"), ("watchlist_kr", "한국 관심종목")]:
        for q in data[group]:
            quotes.append(f"- [{label}] {q['name']}({q['ticker']}): {q['close']:,} ({q['change_pct']:+.2f}%, 기준일 {q['date']})")
    evidence = build_news_evidence(data)
    news = [f"- [{n['id']}] ({n['source']}) {n['title']}" for n in evidence]
    prompt = PROMPT_TEMPLATE.format(
        profile=cfg["profile"]["style"],
        quotes="\n".join(quotes) or "(수집 실패)",
        mood=build_mood(load_sentiment()),
        news="\n".join(news) or "(수집 실패)",
    )
    return prompt, evidence


def append_evidence_references(body, evidence):
    """허용된 기사 ID만 남기고, 실제 인용된 기사에 대한 클릭 가능한 출처 목록을 덧붙인다."""
    valid = {item["id"] for item in evidence}
    cited = []

    def keep_only_known(match):
        ref = match.group(1)
        if ref in valid:
            if ref not in cited:
                cited.append(ref)
            return f"[{ref}]"
        return ""

    cleaned = re.sub(r"\[(N\d{2})\]", keep_only_known, body or "").strip()
    if not cited:
        return cleaned

    by_id = {item["id"]: item for item in evidence}
    lines = ["## 🔗 기사 근거"]
    for ref in cited:
        item = by_id[ref]
        title = item["title"].replace("]", "\\]")
        if item["link"]:
            lines.append(f"- [{ref}] [{title}]({item['link']}) · {item['source']}")
        else:
            lines.append(f"- [{ref}] {title} · {item['source']}")
    return cleaned + "\n\n" + "\n".join(lines)


GEMINI_API = "https://generativelanguage.googleapis.com/v1beta"
# 모델 목록 조회가 실패했을 때 설정 모델 다음으로 시도할 고정 후보(정식 flash → flash-lite → 자동 최신 별칭).
# 평소에는 실행 때마다 /models 목록에서 최신 모델을 골라 쓰므로 이 목록을 손볼 일은 거의 없다.
GEMINI_FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-latest", "gemini-flash-lite-latest"]
# 텍스트 생성용이 아닌 특수 변형(이미지·음성·실시간·임베딩·thinking 전용 등)은 후보에서 뺀다.
_GEMINI_EXCLUDE = ("image", "tts", "audio", "live", "embedding", "thinking", "transcribe",
                   "translate", "computer-use", "robotics", "omni")
_GEMINI_MAX_CANDIDATES = 8

# 한 실행(프로세스) 동안의 Gemini 상태 — 성공한 모델을 고정하고, 키/모델 문제는 한 번만 판정한다.
_GEMINI = {"model": None, "candidates": None, "dead": None}
# '사람이 조치해야 하는' LLM 문제(키 인증 실패·쓸 수 있는 모델 없음·키 미설정). 일시 오류는 넣지 않는다.
LLM_ALERTS = []


class LLMAuthError(Exception):
    """API 키 인증/권한 문제 — 재시도·모델 전환으로 풀리지 않는다(키 재발급 필요)."""


class GeminiNoModelError(Exception):
    """시도한 모든 후보 모델이 '없음/사용 불가'로 응답."""


def _alert(msg):
    if msg not in LLM_ALERTS:
        LLM_ALERTS.append(msg)
        print(f"[alert] {msg}")


def _redact(text):
    """로그·공개 데이터에 키가 새지 않게 가린다(Google 오류 본문에 'api_key:...'가 섞일 수 있음)."""
    text = re.sub(r"AIza[0-9A-Za-z_\-]{10,}", "***", text or "")
    text = re.sub(r"sk-ant-[0-9A-Za-z_\-]+", "***", text)
    for env in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        val = os.environ.get(env)
        if val:
            text = text.replace(val, "***")
    return text


def _http_error_info(e):
    """HTTPError → (코드, status, reason, 가린 메시지 200자). Google 오류 JSON을 파싱한다."""
    raw = getattr(e, "detail", "") or ""
    status = reason = ""
    msg = raw
    try:
        j = json.loads(raw)
        err = (j[0] if isinstance(j, list) and j else j).get("error", {})
        status, msg = err.get("status", ""), err.get("message", raw)
        reason = next((d.get("reason") for d in err.get("details", []) or [] if d.get("reason")), "") or ""
    except Exception:
        pass
    return e.code, status, reason, _redact(" ".join(str(msg).split()))[:200]


_AUTH_REASONS = {"API_KEY_INVALID", "API_KEY_SERVICE_BLOCKED", "API_KEY_HTTP_REFERRER_BLOCKED",
                 "SERVICE_DISABLED", "CONSUMER_SUSPENDED", "ACCESS_TOKEN_EXPIRED"}


def gemini_error_kind(e):
    """Gemini HTTP 오류 분류.
    'auth'     — 키 문제(무효·만료·서비스 비활성). 사람 조치 필요.
    'model'    — 이 모델만 못 씀(404·모델 관련 400/403·무료 할당량 0/일일 소진) → 다음 후보.
    'thinking' — thinking 파라미터 미지원 → 같은 모델로 thinking 없이 재시도.
    'other'    — 일시 오류 등 → 호출부 폴백(알림 없음)."""
    code, status, reason, msg = _http_error_info(e)
    low = f"{status} {reason} {msg}".lower()
    if reason in _AUTH_REASONS or ("api key" in low and any(k in low for k in ("not valid", "invalid", "expired"))):
        return "auth"
    if code == 404 or status == "NOT_FOUND":
        return "model"
    if code == 429:
        return "model" if _quota_is_model_level(getattr(e, "detail", "")) else "other"
    if code == 400 and ("thinking" in low or "budget" in low):
        return "thinking"
    if code in (400, 403) and "model" in low:
        return "model"
    if code in (401, 403):
        return "auth"
    return "other"


def _model_version(name):
    m = re.match(r"gemini-(\d+(?:\.\d+)*)-", name)
    return tuple(int(p) for p in m.group(1).split(".")) if m else ()


def order_gemini_models(available, configured):
    """시도 순서: 설정 모델 → 최신 정식 flash → 최신 정식 flash-lite → 그 외 flash 계열(-latest 별칭, 버전 내림차순).
    available이 None(목록 조회 실패)이면 설정 모델 + 고정 후보(GEMINI_FALLBACK_MODELS)."""
    out = [configured] if configured else []
    if available is None:
        pool = list(GEMINI_FALLBACK_MODELS)
    else:
        flash = [n for n in available
                 if n.startswith("gemini-") and "flash" in n and not any(x in n for x in _GEMINI_EXCLUDE)]
        stable = sorted((n for n in flash if re.fullmatch(r"gemini-\d+(?:\.\d+)*-flash", n)), key=_model_version, reverse=True)
        lite = sorted((n for n in flash if re.fullmatch(r"gemini-\d+(?:\.\d+)*-flash-lite", n)), key=_model_version, reverse=True)
        preferred = stable[:1] + lite[:1]
        rest = sorted((n for n in flash if n not in preferred),
                      key=lambda n: (n.endswith("-latest"), _model_version(n),
                                     bool(re.fullmatch(r"gemini-\d+(?:\.\d+)*-flash(-lite)?", n))),
                      reverse=True)
        pool = preferred + rest
    for n in pool:
        if n not in out:
            out.append(n)
    return out[:_GEMINI_MAX_CANDIDATES]


def list_gemini_models(key):
    """generateContent를 지원하는 모델 이름 목록. 조회 실패 시 None(키 문제면 LLMAuthError)."""
    names, token = [], ""
    try:
        for _ in range(5):  # 페이지네이션(보통 1페이지)
            url = f"{GEMINI_API}/models?pageSize=1000" + (f"&pageToken={token}" if token else "")
            req = urllib.request.Request(url, headers={"x-goog-api-key": key})
            res = _urlopen_json(req, timeout=30, tries=3)
            for m in res.get("models", []):
                if "generateContent" in (m.get("supportedGenerationMethods") or []):
                    names.append(str(m.get("name", "")).removeprefix("models/"))
            token = res.get("nextPageToken")
            if not token:
                break
    except urllib.error.HTTPError as e:
        if gemini_error_kind(e) == "auth":
            code, status, reason, msg = _http_error_info(e)
            raise LLMAuthError(f"HTTP {code} {reason or status}: {msg}") from e
        print(f"[warn] Gemini 모델 목록 조회 실패(HTTP {e.code}) — 설정 모델+고정 후보로 시도")
        return None
    except Exception as e:
        print(f"[warn] Gemini 모델 목록 조회 실패({_redact(str(e))}) — 설정 모델+고정 후보로 시도")
        return None
    return names


def _gemini_generate(model, prompt, cfg, key, thinking=True):
    # 키는 URL 쿼리 대신 헤더로 전달 — 예외 메시지·프록시 로그에 URL이 찍혀도 키가 새지 않는다
    url = f"{GEMINI_API}/models/{model}:generateContent"
    # thinking 예산: >0이면 추론을 켜 분석 깊이를 높인다(무료). thinking 토큰도 출력 한도를
    # 소비하므로 max_output_tokens보다 작게 둔다. 0=끔, -1=동적.
    gen = {"maxOutputTokens": cfg["llm"]["max_output_tokens"]}
    if thinking:
        gen["thinkingConfig"] = {"thinkingBudget": cfg["llm"].get("gemini_thinking_budget", 0)}
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": gen}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "x-goog-api-key": key},
    )
    # 추론을 켜면 생성에 시간이 더 걸릴 수 있어 타임아웃을 늘린다.
    res = _urlopen_json(req, timeout=240)
    # 추론 응답은 본문이 여러 part로 나뉠 수 있으므로 thought가 아닌 text part만 모두 합친다.
    parts = res["candidates"][0]["content"].get("parts", [])
    texts = [p["text"] for p in parts if "text" in p and not p.get("thought")]
    return "\n".join(texts).strip()


def _gemini_candidates(cfg, key):
    """대체 후보 목록(한 실행에 한 번만 /models 조회). 키 문제면 LLMAuthError."""
    if _GEMINI["candidates"] is None:
        try:
            available = list_gemini_models(key)
        except LLMAuthError as e:
            _GEMINI["dead"] = e
            raise
        _GEMINI["candidates"] = order_gemini_models(available, cfg["llm"].get("gemini_model"))
    return _GEMINI["candidates"]


def call_gemini(prompt, cfg, key):
    """Gemini 호출 → (본문, 실제 사용한 모델).
    설정 모델이 종료·접근 제한돼도 사람이 모델명을 바꾸지 않도록, '모델 문제(404 등)'가 나면 그때
    /models 목록으로 후보를 만들어 다음 후보로 넘어간다(평소엔 설정 모델 한 번 호출로 끝 — 기존과 동일).
    성공한 모델은 이 실행 동안 고정(인트라데이 close처럼 여러 번 불러도 같은 모델).
    키 문제는 LLMAuthError, 후보 전멸은 GeminiNoModelError(둘 다 알림 대상), 일시 오류는 그대로 raise."""
    if _GEMINI["dead"]:
        raise _GEMINI["dead"]
    configured = cfg["llm"].get("gemini_model")
    queue = [m for m in [_GEMINI["model"] or configured] if m]
    tried, expanded = [], False
    while True:
        if not queue:
            if expanded:
                break
            expanded = True
            queue = [c for c in _gemini_candidates(cfg, key) if c not in tried]
            if not queue:
                break
            print(f"[info] Gemini 대체 후보: {', '.join(queue[:4])}{' …' if len(queue) > 4 else ''}")
        model = queue.pop(0)
        thinking = True
        for _attempt in range(2):
            try:
                text = _gemini_generate(model, prompt, cfg, key, thinking=thinking)
            except urllib.error.HTTPError as e:
                kind = gemini_error_kind(e)
                code, status, reason, msg = _http_error_info(e)
                if kind == "thinking" and thinking:
                    print(f"[info] {model}: thinking 설정 미지원(HTTP {code}) — thinking 없이 재시도")
                    thinking = False
                    continue
                if kind == "auth":
                    _GEMINI["dead"] = LLMAuthError(f"HTTP {code} {reason or status}: {msg}")
                    raise _GEMINI["dead"] from e
                if kind in ("model", "thinking"):
                    print(f"[info] Gemini 모델 {model} 사용 불가(HTTP {code} {reason or status}: {msg[:120]}) — 다음 후보")
                    tried.append(model)
                    break
                raise
            if _GEMINI["model"] != model:
                _GEMINI["model"] = model
                if model != configured:
                    print(f"[info] Gemini 모델 자동 선택: {model} (설정값 {configured} 대신)")
            return text, model
    _GEMINI["dead"] = GeminiNoModelError(f"시도한 후보 전부 사용 불가: {', '.join(tried)}")
    raise _GEMINI["dead"]


def call_anthropic(prompt, cfg, key):
    model = cfg["llm"]["anthropic_model"]
    body = {
        "model": model,
        "max_tokens": cfg["llm"]["max_output_tokens"],
        "messages": [{"role": "user", "content": prompt}],
        # adaptive thinking: 모델이 인과·맥락을 스스로 충분히 추론한 뒤 답하도록 한다.
        # Opus 4.8/4.7/Sonnet 4.6에서 지원. effort=high로 분석 깊이를 끌어올린다.
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "high"},
    }
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        },
    )
    # thinking이 켜지면 응답 생성에 시간이 더 걸릴 수 있어 타임아웃을 늘린다.
    res = _urlopen_json(req, timeout=300)
    # adaptive thinking이 켜지면 content[0]가 thinking 블록일 수 있으므로
    # text 블록만 추려서 합친다 (content[0]["text"] 직접 접근은 깨질 수 있음).
    texts = [b.get("text", "") for b in res.get("content", []) if b.get("type") == "text"]
    return "\n".join(t for t in texts if t).strip()


def fallback_briefing(data):
    """LLM 키가 없을 때: 데이터만으로 표 중심 브리핑"""
    lines = ["## ⏱ 시세 요약 (LLM 미설정 — 데이터만 표시)\n"]
    lines.append("| 구분 | 종가 | 등락 |\n|---|---|---|")
    for group in ("indices", "watchlist_us", "watchlist_kr"):
        for q in data[group]:
            lines.append(f"| {q['name']} | {q['close']:,} | {q['change_pct']:+.2f}% |")
    lines.append("\n## 주요 헤드라인\n")
    for n in data["news"][:15]:
        lines.append(f"- [{n['title']}]({n['link']})")
    return "\n".join(lines)


def run_llm(prompt, cfg):
    """설정된 provider 우선순위로 LLM을 호출해 (본문, 엔진명) 반환.
    한 엔진이 실패(재시도 후에도 오류)하면 다른 엔진으로 폴백하고, 모두 실패/무키면 (None, "없음").
    예외를 삼켜 워크플로가 죽지 않게 한다(호출부는 None이면 데이터 요약으로 대체).
    인트라데이 등 다른 스크립트도 같은 엔진 설정을 공유하도록 분리."""
    gem, ant = os.environ.get("GEMINI_API_KEY"), os.environ.get("ANTHROPIC_API_KEY")
    provider = cfg["llm"].get("provider", "anthropic")
    if not (gem or ant):
        _alert("LLM API 키가 설정되지 않음(GEMINI_API_KEY/ANTHROPIC_API_KEY 시크릿) — AI 분석 없이 데이터 요약만 게시 중")

    def _gemini():
        text, model = call_gemini(prompt, cfg, gem)
        return text, f"Gemini ({model})"

    engines = []  # (이름, 키, 호출함수)
    if ant:
        engines.append(("anthropic", ant, lambda: (call_anthropic(prompt, cfg, ant), f"Claude ({cfg['llm']['anthropic_model']})")))
    if gem:
        engines.append(("gemini", gem, _gemini))
    # provider로 지정된 엔진을 맨 앞으로
    engines.sort(key=lambda e: 0 if e[0] == provider else 1)

    for name, _key, fn in engines:
        try:
            return fn()
        except LLMAuthError as e:
            _alert(f"Gemini API 키 인증 실패({e}) — GEMINI_API_KEY 재발급 후 저장소 시크릿 갱신 필요")
        except GeminiNoModelError as e:
            _alert(f"사용 가능한 Gemini 모델 없음({e}) — config.yaml llm.gemini_model/키 권한 확인 필요")
        except urllib.error.HTTPError as e:
            if name == "anthropic" and e.code in (401, 403):
                _alert(f"Anthropic API 키 인증 실패(HTTP {e.code}) — ANTHROPIC_API_KEY 확인 필요")
            print(f"[warn] {name} 호출 최종 실패(HTTP {e.code} {_http_error_info(e)[3]}) — 다음 엔진/폴백으로")
        except Exception as e:
            print(f"[warn] {name} 호출 최종 실패({_redact(str(e))}) — 다음 엔진/폴백으로")
    return None, "없음"


def record_llm_status(engine, path=None):
    """모닝 브리핑이 실제로 쓴 엔진·모델과 '사람 조치 필요' 알림을 quality.json에 남긴다.
    사이트(Hero)가 하드코딩 대신 이 값을 표시하고, 워크플로 health_check가 알림을 읽는다."""
    path = path or ROOT / "site" / "src" / "data" / "quality.json"
    quality = {}
    if path.exists():
        try:
            quality = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            quality = {}
    used = re.search(r"\(([^)]+)\)", engine or "")
    quality["llm"] = {
        "engine": engine,
        "model": used.group(1) if used else None,
        "generatedAt": datetime.now(KST).isoformat(),
        "alerts": list(LLM_ALERTS),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(quality, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def main():
    cfg = yaml.safe_load(load(ROOT / "config.yaml"))
    data = json.loads(load(ROOT / "data.json"))
    prompt, evidence = build_prompt(data, cfg)

    body, engine = run_llm(prompt, cfg)
    if body is None:
        body = fallback_briefing(data)
    else:
        body = append_evidence_references(body, evidence)
    print(f"engine: {engine}, evidence: {len(evidence)}")
    record_llm_status(engine)

    date = data["date_kst"]
    md = f"# 📈 아침 시장 브리핑 — {date} ({data['weekday_kr']})\n\n{body}\n\n---\n*자동 생성 브리핑 (엔진: {engine}). 투자 권유가 아닌 정보 제공입니다.*\n"
    out_dir = ROOT / "briefings"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / f"{date}.md"
    out.write_text(md, encoding="utf-8")
    print(f"saved {out}")


if __name__ == "__main__":
    main()
