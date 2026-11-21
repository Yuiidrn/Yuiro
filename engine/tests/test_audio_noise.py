"""S51 语音噪音防护：``is_noise_transcript``（聊天语音与日记语音**共用同一判定**）。

为什么单独一个文件：这是**纯函数**判定，不依赖 VAD/ASR 模型、音频设备或网络 ——
放进 ``test_audio.py`` 会被那一堆"环境相关失败"淹没，也会让它的失败原因变模糊。

背景（实测教训）：ASR 对咳嗽、桌椅响、背景音乐、旁人插话，常会吐出
``"嗯。"`` / ``"(笑声)"`` / ``"[Music]"`` —— 这些**不是空文本**。若只在"空文本"处
拦截，它们会一路走进 LLM，用户侧看到的是"她突然回应了一声响动"。
"""
from __future__ import annotations

import pytest

from yuiro.audio import is_noise_transcript


@pytest.mark.parametrize(
    "text",
    [
        "", "   ",
        # 单字/重复填充词
        "嗯", "嗯嗯", "啊啊", "呃", "唔", "哦", "哈",
        # 填充词 + 标点
        "嗯。", "啊……", "哦！", "呃…",
        # 纯括号描述（ASR 给"非语音"的标注方式）
        "（咳嗽）", "(笑声)", "[Music]", "（喘气）", "[Applause]",
        # 纯标点
        "。。。", "...", "——", "，",
        # 英文填充词
        "hmm", "um", "Ah", "oh",
    ],
)
def test_noise_is_filtered(text: str) -> None:
    """★ 这些必须被判为噪音（否则她会莫名其妙地回应一声响动）。"""
    assert is_noise_transcript(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "停", "放歌", "下一首", "打开记事本", "帮我查一下",
        "嗯，我知道了", "嗯嗯，对", "今天天气怎么样", "算了不用了",
    ],
)
def test_real_commands_are_kept(text: str) -> None:
    """★ 保守取向：**像一句话的一律放行**。

    误杀用户的话（他说了她没反应）比放过一次噪音（她莫名回一句）严重得多 ——
    所以判定只拦"极短且明显无内容"的，短命令（"停""下一首"）与短句（"嗯，我知道了"）
    都必须活下来。
    """
    assert is_noise_transcript(text) is False
