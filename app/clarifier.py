import re


TIME_PATTERN = re.compile(
    r"("
    r"\d{4}年"
    r"|\d{1,2}月"
    r"|\d{4}-\d{1,2}-\d{1,2}"
    r"|本月|上月|下月"
    r"|今年|去年|明年"
    r"|本季度|上季度"
    r"|近\s*\d+\s*(天|周|个月|月|年)"
    r"|最近\s*\d+\s*(天|周|个月|月|年)"
    r"|过去\s*\d+\s*(天|周|个月|月|年)"
    r"|从.+到.+"
    r")"
)


def has_explicit_time_range(question: str) -> bool:
    return bool(TIME_PATTERN.search(question))


def detect_clarification(question: str) -> dict | None:
    normalized = question.strip()

    active_customer_terms = (
        "活跃客户",
        "活跃用户",
        "有消费的客户",
        "下过单的客户",
    )

    if (
        any(term in normalized for term in active_customer_terms)
        and not has_explicit_time_range(normalized)
    ):
        return {
            "reason": "missing_time_range",
            "question": "请问需要统计哪个时间范围内的活跃客户？例如最近30天或2026年9月。",
        }

    vague_time_terms = (
        "最近",
        "近期",
        "这段时间",
        "一段时间",
    )

    if (
        any(term in normalized for term in vague_time_terms)
        and not has_explicit_time_range(normalized)
    ):
        return {
            "reason": "ambiguous_time_range",
            "question": "请提供明确的时间范围，例如最近30天、2026年9月或2026年第三季度。",
        }

    vague_customer_terms = (
        "最好的客户",
        "优质客户",
        "最重要的客户",
        "最有价值的客户",
    )

    if any(term in normalized for term in vague_customer_terms):
        return {
            "reason": "ambiguous_metric",
            "question": "请问希望按照消费总额、订单数量，还是最近活跃时间判断客户价值？",
        }

    return None