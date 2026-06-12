from pathlib import Path
from threading import Lock

from agentic_search.indexing import ChromaDB, Chunker, Retriever, Vectorizer
from agentic_search.reranker import Reranker
from nanobot.utils.helpers import ensure_dir


class DiaryStore:
    def __init__(self, workspace: Path):
        self.diary_dir = ensure_dir(workspace / "diary")
        self.chunker = Chunker()
        self.chroma_db = ChromaDB()
        self.reranker = Reranker().model
        self.lock = Lock()
        self._build_index()

    def query(self, query: str, top_k: int = 20) -> list[str]:
        hybrid_result = self.retriever.hybrid_query(query, top_k)
        reranked_result = self._get_top_chunks_from_reranker(query, hybrid_result)
        return [r[1] for r in reranked_result]

    def _query_top_k(self, query: str, top_k: int = 20) -> list[str]:
        return self.retriever.hybrid_query(query, top_k)

    def _rerank(self, user_query, chunk_list):
        return (user_query, chunk_list)

    def _get_top_chunks_from_reranker(self, user_query, chunk_list, n=5):
        model = self.reranker
        pairs = [(user_query, chunk) for chunk in chunk_list]
        scores = model.compute_score(pairs)
        if scores:
            scores_with_pairs = list(zip(scores, pairs))
            scores_with_pairs.sort(key=lambda x: x[0], reverse=True)
            return [pair[1] for pair in scores_with_pairs[:n]]
        else:
            raise ValueError("No scores returned from model")

    def _get_all_markdown_texts(self) -> list[str]:
        return [doc.read_text(encoding="utf-8") for doc in self.diary_dir.rglob("*.md")]

    def _convert_docs_to_corpus(self) -> None:
        self.corpus = self.chunker.chunk_markdown_texts(self.all_markdown_texts)

    def _build_index(self) -> None:
        self.all_markdown_texts = self._get_all_markdown_texts()
        self._convert_docs_to_corpus()
        self.chroma_db.clear()
        self.chroma_db.add_documents(self.corpus)
        self.vectorizer = Vectorizer(corpus=[doc.page_content for doc in self.corpus])
        self.bm25 = self.vectorizer.get_bm25(corpus=[doc.page_content for doc in self.corpus])
        self.retriever = Retriever(vectorizer=self.vectorizer, chroma_db=self.chroma_db)
