"""GitHub Actions 워크플로의 기본 구조를 외부 실행 없이 검증한다."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

for name in ("daily.yml", "intraday_kr.yml"):
    path = ROOT / ".github" / "workflows" / name
    workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
    jobs = workflow.get("jobs", {})
    assert "deploy" in jobs, f"{name}: deploy job 누락"
    deploy = jobs["deploy"]
    assert deploy.get("concurrency", {}).get("group") == "pages-deploy", f"{name}: Pages 직렬화 설정 누락"
    assert any(step.get("uses", "").startswith("actions/checkout") for step in deploy["steps"]), f"{name}: deploy checkout 누락"
    assert any(step.get("uses", "").startswith("actions/deploy-pages") for step in deploy["steps"]), f"{name}: Pages 배포 단계 누락"

intraday = yaml.safe_load((ROOT / ".github" / "workflows" / "intraday_kr.yml").read_text(encoding="utf-8"))
assert intraday["jobs"]["deploy"].get("if") == "needs.intraday.outputs.captured == 'true'", "인트라데이 빈 스냅샷 배포 차단 누락"

print("workflow validation: OK")
