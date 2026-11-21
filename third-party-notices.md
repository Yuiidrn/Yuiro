# Yuiro 第三方组件与模型许可声明

> 本项目（MIT）仅覆盖原创代码。**Live2D 演示模型、Live2D Cubism 运行时、以及部分模型**有各自独立许可，使用时需遵守。本文件用于记录来源与许可，避免将来发布/商用踩雷。

---

## 1. Live2D 演示模型（自参考项目复制）

| 模型 | 来源 | 许可 |
|---|---|---|
| **Shizuku（白子）** | `Open-LLM-VTuber/live2d-models/shizuku` | **Live2D Inc. 免费素材许可协议**（样本） |
| **Mao Pro** | `Open-LLM-VTuber/live2d-models/mao_pro` | **Live2D Inc. 免费素材许可协议**（样本） |

来源项目的声明（参考 Open-LLM-VTuber README）：
> 这些资产根据 Live2D 免费素材许可协议和 Live2D Cubism 样本数据使用条款单独授权，不受 MIT 许可证约束。
> **商用（尤其中大型企业）可能需要额外许可**，请确保已获得 Live2D Inc. 适当授权，或使用不含这些模型的项目版本。

- Live2D 免费素材许可协议：https://www.live2d.jp/en/terms/live2d-free-material-license-agreement/
- Live2D 样本数据使用条款：https://www.live2d.com/eula/live2d-sample-model-terms_en.html

## 2. Live2D Cubism 运行时（live2dcubismcore）

- 专有、第三方提供；需单独放置 `live2dcubismcore.min.js`（见 deskpet `tauri-app/public/lib/` 的做法）。
- 商用同样需遵守 Live2D Inc. 条款。

## 3. 其它可下载模型（M2+ 用到时加入）

| 模型 | 用途 | 许可 |
|---|---|---|
| faster-whisper (Systran) | ASR | MIT (Whisper 权重 MIT) |
| silero-vad | VAD | MIT |
| BGE-M3 (BAAI) | 记忆向量 | MIT |
| Ollama / llama.cpp 模型 | 本地 LLM | 各模型不同（多为允许本地商用） |

> 维护建议：每新增一个模型/组件，在 "第 3 节" 补一行，保持可审计。
