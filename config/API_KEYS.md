# Yuiro — API 服务申请清单与占位说明

> 本文件列出 Yuiro 可能用到的**云端 API**，以及**到哪些网站申请/获取 Key**。
> 约定：配置只存 keychain 引用（`service=yuiro-*`），**不存明文**（keychain 读写见 `engine/yuiro/keychain.py`）。
> 本地/免费能力（silero、faster-whisper、edge-tts、Ollama）无需任何 Key 即可跑通。

---

## 申请清单（按是否必须排序）

### ✅ 可选但强烈推荐（用于对话质量）
| 服务 | 用途 | 申请网站 | 说明 |
|---|---|---|---|
| **DeepSeek** | 主 LLM（便宜、中文好、OpenAI 兼容） | https://platform.deepseek.com/ | 注册→创建 API Key；余额充值 |
| **OpenAI** | 备用 LLM / 视觉(VLM) | https://platform.openai.com/api-keys | 需绑卡/付费；`gpt-4o` 视觉 |
| **Anthropic (Claude)** | 备用 LLM | https://console.anthropic.com/ | 可选 |
| **硅基流动 SiliconFlow** | 本地化大模型/视觉引导 GUI 的 VLM | https://cloud.siliconflow.cn/ | my-neuro 用 `Qwen2.5-VL` 做"看屏定位"即走它 |

### 🔑 完全本地、**无需任何 Key**（推荐优先）
| 能力 | 方案 | 说明 |
|---|---|---|
| 语音转文字 ASR | **faster-whisper**（本地） | 模型下载自 HuggingFace，无需 Key |
| 语音活动检测 VAD | **silero-vad**（本地） | pip 安装，无需 Key |
| 文字转语音 TTS | **edge-tts**（免费） | 微软免费，无需 Key；需联网 |
| 本地 LLM | **Ollama / llama.cpp** | 全离线，无需 Key |
| 记忆向量 | **BGE-M3**（本地） | HuggingFace 下载，无需 Key |

### 🔋 可选增强（有 Key 更佳，无则跳过）
| 服务 | 用途 | 申请网站 |
|---|---|---|
| Azure TTS | 更自然中文语音 | https://portal.azure.com/ （Cognitive Services） |
| 火山引擎 TTS | 高质量中文（OpenDesktop 用过） | https://console.volcengine.com/ （语音技术→TTS） |
| Tavily / SerpAPI | 联网搜索工具 | https://tavily.com/ / https://serpapi.com/ |
| PostHog | 遥测（AIRI 用） | https://posthog.com/ 可不接 |

---

## 如何填入（占位→生效）
所有 Key 走 **OS 系统 keychain**（Keyring），配置文件只写 keychain 引用：
```toml
# config.toml 示例（key 不落盘）
[llm]
provider = "openai"        # 或 deepseek / ollama
base_url = "https://api.deepseek.com/v1"   # DeepSeek 兼容 OpenAI
model = "deepseek-chat"
key_ref = "yuiro/providers/openai"         # ← keychain 槽位
```
```powershell
# 一次性把 Key 写入系统 keychain（PowerShell 示意）
$env:YUIRO_KEY = "你的Key"
python -c "import keyring; keyring.set_password('yuiro','providers/openai', __import__('os').environ['YUIRO_KEY'])"
```

> **占位现状**：M0 阶段 `config.example.toml` 里 `llm.base_url/model` 已是占位；跑通"文本对话"前，最省事是**本地 Ollama**（0 Key）或先接 DeepSeek（1 个 Key）。
