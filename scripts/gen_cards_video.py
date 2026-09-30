# -*- coding: utf-8 -*-
"""「视频画面版式」章节卡片：真实视频画面 + 要点卡。

一句话：**字幕永远在上、画面永远在下**。上半屏 0~840 是「字幕底板 + 要点卡」，
下半屏 840~1920 放真实视频画面（`burn_footage.py` 用 overlay=0:840 把画面盖上去）。

⚠️ 硬约束：要点卡必须完整落在 0~840 内。一旦溢出到 840 以下就会被画面盖掉，
表现为「最后一条要点和 footer 被切」。改任何字号/间距前先算预算：
  PANEL_H(520) = padding*2 + top-bar + title + subtitle + points + footer
要点高度由 fit_points() 按剩余空间自动推算，不要手写固定值。

字幕在上是刻意设计：字幕在底部容易被播放器控件、评论区、水印等遮挡。

与 gen_cards.py（纯静态卡片版式）的区别：卡片永远只占 840px，另一半留给真实画面。

输入：chapters.json（含 project_title/brand/theme/chapters）
输出：card_01.png ~ card_NN.png（1080x1920）
"""
import subprocess, os, json, argparse

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

THEMES = {
    "purple": {"accent": "#6d5ae6", "rgb": (109, 90, 230), "bg_end": "#f3f1fb"},
    "blue":   {"accent": "#2f6fed", "rgb": (47, 111, 237), "bg_end": "#eef4fe"},
    "green":  {"accent": "#0ea47a", "rgb": (14, 164, 122), "bg_end": "#eafaf4"},
    "orange": {"accent": "#e8590c", "rgb": (232, 89, 12),  "bg_end": "#fdeee6"},
}

W, H = 1080, 1920

# ── 上半屏（0~840）三段式预算：字幕底板 → 要点卡 → 视频 ────────────────
# burn_footage.py 用 [card][vp]overlay=0:840 把画面盖在上半屏之下，
# 所以卡片内容必须完整落在 0~840 内，否则会被画面吃掉（第 3 条要点/footer 被切）。
VIDEO_TOP = 840           # 视频区（下半屏）起始 y
SUB_TOP = 0               # 字幕底板在画面上的起始 y（永远在顶部）
PLATE_H = 300             # 字幕底板高度（align=8 + marginv=60 + 54px 三行 ≈ 262，留 38 余量）
PLATE_INSET = 40          # 字幕底板左右内缩
VIDEO_SEP = 20            # 字幕底板与视频区之间留的深色缝隙（左下角视觉分隔）
PANEL_TOP = PLATE_H       # 320 -> 300：要点卡紧贴字幕底板下沿
PANEL_H = VIDEO_TOP - VIDEO_SEP - PANEL_TOP   # 840 - 20 - 300 = 520
PANEL_BOT = PANEL_TOP + PANEL_H               # 820，下方 20px 深色缝隙与视频区相接

PAD_V = 26                # 要点卡上下内边距
PAD_H = 80                # 要点卡左右内边距

# panel -> (视频区 top, 要点卡 top)
# 字幕在上、画面在下是硬约束，两种取值版式一致；sub-bottom 为历史别名（已废弃）
PANEL_POS = {"sub-top": (VIDEO_TOP, PANEL_TOP), "sub-bottom": (VIDEO_TOP, PANEL_TOP)}
PLATE_EDGE = "bottom"     # 要点卡 accent 边框只画在其与视频区相接的下沿

CSS_TEMPLATE = """
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:1080px; height:1920px; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  background: #101018; position: relative; overflow: hidden;
}
.video-area {
  position:absolute; left:0; top:@V_TOP@px; width:1080px; height:1080px;
  background:#101018;
}
.panel {
  position:absolute; left:0; top:@P_TOP@px; width:1080px; height:@PANEL_H@px;
  padding: @PAD_V@px @PAD_H@px @PAD_V@px;
  background: linear-gradient(160deg, #ffffff 0%, @BG_END@ 100%);
  display:flex; flex-direction:column; overflow:hidden;
}
.sep {
  position:absolute; left:0; top:@PANEL_BOT@px; width:1080px; height:@VIDEO_SEP@px;
  background:#101018;
}
.panel::after {
  content:""; position:absolute; left:0; bottom:0; width:100%; height:6px;
  background:@ACCENT@;
}
.top-bar { display:flex; align-items:center; gap:22px; height:44px; flex:0 0 auto; }
.idx { font-size:36px; font-weight:800; color:@ACCENT@; letter-spacing:2px; }
.tag {
  background:@ACCENT@; color:#fff; font-size:26px; font-weight:600;
  padding:5px 22px; border-radius:40px; letter-spacing:2px;
  max-width:520px; white-space:nowrap; overflow:hidden;
}
.wm { margin-left:auto; font-size:26px; font-weight:700; color:@ACCENT@;
      opacity:0.75; letter-spacing:3px; white-space:nowrap; }
.title {
  font-size:46px; font-weight:800; color:#1a1a2e; line-height:1.22;
  margin-top:14px; max-height:114px; overflow:hidden; flex:0 0 auto;
}
.subtitle {
  font-size:30px; font-weight:500; color:#7a7a92; line-height:1.2;
  margin-top:6px; max-height:38px; overflow:hidden; flex:0 0 auto;
}
.points {
  flex:1 1 auto; min-height:0; margin-top:12px;
  display:flex; flex-direction:column;
  gap:@PGAP@px; justify-content:center; overflow:hidden;
}
.point {
  display:flex; align-items:center; gap:18px; min-height:@PH@px;
  background:#fff; border-radius:24px; padding:0 28px;
  box-shadow: 0 6px 22px rgba(60,50,120,0.07);
}
.dot { flex:0 0 18px; width:18px; height:18px; border-radius:50%; background:@ACCENT@; }
.ptext { font-size:@PFONT@px; color:#2a2a3e; font-weight:500; white-space:nowrap; }
.footer {
  flex:0 0 auto; margin-top:10px; height:32px; font-size:27px; color:#9a9ab0;
  display:flex; justify-content:space-between; align-items:center;
}
.brand { color:@ACCENT@; font-weight:600; }
.glow {
  position:absolute; top:@GLOW_TOP@px; right:-160px; width:520px; height:520px;
  background: radial-gradient(circle, rgba(@R@,@G@,@B@,0.16), transparent 70%);
  border-radius:50%;
}
.subtitle-plate {
  position:absolute; left:@PLATE_INSET@px; right:@PLATE_INSET@px;
  top:@PLATE_TOP@px; height:@PLATE_H@px;
  background: rgba(14,14,26,0.88); border-radius:36px;
  z-index:5;
}
"""


def fit_points(n):
    """按上半屏剩余高度推算每条要点的高度/字号，保证 footer 不被画面切掉。"""
    n = max(1, n)
    # 固定占用：padding*2 + top-bar 44 + title(14+114) + subtitle(6+38)
    #            + points margin-top 12 + footer(10+32)
    fixed = PAD_V * 2 + 44 + (14 + 114) + (6 + 38) + 12 + (10 + 32)
    slot = PANEL_H - fixed
    gap = 10
    ph = (slot - gap * (n - 1)) // n
    ph = max(44, min(72, int(ph)))
    pfont = max(26, min(34, int(ph * 0.58)))
    return ph, pfont, gap


def render_card(card, theme, out_dir, brand, panel):
    th = THEMES.get(theme, THEMES["purple"])
    v_top, p_top = PANEL_POS[panel]
    ph, pfont, pgap = fit_points(len(card.get("points", [])))
    css = (CSS_TEMPLATE
           .replace("@ACCENT@", th["accent"])
           .replace("@BG_END@", th["bg_end"])
           .replace("@R@", str(th["rgb"][0]))
           .replace("@G@", str(th["rgb"][1]))
           .replace("@B@", str(th["rgb"][2]))
           .replace("@V_TOP@", str(v_top))
           .replace("@P_TOP@", str(p_top))
           .replace("@PANEL_H@", str(PANEL_H))
           .replace("@PAD_V@", str(PAD_V))
           .replace("@PAD_H@", str(PAD_H))
           .replace("@PH@", str(ph))
           .replace("@PFONT@", str(pfont))
           .replace("@PGAP@", str(pgap))
           .replace("@PANEL_BOT@", str(PANEL_BOT))
           .replace("@VIDEO_SEP@", str(VIDEO_SEP))
           .replace("@EDGE@", PLATE_EDGE)
           .replace("@PLATE_TOP@", str(SUB_TOP))
           .replace("@PLATE_H@", str(PLATE_H))
           .replace("@PLATE_INSET@", str(PLATE_INSET))
           .replace("@GLOW_TOP@", str(p_top + 40)))
    idx = card["idx"]
    pts = "".join(
        f'<div class="point"><div class="dot"></div><div class="ptext">{p}</div></div>'
        for p in card.get("points", [])
    )
    sub = (f'<div class="subtitle">{card["subtitle"]}</div>'
           if card.get("subtitle") else "")
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="video-area"></div>
<div class="glow"></div>
<div class="panel">
  <div class="top-bar">
    <div class="idx">{idx}</div><div class="tag">{card['tag']}</div>
    <div class="wm">丸子的无限进步</div>
  </div>
  <div class="title">{card['title']}</div>
  {sub}
  <div class="points">{pts}</div>
  <div class="footer"><span>{card.get('footer', '')}</span><span class="brand">{brand}</span></div>
</div>
<div class="sep"></div>
<div class="subtitle-plate"></div>
</body></html>"""
    html_path = os.path.join(out_dir, f"card_{idx}.html")
    png_path = os.path.join(out_dir, f"card_{idx}.png")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path, png_path


def shoot(html_path, png_path):
    url = "file:///" + html_path.replace("\\", "/")
    subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", "--window-size=1080,1920",
        f"--screenshot={png_path}", url,
    ], check=True, capture_output=True, timeout=60)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--theme", default="purple")
    ap.add_argument("--out", required=True)
    ap.add_argument("--panel", default="sub-top", choices=["sub-top", "sub-bottom"],
                    help="版式（保留兼容）。「字幕在上、画面在下」是硬约束，"
                         "sub-bottom 为历史别名，渲染结果与 sub-top 一致")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    chapters = cfg["chapters"]

    for c in chapters:
        hp, pp = render_card(c, args.theme, args.out, cfg.get("brand", ""), args.panel)
        shoot(hp, pp)
        os.remove(hp)
        print(f"[{c['idx']}/{len(chapters)}] {pp}")
    print("DONE")


if __name__ == "__main__":
    main()
