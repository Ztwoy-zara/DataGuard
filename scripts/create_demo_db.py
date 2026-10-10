from pathlib import Path

import duckdb


Path("data").mkdir(exist_ok=True)

connection = duckdb.connect("data/dataguard.duckdb")

connection.execute("""
CREATE OR REPLACE TABLE customers (
    id INTEGER PRIMARY KEY,
    name VARCHAR NOT NULL,
    city VARCHAR NOT NULL,
    email VARCHAR NOT NULL,
    phone VARCHAR NOT NULL
)
""")

connection.execute("""
CREATE OR REPLACE TABLE orders (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    amount DOUBLE NOT NULL,
    order_date DATE NOT NULL
)
""")

connection.executemany(
    "INSERT INTO customers VALUES (?, ?, ?, ?, ?)",
    [
        (1, "张三", "上海", "zhangsan@example.com", "13800000001"),
        (2, "李四", "北京", "lisi@example.com", "13800000002"),
        (3, "王五", "深圳", "wangwu@example.com", "13800000003"),
    ],
)

connection.executemany(
    "INSERT INTO orders VALUES (?, ?, ?, ?)",
    [
        (101, 1, 299.0, "2026-09-01"),
        (102, 1, 599.0, "2026-09-10"),
        (103, 2, 199.0, "2026-09-12"),
        (104, 3, 899.0, "2026-10-01"),
    ],
)

result = connection.execute("""
SELECT customers.name, SUM(orders.amount) AS total_amount
FROM customers
JOIN orders ON customers.id = orders.customer_id
GROUP BY customers.name
ORDER BY total_amount DESC
""").fetchall()

print("数据库创建成功：data/dataguard.duckdb")
print(result)

connection.close()