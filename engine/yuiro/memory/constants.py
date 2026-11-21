"""memory 包的共享常量（S23：从 __init__.py 抽出）。

抽出的原因：``store.py`` 需要 DIM / VEC_K / EXPLICIT_PREFIX，
若从 ``yuiro.memory`` 导入会形成 ``__init__ → store → __init__`` 循环。
"""

# BGE-M3 稠密向量维度
DIM = 1024
# 每个信号进入 RRF 融合的候选条数
VEC_K = 32
# 默认 BGE-M3 模型路径
DEFAULT_MODEL = "BAAI/bge-m3"
# 显式记忆标记前缀（S07）：用户明确要求"记住"的内容以该前缀落 L2，
# 检索时作为独立通道常驻注入（零表结构改动的实现方式）。
EXPLICIT_PREFIX = "[用户要求记住] "
