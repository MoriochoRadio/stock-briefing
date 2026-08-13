"""현재 data.json에서 이벤트 기록의 첫 스냅샷을 생성한다.

네트워크 호출 없이 이미 수집된 데이터만 사용한다. 이후에는 fetch_data.py가 같은 형식으로
날짜별 이벤트 기록을 갱신한다.
"""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FETCH_PATH = ROOT / "scripts" / "fetch_data.py"

spec = importlib.util.spec_from_file_location("fetch_data", FETCH_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError("fetch_data 모듈을 불러올 수 없습니다.")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

source = ROOT / "data.json"
if source.exists():
    data = json.loads(source.read_text(encoding="utf-8"))
else:
    # 자동화가 data.json을 커밋하지 않는 경우에도 현재 공개 뉴스 스냅샷으로 초기화한다.
    news_path = ROOT / "site" / "src" / "data" / "news.json"
    if not news_path.exists():
        raise FileNotFoundError("data.json과 news.json이 모두 없어 이벤트 기록을 초기화할 수 없습니다.")
    news = json.loads(news_path.read_text(encoding="utf-8"))
    data = {
        "date_kst": news.get("asOf"),
        "generated_at": "",
        "news": [
            {
                "title": item.get("title", ""),
                "source": item.get("source", ""),
                "link": item.get("link", ""),
                "pub": item.get("pub", ""),
                "category": item.get("cat", ""),
            }
            for item in news.get("items", [])
        ],
    }

if not data.get("date_kst"):
    raise ValueError("이벤트 기록에 사용할 수집 기준일이 없습니다.")
module.build_event_ledger(data)
print(f"seeded event ledger for {data['date_kst']}")
