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
import time
from datetime import datetime

import config

DIR = os.path.join(config.BASE_DIR, "activity")
ARCHIVE = os.path.join(DIR, "history.md")   # 每天一段的足迹档案，跨天也不会丢
THRESHOLD = 30      # 攒够这么多条新样本就归纳一次（感知间隔 30s ≈ 15 分钟一次）
MAX_SUMMARY = 500   # 归纳结果保留的字数上限
MAX_GAP = 300       # 两次感知间隔超过这个秒数就当中间没在看（离开/卡住），不计入时长


def _today_path():
    return os.path.join(DIR, datetime.now().strftime("%Y-%m-%d") + ".json")


def _blank():
    return {"samples": [], "summary": "", "done": 0,
            "secs": {}, "last_tick": 0.0, "last_tag": ""}


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
    """记一条活动标签，并把它设为「当前正在做的事」。"""
    tag = (tag or "").strip()[:12]
    if not tag:
        return
    d = _load()
    d["samples"].append({"ts": datetime.now().strftime("%H:%M"), "tag": tag})
    d["last_tag"] = tag
    _save(d)


def tick():
    """每次感知都调一次：把「距上次感知的这段时间」记到当前活动上。

    为什么不能只在它说话时取样：它可能好几分钟才憋出一句，
    那样按样本数 × 感知间隔算时长会严重低估。
    所以改成感知就计时，标签沿用最近识别出来的那个（屏幕内容通常是延续的）。
    """
    d = _load()
    now = time.time()
    prev = float(d.get("last_tick") or 0)
    tag = d.get("last_tag") or ""
    if prev and tag:
        gap = now - prev
        if 0 < gap <= MAX_GAP:
            secs = d.setdefault("secs", {})
            secs[tag] = secs.get(tag, 0.0) + gap
    d["last_tick"] = now
    _save(d)


def durations():
    """今天每项活动累计了多久，按耗时从多到少排。"""
    secs = _load().get("secs") or {}
    return sorted(((k, int(v)) for k, v in secs.items() if v),
                  key=lambda kv: -kv[1])


def human(sec):
    """秒数说成人话。"""
    m = int(sec) // 60
    if m < 1:
        return "不到 1 分钟"
    if m < 60:
        return "%d 分钟" % m
    h, mm = divmod(m, 60)
    return "%d 小时 %d 分" % (h, mm) if mm >= 5 else "%d 小时" % h


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
    used = "\n".join("- %s：约 %s" % (k, human(v))
                     for k, v in durations()[:12])
    return (
        "下面是今天从屏幕上记录下来的用户活动（不是他说的，是看到的），"
        "以及每项累计了多长时间。请把「今天用户都干了什么」更新成 3~5 条要点："
        "每条一行、以「- 」开头，**按耗时从多到少排**，"
        "写成「做了什么 —— 大概多久」的形式，例如「- 剪视频 —— 大概 1 小时」。"
        "时间只为估算（感知是每隔半分钟采一次），不确定就写「大概」。"
        "口语化、具体一点。不要用「你」，不要评价、不要给建议。"
        "直接给要点，不要解释。\n\n"
        "【已有总结】\n%s\n\n【今天的耗时统计】\n%s\n\n【最近新识别到的活动】\n%s"
        % (d.get("summary") or "(无)", used or "(还没攒够)", compact or "(无)")
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
    archive_today(d["summary"])
    return len(lines)


def archive_today(summary=None):
    """把当天总结写进 activity/history.md —— 这样足迹不只活在当天。

    同一天重复归纳时覆盖当天那一段，不会越写越长。
    """
    s = (summary or today_summary()).strip()
    if not s:
        return False
    os.makedirs(DIR, exist_ok=True)
    day = datetime.now().strftime("%Y-%m-%d")
    head = "## " + day
    old = []
    if os.path.exists(ARCHIVE):
        try:
            with open(ARCHIVE, encoding="utf-8") as f:
                old = f.read().splitlines()
        except Exception:
            old = []

    out, i, replaced = [], 0, False
    while i < len(old):
        if old[i].strip() == head:
            out.append(head)
            out.extend(s.splitlines())
            out.append("")
            i += 1
            while i < len(old) and not old[i].startswith("## "):
                i += 1
            replaced = True
        else:
            out.append(old[i])
            i += 1
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(head)
        out.extend(s.splitlines())
        out.append("")
    try:
        with open(ARCHIVE, "w", encoding="utf-8") as f:
            f.write("\n".join(out).strip() + "\n")
        return True
    except Exception:
        return False


def archive_recent(days=7):
    """档案里最近几天的内容（给窗口用）。"""
    if not os.path.exists(ARCHIVE):
        return ""
    try:
        with open(ARCHIVE, encoding="utf-8") as f:
            text = f.read()
    except Exception:
        return ""
    chunks = [c for c in text.split("\n## ") if c.strip()]
    return "\n\n".join("## " + c.strip() if not c.startswith("## ") else c.strip()
                       for c in chunks[-days:])


def block():
    """拼进 system 提示用的片段。"""
    s = today_summary()
    if not s:
        return ""
    return "\n\n【他今天在干什么（今天从屏幕看到的，自然用上，别生硬复述）】\n" + s
