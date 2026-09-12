<div align="center">

🌐 **简体中文** | [English](README.en.md)

</div>

---

# 阿拾 · 桌面宠物

一只住在 Windows 桌面上的小宠物。它会**看你屏幕**，跟你一起吐槽、一起看剧、一起打游戏——不是那种等你下指令的助手。

## 下载

👉 **[最新版本 Releases](https://github.com/canshuang1221/ashi-desktop-pet/releases/latest)**

解压后双击 `JarvisLite.exe` 即可。**第一次用要填一个「能看图」的模型**（右键托盘图标 → 设置 → API）—— 见下一节。

> 注意：解压到一个**可写**的目录，别放 `C:\Program Files`。它会在自己所在的目录下建 `config.json`、`memory\` 等文件。

## 模型必须能「看图」

阿拾的核心是**看你屏幕**，所以 API 必须选支持**图片输入**的模型。
填成纯文本模型**不会崩**，但它会变成瞎子 —— 接口直接返回
`Model xxx does not support image input`，"陪你一起看"这件事就没了。

### 建议使用以下模型

| 接口 | base_url | 模型名 | 依据 |
|---|---|---|---|
| **DeepSeek 官方** | `https://api.deepseek.com/v1` | `deepseek-flash` | 官方文档确认支持视觉（DeepSeek-V4.1-Flash）。**也最便宜**：输入 $0.15/百万、命中缓存 $0.003；单张图最多算 1024 token |
| 硅基流动 | `https://api.siliconflow.cn/v1` | `Qwen/Qwen3-VL-8B-Instruct` | 实测 **1.0 秒**（目前量到最快的）|
| AMD Radeon 网关 | `https://developer.amd.com.cn/radeon/api/v1` | `DeepSeek-V4-Flash-Vision-Exp` | 实测 1.8 秒（这名字就是 V4.1-Flash 的旧名）|
| 智谱 BigModel | `https://open.bigmodel.cn/api/paas/v4` | `glm-4.5v` | 官方文档；另有更新的 `glm-4.6v`、更快的 `glm-5v-turbo` |
| 通义千问 / 百炼 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen3-vl-plus` | 官方文档；同系列还有 `qwen3-vl-flash`、`qwen3-vl-235b` 等 |
| Kimi | `https://api.moonshot.cn/v1` | `kimi-k3` | 官方文档支持图片/视频输入 |

> "实测"那两行是我在本机用同一张小测试图量的单次延迟；真实 1080p 截图会再慢一点，量级不变。
> 标"官方文档"的几行只核对了官方文档、没有实际调用；**模型名和端点请以各厂最新文档为准**
> （百炼新版的端点带业务空间 ID，形如 `https://<业务空间ID>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`）。

### ⚠️ 这些别填（看不见屏幕）

| 模型 | 结果 |
|---|---|
| `deepseek-v4-pro` | 官方文档写明**不支持视觉** —— DeepSeek 家只有 `deepseek-flash` 支持 |
| `deepseek-chat` / `deepseek-reasoner` | 老一代模型名；现在的官方文档只列 `deepseek-flash` 和 `deepseek-v4-pro` |
| AMD 网关的 `DeepSeek-V4-Flash`、`MiniCPM5-2B` | 实测 HTTP 400：`does not support image input` |
| AMD 网关的 `Qwen3.8-Flash-Next` | 实测收了图却不返回内容；连纯文本请求都 >90 秒超时 |

报错长这样，看到它就说明填的模型不会看图：

```
Model xxx does not support image input. Remove the image content or use a vision-capable model.
```

### 怎么填

**只填一个就够**：`api.model` 填上面的视觉模型，`api.vision_model` 留空
（留空 = 聊天和看图共用同一个模型）。

也可以拆开省钱：`model` 填便宜的纯文本模型负责聊天，
`vision_model` 填视觉模型专门看图。

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
| 长期记忆 | **每天沉淀一次**：把前一天聊过的 + 在屏幕里看到的，一起提炼成"关于你的事实"。不再每轮对话都记，所以不会越滚越大，可以直接改 |
| 今日足迹 | 记录今天干了什么、每项**花了多久**（离开电脑的时间不算），每天归档 |
| 称呼与共情 | 会按设置里的称呼叫你（默认「宝宝」），并且**替你发声** —— 你不爽先替你吐槽，你干累了替你喊累 |
| 四边停靠 | 四条边都能贴。拖到**超过一半出屏**才缩起来藏好；没超过一半就停在原地（算你自己放的）。鼠标移过去露出来 |
| 不重复自己 | 最近十句里被用滥的词会被认出来，不再翻来覆去说同一个东西（比如光标、眼睛）|
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
cd desktop-pet/jarvis-lite
python main.py                 # 直接跑源码：改完立刻生效，调试期推荐

# 打包（用仓库里的 spec）
pyinstaller --noconfirm JarvisLite.spec

# 等价的手写参数版
pyinstaller --noconfirm --onefile --windowed --name JarvisLite \
  --collect-all certifi --add-data "assets;assets" \
  --exclude-module PyQt5 --exclude-module tkinter \
  --exclude-module matplotlib main.py
```

- `python main.py --quit`：让**已经在跑的那个实例优雅退出**（先把托盘图标干净反注册再退，
  不留"幽灵图标"）。启动脚本就是先发它、失败再兜底强杀的。
- 想在开发机上直接跑源码而不打包：用 `pythonw main.py` 起（不会多一个黑框控制台），
  数据和日志会落在项目目录里，不碰 `dist/`。
- `config.example.json` 是可以直接提交的模板，真正的 `config.json`（含 API Key）已在 `.gitignore` 里。
- `.gitignore` 还挡住了 `dist/`、`build/`、`*.exe`、`*.log`、`memory/`、`user_memory.md`、`activity/`、`shots/`
  —— 这些是本地运行数据，不会误传出去。

---

<div align="center">

🌐 **简体中文** | [English](README.en.md)

</div>
