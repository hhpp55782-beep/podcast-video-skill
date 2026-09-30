# -*- coding: utf-8 -*-
"""「视频画面版式」合成器：真实视频画面 + 章节要点卡 + 烧录彩色字幕。

与 burn_video.py（纯卡片版式）的区别：
- 画面源是真实视频（如飞书妙记录屏），而不是静态卡片 loop
- 版式：**字幕永远在上、画面永远在下**——上半屏 1080x840 放要点卡（字幕烧在其上），
  下半屏 1080x1080 放视频（虚化背景填充两侧）
- 音频直接取原始视频音轨，不做二次转写
- 视频区右下角叠加「丸子的无限进步」水印

输入：
  --config   chapters.json（每章含 idx/start/end/title，start/end 为源视频绝对秒）
  --video    原始视频路径
  --subtitle subtitle.ass（源视频绝对时间戳）
  --out      输出目录（需已存在 card_XX.png）
  --panel    sub-top（默认）/ sub-bottom，与 gen_cards_video.py 保持一致
输出：
  分视频_XX_标题.mp4（每章一个）+ 总视频.mp4
"""
import subprocess, os, json, glob, argparse

W, H = 1080, 1920
PANEL_H = 1080            # 视频区（下半屏）高度
CARD_H = 840              # 要点卡高度 = 上半屏
VIDEO_TOP = H - PANEL_H   # 视频区起始 y = 840，字幕区/要点卡在 0~840
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
WATERMARK_TEXT = "丸子的无限进步"


def ass_time_to_sec(t):
    h, m, s = t.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def sec_to_ass_time(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def load_ass(path):
    header, events = [], []
    with open(path, encoding="utf-8") as f:
        for ln in f.read().splitlines():
            if ln.startswith("Dialogue:"):
                events.append(ln)
            else:
                header.append(ln)
    return header, events


def parse_event(ln):
    parts = ln.split(",")
    return ass_time_to_sec(parts[1]), ass_time_to_sec(parts[2]), ",".join(parts[9:])


def build_seg_ass(header, events, seg_start, seg_end):
    dur = seg_end - seg_start
    body = []
    for ln in events:
        es, ee, text = parse_event(ln)
        if ee <= seg_start or es >= seg_end:
            continue
        ns = max(es - seg_start, 0.0)
        ne = min(ee - seg_start, dur)
        if ne - ns < 0.05:
            continue
        body.append(f"Dialogue: 0,{sec_to_ass_time(ns)},{sec_to_ass_time(ne)},"
                    f"Default,,0,0,0,,{text}")
    return "\n".join(header) + "\n" + "\n".join(body) + "\n"


def safe_name(s, maxlen=14):
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    for ch in "： 、，。":
        s = s.replace(ch, "")
    return (s.replace(" ", "")[:maxlen] or "chapter")


def make_watermark(out_dir, panel):
    """生成 1080x1920 透明水印层，文字压在视频区（下半屏）右下角。"""
    v_top = VIDEO_TOP
    wm_top = v_top + PANEL_H - 78
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>
* {{ margin:0; padding:0; }}
html,body {{ width:{W}px; height:{H}px; background:transparent; }}
.wm {{
  position:absolute; right:36px; top:{wm_top}px;
  font-family:"Microsoft YaHei",sans-serif; font-size:34px; font-weight:700;
  color:rgba(255,255,255,0.66); letter-spacing:3px;
  text-shadow:0 2px 8px rgba(0,0,0,0.6);
}}
</style></head><body><div class="wm">{WATERMARK_TEXT}</div></body></html>"""
    hp = os.path.join(out_dir, f"_wm_{panel}.html")
    pp = os.path.join(out_dir, f"_wm_{panel}.png")
    if os.path.exists(pp):
        return pp                      # 已生成过就复用，避免重复删除临时文件
    with open(hp, "w", encoding="utf-8") as f:
        f.write(html)
    url = "file:///" + hp.replace("\\", "/")
    subprocess.run([
        CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        "--default-background-color=00000000",
        "--force-device-scale-factor=1", f"--window-size={W},{H}",
        f"--screenshot={pp}", url,
    ], check=True, capture_output=True, timeout=60)
    return pp


def build_filter(ass_rel, panel):
    return (
        "[0:v]scale={w}:{p}:force_original_aspect_ratio=increase,"
        "crop={w}:{p},scale=68:68,scale={w}:{p},"
        "eq=saturation=0.45:brightness=-0.10[bg];"
        "[0:v]scale={w}:-2:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2[vp];"
        "[1:v]scale={w}:{h}[card];"
        "[card][vp]overlay=0:{vp_y}[v1];"
        "[v1][2:v]overlay=0:0[v2];"
        "[v2]subtitles={ass},format=yuv420p[v]"
    ).format(w=W, h=H, p=PANEL_H, ass=ass_rel, vp_y=VIDEO_TOP)


def resolve_asset(out_dir, seg_dir, name):
    """卡片/水印优先在 seg_dir 找，找不到回退到 out_dir 与上一级目录。

    这样 `--total-only`（分段落在 _segments/）也能复用项目根目录下已生成的
    card_XX.png / _wm_*.png，不必重复生成。
    """
    for d in (seg_dir, out_dir, os.path.dirname(os.path.abspath(out_dir))):
        p = os.path.join(d, name)
        if os.path.exists(p):
            return p
    return os.path.join(out_dir, name)


def make_segment(cwd_dir, video_abs, card, wm, ass_path, start, dur, seg_path, panel):
    # ⚠️ ass_rel 必须相对「ffmpeg 实际运行的 cwd」计算。
    # 历史 bug：统一用 os.path.relpath(ass_path, args.out) 计算，非 --total-only 时
    # cwd 就是 out 目录（恰好正确），但 --total-only 时 cwd 变成了 out/_segments，
    # 相对路径被解析成 _segments/_segments/seg_01.ass → 文件不存在，ffmpeg 直接失败。
    ass_rel = os.path.relpath(ass_path, cwd_dir).replace("\\", "/")
    # 输入顺序必须与 build_filter 对应：0=视频源 1=章节卡 2=水印层
    cmd = ["ffmpeg", "-y"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", video_abs,
            "-loop", "1", "-t", f"{dur:.3f}", "-i", card,
            "-loop", "1", "-t", f"{dur:.3f}", "-i", wm,
            "-filter_complex", build_filter(ass_rel, panel),
            "-map", "[v]", "-map", "0:a",
            "-t", f"{dur:.3f}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-r", "25", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-movflags", "+faststart",
            seg_path]
    subprocess.run(cmd, check=True, capture_output=True, timeout=1800, cwd=cwd_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--panel", default="sub-top", choices=["sub-top", "sub-bottom"],
                    help="版式，必须与 gen_cards_video.py 传同一个值："
                         "sub-top=要点卡在字幕正下方（默认） / sub-bottom=要点卡夹在字幕与画面之间")
    ap.add_argument("--total-only", action="store_true",
                    help="只输出 总视频.mp4，不生成 分视频_XX_标题.mp4（分段落在 _segments/ 子目录）")
    ap.add_argument("--origin", type=float, default=0.0,
                    help="视频源时间轴相对章节绝对秒的偏移。默认 0（chapters 用源视频绝对秒）；"
                         "当 --video 是从源视频抽出的片段（时间轴从 0 开始）时，传片段起点秒数，"
                         "脚本会用 start-origin 去切视频、用原绝对秒去取字幕")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    chapters = cfg["chapters"]

    seg_dir = args.out
    if args.total_only:
        seg_dir = os.path.join(args.out, "_segments")
        os.makedirs(seg_dir, exist_ok=True)

    header, events = load_ass(args.subtitle)
    video_abs = os.path.abspath(args.video)
    wm = resolve_asset(args.out, seg_dir, f"_wm_{args.panel}.png")
    if not os.path.exists(wm):
        wm = make_watermark(seg_dir, args.panel)

    # ⚠️ 源片段时长短于章节的绝对起点时，`-ss` 会 seek 到末尾（输出 0 帧、画面全黑）。
    # 只剪某位嘉宾时最省流量的做法是先用 ffmpeg 从源 URL 抽一段（时间轴从 0 开始），
    # 此时章节 start/end 必须减去片段起点偏移——由 --origin 显式声明，不要再靠"凑巧正确"。
    # 不传 --origin 时按「chapters 用源视频绝对秒」处理（origin=0），兼容原有用法。
    origin = args.origin

    seg_files = []
    for ch in chapters:
        idx = ch["idx"]
        s, e = float(ch["start"]) - origin, float(ch["end"]) - origin
        dur = e - s
        ass_path = os.path.join(seg_dir, f"seg_{idx}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(build_seg_ass(header, events, s + origin, e + origin))

        card = resolve_asset(args.out, seg_dir, f"card_{idx}.png")
        if not os.path.exists(card):
            raise SystemExit(f"缺少章节卡片：{card}（先跑 gen_cards_video.py）")
        seg_path = os.path.join(seg_dir, f"seg_sub_{idx}.mp4")
        if not (os.path.exists(seg_path) and os.path.getsize(seg_path) > 100000):
            make_segment(seg_dir, video_abs, card, wm, ass_path, s, dur, seg_path, args.panel)
            print(f"[{idx}/{len(chapters)}] done ({dur:.1f}s)", flush=True)
        else:
            print(f"[{idx}/{len(chapters)}] 已存在，跳过", flush=True)
        seg_files.append((idx, ch["title"], seg_path))

    listfile = os.path.join(args.out, "concat_list.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for _, _, p in seg_files:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    total = os.path.join(args.out, "总视频.mp4")
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", listfile, "-c", "copy", "-movflags", "+faststart", total],
                   check=True, capture_output=True, timeout=900)
    print("TOTAL:", total)

    if args.total_only:
        print("TOTAL:", total, "（--total-only：不生成分视频，分段保留在 _segments/）")
        print("ALL DONE")
        return

    # 重命名为中文分视频名；若目标已存在则保留原名，不触发删除
    for idx, title, p in seg_files:
        dst = os.path.join(args.out, f"分视频_{idx}_{safe_name(title)}.mp4")
        if os.path.exists(dst):
            print("已存在，保留：", os.path.basename(dst))
            continue
        try:
            os.rename(p, dst)
            print("分视频 ->", os.path.basename(dst))
        except OSError as ex:
            print("rename failed:", os.path.basename(p), ex)

    print("ALL DONE")


if __name__ == "__main__":
    main()
