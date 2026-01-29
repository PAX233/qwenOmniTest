"""
Token 统计和速度计算模块
"""

import time
from typing import Optional


class TokenStats:
    """Token 统计类，用于跟踪 token 使用情况"""

    def __init__(self):
        self.input_tokens = 0  # 输入 token 总数
        self.output_tokens = 0  # 输出 token 总数
        self.total_tokens = 0  # 总 token 数

        # 速度统计
        self.output_tokens_this_session = 0  # 本次对话输出的 token
        self.session_start_time: Optional[float] = None

    def add_input_tokens(self, count: int):
        """添加输入 token"""
        self.input_tokens += count
        self.total_tokens += count

    def add_output_tokens(self, count: int):
        """添加输出 token"""
        self.output_tokens += count
        self.total_tokens += count
        self.output_tokens_this_session += count

        # 设置会话开始时间（仅第一次）
        if self.session_start_time is None:
            self.session_start_time = time.time()

    def reset_session(self):
        """重置本次对话统计（用于新的对话轮次）"""
        self.output_tokens_this_session = 0
        self.session_start_time = None

    def get_generation_speed(self) -> float:
        """计算 token 生成速度（tokens/秒）"""
        if self.session_start_time is None or self.output_tokens_this_session == 0:
            return 0.0

        elapsed = time.time() - self.session_start_time
        if elapsed <= 0:
            return 0.0

        return self.output_tokens_this_session / elapsed

    def get_stats_summary(self) -> str:
        """获取统计摘要"""
        speed = self.get_generation_speed()

        return (
            f"📊 Token 使用: {self.total_tokens} "
            f"(输入: {self.input_tokens}, 输出: {self.output_tokens})"
        )

    def get_realtime_stats(self, generating: bool = False) -> str:
        """获取实时统计信息"""
        speed = self.get_generation_speed()

        if generating and speed > 0:
            speed_str = f" ⚡ 生成速度: {speed:.1f} tokens/s"
        else:
            speed_str = ""

        return (
            f"📊 {self.total_tokens} tokens "
            f"(入: {self.input_tokens} / 出: {self.output_tokens})"
            f"{speed_str}"
        )
