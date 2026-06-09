import asyncio
import json
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import aiofiles
from loguru import logger

from nanobot.bus import MessageBus
from nanobot.bus.events import InboundMessage
from nanobot.utils.helpers import conver_time


@dataclass
class ChatDelta:
    """Chat-list delta produced by MsgListListener."""

    added: set[str]
    removed: set[str]


class MsgListListener:
    """Poll the user's chat list and emit chat membership changes."""

    def __init__(self, workspace: Path):
        self.workspace = workspace
        self._known_chat_ids: set[str] = set()
        self._chat_delta_queue: asyncio.Queue[ChatDelta] = asyncio.Queue()
        self._running = False

    async def load_user_chat_ids(self, command_timeout: float = 10.0) -> list[dict[str, Any]]:
        cmd = [
            "lark-cli",
            "im",
            "+chat-list",
            "--as",
            "user",
            "--types",
            "p2p",
            "--format",
            "json",
            "--jq",
            ".data.chats",
        ]
        result = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            stdout, stderr = await asyncio.wait_for(result.communicate(), timeout=command_timeout)
        except asyncio.TimeoutError:
            result.kill()
            await result.wait()
            logger.warning(f"Timed out loading user chat ids after {command_timeout}s")
            return []
        if result.returncode != 0:
            logger.error(
                f"Error loading user chat ids (code={result.returncode}): {stderr.decode(errors='ignore').strip()}"
            )
            return []
        if stderr:
            logger.warning(f"Chat list command stderr: {stderr.decode(errors='ignore').strip()}")
        try:
            json_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode chat list JSON: {e}")
            return []
        return [item for item in json_data if item["p2p_target_type"] == "user"]

    @staticmethod
    def _extract_chat_id(chat: dict[str, Any]) -> str | None:
        chat_id = chat.get("chat_id")
        if not chat_id:
            return None
        return str(chat_id)

    async def _snapshot_chat_ids(self) -> set[str]:
        chats = await self.load_user_chat_ids()
        ids: set[str] = set()
        for chat in chats:
            chat_id = self._extract_chat_id(chat)
            if chat_id:
                ids.add(chat_id)
        return ids

    async def listen(self, poll_interval: float = 15.0, emit_initial: bool = True) -> None:
        self._running = True
        self._known_chat_ids = await self._snapshot_chat_ids()
        if emit_initial and self._known_chat_ids:
            await self._chat_delta_queue.put(
                ChatDelta(added=set(self._known_chat_ids), removed=set())
            )

        while self._running:
            await asyncio.sleep(poll_interval)
            current_ids = await self._snapshot_chat_ids()
            added = current_ids - self._known_chat_ids
            removed = self._known_chat_ids - current_ids
            if added or removed:
                await self._chat_delta_queue.put(ChatDelta(added=added, removed=removed))
            self._known_chat_ids = current_ids

    async def consume_chat_delta(self, timeout: float | None = None) -> ChatDelta | None:
        if timeout is None:
            return await self._chat_delta_queue.get()
        try:
            return await asyncio.wait_for(self._chat_delta_queue.get(), timeout=timeout)
        except asyncio.TimeoutError:
            return None

    def stop(self) -> None:
        self._running = False


class ChatListener:
    """Poll new messages for one chat."""

    def __init__(
        self,
        chat_id: str,
        user_id: str,
        workspace: Path,
        message_bus: MessageBus,
        start_time: datetime,
    ):
        self.chat_id = chat_id
        self.user_id = user_id
        self.workspace = workspace
        self.message_bus = message_bus
        self.start_time = start_time
        self._latest_message_id = None
        self._new_messages = []
        self.last_activity_at = start_time

    async def _read_latest_message_id_from_cache(self) -> str | None:
        cache_path = self.workspace / "feishu_cache" / f"{self.chat_id}.jsonl"
        try:
            async with aiofiles.open(cache_path, "r") as f:
                lines = await f.readlines()
                if lines:
                    return json.loads(lines[-1])["message_id"]
        except Exception:
            pass
        return None

    async def write_cache(self, messages: list[dict[str, Any]]) -> None:
        if not messages:
            return
        cache_dir = self.workspace / "feishu_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{self.chat_id}.jsonl"
        async with aiofiles.open(cache_path, "a") as f:
            for message in messages:
                await f.write(json.dumps(message, ensure_ascii=False) + "\n")

    async def listen(self, command_timeout: float = 10.0):
        proc = await asyncio.create_subprocess_exec(
            "lark-cli",
            "im",
            "+chat-messages-list",
            "--as",
            "user",
            "--chat-id",
            self.chat_id,
            "--page-size",
            "50",
            "--format",
            "json",
            "--sort",
            "asc",
            "--jq",
            ".data.messages",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=command_timeout)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            proc.kill()
            await proc.wait()
            raise

        if proc.returncode != 0:
            logger.error(
                f"Error loading chat messages for chat_id={self.chat_id} "
                f"(code={proc.returncode}): {stderr.decode(errors='ignore').strip()}"
            )
            return
        if stderr:
            logger.warning(
                f"Chat messages command stderr for chat_id={self.chat_id}: "
                f"{stderr.decode(errors='ignore').strip()}"
            )
        try:
            json_data = json.loads(stdout)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode chat messages JSON for chat_id={self.chat_id}: {e}")
            return
        # The subprocess has exited and both pipes have been drained.
        if not self._latest_message_id:
            self._latest_message_id = await self._read_latest_message_id_from_cache()

        if not json_data:
            return

        # --sort asc returns oldest messages first, so the newest message is last.
        latest_msg_id = json_data[-1]["message_id"]

        # Ignore historical messages that were created before the agent started.
        # A missing cursor means this chat has not been recorded yet.
        if not self._latest_message_id:
            self._latest_message_id = latest_msg_id
            return

        if self._latest_message_id == latest_msg_id:
            return

        new_messages: list[dict[str, Any]] = []
        past_cursor = False
        for message in json_data:
            if message["message_id"] == self._latest_message_id:
                past_cursor = True
                continue
            if message["sender"]["id"] == self.user_id:
                continue
            if past_cursor and conver_time(message["create_time"]) > self.start_time:
                logger.info(f"New message from feishu chat_id={self.chat_id}: {message}")
                new_messages.append(message)

        if not past_cursor:
            self._latest_message_id = latest_msg_id
            return

        if new_messages:
            self._new_messages.extend(new_messages)
            self.last_activity_at = datetime.now()
            for message in new_messages:
                await self.message_bus.publish_inbound(
                    InboundMessage(
                        "feishu", message["sender"]["id"], self.chat_id, message["content"]
                    )
                )
            await self.write_cache(new_messages)
            self._latest_message_id = latest_msg_id


class AllChatListener:
    """
    Orchestrate chat listeners for all user chats.

    Workflow:
    1. Poll MsgListListener for the full chat list.
    2. Start ChatListener task for every unseen chat.
    3. Keep polling and attach listeners for newly discovered chats.
    """

    def __init__(
        self,
        workspace: Path,
        message_bus: MessageBus,
        poll_interval: float = 15.0,
        max_concurrent_chat_polls: int = 8,
        chat_poll_timeout: float = 10.0,
    ) -> None:
        self.workspace = workspace
        self.msg_list_listener = MsgListListener(workspace)
        self.message_bus = message_bus
        self.poll_interval = poll_interval
        self.max_concurrent_chat_polls = max(1, max_concurrent_chat_polls)
        self.chat_poll_timeout = chat_poll_timeout
        self._running = False
        self.start_time = datetime.now()
        self._chat_listeners: dict[str, ChatListener] = {}
        self._chat_poll_semaphore = asyncio.Semaphore(self.max_concurrent_chat_polls)
        self.user_id = (
            subprocess.run(
                ["lark-cli", "contact", "+get-user", "--as", "user", "--jq", ".data.user.open_id"],
                capture_output=True,
            )
            .stdout.decode("utf-8")
            .strip()
        )

    @staticmethod
    def _extract_chat_id(chat: dict[str, Any]) -> str | None:
        chat_id = chat.get("chat_id")
        if not chat_id:
            return None
        return str(chat_id)

    async def _apply_chat_delta(self, delta: ChatDelta) -> None:
        for chat_id in delta.removed:
            if chat_id in self._chat_listeners:
                self._chat_listeners.pop(chat_id, None)
                logger.info(f"Removed chat listener for chat_id={chat_id}")

        for chat_id in delta.added:
            if chat_id in self._chat_listeners:
                continue

            listener = ChatListener(
                chat_id=chat_id,
                user_id=self.user_id,
                workspace=self.workspace,
                message_bus=self.message_bus,
                start_time=self.start_time,
            )
            self._chat_listeners[chat_id] = listener
            logger.info(f"Added chat listener for chat_id={chat_id}")

    async def _poll_chat_listener(self, chat_id: str, listener: ChatListener) -> None:
        async with self._chat_poll_semaphore:
            try:
                await asyncio.wait_for(
                    listener.listen(command_timeout=self.chat_poll_timeout),
                    timeout=self.chat_poll_timeout,
                )
            except asyncio.TimeoutError:
                logger.warning(
                    f"Timed out polling chat listener for chat_id={chat_id} "
                    f"after {self.chat_poll_timeout}s"
                )
            except Exception as e:
                logger.error(f"Chat listener failed for chat_id={chat_id}: {e}")

    def _chat_listener_batches(
        self, listener_items: list[tuple[str, ChatListener]]
    ) -> list[list[tuple[str, ChatListener]]]:
        ordered = sorted(
            listener_items,
            key=lambda item: item[1].last_activity_at,
            reverse=True,
        )
        return [
            ordered[index : index + self.max_concurrent_chat_polls]
            for index in range(0, len(ordered), self.max_concurrent_chat_polls)
        ]

    async def listen(self) -> None:
        self._running = True
        msg_list_task = asyncio.create_task(
            self.msg_list_listener.listen(poll_interval=self.poll_interval, emit_initial=True)
        )
        try:
            while self._running:
                try:
                    delta = await self.msg_list_listener.consume_chat_delta(
                        timeout=self.poll_interval
                    )
                    if delta:
                        await self._apply_chat_delta(delta)

                    if self._chat_listeners:
                        listener_items = list(self._chat_listeners.items())
                        for batch in self._chat_listener_batches(listener_items):
                            await asyncio.gather(
                                *(
                                    self._poll_chat_listener(chat_id, listener)
                                    for chat_id, listener in batch
                                )
                            )
                except Exception as e:
                    # Keep the orchestrator alive if one polling round fails.
                    logger.error(f"Error syncing chat listeners: {e}")
        finally:
            self.msg_list_listener.stop()
            msg_list_task.cancel()
            await asyncio.gather(msg_list_task, return_exceptions=True)

    def stop(self) -> None:
        self._running = False
        self.msg_list_listener.stop()
