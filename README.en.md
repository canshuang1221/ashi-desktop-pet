<div align="center">

🌐 [简体中文](README.md) | **English**

</div>

---

# Ashi · Desktop Pet

A little creature that lives on your Windows desktop. It **watches your screen** and hangs out with you — griping at bad movies, getting spooked by horror games, reacting to whatever you're doing. Not another assistant waiting for instructions.

## Download

👉 **[Latest Release](https://github.com/canshuang1221/ashi-desktop-pet/releases/latest)**

Unzip and double-click `JarvisLite.exe`. **On first run you need a model that can see images**
(right-click the tray icon → Settings → API) — see the next section.

> Unzip somewhere **writable** — not `C:\Program Files`. It creates `config.json`, `memory\`, etc. next to the executable.

## The model must be able to **see**

Ashi's whole point is **watching your screen**, so the API endpoint must accept **image input**.
A text-only model won't crash it — the pet just becomes blind: the API returns
`Model xxx does not support image input` and the "watch along with you" part is gone.

### Recommended models

| Endpoint | base_url | Model | Basis |
|---|---|---|---|
| **DeepSeek (official)** | `https://api.deepseek.com/v1` | `deepseek-flash` | Official docs confirm vision support (DeepSeek-V4.1-Flash). **Also the cheapest**: $0.15/M input, $0.003/M on cache hits; at most 1024 tokens per image |
| SiliconFlow | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-VL-8B-Instruct` | Measured **1.0 s** — the fastest we've timed |
| AMD Radeon gateway | `https://developer.amd.com.cn/radeon/api/v1` | `DeepSeek-V4-Flash-Vision-Exp` | Measured 1.8 s (this is the legacy name for V4.1-Flash) |
| Zhipu BigModel | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.5v` | Official docs; newer `glm-4.6v` and faster `glm-5v-turbo` also exist |
| Qwen / Bailian | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-vl-plus` | Official docs; the family also has `qwen3-vl-flash`, `qwen3-vl-235b`, … |
| Kimi | `https://api.moonshot.cn/v1` | `kimi-k3` | Official docs support image/video input |

> The "Measured" rows are single-call latencies I took on this machine with one small test image;
> a real 1080p screenshot is a bit slower, same order of magnitude. The "Official docs" rows were
> checked against vendor documentation only, not actually called — **always confirm model names and
> endpoints against the vendor's latest docs** (Bailian's newer endpoints embed a workspace ID, like
> `https://<workspace-id>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`).

### ⚠️ Don't use these (they can't see)

| Model | Result |
|---|---|
| `deepseek-v4-pro` | Official docs state it does **not** support vision — only `deepseek-flash` does |
| `deepseek-chat` / `deepseek-reasoner` | Older model names; the docs now list only `deepseek-flash` and `deepseek-v4-pro` |
| AMD gateway `DeepSeek-V4-Flash`, `MiniCPM5-2B` | HTTP 400: `does not support image input` |
| AMD gateway `Qwen3.8-Flash-Next` | Accepts the image but returns nothing; even a text-only call times out (>90 s) |

The error looks like this — seeing it means the model you configured cannot see images:

```
Model xxx does not support image input. Remove the image content or use a vision-capable model.
```

### How to fill it in

**One model is enough**: put a vision model in `api.model` and leave `api.vision_model` empty
(empty = chat and vision use the same model).

Or split them to save money: a cheap text-only model in `model` for chatting,
a vision model in `vision_model` just for looking at the screen.

## What makes it different

This was deliberately designed to **avoid sounding like an AI assistant**:

- It talks about **what's happening on screen**, not about what you're doing
- **Hard bans**: questions, the word "you", giving advice, reminding you to rest
- If it slips into assistant tone, it rewrites itself into a statement first; if it still fails, it stays silent
- Better to say nothing than to emit that "being watched by an agent" feeling

## Features

| Feature | Description |
|---|---|
| Watches & chats | Glances at your screen every 30 seconds and drops an offhand comment |
| Multiple skins | 4 illustrated characters (each with idle / blink / talk frames) + 2 vector skins; external artwork supported |
| Long-term memory | **Distilled once a day**: yesterday's conversations plus what it saw on screen get folded into "facts about you". No per-message writes, so it never bloats. Editable by hand |
| Daily log | Records what you did today and **how long each thing took** (time away from the PC excluded), archived daily |
| Nickname & empathy | Calls you by the nickname set in Settings (default 「宝宝」) and **speaks up for you** — griping on your behalf instead of observing from the sidelines |
| Four-edge docking | All four edges. It only tucks itself away once **more than half** of it is off-screen; less than half and it just stays where you dropped it. Hover to bring it back |
| No self-repetition | Words it has overused in the last ten lines get flagged, so you don't hear the same thing (cursor, eyes…) over and over |
| Keep chatting | Click a speech bubble to continue the conversation. Enter to send, Shift+Enter for a new line |

## Known limitation

**It cannot cover exclusive-fullscreen games.** That's a Windows rule — no ordinary window can, only injection-based overlays (Steam, NVIDIA, Discord) can, and injection carries anti-cheat ban risk.

Set your game to **"Borderless"** or **"Windowed Fullscreen"** and it will float on top normally.

## Project layout

```
desktop-pet/jarvis-lite/
├── main.py         Entry point: tray, timers, sensing schedule, reply filtering
├── pet.py          The pet and speech bubble: drawing, animation, docking
├── brain.py        Model API, conversation memory, long-term memory
├── activity.py     Daily log: activity tags → time accounting → daily archive
├── chat.py         Chat panel
├── history.py      Three viewer windows: history / memory / daily log
├── settings.py     Settings panel
├── theme.py        Shared visual theme
├── config.py       Defaults and prompts
├── tools/          Scripts used to generate character art
└── assets/         Character artwork
```

## Development

```bash
pip install PySide6 requests
cd desktop-pet/jarvis-lite
python main.py                 # run from source: edits take effect instantly (best while iterating)

# package (uses the spec in the repo)
pyinstaller --noconfirm JarvisLite.spec

# equivalent, spelled out by hand
pyinstaller --noconfirm --onefile --windowed --name JarvisLite \
  --collect-all certifi --add-data "assets;assets" \
  --exclude-module PyQt5 --exclude-module tkinter \
  --exclude-module matplotlib main.py
```

- `python main.py --quit`: asks the **already-running instance to exit gracefully** (it
  unregisters its tray icon properly first, so no "ghost icons" are left behind).
  The launcher sends this, then falls back to a hard kill if nobody answers.
- To run from source on your dev box without packaging, use `pythonw main.py` (no extra
  console window); data and logs land in the project folder and never touch `dist/`.
- `config.example.json` is a safe template to commit; the real `config.json` (containing your API key) is already in `.gitignore`.
- `.gitignore` also covers `dist/`, `build/`, `*.exe`, `*.log`, `memory/`, `user_memory.md`,
  `activity/` and `shots/` — local runtime data never gets committed by accident.

---

<div align="center">

🌐 [简体中文](README.md) | **English**

</div>
