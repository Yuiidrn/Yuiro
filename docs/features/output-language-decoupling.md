# 输出语言解耦：展示语言 / 朗读语言（S52）

> 状态：已实现并验收（2026-10-10）。配置段 `[language]`，出口渲染器 `engine/yuiro/audio/render.py`。

## 1. 问题

**用户语言是单一中文，但 TTS 的参考音频 / 参考转写可能是别的语言**（用户原话：
"参考语音和文本在跨语言上的效果差异化较大"）。本仓库当前的实际配置正是如此：

| 参考 | 语种 | 用途 |
|---|---|---|
| `assets/voices/Model/Hotaru Shiomi/推荐参考/温柔亲近/参考音频.wav` + 同名 `.txt` | **日文**（汐見蛍） | **当前配置**（`[tts].siliconflow_reference_wav/_text`） |
| `assets/voices/Model/Neuro/参考音频.wav` + `参考文本.txt` | **英文**（`You want me to get rid of that chat member...`） | 备用音色（Neuro） |
| `assets/voices/neuro_prompt.wav` + 中文转写 | 中文 | `provider = "cosyvoice"` 路径 |

**参考语种不必靠读配置判断**：启动日志会判定并给出建议，例如
`参考音频转写语种判定=ja（'いいですね。わたしはきょうだいも幼馴染もいないので、…'）｜朗读语言建议设为 ja`。

克隆质量主要取决于**朗读语言是否与参考语种一致**：一致时最自然；用英文参考念中文
会拖长、带夹生腔（实测见 §4）。因此需要把「朗读语言」独立出来可设——而气泡文字
仍应保持用户能读的中文。

在此之前，**气泡文字与朗读语音共用同一段 LLM 原文**，想让她"按参考的语种念"
就必须让整条链路（含工具调用、history、记忆）一起变语言：

- 文字通道：`chat:assistant`（文本聊天）/ `llm:text`（语音）→ 前端 `showSpeech` 气泡；
- 语音通道：`VoicePipeline._speak → split_sentences → TTSTaskManager.enqueue → provider.synthesize_segment`。

这是不可接受的（记忆跨会话检索、历史一致性、人设全都会漂）。

**推荐配置**：`display_language = "zh"`（你看中文）+ `speak_language = "<参考语种>"`
（嘴里用参考的语言念）。两者互不影响，正是本功能要解决的组合。

## 2. 设计：内部恒中文，只在出口分叉

```
用户输入 ──▶ AgentLoop 内部（LLM 往返 / 工具 / history / L1-L3 记忆）——**恒为中文**
                                   │
               ┌───────────────────┴────────────────────┐
               ▼                                        ▼
     render_display(text)                      render_speak(text)
   （→ 展示语言，气泡文字）                   （→ 朗读语言，送进 TTS）
```

- 新增 `OutputRenderer`（`engine/yuiro/audio/render.py`）：唯一做文本转换的组件，
  复用既有 `OpenAIProvider`（无工具、`temperature=0`、独立实例），不引入翻译库/模型。
- 插入点只有出口：
  - 朗读：`VoicePipeline._speak_impl` 的投喂侧（逐句）/ `_speak`（整段模式）；
  - 展示：`main.py` 的 `chat:assistant` × 2（主回复、点歌直连提示）与
    `llm:text`（语音路径）；Presence 主动说话的气泡经 `_presence_broadcast`。
- AgentLoop / MemorySystem **零改动**（`git diff` 为空）→ 记忆与历史仍是中文原文。

### 2.1 三条硬约束

1. **默认零回归**：`display=zh` + `speak=auto` 时 `OutputRenderer.enabled is False`，
   两个出口全部透传，**不产生任何 LLM 调用**（线上行为与引入前逐字节一致）。
2. **已是对应语言就透传**：先做语种判定（假名→ja、谚文→不支持、纯标点→unknown），
   原文已是目标语言时不发起无谓翻译（"嗯。""OK"这类短句不会被翻译）。
3. **绝不静默**：转换超时（默认 6s）/异常/空结果一律**回退原文**并打告警日志——
   宁可念错语言，也不能没声音。

## 3. 配置（调试台「大脑」→「语言」，紧邻「大模型」）

| 字段 | 取值 | 默认 | 说明 |
|---|---|---|---|
| `display_language` | zh / en / ja | `zh` | 气泡文字语言（用户只读中文时保持 zh） |
| `speak_language` | auto / zh / en / ja | `auto` | 朗读语言。**建议设成参考音频的语种**（英文参考→en）；auto = 按朗读文本判定（默认） |
| `translate_mode` | sentence / full | `sentence` | 逐句（保首句先出声）/ 整段一次 |
| `translate_timeout_s` | 1~30 | `6.0` | 单次转换超时，超时回退原文 |
| `[tts].instruct_ja` | 文本 | 内置日文语气指令 | 朗读语言为 ja 时使用（留空退回中文指令） |

参考语种不必靠肉眼判断：启动日志会打印
`参考音频转写语种判定=en（'You want me to get rid of...'）｜朗读语言建议设为 en`，
调试台「声音」页的语音合成自检卡也会回显`参考音频语种`。

- **没有**"内部语言"开关：刻意不暴露，避免把 Agent 内部一起翻掉。
- 各 TTS 后端按**装配期**注入语种：CosyVoice `language=`、GPT-SoVITS `text_language=`、
  edge-tts 按语种换音色；SiliconFlow 无 language 参数（模型自动判定），保持原样。
- 配置热重载：调试台保存即生效（`debug_api` 重建 provider + `VoicePipeline.set_renderer`），
  日志可见 `语言设置已热重载：{...}`。

## 4. 实测（真实 LLM：qwen3.7-max，2026-10-10）

原文（带语气 + 专有名词，正是最容易翻车的那类）：

> 刚才没播成，还在等你确认版本呢，你到底要听哪个Live版呀？

| 场景 | 结果 | 耗时 |
|---|---|---|
| 默认 zh/auto | 透传、0 调用 | **0 ms** |
| `speak=en` | `It didn't play earlier—I'm still waiting for you to confirm the version. Which live version do you actually want to listen to?` | 2288 ms |
| `speak=ja` | `さっき再生できなくて、まだバージョンの確認を待ってるんだけど、結局どのLive版を聴きたいの？` | 1268 ms |
| 同句第二次（缓存命中） | 同上 | **0 ms** |
| `display=en` / `speak=auto` | 气泡英文、朗读保持中文（两路真正独立） | 1606 ms |

试听接口（`POST /api/providers/tts/test` 带 `{"lang": "zh|en|ja"}`）三语种均合成成功，
调试台语音合成卡片上已加语种下拉与"实际语种 / 试听文本 / 参考音频语种"回显。

**关于"参考语种决定听感"的实测说明**：三语种试听的音频时长（`volumes_count × slice_ms`，
即解码后的真实播放时长）分别是 zh≈9~17 s、en≈6.7 s、ja≈26 s，且**同一请求两次结果不一致**
（如 zh 一次 653 KB / 17.1 s，另一次 822 KB / 9.3 s）——说明该云端克隆对跨语言文本的
输出长度本身就不稳定，**不能只看时长判定质量，最终仍需人耳试听**。

可确定的结论只有一条：**参考语种与朗读语种不一致时没有任何好处**，所以推荐
`display=zh` + `speak=<参考语种>`（当前参考是日文 → `speak=ja`），
这也是本功能存在的意义。建议先在调试台用「语音合成」自检卡逐个语种试听再定。

## 5. 已知限制（明确不在本轮范围）

1. **同一时刻只有一套参考**：引擎一次只加载一份参考音频/转写（当前是日文 Hotaru Shiomi），
   因此只能让**一个**朗读语种与它匹配；要"中文用中文参考、日文用日文参考"需要
   "每语种一套档案 + 按朗读语言切换"（用户明确选择暂不做）。
   与本限制配套的当前用法：**朗读语言跟着参考走**（参考日文 → `speak=ja`）。
2. **朗读语言与参考不一致没有收益**：克隆在语种一致时才有意义；不一致时要么夹生、
   要么输出长度失稳（见 §4 实测）。跨语言的真实听感请用调试台试听确认。
3. **非流式整段路径的渲染粒度**：`stream_llm=false` 时，渲染发生在"分句（含 S37 首段细分）
   之后"，首句可能被拆成两段分别翻译（译文质量略降）。默认的流式路径不受影响
   （句子由 LLM 流式分句器给出，按整句渲染）。
4. **混排文本**：中文回复里夹英文单词/人名/URL 时按提示词要求保留原文，仍可能半英半中。

## 6. 观测与排障

- 日志：`[yuiro][language] speak 渲染 zh→en（2288ms）：'原文' → '译文'`（截断 60 字）；
  失败为 `⚠ ... 转换超时/失败，回退原文`。
- trace 新增阶段 `lang_render`（本轮**首个句子**渲染完成的时刻，位于 `tts_start` 与
  `tts_first_audio` 之间）——两者之差直接回答"首句慢是因为翻译还是因为合成"。
- 事件载荷（S52 扩展，向后兼容）：
  - `llm:text {text(展示文本), source_text(内部中文原文), duration_ms}`；
  - `tts:start/tts:synthesize {text, display_text?}`；逐句模式下 `text` 仍是内部原文
    （译文在投喂侧逐段产生），整段模式下 `text` 是整段译文。
- 渲染器统计：`stats = {calls, cache_hits, failures, skipped}`（`describe()` 输出，
  装配与热重载时打日志）。

## 7. 测试

- `engine/tests/test_output_renderer.py`（新增 14 例）：语种判定（含假名→ja）、默认零调用、
  已是对应语言透传、转换/缓存/保序、超时与异常回退、无 LLM 透传、引号清洗、热重载。
- `engine/tests/test_tts_streaming.py`（新增 5 例）：无渲染器时原文直通（回归护栏）、
  两路出口分别渲染、流式路径逐句渲染、整段模式只渲染一次、渲染期间被打断不泄漏译文。
- 全量回归：**766 passed / 0 failed**（顺手修掉了 `test_agent_memory` 中长期红的用例：
  它原先依赖 C 盘 HF 缓存的 `BAAI/bge-m3`，且断言"纯闲聊会写 L2 记忆"与现规定冲突；
  现改为使用项目内权重并守真实契约）。

## 8. 扩展点

- **语种档案**：`[tts.voices.<lang>] = {reference_wav, reference_text, instruct}`，
  provider 按朗读语言选档案（SiliconFlow 需按档案缓存 base64 参考）。
- **零额外往返**：同一轮让 LLM 直出"显示版 + 朗读版"（需改 AgentLoop 输出协议，
  会牵连工具循环/记忆/history，本轮明确不做）。
- **输入侧解耦**：ASR 语种与回复语言解耦（用户本轮只要求输出侧）。
