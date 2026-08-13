"""가격 스냅샷과 이벤트 기록을 바탕으로 주간·월간 회고를 생성한다.

LLM 호출이나 미래 예측 없이, 수집된 종가 변화와 당시 보존한 헤드라인 카테고리만
사용한다. 각 문서에는 기준일·계산 범위·수집 한계를 기록해 재현 가능성을 유지한다.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "site" / "src" / "data" / "history.json"
LEDGER_PATH = ROOT / "site" / "src" / "data" / "event_ledger.json"
KST = ZoneInfo("Asia/Seoul")


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def clean_history():
    raw = load_json(HISTORY_PATH, [])
    snapshots = []
    for item in raw:
        try:
            day = date.fromisoformat(item["date"])
        except Exception:
            continue
        quotes = [quote for quote in item.get("quotes", []) if isinstance(quote.get("close"), (int, float)) and quote.get("ticker")]
        if quotes:
            snapshots.append({"date": day, "quotes": quotes})
    return sorted(snapshots, key=lambda item: item["date"])


def returns_for(snapshots):
    first, last = snapshots[0], snapshots[-1]
    start = {quote["ticker"]: quote for quote in first["quotes"]}
    end = {quote["ticker"]: quote for quote in last["quotes"]}
    rows = []
    for ticker, final in end.items():
        initial = start.get(ticker)
        if not initial:
            continue
        base, close = initial.get("close"), final.get("close")
        if not isinstance(base, (int, float)) or not isinstance(close, (int, float)) or base == 0:
            continue
        rows.append({
            "ticker": ticker,
            "name": final.get("name") or initial.get("name") or ticker,
            "return": (close / base - 1) * 100,
            "start": base,
            "end": close,
        })
    return sorted(rows, key=lambda row: row["return"], reverse=True)


def period_events(start: date, end: date):
    entries = load_json(LEDGER_PATH, {}).get("entries", [])
    selected = []
    for entry in entries:
        try:
            event_date = date.fromisoformat(entry["date"])
        except Exception:
            continue
        if start <= event_date <= end:
            selected.extend(entry.get("items", []))
    counts = Counter((item.get("category") or "마켓") for item in selected)
    return counts, selected[:8]


def format_price(value):
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:,.2f}".rstrip("0").rstrip(".")


def market_rows(rows):
    return [row for row in rows if row["ticker"] in {"^DJI", "^GSPC", "^IXIC", "^KS11", "KRW=X"}]


def write_review(kind: str, key: str, snapshots):
    if len(snapshots) < 2:
        return None
    start, end = snapshots[0]["date"], snapshots[-1]["date"]
    rows = returns_for(snapshots)
    markets = market_rows(rows)
    leaders = rows[:5]
    laggards = list(reversed(rows[-5:]))
    category_counts, events = period_events(start, end)
    generated = datetime.now(KST).strftime("%Y-%m-%d %H:%M KST")
    title = "주간" if kind == "weekly" else "월간"
    event_text = " · ".join(f"{category} {count}건" for category, count in category_counts.most_common(5)) or "수집된 이벤트 기록 없음"
    lines = [
        f"# {key} {title} 시장 회고",
        "",
        f"> **기준 기간:** {start.isoformat()} ~ {end.isoformat()} 수집 스냅샷  ",
        f"> **생성 시각:** {generated}  ",
        "> **계산 기준:** 종목별 기간 첫 수집 종가와 마지막 수집 종가를 비교한 단순 수익률. 배당·거래 비용·환율 조정·거래일 수 차이는 반영하지 않습니다.",
        "",
        "## 기록 요약",
        "",
        f"이 회고는 {len(snapshots)}개 수집 기록과 {len(rows)}개 비교 가능 티커를 바탕으로 자동 생성되었습니다. 가격 변화는 과거 수집값의 정량적 비교이며, 사건의 원인·영향·향후 방향을 판단하지 않습니다.",
        "",
        "## 주요 지수·환율 기록",
        "",
        "| 항목 | 시작 종가 | 종료 종가 | 기간 변화 |",
        "|---|---:|---:|---:|",
    ]
    for row in markets:
        lines.append(f"| {row['name']} ({row['ticker']}) | {format_price(row['start'])} | {format_price(row['end'])} | {row['return']:+.2f}% |")
    if not markets:
        lines.append("| 비교 가능 지수·환율 데이터 없음 | – | – | – |")
    lines += ["", "## 변화폭 상위 종목", "", "| 종목 | 기간 변화 |", "|---|---:|"]
    for row in leaders:
        lines.append(f"| {row['name']} ({row['ticker']}) | {row['return']:+.2f}% |")
    lines += ["", "## 변화폭 하위 종목", "", "| 종목 | 기간 변화 |", "|---|---:|"]
    for row in laggards:
        lines.append(f"| {row['name']} ({row['ticker']}) | {row['return']:+.2f}% |")
    lines += [
        "",
        "## 보존된 뉴스 이벤트",
        "",
        f"기간 내 이벤트 카테고리 기록: **{event_text}**.",
        "",
    ]
    if events:
        for item in events:
            category = item.get("category") or "마켓"
            title_text = item.get("title") or "제목 없음"
            source = item.get("source") or "출처 미표기"
            link = item.get("link") or ""
            if link:
                lines.append(f"- **{category}** — [{title_text}]({link}) · {source}")
            else:
                lines.append(f"- **{category}** — {title_text} · {source}")
    else:
        lines.append("- 해당 기간에 누적된 이벤트 기록이 아직 없습니다. 이벤트 기록 기능이 활성화된 이후부터 일자별로 채워집니다.")
    lines += [
        "",
        "## 해석 한계",
        "",
        "이 문서는 기록을 정리하는 도구입니다. 수익률은 종가의 단순 비교이며, 지수·종목의 구성 차이, 휴장일, 분할·배당, 통화, 데이터 정정 가능성을 통제하지 않습니다. 뉴스는 수집된 헤드라인의 카테고리 기록일 뿐 가격 변화의 원인이나 중요도 순위를 의미하지 않습니다.",
        "",
        "*This is research and analysis only, not personalized financial advice.*",
        "",
    ]
    folder = ROOT / "reviews" / kind
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / f"{key}.md"
    destination.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {destination.relative_to(ROOT)}")
    return destination


def group_snapshots(snapshots, kind):
    groups = defaultdict(list)
    for snap in snapshots:
        if kind == "weekly":
            iso = snap["date"].isocalendar()
            key = f"{iso.year}-W{iso.week:02d}"
        else:
            key = snap["date"].strftime("%Y-%m")
        groups[key].append(snap)
    return groups


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="보유한 모든 주·월 기간의 회고를 생성")
    args = parser.parse_args()
    snapshots = clean_history()
    if len(snapshots) < 2:
        raise SystemExit("회고를 만들기 위한 수집 스냅샷이 부족합니다.")
    for kind in ("weekly", "monthly"):
        groups = group_snapshots(snapshots, kind)
        keys = sorted(groups) if args.all else [sorted(groups)[-1]]
        for key in keys:
            write_review(kind, key, groups[key])


if __name__ == "__main__":
    main()
