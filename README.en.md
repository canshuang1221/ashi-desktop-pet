<div align="center">

🌐 [简体中文](README.md) | **English**

</div>

---

# Ashi · Desktop Pet

A little creature that lives on your Windows desktop. It **watches your screen** and hangs out with you — griping at bad movies, getting spooked by horror games, reacting to whatever you're doing. Not another assistant waiting for instructions.

## Download

👉 **[Latest Release](https://github.com/canshuang1221/jarvis-lite/releases/latest)**

Unzip and double-click `JarvisLite.exe`. **You need to enter your own DeepSeek API Key on first run** (right-click the tray icon → Settings → API).

> Unzip somewhere **writable** — not `C:\Program Files`. It creates `config.json`, `memory\`, etc. next to the executable.

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
| Long-term memory | Distills "facts about you" from conversations, gets to know you better over time. Editable by hand |
| Daily log | Records what you did today and **how long each thing took** (time away from the PC excluded), archived daily |
| Edge docking | Drag to the left/right screen edge and it half-hides; hover to peek out |
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
python main.py            # run directly

pyinstaller --noconfirm --onefile --windowed --name JarvisLite \
  --collect-all certifi --add-data "assets;assets" \
  --exclude-module PyQt5 --exclude-module tkinter \
  --exclude-module matplotlib main.py
```

`config.example.json` is a safe template to commit; the real `config.json` (containing your API key) is already in `.gitignore`.

---

<div align="center">

🌐 [简体中文](README.md) | **English**

</div>
