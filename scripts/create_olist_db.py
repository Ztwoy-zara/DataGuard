from pathlib import Path

import duckdb


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "olist_raw"
DATABASE_PATH = PROJECT_ROOT / "data" / "olist.duckdb"

CSV_TABLES = {
    "customers": "olist_customers_dataset.csv",
    "geolocation": "olist_geolocation_dataset.csv",
    "order_items": "olist_order_items_dataset.csv",
    "order_payments": "olist_order_payments_dataset.csv",
    "order_reviews": "olist_order_reviews_dataset.csv",
    "orders": "olist_orders_dataset.csv",
    "products": "olist_products_dataset.csv",
    "sellers": "olist_sellers_dataset.csv",
    "product_category_translation": (
        "product_category_name_translation.csv"
    ),
}

INDEXES = [
    ("idx_customers_id", "customers", "customer_id"),
    (
        "idx_customers_unique_id",
        "customers",
        "customer_unique_id",
    ),
    ("idx_orders_id", "orders", "order_id"),
    ("idx_orders_customer_id", "orders", "customer_id"),
    ("idx_order_items_order_id", "order_items", "order_id"),
    (
        "idx_order_items_product_id",
        "order_items",
        "product_id",
    ),
    (
        "idx_order_items_seller_id",
        "order_items",
        "seller_id",
    ),
    (
        "idx_order_payments_order_id",
        "order_payments",
        "order_id",
    ),
    (
        "idx_order_reviews_order_id",
        "order_reviews",
        "order_id",
    ),
    ("idx_products_id", "products", "product_id"),
    ("idx_sellers_id", "sellers", "seller_id"),
    (
        "idx_geolocation_zip",
        "geolocation",
        "geolocation_zip_code_prefix",
    ),
]


def sql_path(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").replace(
        "'",
        "''",
    )


def validate_source_files():
    missing_files = [
        filename
        for filename in CSV_TABLES.values()
        if not (RAW_DATA_DIR / filename).exists()
    ]

    if missing_files:
        missing_text = "\n".join(
            f"- {filename}"
            for filename in missing_files
        )
        raise FileNotFoundError(
            f"缺少以下 Olist CSV 文件：\n{missing_text}"
        )


def import_tables(connection):
    for table_name, filename in CSV_TABLES.items():
        csv_path = RAW_DATA_DIR / filename

        print(f"正在导入 {table_name}...")

        connection.execute(
            f"""
            CREATE OR REPLACE TABLE "{table_name}" AS
            SELECT *
            FROM read_csv_auto(
                '{sql_path(csv_path)}',
                header = true,
                sample_size = -1
            )
            """
        )

        row_count = connection.execute(
            f'SELECT COUNT(*) FROM "{table_name}"'
        ).fetchone()[0]

        print(
            f"  完成：{table_name}，"
            f"{row_count:,} 行"
        )


def create_indexes(connection):
    print("\n正在创建索引...")

    for index_name, table_name, column_name in INDEXES:
        connection.execute(
            f"""
            CREATE INDEX IF NOT EXISTS "{index_name}"
            ON "{table_name}" ("{column_name}")
            """
        )

    print(f"  完成：{len(INDEXES)} 个索引")


def print_summary(connection):
    print("\nOlist 数据库汇总：")

    for table_name in CSV_TABLES:
        row_count = connection.execute(
            f'SELECT COUNT(*) FROM "{table_name}"'
        ).fetchone()[0]

        print(f"- {table_name}: {row_count:,} 行")


def main():
    validate_source_files()

    DATABASE_PATH.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    connection = duckdb.connect(str(DATABASE_PATH))

    try:
        import_tables(connection)
        create_indexes(connection)
        print_summary(connection)
    finally:
        connection.close()

    database_size_mb = (
        DATABASE_PATH.stat().st_size / 1024 / 1024
    )

    print(
        "\n数据库创建成功："
        f"{DATABASE_PATH}"
    )
    print(
        f"数据库大小：{database_size_mb:.2f} MB"
    )


if __name__ == "__main__":
    main()