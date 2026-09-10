import json
import os
import sys

# 打包成 exe 后，配置和记忆必须落在 exe 所在目录，
# 否则会写进 PyInstaller 的临时解压目录，退出即丢失。
if getattr(sys, "frozen", False):
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
MEMORY_DIR = os.path.join(BASE_DIR, "memory")
NOTES_DIR = os.path.join(BASE_DIR, "notes")


def _assets_dir():
    """形象图片等只读资源的目录。

    打包成 onefile 后资源被解压到 sys._MEIPASS；开发时就在源码目录旁边的
    assets/。两边都找不到时退回 BASE_DIR，调用方自己判断文件是否存在。
    """
    base = getattr(sys, "_MEIPASS", None)
    if base:
        p = os.path.join(base, "assets")
        if os.path.isdir(p):
            return p
    return os.path.join(BASE_DIR, "assets")


ASSETS_DIR = _assets_dir()

DEFAULT = {
    "api": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
        "model": "deepseek-chat",
        "vision_model": "",
        "temperature": 0.8,
        "max_tokens": 1024,
    },
    "pet": {
        "name": "小贾",
        "x": -1,
        "y": -1,
        "scale": 1.0,
        "opacity": 0.96,
        "sound": False,
        "skin": "cat",
    },
    "sense": {
        "enabled": False,
        "interval_sec": 30,
        "shot_scale": 0.85,      # 截图缩放：太小会让模型读错屏幕上的小字
        "shot_quality": 82,      # JPEG 质量
        "shot_scope": "window",  # window=只截当前活跃窗口 / screen=整个屏幕
        "prompt": (
            "你在看用户电脑上正在使用的窗口。像一个懂行的朋友在旁边看着他干活："
            "先用半句点出你观察到他在做什么（要具体、有代入感），再自然地接一句关心、"
            "好奇或务实的小建议。简短中文，总共不超过 25 字。语气真诚友好，"
            "绝不毒舌、不讽刺、不阴阳怪气。描述方位必须以用户面对屏幕的视角为准："
            "画面左边就是用户的左手边。"
            "注意：屏幕画面边缘处的卡通形象（猫猫/史莱姆/机器人造型）就是你自己——小贾本尊，"
            "不是屏幕里的内容，永远不要对它提问、评论或表示好奇。"
            "如果画面看不清或没什么值得说的，只回复 [SKIP]。"
        ),
    },
    "tick": {
        "enabled": False,
        "interval_sec": 1200,
        "prompt": (
            "现在是 {time}。像朋友一样自然地跟用户说一句话，不超过 25 字："
            "可以关心他的进度、提醒休息、给他打气。语气真诚温暖，"
            "不毒舌、不阴阳怪气、别问「在忙什么」这种套话。没什么可说就只回复 [SKIP]。"
        ),
    },
    "idle": {
        "enabled": True,
        "threshold_sec": 180,
    },
    "ui": {
        "font_size": 12,
        "bubble_width": 260,
        "bubble_ms": 7000,
    },
    "persona": (
        "你是用户电脑桌面上的 AI 桌宠，名字叫小贾。你像一位懂技术、观察力强的朋友："
        "说话简短自然（一般不超过三句话），真诚友好，善于结合用户正在做的事情来交流，"
        "需要时给出务实的建议。绝不毒舌、不讽刺、不阴阳怪气。"
    ),
}


def _merge(base, patch):
    out = dict(base)
    for k, v in patch.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    cfg = json.loads(json.dumps(DEFAULT))
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                cfg = _merge(cfg, json.load(f))
        except Exception:
            pass
    for d in (MEMORY_DIR, NOTES_DIR):
        os.makedirs(d, exist_ok=True)
    return cfg


def save(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
