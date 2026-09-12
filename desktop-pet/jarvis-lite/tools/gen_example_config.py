# -*- coding: utf-8 -*-
"""从 config.py 的 DEFAULT 重新生成 config.example.json。

`config.example.json` 是给别人照抄的模板，必须和代码里的 DEFAULT 保持一致。
不一致的后果很隐蔽：模板停在几天前的样子，新用户照着配就少了一堆新提示词规则
（踩过：模板里没有 user_name、也没有后来加的「读画面文字」「别提光标」那几条）。

用法（在 jarvis-lite 目录下）：
    python tools/gen_example_config.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import config  # noqa: E402  必须在 sys.path 之后导入

OUT = os.path.join(ROOT, "config.example.json")


def main():
    data = json.loads(json.dumps(config.DEFAULT))   # 深拷贝
    data["api"]["api_key"] = ""                     # 模板里绝不能带 key
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("已写出 %s（%d 字节）" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
