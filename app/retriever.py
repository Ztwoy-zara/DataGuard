import json
from functools import lru_cache
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

from app.database_config import get_database_config


PROJECT_ROOT = Path(__file__).resolve().parent.parent
CHROMA_PATH = PROJECT_ROOT / "rag" / "chroma_db"

MODEL_NAME = "BAAI/bge-small-zh-v1.5"
QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


@lru_cache(maxsize=2)
def load_knowledge_base(
    database_name: str = "demo",
) -> list[dict]:
    config = get_database_config(database_name)

    return json.loads(
        config.knowledge_path.read_text(encoding="utf-8")
    )


@lru_cache(maxsize=1)
def get_embedding_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def build_document_text(document: dict) -> str:
    keywords = "、".join(document.get("keywords", []))

    return (
        f"标题：{document.get('title', '')}\n"
        f"关键词：{keywords}\n"
        f"内容：{document.get('content', '')}"
    )


def encode_texts(texts: list[str]) -> list[list[float]]:
    model = get_embedding_model()

    embeddings = model.encode(
        texts,
        normalize_embeddings=True,
        show_progress_bar=False,
    )

    return embeddings.tolist()


@lru_cache(maxsize=2)
def get_vector_collection(
    database_name: str = "demo",
):
    config = get_database_config(database_name)

    client = chromadb.PersistentClient(
        path=str(CHROMA_PATH)
    )

    collection = client.get_or_create_collection(
        name=config.collection_name,
        metadata={
            "hnsw:space": "cosine",
            "database": database_name,
        },
    )

    documents = load_knowledge_base(database_name)
    document_texts = [
        build_document_text(document)
        for document in documents
    ]

    collection.upsert(
        ids=[document["id"] for document in documents],
        documents=document_texts,
        embeddings=encode_texts(document_texts),
        metadatas=[
            {
                "title": document.get("title", ""),
                "content": document.get("content", ""),
                "keywords": json.dumps(
                    document.get("keywords", []),
                    ensure_ascii=False,
                ),
                "database": database_name,
            }
            for document in documents
        ],
    )

    return collection


def retrieve_knowledge(
    question: str,
    top_k: int = 3,
    database_name: str = "demo",
) -> list[dict]:
    collection = get_vector_collection(database_name)

    if collection.count() == 0:
        return []

    query_text = QUERY_INSTRUCTION + question
    query_embedding = encode_texts([query_text])[0]

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=min(top_k, collection.count()),
        include=["metadatas", "distances"],
    )

    retrieved_documents = []

    ids = results.get("ids", [[]])[0]
    metadatas = results.get("metadatas", [[]])[0]
    distances = results.get("distances", [[]])[0]

    for document_id, metadata, distance in zip(
        ids,
        metadatas,
        distances,
    ):
        retrieved_documents.append(
            {
                "id": document_id,
                "title": metadata.get("title", ""),
                "content": metadata.get("content", ""),
                "keywords": json.loads(
                    metadata.get("keywords", "[]")
                ),
                "score": round(1 - distance, 4),
            }
        )

    return retrieved_documents


def format_retrieved_context(
    documents: list[dict],
) -> str:
    if not documents:
        return "未检索到相关业务知识。"

    return "\n".join(
        f"- {document['title']}：{document['content']}"
        for document in documents
    )