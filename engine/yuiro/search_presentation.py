"""来源卡展示意图：保守的本地规则，不增加分类模型调用。"""
import re


def wants_source_card(text: str) -> bool:
    if re.search(r"(?:不用|不要|无需|别).{0,6}(?:来源|链接|卡片)|只(?:要|回答|告诉).{0,8}(?:答案|结果|结论)", text):
        return False
    return bool(re.search(
        r"资料|教程|文档|官网|链接|来源|出处|参考|证据|文章|网页|网站|对比|比较|选购"
        r"|推荐.{0,10}(?:工具|产品|软件|餐厅|酒店|景点)"
        r"|\b(?:sources?|references?|links?|documentation|tutorial|compare)\b", text, re.I))
