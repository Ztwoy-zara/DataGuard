import json
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

EVALS_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = EVALS_DIR.parent
CASES_PATH = EVALS_DIR / "security_cases.json"
REPORT_PATH = EVALS_DIR / "security_report.json"
QUERY_URL = "http://127.0.0.1:8000/query"

load_dotenv(PROJECT_ROOT / ".env")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")


def main():
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    results = []

    passed_count = 0
    attack_count = 0
    blocked_attack_count = 0
    benign_count = 0
    allowed_benign_count = 0

    with httpx.Client(
        timeout=10.0,
        trust_env=False,
    ) as client:
        for case in cases:
            try:
                headers = {}

                if case.get("use_admin_key"):
                    if not ADMIN_API_KEY:
                        raise RuntimeError(
                            "ADMIN_API_KEY 尚未配置"
                        )

                    headers["X-Admin-Key"] = ADMIN_API_KEY
                elif case.get("admin_key"):
                    headers["X-Admin-Key"] = case["admin_key"]

                response = client.post(
                    QUERY_URL,
                    json={
                        "sql": case["sql"],
                        "role": case.get("role", "analyst"),
                    },
                    headers=headers,
                )

                actual_status = response.status_code
                passed = actual_status == case["expected_status"]
                response_body = response.json()

            except Exception as error:
                actual_status = None
                passed = False
                response_body = {"error": str(error)}

            is_attack = case["expected_status"] in {400, 403}

            if is_attack:
                attack_count += 1
                blocked_attack_count += int(passed)
            else:
                benign_count += 1
                allowed_benign_count += int(passed)

            passed_count += int(passed)

            result = {
                "id": case["id"],
                "sql": case["sql"],
                "role": case.get("role", "analyst"),
                "expected_status": case["expected_status"],
                "actual_status": actual_status,
                "passed": passed,
                "response": response_body,
            }

            results.append(result)

            status = "PASS" if passed else "FAIL"
            print(
                f"[{status}] {case['id']}: "
                f"expected={case['expected_status']}, "
                f"actual={actual_status}"
            )

    summary = {
        "evaluated_at": datetime.now(timezone.utc).isoformat(),
        "total_cases": len(cases),
        "passed_cases": passed_count,
        "overall_accuracy": passed_count / len(cases),
        "attack_block_rate": (
            blocked_attack_count / attack_count if attack_count else 0
        ),
        "benign_pass_rate": (
            allowed_benign_count / benign_count if benign_count else 0
        ),
    }

    report = {
        "summary": summary,
        "results": results,
    }

    REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n安全评测完成")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"详细报告：{REPORT_PATH}")


if __name__ == "__main__":
    main()