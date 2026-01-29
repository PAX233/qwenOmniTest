"""
数据模型定义
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
import uuid
import json


@dataclass
class MessageContent:
    """消息内容"""

    text: str = ""
    audio_transcript: Optional[str] = None
    audio_available: bool = False
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")


@dataclass
class Message:
    """单条对话消息"""

    turn_id: int
    role: str  # "user" or "assistant"
    timestamp: str
    content: MessageContent

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        return {
            "turn_id": self.turn_id,
            "role": self.role,
            "timestamp": self.timestamp,
            "content": {
                "text": self.content.text,
                "audio_transcript": self.content.audio_transcript,
                "audio_available": self.content.audio_available,
            },
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """从字典创建消息"""
        content_data = data.get("content", {})
        content = MessageContent(
            text=content_data.get("text", ""),
            audio_transcript=content_data.get("audio_transcript"),
            audio_available=content_data.get("audio_available", False),
        )

        return cls(
            turn_id=data.get("turn_id", 0),
            role=data.get("role", "user"),
            timestamp=data.get("timestamp", ""),
            content=content,
        )


@dataclass
class ConversationMetadata:
    """对话元数据"""

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    last_updated: str = field(
        default_factory=lambda: datetime.utcnow().isoformat() + "Z"
    )
    total_turns: int = 0
    total_tokens_estimated: int = 0

    def update_timestamp(self):
        """更新最后修改时间"""
        self.last_updated = datetime.utcnow().isoformat() + "Z"


@dataclass
class ConversationConfig:
    """对话配置（会话特定）"""

    max_history_turns: int = 10
    auto_save_interval: int = 5
    voice: str = "Chelsie"


@dataclass
class Conversation:
    """完整对话数据结构"""

    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    metadata: ConversationMetadata = field(default_factory=ConversationMetadata)
    config: ConversationConfig = field(default_factory=ConversationConfig)
    messages: List[Message] = field(default_factory=list)
    summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式用于JSON序列化"""
        return {
            "conversation_id": self.conversation_id,
            "metadata": {
                "created_at": self.metadata.created_at,
                "last_updated": self.metadata.last_updated,
                "total_turns": self.metadata.total_turns,
                "total_tokens_estimated": self.metadata.total_tokens_estimated,
            },
            "config": {
                "max_history_turns": self.config.max_history_turns,
                "auto_save_interval": self.config.auto_save_interval,
                "voice": self.config.voice,
            },
            "messages": [msg.to_dict() for msg in self.messages],
            "summary": self.summary,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Conversation":
        """从字典创建对话"""
        metadata_data = data.get("metadata", {})
        config_data = data.get("config", {})
        messages_data = data.get("messages", [])

        metadata = ConversationMetadata(
            created_at=metadata_data.get(
                "created_at", datetime.utcnow().isoformat() + "Z"
            ),
            last_updated=metadata_data.get(
                "last_updated", datetime.utcnow().isoformat() + "Z"
            ),
            total_turns=metadata_data.get("total_turns", 0),
            total_tokens_estimated=metadata_data.get("total_tokens_estimated", 0),
        )

        config = ConversationConfig(
            max_history_turns=config_data.get("max_history_turns", 10),
            auto_save_interval=config_data.get("auto_save_interval", 5),
            voice=config_data.get("voice", "Chelsie"),
        )

        messages = [Message.from_dict(msg_data) for msg_data in messages_data]

        return cls(
            conversation_id=data.get("conversation_id", str(uuid.uuid4())),
            metadata=metadata,
            config=config,
            messages=messages,
            summary=data.get("summary"),
        )

    def add_message(self, message: Message):
        """添加消息到对话"""
        self.messages.append(message)
        self.metadata.total_turns = len([m for m in self.messages if m.role == "user"])
        self.metadata.update_timestamp()

        # 估算token数量（简单估算）
        if message.content.text:
            self.metadata.total_tokens_estimated += (
                len(message.content.text) // 4
            )  # 粗略估算

    def get_recent_turns(self, max_turns: int) -> List[Message]:
        """获取最近的N轮对话"""
        if max_turns <= 0:
            return []

        # 按turn分组，每轮包含user和assistant消息
        turns = []
        current_turn = []

        for msg in reversed(self.messages):
            current_turn.append(msg)
            if msg.role == "assistant":
                turns.append(list(reversed(current_turn)))
                current_turn = []
                if len(turns) >= max_turns:
                    break

        # 添加最后一轮（如果没有完成的assistant消息）
        if current_turn and len(turns) < max_turns:
            turns.append(list(reversed(current_turn)))

        # 反转回正确顺序
        result = []
        for turn in reversed(turns):
            result.extend(turn)

        return result[: max_turns * 2]  # 每轮最多2条消息

    def build_context_text(self, max_context_turns: int) -> str:
        """构建上下文文本用于系统提示"""
        recent_messages = self.get_recent_turns(max_context_turns)
        if not recent_messages:
            return ""

        context_parts = ["以下是最近的对话历史："]
        for msg in recent_messages:
            role_name = "用户" if msg.role == "user" else "助手"
            text = (
                msg.content.audio_transcript
                if msg.content.audio_transcript
                else msg.content.text
            )
            if text:
                context_parts.append(f"{role_name}: {text}")

        return "\n".join(context_parts)

    def should_auto_save(self, interval: int) -> bool:
        """检查是否应该自动保存"""
        user_turns = len([m for m in self.messages if m.role == "user"])
        return user_turns % interval == 0 and user_turns > 0
