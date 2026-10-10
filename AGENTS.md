# AGENTS.md

## 项目概述

DataGuard 是一个安全、可解释、可评测的中文数据分析 Agent。

本项目不使用 Wren Engine 或 MDL 模型。

## 技术栈

- FastAPI：HTTP API
- DuckDB：只读数据查询
- SQLGlot：SQL 解析与安全校验
- DeepSeek：通过 OpenAI 兼容接口实现 Text-to-SQL
- ChromaDB 和 sentence-transformers：本地 RAG 检索
- Pydantic：模型输出结构校验
- HTML、CSS 和 JavaScript：前端界面

## 重要文件

- `app/main.py`：API、Text-to-SQL、权限控制和查询执行
- `app/database_config.py`：Demo 与 Olist 数据库配置
- `app/retriever.py`：RAG 知识检索
- `app/clarifier.py`：问题歧义检测与主动追问
- `web/index.html`：Agent 主界面
- `web/evals.html`：评测 Dashboard
- `rag/knowledge_base.json`：Demo 知识库
- `rag/olist_knowledge_base.json`：Olist 知识库
- `evals/`：功能、安全、RAG、主动追问和对比评测

## 安全要求

修改查询执行逻辑时，必须遵守以下要求：

1. DuckDB 必须使用只读连接。
2. 每次只能执行一条只读 SQL。
3. SQL 执行前必须使用 SQLGlot 解析和校验。
4. 必须保留数据表白名单和敏感字段权限控制。
5. `admin` 角色必须提供有效的 `X-Admin-Key`。
6. 不得向客户端暴露内部异常、数据库路径或 API 密钥。
7. 查询结果最多返回 100 行。
8. 单条查询最多允许 8 个 JOIN。
9. 单条查询执行时间最多为 10 秒。
10. 必须保留 DuckDB 内存、线程和临时目录限制。
11. 不得提交 `.env`、数据库文件或 Olist 原始数据。

## 修改后的验证

修改后端或安全逻辑后，运行：

```powershell
.\.venv\Scripts\python.exe .\evals\run_security_evals.py
.\.venv\Scripts\python.exe .\evals\run_evals.py
.\.venv\Scripts\python.exe .\evals\run_olist_evals.py
.\.venv\Scripts\python.exe .\evals\run_olist_holdout_evals.py
```

修改对应模块后，运行相关补充评测：

```powershell
.\.venv\Scripts\python.exe .\evals\run_rag_evals.py
.\.venv\Scripts\python.exe .\evals\run_clarification_evals.py
.\.venv\Scripts\python.exe .\evals\run_comparison.py
```

## 本地开发

在项目根目录启动服务：

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

## 评测原则

不要为了让失败案例通过而随意修改正确的预期结果。

当预期行为正确时，应修复提示词、RAG 知识、校验逻辑或程序实现。