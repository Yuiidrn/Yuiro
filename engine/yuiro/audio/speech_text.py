"""展示文本不变；朗读出口去除链接与末尾参考列表。"""
import re

URL = re.compile(
    r"(?:https?://|www\.)[^\s<>，。！？；）】]+"
    r"|(?<![\w@])(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
    r"(?:com|cn|org|net|io|ai|dev|edu|gov|co)\b(?:[/?#][^\s<>，。！？；）】]+)?", re.IGNORECASE)


def speech_body(text: str) -> str:
    text = re.split(r"(?im)^\s*(?:#{1,6}\s*)?(?:参考来源|参考链接|来源链接|Sources|References)\s*[:：]?\s*$", text or "")[0]
    text = re.sub(r"(?m)^\s*\[[^\]]+\]:\s*https?://.*$", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\(https?://[^\s]*?\)", lambda m: "" if URL.search(m[1]) else m[1], text)
    text = URL.sub("", text)
    text = re.sub(r"\[\d+(?:[,，、\-]\d+)*\]", "", text)
    text = re.sub(r"(?im)^\s*(?:[-*]|\d+[.)、])?\s*(?:来源|链接|出处)\s*[:：]\s*$", "", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def sentence_boundary(text: str, *, min_len: int = 1) -> int:
    """跳过过短句界及URL内标点；短前缀可与后续完整句合并交付。"""
    spans = [(m.start(), m.end()) for m in URL.finditer(text)]
    return next((i for i, ch in enumerate(text) if i + 1 >= min_len and ch in "。！？!?；;\n"
                 and not any(start <= i < end for start, end in spans)), -1)
