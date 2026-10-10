import json
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx


EVALS_DIR = Path(__file__).resolve().parent
CASES_PATH = EVALS_DIR / "olist_cases.json"
REPORT_PATH = EVALS_DIR / "olist_report.json"
AGENT_URL = "http://127.0.0.1:8000/ask"


def normalize_value(value):
    if isinstance(value, float):
        return round(value, 4)

    return value


def normalize_rows(rows):
    normalized = [
        tuple(normalize_value(value) for value in row)
        for row in rows
    ]

    return sorted(normalized, key=str)

def request_agent(
    client: httpx.Client,
    case: dict,
    max_attempts: int = 3,
) -> dict:
    last_error = None

    for attempt in range(1, max_attempts + 1):
        try:
            response = client.post(
                AGENT_URL,
                json={
                    "question": case["question"],
                    "role": "analyst",
                    "database": "olist",
                },
            )

            if response.status_code >= 500:
                last_error = (
                    f"HTTP {response.status_code}: "
                    f"{response.text}"
                )

                if attempt < max_attempts:
                    print(
                        f"  第 {attempt} 次请求失败，"
                        "准备重试……"
                    )
                    time.sleep(1)
                    continue

                raise RuntimeError(last_error)

            response.raise_for_status()
            data = response.json()

            if data.get("status") != "completed":
                raise ValueError(
                    f"Agent 未完成查询：{data}"
                )

            return data

        except httpx.RequestError as error:
            last_error = str(error)

            if attempt < max_attempts:
                print(
                    f"  第 {attempt} 次网络请求失败，"
                    "准备重试……"
                )
                time.sleep(1)
                continue

            raise RuntimeError(last_error) from error

    raise RuntimeError(last_error or "请求失败")

def main():
    cases = json.loads(
        CASES_PATH.read_text(encoding="utf-8")
    )

    results = []
    passed_cases = 0
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
                data = request_agent(client, case)

                latency = time.perf_counter() - started_at

                answer_passed = (
                    normalize_rows(data["rows"])
                    == normalize_rows(case["expected_rows"])
                )
                columns_passed = (
                    data["columns"]
                    == case["expected_columns"]
                )
                passed = answer_passed and columns_passed

                tokens = data["token_usage"]["total_tokens"]

                passed_cases += int(passed)
                passed_answers += int(answer_passed)
                passed_columns += int(columns_passed)
                total_tokens += tokens
                total_latency += latency

                result = {
                    "id": case["id"],
                    "question": case["question"],
                    "passed": passed,
                    "answer_passed": answer_passed,
                    "columns_passed": columns_passed,
                    "database": data.get("database"),
                    "sql": data["sql"],
                    "rag_source_ids": [
                        source["id"]
                        for source in data.get(
                            "rag_sources",
                            [],
                        )
                    ],
                    "actual_columns": data["columns"],
                    "expected_columns": (
                        case["expected_columns"]
                    ),
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
                    "database": "olist",
                    "sql": None,
                    "rag_source_ids": [],
                    "actual_columns": None,
                    "expected_columns": (
                        case["expected_columns"]
                    ),
                    "actual_rows": None,
                    "expected_rows": case["expected_rows"],
                    "tokens": 0,
                    "latency_seconds": round(latency, 3),
                    "error": str(error),
                }

            results.append(result)

            status = "PASS" if result["passed"] else "FAIL"

            print(
                f"[{status}] {case['id']} - "
                f"{case['question']}"
            )

            if not result["passed"]:
                print(
                    "  expected_columns="
                    f"{result['expected_columns']}"
                )
                print(
                    "  actual_columns="
                    f"{result['actual_columns']}"
                )
                print(
                    f"  error={result['error']}"
                )

    total_cases = len(cases)

    summary = {
        "evaluated_at": (
            datetime.now(timezone.utc).isoformat()
        ),
        "database": "olist",
        "total_cases": total_cases,
        "passed_cases": passed_cases,
        "overall_accuracy": (
            passed_cases / total_cases
        ),
        "answer_accuracy": (
            passed_answers / total_cases
        ),
        "column_accuracy": (
            passed_columns / total_cases
        ),
        "total_tokens": total_tokens,
        "average_tokens": (
            total_tokens / total_cases
        ),
        "average_latency_seconds": round(
            total_latency / total_cases,
            3,
        ),
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

    print("\nOlist 大数据库评测完成")
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