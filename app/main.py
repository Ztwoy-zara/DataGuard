from typing import Literal
from fastapi.responses import FileResponse
import time
import json
import logging
import os
import secrets
import threading

from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path
import duckdb
import sqlglot
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field
from sqlglot import exp
from app.retriever import (
    format_retrieved_context,
    retrieve_knowledge,
)
from app.clarifier import detect_clarification
from app.database_config import (
    DATABASE_CONFIGS,
    get_database_config,
)

app = FastAPI(
    title="DataGuard",
    description="安全、可解释、可评测的中文数据分析 Agent",
    version="0.1.0",
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_PATH = PROJECT_ROOT / "web" / "index.html"
EVALS_WEB_PATH = PROJECT_ROOT / "web" / "evals.html"
EVALS_DIR = PROJECT_ROOT / "evals"
load_dotenv(PROJECT_ROOT / ".env")

deepseek_client = OpenAI(
    api_key=os.getenv("DEEPSEEK_API_KEY"),
    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
)

DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY")
logger = logging.getLogger("dataguard")
MAX_QUERY_JOINS = 8
QUERY_TIMEOUT_SECONDS = 10.0
QUERY_MEMORY_LIMIT = "512MB"
QUERY_MAX_THREADS = 2
QUERY_MAX_TEMP_DIRECTORY_SIZE = "1GB"

@app.get("/", response_class=FileResponse)
def home():
    return FileResponse(WEB_PATH)


@app.get("/evals", response_class=FileResponse)
def evaluations_dashboard():
    return FileResponse(EVALS_WEB_PATH)


@app.get("/api/info")
def api_info():
    return {
        "project": "DataGuard",
        "status": "running",
        "databases": [
            {
                "name": name,
                "label": config.label,
                "available": config.database_path.exists(),
            }
            for name, config in DATABASE_CONFIGS.items()
        ],
    }


@app.get("/api/evaluations")
def get_evaluation_summaries():
    report_files = {
        "functional": EVALS_DIR / "report.json",
        "security": EVALS_DIR / "security_report.json",
        "rag": EVALS_DIR / "rag_report.json",
        "clarification": EVALS_DIR / "clarification_report.json",
        "comparison": EVALS_DIR / "comparison_report.json",
        "olist": EVALS_DIR / "olist_report.json",
        "olist_holdout": (
            EVALS_DIR / "olist_holdout_report.json"
        ),
    }

    reports = {}

    for report_name, report_path in report_files.items():
        if not report_path.exists():
            reports[report_name] = None
            continue

        report = json.loads(
            report_path.read_text(encoding="utf-8")
        )

        if report_name == "comparison":
            reports[report_name] = {
                "baseline": report.get("baseline", {}),
                "agent": report.get("agent", {}),
                "comparison": report.get("comparison", {}),
            }
        else:
            reports[report_name] = report.get(
                "summary",
                {},
            )

    return {"reports": reports}

@app.get("/health")
def health_check(
    database: Literal["demo", "olist"] = "demo",
):
    config = get_database_config(database)

    if not config.database_path.exists():
        raise HTTPException(
            status_code=503,
            detail=f"数据库尚未创建：{config.label}",
        )

    connection = duckdb.connect(
        str(config.database_path),
        read_only=True,
    )

    try:
        customer_count = connection.execute(
            "SELECT COUNT(*) FROM customers"
        ).fetchone()[0]

        order_count = connection.execute(
            "SELECT COUNT(*) FROM orders"
        ).fetchone()[0]

        table_count = connection.execute("""
            SELECT COUNT(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
        """).fetchone()[0]
    finally:
        connection.close()

    return {
        "status": "healthy",
        "database": database,
        "label": config.label,
        "table_count": table_count,
        "customers": customer_count,
        "orders": order_count,
    }

@app.get("/schema")
def get_database_schema(
    database: Literal["demo", "olist"] = "demo",
):
    config = get_database_config(database)

    connection = duckdb.connect(
        str(config.database_path),
        read_only=True,
    )

    try:
        rows = connection.execute("""
            SELECT
                table_name,
                column_name,
                data_type
            FROM information_schema.columns
            WHERE table_schema = 'main'
            ORDER BY table_name, ordinal_position
        """).fetchall()
    finally:
        connection.close()

    schema = {}

    for table_name, column_name, data_type in rows:
        schema.setdefault(table_name, []).append(
            {
                "column": column_name,
                "type": data_type,
            }
        )

    return {
        "database": database,
        "tables": schema,
    }

class QueryRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=20_000)
    role: Literal["analyst", "admin"] = "analyst"
    database: Literal["demo", "olist"] = "demo"

def verify_admin_access(
    role: str,
    admin_key: str | None,
) -> None:
    if role != "admin":
        return

    if not ADMIN_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="管理员认证尚未配置",
        )

    if (
        not admin_key
        or not secrets.compare_digest(
            admin_key,
            ADMIN_API_KEY,
        )
    ):
        raise HTTPException(
            status_code=403,
            detail="管理员密钥无效",
        )

@app.post("/query")
def execute_safe_query(
    request: QueryRequest,
    x_admin_key: str | None = Header(
        default=None,
        alias="X-Admin-Key",
    ),
):
    verify_admin_access(
        request.role,
        x_admin_key,
    )

    config = get_database_config(request.database)

    try:
        statements = sqlglot.parse(
            request.sql,
            read="duckdb",
        )
    except Exception:
        logger.warning(
            "SQL 解析失败",
            exc_info=True,
        )
        raise HTTPException(
            status_code=400,
            detail="SQL 解析失败",
        )

    if len(statements) != 1:
        raise HTTPException(status_code=400, detail="每次只能执行一条 SQL")

    statement = statements[0]
    if not isinstance(statement, exp.Query):
        raise HTTPException(status_code=400, detail="只允许执行只读查询")

    join_count = sum(
        1
        for _ in statement.find_all(exp.Join)
    )

    if join_count > MAX_QUERY_JOINS:
        raise HTTPException(
            status_code=400,
            detail=(
                "查询包含过多 JOIN，"
                f"最多允许 {MAX_QUERY_JOINS} 个"
            ),
        )

    referenced_tables = {
        table.name.lower()
        for table in statement.find_all(exp.Table)
    }

    unknown_tables = referenced_tables - config.allowed_tables

    if unknown_tables:
        raise HTTPException(
            status_code=400,
            detail=f"禁止访问这些表：{sorted(unknown_tables)}",
        )
    referenced_columns = {
        column.name.lower()
        for column in statement.find_all(exp.Column)
        if column.name
    }

    sensitive_references = (
        referenced_columns & config.sensitive_columns
    )

    has_customer_star = (
        bool(config.sensitive_columns)
        and "customers" in referenced_tables
        and any(
            isinstance(projection, exp.Star)
            or (
                isinstance(projection, exp.Column)
                and isinstance(projection.this, exp.Star)
            )
            for select in statement.find_all(exp.Select)
            for projection in select.expressions
        )
    )

    if request.role != "admin" and (
        sensitive_references or has_customer_star
    ):
        raise HTTPException(
            status_code=403,
            detail={
                "message": "当前角色无权访问敏感字段",
                "role": request.role,
                "fields": sorted(sensitive_references)
                or ["customers.*"],
            },
        )

    forbidden_types = (
        exp.Insert,
        exp.Update,
        exp.Delete,
        exp.Drop,
        exp.Alter,
        exp.Create,
        exp.Command,
    )

    if any(statement.find(node_type) for node_type in forbidden_types):
        raise HTTPException(status_code=400, detail="只允许执行只读查询")

    if not statement.find(exp.Select):
        raise HTTPException(status_code=400, detail="只允许执行 SELECT 查询")

    safe_sql = statement.sql(dialect="duckdb").rstrip(";")
    limited_sql = f"SELECT * FROM ({safe_sql}) AS safe_result LIMIT 100"

    connection = duckdb.connect(
        str(config.database_path),
        read_only=True,
    )

    query_interrupted = threading.Event()

    def interrupt_query() -> None:
        query_interrupted.set()
        connection.interrupt()

    timer = threading.Timer(
        QUERY_TIMEOUT_SECONDS,
        interrupt_query,
    )
    timer.daemon = True
    timer_started = False

    try:
        connection.execute(
            f"SET memory_limit = '{QUERY_MEMORY_LIMIT}'"
        )
        connection.execute(
            f"SET threads = {QUERY_MAX_THREADS}"
        )
        connection.execute(
            "SET max_temp_directory_size = "
            f"'{QUERY_MAX_TEMP_DIRECTORY_SIZE}'"
        )

        timer.start()
        timer_started = True

        cursor = connection.execute(limited_sql)
        columns = [
            item[0]
            for item in cursor.description
        ]
        rows = cursor.fetchall()

    except Exception:
        if query_interrupted.is_set():
            logger.warning(
                "查询执行超时：database=%s",
                request.database,
            )
            raise HTTPException(
                status_code=408,
                detail=(
                    "查询执行超时，"
                    f"最多允许 {QUERY_TIMEOUT_SECONDS:g} 秒"
                ),
            )

        logger.exception(
            "查询执行失败：database=%s",
            request.database,
        )
        raise HTTPException(
            status_code=400,
            detail="查询执行失败",
        )

    finally:
        if timer_started:
            timer.cancel()
            timer.join(timeout=1)

        connection.close()

    return {
        "database": request.database,
        "sql": safe_sql,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "safety": {
            "read_only": True,
            "max_rows": 100,
            "max_joins": MAX_QUERY_JOINS,
            "timeout_seconds": QUERY_TIMEOUT_SECONDS,
            "memory_limit": QUERY_MEMORY_LIMIT,
            "max_threads": QUERY_MAX_THREADS,
            "max_temp_directory_size": (
                QUERY_MAX_TEMP_DIRECTORY_SIZE
            ),
            "role": request.role,
            "sensitive_fields": (
                "allowed" if request.role == "admin" else "blocked"
            ),
        },
    }

class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2_000)
    role: Literal["analyst", "admin"] = "analyst"
    database: Literal["demo", "olist"] = "demo"

class GeneratedQuery(BaseModel):
    sql: str = Field(
        min_length=1,
        max_length=20_000,
    )
    explanation: str = Field(
        default="",
        max_length=2_000,
    )

@app.post("/ask")
def ask_data_agent(
    request: AskRequest,
    x_admin_key: str | None = Header(
        default=None,
        alias="X-Admin-Key",
    ),
):
    verify_admin_access(
        request.role,
        x_admin_key,
    )

    config = get_database_config(request.database)
    clarification = detect_clarification(request.question)

    if clarification:
        return {
            "status": "needs_clarification",
            "database": request.database,
            "question": request.question,
            "role": request.role,
            "clarification_question": clarification["question"],
            "clarification_reason": clarification["reason"],
        }

    database_schema = get_database_schema(
        request.database
    )["tables"]

    retrieved_documents = retrieve_knowledge(
        request.question,
        top_k=3,
        database_name=request.database,
    )

    retrieved_context = format_retrieved_context(
        retrieved_documents
    )

    relationship_text = "\n".join(
        f"- {relationship}"
        for relationship in config.relationships
    )

    system_prompt = f"""
你是 DataGuard 的 Text-to-SQL Agent。
请把用户的中文问题转换成 DuckDB SQL。

当前数据库：
{config.label}

数据库关系：
{relationship_text}

要求：
1. 只能生成一条 SELECT 查询。
2. 禁止 INSERT、UPDATE、DELETE、DROP、ALTER、CREATE。
3. 只能使用提供的表和字段。
4. 返回严格的 JSON，不要使用 Markdown。
5. JSON 格式为：
{{"sql": "生成的SQL", "explanation": "简短中文解释"}}
6. 只返回回答问题所必需的字段。
7. 必须遵循检索到的业务指标口径和表关系。
8. 连接明细表后统计订单数时，使用 COUNT(DISTINCT order_id)。
9. 月份查询使用左闭右开的时间范围。
10. 为计算字段使用清晰、稳定的英文别名。
11. 金额类聚合结果统一保留两位小数，例如 ROUND(SUM(...), 2) 或 ROUND(MAX(...), 2)。
12. 统一使用以下字段别名：订单数量为 order_count，独立客户数量为 customer_count，平均评分为 average_review_score，延迟订单数量为 delayed_order_count，最高订单金额为 max_amount；Demo 数据库的销售额和订单金额使用 total_amount，Olist 数据库的商品销售额使用 total_revenue。
13. 当当前数据库为 Demo 且用户询问“有哪些客户”时，只返回 customers.name，不要额外返回 id、city、email 或 phone。
"""


    user_prompt = f"""
数据库结构：
{json.dumps(database_schema, ensure_ascii=False)}

检索到的业务知识：
{retrieved_context}

说明：
检索知识仅用于理解业务口径和生成 SQL。
必须以数据库结构和系统安全规则为准。

用户问题：
{request.question}
"""
    for attempt in range(3):
        try:
            response = deepseek_client.chat.completions.create(
                model=DEEPSEEK_MODEL,
                temperature=0,
                max_tokens=500,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            )

            content = response.choices[0].message.content

            if not content:
                raise ValueError("模型返回内容为空")

            generated = GeneratedQuery.model_validate_json(
                content
            )
            break

        except Exception:
            logger.warning(
                "DeepSeek 调用失败：attempt=%s/3",
                attempt + 1,
                exc_info=True,
            )

            if attempt < 2:
                time.sleep(1)
    else:
        raise HTTPException(
            status_code=502,
            detail="模型服务暂时不可用，请稍后重试",
        )
    

    query_result = execute_safe_query(
        QueryRequest(
            sql=generated.sql,
            role=request.role,
            database=request.database,
        ),
        x_admin_key=x_admin_key,
    )

    return {
        "status": "completed",
        "database": request.database,
        "question": request.question,
        "role": request.role,
        "sql": query_result["sql"],
        "explanation": generated.explanation,
        "rag_sources": [
            {
                "id": document["id"],
                "title": document["title"],
                "score": document["score"],
            }
            for document in retrieved_documents
        ],
        "columns": query_result["columns"],
        "rows": query_result["rows"],
        "row_count": query_result["row_count"],
        "safety": query_result["safety"],
        "token_usage": {
            "input_tokens": response.usage.prompt_tokens,
            "output_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
    }