# 阿拾桌宠 · 项目交接（2026-09-12 23:40 更新）

> 新对话直接读这份，不用翻历史。上一版是 2026-09-11 19:06。

---

## 一、这是什么 / 三个名字别搞混

Windows 桌面 AI 桌宠，PySide6 写的。它会**看你屏幕**，用朋友口吻陪你吐槽，
**不是**那种问你"要不要休息"的助手。

| 层面 | 名字 | 说明 |
|---|---|---|
| **项目名** | **阿拾桌宠** | 对外叫法，写在 GitHub 仓库介绍里 |
| **仓库** | **`canshuang1221/ashi-desktop-pet`** | 已**公开**（2026-09-12 改的）|
| **程序 / 源码目录 / exe** | **`ashi`** | `desktop-pet/ashi/`、`ashi.exe`、`ashi.spec` |
| **发布资产** | `v1.0.5.zip` / `v1.0.5.exe` | ⚠️ 想叫「阿拾v1.0.5」但**GitHub 不支持中文资产名**（见第七节）|

> ℹ️ 容易误解的点：本地路径 `E:\WorkBuddy\Git\` 里的 "WorkBuddy" 只是
> **本地文件夹名**，跟云端仓库无关。这个仓库的 git remote 只有一个 `jarvis`
> → `canshuang1221/ashi-desktop-pet`。另外确实存在一个
> `canshuang1221/WorkBuddy-Workspace` 仓库，但它是**另一个私有空仓库**，
> 我们的代码从没往那儿推过。

---

## 二、从哪个文件夹继续（★ 2026-09-13 已改：不再用副本）

| 路径 | 用途 |
|---|---|
| `E:\WorkBuddy\Git` | **git 仓库根**（分支 `main`）|
| **`E:\WorkBuddy\Git\desktop-pet\ashi\`** | **唯一的开发目录 + 运行目录**。代码和数据都在这一处 |
| `E:\WorkBuddy\Git\desktop-pet\.workbuddy\memory\` | 我的工作记忆（按天一个 md）|
| `E:\WorkBuddy\阿拾-工作记忆备份\` | 工作记忆的**仓库外**备份（`.workbuddy/` 被 gitignore，怕被误删）|

### 为什么不再用 worktree 副本

以前在 `C:\Users\46001\WorkBuddy\Worktrees\…` 另开一个 worktree 改代码，
好处是"不污染 E: 源码"，但代价很大：

- **数据不跟着副本走** —— `config.json` / `memory` / `activity` / `shots`
  都被 `.gitignore` 排除，新建 worktree 时**一个都不会带过去**，
  每次开新副本都得手工搬一遍
- 切分支（比如游戏模式）时同理，数据留在原地不动
- 数据因此散落在 C 盘，而 git 本身就已经是保险了（改错能 diff / 能回退）

**2026-09-13 已把 C 盘 worktree 删掉**（`git worktree remove` + 分支已删），
数据全部搬进 `E:\WorkBuddy\Git\desktop-pet\ashi\`。
**以后所有改动直接在这个目录里做，改完直接 commit + push，不再开副本。**

> 目录 `C:\Users\46001\WorkBuddy\Worktrees\desktop-pet\main-733f0f98` 可能还剩一个
> **空壳**（被当前会话占用删不掉，0 字节），重启后消失，不用管。

**开发流程（现在的做法）**：
在 `E:\WorkBuddy\Git\desktop-pet\ashi\` 直接改 → `git add` → `git commit`
→ `git push jarvis main`。就三步，没有合并环节。

**启动**：双击 `E:\桌面\打开阿拾.vbs`（指 E: 的 `main.py`，改完立刻生效，
不用打包）；关闭用 `关闭阿拾.vbs`（会先发 `--quit` 优雅退出）。
两个脚本都是**纯 ASCII**（wscript 按 GBK 读 .vbs，中文注释会破坏解析）。

> ⚠️ 我启动的进程会被沙箱回收（活不过 1 分钟），**必须你双击**。
> 我只能"起监测等你启动"。

---

## 三、当前状态

| 项 | 值 |
|---|---|
| `main` | `fda6253`（本次修复后待提交新 commit）|
| 冻结分支 | `feature/game-mode` = `4dbc235`（**游戏模式，未合入**）|
| 已发布 | **v1.0.6 = 最新**（见 <https://github.com/canshuang1221/ashi-desktop-pet/releases/latest>）|
| 更早的 | v1.0.0、v1.1.0（v1.1.0 是游戏模式版，用户认为未完善）|
| 仓库 | 公开 |

### v1.0.6 里有什么（2026-09-13 这天的改动）

**模型下拉**：设置页「模型」「视觉模型」下拉框之前点开没有下拉三角（QSS 只留了
`drop-down` 宽度没定义 `down-arrow`，Qt 可编辑模式下不画箭头）。现在给两个下拉框
都补上了 SVG 箭头（存 `assets/dropdown_arrow.png`/`_hover.png`，默认灰色、悬停变蓝），
且运行时用 `_asset_path()` 从 `ASSETS_DIRS` 解析（打包成 exe 后能正确回退到
`sys._MEIPASS` 里的素材，不会因路径错位而画不出箭头）。

**感知/搭话默认开启**：`config.DEFAULT` 里「开启屏幕感知」`sense.enabled` 和「定时搭话」`tick.enabled`
之前默认是 `false`，新用户头一次打开感知/搭话是关的。现改成默认 `true`，并同步重新生成
`config.example.json`（模板跟着 DEFAULT 走）。

### v1.0.5 里有什么（2026-09-12 这天的改动）

**记忆**：从"每轮对话都提炼"改成**每天首次启动沉淀一次**（读前一天聊过的 +
屏幕里看到的，整体重写 `user_memory.md`，用 `memory/.last_digest` 记进度，
启动后 8 秒 + 每小时复查）。修了 `_save_history` 只留 60 条导致
**聊天记录半小时内被感知流水挤光**的真 bug（现在 chat/note 留 400 条）。
新增 `brain.user_block()`：称呼/共情由代码生成，不依赖会被覆盖的 persona 文本。

**桌宠**：贴边判定按**可见立绘轮廓**（alpha 包围盒）而非窗口矩形；
规则改成**人物过半出屏才隐藏，没过半就停在原地不干预**；
四边都支持（含下边）；箭头改瞄头顶；修了负坐标被误判成"没存过"的 bug。

**托盘**：启用 QLocalServer 做实例间控制通道，新增 `main.py --quit` 优雅退出
（先反注册图标，从根上不留幽灵图标）；监听 `TaskbarCreated` 自动重建；
菜单加「修复托盘图标」；菜单让路改挂 `aboutToShow/aboutToHide`。
版本号改为按 mtime 自动生成并写进 `crash.log`。

**说话**：三层封堵"复读"（提示词+改写+出口过滤）；关键词级去重（最近 10 句里
出现 ≥3 次的二字组合判为用滥）；感知会读画面里的文字；前台窗口裁剪加面积闸。

**模型**：默认改成 `deepseek-flash`（官方确认支持视觉且最便宜）——
原来默认 `deepseek-chat` 是纯文本，新用户一上手核心功能就是坏的。
`config.example.json` 改为**从 `config.py` 的 DEFAULT 生成**
（`tools/gen_example_config.py`），不会再落后于代码。

**打包**：`ashi.spec` 排除 `assets/_source`，exe 71.5MB → **46.3MB**。

---

## 四、下一步：游戏模式（v1.1.0 之后要做的）

`feature/game-mode` 分支冻结在 `4dbc235`，**未合入 main**。内容：
缩到 55% + 气泡半透明 + **鼠标穿透**（`WS_EX_TRANSPARENT`），
`Ctrl+Alt+G` 切换，用 DWM 可见边界判全屏。

**重新开工的顺序**（上次的结论）：

1. **先修托盘锁死** —— 现在 main 上的托盘已经大改（优雅退出、自愈、
   让路逻辑），所以最好把 `feature/game-mode` **rebase 到最新 main** 再动手，
   而不是直接合入旧的。
2. 再做 **F4 可配置快捷键**（原来 `Ctrl+Alt+G` 写死且可能冲突）
3. 快捷键要能在设置里改，并检测冲突（参考 `main.py` 里 Ctrl+M 被占用时的提示）

---

## 五、协作约定（重要）

### ① 需要你手动操作时，我会自动等待

**你明确要求过的**：我让你做某事（启动程序、点按钮、确认）之后，
**不能干完就撒手**，要在同一轮里持续轮询那个状态，一旦达成自动继续。
默认最多等 **3~5 分钟**，开始前告诉你上限；超时才结束并说明卡在哪。

### ② 其他约定

- **出图花钱的活，先问再做**
- **桌面在 `E:\桌面\`**（不是 `C:\Users\46001\Desktop`，那个是空壳）
- **提交身份**：`canshuang1221` / `206538262+canshuang1221@users.noreply.github.com`
- **`gh` 命令必须带 `-R canshuang1221/ashi-desktop-pet`**
- **别擅自合并分支、别未经你验证就发布**
- **公开/改名这类对外动作，先问我**（不过这次"公开"你已经明确说过要了）

---

## 六、常用操作

### 打包（**先关阿拾**）

```bash
cd E:/WorkBuddy/Git/desktop-pet/ashi
"C:/Users/46001/.workbuddy/binaries/python/envs/default/Scripts/python.exe" \
  -m PyInstaller --noconfirm ashi.spec
```

### 发布

```bash
gh release view v1.0.5 -R canshuang1221/ashi-desktop-pet --json assets \
  -q '.assets[]|"\(.name) \(.size)"'
gh release upload v1.0.5 -R canshuang1221/ashi-desktop-pet --clobber dist/X.zip dist/X.exe
```

### 看它干了什么

| 文件 | 内容 |
|---|---|
| `log.txt` | 每次弹气泡说了什么 |
| `ui_log.txt` | 拦截记录（`skip repeat` / `skip assistant-tone` / `skip overused word` / 菜单操作）|
| `crash.log` | 崩溃调用栈（黑匣子），**也记启动版本号** |
| `memory\YYYY-MM-DD.json` | 当天对话记录 |
| `activity\history.md` | 今日足迹档案 |

### 回归测试（在 `C:\Users\46001\AppData\Local\Temp\`）

`test_edge_art.py`(38 项·贴边/过半/停靠)、`test_round3.py`(本轮五项改动)、
`test_digest.py`(每日沉淀)、`test_tray_fix.py`(托盘/优雅退出)、
`test_cursor_ban.py`(光标封禁)、`test_history_keep.py`(记录保留)、
`test_import.py`(离屏导入)。

---

## 七、踩过的坑（别再踩）

1. **TOPMOST 窗口弹菜单前必须先让路**，否则菜单被自己压住（托盘点不动的真因）
2. **Qt 槽函数里的异常会被静默吞掉** —— 用 offscreen 直接实例化才能复现
3. **`GetWindowRect` 对最大化窗口返回含隐藏边框的尺寸**（1936×1066，比屏幕大）
4. **Bash 里的 `grep` 不可信**：`{}` 转义会坏、数字会假（曾把 2 条报成 455 条）；
   要统计/扫描就**用 Python**。`find` 同样不可靠（会报"参数格式不正确"）
5. **`config.json` 必须永远不上云** —— 里面有 API Key。
   `.gitignore` 已挡住它和 `memory/ activity/ shots/ *.log user_memory.md`。
   **发布前用 Python 扫一遍**（`rc-[0-9a-f]{16,}`、`sk-[A-Za-z0-9]{20,}`、key 字面值），
   包括 `git log --all -S<key>` 全历史
6. **GitHub release 资产不支持中文名** —— 传 `阿拾探针.txt` 会被强制改名成
   `default.txt`。所以资产只能用 ASCII（现在的 `v1.0.5.zip` / `v1.0.5.exe`）
7. **`gh release download` 拉旧资产经常 502** —— 拉不到就别死磕
8. **改 git 目录名时，被忽略的运行数据不会跟着走！**
   2026-09-12 把 `desktop-pet/jarvis-lite` 改名成 `ashi` 时，
   E: 那份的 `config.json`/`dist/`/`memory/` 全被留在旧目录里、旧目录被删，
   **数据一度丢失**（后来从一份临时副本里救回来了）。
   → **教训：目录改名前后，先手工把未被 git 跟踪的运行数据搬过去。**
9. **被忽略的未跟踪文件不跨 worktree 共享** —— 某文件只在 E: 有时，
   副本 `git add -A` 加不到，得先复制过去
10. **`git commit --amend` + 强推后，另一个 worktree 的分支会脱节**，
    下次 ff 合并会失败 → 去那个 worktree `git reset --hard <新commit>` 对齐
11. **中文路径本身没问题**（实测：中文+空格目录里能跑能打包）；
    但**桌面 .vbs 启动器内容必须纯 ASCII**（wscript 按 ANSI/GBK 读 .vbs）

---

## 八、待清理（等用户确认再动手）

- `E:\WorkBuddy\Git\_中文路径测试\` —— 我建的临时测试副本，约 173MB
- `E:\...\ashi\dist\` 里的历史 exe（`ashi.prev-*.exe` 等）
- 开发用完的 worktree 副本（**里面有你日常在跑的数据，删之前要先迁移**）
