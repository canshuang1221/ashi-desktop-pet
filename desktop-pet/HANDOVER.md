# 阿拾 · 项目交接总结（2026-09-11 19:06）

> 新对话直接读这份就够了，不用翻之前那 38 万 token 的历史。

---

## 一、这是什么

Windows 桌面 AI 桌宠「阿拾」，PySide6 写的。它会看屏幕、用朋友口吻陪你吐槽，
**不是**那种问你"要不要休息"的助手。代码托管在 GitHub 私有仓库
`canshuang1221/ashi-desktop-pet`。

---

## 二、从哪个文件夹继续施工

| 路径 | 用途 |
|---|---|
| `E:\WorkBuddy\Git` | **git 仓库根** —— 在 WorkBuddy 里把工作目录设成这个 |
| `E:\WorkBuddy\Git\desktop-pet\ashi\` | **源码在这**（7 个 py + `assets/` + `tools/`）|
| `E:\WorkBuddy\Git\desktop-pet\ashi\dist\` | **运行目录**：exe + `config.json` + 日志 + `memory/` |
| `E:\WorkBuddy\Git\desktop-pet\.workbuddy\memory\` | 我的工作记忆（按天一个 md）|

**启动方式**：双击 `E:\WorkBuddy\Git\desktop-pet\ashi\start-ashi.vbs`
（它先 taskkill 旧进程，再启动 `dist\ashi.exe`）

> ⚠️ **我启动的进程会被沙箱回收**（活不过 1 分钟，试过三种方式都不行），
> 所以**必须你双击**。我只能"起监测等你启动"。

---

## 三、当前版本状态

| 项 | 值 |
|---|---|
| 当前分支 | `main` = `d212669` |
| 冻结分支 | `feature/game-mode` = `4dbc235`（游戏模式，未合入 main）|
| 当前 exe | `dist\ashi.exe`，**19:03 打包**，68.3MB，含 12 张立绘 |
| 远程发布 | `v1.0.0`（稳定）、`v1.1.0`（含游戏模式）|

### `main` 分支包含

- 默认形象 = **立绘 · 狐耳少女**（新用户第一次打开就是她）
- 崩溃相关修复：线程生命周期、置顶调用时机、退出时等线程、
  **`crash.log` 黑匣子**（faulthandler，段错误会写出 Python 栈）
- **菜单修复（最新）**：桌宠不再压住自己的菜单 / 托盘点不动

### `feature/game-mode` 分支（冻结，未合入）

- 游戏模式：缩小到 55% + 气泡半透明 + **鼠标穿透**（点击落到游戏上）
- `Ctrl+Alt+G` 切换；自动检测全屏（用 DWM 可见边界，不是 `GetWindowRect`）
- 已知问题：托盘菜单锁死、快捷键不可配置 —— 要继续做需先修这两个

---

## 四、待办

1. **验证菜单修复**：右键桌宠 → 菜单是否显示在最上面；右键托盘 → 能否点动
2. **验证崩溃修复**：正常用几天，崩了看 `dist\crash.log`
3. `v1.1.0` 那个 release 怎么处理（标预发布 / 撤下）—— **等你决定**
4. 游戏模式若要继续：先修托盘锁死，再做 **F4 可配置快捷键**

---

## 五、协作约定（重要）

### ① 需要你手动操作时，我会自动等待

**这是你明确要求过的**：我让你做某事（启动程序、点按钮、确认）之后，
**不能干完就撒手**。我会在**同一轮里持续轮询检查那个状态**
（例如循环检测进程是否出现、文件是否被修改），**一旦达成自动继续下一步**。

- 默认最多等 **3~5 分钟**，开始前会告诉你等待上限
- 只有超过时限仍未达成，才结束这轮，并说明「等了多久、卡在哪一步」

### ② 其他约定

- **出图花钱的活，先问再做**（你对"花了钱还用同一套模板"很敏感）
- **桌面在 `E:\桌面\`**（不是 `C:\Users\46001\Desktop`，那个是空壳）
- **关阿拾**：任务管理器结束 `ashi.exe`，或直接跟我说，我用命令关
- **提交身份**：`canshuang1221` / `206538262+canshuang1221@users.noreply.github.com`
- **`gh` 命令必须带 `-R canshuang1221/ashi-desktop-pet`**
  —— 默认 remote 指向另一个仓库，曾把 release 发错地方
- 别擅自合并分支、别未经你验证就发布

---

## 六、常用操作

### 打包（**必须先关阿拾**，否则文件被占用）

```bash
cd E:/WorkBuddy/Git/desktop-pet/ashi
"C:/Users/46001/.workbuddy/binaries/python/envs/default/Scripts/python.exe" \
  -m PyInstaller --noconfirm --onefile --windowed --name ashi \
  --collect-all certifi --add-data "assets;assets" \
  --exclude-module PyQt5 --exclude-module tkinter --exclude-module matplotlib main.py
```

### 看它干了什么

| 文件 | 内容 |
|---|---|
| `dist\log.txt` | 每次弹气泡的内容 |
| `dist\ui_log.txt` | 拦截记录（`skip repeat` / `skip assistant-tone` / `rewrite` / 菜单操作）|
| `dist\crash.log` | 崩溃时的 Python 调用栈（黑匣子）|
| `dist\memory\YYYY-MM-DD.json` | 当天对话记录 |

### 回归测试脚本（临时目录）

`C:\Users\46001\AppData\Local\Temp\` 下的 `test_follow.py`（跟随）、
`test_arrow.py`（气泡箭头）、`check_all_frames.py`（立绘三帧）、
`test_crash_fix.py`（对话 8 轮不崩）

---

## 七、踩过的坑（别再踩）

1. **TOPMOST 窗口要弹出自己的菜单时，必须先让路**
   （停掉抢置顶 + 临时 `HWND_NOTOPMOST`），否则菜单永远被压在它下面
   —— 这就是「托盘点不动 / 阿拾凌驾于菜单之上」的真正原因
2. **Qt 槽函数里的异常会被静默吞掉** —— 表现为窗口空白但毫无报错。
   要用 offscreen 直接实例化来复现
3. **`GetWindowRect` 对最大化窗口会返回含隐藏边框的尺寸**（实测 1936×1066，
   比屏幕还大），判全屏要用 DWM 的 `DWMWA_EXTENDED_FRAME_BOUNDS`
4. **Git Bash 里的 `timeout` 是 Windows 的 `timeout.exe`**，不是 GNU 的
5. **gh 的 token 存在系统 keyring**（`hosts.yml` 里没有）。
   丢了可以 `git -c credential.helper=manager credential fill` 取回来，
   再 `gh auth login --with-token`
6. **重建 `.git` 后仓库级 git config 全丢**（`user.name/email`、
   `credential.helper`），提交会报 `unable to auto-detect email address`
7. **`gh release upload --clobber` 期间查 assets 是空的** —— 别误判成失败，
   68MB×2 大概要传十分钟
