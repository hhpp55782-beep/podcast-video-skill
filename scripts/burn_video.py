# -*- coding: utf-8 -*-
"""合成竖屏播客视频：每章切音频 + 配卡片 + 烧字幕 -> 分视频；再拼接总视频。

输入：
  --config   chapters.json（每章含 idx/start/end/title）
  --audio    原始音频路径
  --subtitle subtitle.ass（绝对时间戳 0~总时长）
  --out      输出目录
输出：
  seg_sub_XX.mp4（中间）-> 分视频_XX_标题.mp4
  总视频.mp4
"""
import subprocess, os, json, re, glob, argparse


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
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    header, events = [], []
    for ln in lines:
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
    s = s.replace("：", "").replace(" ", "").replace("、", "").replace("，", "")
    return s[:maxlen] or "chapter"


def cut_audio(audio, out_dir, idx, start, end):
    a = os.path.join(out_dir, f"audio_{idx}.m4a")
    dur = end - start
    cmd = ["ffmpeg", "-y", "-ss", str(start), "-t", str(dur), "-i", audio,
           "-c:a", "aac", "-b:a", "128k", "-ar", "44100", a]
    subprocess.run(cmd, check=True, capture_output=True, timeout=120)
    return a


def make_segment(out_dir, idx, a, ass_path, seg_path):
    card = os.path.join(out_dir, f"card_{idx}.png")
    ass_rel = os.path.relpath(ass_path, out_dir).replace("\\", "/")
    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-i", card,
        "-i", a,
        "-vf", f"subtitles={ass_rel},format=yuv420p",
        "-r", "25",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-tune", "stillimage",
        "-c:a", "copy",
        "-shortest", "-movflags", "+faststart",
        seg_path,
    ]
    subprocess.run(cmd, check=True, capture_output=True, timeout=600, cwd=out_dir)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--audio", required=True)
    ap.add_argument("--subtitle", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = json.load(f)
    chapters = cfg["chapters"]

    for f in glob.glob(os.path.join(args.out, "seg_sub_*.mp4")):
        os.remove(f)
    for f in glob.glob(os.path.join(args.out, "audio_*.m4a")):
        os.remove(f)

    header, events = load_ass(args.subtitle)
    seg_files = []
    for ch in chapters:
        idx = ch["idx"]
        s, e = float(ch["start"]), float(ch["end"])
        ass_path = os.path.join(args.out, f"seg_{idx}.ass")
        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(build_seg_ass(header, events, s, e))

        a = cut_audio(args.audio, args.out, idx, s, e)
        seg_path = os.path.join(args.out, f"seg_sub_{idx}.mp4")
        make_segment(args.out, idx, a, ass_path, seg_path)
        os.remove(a)
        os.remove(ass_path)
        seg_files.append((idx, ch["title"], seg_path))
        print(f"[{idx}/{len(chapters)}] done: seg_sub_{idx}.mp4 ({e - s:.1f}s)", flush=True)

    # 拼接总视频
    listfile = os.path.join(args.out, "concat_list.txt")
    with open(listfile, "w", encoding="utf-8") as f:
        for _, _, p in seg_files:
            f.write(f"file '{p.replace(chr(92), '/')}'\n")
    total = os.path.join(args.out, "总视频.mp4")
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
           "-i", listfile, "-c", "copy", "-movflags", "+faststart", total]
    subprocess.run(cmd, check=True, capture_output=True, timeout=180)
    os.remove(listfile)
    print("TOTAL:", total)

    # 重命名为中文分视频名
    for idx, title, p in seg_files:
        dst = os.path.join(args.out, f"分视频_{idx}_{safe_name(title)}.mp4")
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(p, dst)
        print(f"分视频 -> {os.path.basename(dst)}")

    print("ALL DONE")


if __name__ == "__main__":
    main()
