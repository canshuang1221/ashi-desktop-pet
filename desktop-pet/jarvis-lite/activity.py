"""今日足迹：从宠物「看到」的屏幕里归纳出用户一天在干什么。

和 user_memory.md 的分工：
- user_memory.md 记的是**长期不变的事实**（喜好、习惯、在做的项目）
- 本模块记的是**当天的活动轨迹**（看视频、剪软件、工作、摸鱼、打游戏……）

关键在于**数据来源不是用户说了什么**：感知时让它在回复里带一个活动标签
（[活动:看视频]），这里把标签攒起来，攒够了就让模型归纳成几条要点。
所以用户一句话不说，足迹也照样积累。
"""
import json
import os
from datetime import datetime

import config

DIR = os.path.join(config.BASE_DIR, "activity")
THRESHOLD = 30      # 攒够这么多条新样本就归纳一次（感知间隔 30s ≈ 15 分钟一次）
MAX_SUMMARY = 500   # 归纳结果保留的字数上限


def _today_path():
    return os.path.join(DIR, datetime.now().strftime("%Y-%m-%d") + ".json")


def _blank():
    return {"samples": [], "summary": "", "done": 0}


def _load():
    p = _today_path()
    if not os.path.exists(p):
        return _blank()
    try:
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        for k, v in _blank().items():
            d.setdefault(k, v)
        return d
    except Exception:
        return _blank()


def _save(d):
    try:
        os.makedirs(DIR, exist_ok=True)
        with open(_today_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def add(tag):
    """记一条活动标签。"""
    tag = (tag or "").strip()[:12]
    if not tag:
        return
    d = _load()
    d["samples"].append({"ts": datetime.now().strftime("%H:%M"), "tag": tag})
    _save(d)


def count():
    return len(_load()["samples"])


def today_summary():
    return (_load().get("summary") or "").strip()


def need_summary():
    d = _load()
    return len(d["samples"]) - int(d.get("done") or 0) >= THRESHOLD


def summary_prompt():
    d = _load()
    done = int(d.get("done") or 0)
    fresh = d["samples"][done:]
    compact = "、".join(s["tag"] for s in fresh[-80:])
    buckets = {}
    for s in d["samples"]:
        buckets.setdefault(s["ts"][:2] + "点", []).append(s["tag"])
    timeline = "\n".join("%s：%s" % (k, "、".join(v[:16]))
                         for k, v in sorted(buckets.items()))
    return (
        "下面是今天从屏幕上记录下来的用户活动标签（不是他说的，是看到的），"
        "以及已有的一段总结。请把「今天用户都干了什么」更新成 3~5 条要点："
        "每条一行、以「- 」开头，按时间顺序，写清大概几点在做什么"
        "（看视频 / 剪软件 / 工作 / 摸鱼 / 打游戏…），口语化、具体一点。"
        "不要用「你」，不要评价、不要给建议。直接给要点，不要解释。\n\n"
        "【已有总结】\n%s\n\n【今天的标签时间线】\n%s\n\n【最近新增】\n%s"
        % (d.get("summary") or "(无)", timeline or "(无)", compact or "(无)")
    )


def save_summary(text, done_count=None):
    lines = [ln.strip() for ln in (text or "").splitlines()
             if ln.strip().startswith("-")]
    if not lines:
        return 0
    d = _load()
    d["summary"] = "\n".join(lines)[:MAX_SUMMARY]
    d["done"] = len(d["samples"]) if done_count is None else int(done_count)
    _save(d)
    return len(lines)


def block():
    """拼进 system 提示用的片段。"""
    s = today_summary()
    if not s:
        return ""
    return "\n\n【他今天在干什么（今天从屏幕看到的，自然用上，别生硬复述）】\n" + s
