# S45 · 媒体链路彻底清查（诊断 + 修复）

**触发**：用户反馈媒体/点歌"非常非常不稳定"：点击候选条目报错、日志完整但播放器没反应、
点选后放的不是同一首、切歌丢失、对话积攒后工具灵敏度下降。

下面每一条都有**实测证据**，不是推测。诊断脚本：`engine/scripts/media_probe.py`。

---

## 一、根因 1：**静默串歌**（点的和放的不是同一首）★

实测 `media_probe.py LIFE`：

```
搜索「LIFE」：
  1. Life   / Tobu            originalId=28830410    playFlag=True
  2. LIFE   / Neuro-sama      originalId=2657613721  playFlag=False  ← 原唱，但没版权
  3. Life   / 西原健一郎       originalId=456045      playFlag=True
```

`_pick_best` 的逻辑：

```python
playable = [r for r in records if r.get("playFlag")]   # 先把没版权的过滤掉
...
def strong(r):
    if not song_tok or song_tok not in name_c: return False
    if not artist_tok: return True        # ★ 用户只说歌名时，歌手不限 → 任何同名都算命中
...
matched = [r for r in playable if strong(r)]
if matched:
    return matched[0], None               # ★ 静默取第一个
```

**两个缺陷叠加**：
1. **没版权的原唱被提前过滤**，用户根本不知道"原唱不可播"；
2. `artist_tok` 为空时**任何同名曲都算强匹配** → 于是**静默播了同名的另一首歌**。

**用户侧观感**：点《LIFE》→ 放成了 Life(Tobu)，**且毫无提示**。

### 修复

```python
if matched:
    if len(matched) > 1:
        # 多个同名（原唱/翻唱/不同歌手的同名曲）→ 让用户选，别替他决定
        return None, [_brief_song(r) for r in matched[:5]]
    return matched[0], None
```

**原则**：**同名多候选时不许替用户决定** —— 这与 S41 歌单匹配确立的"不确定就不猜"是同一条原则。

---

## 二、根因 2：**明文 `song_id` 无法播放**（点击候选 → error）★

实测：

```
song_detail(加密 id)          → ✓ 返回 playUrl
song_detail(明文 originalId)  → ✗ 接口 400「参数错误：28830410」
```

即**接口只认加密 ID**。而原实现想靠"把明文 ID 当关键词搜"来解析：

```python
records = await api.search_song(song_id, 20)      # ✗ 搜索匹配歌名/歌手，用 ID 搜必然为空
...
if not encrypted:
    if not keyword:
        return error("请给歌曲关键词、song_id 或 playlist_id 之一")   # ✗ 用户明明给了 song_id
```

**错误信息完全误导** —— 这是"点击后报 error"的直接原因（日志原文）。

### 修复（双层）

1. **前端主路径**：点选时**带上 ID**，不再只发歌名（见下节）；
2. **后端兜底**：只在有歌名时才搜索解析，**不再用 ID 当关键词**；错误信息改为如实说明
   "明文 ID 无法直接播放，请给 encrypted_id 或歌名"。

> **架构含义**：`song_id`（明文）与 `encrypted_id`（加密）在工具间靠"约定"传递，
> **没有统一的解析层** —— 这是媒体链路不稳定的结构性来源。
> 长期应引入 `resolve_song()` 统一入口，把"形态差异"关在一个地方。

---

## 三、根因 3：**确定性意图被交给 LLM 二次解释** ★★

原前端点选实现：

```javascript
const text = card.kind === 'playlist' ? `播放歌单「${it.name}」` : `播放《${it.name}》`
sendText(text)      // ✗ 只发名字，ID 丢了
```

于是链路变成：**用户点一个确定条目 → 转成自然语言 → LLM 重新理解 → 重新模糊搜索**。
**一个完全确定的事情，被交给模糊匹配** —— 串歌与报错都在这一层被放大。

### 修复：结构化直连

前端改发结构化指令，**绕过 LLM**：

```javascript
socket.send(JSON.stringify({
  type: 'media:play', kind: 'song' | 'playlist',
  name, song_id, encrypted_id, playlist_id
}))
```

引擎侧新增 `media:play` 分支 → **直接调播放链路**，不经 `AgentLoop`。

> **这正是前沿 Agent 框架的核心策略之一**：**确定性的边不要穿过模型**。
> LangGraph 那类框架强调"把确定性骨架留在代码里，模型只负责真正需要判断的部分" ——
> 用户点击一个具体条目没有任何需要判断的东西，就该走显式通道。

---

## 四、其余症状的定位

| 症状 | 定位 | 状态 |
|---|---|---|
| **日志完整但播放器没声音** ★ | **`pause` 残留**：`pause` 是 mpv 的**全局属性**，`loadfile` **不会**重置它。只要此前暂停过（用户说过"暂停"、或系统媒体键暂停过），之后每次 loadfile 完都停在 paused —— 而日志里 `played`、曲目信息一应俱全，极难归因 | ✅ 修：`play_urls` 先发 `set_property pause False`（顺带让"等待 playing"提前返回、提速） |
| **对话积攒后灵敏度降低** | `history_inject` 默认 **True**，且上限是 **40 条**（12+ 轮）；每轮的工具执行摘要会一起进 history，**累积后模型形成"我已经做过很多了"的印象**，反而压低对新请求的工具触发率 | ✅ 修：上限收紧到 **12 条**（约 3–4 轮）；提示词补一条"已成功的事不要再调一次工具去确认" |
| **重复调用同一工具** | 第 1 轮 `played:true` → 第 2 轮又调同一工具 → 被 `TurnPolicy` 去重挡回 `{"status":"done"}`（`progress_made` 仍为 False → 再下一轮即早停）。**机制本身是闭环的** —— 它不会死循环，浪费的是一轮 LLM 调用 | 🟡 已加提示词引导；机制无需再改 |
| **切歌丢失** | mpv 状态实测 `queueLength: 1` —— **单曲播放时播放列表只有 1 首**，`playlist-next` 必然无效。另：SMTC 转投（2026-09-16）已覆盖"mpv 空闲时按下一首"的场景 | 🟡 已知限制：单曲播放时"下一首"无效（重新点歌即可；歌单播放正常）。**不修**：补队列需额外 API 调用且用户未必想要同歌手的歌，收益/风险不划算 |
| **`volume: null`** | **不是 bug** —— `get_state` 有意精简掉了 volume，需单独回读 | 正常 |

---

## 五、修复清单（按优先级）

| # | 修复 | 位置 | 状态 |
|---|---|---|---|
| 1 | 点选带 ID + 结构化直连（绕开 LLM） | `App.vue` + `main.py` | 🟡 前端已完成，引擎侧进行中 |
| 2 | 同名多候选 → 给用户选，不静默播 | `netease_tool.py` `_pick_best` | 待做 |
| 3 | 明文 ID 解析只用歌名搜 + 错误信息如实 | `netease_tool.py` | ✅ 本轮 |
| 4 | 单曲播放后补队列（让"下一首"可用） | `netease_tool.py` | 待做 |
| 5 | 成功结果加"勿重复调用"引导 | `netease_tool.py` | 待做 |
| 6 | history 与 StateNotes 去重（收敛注入） | `AgentLoop._build_messages` | 待做 |
| 7 | 长期：统一 `resolve_song()` ID 解析层 | `netease/api.py` | 待做 |

---

## 六、可复用的诊断工具

`engine/scripts/media_probe.py`：打出**每一步的实际返回值**（搜索的 ID 形态 / 播放地址有无 /
mpv 状态），让"哪一层拿不到东西"一目了然。以后媒体问题先跑它。
