import os
import base64
import signal
import sys
import time
import pyaudio
import contextlib
import threading
import queue
import argparse
import json
import logging
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import dashscope
from dashscope.audio.qwen_omni import *

# 导入对话管理模块
sys.path.insert(0, "src")
from qwenomnitest.conversation_config import AppConfig
from qwenomnitest.conversation_manager import ConversationManager
from qwenomnitest.token_stats import TokenStats

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# 加载环境变量
load_dotenv()

# ================= 配置区 =================
# 1. 从环境变量加载 API Key
api_key = os.getenv("API_KEY")
if not api_key:
    raise EnvironmentError("API_KEY 环境变量未设置，请在 .env file 配置！")
dashscope.api_key = api_key

# 2. 加载配置文件
app_config = AppConfig.from_file("config/conversation.toml")

# 3. 获取配置参数
api_model = app_config.api.model
api_url = app_config.api.api_url
voice = app_config.audio.voice
input_audio_format_str = app_config.audio.input_format
output_audio_format_str = app_config.audio.output_format
sample_rate_input = app_config.audio.sample_rate_input
sample_rate_output = app_config.audio.sample_rate_output
chunk_size_ms = app_config.audio.chunk_size_ms

# 4. 对话管理配置
auto_save_interval = app_config.conversation.auto_save_interval
enable_context_injection = app_config.conversation.enable_context_injection
max_context_turns = app_config.conversation.max_context_turns
show_token_stats = app_config.conversation.show_token_stats  # 是否显示 token 统计信息
debug_mode = app_config.conversation.debug_mode  # 是否启用调试模式
# =========================================

# 全局变量
pya: Optional[pyaudio.PyAudio] = None
mic_stream = None
b64_player: Optional["B64PCMPlayer"] = None
conversation = None
conv_manager: Optional[ConversationManager] = None
current_response_text: str = ""  # 当前助手响应的累积文本
token_stats = TokenStats()  # Token 统计


class B64PCMPlayer:
    """音频播放器类：负责解码 Base64 并通过 PyAudio 播放"""

    def __init__(self, pya: pyaudio.PyAudio, sample_rate=24000, chunk_size_ms=100):
        self.pya = pya
        self.sample_rate = sample_rate
        self.chunk_size_bytes = chunk_size_ms * sample_rate * 2 // 1000
        self.player_stream = pya.open(
            format=pyaudio.paInt16, channels=1, rate=sample_rate, output=True
        )
        self.raw_audio_buffer = queue.Queue()
        self.b64_audio_buffer = queue.Queue()
        self.status = "playing"
        self.decoder_thread = threading.Thread(target=self.decoder_loop, daemon=True)
        self.player_thread = threading.Thread(target=self.player_loop, daemon=True)
        self.decoder_thread.start()
        self.player_thread.start()

    def decoder_loop(self):
        while self.status != "stop":
            try:
                recv_audio_b64 = self.b64_audio_buffer.get(timeout=0.1)
                recv_audio_raw = base64.b64decode(recv_audio_b64)
                for i in range(0, len(recv_audio_raw), self.chunk_size_bytes):
                    self.raw_audio_buffer.put(
                        recv_audio_raw[i : i + self.chunk_size_bytes]
                    )
            except queue.Empty:
                continue

    def player_loop(self):
        while self.status != "stop":
            try:
                recv_audio_raw = self.raw_audio_buffer.get(timeout=0.1)
                self.player_stream.write(recv_audio_raw)
            except queue.Empty:
                continue

    def cancel_playing(self):
        """当用户开始说话时，清空播放队列以中断 AI 的回答"""
        while not self.b64_audio_buffer.empty():
            self.b64_audio_buffer.get()
        while not self.raw_audio_buffer.empty():
            self.raw_audio_buffer.get()

    def add_data(self, data):
        self.b64_audio_buffer.put(data)

    def shutdown(self):
        self.status = "stop"
        self.player_stream.stop_stream()
        self.player_stream.close()


class MyCallback(OmniRealtimeCallback):
    def __init__(self, debug_mode: bool = False):
        super().__init__()
        self.current_transcript = ""
        self.response_in_progress = False
        self.generation_started = False
        self.last_input_text = ""  # 用于累积完整输入文本
        self.debug_mode = debug_mode  # 调试模式，打印完整事件数据（默认关闭）
        self.has_api_token_data = False  # API 是否返回了 token 数据

    def on_open(self) -> None:
        global pya, mic_stream, b64_player
        print("--- 已连接到服务器，初始化麦克风 ---")
        pya = pyaudio.PyAudio()
        # 录音配置
        mic_stream = pya.open(
            format=pyaudio.paInt16, channels=1, rate=sample_rate_input, input=True
        )
        b64_player = B64PCMPlayer(
            pya, sample_rate=sample_rate_output, chunk_size_ms=chunk_size_ms
        )

    def on_close(self, close_status_code, close_msg) -> None:
        print(f"--- 连接已关闭: {close_status_code}, {close_msg} ---")
        # 保存对话
        if conv_manager:
            conv_manager.save_current_conversation()
        sys.exit(0)

    def on_event(self, message: str) -> None:
        global conversation, b64_player, current_response_text, token_stats

        # 解析消息
        try:
            if isinstance(message, str):
                message_data = json.loads(message)
            else:
                message_data = message
        except (json.JSONDecodeError, TypeError):
            return

        event_type = (
            message_data.get("type") if isinstance(message_data, dict) else None
        )

        if not event_type:
            return

        # 调试：打印完整事件数据
        if self.debug_mode and show_token_stats:
            print(f"\n[DEBUG] Event: {event_type}")
            # 打印所有键
            for key in message_data.keys():
                if key not in ["delta", "base64_data"]:  # 跳过二进制数据
                    print(f"  {key}: {message_data[key]}")

        if "session.created" == event_type:
            print(f"会话创建成功 ID: {message_data.get('session', {}).get('id')}")

        elif "conversation.item.input_audio_transcription.completed" == event_type:
            transcript = message_data.get("transcript", "")
            print(f"你说: {transcript}")
            # 保存用户消息到对话历史
            if conv_manager:
                conv_manager.add_user_message(audio_transcript=transcript)
            # 保存完整输入文本，用于 token 计算
            self.last_input_text = transcript
            # 尝试提取 API 返回的输入 token
            if show_token_stats:
                self.extract_token_usage(message_data, event_type)

        elif "response.audio_transcript.delta" == event_type:
            delta = message_data.get("delta", "")
            print(f"{delta}", end="", flush=True)
            # 累积助手响应文本
            current_response_text += delta

            # 开始生成时重置统计
            if show_token_stats and not self.generation_started:
                self.generation_started = True
                token_stats.reset_session()
            # 尝试提取 API 返回的输出 token
            if show_token_stats:
                self.extract_token_usage(message_data, event_type)

        elif "response.audio.delta" == event_type:
            delta = message_data.get("delta", "")
            if b64_player:
                b64_player.add_data(delta)

        elif "input_audio_buffer.speech_started" == event_type:
            print("\n(检测到用户说话，中断播放...)")
            if b64_player:
                b64_player.cancel_playing()
            # 重置当前响应文本和生成标志
            current_response_text = ""
            self.generation_started = False

        elif "response.done" == event_type:
            print("\n--- 回答结束 ---")
            # 如果 API 没有在之前的事件中返回 token 信息，使用文本估算
            if show_token_stats:
                # 只在未从 API 获取到 token 时才使用估算
                if not self.has_api_token_data and current_response_text:
                    print("[INFO] API 未返回 token 数据，使用文本估算")
                    self.estimate_tokens_from_text()

                # 显示统计
                print(token_stats.get_stats_summary())

            # 保存助手消息到对话历史
            if conv_manager and current_response_text:
                conv_manager.add_assistant_message(
                    text=current_response_text, audio_available=True
                )
                current_response_text = ""
                # 检查是否需要自动保存
                conv_manager.save_current_conversation()

            # 重置生成状态和 token 数据标志
            self.generation_started = False
            self.has_api_token_data = False  # 为下一轮对话重置

            # 更新上下文注入
            if enable_context_injection and conv_manager:
                update_conversation_context(conversation)

    def extract_token_usage(self, message_data: dict, event_type: str):
        """从 API 响应中提取 token 使用信息"""
        global token_stats

        if not show_token_stats:
            return

        # 检查常见的 token 字段
        possible_token_fields = [
            "usage",
            "token_count",
            "tokens",
            "input_tokens",
            "output_tokens",
            "total_tokens",
            "input_length",
            "output_length",
        ]

        for field in possible_token_fields:
            if field in message_data:
                value = message_data[field]

                # 处理不同的格式
                if isinstance(value, dict):
                    # 可能是 {"input": 10, "output": 20}
                    if "input" in value:
                        token_stats.add_input_tokens(int(value["input"]))
                        print(f"[TOKEN] API 返回输入 tokens: {value['input']}")
                    if "output" in value:
                        token_stats.add_output_tokens(int(value["output"]))
                        print(f"[TOKEN] API 返回输出 tokens: {value['output']}")
                elif isinstance(value, (int, float)):
                    # 单个数值
                    if "input" in field.lower():
                        token_stats.add_input_tokens(int(value))
                        print(f"[TOKEN] API 返回输入 tokens: {value}")
                    elif "output" in field.lower():
                        token_stats.add_output_tokens(int(value))
                        print(f"[TOKEN] API 返回输出 tokens: {value}")

                self.has_api_token_data = True

    def estimate_tokens_from_text(self):
        """当 API 未返回 token 信息时，基于文本估算"""
        global token_stats

        # 输入 token：基于用户输入文本
        if self.last_input_text:
            # 中文：每个字符约 1.0 token，英文：每个字符约 0.25 token
            input_text = self.last_input_text
            # 判断文本类型
            has_chinese = any("\u4e00" <= c <= "\u9fff" for c in input_text)
            if has_chinese or (len(input_text) > 0 and ord(input_text[0]) > 127):
                # 中文为主
                input_tokens = int(len(input_text) * 1.0)
            else:
                # 英文为主
                input_tokens = int(len(input_text) * 0.25)

            token_stats.add_input_tokens(input_tokens)
            print(
                f"[ESTIMATE] 输入 tokens 估算: {input_tokens} (长度: {len(input_text)})"
            )

        # 输出 token：基于助手响应文本
        if current_response_text:
            output_text = current_response_text
            has_chinese = any("\u4e00" <= c <= "\u9fff" for c in output_text)
            if has_chinese or (len(output_text) > 0 and ord(output_text[0]) > 127):
                # 中文为主
                output_tokens = int(len(output_text) * 1.0)
            else:
                # 英文为主
                output_tokens = int(len(output_text) * 0.25)

            token_stats.add_output_tokens(output_tokens)
            print(
                f"[ESTIMATE] 输出 tokens 估算: {output_tokens} (长度: {len(output_text)})"
            )


def update_conversation_context(conv_obj):
    """更新会话上下文，注入历史对话"""
    global conv_manager

    if not conv_manager or not conv_manager.current_conversation:
        return

    # 构建上下文提示
    context_prompt = conv_manager.build_context_prompt(max_turns=max_context_turns)

    if not context_prompt:
        # 没有历史对话，使用默认提示
        instructions = (
            "你是一个友好、乐于助人的AI助手。请用简洁明了的方式回答用户的问题。"
        )
    else:
        # 使用历史对话作为上下文
        instructions = f"""你是一个友好、乐于助人的AI助手。

{context_prompt}

请记住以上对话历史，保持回答的连贯性和一致性。如果用户询问之前讨论过的内容，请参考历史记录。回答要简洁明了。"""

    # 更新会话配置
    try:
        conv_obj.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=voice,
            input_audio_format=input_audio_format,
            output_audio_format=output_audio_format,
            enable_input_audio_transcription=True,
            input_audio_transcription_model="gummy-realtime-v1",
            enable_turn_detection=True,
            turn_detection_type="server_vad",
            instructions=instructions,
        )
        print("✓ 上下文已更新")
    except Exception as e:
        print(f"⚠ 更新上下文失败: {e}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(description="Qwen-Omni 实时对话应用")
    parser.add_argument(
        "--load-conversation", type=str, default=None, help="加载指定 ID 的历史对话"
    )
    parser.add_argument(
        "--list-conversations", action="store_true", help="列出所有历史对话"
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # 初始化对话管理器
    conv_manager = ConversationManager(app_config.conversation)

    # 处理命令行参数
    if args.list_conversations:
        print("\n=== 历史对话列表 ===")
        conv_list = conv_manager.get_conversation_list()
        if not conv_list:
            print("没有历史对话")
        else:
            for idx, conv in enumerate(conv_list, 1):
                print(f"{idx}. ID: {conv['conversation_id']}")
                print(f"   创建时间: {conv['created_at']}")
                print(f"   最后更新: {conv['last_updated']}")
                print(f"   对话轮数: {conv['total_turns']}")
                print(f"   文件路径: {conv['file_path']}")
                print()
        sys.exit(0)

    if args.load_conversation:
        success = conv_manager.load_conversation(args.load_conversation)
        if not success:
            print(f"加载对话失败，将开始新对话")
            conv_manager.start_new_conversation(voice=voice)
    else:
        # 开始新对话
        conv_manager.start_new_conversation(voice=voice)

    if conv_manager.current_conversation:
        print(f"当前对话 ID: {conv_manager.current_conversation.conversation_id}")

    print("正在启动 Qwen-Omni 实时对话...")
    callback = MyCallback(debug_mode=debug_mode)
    conversation = OmniRealtimeConversation(
        model=api_model, callback=callback, url=api_url
    )

    conversation.connect()

    # 配置会话参数
    # 将音频格式字符串转换为枚举
    input_audio_format = AudioFormat[input_audio_format_str]
    output_audio_format = AudioFormat[output_audio_format_str]

    # 初始上下文注入（如果启用了上下文注入）
    if enable_context_injection:
        context_prompt = conv_manager.build_context_prompt(max_turns=max_context_turns)

        if context_prompt:
            instructions = f"""你是一个友好、乐于助人的AI助手。

{context_prompt}

请记住以上对话历史，保持回答的连贯性和一致性。如果用户询问之前讨论过的内容，请参考历史记录。回答要简洁明了。"""
        else:
            instructions = (
                "你是一个友好、乐于助人的AI助手。请用简洁明了的方式回答用户的问题。"
            )

        conversation.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=voice,
            input_audio_format=input_audio_format,
            output_audio_format=output_audio_format,
            enable_input_audio_transcription=True,
            input_audio_transcription_model="gummy-realtime-v1",
            enable_turn_detection=True,
            turn_detection_type="server_vad",
            instructions=instructions,
        )
        print("✓ 初始上下文已注入")
    else:
        # 不注入上下文，使用默认配置
        conversation.update_session(
            output_modalities=[MultiModality.AUDIO, MultiModality.TEXT],
            voice=voice,
            input_audio_format=input_audio_format,
            output_audio_format=output_audio_format,
            enable_input_audio_transcription=True,
            input_audio_transcription_model="gummy-realtime-v1",
            enable_turn_detection=True,
            turn_detection_type="server_vad",
        )

    def signal_handler(sig, frame):
        print("\n正在停止...")
        if conversation:
            conversation.close()
        if b64_player:
            b64_player.shutdown()
        if conv_manager:
            conv_manager.save_current_conversation()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)
    print("现在可以开始说话了 (按 Ctrl+C 退出)")

    while True:
        if mic_stream:
            try:
                # 读取麦克风数据并发送
                audio_data = mic_stream.read(3200, exception_on_overflow=False)
                audio_b64 = base64.b64encode(audio_data).decode("ascii")
                conversation.append_audio(audio_b64)
            except Exception as e:
                print(f"麦克风读取错误: {e}")
                break
        time.sleep(0.01)
