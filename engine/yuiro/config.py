"""Unified configuration loading for the Yuiro engine.

Reads config.toml with env-var overrides. Secrets are read directly from
runtime input or environment variables.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import tomllib


@dataclass
class ServerConfig:
    host: str = "127.0.0.1"
    port: int = 8200
    shared_secret: str = ""

    @classmethod
    def from_dict(cls, d: dict) -> "ServerConfig":
        secret = os.environ.get("YUIRO_SHARED_SECRET") or d.get("shared_secret", "")
        return cls(
            host=d.get("host", "127.0.0.1"),
            port=int(d.get("port", 8200)),
            shared_secret=secret,
        )


@dataclass
class LLMConfig:
    provider: str = "openai"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4o-mini"
    # 采样温度：工具调用场景需低温度以提升确定性。qwen3 系列在流式+多 system
    # 消息下高温会不稳定地漏掉 tool_call；0.1 在实测中触发率最高（0 反而更随机）。
    temperature: float = 0.1


# LLM 提供商预设：选择 provider 时若 base_url/model 仍为默认值则自动填充。
# 千问走阿里云百炼 DashScope 的 OpenAI 兼容端点。
LLM_PROVIDER_PRESETS: dict[str, tuple[str, str]] = {
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "deepseek": ("https://api.deepseek.com/v1", "deepseek-chat"),
    "ollama": ("http://localhost:11434/v1", "qwen2.5:7b"),
    "qwen": ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen-plus"),
}


@dataclass
class VADConfig:
    provider: str = "fsmn"  # silero | fsmn（FunASR 流式 VAD，默认）
    probability_threshold: float = 0.4  # 兼容 silero 旧配置
    db_threshold: float = 60.0
    smoothing_window: int = 5
    required_hits: int = 3
    required_misses: int = 24  # silero 旧字段：静音确认帧数（@512采样≈0.77s）
    # 前置补白：VAD 确认"开始说话"需累积若干帧（required_hits + 平滑窗口滞后），
    # 这段时间内用户已开口，若不保留其音频就会被吞掉开头几个字（front-end clipping）。
    # 这里在判定开始前保留最近 pre_roll_ms 的音频，SpeechStart 时并入待识别音频。
    pre_roll_ms: int = 400
    # 播放期「她正在说话」时，认作**用户插话**所需的能量余量（相对静音门槛上抬的 dB）。
    # 见 `audio.VoicePipeline._barge_min_db`：值越大越不容易被"她自己的外放声"或
    # 旁人噪声误判成插话（代价是插话需要说得更响一点）。
    barge_margin_db: float = 12.0
    # ★ 打断（barge-in）总开关。**默认关闭**：
    #   当前的语音识别与噪声屏蔽还不够可靠，自动打断容易被旁人说话 / 环境噪声误触发，
    #   反而把她正常的回复切碎。所以先做成"可开关的功能"，而不是不可关的融合属性。
    #   关闭时：她说话期间你说的话**不打断她**，但仍会被完整录下来 ——
    #   等她说完后照常识别并回应（"不打断，也不丢话"）。
    #   ⚠ 只关"VAD 自动打断"；**显式打断**（前端主动发 interrupt、发新文字消息顶掉
    #     旧回复）不受它影响 —— 那是用户的明确意图。
    barge_in_enabled: bool = False
    # FSMN 流式端点检测参数（解决"短暂停顿过早截断 vs 延迟高"两难）
    max_end_silence_time: int = 800  # 尾静音判停阈值(ms)，越小越灵敏/越早截断
    speech_pad: int = 200  # 句首/句尾补零(ms)，避免吞音
    chunk_size: list[int] = field(default_factory=lambda: [0, 10, 24])  # FSMN 流式 chunk(d/dec/look)
    local_model_path: str | None = None  # FSMN-VAD 本地权重目录（留空走 modelscope 自动下载）


@dataclass
class ASRConfig:
    provider: str = "funasr-sensevoice"  # faster-whisper | funasr-sensevoice（默认）
    model: str = "iic/SenseVoiceSmall"  # funasr 模型 id；faster-whisper 时填 small/base/...
    version: str = "v4"  # funasr AutoModel 版本
    device: str = "auto"
    compute_type: str = "float16"  # funasr 走 torch dtype；faster-whisper 用 int8/float16
    language: str | None = "auto"  # SenseVoice 支持 auto/zh/en/ja/ko；faster-whisper 填 zh
    beam_size: int = 5  # 束搜索宽度，越大越准
    vad_filter: bool = False  # faster-whisper 专用
    initial_prompt: str | None = None  # faster-whisper 引导提示
    # SenseVoice 专属：自带标点 + ITN + 情感标签，无需额外后处理
    local_model_path: str | None = None  # 本地权重目录（留空走 modelscope 自动下载）
    llm_polish: bool = False  # 低置信/含歧义时调用 LLM 二次润色（口语→书面语泛化）


@dataclass
class TTSConfig:
    provider: str = "edge-tts"      # edge-tts（云端兜底） | cosyvoice（本地 tts-server） | gptsovits（本地 Bundle） | siliconflow（云端克隆）
    segment_streaming: bool = True
    # A1：LLM 流式接 TTS —— 句子一到就送去合成，首句提前 1~3 秒出声。
    # 关掉则退回"等整段回复再分句合成"的旧行为（保底回退用）。
    stream_llm: bool = True
    # 本地 TTS 后端型号（仅 cosyvoice provider 生效）：
    #   cosyvoice2 —— 默认，约 2GB 显存，与 SenseVoice 共存于 3060 6GB 可行；
    #   cosyvoice3 —— 预留接口，需 6-10GB 显存，当前 3060 必 OOM；
    #                 仅当 ASR 外移到独立进程（或换更大显存）后启用，否则启动时报明确指引。
    backend: str = "cosyvoice2"
    # 本地 TTS 服务（CosyVoice2/3 独立进程）配置
    tts_url: str = "http://127.0.0.1:5005"
    # 角色参考音频（零样本克隆来源，来自 my-neuro 的 肥牛.wav，已复制为 assets/voices/neuro_prompt.wav）
    reference_wav: str = "../assets/voices/neuro_prompt.wav"
    # 参考音频转写文本（CosyVoice2 zero-shot 必需）。
    # 当前为近似占位（肥牛.wav 真实内容待用户提供准确转写后替换，可提升克隆保真度）。
    reference_text: str = "嗯，你说什么？我刚才在想别的事情，你再说一遍试试看。"
    instruct_zh: str = "用自然、慵懒又带点毒舌的中文语气说。"
    instruct_en: str = "Speak in a natural, slightly sarcastic English tone."
    # S52：朗读语言为 ja 时用的语气指令（留空则退回 instruct_zh）。
    instruct_ja: str = "用自然、慵懒又带点毒舌的日文语气说。"
    default_language: str = "auto"
    # 统一「语音回复 TTS」开关（默认开）：控制"她的回复是否出声"，覆盖两条输入链路——
    #   开：语音输入与文字输入的回复都走 TTS 合成并播放；
    #   关：两条链路的回复都**不做 TTS**、不出声（语音链路保留 ASR+LLM 的文字回复）。
    # 运行时由 /api/config PUT 就地修改（回合时读取，即时生效，无需重启引擎）。
    reply_tts_enabled: bool = True
    # GPT-SoVITS 专用：text_language（zh | en | auto），音色在服务端固化无需参考音频
    tts_text_language: str = "auto"
    # SiliconFlow 云端 TTS（provider=siliconflow 生效）：零样本声音克隆，零本地显存占用
    siliconflow_key: str = ""                                   # API key；为空时尝试从 keychain 读取（service: yuiro-siliconflow）
    siliconflow_model: str = "FunAudioLLM/CosyVoice2-0.5B"      # 克隆/合成所用基础模型
    siliconflow_voice: str = "FunAudioLLM/CosyVoice2-0.5B:anna"
    # Fish 密钥仅存 OS keychain，禁止新增配置明文字段。
    fish_model: str = "s2.1-pro"
    fish_reference_id: str = ""
    fish_latency: str = "balanced"
    fish_speed: float = 1.0
    fish_transport: str = "http"
    fish_first_chunk_ms: int = 400  # 首包40960B≈464ms；400ms首块，后续仍480ms。
    # 克隆用参考音频（绝对路径或相对引擎工作目录）；留空则用模型内置音色
    siliconflow_reference_wav: str = "../assets/voices/Model/Neuro/参考音频.wav"
    siliconflow_reference_text: str = ""                        # 参考音频转写文本（克隆保真度关键）


@dataclass
class LanguageConfig:
    """输出语言解耦（S52）：**展示语言**与**朗读语言**分开设。

    背景：语音克隆的参考音频/参考转写是单语的，中文参考念英文会带夹生腔；
    而"文字给谁看"和"声音怎么念"本来是两件事，此前被同一段 LLM 原文绑死。

    设计：Agent 内部（LLM 往返、工具、history、三层记忆）**恒为中文**，
    只在出口分叉——因此本段**没有**"内部语言"开关（刻意不暴露，避免把 Agent
    内部也翻掉、污染记忆与跨会话检索一致性）。

    - ``display_language``：气泡文字语言（zh/en/ja）。默认 zh = 现状。
    - ``speak_language``：朗读语言（auto/zh/en/ja）。默认 auto = 沿用"按文本判定"
      的既有行为；设为 en/ja 时，朗读文本会先被转换再送 TTS。
    - ``translate_mode``：sentence = 逐句转换（保住 A1"首句先出声"）；
      full = 整段一次转换（只一次调用，但推迟首句，作为保底）。
    - ``translate_timeout_s``：单次转换超时；超时回退原文（绝不静默无声）。

    默认值保证**零回归**：zh + auto 时渲染器全部透传，不产生任何额外 LLM 调用。
    """

    display_language: str = "zh"
    speak_language: str = "auto"
    translate_mode: str = "sentence"
    translate_timeout_s: float = 6.0


@dataclass
class PersonaConfig:
    """人设段：收拢散落的人设表现参数（提示词/音色/情绪文案/表情映射/记忆主体）。

    提示词由三段职责分离（便于热重载只换人设不碰系统约束）：
    - system_prompt  ：系统提示词——身份锚定 + 行为红线 + 工具调用铁律（不含性格）。
    - persona_prompt ：人设提示词——性格、语气、说话风格、emoji 铁律等角色扮演内容。
    标量字段（name/display_name/system_prompt/persona_prompt/voice/model_path/memory_subject）
    在调试台可编辑；emotion_hints/expression_map 为 TOML 子表，仅引擎读取，调试台不渲染。
    """

    name: str = "Yuiro"
    display_name: str = "幽萝"
    # 提示词默认**留空** → 回退引擎内置（yuiro/agent/__init__.py 的
    # _DEFAULT_SYSTEM_PROMPT / _DEFAULT_PERSONA_PROMPT）。
    # **不要在这里再写一份**：历史上 config.py、agent 模块、config.toml 三处各存一份，
    # 结果逐渐不同步 —— 这里那份甚至还在教模型用早已废弃的 media_control 控制网易云，
    # 典型"改一处漏两处"。真相源只有一个：agent 模块里的内置默认。
    system_prompt: str = ""
    persona_prompt: str = ""
    voice: str = "zh-CN-XiaoxiaoNeural"
    # 默认模型 = 桃瀬ひより（官方示例；8 个手写表情 + Idle 9 个动作，见 live2d/hiyori）。
    # 肥牛 改用 [persona.profiles.feiniu] 档案承载它的表现（见下 profiles 字段说明）。
    model_path: str = "/live2d/hiyori/Hiyori.model3.json"
    # 正在对话的用户就是 Yui 本人，记忆主体用真名（而非泛称"用户"）以保证人称一致。
    memory_subject: str = "Yui"
    emotion_hints: dict[str, str] = field(default_factory=lambda: {
        "happy": "你现在心情不错，语气轻快温暖。",
        "sad": "你现在有点低落，语气温柔安抚。",
        "excited": "你现在很兴奋，语气活泼有精神。",
        "bored": "你现在有点无聊，语气可以俏皮地找点话题。",
        "angry": "你现在有点生气，语气保持冷静克制。",
    })
    # 情绪 → 模型表情名。**默认对齐默认模型（Hiyori）**：它的 8 个表情是我们手写的
    # exp3.json，名字即语义（happy/sad/angry/surprised/shy/playful/think/bored）。
    # 换别的模型时优先用 [persona.profiles.<档案>].expression_map 覆盖；
    # 没有档案的模型沿用本表 —— 所以本表要跟"默认模型"保持一致，否则换回去会不匹配。
    #
    # 肥牛的表现收在 [persona.profiles.feiniu]：它只有 6 个**有效**表情（expression1
    # 的定义是空的，参数列表为空 → 无效果），且模型本身没有"思考/无聊"：
    #   expression2=biaoqing1 开心 · expression3=biaoqing2 生气 · expression4=biaoqing3 难过
    #   expression5=biaoqing4 惊讶 · expression6=biaoqing5 害羞 · expression7=biaoqing6 俏皮
    expression_map: dict[str, str] = field(default_factory=lambda: {
        "happy": "happy",         # 开心
        "sad": "sad",             # 难过
        "angry": "angry",         # 生气
        "excited": "surprised",   # Hiyori 无"兴奋"，取语义最近的"惊讶"
        "bored": "bored",         # 无聊
        "thinking": "think",      # 思考
    })
    # 情绪/表演名 → 动作组名（S18）：留空则不配动作，只演表情。
    # 肥牛模型动作组：Idle（待机循环，前端自动播）/ TapBody（13 个动作）。
    # 例如确认「第 5 个动作是挥手」后可写 "greet" = "TapBody"（配合表演名使用）。
    motion_map: dict[str, str] = field(default_factory=dict)
    # 自由搭配（S48）：表演名 → "表情名, 动作组#索引"（覆盖内置表演包的表情与动作）。
    #
    # 为什么需要本表：内置表演包的表情是**按情绪**推出来的 —— celebrate / surprise /
    # excited 的 emotion 都是 excited，于是三者共用同一个表情，想让"庆祝"用俏皮、
    # "惊讶"仍用惊讶，配置层原本表达不了（改 expression_map.excited 会一起改掉）。
    # 有了本表，每个表演的表情与动作都能独立指定，还能**自定表演名**（自动进表演库，
    # 可在调试台试演；也让 LLM 通过 avatar_perform 点播）。
    #
    # 语法（以第一个逗号分两段：前段=表情、后段=动作；缺哪段就留空那一段）：
    #   "expression7, TapBody#4"   表情 + 动作
    #   "expression6"              只改表情（无逗号 = 纯表情）
    #   ", TapBody#7"              只改动作（前面留逗号）
    #   单独写带索引的动作（"TapBody#4"）也按动作处理（索引里的 # 是判据）
    # 优先级：本表 > motion_map > 内置表演包。
    performance_map: dict[str, str] = field(default_factory=dict)
    # 语义动作槽位（S53）：槽位名 → "组#索引"。
    #
    # 为什么需要：内置表演包不再写死 TapBody#5 这类模型私有坐标，而是表达
    # "要一个庆祝动作"；槽位由当前模型的清单解析。文件名带语义的模型（Hotaru 的
    # mtn_bye01_C）能自动推断；Hiyori / 肥牛 的文件名无语义，就在这里显式指定。
    #
    # 可用槽位：idle / greet / celebrate / comfort / surprise / thinking / sing / angry / nod / look
    # 例：look = "TapBody#9"、greet = "TapBody#7"
    motion_slots: dict[str, str] = field(default_factory=dict)
    # 每模型表现档案（S49）：档案名 → 该模型的映射表覆盖。
    #
    # 为什么需要：上面三张表是**全局唯一**的。换模型后旧的 expression2 / TapBody#5
    # 全部失效却仍被沿用（表现"变了，但没人管"），而每换一次模型都得手改一遍配置 ——
    # 实测切到 Hiyori（0 个表情、TapBody 只有 1 个动作）时，表演会静默不出动作、
    # 还按旧模型的时长表空等 8.8 秒。档案就是"换个模型，整套表现跟着换"。
    #
    # 结构（TOML 子表；键是档案名，可任取）：
    #   [persona.profiles.hiyori]
    #   model = "/live2d/hiyori/Hiyori.model3.json"   # 命中哪个模型（必填）
    #   note  = "桃瀬ひより（Neuro v1 同款官方示例）"
    #   [persona.profiles.hiyori.expression_map]      # 命中后**整表替换**全局表
    #   happy = "happy"
    #   [persona.profiles.hiyori.performance_map]
    #   celebrate = "happy, Idle#4"
    # 没配档案的模型自动沿用全局表（不报错、不静默变空）。
    profiles: dict[str, dict] = field(default_factory=dict)


@dataclass
class MemoryConfig:
    backend: str = "sqlite-vec"
    embedder: str = "bge-m3"
    rrf_k: int = 60
    auto_inject_top_k: int = 3
    auto_inject_threshold: float = 0.6
    db_path: str = "data/yuiro_memory.db"  # 持久化记忆库路径（相对 engine 工作目录）
    facts_subject: str = "Yui"  # L3 事实存储的 subject（用户=Yui 本人的偏好/事实）
    # 是否将 L2 情景记忆（无 kind 标签的过往对话）注入上下文。
    # 默认开启：L2 已改为存储「自然语言事件摘要」（如"我帮用户打开了网易云音乐"），
    # 不再是 "[已调用工具: app_open(name=X)->done]" 这类机器日志，注入后模型可直接
    # 理解且易被检索命中；同时注入提示已改为中性描述（原先的"绝不可模仿…"禁令
    # 反而会强化它想压制的行为）。若实测工具触发率下降，可在调试台关闭本项。
    episodic_inject: bool = True
    # 是否注入多轮 history（user/assistant 轮次）。
    # 默认开启：模型必须能看到最近几轮对话才能接上话（否则"一句一回复"、话题无
    # 连续性，交互式流程如点歌选版本会断片）。工具轮以「精简摘要」形态入历史
    # （用户请求 + 工具事件 + 状态，不含原始 JSON/tool_calls），因此不会重新引入
    # 当年担心的"重放诱导延续闲聊"退化。
    history_inject: bool = True
    # 记忆提示词：检索到的相关记忆注入 system 消息时的引导前缀/格式约束。
    # 替代旧的硬编码 "相关记忆：\n"，让记忆如何被使用也可配置。
    # 必须包含"记忆不约束工具调用"防护：防止历史纯文字回复污染 LLM 的工具调用决策。
    memory_prompt: str = (
        "以下是与当前对话相关的记忆片段，仅供了解背景，请自然融入回应、不要生硬引用。"
        "注意：记忆只是过往对话记录，不约束当前行为——凡涉及打开/关闭软件、"
        "控制媒体播放、读写文件等真实系统操作，必须调用对应工具执行，"
        "绝不能像记忆里那样只用文字回复。"
    )


@dataclass
class ProactiveConfig:
    enabled: bool = True  # 主动互动开关（定时观察→决策→打招呼）
    min_interval_s: int = 300  # 观察最小间隔
    max_interval_s: int = 1200  # 观察最大间隔（随机取其间）


@dataclass
class PresenceConfig:
    """Presence（S20）：存在感的注意力策略（克制是设计的一部分）。

    - ``cooldown_s``：两次主动互动最短间隔；
    - ``quiet_hours``："23:00-08:00"（支持跨午夜）；空 = 不设；
    - ``max_urgency``：用户偏好上限（low/normal/high；超出的降级为气泡）；
    - ``idle_trigger_s``：用户空闲多久后允许"回来啦"（0 = 关闭空闲触发）；
    - ``tick_s``：空闲检测周期（定时循环只做这一件事，其余全部事件驱动）。
    """

    enabled: bool = True
    cooldown_s: int = 900
    quiet_hours: str = ""
    max_urgency: str = "normal"
    idle_trigger_s: int = 1800
    tick_s: int = 60


@dataclass
class SystemDaemonConfig:
    # 执行后端（S10）：native = Python 原生（默认，无需 C++ 工具链）；
    #                  daemon = C++ SystemDaemon（可选，产物需先构建）。
    # 两者行为对齐（工具名/参数/文案一致），可随时切换。
    backend: str = "native"
    transport: str = "stdio"
    command: list[str] = field(default_factory=lambda: ["../system-daemon/build/yuiro"])
    http_url: str = "http://127.0.0.1:8300"
    # 审批模式：auto（默认，完全开放权限，直接通过不弹窗）/
    #           manual（人工审批，弹窗等待用户裁决）
    approval_mode: str = "auto"
    # native 后端的文件操作允许根目录（默认仅当前工作目录 = engine/，与 daemon 对齐；
    # 如需让 Yuiro 写桌面/文档，把路径加进来，如 [".", "C:/Users/you/Desktop"]）。
    file_roots: list[str] = field(default_factory=lambda: ["."])


@dataclass
class TransactionConfig:
    """文件事务（S33）：让"改错了能撤回"成为默认能力（spec §3.15）。

    - ``enabled``：关闭后文件写操作不再生成事务（也就无法回滚）；
    - ``backup_root``：事务记录与备份的目录（相对引擎工作目录）；
    - ``keep``：只保留最近 N 个事务，更早的连同备份自动清理。
    """

    enabled: bool = True
    backup_root: str = ".yuiro/txn"
    keep: int = 20


@dataclass
class ObservabilityConfig:
    metrics_port: int = 9100
    log_level: str = "INFO"


@dataclass
class NeteaseConfig:
    """网易云音乐接入配置（官方 ncm-cli + mpv 发声）。

    凭证（appId / privateKey）由 ncm-cli 自身配置托管，不进本仓库、
    不进日志。此处只放非敏感项。

    实测要点（2026-08-31，ncm-cli 0.1.7 / 网易云客户端 3.1.38）：
    - search / playlist / recommend / song 等命令**登录后才动态加载**，
      未登录时 `ncm-cli commands` 里看不到，调用会报 unknown command。
    - 播放需要后台守护进程（NCM_DAEMON=1）常驻，否则 play 只把歌加进队列、
      mpv 不会被拉起；该进程由 yuiro/netease/client.py 的 ensure_daemon() 按需拉起。
    - Windows 客户端无法被外部唤起（`--player orpheus` 报"仅支持 macOS"，
      orpheus:// 投递亦无效），因此声音由 mpv 发出，
      与桌面客户端是两个独立播放源，同时开着会有两个声音。
    """
    enabled: bool = True
    bin: str = "ncm-cli"              # 支持绝对路径（不在 PATH 时）
    timeout_s: float = 20.0           # 默认超时
    timeout_search_s: float = 15.0    # 搜索/状态类（较快）
    timeout_write_s: float = 30.0     # 歌单同步/写操作（较慢）
    # 歌单列表缓存秒数（避免连续提问重复 spawn Node 进程）
    cache_ttl_s: float = 30.0


@dataclass
class ContextConfig:
    """ContextEngine（S06）：Hot Context 预算与工具结果截断。"""

    # Hot Context 总预算（估算 token：1 汉字≈1、4 字符≈1）；超出按优先级裁剪低优先段。
    budget_tokens: int = 6000
    # 工具结果喂给 LLM 前的最大字符数（超出截断 + 标注；前端仍收完整结果）。
    # S36：2000 → 3500 —— 歌单/搜索类结果稍长就被截成半截 JSON，模型解析不了会**反复重拉**
    # （实测 netease_recommend 连调 3 次、端到端 18 秒）。
    tool_result_max_chars: int = 3500


@dataclass
class AgentConfig:
    """Agent 回合预算（S47 / B3）：时间 / token / 轮数。

    为什么需要它：此前唯一的上限是"工具轮数 ≤ 3"，而单轮 LLM 可以跑到 30s、
    单轮上下文可以到 6000 tokens —— **最坏情况一轮能烧掉 90 秒和上万 token**，
    期间用户面对的是没有任何解释的等待。

    三个维度独立，对应三种不同的坏体验：
    - ``max_seconds``：**体感**（等多久算久）；
    - ``max_tokens``：**成本**（工具轮会不断把上下文撑大）；
    - ``max_rounds``：**绕圈**（模型反复调同一个工具时的刹车）。

    接近上限时引擎会**先给模型一条收尾提醒**（渐进收尾），而不是到点掐断 ——
    用户拿到的是完整句子，不是半截回复。
    """

    max_seconds: float = 90.0
    max_tokens: int = 60000
    max_rounds: int = 3


@dataclass
class CapabilityConfig:
    """Capability 层（S11）：工具权限档位。

    - read_only / privacy：只读（MEDIUM 及以上写操作直接拒绝，硬边界）；
    - normal（默认）：LOW 直通；MEDIUM/HIGH 依 [systemd].approval_mode
      （auto 放行 / manual 弹窗）；
    - trusted：LOW/MEDIUM 直通；HIGH 依审批模式。
    """

    profile: str = "normal"
    # S19：参数级资源域（CapabilityScope）。未声明的域 = 不限（默认宽松，不打断现有工作流）；
    # 系统关键目录（C:/Windows、/etc 等）是**硬红线**，即使写 ["*"] 也拒绝。
    # 例：scope = { filesystem = ["~/Documents/Yuiro/**"], process = ["记事本"] }
    scope: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class SearchConfig:
    """联网检索配置（S51）。设计：`docs/features/web-search-design.md`。

    要点：
    - ``enabled`` 是**全局总开关**，默认 **False** —— 隐私优先：查询词会发送给
      第三方搜索服务（data egress）。会话级即时开关在 UI（聊天坞发送键左侧），
      两者并存且按钮优先；
    - **本段刻意不含 ``api_key``**：密钥只走 OS keychain
      （``keychain.load_search_key()``），配置里绝不出现明文 key
      （`AGENTS.md` 铁律；对照 my-neuro 把 key 明文存 json 的反面案例）；
    - 默认值对齐 my-neuro 实测取值（克制优先：条数少、超时短）。
    """

    enabled: bool = False
    provider: str = "deepseek"
    top_k: int = 3  # 结果条数（上限 5）：条数直接乘进上下文与延迟
    timeout_s: float = 8.0
    endpoint: str = "https://api.deepseek.com/v1/tools/search"
    refine_results: bool = False  # 默认直接给主模型摘要，避免额外一次 LLM 往返

    def __post_init__(self):
        # 旧配置仅迁移标识；不迁移旧服务商凭证，亦不使用旧自定义 URL。
        if self.provider in {"tavily", "searxng", "serpapi"}:
            self.provider = "deepseek"
        if self.provider != "deepseek":
            raise ValueError("联网检索仅支持 DeepSeek")
        self.endpoint = "https://api.deepseek.com/v1/tools/search"


@dataclass
class DiaryConfig:
    """日记配置（S51）。设计：`docs/features/diary-feature-design.md`。

    - 日记**不是新的记忆层**，而是一个"受控的记忆上游"（§1.3）：用户显式确认
      才写入，而不是自动记录；
    - ``enabled`` 默认 **True**（与联网检索相反）：日记是用户主动进入的模式，
      进入即授权；而联网涉及数据外发，必须默认关；
    - ``quip_default_on`` 默认 **False**：吐槽模式默认关（§8.1.3 心流优先）。
    """

    enabled: bool = True
    db_path: str = "data/yuiro_diary.db"
    quip_default_on: bool = False  # 吐槽模式默认关（写日记时心流优先）
    review_enabled: bool = True  # 总评（确认录入后的收尾，§8.2）


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    asr: ASRConfig = field(default_factory=ASRConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    persona: PersonaConfig = field(default_factory=PersonaConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    systemd: SystemDaemonConfig = field(default_factory=SystemDaemonConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    proactive: ProactiveConfig = field(default_factory=ProactiveConfig)
    presence: PresenceConfig = field(default_factory=PresenceConfig)
    netease: NeteaseConfig = field(default_factory=NeteaseConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    capability: CapabilityConfig = field(default_factory=CapabilityConfig)
    search: SearchConfig = field(default_factory=SearchConfig)
    diary: DiaryConfig = field(default_factory=DiaryConfig)
    transaction: TransactionConfig = field(default_factory=TransactionConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    # S52：输出语言解耦（展示语言 / 朗读语言）
    language: LanguageConfig = field(default_factory=LanguageConfig)


def active_profile(persona: PersonaConfig) -> tuple[str, dict] | None:
    """按当前 ``model_path`` 挑出生效的表现档案，返回 ``(档案名, 档案字典)``；没有则 None。

    命中规则：档案里的 ``model`` 与 ``persona.model_path`` 相等（忽略首尾空白）。
    直接用模型路径当档案名也认（少写一个字段）。
    """
    path = (persona.model_path or "").strip()
    if not path:
        return None
    for name, prof in (persona.profiles or {}).items():
        if not isinstance(prof, dict):
            continue
        if str(prof.get("model", "")).strip() == path or str(name).strip() == path:
            return str(name), prof
    return None


def effective_persona_maps(persona: PersonaConfig) -> tuple[dict, dict, dict]:
    """算出生效的 ``(expression_map, motion_map, performance_map)``。

    规则：全局表打底；命中档案里**出现过的**表整表替换（不是逐键合并）。
    整表替换是有意的 —— 档案的语义是"这个模型该怎么演"，逐键合并会把旧模型的键
    残留下来，换模型后表现"半新半旧"反而更难排查。档案没写的表仍沿用全局。
    """
    expr = dict(persona.expression_map or {})
    motion = dict(persona.motion_map or {})
    perf = dict(persona.performance_map or {})
    hit = active_profile(persona)
    if hit is None:
        return expr, motion, perf
    _, prof = hit
    for key, target in (
        ("expression_map", expr),
        ("motion_map", motion),
        ("performance_map", perf),
    ):
        got = prof.get(key)
        if isinstance(got, dict):
            target.clear()
            target.update({str(k): str(v) for k, v in got.items()})
    return expr, motion, perf


def effective_motion_slots(persona: PersonaConfig) -> dict[str, str]:
    """算出生效的**语义动作槽位**（全局表 + 命中档案的覆盖）。

    与 :func:`effective_persona_maps` 同样是"档案整表替换"语义：档案写了
    ``motion_slots`` 就整表替换，没写才用全局表。
    """
    slots = dict(persona.motion_slots or {})
    hit = active_profile(persona)
    if hit is None:
        return slots
    got = hit[1].get("motion_slots")
    if isinstance(got, dict):
        slots.clear()
        slots.update({str(k): str(v) for k, v in got.items()})
    return slots


def load_config(path: Path | None = None, *, with_character: bool = True) -> AppConfig:
    """Load config.toml; fall back to defaults when absent."""
    if path is None:
        path = Path("config.toml")
    data: dict = {}
    if path.exists():
        with path.open("rb") as f:
            data = tomllib.load(f)
    cfg = AppConfig()
    cfg.server = ServerConfig.from_dict(data.get("server", {}))
    cfg.llm = LLMConfig(**data.get("llm", {}))
    cfg.vad = VADConfig(**data.get("vad", data.get("hard_of_hearing", {})))
    cfg.asr = ASRConfig(**data.get("asr", {}))
    # 兼容旧版 config.toml：voice 曾位于 [tts]，现已迁至 [persona]。
    # 若旧文件 [tts] 仍带 voice 而 [persona] 未配置，则自动迁移，避免启动报错。
    tts_data = dict(data.get("tts", {}))
    legacy_voice = tts_data.pop("voice", None)
    persona_data = dict(data.get("persona", {}))
    if legacy_voice and "voice" not in persona_data:
        persona_data["voice"] = legacy_voice
    cfg.tts = TTSConfig(**tts_data)
    cfg.persona = PersonaConfig(**persona_data)
    cfg.memory = MemoryConfig(**data.get("memory", {}))
    cfg.systemd = SystemDaemonConfig(**data.get("systemd", {}))
    cfg.observability = ObservabilityConfig(**data.get("observability", {}))
    cfg.proactive = ProactiveConfig(**data.get("proactive", {}))
    cfg.presence = PresenceConfig(**data.get("presence", {}))
    cfg.netease = NeteaseConfig(**data.get("netease", {}))
    cfg.context = ContextConfig(**data.get("context", {}))
    cfg.capability = CapabilityConfig(**data.get("capability", {}))
    cfg.search = SearchConfig(**data.get("search", {}))
    cfg.diary = DiaryConfig(**data.get("diary", {}))
    cfg.transaction = TransactionConfig(**data.get("transaction", {}))
    cfg.agent = AgentConfig(**data.get("agent", {}))
    cfg.language = LanguageConfig(**data.get("language", {}))
    cfg._config_path = path
    if with_character:
        from yuiro.characters import apply_active

        cfg = apply_active(cfg, path)
    return cfg


# ---------------------------------------------------------------------------
# 调试接口支持：字典化 / 字段合并 / 元数据 / TOML 序列化（供 debug_api.py 使用）
# ---------------------------------------------------------------------------

# (TOML 段名, AppConfig 属性名) 顺序即写回 config.toml 的顺序。
TOML_SECTIONS: list[tuple[str, str]] = [
    ("server", "server"),
    ("llm", "llm"),
    ("hard_of_hearing", "vad"),
    ("asr", "asr"),
    ("tts", "tts"),
    ("persona", "persona"),
    ("memory", "memory"),
    ("systemd", "systemd"),
    ("observability", "observability"),
    ("proactive", "proactive"),
    ("presence", "presence"),
    ("netease", "netease"),
    ("context", "context"),
    ("capability", "capability"),
    ("transaction", "transaction"),
    ("search", "search"),
    ("diary", "diary"),
    ("language", "language"),
]

# 字段元数据：驱动前端表单自动渲染。key 用 AppConfig 属性名。
# 每个字段: {label, type, options?, secret?, min?, max?, step?}
FIELD_META: dict[str, dict[str, dict]] = {
    "server": {
        "host": {"label": "监听地址", "type": "string"},
        "port": {"label": "端口", "type": "int", "min": 1, "max": 65535},
        "shared_secret": {"label": "共享密钥", "type": "string", "secret": True},
    },
    "llm": {
        "provider": {"label": "提供商", "type": "select",
                     "options": ["openai", "anthropic", "ollama", "deepseek", "qwen"]},
        "base_url": {"label": "Base URL", "type": "string",
                     "hint": "千问(百炼)填 https://dashscope.aliyuncs.com/compatible-mode/v1"},
        "model": {"label": "模型", "type": "string",
                  "hint": "千问推荐 qwen-plus / qwen-turbo / qwen-max"},
    },
    "vad": {
        "provider": {"label": "VAD 引擎", "type": "string"},
        "probability_threshold": {
            "label": "概率阈值", "type": "float", "min": 0, "max": 1, "step": 0.05,
        },
        "db_threshold": {"label": "音量阈值 (dB)", "type": "float", "min": 0, "max": 120, "step": 1},
        "smoothing_window": {"label": "平滑窗口", "type": "int", "min": 1, "max": 50},
        "required_hits": {"label": "起音命中数", "type": "int", "min": 1, "max": 50},
        "required_misses": {"label": "静音确认帧数", "type": "int", "min": 1, "max": 100},
        "barge_margin_db": {
            "label": "插话能量余量 (dB)", "type": "float", "min": 0, "max": 40, "step": 1,
            "hint": "越大越不容易被她自己的外放声 / 旁人噪声误打断；太大则你插话要说得更响",
        },
        "barge_in_enabled": {
            "label": "允许插话打断", "type": "bool",
            "hint": "默认关闭。当前识别与降噪不够可靠，自动打断容易被旁人说话 / 噪声误触发，"
                    "把她的话切碎。关闭时你说的话不打断她，但会被完整录下、等她说完后照常回应",
        },
    },
    "asr": {
        "provider": {"label": "ASR 引擎", "type": "string"},
        "model": {"label": "模型", "type": "string"},
        "device": {"label": "设备", "type": "select", "options": ["auto", "cpu", "cuda"]},
        "compute_type": {"label": "计算类型", "type": "select",
                         "options": ["int8", "float16", "float32"]},
        "language": {"label": "语言", "type": "string",
                     "hint": "中文填 zh；留空自动检测（短音频易误判）"},
        "beam_size": {"label": "Beam Size", "type": "int", "min": 1, "max": 10,
                      "hint": "束搜索宽度，越大越准越慢"},
        "vad_filter": {"label": "VAD 过滤", "type": "bool",
                       "hint": "先滤除非语音片段，减少幻觉"},
        "initial_prompt": {"label": "初始提示", "type": "string",
                           "hint": "如：以下是普通话的句子。"},
    },
    "tts": {
        "provider": {"label": "TTS 引擎", "type": "select",
                     "options": ["edge-tts", "cosyvoice", "gptsovits", "siliconflow", "fish"],
                     "hint": "edge-tts=云端免费（需联网）；cosyvoice=本地 CosyVoice2（需先启动 tts-server:5005）；siliconflow=云端克隆（零本地显存）"},
        "fish_model": {"label": "Fish 合成引擎", "type": "select",
                       "options": ["s2.1-pro", "s2.1-pro-free", "s2-pro", "drama-3"]},
        "fish_reference_id": {"label": "Fish 音色 ID", "type": "string",
                              "hint": "当前角色独立保存；公共音色 ID 填在这里，不是合成引擎名"},
        "fish_latency": {"label": "Fish 延迟模式", "type": "select",
                         "options": ["normal", "balanced", "low"]},
        "fish_speed": {"label": "Fish 语速", "type": "float", "min": 0.5, "max": 2.0},
        "fish_first_chunk_ms": {"label": "Fish 首块时长（毫秒）", "type": "int",
                                "min": 80, "max": 960,
                                "hint": "默认400；仅调整首块积累，后续仍480。可设480回退。"},
        "fish_transport": {"label": "Fish 传输方式", "type": "select", "options": ["http", "websocket"],
                           "hint": "HTTP连接池为默认；WebSocket为单轮持续文本流试验路径，新回合生效。失败不自动重试，可切回HTTP。"},
        "segment_streaming": {"label": "分段流式", "type": "bool"},
        "backend": {"label": "本地后端", "type": "select", "options": ["cosyvoice2", "cosyvoice3"],
                    "hint": "仅 cosyvoice 生效；cosyvoice3 需更大显存"},
        "tts_url": {"label": "本地服务地址", "type": "string",
                    "hint": "cosyvoice 用 5005，gptsovits 用 5000（GPT-SoVITS-Bundle）"},
        "reference_wav": {"label": "参考音频", "type": "string", "file": "audio",
                          "hint": "音色克隆来源 wav（零样本，只能选一个）；仅 cosyvoice 生效。"
                                  "点右侧「选择文件」挑，别手敲路径"},
        "reference_text": {"label": "参考音频转写", "type": "string",
                           "hint": "参考 wav 的准确转写文本，越准克隆保真度越高"},
        "instruct_zh": {"label": "中文语气指令", "type": "string"},
        "instruct_en": {"label": "英文语气指令", "type": "string"},
        "instruct_ja": {"label": "日文语气指令", "type": "string",
                        "hint": "朗读语言为日文时的语气指令；留空则沿用中文指令"},
        "default_language": {"label": "默认语种", "type": "select", "options": ["auto", "zh", "en"],
                             "hint": "auto=按字符自动判定"},
        "reply_tts_enabled": {
            "label": "语音回复 TTS", "type": "bool",
            "hint": "统一控制「她的回复是否出声」。开启：语音输入与文字输入的回复都合成播放；"
                    "关闭：两条链路都只回文字、不出声",
        },
        "tts_text_language": {"label": "GPT-SoVITS 语种", "type": "select",
                              "options": ["auto", "zh", "en"],
                              "hint": "仅 gptsovits 生效；音色在服务端固化，只传语种"},
        "siliconflow_key": {"label": "SiliconFlow API Key", "type": "string", "secret": True,
                            "hint": "provider=siliconflow 生效；云端零样本克隆，留空则从 keychain 读取（service: yuiro-siliconflow）"},
        "siliconflow_model": {"label": "克隆基础模型", "type": "string",
                              "hint": "仅 siliconflow 生效；默认 FunAudioLLM/CosyVoice2-0.5B"},
        "siliconflow_voice": {"label": "SiliconFlow 内置音色", "type": "string",
                              "hint": "参考音频为空时生效；填写完整 model:voice，例如 FunAudioLLM/CosyVoice2-0.5B:claire"},
        "siliconflow_reference_wav": {"label": "克隆参考音频", "type": "string",
                                      "file": "audio",
                                      "hint": "仅 siliconflow 生效；克隆音色来源 wav（只能选一个，"
                                              "朗读语言应与它的语种一致）。点右侧「选择文件」挑"},
        "siliconflow_reference_text": {"label": "克隆参考转写", "type": "string",
                                       "file": "text",
                                       "hint": "仅 siliconflow 生效；参考音频的准确转写（越准保真度越高），"
                                               "可直接填文本，也可选一个 .txt 文件；语种必须与参考音频一致"},
    },
    "persona": {
        "name": {"label": "内部名", "type": "string",
                 "hint": "提示词中自称的名字（英文）"},
        "display_name": {"label": "展示名", "type": "string",
                         "hint": "调试台/图鉴展示用中文名"},
        "system_prompt": {"label": "系统提示词", "type": "string",
                          "hint": "身份锚定 + 行为红线 + 工具调用铁律（不含性格）"},
        "persona_prompt": {"label": "人设提示词", "type": "string",
                           "hint": "性格、语气、说话风格、emoji 铁律等角色扮演内容"},
        "voice": {"label": "音色", "type": "string",
                  "hint": "edge-tts 音色，如 zh-CN-XiaoxiaoNeural"},
        "model_path": {"label": "Live2D 模型路径", "type": "string",
                       "hint": "相对 public 的 model3.json 路径"},
        "memory_subject": {"label": "记忆归属", "type": "string",
                           "hint": "这些记忆算在谁名下（默认就是你的名字）；换人使用时可区分。"
                                   "改动需重启引擎生效"},
    },
    "memory": {
        # S51：label/hint 一律**说人话** —— 此前是「后端 / RRF k / 注入阈值」这类
        # 内部术语，界面上没人看得懂（用户实测反馈："L2/L3 这种注释让人云里雾里"）。
        "backend": {"label": "存储方式", "type": "select", "options": ["sqlite-vec", "none"],
                    "hint": "sqlite-vec = 本地向量库（默认，推荐）；none = 关闭长期记忆"},
        "embedder": {"label": "语义模型", "type": "string",
                     "hint": "把话变成「向量」以便按意思检索的模型（默认本地 BGE-M3）。"
                             "填 md5 会退化成纯字面匹配（仅测试用）"},
        "rrf_k": {"label": "融合平滑参数", "type": "int", "min": 1, "max": 1000,
                  "hint": "融合「意思相近 / 字面命中 / 时间新近 / 重要度」四种检索信号的系数，"
                          "一般不用改"},
        "auto_inject_top_k": {"label": "每次带入几条", "type": "int", "min": 0, "max": 20,
                              "hint": "每轮对话前自动挑几条相关记忆放进上下文；越多越聪明，也越慢"},
        "auto_inject_threshold": {
            "label": "相关度门槛", "type": "float", "min": 0, "max": 1, "step": 0.05,
            "hint": "低于这个相关度的记忆不会被带入 —— 调高更严格，调低更宽松",
        },
        "memory_prompt": {"label": "注入时的引导语", "type": "string",
                          "hint": "把记忆放进上下文时附给她的说明（如「以下是相关记忆，仅供参考」）"},
    },
    "systemd": {
        "backend": {"label": "执行后端", "type": "select",
                    "options": ["native", "daemon"],
                    "hint": "native = Python 原生（默认，无需 C++ 工具链）；"
                            "daemon = C++ SystemDaemon（需先构建）"},
        "transport": {"label": "传输", "type": "select", "options": ["stdio", "http"]},
        "command": {"label": "启动命令", "type": "string_list"},
        "http_url": {"label": "HTTP 地址", "type": "string"},
        "approval_mode": {"label": "审批模式", "type": "select",
                          "options": ["auto", "manual"]},
        "file_roots": {"label": "文件允许目录", "type": "string_list",
                       "hint": "native 后端文件读写的允许根目录（默认 '.' = engine 目录）"},
    },
    "observability": {
        "metrics_port": {"label": "Metrics 端口", "type": "int", "min": 1, "max": 65535},
        "log_level": {"label": "日志级别", "type": "select",
                      "options": ["DEBUG", "INFO", "WARNING", "ERROR"]},
    },
    "proactive": {
        "enabled": {"label": "主动互动", "type": "bool",
                    "hint": "开启后桌宠会定时观察并偶尔主动打招呼（不打扰专注）"},
        "min_interval_s": {"label": "最短间隔（秒）", "type": "int", "min": 30, "max": 3600,
                           "hint": "两次观察之间的最短间隔"},
        "max_interval_s": {"label": "最长间隔（秒）", "type": "int", "min": 60, "max": 7200,
                           "hint": "两次观察之间的最长间隔（实际随机取其间）"},
    },
    "presence": {
        "enabled": {"label": "存在感", "type": "bool",
                    "hint": "开启后它会主动关心你（事件驱动 + 注意力策略，不打扰专注）"},
        "cooldown_s": {"label": "冷却（秒）", "type": "int", "min": 60, "max": 86400,
                       "hint": "两次主动互动的最短间隔"},
        "quiet_hours": {"label": "静默时段", "type": "string",
                        "hint": "如 23:00-08:00（支持跨午夜）；留空 = 不设"},
        "max_urgency": {"label": "打扰上限", "type": "select",
                        "options": ["low", "normal", "high"],
                        "hint": "超过该等级的主动表达会降级为气泡"},
        "idle_trigger_s": {"label": "空闲触发（秒）", "type": "int", "min": 0, "max": 86400,
                           "hint": "用户空闲多久后说「回来啦」（0 = 关闭）"},
        "tick_s": {"label": "检测周期（秒）", "type": "int", "min": 5, "max": 600,
                   "hint": "空闲检测的轮询周期（定时循环只做这一件事）"},
    },
    "context": {
        "budget_tokens": {"label": "上下文预算（tokens）", "type": "int",
                          "min": 1000, "max": 32000,
                          "hint": "Hot Context 总预算（估算）；超出时按优先级裁剪低优先段"},
        "tool_result_max_chars": {"label": "工具结果上限（字符）", "type": "int",
                                  "min": 200, "max": 20000,
                                  "hint": "超长工具结果截断后再喂 LLM（前端仍显示完整结果）"},
    },
    "search": {
        "enabled": {"label": "联网检索（总开关）", "type": "bool",
                    "hint": "默认关闭：查询词会发送给第三方搜索服务。开启后桌宠可查时效性信息"},
        "provider": {"label": "搜索后端", "type": "select",
                     "options": ["deepseek"],
                     "hint": "DeepSeek 独立 Search API；无需更换当前聊天模型"},
        "top_k": {"label": "结果条数", "type": "int", "min": 1, "max": 5,
                  "hint": "条数直接乘进上下文与延迟，建议 3"},
        "timeout_s": {"label": "超时（秒）", "type": "float", "min": 2, "max": 30, "step": 1},
        "refine_results": {"label": "额外提炼搜索结果", "type": "bool",
                           "hint": "默认关闭以减少一次模型请求；开启后多条结果先经聊天模型提炼"},
    },
    "diary": {
        "enabled": {"label": "日记功能", "type": "bool",
                    "hint": "开启后可进入日记模式；日记是「受控的记忆上游」——用户确认才写入记忆"},
        "db_path": {"label": "日记库路径", "type": "string",
                    "hint": "独立于记忆库，便于整库导出/删除"},
        "quip_default_on": {"label": "吐槽模式默认开启", "type": "bool",
                            "hint": "默认关闭：写日记时心流优先；可在日记界面随时切换"},
        "review_enabled": {"label": "总评", "type": "bool",
                           "hint": "确认录入后她给一段整体回应（可随时跳过）"},
    },
    "capability": {
        "profile": {"label": "权限档位", "type": "select",
                    "options": ["read_only", "privacy", "normal", "trusted"],
                    "hint": "read_only/privacy = 只读（拒绝写操作）；"
                            "normal = 低风险直通、中高风险依审批模式；trusted = 中风险免审批"},
    },
    "transaction": {
        "enabled": {"label": "文件事务", "type": "bool",
                    "hint": "开启后文件的改/移/删会自动备份，可随时「恢复刚才的操作」"},
        "backup_root": {"label": "备份目录", "type": "string",
                        "hint": "事务记录与备份的存放目录（相对引擎工作目录）"},
        "keep": {"label": "保留事务数", "type": "int", "min": 1, "max": 500,
                 "hint": "只保留最近 N 个事务，更早的连同备份自动清理"},
    },
    "language": {
        "display_language": {"label": "展示语言", "type": "select", "options": ["zh", "en", "ja"],
                             "hint": "气泡里的文字用哪种语言。她「内部思考」（含工具、"
                                     "对话历史、记忆）始终是中文，只有给你看的这段文字会变；"
                                     "默认中文"},
        "speak_language": {"label": "朗读语言", "type": "select",
                           "options": ["auto", "zh", "en", "ja"],
                           "hint": "嘴里念的语音用哪种语言（与展示语言互不影响）。"
                                   "应设成参考音频的语种（参考是日文就选 ja、英文选 en）："
                                   "与参考一致时克隆才有意义，不一致时容易夹生、输出长度也不稳。"
                                   "启动日志与「声音」页的自检都会告诉你参考是哪个语种。"
                                   "auto = 按朗读文本判定（默认，等于跟随展示语言）"},
        "translate_mode": {"label": "转换方式", "type": "select", "options": ["sentence", "full"],
                           "hint": "sentence = 逐句转换（首句出声更快，默认）；"
                                   "full = 整段一次转换（调用更少，但首句更晚）"},
        "translate_timeout_s": {"label": "转换超时（秒）", "type": "float", "min": 1.0, "max": 30.0,
                                "hint": "单次文本转换的超时上限；超时就直接用原文，不会没声音"},
    },
}


def config_to_dict(cfg: AppConfig) -> dict:
    """把 AppConfig 序列化为 {section: {field: value}} 供 API 返回。"""
    return {attr: asdict(getattr(cfg, attr)) for _, attr in TOML_SECTIONS}


def _coerce_value(obj, key: str, value):
    """按字段当前类型把传入值归一化，避免 int/float/bool 串型。"""
    cur = getattr(obj, key)
    if isinstance(cur, bool):
        if isinstance(value, str):
            return value.strip().lower() in ("1", "true", "yes", "on")
        return bool(value)
    if isinstance(cur, int):
        return int(value)
    if isinstance(cur, float):
        return float(value)
    if isinstance(cur, list):
        if isinstance(value, str):
            return [s.strip() for s in value.split() if s.strip()] or list(cur)
        return [str(x) for x in value]
    if isinstance(cur, dict):
        # 嵌套 dict（如 persona.emotion_hints）：原样透传，不做标量转换。
        return value if isinstance(value, dict) else cur
    return value


def config_apply(cfg: AppConfig, patch: dict) -> AppConfig:
    """把 {section: {field: value}} 合并进现有配置（就地修改并返回）。"""
    for section, values in patch.items():
        if not isinstance(values, dict) or not hasattr(cfg, section):
            continue
        sub = getattr(cfg, section)
        for key, value in values.items():
            if not hasattr(sub, key):
                continue
            setattr(sub, key, _coerce_value(sub, key, value))
    _apply_llm_preset(cfg, patch)
    if "search" in patch:
        cfg.search.__post_init__()
    return cfg


def _apply_llm_preset(cfg: AppConfig, patch: dict) -> None:
    """切换 LLM 提供商时自动填充默认 base_url/model（仅当字段为空或仍为默认值）。"""
    llm_patch = patch.get("llm", {})
    if not isinstance(llm_patch, dict) or "provider" not in llm_patch:
        return
    preset = LLM_PROVIDER_PRESETS.get(str(getattr(cfg.llm, "provider", "")).lower())
    if not preset:
        return
    default_base, default_model = LLMConfig().base_url, LLMConfig().model
    if "base_url" not in llm_patch and getattr(cfg.llm, "base_url", "") in ("", default_base):
        cfg.llm.base_url = preset[0]
    if "model" not in llm_patch and getattr(cfg.llm, "model", "") in ("", default_model):
        cfg.llm.model = preset[1]


def _toml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    s = str(value)
    # 含换行（或回车）的文本必须用 TOML 多行基本字符串 """...""",
    # 否则普通 ".." 会因 Illegal character '\n' 解析失败。
    # 多行串内部可自由含 " 与换行，仅需规避连续三个 "（极少出现在配置值中）。
    if "\n" in s or "\r" in s:
        body = s.replace('"""', '\\"\\"\\"')
        return f'"""{body}"""'
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_key(key: str) -> str:
    """TOML 键名：裸标识符照写，含其它字符（如模型路径 / 带点的名字）加引号。"""
    k = str(key)
    if re.fullmatch(r"[A-Za-z0-9_-]+", k):
        return k
    return '"' + k.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _emit_table(lines: list[str], header: str, mapping: dict) -> None:
    """递归写出一个 TOML 表：**先标量、后子表**（TOML 要求父表先于其子表出现）。"""
    lines.append("")
    lines.append(f"[{header}]")
    children: list[tuple[str, dict]] = []
    for key, value in mapping.items():
        if isinstance(value, dict):
            children.append((key, value))
            continue
        if isinstance(value, list):
            lines.append(f"{_toml_key(key)} = [{', '.join(_toml_scalar(x) for x in value)}]")
        else:
            lines.append(f"{_toml_key(key)} = {_toml_scalar(value)}")
    for key, value in children:
        _emit_table(lines, f"{header}.{_toml_key(key)}", value)


def dump_toml(cfg: AppConfig) -> str:
    """把 AppConfig 序列化为 TOML 文本（覆盖 config.example.toml 的全部段）。

    嵌套 dict 字段一律展开为 TOML 子表而非平铺标量，与 tomllib 解析结果对齐：

    - ``persona.emotion_hints`` → ``[persona.emotion_hints]``；
    - ``persona.profiles.hiyori.expression_map`` →
      ``[persona.profiles.hiyori]`` + ``[persona.profiles.hiyori.expression_map]``。

    递归展开（不设深度上限）—— 写死层数时踩过坑：少一层会把子表悄悄降级成
    "# 跳过" 注释，配置保存后档案整块消失且不报错。
    """
    lines: list[str] = ["# Yuiro Engine 配置（由调试界面 / debug API 写入）", ""]
    for toml_name, attr in TOML_SECTIONS:
        d = asdict(getattr(cfg, attr))
        lines.append(f"[{toml_name}]")
        children: list[tuple[str, dict]] = []
        for key, value in d.items():
            if isinstance(value, dict):
                children.append((key, value))
                continue
            if isinstance(value, list):
                val = "[" + ", ".join(_toml_scalar(x) for x in value) + "]"
            else:
                val = _toml_scalar(value)
            lines.append(f"{_toml_key(key)} = {val}")
        for key, value in children:
            _emit_table(lines, f"{toml_name}.{_toml_key(key)}", value)
        lines.append("")
    return "\n".join(lines)


def save_config(cfg: AppConfig, path: Path | None = None) -> Path:
    """把配置写回 config.toml，返回实际路径。"""
    if path is None:
        path = getattr(cfg, "_config_path", Path("config.toml"))
    role = getattr(cfg, "_character_id", "")
    if role:
        from yuiro.characters import ROLE_SECTIONS, CharacterStore

        CharacterStore(path).save(role, cfg)
        # config.toml 保留旧角色段用于回退；只把共用设置写回公共文件。
        shared = load_config(path, with_character=False)
        # 兼容旧公共凭证字段，不能随角色切换丢失；卡内始终不写此字段。
        shared.tts.siliconflow_key = cfg.tts.siliconflow_key
        for _, attr in TOML_SECTIONS:
            if attr not in ROLE_SECTIONS:
                setattr(shared, attr, getattr(cfg, attr))
        path.write_text(dump_toml(shared), encoding="utf-8")
        return path
    path.write_text(dump_toml(cfg), encoding="utf-8")
    return path
