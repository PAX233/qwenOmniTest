"""
多轮对话管理配置系统
支持从文件和环境变量加载配置
"""

import os
import toml
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path


@dataclass
class ApiConfig:
    """API 配置类"""

    model: str = "qwen3-omni-flash-realtime"
    api_url: str = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"


@dataclass
class AudioConfig:
    """音频配置类"""

    input_format: str = "PCM_16000HZ_MONO_16BIT"
    output_format: str = "PCM_24000HZ_MONO_16BIT"
    voice: str = "Chelsie"
    sample_rate_input: int = 16000
    sample_rate_output: int = 24000
    chunk_size_ms: int = 100


@dataclass
class ConversationConfig:
    """多轮对话配置类"""

    # 存储配置
    storage_directory: str = "./conversations"
    file_format: str = "json"

    # 历史管理
    max_history_turns: int = 10
    max_context_turns: int = 3  # 注入到 API 的上下文轮数（建议 3-5 轮）
    auto_save_interval: int = 3  # 每 N 轮自动保存

    # 上下文注入
    enable_context_injection: bool = True  # 是否启用对话历史上下文注入
    auto_load_last: bool = False  # 是否自动加载上次对话

    # Token 统计
    show_token_stats: bool = True  # 是否实时显示 token 使用情况
    debug_mode: bool = False  # 是否启用调试模式（打印完整事件数据）

    # 高级选项
    enable_summary: bool = True
    max_summary_age_turns: int = 20
    backup_enabled: bool = True
    cleanup_days: int = 30

    # 性能配置
    max_context_tokens: int = 65000  # Qwen-Omni 最大上下文窗口
    context_buffer_ratio: float = 0.8

    def validate(self) -> bool:
        """验证配置的合理性"""
        if self.max_history_turns <= 0:
            print("错误：max_history_turns 必须大于0")
            return False

        if (
            self.max_context_turns <= 0
            or self.max_context_turns > self.max_history_turns
        ):
            print("错误：max_context_turns 必须 > 0 且 <= max_history_turns")
            return False

        if self.auto_save_interval <= 0:
            print("错误：auto_save_interval 必须大于0")
            return False

        if not 0.1 <= self.context_buffer_ratio <= 1.0:
            print("错误：context_buffer_ratio 必须在0.1-1.0之间")
            return False

        return True

    def ensure_storage_directory(self) -> Path:
        """确保存储目录存在"""
        storage_path = Path(self.storage_directory)
        storage_path.mkdir(parents=True, exist_ok=True)

        # 创建子目录
        (storage_path / "archived").mkdir(exist_ok=True)
        (storage_path / "backup").mkdir(exist_ok=True)

        return storage_path

    def to_dict(self) -> dict:
        """转换为字典格式，用于保存"""
        return {
            "storage_directory": self.storage_directory,
            "file_format": self.file_format,
            "max_history_turns": self.max_history_turns,
            "max_context_turns": self.max_context_turns,
            "auto_save_interval": self.auto_save_interval,
            "enable_context_injection": self.enable_context_injection,
            "auto_load_last": self.auto_load_last,
            "show_token_stats": self.show_token_stats,
            "debug_mode": self.debug_mode,
            "enable_summary": self.enable_summary,
            "max_summary_age_turns": self.max_summary_age_turns,
            "backup_enabled": self.backup_enabled,
            "cleanup_days": self.cleanup_days,
            "max_context_tokens": self.max_context_tokens,
            "context_buffer_ratio": self.context_buffer_ratio,
        }


@dataclass
class AppConfig:
    """应用配置类，包含所有配置项"""

    api: ApiConfig = field(default_factory=ApiConfig)
    audio: AudioConfig = field(default_factory=AudioConfig)
    conversation: ConversationConfig = field(default_factory=ConversationConfig)

    @classmethod
    def from_file(cls, config_file: str = "config/conversation.toml") -> "AppConfig":
        """从配置文件加载设置"""
        config_path = Path(config_file)
        if not config_path.exists():
            print(f"配置文件 {config_file} 不存在，使用默认配置")
            return cls()

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = toml.load(f)

                # 加载各个配置部分
                api_data = data.get("api", {})
                audio_data = data.get("audio", {})
                conv_data = data.get("conversation", {})

                api_config = ApiConfig(**api_data) if api_data else ApiConfig()
                audio_config = (
                    AudioConfig(**audio_data) if audio_data else AudioConfig()
                )
                conv_config = (
                    ConversationConfig(**conv_data)
                    if conv_data
                    else ConversationConfig()
                )

                return cls(api=api_config, audio=audio_config, conversation=conv_config)
        except Exception as e:
            print(f"读取配置文件失败: {e}，使用默认配置")
            return cls()

    def validate(self) -> bool:
        """验证配置的合理性"""
        return self.conversation.validate()

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "api": {
                "model": self.api.model,
                "api_url": self.api.api_url,
            },
            "audio": {
                "input_format": self.audio.input_format,
                "output_format": self.audio.output_format,
                "voice": self.audio.voice,
                "sample_rate_input": self.audio.sample_rate_input,
                "sample_rate_output": self.audio.sample_rate_output,
                "chunk_size_ms": self.audio.chunk_size_ms,
            },
            "conversation": self.conversation.to_dict(),
        }
