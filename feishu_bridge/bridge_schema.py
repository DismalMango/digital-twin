from dataclasses import dataclass


@dataclass
class ChatDelta:
    """Chat-list delta produced by MsgListListener."""

    added: set[str]
    removed: set[str]
