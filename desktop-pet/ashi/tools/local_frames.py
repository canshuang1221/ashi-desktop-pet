# -*- coding: utf-8 -*-
"""本地零成本生成「闭眼 / 张嘴」帧（手动坐标版）。

为什么要手写坐标：这套立绘里耳朵内耳是深棕色，自动找暗块会把耳朵当眼睛。
素材就这一套，手写一次最稳妥；以后换素材时先跑 preview() 看框位再调。

坐标基于 960x1280 的原图。
"""
import os
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

SRC = r"E:\WorkBuddy\Git\desktop-pet\ashi\assets\_source\kolors_0910-174051_probe.png"
OUT_DIR = os.path.dirname(SRC)
TMP = r"C:\Users\46001\AppData\Local\Temp"

# 眼睛中心 + 半径（手写）
EYES = [(356, 577, 55, 58), (628, 573, 55, 58)]
NOSE = (480, 599)          # 鼻心
MOUTH = (480, 648)         # 嘴心


def _lerp_fill(a, box):
    """用 box 上下边缘外侧的颜色做垂直渐变，把 box 内填平（去眼睛）。"""
    x0, y0, x1, y1 = box
    H, W = a.shape[:2]
    x0, x1 = max(0, x0), min(W, x1)
    y0, y1 = max(0, y0), min(H, y1)
    w, h = x1 - x0, y1 - y0
    if w <= 0 or h <= 0:
        return a
    top_src = a[max(0, y0 - 4):y0, x0:x1]
    bot_src = a[y1:min(H, y1 + 4), x0:x1]
    top = top_src.mean(axis=0) if top_src.shape[0] else a[y0:y0 + 1, x0:x1][0]
    bot = bot_src.mean(axis=0) if bot_src.shape[0] else a[y1 - 1:y1, x0:x1][0]
    top = np.repeat(top[None, :, :], 1, axis=0)[0]
    bot = np.repeat(bot[None, :, :], 1, axis=0)[0]
    t = np.linspace(0, 1, h)[:, None, None]
    a[y0:y1, x0:x1] = top[None, :, :] * (1 - t) + bot[None, :, :] * t
    return a


def _soft_paste(base, patch, box, blur):
    """把 patch 以羽化椭圆蒙版贴到 base 的 box 位置。"""
    w, h = patch.size
    mask = Image.new("L", (w, h), 0)
    ImageDraw.Draw(mask).ellipse((0, 0, w - 1, h - 1), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(blur))
    base.paste(patch, (box[0], box[1]), mask)


def make_blink(src=SRC, squash=0.15, out_name="plush_blink_local.png"):
    im = Image.open(src).convert("RGB")
    out = im.copy()
    for (cx, cy, rx, ry) in EYES:
        pad = 14
        bx = (cx - rx - pad, cy - ry - pad, cx + rx + pad, cy + ry + pad)
        a = np.array(im).astype(float)
        a = _lerp_fill(a, bx)
        clean = Image.fromarray(a.astype(np.uint8))
        # 压扁后的眼睛（保留上高光）：贴到区域偏下，像上眼皮落下来
        region = clean.crop(bx)
        w, h = region.size
        bh = max(6, int(h * squash))
        squashed = region.resize((w, bh), Image.LANCZOS)
        patch = region.copy()
        patch.paste(squashed, (0, h - bh - max(3, h // 10)))
        _soft_paste(out, patch, bx, max(5, min(w, h) // 8))
    p = os.path.join(OUT_DIR, out_name)
    out.save(p)
    print("OK  %s" % p)
    return p


def make_talk(src=SRC, out_name="plush_talk_local.png"):
    im = Image.open(src).convert("RGBA")
    cx, cy = MOUTH
    w, h = 78, 66
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    # 口腔（深色），圆角矩形+椭圆拼出自然的开口
    d.ellipse((cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2),
              fill=(70, 30, 36, 255))
    # 舌头
    tw, th = int(w * 0.60), int(h * 0.52)
    d.ellipse((cx - tw // 2, cy + h // 2 - th - 4, cx + tw // 2, cy + h // 2 - 4),
              fill=(238, 140, 160, 255))
    layer = layer.filter(ImageFilter.GaussianBlur(1.5))
    out = Image.alpha_composite(im, layer).convert("RGB")
    p = os.path.join(OUT_DIR, out_name)
    out.save(p)
    print("OK  %s" % p)
    return p


def preview(src=SRC):
    im = Image.open(src).convert("RGB")
    d = ImageDraw.Draw(im)
    for (cx, cy, rx, ry) in EYES:
        d.ellipse((cx - rx, cy - ry, cx + rx, cy + ry), outline=(255, 0, 0), width=4)
    d.line((NOSE[0] - 30, NOSE[1], NOSE[0] + 30, NOSE[1]), fill=(0, 120, 255), width=3)
    d.line((MOUTH[0], MOUTH[1] - 20, MOUTH[0], MOUTH[1] + 20), fill=(0, 200, 0), width=3)
    p = os.path.join(TMP, "detect_preview.png")
    im.save(p)
    print("OK  %s" % p)


if __name__ == "__main__":
    preview()
    make_blink()
    make_talk()
