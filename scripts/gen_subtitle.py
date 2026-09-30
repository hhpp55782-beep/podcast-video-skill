# -*- coding: utf-8 -*-
"""把飞书妙记逐字稿 transcript.txt 转成竖屏段落滚动 ASS 字幕。

输入：
  --transcript  transcript.txt
  --speakers    speakers.json（说话人原文 -> {name, color BGR}）
  --corrections corrections.json（[["错误","正确"],...]，可省略）
  --duration    音频总时长秒
  --out         输出 subtitle.ass
"""
import re, os, json, argparse

PER_LINE = 14              # 正文每行最多字符数
MAX_LINES = 2              # 正文最多行数
MAX_CHARS = PER_LINE * MAX_LINES  # 28
MARGINV = 300              # 字幕底部距画面底边（默认纯卡片版式：落在卡片底部底板内）
FONTSIZE = 64
PLATE_TOP = 52             # 字幕底板在画面上的起始 y（视频画面版式，字幕在上）
PLATE_H = 292              # 字幕底板高度

TS_RE = re.compile(r"^(.+?)\s+(\d{2}:\d{2}:\d{2}\.\d{3})\s*$")
BREAK_PUNCT = "。！？；!?;，、"


def ts_to_sec(ts):
    h, m, s = ts.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)


def sec_to_ass(sec):
    sec = max(0.0, sec)
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def parse_transcript(path, corrections, total_duration):
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    blocks = []
    i = 0
    while i < len(lines):
        if TS_RE.match(lines[i]):
            break
        i += 1
    while i < len(lines):
        m = TS_RE.match(lines[i])
        if not m:
            i += 1
            continue
        speaker = m.group(1).strip()
        start = ts_to_sec(m.group(2))
        i += 1
        content = []
        while i < len(lines):
            if TS_RE.match(lines[i]):
                break
            if lines[i].strip():
                content.append(lines[i].strip())
            i += 1
        text = re.sub(r"\s+", "", "".join(content))
        for wrong, right in corrections:
            text = text.replace(wrong, right)
        if text:
            blocks.append({"speaker": speaker, "start": start, "text": text})
    for idx, b in enumerate(blocks):
        b["end"] = blocks[idx + 1]["start"] if idx + 1 < len(blocks) else total_duration
    return blocks


def split_paragraphs(text, max_chars=MAX_CHARS, min_len=8):
    sentences = re.split(r"(?<=[。！？；!?;])", text)
    sentences = [s.strip() for s in sentences if s.strip()]
    paras = []
    cur = ""
    for s in sentences:
        if not cur:
            cur = s
        elif len(cur) + len(s) <= max_chars:
            cur += s
        else:
            paras.append(cur)
            cur = s
    if cur:
        paras.append(cur)
    final = []
    for p in paras:
        while len(p) > max_chars:
            final.append(p[:max_chars])
            p = p[max_chars:]
        if p:
            final.append(p)
    merged = []
    for p in final:
        if merged and len(p) < min_len and len(merged[-1]) + len(p) <= max_chars:
            merged[-1] += p
        else:
            merged.append(p)
    return merged


def wrap_lines(text, per_line=PER_LINE):
    lines = []
    rest = text
    while len(rest) > per_line:
        cut = per_line
        for idx in range(per_line, max(per_line - 6, 0), -1):
            if rest[idx - 1] in BREAK_PUNCT:
                cut = idx
                break
        if len(rest) - cut <= 2:
            cut = len(rest)
        if cut < len(rest) and rest[cut - 1].isalnum() and rest[cut].isalnum():
            j = cut
            while j > 0 and rest[j - 1].isalnum():
                j -= 1
            if cut - j <= 6:
                cut = j
        lines.append(rest[:cut])
        rest = rest[cut:]
    if rest:
        lines.append(rest)
    return lines[:MAX_LINES] if len(lines) > MAX_LINES else lines


def build_events(blocks, speakers, per_line=PER_LINE):
    events = []
    for b in blocks:
        paras = split_paragraphs(b["text"])
        total_chars = sum(len(p) for p in paras) or 1
        duration = max(0.1, b["end"] - b["start"])
        sp = speakers.get(b["speaker"], {"name": b["speaker"], "color": "&HFFFFFF&"})
        cursor = b["start"]
        for p in paras:
            d = max(0.3, duration * (len(p) / total_chars))
            start = cursor
            end = min(b["end"], cursor + d)
            cursor += d
            # 说话人名单独一行；正文人工折行到 per_line 字宽。
            # per_line 必须跟版式一起调：marginv 大（字幕在下）时可窄，marginv 小
            # （字幕在上、贴近屏幕边缘）时要用小字号 + 窄行宽，否则会顶满屏幕。
            body = "\\N".join(wrap_lines(p, per_line))
            text = (f"{{\\c{sp['color']}\\b1}}{sp['name']}{{\\b0}}\\N"
                    f"{{\\c&HFFFFFF&}}{body}")
            events.append((start, end, text))
    return events


def gen_ass(events, marginv=MARGINV, fontsize=FONTSIZE, align=2):
    # Alignment: 2=底部居中（画面底部安全区） / 8=顶部居中（画面顶部安全区）
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,Microsoft YaHei,{fontsize},&H00FFFFFF,&H00FFFFFF,&H00101010,&H80000000,0,0,0,0,100,100,2,0,1,3,2,{align},60,60,{marginv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = [header]
    for start, end, text in events:
        lines.append(
            f"Dialogue: 0,{sec_to_ass(start)},{sec_to_ass(end)},"
            f"Default,,0,0,0,,{text}"
        )
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--transcript", required=True)
    ap.add_argument("--speakers", required=True)
    ap.add_argument("--corrections", default=None)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--marginv", type=int, default=MARGINV,
                    help="字幕距画面边缘像素。默认 300（纯卡片版式，底部底板内）；"
                         "视频画面版式「字幕在上」时传 60（Alignment=8，距顶部 60px）")
    ap.add_argument("--fontsize", type=int, default=FONTSIZE,
                    help="字幕字号，默认 64；视频画面版式用 54")
    ap.add_argument("--align", type=int, default=2, choices=[2, 8],
                    help="字幕对齐：2=底部居中（纯卡片版式默认） / 8=顶部居中（视频画面版式，字幕在上）")
    ap.add_argument("--per-line", type=int, default=PER_LINE,
                    help=f"正文每行最多字数，默认 {PER_LINE}；字幕贴顶时建议 10")
    args = ap.parse_args()

    with open(args.speakers, encoding="utf-8") as f:
        speakers = json.load(f)
    corrections = []
    if args.corrections and os.path.exists(args.corrections):
        with open(args.corrections, encoding="utf-8") as f:
            corrections = json.load(f)

    blocks = parse_transcript(args.transcript, corrections, args.duration)
    events = build_events(blocks, speakers, args.per_line)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(gen_ass(events, args.marginv, args.fontsize, args.align))
    print(f"解析 {len(blocks)} 段发言 -> {len(events)} 条字幕 "
          f"(align={args.align}, marginv={args.marginv}, per_line={args.per_line}) "
          f"-> {args.out}")


if __name__ == "__main__":
    main()
