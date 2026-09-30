---
name: /podcast-video
description: 把音频或飞书妙记剪辑成竖屏 9:16 播客视频：转录逐字稿 → 自动按内容分章节 → 生成竖屏 PPT 风格卡片（合成用中间产物）→ 彩色滚动字幕（不同说话人不同颜色）→ 合成多个分视频 + 1 个总视频 → 生成视频号文案。当用户给音频文件或飞书妙记链接、要求"剪辑/做成视频/配图/加字幕/发视频号/生成章节卡片/写文案"时使用。
argument-hint: [音频路径 或 妙记链接]
allowed-tools: Read, Write, Edit, Bash, Grep, Glob, WebFetch
user-invocable: true
---

# /podcast-video — 播客视频剪辑器

把一段音频（或飞书妙记）自动剪辑成可发视频号的竖屏播客视频。

## 产物

- 彩色滚动字幕 `subtitle.ass`（不同说话人不同颜色）
- N 个分视频 `分视频_XX_标题.mp4`（每章一个，字幕已烧录；章数随内容浮动，通常 8~16）
- 1 个总视频 `总视频.mp4`（完整版，字幕已烧录）
- 一段视频号文案 `视频号文案.md`（分析核心观点，精简犀利、吸引点击）
- **一个「收片台」看板 `收片台.html`**（剪完后验收用：上面能直接看视频，下面列每个片段的字幕 + 摘要）

> **章节卡片 `card_XX.png` 不是交付物**，是合成视频用的中间产物（分视频的画面就是它）。
> 仍然必须生成，但不要列进交付清单、也不要单独 present 给用户。

## 版式总原则 —— 字幕永远在上、画面永远在下

**所有版式统一遵守**：字幕落在画面**顶部**安全区，内容/画面在下方。
原因是字幕放底部容易被播放器控件、评论区、平台水印、手机手势条挡住。

| 区域（0~1920） | 内容 |
|----------------|------|
| `0 ~ 300` | 字幕底板（深色半透明圆角）+ 烧录字幕 |
| `300 ~ 820` | 要点卡（章节序号 / 标签 / 标题 / 要点 / 页脚），下沿 6px 主色收口 |
| `820 ~ 840` | 深色分隔条（让字幕+卡片与画面有视觉断口） |
| `840 ~ 1920` | 视频画面区（1080×1080） |

> ⚠️ **上半屏是硬预算，必须完整落在 `0 ~ 840` 内**。`burn_footage.py` 用
> `[card][vp]overlay=0:840` 把真实画面**盖**上去，卡片一旦溢出到 840 以下就被画面吃掉，
> 表现为「最后一条要点和 footer 被切一半」——不报错，只能抽帧才看得出来。
> 要点高度`fit_points()`按剩余空间自动推算（`PANEL_H(520) - 固定占用`），
> **不要**手写 `.point{min-height}`，改字号/间距前先重算这笔账。

纯卡片版式（`gen_cards.py`）同理：字幕底板在 `top:156px`，卡片内容整体下移到 `padding-top:620px`。

## 用法

```
/podcast-video <音频路径>
/podcast-video <飞书妙记链接或 minute_token>
```

**两种版式**（用户可指定，默认纯卡片版式）：

| 版式 | 画面 | 卡片脚本 | 合成脚本 |
|------|------|----------|----------|
| 纯卡片（默认） | 静态章节卡 + 烧字幕 | `gen_cards.py` | `burn_video.py` |
| **视频画面** | 一半真实视频画面（虚化背景填充两侧）+ 一半要点卡 + 字幕底板 | `gen_cards_video.py` | `burn_footage.py` |

视频画面版式有两种排布（两个脚本都要传同一个 `--panel`），**两种都是字幕在上、画面在下**：
- `sub-top`（默认）：字幕底板在上，要点卡紧接其下，视频在最下
- `sub-bottom`：字幕底板在上，要点卡夹在字幕与视频之间

> 历史注记：旧参数值 `bottom` / `top` 已废弃，语义与现在完全不同（旧 `top` 是"卡在上"，
> 字幕位置不固定）。改用新值时**必须两个脚本传同一个 `panel`**，否则字幕会落在错误的位置。

视频画面版式适用于：输入是**带画面的妙记录屏 / 会议录像**，用户要求"要有视频画面 / 保留真实画面"。要点：

1. 逐字稿流程不变（`minutes +detail --transcript`）。
2. 视频源用 `lark-cli minutes +download --minute-tokens <token> --output <相对路径>` 下载
   （⚠️ `--output` 只允许写入当前工作目录 / 账号临时目录 / `~/files`，写到盘符绝对路径会被拒；
   下载后再用 Python `shutil.move` 挪到目标目录。
   ⚠️ URL 里的 minute_token 容易被截断，报 `field validation failed` 时先去 `minutes +search` 反查完整 token）。
3. `gen_cards_video.py` 与 `burn_footage.py` 的版式常量必须一致：`CARD_H=840`、`PLATE_H=292`；
   字幕生成用 `--align 8 --marginv 60 --fontsize 54 --per-line 10`（`--align 8` = 顶部居中）。
4. `burn_footage.py` 的 ffmpeg 输入顺序**固定为 0=视频源（`-ss` 放它前面）、1=章节卡、2=水印层**，
   `build_filter()` 里的 `[0:v]/[1:v]/[2:v]` 与之一一对应，改顺序必炸。
5. 章节的 `start/end` 用**源视频绝对秒**；三段不相邻时直接并列成多个章节，
   总视频由 `-c copy` 拼接（中间被跳过的部分自然不出现）。
6. 水印「丸子的无限进步」由 `burn_footage.py` 自动生成透明 PNG 叠加在**视频区右下角**，
   卡片顶部栏右侧也有一份。
7. 用户只要总视频时传 `--total-only`：分段落到 `<out>/_segments/` 子目录，不生成分视频，
   也不触发 safe-delete 删除钩子。


## 执行流程（九步）

### 第 0 步 — 建工作目录

在 `D:\terminal\` 下新建独立子文件夹，命名 `播客视频_<主题>`。所有中间文件和产物都放这里。

### 第 1 步 — 拿到逐字稿

**输入是音频文件**：走飞书妙记转写（不要用 ffmpeg/whisper 本地转写）：
1. 若音频 > 20MB，先用 ffmpeg 压缩（mono 48k 16kHz）：
   ```bash
   ffmpeg -y -i "<音频>" -ac 1 -b:a 48k -ar 16000 "<工作目录>/audio_small.m4a"
   ```
2. `lark-cli drive +upload` 上传 → 拿 `file_token`
3. `lark-cli minutes +upload` 生成妙记 → 从 URL 拿 `minute_token`
4. `lark-cli minutes +detail --minute-tokens <token> --transcript` → 拿逐字稿，保存为 `transcript.txt`

> 转录完整流程见 [lark-minutes](../lark-minutes/SKILL.md)，必须先 Read 它及其 `references/lark-minutes-download.md`。

**输入是妙记链接/token**：直接 `minutes +detail --transcript` 拿逐字稿。

记录音频总时长 `TOTAL_DURATION`（秒），后面字幕要用。

### 第 2 步 — 自动分章节

读 `transcript.txt`，**按话题/内容自动切章**（不是固定 12 章，章数随内容长短浮动，通常 8~16 章）。

每章提取：
- `tag`：章节标签（如「起点 · 丸子」「工具选择」「路径 1 · 跟大 V 学」）
- `title`：大标题（一句话，含金句感）
- `subtitle`：副标题（可选）
- `points`：3~4 条要点（短句，讲清这章讲了什么）
- `footer`：底部说明
- `start` / `end`：该章在音频里的起止秒（从 transcript 的时间戳取）

把结果写成 `chapters.json`，格式见下方「chapters.json 规范」。

**错别字修正**：读逐字稿时识别转写错误（人名、专有名词、播客名），生成 `corrections.json`（`[["错误","正确"],...]`），后面字幕生成会自动替换。

### 第 3 步 — 选配色 + 分说话人颜色

1. **卡片配色**：用 AskUserQuestion 让用户从内置主题里选（见 [color-themes.md](references/color-themes.md)），默认 `purple`。
2. **说话人颜色**：从逐字稿识别所有说话人，按出现顺序从默认色板**自动分配**（见 [color-themes.md](references/color-themes.md) 的说话人色板）。写入 `speakers.json`：
   ```json
   {"说话人原文": {"name": "显示名", "color": "&HBGR&"}, ...}
   ```
   显示名可用 AI 根据上下文起（如「漫游土豆」「丸子」），不确定就沿用原文。

### 第 4 步 — 生成卡片

**纯卡片版式**（字幕底板在顶部）：
```bash
python "scripts/gen_cards.py" \
  --config "<工作目录>/chapters.json" \
  --theme purple \
  --out "<工作目录>"
```

**视频画面版式**（要点卡 + 真实画面，`--panel` 二选一）：
```bash
python "scripts/gen_cards_video.py" \
  --config "<工作目录>/chapters.json" \
  --theme purple \
  --out "<工作目录>" \
  --panel sub-top
```

产出 `card_01.png` ~ `card_NN.png`（字幕底板 `0~300`，要点卡 `300~820`）。
要点高度由 `fit_points()` 按剩余空间自动推算，改 `points` 条数不会溢出。

**改完上半屏版式必须抽帧验片**（详见关键约定第 16 条），参考验证脚本 `D:\terminal\_verify_cards.py`。

### 第 5 步 — 生成彩色字幕

**纯卡片版式**（字幕落在卡片顶部底板内，**必须显式传 `--align 8`**）：
```bash
python "scripts/gen_subtitle.py" \
  --transcript "<工作目录>/transcript.txt" \
  --speakers "<工作目录>/speakers.json" \
  --corrections "<工作目录>/corrections.json" \
  --duration <TOTAL_DURATION> \
  --align 8 --marginv 240 --fontsize 64 --per-line 14 \
  --out "<工作目录>/subtitle.ass"
```

> ⚠️ `gen_subtitle.py` 的 `align` **默认值是 2（底部）**。纯卡片版式如果只写 `--out` 不传
> `--align 8`，生成的就是底部字幕——历史上一批成片字幕在底部，根子就在这里。
> 别指望默认值，两套版式都显式写 `--align 8`。

**视频画面版式**（字幕贴画面顶部，必须带这组参数）：
```bash
python "scripts/gen_subtitle.py" \
  --transcript "<工作目录>/transcript.txt" \
  --speakers "<工作目录>/speakers.json" \
  --corrections "<工作目录>/corrections.json" \
  --duration <TOTAL_DURATION> \
  --align 8 --marginv 60 --fontsize 54 --per-line 10 \
  --out "<工作目录>/subtitle.ass"
```

产出 `subtitle.ass`（说话人名 + 正文，按色板上色）。参数速查见文末表格。

### 第 6 步 — 合成视频

**纯卡片版式**：
```bash
python "scripts/burn_video.py" \
  --config "<工作目录>/chapters.json" \
  --audio "<原始音频路径>" \
  --subtitle "<工作目录>/subtitle.ass" \
  --out "<工作目录>"
```

**视频画面版式**（`--panel` 必须与第 4 步一致）：
```bash
python "scripts/burn_footage.py" \
  --config "<工作目录>/chapters.json" \
  --video "<原始视频路径>" \
  --subtitle "<工作目录>/subtitle.ass" \
  --out "<工作目录>" \
  --panel sub-top
```

产出 `分视频_XX_标题.mp4`（每章一个）+ `总视频.mp4`（全部拼接，字幕烧录、时长与音频精确对齐）。

### 第 7 步 — 生成视频号文案

分析本次内容的**核心观点**，写一段用于发布视频号的配文，保存为 `<工作目录>/视频号文案.md` 并在对话中展示。

文案要求：
1. **精简、表达清晰**：一句话讲清核心观点，不绕弯。
2. **风格犀利**：观点鲜明、有钩子，能让人想点开看。
3. **篇幅不宜过长**：正文 3~5 句为宜，可配 1~3 个话题标签（`#`）。

结构建议：
- 开头一句钩子（抛出痛点 / 反常识 / 金句）
- 中间 1~2 句点出核心观点
- 结尾一句引导（互动 / 关注）

### 第 8 步 — 生成「收片台」看板

剪完必做。生成一个单文件看板 `收片台.html`，用于验收和归档：上面能直接播片，下面把
每个片段的字幕和摘要摊开，一眼看清"分了几个片段、第几个片段是什么内容"。

```bash
python "scripts/gen_dashboard.py" \
  --chapters   "<工作目录>/chapters.json" \
  --out        "<工作目录>" \
  --transcript "<工作目录>/transcript.txt" \
  --corrections "<工作目录>/corrections.json" \
  --subtitle   "<工作目录>/subtitle.ass"
```

看板结构（自上而下）：

1. **顶部栏** —— 项目名 + 品牌 + 片段数 / 总时长
2. **看片区** —— 播放器通栏占满宽度；**下方一排 chip 是唯一的跳转入口**（当前片段高亮）。
3. **内容明细** —— **只显示当前选中的那一个片段**：`第 N 个片段` + 标签 + 时间码 + 标题
   + 一句话摘要 + 本段要点 + 该片段的字幕原文。切换 chip 时明细跟着换。

**配色**：整页浅色（底 `#f5f6f8`，卡片白底、`rgba(0,0,0,.07)` 描边，正文 `#1e2130`）。
注意主题色要用**饱和深一档**的那套（`#6d5ae6` / `#2f6fed` / `#0ea47a` / `#e8590c`），
不要用为深色底调的高亮色（如 `#2fd3a5`），白底上会发虚。

> ⚠️ 两个别改回去的点：
> 1. **跳转入口只留一处**——历史上有过一份"左侧选片列表"，和 chip 完全重复，已删除。
> 2. **明细只渲染当前片段**——一开始是把 7 个片段全铺出来，页面又长又冗余，用户明确要求
>    跟着选择走。实现上是全部渲染 + 用 `.dcard.on` 控制显隐（比重建 DOM 简单可靠）。

**看板播放的实现（重要：数据外置 + `fetch`→`blob`，别再内联 base64）**：脚本用 ffmpeg 把每个
分视频转成低码率预览（`preview/NN_h720_c30.mp4`，720p / 25fps / CRF30 / 音频 48k 单声道，实测
约 0.6MB/分钟），**预览文件留在磁盘上，HTML 只存相对路径**；播放时由 JS `fetch` 成 blob 再喂
`<video>`。`gen_dashboard.py` 已内置该逻辑，并带 相对路径 → `file://` 绝对路径 两级回退，
末级提示用户改用系统播放器打开原片。

**为什么不再内联 base64（2026-09-25 实测结论）**：内联会把 HTML 顶到 MB 级（7 片段 / 392 秒 →
HTML 5.07MB），预览面板直接**黑屏 `0:00`**——成片本身没问题（h264 + yuv420p + aac + faststart，
`file://` 直开能正常播）。外置后同一批素材的 HTML 只有 ~16KB，立刻能播。
**所以黑屏的主因是页面体积，不是 Range**——别再把"必须内联"当铁律。

**为什么还要 `fetch`→`blob`，而不是直接把相对路径喂 `<video>`**：预览服务（`present_files` 打开的
`http://127.0.0.1:<port>/static-html/<hash>/`）的响应是 `Transfer-Encoding: chunked`、
**无 `Content-Length`、无 `Accept-Ranges`**（带 `Range:` 仍回 200 而非 206）。实测 A/B 对照
（本地 HTTP/1.1 复刻该响应 + 无头 Chrome 量测）：

| 方式 | 起播 | 时长 | seek 到 20s | `seekable.end(0)` |
|------|------|------|-------------|-------------------|
| `fetch`→blob（现行方案） | ✅ `readyState=4` `canplay` | 46.30 | **20.00** ✅ | **46.3** ✅ |
| 相对路径直连 | ✅ 能起播 | 46.30 | **0.00** ❌ | **0.0** ❌ |

直连**能起播但完全拖不动进度条**（`seekable` 为空）——验收时要回看某句台词根本做不到，
所以必须走 blob。

**预览仍然要"瘦"**（单文件 <10MB 的红线没变）：预览面板超过 10MB 直接拒开，用户看到的是
「文件过大，暂不支持在线预览 / 超过 10.0 MB 预览上限」的空白页——比黑屏更糟，因为连页面
都进不去。外置之后 HTML 通常只有几十 KB，红线基本碰不到，但预览转码仍按这个顺序省：

1. **先砍音频码率**——这类视频音频很容易占到一半体积。1080p/CRF30 + 96kbps 单声道，
   392 秒的片子实测 9.3MB，其中音频就 4.7MB。降到 48kbps 直接省一半，人声完全够听。
2. **再砍分辨率**——竖屏素材按高度定：720p 是像素量的 44%，肉眼几乎无损；
   `width:100%` 那套别用，会连高度一起顶上去。
3. **最后才动 CRF / 帧率**。

`build_previews()` 就是按这个思路设计的：整批用同一档参数转码 → 核对总字节 →
超预算就**整批降档重来**（`PREVIEW_LADDER`，720p/CRF30 → 720p/CRF33 → 540p → 540p/CRF36）。
一档一档降是刻意的：同一批视频参数一致，页面里观感才统一。
脚本末尾还有体积闸门，超过 10MB 会打印 ✗ 提示并给出三个减负方向。

> **验证手法（别靠肉眼看截图）**：起一个本地 HTTP 服务 + 无头 Chrome 注入 DIAG 探针，
> `--dump-dom` 后读 `v.readyState` / `v.error` / `v.duration` / `v.seekable.end(0)`。
> 两个必踩的坑：
> 1. **不要用 `--virtual-time-budget` 测媒体**——虚拟时间会瞬间快进定时器，媒体解码拿不到真实
>    时间，`readyState` 恒为 0（**假阴性**，会让你误判方案失败）。改用一张延迟 N 秒返回的
>    `<img>` 把 load 事件拖住，换取真实等待窗口；并且 seek 探针要挂在 `canplay` / `seeked`
>    事件上、必须**在 load 之前**跑完，否则 `--dump-dom` 早已把 DOM 取走，探针白写。
> 2. 自己写模拟服务时**必须设 `protocol_version = "HTTP/1.1"`**：`SimpleHTTPRequestHandler`
>    默认 HTTP/1.0，而 chunked 是 1.1 的特性；用 1.0 发 chunked，Chrome 不会去分块解码，会把
>    `0\r\n\r\n` 这类分块帧头也当正文读进去 → 数据污染 → `err=c4`
>    （`MEDIA_ERR_SRC_NOT_SUPPORTED`），A/B 两组一起假失败，极易误判成"方案不行"。
>
> 3. **在真实预览 URL 上验证时，诊断回传必须用 `fetch`，不能用 Image beacon**：
>    预览服务带 CSP —— `img-src 'self' data: blob: https: ...`（发到 `http://127.0.0.1:<port>` 的
>    图片会被拦，你会收到 0 条报告并误判成"JS 没执行"）；而
>    `connect-src 'self' http://127.0.0.1:* https: ...` **明确放行 fetch 到本地端口**。
>    同源 `fetch('preview/...')` 属于 `'self'`，合规可用——这也是 blob 方案成立的前提。
> 4. **`chrome --headless=new <url>` 不带 action 会立即退出**，页面根本没机会运行（同样收到 0 条）。
>    要让它活着必须加 `--remote-debugging-port=<port>`（配 `--user-data-dir` 临时目录），
>    等待真实时间后再关闭。
>
> 参考脚本：`D:\terminal\_dash_http_test.py`（自建服务 A/B 对照 + seek 检测）、
> `D:\terminal\_probe_real.py`（真实预览 URL 上用 fetch beacon 回传诊断）。
>
> **⚠️ 播放 JS 里不要用 `location.protocol` 做 fetch 门槛**：预览面板可能以 `blob:` / `data:`
> 方式加载本页，一旦跳过 fetch，就只剩相对路径（在该上下文里解析不了）→ 黑屏。
> 正确写法是**总是先试 fetch，失败由 `.catch` 落到直连回退**。
>
> 附：预览服务实测行为（`http://127.0.0.1:<port>/static-html/<hash>/<file>`）——项目目录整体暴露，
> `preview/NN_h720_c30.mp4` 相对路径返回 **200 + `video/mp4` + `Access-Control-Allow-Origin: *`**，
> 字节完整（437721 与本地一致）。所以**路径从来不是问题**，问题只在响应头与页面体积。
> 真实 URL 实测链路：`FETCH 200` → `blob 437721` → `loadedmetadata rs=4 dur=46.30 seekable=46.3`
> → `canplay` → `SEEKED at=20.00`，全程 `err=none`。

**取片来源**：脚本自动在 `--out` 目录里按 `分视频_XX_*` → `seg_sub_XX.mp4` → `_segments/seg_sub_XX.mp4`
的顺序找每个片段。所以 `--total-only` 模式下（分段落在 `_segments/`）也能正常取到。
若都找不到，可显式传 `--video "<源视频路径>"` 兜底。

**摘要来源**：优先读 chapters.json 里该章的 `summary` 字段；没有就回落到 `subtitle`，
再没有就用 `title`。所以**分章时顺手给每章写一句 `summary`**，看板的明细质量会立刻不一样。
摘要与 `title` 完全相同时不重复渲染（历史上出现过标题下面又抄一遍标题的观感问题）。

**字幕原文来源**：优先用 `--subtitle subtitle.ass`（每条都是一小段正文，接近"逐字稿"）；
回落到 `--transcript transcript.txt` 时每条是整段长文，脚本会自动改用它当「摘要」，
并用本章开头那段的摘要填补「摘要」位置。所以**尽量传 `--subtitle`**。

生成后在对话里用 present_files 把 `收片台.html` 打开给用户看。

---

## chapters.json 规范

```json
{
  "project_title": "AI学习路径与方法",
  "brand": "漫游土豆 × 丸子",
  "theme": "purple",
  "chapters": [
    {
      "idx": "01",
      "start": 0.0,
      "end": 31.5,
      "tag": "本期主题",
      "title": "AI 学习路径与方法",
      "subtitle": "漫游土豆 × 丸子 播客对谈",
      "points": ["要点一", "要点二", "要点三", "要点四"],
      "footer": "漫游土豆 × 丸子 · 播客对谈"
    }
  ]
}
```

- `idx`：两位数字符串，顺序编号
- `start`/`end`：该章音频起止秒（float），相邻章首尾相接，最后一章 `end` = 总时长
- `subtitle` 可选；没有就省略
- `summary` **强烈建议写**：一句话摘要，收片台看板的「内容明细」直接用这一句。
  写清"这一段到底在讲什么"，而不是复述标题。

## 关键约定（务必遵守）

1. **转写只用飞书妙记**，禁止 ffmpeg/whisper 本地转写。
2. **章节自动分**：读逐字稿按内容切，不要写死 12 章。
3. **说话人颜色自动分配**：从色板按出现顺序取，不要求用户指定（除非用户主动要求）。
4. **卡片配色每次可选**：默认 `purple`，用户可换。
5. **视频精确对齐**：用「先切音频段 → 每段配图烧字幕 → `-c copy` 拼接」的方案，避免时间漂移。
6. **长段防超时**：x264 用 `-preset veryfast`，单段 ffmpeg timeout 设 600s。
7. **Windows 路径**：喂给 ffmpeg `subtitles` 滤镜的 ass 路径用正斜杠相对路径，避免盘符冒号问题。
8. **字幕落点恒在画面顶部**：卡片上方有深色底板（`subtitle-plate`，0~300），字幕用
   `--align 8 --marginv 60 --fontsize 54 --per-line 10` 落在底板内。字幕在下容易被播放器控件/
   评论区/水印遮挡，这是硬约束，两套版式一致。
9. **视频号文案必生成**：每次完成视频后，分析核心观点，写一段精简犀利、能吸引点击的配文（3~5 句 + 1~3 个标签），见第 7 步。
10. **收片台看板必生成**：每次剪完视频后跑 `gen_dashboard.py`，产出 `收片台.html` 并用 present_files 打开，
    见第 8 步。这是"交付验收"环节，不能省。
11. **只剪某位嘉宾 / 某段内容时**：章节 `start/end` 直接写**源视频绝对秒**（不用从 0 开始），
    `--total-only` 只出总视频；`gen_subtitle.py` 的 `--duration` 仍然传**源视频总时长**
    （字幕是绝对时间戳，传错会导致最后一段字幕被截断）。
12. **先扫说话人再分章**：拿到 transcript 后先用正则统计 `说话人 + 首次出现秒数`，
    一眼定位目标嘉宾的时间区间，再按内容切章，比通读全文快得多。
13. **corrections.json 防重复替换**：`str.replace` 是裸子串替换，
    `["豆包工作","豆包工作伙伴"]` 会把已有的「豆包工作伙伴」变成「豆包工作伙伴伙伴」。
    只写**确实写错的短串**，不要写"正确串的前缀"。
14. **改版式时字幕参数要成组改**：字幕从底部移到顶部，不只是改 `--align`/`--marginv`，
    还要调小 `--per-line`（贴顶时 10 字/行），否则窄边距 + 长行宽会顶满屏幕边缘。
    改完必须抽一帧出来看一眼再交付。
15. **看板视频数据外置 + `fetch`→`blob`（不要内联 base64、也不要直接相对路径喂 `<video>`）**：
    内联 base64 会把 HTML 顶到 MB 级 → 预览面板黑屏 `0:00`（**这才是黑屏主因**）；
    直连相对路径虽能起播，但预览服务响应无 `Content-Length` / 无 `Accept-Ranges`，实测
    `seekable` 为空、**进度条完全拖不动**。所以走 `fetch`→blob，外加 相对路径 → `file://` 回退。
    `gen_dashboard.py` 已内置，别改回去。详见第 8 步。
    排查"文件没问题但页面放不出来"的顺序：① `ffprobe` 看编码 ② 看 HTML 体积（MB 级先瘦身）
    ③ `curl` 看服务响应头 ④ 用 `file://` 直开对比——前后表现不一致就说明是服务端/页面问题，
    不是编码问题。
16. **改上半屏版式后必须抽帧验片**：`overlay=0:840` 会把卡片溢出部分无声无息地盖掉，
    编译不报错、截图不报错，只有抽一帧看才发现「最后一条要点 + footer 被切」。
    验证脚本思路：抽帧后逐行扫 `0~840` 找纯黑行、检查 accent 边框行是否出现在面板下沿、
    检查 `840+` 是否为画面——三项全绿才算过。
17. **看板播放器里竖屏素材按高度定尺寸**：`.vbox video{height:42vh;width:auto}`。
    写成 `width:100%` 时，1080×1920 的视频高度会被顶成宽度的 1.78 倍，超出播放框、左右留黑边。
    `.vbox` 也不要有 `min-height`，否则视频会被撑高的黑框缩成中间一小条。
18. **⚠️ 交付的 HTML 单文件必须 < 10MB**：WorkBuddy 预览面板超过 10MB 直接拒开，
    用户看到的是「文件过大，暂不支持在线预览」的空白页——比黑屏更糟，连页面都进不去。
    收片台要内联视频，所以必须瘦身，顺序是：**先降音频码率**（配音类视频音频常占一半体积，
    96k→48k 直接省一半）→ **再降分辨率**（限高 720）→ 最后才动 CRF/帧率。
    `build_previews()` 已内置整批降档 + 体积闸门，正常一次就过；成片特别长时调小 `--preview-h`。
19. **凡是内联 base64 的交付物，生成后都要报一次实际体积**：这是唯一能在交付前发现
    「10MB 超限」的机会，别等用户截图反馈。
20. **批量重做/重建时，脚本里不要 `os.remove` 临时文件**：本机有批量删除确认钩子
    （`SAFE_DELETE_BULK_CONFIRM_REQUIRED`），后台非交互进程无法确认会被 SIGTERM 终止，
    而且**日志里不留任何报错堆栈**——表现为"进程凭空消失"，极难排查，容易误判成别的原因。
    临时文件留着无害，要清理就单独一趟或交给用户。并行跑多个重做任务时最容易触发。
21. **Chrome 无头截图默认 60s 超时，多任务并行会超时被杀**：`gen_cards.py` 的 `shoot()`
    靠 Chrome 截图，8 路并行抢资源时渲染到后几张卡就 `TimeoutExpired`，同一批任务集体失败。
    做法：超时放大（建议 180s）+ 失败重试 2 次，并**把并行数压到 4 个一批**。
    另外重做脚本务必加 `try/except` 打印真实异常——没有捕获时你只会看到进程消失，看不到原因。
22. **判断字幕位置用"帧间差分法"，不要靠肉眼看截图**：同一段抽两帧 → 转灰度 → 按 20 等分算
    每条带的平均像素变化 → **变化最集中的带就是字幕带**（实测顶部字幕的变化集中在 y96-288）。
    纯"深色像素占比"法会误报，因为卡片版式整屏都是浅色卡片。
    ⚠️ 本机环境下 `Read` 图片会被过滤（返回 `Content filtered`），所以必须让脚本把结论
    **打印成文本**再读，不要指望看图。
23. **改版式后必做两项自检**：① 卡片不溢出（第 16 条的抽帧验片）② 字幕确实在顶部
    （第 22 条的帧间差分）。这两处**都不报错**——编译过、截图也不报错，错了只有看画面才发现，
    属于典型静默失效，跳过去就等着用户截图打脸。
24. **⚠️ `--video` 的时间轴必须与 chapters / ass 完全一致——不一致会「画面全黑」且不报错**：
    只剪某位嘉宾时最省流量的做法是先用 ffmpeg 从源 URL 拉一段（`-ss` + `-t` + `-c copy`），
    再把这段交给 `burn_footage.py`。此时**裁剪片段自身的时长只有片段长度**，
    而 chapters 里写的却是源视频绝对秒（如 3183）→ `-ss 3183` 直接 seek 到片段末尾，
    视频流一帧都没有，表现为**下半屏画面区纯黑**（x264 统计 `skip:99.6%`、码率掉到几十 kb/s），
    但字幕照常显示、ffmpeg 退出码 0，属于典型静默失效。
    两条路二选一，不要混：
    ① **用完整源视频当 `--video`**（推荐，多人剪辑可共用一份 source）：chapters/ass 都用源绝对秒；
    ② 用裁剪片段当 `--video`：chapters 的 `start/end` 和 ass 的时间戳**都要减掉片段起点偏移**。
    拉片段用 `-i URL -ss X -t Y -c copy` 可行（Range 请求，645s 约 32MB / 6 秒）；
    整段下载 1h15m 也就 261MB / 约 30 秒——所以「先拉片段」基本只在带宽受限时才值得。
25. **交付前必查「视频区到底有没有画面」**（第三项自检）：多个时间点抽帧，看下半屏亮度。
    成片正常时 y 900~1800 平均亮度在 130~230 且帧间差分 > 1；
    若恒等于 17.67（`#101018`，卡片自带的 video-area 底色）且方差为 0，
    就是画面层没铺上——按第 24 条查时间轴。
    参考脚本 `D:\terminal\_mona_video_area.py`（结果打印成文本，别指望看图）。
26. **重做视频前先把旧分段改名（`os.rename`），不要用删除**：`burn_footage.py` 会把
    `_segments/seg_sub_XX.mp4` 已存在且 >100KB 的段落整个跳过，改了源视频却不改名，
    跑出来还是上一版的画面；同时第 20 条说了本机删除有确认钩子，改名更安全。
27. **`--video` 用「抽出来的片段」时，必须传 `--origin <片段起点秒>`**：
    `burn_footage.py` 用 `chapters` 的 start/end **直接**当 `-ss` 去切 `--video`。
    如果 `--video` 是从源视频抽出的片段（时间轴从 0 开始，比如只剪某位嘉宾用
    `-ss 2658.7 -t 544` 抽的那段），章节里写源绝对秒就会 seek 到片段末尾以后 →
    **输出帧为 0，画面区全黑**（x264 `skip:99.5%`、码率掉到 70kb/s），
    但字幕/卡片正常、ffmpeg 退出码 0——又一例静默失效。
    传 `--origin 2658.7` 后脚本会自动用 `start-origin` 切视频、用原绝对秒取字幕。
    **自检口诀**：拉一个 6 秒的短输出试试，黑 → 十有八九是时间轴没对齐。

## 剪「某位嘉宾 / 某人一段」的标准做法（多人剪辑时按这个走）

1. **先扫说话人**：正则统计 `说话人 + 首次/末次出现秒`（不要通读全文），
   一眼定位目标嘉宾的区间（主持人串场通常包在首尾，剪进去更完整）。
2. **只拉需要的那一段**：源视频 `minutes +download --url-only` 拿到的 URL **支持 Range**，
   `ffmpeg -ss A -i URL -t (B-A) -c copy` 就能只下这一段的字节。
   ⚠️ **但不要把这段当成 `--video` 去用**——它时间轴从 0 开始，与 chapters 的绝对秒冲突。
3. 两种落地方案，**优先第一种**：
   - **① 直接用完整源 + `--video` 指向整段**（chapters 写绝对秒，无需 `--origin`）。
     完整源下载也就 261MB / 30 秒，多人剪辑还能共用一份，最不容易出错。
   - ② 用抽出的片段 + `--origin <片段起点秒>`。
     只有在「用户明确要求按单个人物拆成独立项目目录」时才值得，
     此时该目录自带 `source.mp4`，但要注意第 27 条。
     ⚠️ 想让片段在自己的时间轴上也能直接抽帧看，就别用 `-c copy` 抽片
     （关键帧间隔实测约 146 秒，`-ss`+`copy` 会把起点对齐到关键帧 → 开头 10~20 秒是静态帧）；
     改用 `-c:v libx264 -crf 20 -r 25 + -c:a copy`（469 秒约 37MB / 1 分钟）。
4. `chapters.json` 的 `start/end` **一律写源视频绝对秒**——这样字幕（也按绝对秒生成）
   与章节天然对齐，两套方案都能用。

## 脚本一览

| 脚本 | 作用 | 输入 | 输出 |
|------|------|------|------|
| `scripts/gen_cards.py` | 生成竖屏卡片（纯卡片版式，字幕底板在顶部） | chapters.json + theme | card_XX.png |
| `scripts/gen_cards_video.py` | 生成「要点卡 + 视频画面」版式卡片（字幕底板在顶部） | chapters.json + theme + `--panel` | card_XX.png |
| `scripts/gen_subtitle.py` | 生成彩色字幕（`--align/--marginv/--fontsize/--per-line` 可调） | transcript.txt + speakers.json + corrections.json | subtitle.ass |
| `scripts/burn_video.py` | 合成视频+烧字幕（纯卡片版式） | chapters.json + 音频 + subtitle.ass | 分视频 + 总视频 |
| `scripts/burn_footage.py` | 合成视频+烧字幕（视频画面版式，含水印；`--origin` 支持片段源） | chapters.json + 视频 + subtitle.ass + `--panel` [+ `--origin`] | 分视频 + 总视频 |
| `scripts/gen_dashboard.py` | **生成「收片台」看板**（预览外置 + `fetch`→`blob` 播放 + 逐片段字幕摘要） | `--chapters` + `--subtitle`（或 `--transcript`）+ `--out` + `--preview-h` | 收片台.html（~几十 KB）+ preview/NN_h720_c30.mp4 |

> `gen_dashboard.py` 的必填参数是 `--chapters`（不是 `--config`），别写错。
> `burn_footage.py` 在 `--total-only` 模式下会在 `_segments/` 和上一级目录里找
> `card_XX.png` / `_wm_*.png`，所以用探针单独试某一段时不需要重新生成卡片。

配色与色板见 [references/color-themes.md](references/color-themes.md)。

## 字幕参数速查

| 版式 | 字幕位置 | `--align` | `--marginv` | `--fontsize` | `--per-line` |
|------|----------|-----------|-------------|--------------|--------------|
| 纯卡片 | 顶部底板内（`top:156`） | **8** | **240** | 64 | 14 |
| 视频画面 | 顶部安全区 | **8** | **60** | **54** | **10** |

> ⚠️ 两套版式都必须是 `--align 8`。纯卡片版式曾长期沿用 `align 2`（底部），与「字幕永远在上」
> 的总原则冲突——历史成片里字幕在底部的就是这么来的。重做老项目时，改 `align` 的同时
> 记得 `marginv` 也要跟着换（从底部 300 → 顶部 240），否则字幕会飘到屏幕外或被卡片压住。

`--align 8` = 顶部居中（`MarginV` 从顶部算起）；`--align 2` = 底部居中（从底部算起）。
