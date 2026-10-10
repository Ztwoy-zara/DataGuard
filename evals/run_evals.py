import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


EVALS_DIR = Path(__file__).resolve().parent
CASES_PATH = EVALS_DIR / "cases.json"
REPORT_PATH = EVALS_DIR / "report.json"
AGENT_URL = "http://127.0.0.1:8000/ask"


def normalize_rows(rows):
    normalized = [tuple(row) for row in rows]
    return sorted(normalized, key=str)


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    passed_answers = 0
    passed_columns = 0
    total_tokens = 0
    total_latency = 0.0

    with httpx.Client(
        timeout=120.0,
        trust_env=False,
    ) as client:
        for case in cases:
            started_at = time.perf_counter()

            try:
                response = client.post(
                    AGENT_URL,
                    json={"question": case["question"]},
                )
                response.raise_for_status()
                data = response.json()

                latency = time.perf_counter() - started_at
                answer_passed = normalize_rows(data["rows"]) == normalize_rows(
                    case["expected_rows"]
                )
                columns_passed = data["columns"] == case["expected_columns"]
                case_passed = (
                    answer_passed
                    and columns_passed
                )
                tokens = data["token_usage"]["total_tokens"]

                passed_answers += int(answer_passed)
                passed_columns += int(columns_passed)
                total_tokens += tokens
                total_latency += latency

                result = {
                    "id": case["id"],
                    "question": case["question"],
                    "passed": case_passed,
                    "answer_passed": answer_passed,
                    "columns_passed": columns_passed,
                    "sql": data["sql"],
                    "actual_columns": data["columns"],
                    "expected_columns": case["expected_columns"],
                    "actual_rows": data["rows"],
                    "expected_rows": case["expected_rows"],
                    "tokens": tokens,
                    "latency_seconds": round(latency, 3),
                    "error": None,
                }

            except Exception as error:
                latency = time.perf_counter() - started_at
                total_latency += latency

                result = {
                    "id": case["id"],
                    "question": case["question"],
                    "passed": False,
                    "answer_passed": False,
                    "columns_passed": False,
                    "sql": None,
                    "actual_columns": None,
                    "expected_columns": case["expected_columns"],
                    "actual_rows": None,
                    "expected_rows": case["expected_rows"],
                    "tokens": 0,
                    "latency_seconds": round(latency, 3),
                    "error": str(error),
                }

            results.append(result)

            status = "PASS" if result["passed"] else "FAIL"
            print(f"[{status}] {case['id']} - {case['question']}")

            if not result["columns_passed"]:
                print(
                    f"  expected_columns="
                    f"{result['expected_columns']}"
                )
                print(
                    f"  actual_columns="
                    f"{result['actual_columns']}"
                )
    total_cases = len(cases)

    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": total_cases,
        "answer_accuracy": passed_answers / total_cases,
        "column_accuracy": passed_columns / total_cases,
        "total_tokens": total_tokens,
        "average_tokens": total_tokens / total_cases,
        "average_latency_seconds": round(total_latency / total_cases, 3),
    }

    report = {
        "summary": summary,
        "results": results,
    }

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n评测完成")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"详细报告：{REPORT_PATH}")


if __name__ == "__main__":
    main()