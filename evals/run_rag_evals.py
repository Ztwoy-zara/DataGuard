import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CASES_PATH = PROJECT_ROOT / "evals" / "rag_cases.json"
REPORT_PATH = PROJECT_ROOT / "evals" / "rag_report.json"

sys.path.insert(0, str(PROJECT_ROOT))

from app.retriever import retrieve_knowledge


def load_cases() -> list[dict]:
    return json.loads(
        CASES_PATH.read_text(encoding="utf-8")
    )


def main():
    cases = load_cases()
    results = []

    for case in cases:
        start_time = time.perf_counter()

        documents = retrieve_knowledge(
            case["question"],
            top_k=3,
        )

        latency_seconds = time.perf_counter() - start_time
        retrieved_ids = [
            document["id"]
            for document in documents
        ]

        matching_ranks = [
            index + 1
            for index, document_id in enumerate(retrieved_ids)
            if document_id in case["expected_ids"]
        ]

        passed = bool(matching_ranks)
        first_relevant_rank = (
            min(matching_ranks)
            if matching_ranks
            else None
        )
        reciprocal_rank = (
            1 / first_relevant_rank
            if first_relevant_rank
            else 0
        )

        status = "PASS" if passed else "FAIL"
        print(
            f"[{status}] {case['id']} "
            f"- retrieved={retrieved_ids}"
        )

        results.append(
            {
                "id": case["id"],
                "question": case["question"],
                "passed": passed,
                "expected_ids": case["expected_ids"],
                "retrieved": [
                    {
                        "id": document["id"],
                        "title": document["title"],
                        "score": document["score"],
                    }
                    for document in documents
                ],
                "first_relevant_rank": first_relevant_rank,
                "reciprocal_rank": round(reciprocal_rank, 4),
                "latency_seconds": round(latency_seconds, 4),
            }
        )

    passed_cases = sum(
        result["passed"]
        for result in results
    )

    mean_reciprocal_rank = (
        sum(result["reciprocal_rank"] for result in results)
        / len(results)
        if results
        else 0
    )

    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(results),
        "passed_cases": passed_cases,
        "hit_rate_at_3": round(
            passed_cases / len(results),
            4,
        ) if results else 0,
        "mean_reciprocal_rank": round(
            mean_reciprocal_rank,
            4,
        ),
        "average_latency_seconds": round(
            sum(
                result["latency_seconds"]
                for result in results
            ) / len(results),
            4,
        ) if results else 0,
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

    print("\nRAG 评测完成")
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