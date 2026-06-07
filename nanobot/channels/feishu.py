"""feishu secretary channel implementation"""

# lark-cli im +messages-send --as user --chat-id oc_8614c1dd84caeb86106ffa656fe31cbb  --text "你好"

import subprocess
from pathlib import Path

from feishu_bridge.bridge import AllChatListener
from nanobot.bus.events import OutboundMessage
from nanobot.bus.queue import MessageBus
from nanobot.channels.base import BaseChannel
from nanobot.config.schema import FeishuSecretaryConfig


class FeishuSecretaryChannel(BaseChannel):
    """
    Telegram channel using long polling.

    Simple and reliable - no webhook/public IP needed.
    """

    name = "feishu_secretary"

    def __init__(
        self,
        config: FeishuSecretaryConfig,
        bus: MessageBus,
        workspace: Path = Path.home() / ".nanobot" / "workspace",
    ):
        self.workspace = workspace
        self.config = config
        self.bus = bus
        self.all_chat_listener = AllChatListener(workspace=self.workspace, message_bus=self.bus)

    async def start(self) -> None:
        await self.all_chat_listener.listen()

    async def send(self, msg: OutboundMessage) -> None:
        subprocess.run(["lark-cli", "im", "+messages-send", "--as", "user", "--chat-id", msg.chat_id, "--text", msg.content])

    async def stop(self) -> None:
        self.all_chat_listener.stop()
