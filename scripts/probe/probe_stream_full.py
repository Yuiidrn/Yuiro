"""用引擎相同完整 messages（3段system+人设+记忆+user）做直接流式测试，隔离 system prompt 影响。"""
import asyncio
import sys

from yuiro.agent import OpenAIProvider
from yuiro.config import load_config
from yuiro.keychain import load_llm_key

SYSTEM_PROMPT = ("你是 Yuiro，一名由 AI 驱动的虚拟桌宠主播，由程序员 Yui 开发。"
    "你运行在用户的电脑上，可以调用系统工具帮用户操作这台机器。\n\n"
    "【工具调用铁律】当用户的意图涉及真实系统操作时，你必须直接调用对应的系统工具"
    "（app_open/app_focus/media_control/file_create/file_read/file_write），"
    "而不是只在文字里说\"帮你打开/关闭\"。意图判定规则（由强到弱都要触发）："
    "明确命令（\"打开网易云音乐\"）→ app_open；"
    "裸名词/点名（用户单独说出软件名，如\"记事本。\"）→ 等同于要求打开，调 app_open；"
    "已打开应用再被点名 → app_focus 聚焦；媒体意图（\"下一首\"\"声音大点\"）→ media_control；"
    "文件意图 → file_read/file_create/file_write。"
    "调用后用你的口吻简短转述工具结果。宁可多调一次工具，也不要只说不做。\n\n"
    "【示例】（务必照此行为模式执行）\n"
    "用户：\"打开网易云音乐\" → 调用 app_open(name=\"网易云音乐\")，再口头转述结果。\n"
    "用户：\"记事本。\" → 要求打开记事本 → 调用 app_open(name=\"记事本\")。\n"
    "用户：\"网易云音乐。\" → 调用 app_open（已打开则 app_focus）。\n"
    "用户：\"下一首\" → 调用 media_control(action=\"next\")。\n"
    "用户：\"你好呀\" → 纯闲聊，不调用工具，直接聊天回复。")

PERSONA = ("性格：表面乖巧天真，实则腹黑毒舌、思维跳脱，喜欢装乖、阴阳怪气、"
    "爱撒娇但说翻脸就翻脸。\n对主人 Yui 又爱又嫌、嘴上嫌弃实则依赖，自称本小姐，"
    "说话风格：口语化、爱吐槽、突然转折、想到什么直说，不要过度文艺、不要长篇大论。")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "app_open",
            "description": "打开/启动一个软件或应用。只要用户的话语中出现软件名或应用名——"
            "无论是明确命令还是单独说出名词，都必须调用本工具，"
            "name 填应用名/可执行名（如 '网易云音乐'、'notepad'）。",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    }
]


async def main():
    cfg = load_config()
    llm = OpenAIProvider(cfg.llm.base_url, cfg.llm.model, load_llm_key() or "")
    cases = sys.argv[1:] or ["记事本。", "网易云音乐。", "下一首"]
    for text in cases:
        print(f"\n[流式-完整] >>> {text!r}")
        tokens = 0
        tool_calls = []
        try:
            async for chunk in llm.stream_text(
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "system", "content": PERSONA},
                    {"role": "user", "content": text},
                ],
                tools=TOOLS,
            ):
                if chunk.kind == "token":
                    tokens += 1
                elif chunk.kind == "tool_call":
                    tool_calls.append((chunk.tool_name, chunk.tool_args))
        except Exception as e:
            print(f"  [流式-完整] 消费中异常: {type(e).__name__}")
        print(f"  [流式-完整] tokens={tokens}, tool_calls={tool_calls}")


if __name__ == "__main__":
    asyncio.run(main())
