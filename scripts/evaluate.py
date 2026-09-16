from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.local_rag import LocalRAG  # noqa: E402


def main() -> None:
    rag = LocalRAG.from_directory(ROOT / "data" / "clean")
    cases = json.loads((ROOT / "evaluation" / "questions.json").read_text())
    hits = 0
    refusals = 0
    for case in cases:
        response = rag.ask(case["question"])
        sources = {item["source"] for item in response["sources"]}
        if case["expected_source"] in sources:
            hits += 1
        if case["expected_source"] is None and not sources:
            hits += 1
            refusals += 1
        print(f"{'PASS' if (case['expected_source'] in sources or (case['expected_source'] is None and not sources)) else 'FAIL'} | {case['question']}")
    print(f"\nRetrieval/refusal accuracy: {hits}/{len(cases)} ({hits / len(cases):.1%})")
    print(f"Correct out-of-scope refusals: {refusals}")


if __name__ == "__main__":
    main()

