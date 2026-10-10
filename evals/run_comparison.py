import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import OpenAI


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = PROJECT_ROOT / "evals" / "cases.json"
REPORT_PATH = PROJECT_ROOT / "evals" / "comparison_report.json"

AGENT_URL = "http://127.0.0.1:8000/ask"
QUERY_URL = "http://127.0.0.1:8000/query"
SCHEMA_URL = "http://127.0.0.1:8000/schema"

load_dotenv(PROJECT_ROOT / ".env")

deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv(
        "DEEPSEEK_BASE_URL",
        "https://api.deepseek.com",
    ),
)

DEEPSEEK_MODEL = os.getenv(
    "DEEPSEEK_MODEL",
    "deepseek-flash",
)


def normalize_rows(rows):
    normalized = [tuple(row) for row in rows]
    return sorted(normalized, key=str)


def evaluate_response(data, case):
    answer_passed = (
        normalize_rows(data["rows"])
        == normalize_rows(case["expected_rows"])
    )

    columns_passed = (
        data["columns"]
        == case["expected_columns"]
    )

    return answer_passed, columns_passed


def run_baseline(case, database_schema, http_client):
    started_at = time.perf_counter()

    try:
        prompt = f"""
请把用户的中文问题转换成一条 DuckDB SELECT 查询。

只返回严格 JSON：
{{"sql": "生成的SQL"}}

数据库结构：
{json.dumps(database_schema, ensure_ascii=False)}

用户问题：
{case["question"]}
"""

        response = deepseek_client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            temperature=0,
            max_tokens=300,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "user",
                    "content": prompt,
                }
            ],
        )

        content = response.choices[0].message.content

        if not content:
            raise ValueError("Baseline 模型返回内容为空")

        generated = json.loads(content)

        if "sql" not in generated:
            raise ValueError("Baseline 模型没有返回 SQL")

        query_response = http_client.post(
            QUERY_URL,
            json={
                "sql": generated["sql"],
                "role": "analyst",
            },
        )
        query_response.raise_for_status()
        query_data = query_response.json()

        latency = time.perf_counter() - started_at
        answer_passed, columns_passed = evaluate_response(
            query_data,
            case,
        )

        return {
            "passed": answer_passed,
            "columns_passed": columns_passed,
            "sql": query_data["sql"],
            "actual_rows": query_data["rows"],
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
            "latency_seconds": round(latency, 3),
            "error": None,
        }

    except Exception as error:
        latency = time.perf_counter() - started_at

        return {
            "passed": False,
            "columns_passed": False,
            "sql": None,
            "actual_rows": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": round(latency, 3),
            "error": str(error),
        }


def run_agent(case, http_client):
    started_at = time.perf_counter()

    try:
        response = http_client.post(
            AGENT_URL,
            json={
                "question": case["question"],
                "role": "analyst",
            },
        )
        response.raise_for_status()
        data = response.json()

        if data.get("status") != "completed":
            raise ValueError(
                "Agent 没有返回完整查询结果"
            )

        latency = time.perf_counter() - started_at
        answer_passed, columns_passed = evaluate_response(
            data,
            case,
        )

        return {
            "passed": answer_passed,
            "columns_passed": columns_passed,
            "sql": data["sql"],
            "actual_rows": data["rows"],
            "input_tokens": data["token_usage"][
                "input_tokens"
            ],
            "output_tokens": data["token_usage"][
                "output_tokens"
            ],
            "total_tokens": data["token_usage"][
                "total_tokens"
            ],
            "latency_seconds": round(latency, 3),
            "rag_sources": data.get("rag_sources", []),
            "error": None,
        }

    except Exception as error:
        latency = time.perf_counter() - started_at

        return {
            "passed": False,
            "columns_passed": False,
            "sql": None,
            "actual_rows": None,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "latency_seconds": round(latency, 3),
            "rag_sources": [],
            "error": str(error),
        }


def summarize(results):
    total_cases = len(results)

    if total_cases == 0:
        return {
            "total_cases": 0,
            "answer_accuracy": 0,
            "column_accuracy": 0,
            "total_tokens": 0,
            "average_tokens": 0,
            "average_latency_seconds": 0,
        }

    total_tokens = sum(
        result["total_tokens"]
        for result in results
    )

    return {
        "total_cases": total_cases,
        "answer_accuracy": round(
            sum(result["passed"] for result in results)
            / total_cases,
            4,
        ),
        "column_accuracy": round(
            sum(
                result["columns_passed"]
                for result in results
            ) / total_cases,
            4,
        ),
        "total_input_tokens": sum(
            result["input_tokens"]
            for result in results
        ),
        "total_output_tokens": sum(
            result["output_tokens"]
            for result in results
        ),
        "total_tokens": total_tokens,
        "average_tokens": round(
            total_tokens / total_cases,
            2,
        ),
        "average_latency_seconds": round(
            sum(
                result["latency_seconds"]
                for result in results
            ) / total_cases,
            3,
        ),
    }


def percentage_change(new_value, old_value):
    if old_value == 0:
        return None

    return round(
        (new_value - old_value) / old_value * 100,
        2,
    )


def main():
    cases = json.loads(
        CASES_PATH.read_text(encoding="utf-8")
    )

    baseline_results = []
    agent_results = []
    case_results = []

    with httpx.Client(
        timeout=90.0,
        trust_env=False,
    ) as http_client:
        schema_response = http_client.get(SCHEMA_URL)
        schema_response.raise_for_status()
        database_schema = schema_response.json()["tables"]

        for case in cases:
            baseline = run_baseline(
                case,
                database_schema,
                http_client,
            )

            agent = run_agent(
                case,
                http_client,
            )

            baseline_results.append(baseline)
            agent_results.append(agent)

            baseline_status = (
                "PASS" if baseline["passed"] else "FAIL"
            )
            agent_status = (
                "PASS" if agent["passed"] else "FAIL"
            )

            print(
                f"{case['id']}: "
                f"baseline={baseline_status}, "
                f"agent={agent_status}"
            )

            case_results.append(
                {
                    "id": case["id"],
                    "question": case["question"],
                    "expected_columns": case[
                        "expected_columns"
                    ],
                    "expected_rows": case[
                        "expected_rows"
                    ],
                    "baseline": baseline,
                    "agent": agent,
                }
            )

    baseline_summary = summarize(baseline_results)
    agent_summary = summarize(agent_results)

    comparison = {
        "answer_accuracy_gain": round(
            agent_summary["answer_accuracy"]
            - baseline_summary["answer_accuracy"],
            4,
        ),
        "column_accuracy_gain": round(
            agent_summary["column_accuracy"]
            - baseline_summary["column_accuracy"],
            4,
        ),
        "token_change_percent": percentage_change(
            agent_summary["average_tokens"],
            baseline_summary["average_tokens"],
        ),
        "latency_change_percent": percentage_change(
            agent_summary["average_latency_seconds"],
            baseline_summary["average_latency_seconds"],
        ),
    }

    report = {
        "evaluated_at": datetime.now(
            timezone.utc
        ).isoformat(),
        "baseline": baseline_summary,
        "agent": agent_summary,
        "comparison": comparison,
        "results": case_results,
    }

    REPORT_PATH.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print("\nBaseline 与 Agent 对比完成")
    print(
        json.dumps(
            {
                "baseline": baseline_summary,
                "agent": agent_summary,
                "comparison": comparison,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"详细报告：{REPORT_PATH}")


if __name__ == "__main__":
    main()