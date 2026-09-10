"""把生成的立绘抠成透明背景，并统一成多帧对齐的 PNG。

要点：
- 背景色常与角色浅色部分接近，不能全局按颜色抠，否则会把角色抠出洞；
  所以从四角「泛洪填充」，只删与画面边缘连通的背景。
- 画面底部常有模型顺手画的散落小颗粒，泛洪删不掉；
  用「只保留最大连通块」把它们清掉。
- 各帧包围盒有差异，若各自缩放会导致换帧时人物跳动，
  因此统一按同一比例缩放，并把底边对齐同一基线、水平居中。
"""
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = r"E:\WorkBuddy\Git\desktop-pet\jarvis-lite"
SRC = os.path.join(ROOT, "assets", "_source")
OUT = os.path.join(ROOT, "assets")
CANVAS = (600, 720)
TARGET_H = 660
BASELINE = 700
EDGE_TOL = 72
EDGE_KEEP = 0.32

JOBS = {
    "pic_plush": {
        "idle": "kolors_0910-174051_probe.png",
        "blink": "plush_blink_raw.png",
        "talk": "plush_talk_raw.png",
    },
}



def close_small_holes(alpha, k=9):
    """闭运算填掉零星的小透明点。

    收紧色距阈值后仍可能有几像素的毛影被误删，在深色桌面上会变成小黑点。
    开闭运算能把小于核尺寸的洞填上，同时不怎么改变轮廓。
    """
    m = Image.fromarray(((alpha > 128).astype(np.uint8) * 255))
    m = m.filter(ImageFilter.MaxFilter(k)).filter(ImageFilter.MinFilter(k))
    ok = np.array(m) > 127
    out = alpha.copy()
    out[ok & (alpha <= 128)] = 255
    return out


def fill_small_holes(alpha, ds=4, max_area=9000):
    """把被误删的「小洞」补回来。

    按颜色距离删背景时，角色的粉色鼻头、腮红会被一起删掉，
    在脸上留下透明的洞。这里找出「四周被前景包住、且面积不大」的
    透明区域，把 alpha 恢复。面积大的（比如两耳之间那块真空隙）不动。
    """
    from collections import deque
    H, W = alpha.shape
    hole = alpha <= 128
    h, w = H // ds, W // ds
    hb = hole[:h * ds, :w * ds].reshape(h, ds, w, ds).all(axis=(1, 3))
    if not hb.any():
        return alpha
    lab = np.zeros((h, w), np.int32)
    cur = 0
    for y0 in range(h):
        row = hb[y0]
        for x0 in range(w):
            if row[x0] and lab[y0, x0] == 0:
                cur += 1
                lab[y0, x0] = cur
                dq = deque([(y0, x0)])
                while dq:
                    y, x = dq.popleft()
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ny, nx = y + dy, x + dx
                            if (0 <= ny < h and 0 <= nx < w
                                    and hb[ny, nx] and lab[ny, nx] == 0):
                                lab[ny, nx] = cur
                                dq.append((ny, nx))
    edge_labels = set(lab[0, :]) | set(lab[-1, :])
    edge_labels |= set(lab[:, 0]) | set(lab[:, -1])
    edge_labels.discard(0)
    sizes = np.bincount(lab.ravel())
    fill_ids = np.zeros(cur + 1, bool)
    for i in range(1, cur + 1):
        if i not in edge_labels and sizes[i] * ds * ds < max_area:
            fill_ids[i] = True
    if not fill_ids.any():
        return alpha
    fill = np.zeros((H, W), bool)
    fill[:h * ds, :w * ds] = np.kron(fill_ids[lab], np.ones((ds, ds), bool))
    out = alpha.copy()
    out[fill] = 255
    return out


def keep_main_blob(alpha, ds=4):
    """只保留与画面中心连通的那一块前景。

    在全分辨率上跑 BFS 太慢，先降采样 ds 倍（块内只要有前景就算），
    在 1/ds² 的规模上做连通判断，再升采样回来。
    PIL 的 ImageDraw.floodfill 在 L 模式下实测不生效，所以自己写。
    """
    from collections import deque
    H, W = alpha.shape
    fg = alpha > 128
    h, w = H // ds, W // ds
    blk = fg[:h * ds, :w * ds].reshape(h, ds, w, ds).any(axis=(1, 3))
    if not blk.any():
        return fg
    ys, xs = np.nonzero(blk)
    cy, cx = h // 2, w // 2
    i = int(np.argmin((ys - cy) ** 2 + (xs - cx) ** 2))
    cy, cx = int(ys[i]), int(xs[i])

    lab = np.zeros((h, w), bool)
    lab[cy, cx] = True
    dq = deque([(cy, cx)])
    while dq:
        y, x = dq.popleft()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ny, nx = y + dy, x + dx
                if 0 <= ny < h and 0 <= nx < w and blk[ny, nx] and not lab[ny, nx]:
                    lab[ny, nx] = True
                    dq.append((ny, nx))

    keep = np.zeros((H, W), bool)
    keep[:h * ds, :w * ds] = np.kron(lab, np.ones((ds, ds), bool))
    return keep


def key_out(path, dist_tol=16, blur=0.9):
    """抠背景。

    做法：直接按「与背景色的距离」全局删。
    为什么不用块级连通：这套图里角色的耳朵之间夹着一小块背景，
    粗粒度分块会把「耳朵+夹缝背景」当成同一块前景整体保留下来，
    深色桌面上就能看见一块白斑。

    阈值 28 是权衡出来的：背景自身的色距基本在 15 以内；
    而角色的粉色鼻头约 27、腮红约 42、白毛 66 以上，都能保住。

    再补两步：
      - 用 floodfill 只保留与画面中心连通的那一块前景，
        清掉模型画在画面边缘的孤立杂物；
      - 对 alpha 做极轻微的高斯模糊，把硬边磨掉一点，避免锯齿。
    """
    im = Image.open(path).convert("RGBA")
    a = np.array(im)
    corners = np.concatenate([
        a[0:6, 0:6].reshape(-1, 4), a[0:6, -6:].reshape(-1, 4),
        a[-6:, 0:6].reshape(-1, 4), a[-6:, -6:].reshape(-1, 4),
    ])
    bg = np.median(corners[:, :3], axis=0)
    dist = np.linalg.norm(a[:, :, :3].astype(float) - bg, axis=2)

    R = a[:, :, 0].astype(int)
    G = a[:, :, 1].astype(int)
    B = a[:, :, 2].astype(int)
    H, W = a.shape[:2]

    # 判定「要删的背景像素」：
    #   ① 与背景色距离够近；
    #   ② 画面最下方那一条里的粉色调 —— 模型在角色脚下画了一片粉色地面阴影，
    #      它比背景深，色距不够近，但明显是粉的（R 明显大于 B、且 G 明显小于 R），
    #      而这个判据不会误伤奶白色的毛（毛的 R≈G≈B）。
    bottom = np.zeros((H, W), bool)
    bottom[int(H * 0.86):, :] = True
    pinkish = (R - B > 10) & (G < R - 15)
    kill = (dist < dist_tol) | (bottom & pinkish)
    a[kill, 3] = 0

    # 只保留与画面中心连通的前景块
    keep = keep_main_blob(a[:, :, 3])
    a[~keep, 3] = 0

    # 把被误删的小洞补回来（鼻头、腮红），再用闭运算清掉零星小点
    a[:, :, 3] = fill_small_holes(a[:, :, 3])
    a[:, :, 3] = close_small_holes(a[:, :, 3])

    # 边缘残留的半透明背景像素：与透明区相邻且接近背景色的，压低不透明度
    alpha = a[:, :, 3]
    transparent = alpha == 0
    near = np.zeros_like(transparent)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        near |= np.roll(transparent, (dy, dx), (0, 1))
    edge = (~transparent) & near & (dist < EDGE_TOL)
    a[edge, 3] = (a[edge, 3] * EDGE_KEEP).astype(np.uint8)

    out = Image.fromarray(a)
    if blur:
        al = out.getchannel("A").filter(ImageFilter.GaussianBlur(blur))
        out.putalpha(al)
    return out, bg


def despeckle(im, k=7, verbose=True):
    """去掉底色上散落的小颗粒：对 alpha 做形态学开运算（先腐蚀再膨胀）。

    小颗粒在腐蚀阶段就没了，膨胀阶段回不来；角色主体只是边缘轻微收缩再还原。
    """
    arr = np.array(im)
    a = arr[:, :, 3]
    m = Image.fromarray(((a > 16).astype(np.uint8)) * 255)
    before = int((a > 16).sum())
    m = m.filter(ImageFilter.MinFilter(k)).filter(ImageFilter.MaxFilter(k))
    keep = np.array(m) > 127
    arr[~keep, 3] = 0
    if verbose:
        print("  去碎屑: %d -> %d 前景像素" % (before, int(keep.sum())))
    return Image.fromarray(arr)



def trim_noise(im, a_min=48):
    """清掉抠图后残留的、几乎全透明的边缘噪点。"""
    arr = np.array(im)
    arr[arr[:, :, 3] < a_min, 3] = 0
    return Image.fromarray(arr)


def solid_bbox(im, a_min=120, min_count=12, pad=8):
    """按「足够实」的像素算裁剪框。

    直接用 getbbox()（alpha>0）会被边缘那些泛洪没覆盖到的背景残留拉大框，
    导致角色被缩得偏小。这里要求某一列/行至少有 min_count 个实心像素才算主体。
    """
    a = np.array(im)[:, :, 3]
    m = a > a_min
    H, W = m.shape
    colc, rowc = m.sum(axis=0), m.sum(axis=1)
    cols = np.nonzero(colc >= min_count)[0]
    rows = np.nonzero(rowc >= min_count)[0]
    if not len(cols) or not len(rows):
        return im.getbbox()
    return (max(0, int(cols[0]) - pad), max(0, int(rows[0]) - pad),
            min(W, int(cols[-1]) + 1 + pad), min(H, int(rows[-1]) + 1 + pad))


def place(im, scale, box=None):
    bbox = box or im.getbbox()
    if bbox is None:
        raise SystemExit("抠完是空白，检查阈值")
    cut = im.crop(bbox)
    nw, nh = max(1, int(cut.width * scale)), max(1, int(cut.height * scale))
    cut = cut.resize((nw, nh), Image.LANCZOS)
    canvas = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    canvas.paste(cut, (CANVAS[0] // 2 - nw // 2, BASELINE - nh), cut)
    return canvas


for base, files in JOBS.items():
    keyed = {}
    for k, fname in files.items():
        p = os.path.join(SRC, fname)
        if not os.path.exists(p):
            print("缺文件:", p)
            continue
        im, bg = key_out(p)
        im = despeckle(im)
        im = trim_noise(im)
        keyed[k] = im
        print("%-10s %-6s 背景=%s 实心框=%s"
              % (base, k, tuple(int(v) for v in bg), solid_bbox(im)))
    if "idle" not in keyed:
        continue
    boxes = {k: solid_bbox(v) for k, v in keyed.items()}
    # 三帧共用同一个裁剪框：各帧包围盒大小略有差异（边缘杂点、毛尖），
    # 若各裁各的，缩放后角色会左右/上下跳动，所以取并集统一裁。
    box = (min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values()),
           max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values()))
    scale = TARGET_H / (box[3] - box[1])
    print("  %s 统一裁剪框 = %s  缩放 = %.4f" % (base, box, scale))
    for k, im in keyed.items():
        dst = os.path.join(OUT, "%s_%s.png" % (base, k))
        place(im, scale, box).save(dst)
        print("  写出", os.path.basename(dst), os.path.getsize(dst), "字节")
print("DONE")
