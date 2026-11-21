"""扫描肥牛模型的动作文件，输出**参数级特征**用于推断动作语义。

Live2D 的 .model3.json 不给动作语义（只有 File 名），.motion3.json 也只是曲线数据。
但曲线**动了哪些参数、幅度多大**是可读的，配合 .cdi3.json 的中文参数名即可推断语义
（如 ParamAngleY 大幅变化 = 点头）。这比"人眼看逐帧动画"更准且可复现。

用法：python _motion_scan.py
"""
from __future__ import annotations

import json
import os

BASE = os.path.abspath(
    os.path.join(
        os.path.dirname(__file__), "..", "shell", "src", "renderer", "public", "live2d", "肥牛"
    )
)

# 参数 → 语义标签（按"动这个参数意味着什么"归类；阈值见 _tag）
TAGS: dict[str, str] = {
    "ParamAngleX": "转头",
    "ParamAngleY": "点头",
    "ParamAngleZ": "歪头",
    "ParamBodyAngleX": "身体前倾",
    "ParamBodyAngleY": "身体上下",
    "ParamBodyAngleZ": "身体侧倾",
    "ParamBreath": "呼吸",
    "ParamEyeLOpen": "眨眼",
    "ParamEyeROpen": "眨眼",
    "ParamEyeLSmile": "笑眼",
    "ParamEyeRSmile": "笑眼",
    "ParamEyeBallX": "眼神左右",
    "ParamEyeBallY": "眼神上下",
    "ParamBrowLY": "挑眉",
    "ParamBrowRY": "挑眉",
    "ParamBrowLAngle": "眉毛角度",
    "ParamBrowRAngle": "眉毛角度",
    "ParamMouthOpenY": "张嘴",
    "ParamMouthForm": "嘴型",
    "ParamCheek": "脸红",
    "ParamHairFront": "头发摆动",
    "ParamHairSide": "头发摆动",
    "ParamHairBack": "头发摆动",
    "ParamArmLA": "左臂",
    "ParamArmRA": "右臂",
    "ParamHandL": "左手",
    "ParamHandR": "右手",
    "ParamShoulder": "肩膀",
}

# 判定"有意义的幅度"阈值（各参数量纲不同，按经验分档）
SMALL = 1e-3


def load(rel: str) -> dict:
    with open(os.path.join(BASE, rel), encoding="utf-8-sig") as f:
        return json.load(f)


def curve_values(segs: list) -> list[float]:
    """提取 Segment 数组中的**值**（跳时间戳与贝塞尔控制点）。"""
    if not segs:
        return []
    kind = int(segs[0])
    vals: list[float] = []
    if kind == 1:  # Bezier：[1, t0, v0, (t, v, c1x, c1y, c2x, c2y)*]
        if len(segs) >= 3:
            vals.append(float(segs[2]))
        i = 3
        while i + 1 < len(segs):
            vals.append(float(segs[i + 1]))
            i += 6
    else:  # Linear(0) / Stepped(2) / InverseStepped(3)：[k, t0, v0, t1, v1, ...]
        vals = [float(x) for x in segs[1::2]]
    return vals


def analyze(rel: str, param_cn: dict[str, str]) -> dict:
    m = load(rel)
    duration = float(m.get("Meta", {}).get("Duration", 0.0))
    rows = []
    for curve in m.get("Curves", []):
        # motion3 的曲线结构：Target="Parameter"，真实参数 id 在 Id 字段
        pid = str(curve.get("Id") or curve.get("Target") or "")
        vals = curve_values(curve.get("Segments", []))
        if not vals:
            continue
        amp = max(vals) - min(vals)
        if amp < SMALL:
            continue
        rows.append((pid, amp, min(vals), max(vals)))
    rows.sort(key=lambda r: -r[1])
    # 指纹：用于检测"同一个动作被复制成多份"（如 singing 与 m01、micon 与 micoff）
    fingerprint = "|".join(f"{p}:{a:.2f}" for p, a, _, _ in rows)
    return {
        "file": os.path.basename(rel),
        "duration": duration,
        "params": rows,
        "fingerprint": fingerprint,
    }


def main() -> None:
    cdi = load("feiniu.cdi3.json")
    param_cn = {p["Id"]: str(p.get("Name", "")) for p in cdi.get("Parameters", [])}
    model = load("feiniu.model3.json")
    tap = [m["File"] for m in model["FileReferences"]["Motions"]["TapBody"]]

    print(f"TapBody 动作数：{len(tap)}\n")
    seen: dict[str, int] = {}
    for idx, rel in enumerate(tap):
        info = analyze(rel, param_cn)
        dup = seen.get(info["fingerprint"])
        seen.setdefault(info["fingerprint"], idx)
        dup_note = f"   ⚠ 与 #{dup} 完全相同（同一动作的副本）" if dup is not None else ""
        print(
            f"── #{idx}  {info['file']}  时长 {info['duration']:.2f}s  "
            f"参数 {len(info['params'])} 个{dup_note}"
        )
        tags: list[str] = []
        for pid, amp, lo, hi in info["params"][:8]:
            cn = param_cn.get(pid, "")
            tag = TAGS.get(pid, "")
            if tag and tag not in tags:
                tags.append(tag)
            print(f"     {pid:<18} {cn:<10} 幅度 {amp:6.2f}  [{lo:.2f} → {hi:.2f}]")
        top = info["params"][0] if info["params"] else ("", 0, 0, 0)
        hint = "＋".join(tags[:4]) if tags else "（仅微动）"
        print(f"     → 主导参数 {top[0]}（幅度 {top[1]:.2f}）｜涉及：{hint}\n")


if __name__ == "__main__":
    main()
