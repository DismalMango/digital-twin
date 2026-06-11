import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from typing import Any, cast

import chromadb
import jieba
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownTextSplitter
from openai import OpenAI
from rank_bm25 import BM25Okapi

from constants import WORKSPACE_PATH


class Chunker:
    def __init__(self, chunk_size=100, chunk_overlap=10) -> None:
        self.splitter = MarkdownTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        self.lock = Lock()

    def chunk_markdown_texts(self, markdown_texts: list[str]) -> list[Document]:
        chunk_list: list[Document] = []
        with ThreadPoolExecutor(max_workers=10) as executor:
            futures = {
                executor.submit(self.splitter.create_documents, [markdown_text]): markdown_text
                for markdown_text in markdown_texts
            }
            for future in as_completed(futures):
                docs = future.result()
                for doc in docs:
                    self._safe_append(doc, chunk_list)
        return chunk_list

    def _safe_append(self, text: Document, chunk_list: list[Document]) -> None:
        with self.lock:
            chunk_list.append(text)


class Vectorizer:
    def __init__(
        self,
        corpus: list[str] | None = None,
        model: str = "text-embedding-3-small",
        client: OpenAI | None = None,
    ) -> None:
        self.model = model
        self.client = client or OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
        self.corpus = corpus or []

    def get_dense_vector(self, text: str) -> list[float]:
        """
        Generates a vector embedding for the provided text using OpenAI's API.
        """
        response = self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    def get_dense_vectors(self, texts: list[str], batch_size: int = 64) -> list[list[float]]:
        if not texts:
            return []

        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = self.client.embeddings.create(
                model=self.model,
                input=batch,
            )
            vectors.extend(item.embedding for item in response.data)
        return vectors

    def get_bm25(self, corpus: list[str]) -> BM25Okapi:
        """
        get BM25 index for the corpus
        """
        tokenized_corpus = [jieba.lcut_for_search(text) for text in corpus]
        return BM25Okapi(tokenized_corpus)


class ChromaDB:
    def __init__(
        self,
        path: str | None = None,
        collection_name: str = "my_notes",
        vectorizer: Vectorizer | None = None,
    ) -> None:
        self.client = chromadb.PersistentClient(path=path or str(WORKSPACE_PATH / "chroma_db"))
        self.collection = self.client.get_or_create_collection(name=collection_name)
        self.vectorizer = vectorizer or Vectorizer(corpus=[])

    def clear(self) -> None:
        records = self.collection.get()
        ids = cast(list[str], records.get("ids") or [])
        if ids:
            self.collection.delete(ids=ids)

    def _make_doc_id(self, doc: Document, idx: int) -> str:
        metadata = doc.metadata or {}
        source = str(metadata.get("source", "unknown"))
        digest = hashlib.sha256(f"{source}\0{idx}\0{doc.page_content}".encode("utf-8")).hexdigest()
        return f"{source}:{idx}:{digest[:16]}"

    def add_documents(self, documents: list[Document]) -> None:
        if not documents:
            return

        batch_size = 5000
        contents = [doc.page_content for doc in documents]
        embeddings = cast(Any, self.vectorizer.get_dense_vectors(contents))
        metadatas = cast(
            Any,
            [
                {**(doc.metadata or {}), "source": (doc.metadata or {}).get("source", "unknown")}
                for doc in documents
            ],
        )
        ids = [self._make_doc_id(doc, i) for i, doc in enumerate(documents)]
        for start in range(0, len(documents), batch_size):
            end = start + batch_size
            self.collection.upsert(
                ids=ids[start:end],
                embeddings=embeddings[start:end],
                documents=contents[start:end],
                metadatas=metadatas[start:end],
            )

    def query(self, query: str, n_results: int = 2) -> dict[str, Any]:
        results = self.collection.query(
            query_embeddings=[self.vectorizer.get_dense_vector(query)],
            n_results=n_results,
        )
        return cast(dict[str, Any], results)


class Retriever:
    def __init__(self, vectorizer: Vectorizer, chroma_db: ChromaDB) -> None:
        self.vectorizer = vectorizer
        self.chroma_db = chroma_db
        self._cached_bm25: BM25Okapi | None = None
        self._cached_doc_ids: list[str] = []

    def dense_query(self, query: str, n_results: int = 2) -> dict[str, Any]:
        return self.chroma_db.query(query, n_results)

    def _get_or_build_bm25(self, doc_ids: list[str], documents: list[str]) -> BM25Okapi:
        if (
            self._cached_bm25 is None
            or len(doc_ids) != len(self._cached_doc_ids)
            or doc_ids != self._cached_doc_ids
        ):
            self._cached_bm25 = self.vectorizer.get_bm25(documents)
            self._cached_doc_ids = list(doc_ids)
        return self._cached_bm25

    def sparse_query(self, query: str, n_results: int = 2) -> list[str]:
        corpus_data = self.chroma_db.collection.get(include=["documents"])
        doc_ids = corpus_data.get("ids", [])
        documents = corpus_data.get("documents", [])

        if not doc_ids or not documents:
            return []

        bm25 = self._get_or_build_bm25(doc_ids, documents)
        query_tokens = jieba.lcut_for_search(query)
        scores = bm25.get_scores(query_tokens)
        ranked_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[
            :n_results
        ]
        return [doc_ids[i] for i in ranked_indices]

    def reciprocal_rank_fusion(self, rankings: list[list[str]], k: int = 60) -> list[str]:
        scores: dict[str, float] = {}

        for ranking in rankings:
            for rank, doc_id in enumerate(ranking, start=1):
                if doc_id not in scores:
                    scores[doc_id] = 0.0
                scores[doc_id] += 1.0 / (k + rank)

        sorted_docs = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return [doc_id for doc_id, _ in sorted_docs]

    def _fetch_documents_by_ids(self, doc_ids: list[str]) -> list[str]:
        if not doc_ids:
            return []

        records = self.chroma_db.collection.get(ids=doc_ids, include=["documents"])
        fetched_ids = cast(list[str], records.get("ids") or [])
        fetched_docs = cast(list[str], records.get("documents") or [])

        id_to_doc = {doc_id: doc for doc_id, doc in zip(fetched_ids, fetched_docs)}
        return [id_to_doc[doc_id] for doc_id in doc_ids if doc_id in id_to_doc]

    def hybrid_query(self, query: str, n_results: int = 2) -> list[str]:
        """using Reciprocal Rank Fusion, RRF to fuse the dense and sparse results"""
        dense_results = self.dense_query(query, n_results)
        sparse_results = self.sparse_query(query, n_results)
        dense_ids_nested = dense_results.get("ids", [])
        dense_ids = dense_ids_nested[0] if dense_ids_nested else []
        fused_ids = self.reciprocal_rank_fusion([dense_ids, sparse_results])[:n_results]
        return self._fetch_documents_by_ids(fused_ids)
