# -*- coding: utf-8 -*-
"""生成竖屏 9:16 播客章节卡片（HTML -> Chrome 无头截图）。

版式：字幕区在上、内容区在下。
- 顶部 96~156px 留空、156~560px 为字幕底板（深色半透明）——字幕永远在画面上方，
  避开底部的播放器控件、评论区、平台水印。
- 章节内容（序号/标签/标题/要点）整体下移，不与字幕底板重叠。

输入：chapters.json（含 project_title/brand/theme/chapters）
输出：card_01.png ~ card_NN.png（1080x1920，含顶部字幕底板）
"""
import subprocess, os, json, argparse, sys

CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"

# 卡片主题：accent 主色 / rgb 用于光晕 / bg_end 背景渐变终点
THEMES = {
    "purple": {"accent": "#6d5ae6", "rgb": (109, 90, 230), "bg_end": "#f3f1fb"},
    "blue":   {"accent": "#2f6fed", "rgb": (47, 111, 237), "bg_end": "#eef4fe"},
    "green":  {"accent": "#0ea47a", "rgb": (14, 164, 122), "bg_end": "#eafaf4"},
    "orange": {"accent": "#e8590c", "rgb": (232, 89, 12),  "bg_end": "#fdeee6"},
}

PLATE_TOP = 156           # 字幕底板起始 y
PLATE_H = 404             # 字幕底板高度

CSS_TEMPLATE = """
* { margin:0; padding:0; box-sizing:border-box; }
html,body { width:1080px; height:1920px; }
body {
  font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
  background: @BG_END@;
  position: relative;
  overflow: hidden;
}
.card {
  position: absolute; inset: 0;
  padding: 620px 96px 100px;
  display: flex; flex-direction: column;
  background: linear-gradient(160deg, #ffffff 0%, @BG_END@ 100%);
}
.top-bar { display:flex; align-items:center; gap:28px; margin-bottom:60px; }
.idx {
  font-size: 56px; font-weight: 800; color: @ACCENT@;
  letter-spacing: 2px;
}
.tag {
  background: @ACCENT@; color:#fff; font-size:40px; font-weight:600;
  padding: 14px 36px; border-radius: 60px; letter-spacing: 2px;
}
.glow {
  position:absolute; top:-200px; right:-200px; width:600px; height:600px;
  background: radial-gradient(circle, rgba(@R@,@G@,@B@,0.18), transparent 70%);
  border-radius:50%;
}
.title {
  font-size: 92px; font-weight: 800; color:#1a1a2e;
  line-height: 1.25; margin-bottom: 40px;
}
.subtitle {
  font-size: 48px; font-weight: 500; color:#8a8aa0; margin-bottom: 70px;
}
.points { display:flex; flex-direction:column; gap: 40px; margin-top:10px; }
.point {
  display:flex; align-items:flex-start; gap: 30px;
  background:#fff; border-radius: 40px; padding: 40px 44px;
  box-shadow: 0 8px 30px rgba(60,50,120,0.06);
}
.dot {
  flex:0 0 24px; width:24px; height:24px; border-radius:50%;
  background:@ACCENT@; margin-top: 22px;
}
.ptext { font-size: 46px; color:#2a2a3e; line-height:1.5; font-weight:500; }
.footer {
  position:absolute; bottom: 80px; left:96px; right:96px;
  font-size: 38px; color:#9a9ab0; letter-spacing:1px;
  display:flex; justify-content:space-between; align-items:center;
}
.brand { color:@ACCENT@; font-weight:600; }
.subtitle-plate {
  position: absolute;
  left: 72px; right: 72px;
  top: @PLATE_TOP@px;
  height: @PLATE_H@px;
  background: rgba(10,10,24,0.55);
  border-radius: 40px;
}
"""


def render_card(card, theme, out_dir, brand):
    th = THEMES.get(theme, THEMES["purple"])
    css = (CSS_TEMPLATE
           .replace("@ACCENT@", th["accent"])
           .replace("@BG_END@", th["bg_end"])
           .replace("@R@", str(th["rgb"][0]))
           .replace("@G@", str(th["rgb"][1]))
           .replace("@B@", str(th["rgb"][2]))
           .replace("@PLATE_TOP@", str(PLATE_TOP))
           .replace("@PLATE_H@", str(PLATE_H)))
    idx = card["idx"]
    pts = "".join(
        f'<div class="point"><div class="dot"></div><div class="ptext">{p}</div></div>'
        for p in card.get("points", [])
    )
    subtitle = f'<div class="subtitle">{card["subtitle"]}</div>' if card.get("subtitle") else ""
    footer = card.get("footer", "")
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{css}</style></head>
<body>
<div class="glow"></div>
<div class="card">
  <div class="top-bar"><div class="idx">{idx}</div><div class="tag">{card['tag']}</div></div>
  <div class="title">{card['title']}</div>
  {subtitle}
  <div class="points">{pts}</div>
  <div class="subtitle-plate"></div>
  <div class="footer"><span>{footer}</span><span class="brand">{brand}</span></div>
</div>
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
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    brand = cfg.get("brand", "")
    chapters = cfg["chapters"]

    for c in chapters:
        hp, pp = render_card(c, args.theme, args.out, brand)
        shoot(hp, pp)
        os.remove(hp)
        print(f"[{c['idx']}/{len(chapters)}] {pp}")
    print("DONE")


if __name__ == "__main__":
    main()
