from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING

from agentic_search.constants import WORKSPACE_PATH
from agentic_search.rag_state import GraphState

if TYPE_CHECKING:
    from agentic_search.diary import DiaryStore

_diary_store: "DiaryStore | None" = None
_diary_store_lock = Lock()


def _create_diary_store() -> "DiaryStore":
    from agentic_search.diary import DiaryStore

    return DiaryStore(Path(WORKSPACE_PATH))


def get_diary_store() -> "DiaryStore":
    global _diary_store

    if _diary_store is None:
        with _diary_store_lock:
            if _diary_store is None:
                _diary_store = _create_diary_store()
    return _diary_store


def rag_node(state: GraphState) -> dict[str, list[str]]:
    diary_store = get_diary_store()
    return {"retrieved_documents": diary_store.query(state["user_query"])}
