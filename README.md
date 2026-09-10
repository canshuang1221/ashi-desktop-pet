<div align="center">

🌐 **简体中文** | [English](README.en.md)

</div>

---

# 阿拾 · 桌面宠物

一只住在 Windows 桌面上的小宠物。它会**看你屏幕**，跟你一起吐槽、一起看剧、一起打游戏——不是那种等你下指令的助手。

## 下载

👉 **[最新版本 Releases](https://github.com/canshuang1221/jarvis-lite/releases/latest)**

解压后双击 `JarvisLite.exe` 即可。**第一次用需要填自己的 DeepSeek API Key**（右键托盘图标 → 设置 → API）。

> 注意：解压到一个**可写**的目录，别放 `C:\Program Files`。它会在自己所在的目录下建 `config.json`、`memory\` 等文件。

## 它是什么样的

设计上刻意避开了"另一个 AI 助手"的口气：

- 说的是**屏幕上正在发生的事**，而不是点评你正在做什么
- **硬性禁止**：问句、「你」和「您」、给建议、提醒休息
- 检测到这些口气会先让它自己改写成陈述句；改完还不合格就不发
- 宁可不说话，也不发出那种"被一个 agent 盯着"的感觉

## 功能

| 功能 | 说明 |
|---|---|
| 看屏幕陪聊 | 每半分钟瞄一眼屏幕，随口一句吐槽/感叹 |
| 多套形象 | 4 套立绘（各三帧：睁眼/眨眼/张嘴）+ 2 套矢量形象，也支持外部素材 |
| 长期记忆 | 从聊天里提炼"关于你的事实"，越用越懂你，可以直接改 |
| 今日足迹 | 记录今天干了什么、每项**花了多久**（离开电脑的时间不算），每天归档 |
| 边缘停靠 | 拖到屏幕左/右边缘自动半隐藏，鼠标移过去再露出来 |
| 继续聊 | 点气泡可以接着聊，Enter 发送 / Shift+Enter 换行 |

## 已知限制

**独占全屏的游戏盖不住。** 这是 Windows 的规则——任何普通窗口都做不到，只有注入式 overlay（Steam / NVIDIA 那种）才行，而那有反作弊风险。

把游戏的显示模式改成**「无边框」/「窗口化全屏」**就能正常浮在上面。

## 代码结构

```
desktop-pet/jarvis-lite/
├── main.py        程序入口：托盘、定时器、感知调度、发言过滤
├── pet.py         桌宠本体与气泡的绘制、动画、停靠
├── brain.py       模型接口、对话记忆、长期记忆
├── activity.py    今日足迹：活动标签 → 耗时统计 → 每日归档
├── chat.py        对话面板
├── history.py     历史记录 / 长期记忆 / 今日足迹 三个查看窗口
├── settings.py    设置面板
├── theme.py       统一视觉主题
├── config.py      默认配置与提示词
├── tools/         生成立绘用的脚本（生图、抠图对齐）
└── assets/        立绘素材
```

## 开发

```bash
pip install PySide6 requests
python main.py            # 直接跑

pyinstaller --noconfirm --onefile --windowed --name JarvisLite \
  --collect-all certifi --add-data "assets;assets" \
  --exclude-module PyQt5 --exclude-module tkinter \
  --exclude-module matplotlib main.py
```

`config.example.json` 是可以直接提交的模板，真正的 `config.json`（含 API Key）已在 `.gitignore` 里。

---

<div align="center">

🌐 **简体中文** | [English](README.en.md)

</div>
