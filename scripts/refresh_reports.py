"""현재 로컬 데이터로 결과 설명자료를 갱신한다. ZIP·API·평가용 키는 다루지 않는다."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def main():
    from check_offline import block_external_connections

    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "JEJU_HUB_PROJECT_KEY"):
        os.environ[key] = ""
    block_external_connections()
    from build_submission import result_report
    from evaluate import evaluate, to_markdown
    from src.data_pipeline import load_store

    store = load_store()
    evaluation = to_markdown(evaluate())
    (ROOT / "docs/evaluation_result.md").write_text(evaluation, encoding="utf-8")
    (ROOT / "docs/result_report.md").write_text(result_report(store, evaluation), encoding="utf-8")
    print(f"Reports updated: sample={store.is_sample}, monthly={len(store.monthly)}, weekday={len(store.weekday)}")


if __name__ == "__main__":
    main()
