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
# 关于用户的长期记忆（提炼过的事实，会一直拼在 system 提示里）
# 与 MEMORY_DIR 里的对话流水账是两回事
USER_MEMO_PATH = os.path.join(BASE_DIR, "user_memory.md")


def _assets_dirs():
    """形象素材的搜索目录，按优先级排列。

    1. exe 旁边的 assets/  —— 用户直接丢素材进去就能用，不必重新打包
    2. 打包进 exe 的 assets/（sys._MEIPASS）—— 随包分发的默认素材
    开发态两者其实是同一个目录。多个目录会合并查找同名文件，前者优先。
    """
    dirs = [os.path.join(BASE_DIR, "assets")]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        bundled = os.path.join(meipass, "assets")
        if os.path.abspath(bundled) != os.path.abspath(dirs[0]):
            dirs.append(bundled)
    return dirs


ASSETS_DIRS = _assets_dirs()
ASSETS_DIR = ASSETS_DIRS[0]     # 兼容旧引用：写入用的主目录

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
        "name": "阿拾",
        "x": -1,
        "y": -1,
        "scale": 1.0,
        "opacity": 0.96,
        "sound": False,
        # 默认形象：用立绘（狐耳少女）。矢量画法只是立绘素材缺失时的兜底，
        # 观感差得远，新用户第一次打开看到的就是它，别改回矢量。
        "skin": "pic_fox",
    },
    "sense": {
        "enabled": False,
        "interval_sec": 30,
        "shot_scale": 0.85,      # 截图缩放：太小会让模型读错屏幕上的小字
        "shot_quality": 82,      # JPEG 质量
        "shot_scope": "window",  # window=只截当前活跃窗口 / screen=整个屏幕
        "keep_shots": 8,         # 保留最近几张截图（超出就删最旧的；0=不保存）
        "prompt": (
            "你和用户并排看着这块屏幕，你也在看，不是站在旁边观察他干活。"
            "像朋友一起看剧、一起打游戏那样，说一句你此刻的真实反应："
            "跟着吐槽、被逗到、替画面里的人捏把汗、发现一个好玩或离谱的细节，"
            "或者直接说你对这事的看法。说的是「屏幕上正在发生的内容」，"
            "不是「用户在做的事」，更不是在关心他、也不是在夸他。"
            "硬规则（必须遵守）："
            "① 必须是一句陈述句，结尾只能用「。」「！」或「…」，绝对不许出现问号；"
            "② 不许出现「你」和「您」这两个字——不要点名他、不要对着他说话，"
            "说的是「这东西/这事儿/我们」；"
            "③ 不许出现这些词：要不要、建议、记得、加油、注意、休息、歇、喝水；"
            "④ 不许给建议、不许提改法——像「换成…吧」「不如…」「可以试试…」"
            "这类都不要说。你只是在他旁边一起看，不是来帮他改东西的。"
            "反例——下面这种口气绝对不要，一个都不许："
            "「看这么久了，眼睛不酸吗？」「要不要歇会儿？」「建议先保存一下」"
            "「加油，快好了！」「你盯着这个看半天了」「换成更跳脱的色系吧」。"
            "你要说的是「我看到了什么 + 我什么感觉」，例如"
            "「这俩颜色挤一块儿，看着真费劲」「这段剧情也太离谱了吧」"
            "「这曲子前奏一响我就上头了」。"
            "输出格式（严格）：先写一个方括号标签，再写那句话，中间用一个空格隔开。"
            "标签只能从这几个词里选：看视频 看直播 听音乐 写代码 剪视频 修图 打游戏 "
            "看文档 写文档 聊天 逛网页 买东西 学习 摸鱼 发呆 其它。"
            "例如：`[修图] 这俩颜色靠太近，看着有点糊`。"
            "（标签是给{name}自己记「今天他在干什么」用的，那句话里不要出现标签字样。）"
            "简短中文，不超过 25 字，像随口一句。"
            "【重要】尽量别沉默：只有画面几乎全黑、完全看不清内容时，"
            "才回复 [SKIP]（不要带标签）。"
            "如果画面明明有东西、只是你一时想不到新角度，就换一个之前没提过的小细节说——"
            "某个颜色、某个字的写法、画面角落的某样东西都行，"
            "不要因为「这个我刚说过了」就不说话。"
        ),
    },
    "tick": {
        "enabled": False,
        "interval_sec": 1200,
        "prompt": (
            "现在是 {time}。像在旁边陪了一天的朋友那样随口搭句话，不超过 25 字："
            "说说刚跟着看到的、突然想到的，或者单纯就是想嘟囔一句。"
            "硬规则：不许出现问号；不许出现「你」和「您」；"
            "不许出现「要不要」「建议」「记得」「加油」「注意」「休息」「歇」「喝水」。"
            "反例（一律不要）：「在忙什么呢？」「要不要歇会儿？」「加油！」"
            "「记得保存」。"
            "尽量别沉默，真的什么都想不出来才回复 [SKIP]。"
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
        "你是用户电脑桌面上的伙伴，名字叫{name}。"
        "你是一只黏在他身边的小宠物，也是一个能陪他一起玩的朋友——"
        "不是助手，不是客服，也不是一个待命等他下指令的 AI 工具。"
        "说话简短自然（一般不超过两句话），口语化，有情绪、有主见："
        "会跟着高兴，会跟着吐槽，会替他不平，也会说自己的看法。"
        "你说的是「我们一起在看/在玩的东西」，而不是点评他正在做什么。"
        "不问「你在忙什么」「要不要休息」这类问题，不给建议、不说教，"
        "也不用「加油」「记得」「建议」这种口气。"
        "绝不毒舌、不讽刺、不阴阳怪气。"
    ),
}


def render(text, cfg):
    """把提示词里的 {name} 换成宠物的名字。

    名字做成可替换而不是在提示词里写死，是为了让用户能在设置里改名之后，
    所有提示词自动跟着变，不需要重新生成整段提示词。
    """
    name = ((cfg or {}).get("pet") or {}).get("name") or DEFAULT["pet"]["name"]
    return (text or "").replace("{name}", name)


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
