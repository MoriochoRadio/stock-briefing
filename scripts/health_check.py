"""'사람이 조치해야 하는' 상태만 골라 GitHub Actions 출력(alerts)으로 내보낸다.

대상: LLM 키 인증 실패·쓸 수 있는 모델 없음·키 미설정(generate.py가 quality.json llm.alerts에 기록),
      시세 그룹 수집 0건이 ZERO_STREAK_ALERT일 연속(fetch_data.py가 quality.json zeroStreaks에 기록).
비대상: 429/5xx 같은 일시 오류, 하루짜리 NaN/누락 — 스스로 회복되므로 메일로 깨우지 않는다.
이 스크립트는 항상 0으로 끝난다. 워크플로 마지막 job이 alerts가 있을 때만(커밋·배포가 끝난 뒤)
::error::와 exit 1로 실패 메일을 보낸다."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ZERO_STREAK_ALERT = 3


def collect_alerts(quality):
    alerts = [str(a) for a in ((quality.get("llm") or {}).get("alerts") or [])]
    for s in (quality.get("zeroStreaks") or {}).values():
        if s.get("days", 0) >= ZERO_STREAK_ALERT:
            alerts.append(
                f"{s.get('label')} 수집 0/{s.get('expected')}이 {s['days']}일 연속({s.get('since')}~) "
                "— Yahoo/yfinance 응답 변화 여부 확인 필요"
            )
    return alerts


def main():
    path = ROOT / "site" / "src" / "data" / "quality.json"
    try:
        quality = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[warn] quality.json 읽기 실패({e}) — 점검 생략")
        quality = {}
    alerts = collect_alerts(quality)
    for a in alerts:
        print(f"[alert] {a}")
    print(f"health: {len(alerts)} alert(s)")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            if alerts:
                fh.write("alerts<<__ALERTS__\n" + "\n".join(a.replace("\n", " ") for a in alerts) + "\n__ALERTS__\n")
            else:
                fh.write("alerts=\n")


if __name__ == "__main__":
    main()
