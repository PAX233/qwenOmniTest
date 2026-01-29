"""
对话管理器
负责对话的存储、加载和管理
"""

import os
import json
import threading
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

from .conversation_config import ConversationConfig
from .conversation_models import Conversation, Message, MessageContent


class ConversationManager:
    """对话管理器"""

    def __init__(self, config: ConversationConfig):
        self.config = config
        self.storage_path = config.ensure_storage_directory()
        self.current_conversation: Optional[Conversation] = None
        self._file_lock = threading.Lock()

        # 确保目录结构
        self._ensure_directory_structure()

        # 尝试加载活跃会话
        self.load_active_conversation()

    def _ensure_directory_structure(self):
        """确保目录结构存在"""
        self.storage_path.mkdir(parents=True, exist_ok=True)
        (self.storage_path / "archived").mkdir(exist_ok=True)
        (self.storage_path / "backup").mkdir(exist_ok=True)

    def start_new_conversation(self, voice: str = "Chelsie") -> str:
        """开始新的对话会话"""
        with self._file_lock:
            # 归档当前会话
            if self.current_conversation:
                self.archive_current_conversation()

            # 创建新会话
            self.current_conversation = Conversation()
            self.current_conversation.config.voice = voice

            # 保存为活跃会话
            self._save_active_conversation()

            print(f"开始新对话会话: {self.current_conversation.conversation_id}")
            return self.current_conversation.conversation_id

    def load_conversation(self, conversation_id: str) -> bool:
        """加载指定ID的对话"""
        conversation_file = self.storage_path / f"{conversation_id}.json"
        if not conversation_file.exists():
            print(f"对话文件不存在: {conversation_file}")
            return False

        try:
            with self._file_lock:
                with open(conversation_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 归档当前会话
                if self.current_conversation:
                    self.archive_current_conversation()

                # 加载指定对话
                self.current_conversation = Conversation.from_dict(data)
                self._save_active_conversation()

                print(f"加载对话: {conversation_id}")
                if self.current_conversation:
                    print(f"对话包含 {len(self.current_conversation.messages)} 条消息")
                return True

        except Exception as e:
            print(f"加载对话失败: {e}")
            return False

    def get_conversation_list(self) -> List[Dict[str, Any]]:
        """获取所有对话列表"""
        conversations = []

        # 扫描对话文件
        for conv_file in self.storage_path.glob("*.json"):
            if conv_file.name == "active_conversation.json":
                continue

            try:
                with open(conv_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    metadata = data.get("metadata", {})

                    conversations.append(
                        {
                            "conversation_id": data.get("conversation_id"),
                            "created_at": metadata.get("created_at"),
                            "last_updated": metadata.get("last_updated"),
                            "total_turns": metadata.get("total_turns", 0),
                            "file_path": str(conv_file),
                        }
                    )
            except Exception as e:
                print(f"读取对话文件失败 {conv_file}: {e}")

        # 按最后更新时间排序
        conversations.sort(key=lambda x: x["last_updated"], reverse=True)
        return conversations

    def add_user_message(self, text: str = "", audio_transcript: str = None):
        """添加用户消息"""
        if not self.current_conversation:
            self.start_new_conversation()

        if not self.current_conversation:
            return

        content = MessageContent(
            text=text,
            audio_transcript=audio_transcript or text,
            audio_available=bool(audio_transcript),
        )

        turn_id = (
            len([m for m in self.current_conversation.messages if m.role == "user"]) + 1
        )
        message = Message(
            turn_id=turn_id,
            role="user",
            timestamp=datetime.utcnow().isoformat() + "Z",
            content=content,
        )

        self.current_conversation.add_message(message)

    def add_assistant_message(self, text: str, audio_available: bool = True):
        """添加助手消息"""
        if not self.current_conversation:
            self.start_new_conversation()

        if not self.current_conversation:
            return

        content = MessageContent(text=text, audio_available=audio_available)

        # 获取用户消息的turn_id
        if self.current_conversation.messages:
            user_messages = [
                m for m in self.current_conversation.messages if m.role == "user"
            ]
            turn_id = len(user_messages) if user_messages else 1
        else:
            turn_id = 1

        message = Message(
            turn_id=turn_id,
            role="assistant",
            timestamp=datetime.utcnow().isoformat() + "Z",
            content=content,
        )

        self.current_conversation.add_message(message)

        # 检查是否需要自动保存
        if hasattr(self.current_conversation, "should_auto_save"):
            if self.current_conversation.should_auto_save(
                self.config.auto_save_interval
            ):
                self.save_current_conversation()

    def get_recent_context(self, max_turns: Optional[int] = None) -> List[Message]:
        """获取最近的对话上下文"""
        if not self.current_conversation:
            return []

        max_turns = max_turns or self.config.max_context_turns
        return self.current_conversation.get_recent_turns(max_turns)

    def build_context_prompt(self, max_turns: Optional[int] = None) -> str:
        """构建上下文提示词"""
        if not self.current_conversation:
            return ""

        context_text = self.current_conversation.build_context_text(
            max_turns or self.config.max_context_turns
        )

        if not context_text:
            return ""

        return f"""{context_text}

请基于以上对话历史继续对话。保持对话的连贯性和一致性，记住之前讨论的内容。"""

    def save_current_conversation(self) -> bool:
        """保存当前对话"""
        if not self.current_conversation:
            return False

        try:
            with self._file_lock:
                self._save_active_conversation()
                print(f"对话已保存: {self.current_conversation.conversation_id}")
                return True
        except Exception as e:
            print(f"保存对话失败: {e}")
            return False

    def archive_current_conversation(self):
        """归档当前对话"""
        if not self.current_conversation:
            return

        conversation_file = (
            self.storage_path / f"{self.current_conversation.conversation_id}.json"
        )
        archive_dir = self.storage_path / "archived"

        try:
            # 移动到归档目录
            if conversation_file.exists():
                target_file = archive_dir / conversation_file.name
                conversation_file.rename(target_file)
                print(f"对话已归档: {self.current_conversation.conversation_id}")
        except Exception as e:
            print(f"归档对话失败: {e}")

    def cleanup_old_conversations(self, days: Optional[int] = None) -> int:
        """清理旧的对话文件"""
        days = days or self.config.cleanup_days
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        cleaned_count = 0

        try:
            for conv_file in (self.storage_path / "archived").glob("*.json"):
                try:
                    # 从文件名或内容获取创建时间
                    file_time = datetime.fromtimestamp(conv_file.stat().st_mtime)
                    if file_time < cutoff_date:
                        conv_file.unlink()
                        cleaned_count += 1
                except Exception:
                    pass

            if cleaned_count > 0:
                print(f"清理了 {cleaned_count} 个旧对话文件")
            return cleaned_count

        except Exception as e:
            print(f"清理旧对话失败: {e}")
            return 0

    def _save_active_conversation(self):
        """保存活跃会话文件"""
        active_file = self.storage_path / "active_conversation.json"
        if self.current_conversation:
            with open(active_file, "w", encoding="utf-8") as f:
                json.dump(
                    self.current_conversation.to_dict(), f, ensure_ascii=False, indent=2
                )

    def load_active_conversation(self):
        """加载活跃会话"""
        active_file = self.storage_path / "active_conversation.json"
        if not active_file.exists():
            return

        try:
            with open(active_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                self.current_conversation = Conversation.from_dict(data)
                print(f"恢复活跃会话: {self.current_conversation.conversation_id}")
        except Exception as e:
            print(f"加载活跃会话失败: {e}")
            # 如果加载失败，备份文件并开始新会话
            backup_file = (
                self.storage_path
                / "backup"
                / f"active_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            )
            try:
                active_file.rename(backup_file)
                print(f"损坏的活跃会话已备份到: {backup_file}")
            except:
                pass

    def get_conversation_stats(self) -> Dict[str, Any]:
        """获取当前对话统计信息"""
        if not self.current_conversation:
            return {"error": "没有活跃对话"}

        return {
            "conversation_id": self.current_conversation.conversation_id,
            "total_turns": self.current_conversation.metadata.total_turns,
            "total_messages": len(self.current_conversation.messages),
            "total_tokens_estimated": self.current_conversation.metadata.total_tokens_estimated,
            "created_at": self.current_conversation.metadata.created_at,
            "last_updated": self.current_conversation.metadata.last_updated,
            "voice": self.current_conversation.config.voice,
        }
