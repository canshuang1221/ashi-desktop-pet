# 阿拾桌宠 · 交接文档

生成时间：2026-09-10 ｜ 版本：**v2026.09.08.1540**（源码与 dist/ashi.exe 一致）

---

## 1. 项目是什么

Windows 桌面 AI 桌宠。常驻屏幕右下角（可拖动、贴边半隐藏），会主动看屏幕搭话、点气泡可以接着聊、有历史记录与设置面板。

- 源码目录：`ashi/`（7 个 .py）
- 可执行文件：`ashi/dist/ashi.exe`（PyInstaller onefile，约 47MB）
- 运行态目录（exe 同级）：`config.json`（配置）、`memory/`（对话记忆）、`notes/`（笔记）、`log.txt`、`ui_log.txt`

---

## 2. 本次做了什么（2026-09-08 全天）

### 功能与体验
| 项 | 内容 |
|---|---|
| 多皮肤 | 猫猫 / 史莱姆 / 机器人三形态，设置里可切换 |
| 贴边隐藏 | 完全贴边才隐藏（阈值归零 40→0）；桌宠归位菜单可一键找回 |
| 气泡交互 | 悬停不消失；**单击气泡**打开当轮对话（带截图上下文，全新对话框不叠加） |
| 感知提示词 | 去毒舌、加代入感：**角度×句式×长度**三维随机（8×5×3=120 种组合），最近 6 句不重复 |
| 截图策略 | 感知时优先截**前台工作窗口**（多屏/负坐标保护，失败退回全屏），scale 0.6 / q72 |
| 自我认知 | 提示词明确“猫猫/史莱姆/机器人都是阿拾你自己”，并按当前皮肤动态注入；方位按用户视角（画面左=用户左手边） |
| 历史记录 | **只显示阿拾说过的话**，微信式白底气泡（宽度自适应 + 昵称时间灰字），浅灰聊天背景 |
| 感知内容入库 | 感知/主动搭话的内容现在也会进历史（之前被 record=False 吞掉，导致“只有一条记录”） |
| 停靠防抖 | 半隐藏滑出后延迟 500ms 缩回 + 二次确认（鼠标还贴边/在宠物上就不缩），消除左右横跳闪烁 |
| 窗口居中 | 设置/历史打开时移到屏幕正中央（**不置顶、不强制前置**，不遮挡其他应用） |
| 去功能 | 「看屏幕」「记笔记」已移除（带图请求在用户接口无响应） |

### 稳定性修复
- 记笔记卡死：同步网络请求卡主线程 → 改后台线程（截屏留主线程）
- 设置/历史卡死：菜单里 exec 模态对话框 → 改延后一拍 + 非模态复用实例
- 截图链接乱码：QTextBrowser 把 file:/// 当文档导航渲染二进制 → setOpenLinks(False) + 系统打开
- 启动即崩：VERSION 写成类属性却按全局引用 → 移为模块级常量
- 托盘菜单白底白字：补全 QMenu::item 文字色/悬停色
- 黑匣子：所有窗口打开/失败写 `dist/ui_log.txt`（含窗口坐标），失败还会气泡提示

---

## 3. 发生过什么（踩坑记录，换机后别再踩）

1. **改 `config.py` 的默认提示词不生效**——用户配置从 `dist/config.json` 读，改完必须同步到 `config.json` 和 `dist/config.json` 两份（已同步）。
2. **`py_compile` 只查语法，查不出运行时 NameError**（VERSION 那次导致 exe 启动即崩）。**打包前必须做运行时冒烟**：
   ```
   import main; main.App._already_running = lambda self: False; a = main.App(); a.show_history()
   ```
   （offscreen 测试需加 `os.environ["QT_QPA_PLATFORM"]="offscreen"`；运行中还有实例时必须绕开单实例锁，否则 App 走 dup 分支没有 `chat` 属性）
3. **vbs 脚本不能含中文**：Write 工具写 UTF-8，Windows 脚本宿主按 GBK 解析 → 报 800A01A8。注释一律英文。
4. **vbs 启动的实例与 exe 双击不一致**（历史窗口不弹）始终没定位到根因，最终用 `explorer` 拉起 exe 规避（同源启动）。
5. **offscreen 环境假象**：对显示中的 QTextBrowser 调 `insertHtml/insertImage/setTextCursor` 会挂起（90s 超时被杀），但真机正常；`setMarkdown` 稳定。别把 offscreen 的挂死当成真 bug。
6. **外部回退**：源码偶发被回退/丢改动，交付前用标志性字符串全量校验过一遍（见 `交接-校验` 里的检查点）。
7. **打包与启动撞车**：打包期间 exe 是半成品，用户此时双击会得到坏程序。流程上已固定为“打包完成确认后再启动”。

---

## 4. 还需要做什么（待办清单）

按优先级：

1. **感知功能未实测**：`sense.enabled=false`（当前关闭）。开启后每 90 秒看一次屏幕说话；提示词大改过（去毒舌+代入感+自我认知），需要真人体验确认语气是否自然。
2. **历史气泡圆角**：Qt 富文本不支持圆角，目前是直角气泡。要真正像微信可换成 `QListWidget` 自绘 item（工作量中等）。
3. **看屏幕/记笔记的替代方案**：现接口（AMD Radeon 网关 + `DeepSeek-V4-Flash-Vision-Exp`）对带图请求无响应。若换支持视觉的接口（如 DeepSeek 官方或填 `vision_model`），可恢复这两个功能。
4. **启动方式统一**：桌面现在是 vbs（explorer 拉起）。更干净的做法是换成 .lnk 快捷方式直指 exe（本机 COM 被安全策略拦，没做成）。
5. **打包体积**：47MB，可用 `--exclude` 更多未用模块瘦身（当前已排除 PyQt5/tkinter/matplotlib）。

---

## 5. 换一台电脑怎么继续

### 环境
- Python 3.13（本机用 `C:\Users\Administrator\.workbuddy\binaries\python\envs\default`）
- 依赖：`PySide6`、`requests`、`certifi`、`pyinstaller`

### 打包命令（在 ashi 目录下）
```
pyinstaller --noconfirm --onefile --windowed --name ashi ^
  --collect-all certifi ^
  --exclude-module PyQt5 --exclude-module tkinter --exclude-module matplotlib main.py
```
产出在 `dist/ashi.exe`。

### 运行
- 直接双击 `dist/ashi.exe`（配置/记忆写在 exe 同级目录，换机即新数据）
- 桌面启动脚本 `start-ashi.vbs`：先 taskkill 旧实例，再 explorer 拉起 exe

### 配置（dist/config.json）
- `api.base_url` / `api.api_key` / `api.model`：接口三件套（当前是 AMD Radeon 网关 + DeepSeek-V4-Flash-Vision-Exp）
- `api.vision_model`：留空（视觉功能已停用）
- `sense.enabled`：感知开关，默认 false
- `pet.skin`：`cat` / `slime` / `robot`
- `ui.font_size` / `ui.bubble_width` / `ui.bubble_ms`：字号、气泡宽度、气泡留存毫秒

### 开发约定
- 每次改动后：**运行时冒烟 → 打包 → 杀旧进程 → 启动 → 托盘版本号核对**
- 版本号在 `main.py` 顶部 `VERSION`，托盘菜单第一项显示
- 窗口相关失败都会写 `dist/ui_log.txt`，排查先看它

---

## 6. 包内文件清单

```
ashi/
├─ HANDOVER.md          ← 本文档
├─ main.py              托盘/感知/窗口管理/热键（VERSION 在这）
├─ pet.py               桌宠本体（三形态绘制、拖动、贴边、气泡）
├─ chat.py              对话面板
├─ brain.py             接口客户端、记忆、截屏
├─ history.py           历史记录（微信式气泡）
├─ settings.py          设置面板
├─ config.py            配置默认值与读写
├─ start-ashi.vbs     桌面启动脚本副本
├─ 阿拾 桌宠.vbs        桌面上那个启动脚本
├─ config.json          项目侧配置（与 dist 内一致）
└─ dist/
   ├─ ashi.exe    ← 可直接运行的成品 v2026.09.08.1540
   ├─ config.json       运行配置（API Key 等）
   ├─ memory/           对话记忆（按天 json）
   └─ notes/            笔记
```
