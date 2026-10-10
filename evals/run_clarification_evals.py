import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = PROJECT_ROOT / "evals" / "clarification_cases.json"
REPORT_PATH = PROJECT_ROOT / "evals" / "clarification_report.json"

sys.path.insert(0, str(PROJECT_ROOT))

from app.clarifier import detect_clarification


def load_cases() -> list[dict]:
    return json.loads(
        CASES_PATH.read_text(encoding="utf-8")
    )


def main():
    cases = load_cases()
    results = []

    true_positive = 0
    false_positive = 0
    false_negative = 0

    for case in cases:
        clarification = detect_clarification(
            case["question"]
        )

        actual_should_clarify = clarification is not None
        actual_reason = (
            clarification["reason"]
            if clarification
            else None
        )

        passed = (
            actual_should_clarify
            == case["should_clarify"]
            and actual_reason
            == case["expected_reason"]
        )

        if actual_should_clarify and case["should_clarify"]:
            true_positive += 1
        elif actual_should_clarify and not case["should_clarify"]:
            false_positive += 1
        elif not actual_should_clarify and case["should_clarify"]:
            false_negative += 1

        status = "PASS" if passed else "FAIL"

        print(
            f"[{status}] {case['id']} "
            f"- expected={case['expected_reason']}, "
            f"actual={actual_reason}"
        )

        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "passed": passed,
                "expected_should_clarify": case[
                    "should_clarify"
                ],
                "actual_should_clarify": actual_should_clarify,
                "expected_reason": case["expected_reason"],
                "actual_reason": actual_reason,
                "clarification_question": (
                    clarification["question"]
                    if clarification
                    else None
                ),
            }
        )

    passed_cases = sum(
        result["passed"]
        for result in results
    )

    precision = (
        true_positive
        / (true_positive + false_positive)
        if true_positive + false_positive
        else 0
    )

    recall = (
        true_positive
        / (true_positive + false_negative)
        if true_positive + false_negative
        else 0
    )

    f1_score = (
        2 * precision * recall / (precision + recall)
        if precision + recall
        else 0
    )

    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(results),
        "passed_cases": passed_cases,
        "accuracy": round(
            passed_cases / len(results),
            4,
        ) if results else 0,
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1_score": round(f1_score, 4),
    }

    report = {
        "summary": summary,
        "results": results,
    }

    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\n主动追问评测完成")
    print(
        json.dumps(
            summary,
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"详细报告：{REPORT_PATH}")


if __name__ == "__main__":
    main()