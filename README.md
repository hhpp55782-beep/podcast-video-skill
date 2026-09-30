# /podcast-video — 播客视频剪辑器

把一段音频（或飞书妙记）自动剪辑成可发视频号的竖屏 9:16 播客视频。

> 🌿 **丸子的无限进步** · 本技能出自「丸子的无限进步」技能库 — 小红书 / 视频号同名账号

## 它能做什么

输入一段音频文件或一个飞书妙记链接，自动完成：

1. **转录逐字稿** → 自动按内容语义分章节
2. **生成竖屏 PPT 风格卡片**（合成用中间产物）
3. **彩色滚动字幕**（`subtitle.ass`，不同说话人不同颜色）
4. **合成多个分视频 + 1 个总视频**（字幕已烧录）
5. **生成视频号文案**（`视频号文案.md`，犀利吸睛）
6. 产出 **「收片台」看板 `收片台.html`**（验收用：在线看视频 + 看每片段字幕/摘要）

## 使用场景

当用户给音频文件或飞书妙记链接，并说「剪辑 / 做成视频 / 配图 / 加字幕 / 发视频号 / 生成章节卡片 / 写文案」时使用。

## 安装

把本目录整体复制到 WorkBuddy 用户级技能目录：

```bash
# 用户级（所有项目可用）
cp -r podcast-video ~/.workbuddy/skills/podcast-video

# 或项目级
cp -r podcast-video <你的项目>/.workbuddy/skills/podcast-video
```

## 依赖

- Python 3.11+（脚本用标准库 + `moviepy` / `Pillow` / `ass` 相关依赖，按 SKILL.md 指引安装）
- `ffmpeg` 需在 PATH 中
- 转录环节依赖飞书妙记或本地 whisper 等转录能力（详见 SKILL.md）

> ⚠️ 路径占位符：本仓库示例命令中的 `scripts/...` 为相对路径，请以你实际技能安装目录为准。

## 目录结构

```
podcast-video/
├── SKILL.md                       # 技能主文件（完整流程与版式规范）
├── _user_meta.json                # 安装元信息
├── references/
│   └── color-themes.md            # 配色主题说明
└── scripts/
    ├── gen_cards.py               # 纯卡片版式生成
    ├── gen_cards_video.py         # 视频画面版式（要点卡 + 真实画面）
    ├── gen_subtitle.py            # 彩色滚动字幕生成
    ├── burn_video.py              # 字幕烧录到分视频
    ├── burn_footage.py            # 真实画面烧录
    └── gen_dashboard.py           # 收片台看板 HTML 生成
```

## 版式总原则

**字幕永远在上、画面永远在下** —— 字幕落在画面顶部安全区，内容/画面在下方，避免被播放器控件、评论区、平台水印、手机手势条遮挡。详细版式规范见 `SKILL.md`。

## License

个人技能，仅供学习交流。转载请保留「丸子的无限进步」水印。
