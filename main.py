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
from typing import Dict, Any, Optional
from dotenv import load_dotenv
import dashscope
from dashscope.audio.qwen_omni import *

# 导入对话管理模块
sys.path.insert(0, "src")
from qwenomnitest.conversation_config import AppConfig
from qwenomnitest.conversation_manager import ConversationManager

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
# =========================================

# 全局变量
pya: Optional[pyaudio.PyAudio] = None
mic_stream = None
b64_player: Optional["B64PCMPlayer"] = None
conversation = None
conv_manager: Optional[ConversationManager] = None
current_response_text: str = ""  # 当前助手响应的累积文本


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
    def __init__(self):
        super().__init__()
        self.current_transcript = ""
        self.response_in_progress = False

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
        global conversation, b64_player, current_response_text

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

        if "session.created" == event_type:
            print(f"会话创建成功 ID: {message_data.get('session', {}).get('id')}")

        elif "conversation.item.input_audio_transcription.completed" == event_type:
            transcript = message_data.get("transcript", "")
            print(f"你说: {transcript}")
            # 保存用户消息到对话历史
            if conv_manager:
                conv_manager.add_user_message(audio_transcript=transcript)

        elif "response.audio_transcript.delta" == event_type:
            delta = message_data.get("delta", "")
            print(f"{delta}", end="", flush=True)
            # 累积助手响应文本
            current_response_text += delta

        elif "response.audio.delta" == event_type:
            delta = message_data.get("delta", "")
            if b64_player:
                b64_player.add_data(delta)

        elif "input_audio_buffer.speech_started" == event_type:
            print("\n(检测到用户说话，中断播放...)")
            if b64_player:
                b64_player.cancel_playing()
            # 重置当前响应文本
            current_response_text = ""

        elif "response.done" == event_type:
            print("\n--- 回答结束 ---")
            # 保存助手消息到对话历史
            if conv_manager and current_response_text:
                conv_manager.add_assistant_message(
                    text=current_response_text, audio_available=True
                )
                current_response_text = ""
                # 检查是否需要自动保存
                conv_manager.save_current_conversation()

                # 更新上下文注入
                if enable_context_injection and conv_manager:
                    update_conversation_context(conversation)


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
    callback = MyCallback()
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
