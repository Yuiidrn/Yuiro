"""当前 API 通道的可播性，不把曲目标志误解为用户会员或全站版权结论。"""
from __future__ import annotations


def song_availability(song: dict, *, detail: bool = False) -> dict:
    flag = song.get("playFlag")
    playable = flag if type(flag) is bool else None
    state = "unknown" if playable is None else ("api_available" if playable else "api_unavailable")
    if song.get("visible") is False or (detail and not song.get("playUrl")):
        state, playable = "api_unavailable", False
    if detail and song.get("playUrl") and song.get("visible") is not False and flag is not False:
        state, playable = "api_available", True
    if song.get("freeTrailFlag") is True:
        state = "api_preview"
    notes = {
        "unknown": "当前 API 可播状态待确认",
        "api_available": "当前 API 标记可播，完整取流仍需确认",
        "api_unavailable": "当前 API 通道不可播，不代表官方客户端无版权或账号无会员",
        "api_preview": "当前 API 仅标记为试听，未确认完整播放权益",
    }
    return {
        "playable": playable,
        "availability": state,
        "availability_note": notes[state],
        "playback_backend": "builtin",
        "rights_flags": {k: song[k] for k in (
            "playFlag", "visible", "vipFlag", "vipPlayFlag", "payPlayFlag", "songFee",
            "freeTrailFlag",
        ) if k in song},
    }


def unavailable_note(name: str) -> str:
    return (f"《{name or '该歌曲'}》当前 API 通道未取得完整播放地址；"
            "未播放、未替换版本。可在网易云官方客户端打开原版，"
            "不能据此判断你未开会员或歌曲没有版权。")
