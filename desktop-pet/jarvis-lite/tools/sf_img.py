# -*- coding: utf-8 -*-
"""硅基流动图片生成/编辑 —— 可复用的小工具。

用法（在本文件里改 PROMPT / MODEL 后直接跑）：
    python sf_img.py

接口：
  生图  POST /v1/images/generations   （Kolors / Qwen-Image / Z-Image ...）
  编辑  POST /v1/images/generations   （Qwen/Qwen-Image-Edit*，需传 image 字段）
"""
import os
import sys
import time
import requests

KEY = open(r"E:\WorkBuddy\Git\desktop-pet\.workbuddy\siliconflow.key",
           encoding="utf-8").read().strip()
BASE = "https://api.siliconflow.cn/v1"
OUT = r"E:\WorkBuddy\Git\desktop-pet\jarvis-lite\assets\_source"


def gen(model, prompt, negative="", image_size="960x1280", seed=None,
        image=None, steps=25, out_dir=OUT, tag=""):
    """生成/编辑一张图，返回落盘路径。"""
    os.makedirs(out_dir, exist_ok=True)
    body = {
        "model": model,
        "prompt": prompt,
        "image_size": image_size,
        "batch_size": 1,
        "num_inference_steps": steps,
        "guidance_scale": 7.5,
    }
    if negative:
        body["negative_prompt"] = negative
    if seed is not None:
        body["seed"] = seed
    if image:
        body["image"] = image          # 编辑模型：dataURL 或公网 url

    t0 = time.time()
    r = requests.post(BASE + "/images/generations",
                      headers={"Authorization": "Bearer " + KEY,
                               "Content-Type": "application/json"},
                      json=body, timeout=300)
    cost = time.time() - t0
    if r.status_code != 200:
        print("!! HTTP %s  (%.1fs)" % (r.status_code, cost))
        print(r.text[:500])
        return None
    j = r.json()
    url = j["images"][0]["url"]
    used_seed = j.get("seed")
    name = "%s_%s%s.png" % (model.split("/")[-1].replace("-", "").lower(),
                            time.strftime("%m%d-%H%M%S"), ("_" + tag) if tag else "")
    path = os.path.join(out_dir, name)
    d = requests.get(url, timeout=180)
    with open(path, "wb") as f:
        f.write(d.content)
    print("OK  %s" % path)
    print("    seed=%s  耗时 %.1fs  体积 %.0f KB" % (used_seed, cost, len(d.content) / 1024))
    return path


if __name__ == "__main__":
    NEG = ("realistic, 3d render, photograph, photo, complex background, "
           "scenery, landscape, text, watermark, signature, logo, "
           "multiple characters, lowres, blurry, jpeg artifacts, "
           "extra limbs, deformed, bad anatomy, human face")
    PROMPT = (
        "An original cute mascot character illustration. A round fluffy "
        "cream-white plush creature sitting down, chubby ball-shaped body, "
        "two tiny rounded ears on top, big glossy dark round eyes with large "
        "white highlights, a tiny pink nose, short stubby arms and legs, a "
        "short fluffy tail, wearing a soft mint-green knitted scarf. "
        "Kawaii chibi style, clean bold outlines, flat cel shading, soft "
        "pastel palette, sticker-like clean art, simple design, "
        "plain flat background, centered composition, full body visible."
    )
    gen("Kwai-Kolors/Kolors", PROMPT, NEG, image_size="960x1280",
        seed=20260910, steps=25, tag="probe")
