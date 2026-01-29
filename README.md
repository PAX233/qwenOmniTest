# qwenOmniTest

Qwen-Omni 实时对话应用，基于 DashScope API 构建，支持完整的对话历史管理和智能上下文注入。

## ✨ 功能特性

### 核心功能
- 🎤 **实时语音对话** - 基于 WebSocket 的低延迟语音交互
- 🔊 **语音输出播放** - 实时播放 AI 生成的语音响应
- 💬 **对话历史管理** - 自动保存所有对话记录
- 🧠 **智能上下文注入** - 自动将历史对话注入到 AI 上下文中
- 💾 **自动保存** - 可配置的自动保存间隔
- 📂 **对话归档** - 支持对话归档和清理

### 高级功能
- ⚙️ **完全可配置** - 所有参数通过 TOML 配置文件管理
- 🔄 **对话恢复** - 支持加载历史对话继续
- 📋 **对话列表** - 查看所有历史对话记录
- 🌐 **多地域支持** - 支持北京和新加坡 API 地域
- 🎯 **上下文控制** - 可配置上下文轮数和注入策略

## 📋 快速开始

### 前置要求

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) - 快速 Python 包管理器
- DashScope API Key

### 安装步骤

```bash
# 1. 克隆项目
git clone <repository-url>
cd qwenOmniTest

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 3. 同步依赖
uv sync

# 4. 配置 API Key
# 创建 .env 文件并添加：
API_KEY=your_dashscope_api_key_here
```

### 运行应用

```bash
# 启动新对话
python main.py

# 列出所有历史对话
python main.py --list-conversations

# 加载指定对话
python main.py --load-conversation <conversation_id>
```

## ⚙️ 配置说明

### 环境变量

在项目根目录创建 `.env` 文件：

```env
API_KEY=sk-your-dashscope-api-key-here
```

### 配置文件

所有配置项在 `config/conversation.toml` 中：

## 🎮 使用示例

### 启动新对话

```bash
python main.py
```

输出示例：
```
当前对话 ID: 6a03bc27-47fd-4f75-9923-59503095ff82
正在启动 Qwen-Omni 实时对话...
✓ 初始上下文已注入
--- 已连接到服务器，初始化麦克风 ---
会话创建成功 ID: session_xxx
现在可以开始说话了 (按 Ctrl+C 退出)
```

### 列出历史对话

```bash
python main.py --list-conversations
```

输出示例：
```
=== 历史对话列表 ===
1. ID: 6a03bc27-47fd-4f75-9923-59503095ff82
   创建时间: 2025-01-29T12:34:56.789Z
   最后更新: 2025-01-29T12:45:12.345Z
   对话轮数: 5
   文件路径: ./conversations/6a03bc27-47fd-4f75-9923-59503095ff82.json

2. ID: 7b14cd38-58ge-5g86-0034-60614106gg93
   创建时间: 2025-01-28T10:20:30.123Z
   最后更新: 2025-01-28T11:15:45.678Z
   对话轮数: 8
   文件路径: ./conversations/7b14cd38-58ge-5g86-0034-60614106gg93.json
```

### 加载历史对话

```bash
python main.py --load-conversation 6a03bc27-47fd-4f75-9923-59503095ff82
```

输出示例：
```
恢复活跃会话: 6a03bc27-47fd-4f75-9923-59503095ff82
当前对话 ID: 6a03bc27-47fd-4f75-9923-59503095ff82
正在启动 Qwen-Omni 实时对话...
✓ 上下文已更新（包含 3 轮历史对话）
...
```

## 📁 项目结构

```
qwenOmniTest/
├── main.py                          # 主程序入口
├── pyproject.toml                   # 项目依赖配置
├── uv.lock                         # 依赖锁定文件
├── .env                            # 环境变量（API Key）
├── .gitignore                      # Git 忽略文件
├── README.md                       # 项目文档
├── config/
│   └── conversation.toml            # 应用配置文件
├── src/
│   └── qwenomnitest/
│       ├── __init__.py
│       ├── conversation_config.py    # 配置管理模块
│       ├── conversation_models.py     # 数据模型
│       └── conversation_manager.py   # 对话管理器
└── conversations/                  # 对话存储目录（自动创建）
    ├── active_conversation.json      # 当前活跃对话
    ├── archived/                   # 已归档对话
    └── backup/                    # 备份文件
```

## 🔧 技术栈

- **Python** 3.11+
- **DashScope SDK** - Qwen-Omni 实时语音 API
- **PyAudio** - 音频输入输出
- **python-dotenv** - 环境变量管理
- **toml** - 配置文件解析

## 🧠 上下文注入机制

应用实现了智能的上下文注入机制，使 AI 能够记住对话历史：

### 工作原理

1. **初始注入** - 会话开始时，将最近 N 轮对话格式化为系统提示
2. **动态更新** - 每轮对话完成后，更新上下文提示
3. **可配置** - 通过 `max_context_turns` 控制注入的对话轮数

### 示例系统提示

```
你是一个友好、乐于助人的AI助手。

以下是最近的对话历史：
用户: 你好
助手: 你好！有什么可以帮助你的吗？
用户: 我想了解天气
助手: 当然，你想了解哪个城市的天气？

请记住以上对话历史，保持回答的连贯性和一致性。如果用户询问之前讨论过的内容，请参考历史记录。回答要简洁明了。
```

## 📊 对话数据格式

每个对话存储为 JSON 文件，包含以下结构：

```json
{
  "conversation_id": "uuid-string",
  "metadata": {
    "created_at": "2025-01-29T12:34:56.789Z",
    "last_updated": "2025-01-29T12:45:12.345Z",
    "total_turns": 5,
    "total_tokens_estimated": 1234
  },
  "config": {
    "voice": "Chelsie",
    "max_history_turns": 10,
    "auto_save_interval": 3
  },
  "messages": [
    {
      "turn_id": 1,
      "role": "user",
      "timestamp": "2025-01-29T12:35:00.000Z",
      "content": {
        "text": "",
        "audio_transcript": "你好",
        "audio_available": true
      }
    },
    {
      "turn_id": 1,
      "role": "assistant",
      "timestamp": "2025-01-29T12:35:05.000Z",
      "content": {
        "text": "你好！有什么可以帮助你的吗？",
        "audio_available": true
      }
    }
  ]
}
```

## ⚠️ 注意事项

### API 限制
- 会话最长时长：120 分钟
- 上下文窗口：65,536 tokens
- 上下文轮数建议：3-5 轮（避免超出 token 限制）

### 音频设备
- 确保麦克风和扬声器正常工作
- Windows 上可能需要安装 PyAudio 依赖：
  ```bash
  pip install pipwin
  pipwin install pyaudio
  ```

### 网络要求
- 需要稳定的网络连接
- WebSocket 连接需要支持 wss:// 协议
- 建议使用北京地域获得更低延迟

## 🐛 故障排除

### 导入错误
```
ModuleNotFoundError: No module named 'toml'
```
**解决方案**：运行 `uv sync` 安装依赖

### 麦克风错误
```
OSError: [Errno -9996] Invalid input device index
```
**解决方案**：
1. 检查麦克风是否连接
2. 检查系统音频设置
3. 确认 PyAudio 正确安装

### API 连接错误
```
ConnectionError: Failed to connect to wss://dashscope.aliyuncs.com/...
```
**解决方案**：
1. 检查网络连接
2. 验证 API Key 是否正确
3. 尝试使用新加坡地域

## 🚀 未来展望

项目核心功能已基本完成，作为一个轻量化的语音对话工具，未来可能考虑以下实用改进：

- [ ] **对话导出** - 将对话导出为 Markdown 或文本格式，便于保存和分享
- [ ] **全文搜索** - 在所有历史对话中搜索关键词，快速定位内容
- [ ] **对话摘要** - 自动生成长对话的简要摘要，便于回顾
- [ ] **模型切换** - 支持选择不同的 Qwen-Omni 模型版本（如适用）

本项目定位为轻量级语音对话工具，功能已相对完整，未来更新以实用为主。

如需贡献，欢迎提交 Issue 和 Pull Request！

## 📄 许可证

MIT License

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

## 📞 联系方式

- 项目仓库：[GitHub Repository]
- DashScope 文档：[DashScope 官方文档]
