from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class DatabaseConfig:
    name: str
    label: str
    database_path: Path
    allowed_tables: frozenset[str]
    sensitive_columns: frozenset[str]
    relationships: tuple[str, ...]
    knowledge_path: Path
    collection_name: str


DATABASE_CONFIGS = {
    "demo": DatabaseConfig(
        name="demo",
        label="Demo 客户订单库",
        database_path=(
            PROJECT_ROOT
            / "data"
            / "dataguard.duckdb"
        ),
        allowed_tables=frozenset(
            {
                "customers",
                "orders",
            }
        ),
        sensitive_columns=frozenset(
            {
                "email",
                "phone",
            }
        ),
        relationships=(
            "orders.customer_id 对应 customers.id。",
        ),
        knowledge_path=(
            PROJECT_ROOT
            / "rag"
            / "knowledge_base.json"
        ),
        collection_name="dataguard_demo_knowledge",
    ),
    "olist": DatabaseConfig(
        name="olist",
        label="Olist 巴西电商库",
        database_path=(
            PROJECT_ROOT
            / "data"
            / "olist.duckdb"
        ),
        allowed_tables=frozenset(
            {
                "customers",
                "geolocation",
                "order_items",
                "order_payments",
                "order_reviews",
                "orders",
                "products",
                "sellers",
                "product_category_translation",
            }
        ),
        sensitive_columns=frozenset(),
        relationships=(
            "orders.customer_id 对应 customers.customer_id。",
            "order_items.order_id 对应 orders.order_id。",
            "order_payments.order_id 对应 orders.order_id。",
            "order_reviews.order_id 对应 orders.order_id。",
            "order_items.product_id 对应 products.product_id。",
            "order_items.seller_id 对应 sellers.seller_id。",
            "products.product_category_name 对应 "
            "product_category_translation.product_category_name。",
        ),
        knowledge_path=(
            PROJECT_ROOT
            / "rag"
            / "olist_knowledge_base.json"
        ),
        collection_name="dataguard_olist_knowledge",
    ),
}


def get_database_config(
    database_name: str,
) -> DatabaseConfig:
    try:
        return DATABASE_CONFIGS[database_name]
    except KeyError as error:
        available = ", ".join(DATABASE_CONFIGS)

        raise ValueError(
            f"未知数据库：{database_name}。"
            f"可选数据库：{available}"
        ) from error