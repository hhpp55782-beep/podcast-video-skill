# -*- coding: utf-8 -*-
"""生成「收片台」看板 —— 剪完片子的验收 / 归档页面。

版式（自上而下）：
  1. 顶部栏：项目名 + 品牌 + 章节数 / 总时长 三块信息
  2. 播放区：左边选片列表（每个片段一张卡），右边内嵌 <video> 播放器
  3. 内容明细：逐片段列出 序号 / 时间码 / 标签 / 标题 / 一句话摘要 / 要点 / 字幕原文
     —— 「第一个片段、第二个片段分别是什么内容」一眼看完

为了「看板内直接播放」（用户明确要的方式），脚本会顺带用 ffmpeg 生成低码率预览版
（`preview/*.mp4`，720p / 音频 48k，约 0.6MB/分钟），**以外部文件引用**的方式接入播放器
（不再 base64 内联 —— 见下方说明）。预览文件体积仍要"瘦"：竖向限高 720、音频降到 48kbps
单声道（配音类视频里音频很容易占到一半体积）。`build_previews()` 会整批转码后核对总字节，
超预算就自动降档重来。

⚠️ 为什么不能用 base64 内联、也不能直接相对路径喂 `<video>`：
WorkBuddy 的静态预览服务（present_files 打开 HTML 时用的
`http://127.0.0.1:<port>/static-html/<hash>/`）**不支持 HTTP Range 请求**——发 Range 拿回来的是
`200`（不是 `206`）、无 `Accept-Ranges`、无 `Content-Length`。直接把相对路径喂 `<video>` 时，
Chrome 拿不到字节范围就定不了时长、渲染不出首帧，页面表现是**播放器显示 `0:00` + 画面全黑**
（文件本身没问题，`file://` 直开能正常播）。
历史方案是 base64 内联绕开服务端读取，但 **HTML 一旦到 ~5MB 量级，预览面板仍可能黑屏 0:00**
（且内联会把页面顶到 10MB 上限外）。

✅ 当前方案：视频**数据外置**（`preview/*.mp4` 留在磁盘，HTML 只存相对路径），播放时 JS 用
`fetch(preview_rel)` 读成 blob 再喂 `<video>`，完全绕开 Range 限制；再按
相对路径 → `file://` 绝对路径 两级回退（末级提示用户用系统播放器开原片）。
实测（无头 Chrome `readyState=4`、`err=none`、时长读完）确认可行。HTML 因此只有几十 KB，
体积闸门基本不会触发。

输入：
  --chapters    chapters.json
  --out         输出目录（成品目录，同时产出 收片台.html）
  --transcript  transcript.txt（可选，用于"内容明细"里的字幕原文）
  --corrections corrections.json（可选）
  --subtitle    subtitle.ass（可选，用于按片段切字幕；比 transcript 更贴近成片）
  --preview-h   预览画面高度上限（默认 720，越小文件越小）
  --no-preview  跳过 ffmpeg 预览转码（页面里的视频将不可播，仅作占位）
输出：
  <out>/收片台.html（自包含，含内联视频，必须 <10MB）
  <out>/preview/NN_h720_c30.mp4 ...（内联用的低码率预览，非 --no-preview 时生成）
"""
import os, re, json, html, argparse, subprocess, shutil

PREVIEW_PRESET = "veryfast"

# ⚠️ WorkBuddy 预览面板单文件硬上限 10MB：超了直接显示「文件过大，暂不支持在线预览」。
# 内联 base64 会膨胀 4/3，所以所有预览的**原始字节之和**必须压在这个预算内。
HTML_MAX = 10 * 1024 * 1024
RAW_BUDGET = int(6.2 * 1024 * 1024)   # 原始视频字节预算（×4/3 ≈ 8.3MB + 正文，安全落在 10MB 内）

# 降档阶梯：(画面高度, 帧率, CRF, 音频码率kbps)
# 竖屏素材只限高度。配音才是这类视频的主体，所以音频码率给得比 96k 低一档——省得音频占掉一半体积。
PREVIEW_LADDER = [
    (720, 25, 30, 48),    # 首选：720x1280，肉眼几乎无损，体积约 1080p 的 45%
    (720, 25, 33, 40),
    (540, 20, 34, 32),
    (540, 20, 36, 32),    # 兜底：再不够就只能更狠地压
]


# ---------- 基础工具 ----------

def hhmmss(sec):
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:04.1f}" if h else f"{m:02d}:{s:04.1f}"


def dur_text(sec):
    sec = max(0, int(round(float(sec))))
    m, s = divmod(sec, 60)
    return f"{m} 分 {s:02d} 秒" if m else f"{s} 秒"


def esc(s):
    return html.escape(str(s or ""), quote=True)


def head_tail(text, head=180, tail=80):
    """字幕原文太长时掐头留尾，中间用省略号。"""
    t = re.sub(r"\s+", " ", (text or "")).strip()
    if len(t) <= head + tail + 3:
        return t
    return t[:head] + "……" + t[-tail:]


def safe_name(s):
    for ch in '\\/:*?"<>|':
        s = s.replace(ch, "_")
    return re.sub(r"\s+", "", s)[:60] or "seg"


# ---------- 字幕解析（subtitle.ass 优先，回落到 transcript.txt）----------

def load_ass_events(path):
    """返回 [(start_sec, end_sec, plain_text), ...]"""
    out = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if not ln.startswith("Dialogue:"):
                continue
            parts = ln.split(",")
            if len(parts) < 10:
                continue
            try:
                st = sum(x * y for x, y in zip(
                    [3600, 60, 1], [float(v) for v in parts[1].split(":")]))
                en = sum(x * y for x, y in zip(
                    [3600, 60, 1], [float(v) for v in parts[2].split(":")]))
            except ValueError:
                continue
            body = ",".join(parts[9:])
            body = re.sub(r"\{[^}]*\}", "", body)      # 去掉 {\c&H..&} 等样式覆盖
            body = body.replace("\\N", "\n").replace("\\n", "\n")
            body = "\n".join(l for l in body.split("\n") if l.strip())
            if body.strip():
                out.append((st, en, body.strip()))
    return out


TS_RE = re.compile(r"^(.+?)\s+(\d{2}:\d{2}:\d{2}\.\d{3})\s*$")


def load_transcript_blocks(path):
    """返回 [(start_sec, text), ...]，text 里首行是说话人名。"""
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    blocks, i = [], 0
    while i < len(lines):
        m = TS_RE.match(lines[i])
        if not m:
            i += 1
            continue
        sp = m.group(1).strip()
        h, mi, s = m.group(2).split(":")
        st = int(h) * 3600 + int(mi) * 60 + float(s)
        i += 1
        buf = []
        while i < len(lines) and not TS_RE.match(lines[i]):
            if lines[i].strip():
                buf.append(lines[i].strip())
            i += 1
        txt = re.sub(r"\s+", "", "".join(buf))
        if txt:
            blocks.append((st, f"{sp}\n{txt}"))
    return blocks


def apply_corrections(text, corrections):
    for wrong, right in corrections:
        text = text.replace(wrong, right)
    return text


def is_subtitle(items):
    """判断 items 是否来自 subtitle.ass（含简短说话人名）还是 transcript.txt（整段长文）。

    ass 的每条 Dialogue 都是一小段正文，取出来接近「字幕原文」；
    transcript 的每条是整段发言（几百字），更适合当「摘要」而不是逐字稿。
    """
    if not items:
        return False
    n = min(12, len(items))
    avg = sum(len(tx) for _, tx in items[:n]) / n
    return avg < 60


def clip_text(items, start, end, corrections):
    """取出落在 [start,end) 内、按时间排序的文本。"""
    picked = [(t, tx) for t, tx in items if start <= t < end]
    picked.sort(key=lambda x: x[0])
    joined = "\n".join(tx for _, tx in picked)
    return apply_corrections(joined, corrections)


# ---------- 预览转码 ----------

def ffmpeg_bin():
    return shutil.which("ffmpeg") or "ffmpeg"


def make_preview(src, dst, h=720, fps=25, crf=30, abr=48):
    """生成低码率预览（限高度），供页面内嵌播放。同名已存在则跳过（缓存）。"""
    if os.path.exists(dst) and os.path.getsize(dst) > 20000:
        return dst
    cmd = [ffmpeg_bin(), "-y", "-i", src,
           "-vf", f"scale=-2:{h}",
           "-r", str(fps),
           "-c:v", "libx264", "-preset", PREVIEW_PRESET, "-crf", str(crf),
           "-profile:v", "main", "-pix_fmt", "yuv420p",
           "-c:a", "aac", "-b:a", f"{abr}k", "-ac", "1",
           "-movflags", "+faststart", dst]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=1800)
        return dst
    except Exception as ex:
        print("  ! 预览转码失败：", os.path.basename(src), ex)
        return None


def build_previews(tasks, prev_dir, budget=RAW_BUDGET):
    """批量转码预览，并保证总原始体积落进预算（否则 HTML 会超过 10MB 打不开）。

    做法是「整批降档重试」而不是逐个降档：同一批视频用同一档参数，页面内观感才一致。
    首档是 720p/CRF30，正常 6~8 分钟的播客跑下来约 4~5MB，一次就过。
    """
    os.makedirs(prev_dir, exist_ok=True)
    last = None
    for rung, (h, fps, crf, abr) in enumerate(PREVIEW_LADDER, 1):
        outs, total = {}, 0
        for idx, src in tasks:
            dst = os.path.join(prev_dir, f"{idx}_h{h}_c{crf}.mp4")
            got = make_preview(src, dst, h, fps, crf, abr)
            if got:
                outs[idx] = got
                total += os.path.getsize(got)
        print(f"  预览档位 {rung}/{len(PREVIEW_LADDER)}：{h}p / {fps}fps / CRF{crf}"
              f" / 音频{abr}k → 合计 {total / 1048576:.2f}MB（预算 {budget / 1048576:.1f}MB）")
        last = (outs, (h, fps, crf, abr))
        if total <= budget:
            # 清掉其它档位残留，preview/ 里只留当前这一档
            keep = {os.path.basename(p) for p in outs.values()}
            for fn in os.listdir(prev_dir):
                if fn.endswith(".mp4") and fn not in keep:
                    try:
                        os.remove(os.path.join(prev_dir, fn))
                    except OSError:
                        pass
            return last
        for p in outs.values():      # 超预算 → 丢本档产物，降档重来
            try:
                os.remove(p)
            except OSError:
                pass
    return last


# ---------- 页面 ----------

CSS = """
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:"Microsoft YaHei","PingFang SC",sans-serif;background:#f5f6f8;color:#1e2130;
     -webkit-font-smoothing:antialiased}
.wrap{max-width:1560px;margin:0 auto;padding:34px 40px 80px}
.topbar{display:flex;align-items:flex-start;gap:28px;flex-wrap:wrap;
        border-bottom:1px solid rgba(0,0,0,.08);padding-bottom:24px}
.brandline{font-size:15px;color:#8a90a2;letter-spacing:2px}
.project{font-size:36px;font-weight:800;letter-spacing:1px;margin-top:6px;line-height:1.25;
         color:#12141f}
.stats{margin-left:auto;display:flex;gap:14px;flex-wrap:wrap}
.stat{background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:16px;
      padding:14px 24px;min-width:132px}
.stat .k{font-size:14px;color:#8a90a2;letter-spacing:1px}
.stat .v{font-size:28px;font-weight:800;margin-top:6px;color:@ACCENT@}
.stage{margin-top:30px}
.stage h2,.detail h2{font-size:17px;font-weight:700;color:#5b6377;letter-spacing:2px;
                     padding:6px 10px 14px}
.player{background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:22px;
        padding:20px;display:flex;flex-direction:column;min-width:0}
.ptitle{font-size:24px;font-weight:700;line-height:1.35;margin-bottom:6px;color:#12141f}
.pmeta{font-size:15px;color:#8a90a2;margin-bottom:16px;display:flex;gap:16px;flex-wrap:wrap}
.pmeta b{color:@ACCENT@;font-weight:600}
/* vbox 只做居中容器，不再给 min-height —— 否则会把黑框撑高、视频缩成中间一小条 */
.vbox{flex:1 1 auto;background:#000;border-radius:16px;overflow:hidden;
      display:flex;align-items:center;justify-content:center;min-height:0}
/* 竖屏 9:16 素材：按「高度上限」定尺寸，否则宽度撑满会把高度顶到 1.78 倍、左右留黑边。 */
.vbox video{height:42vh;max-height:620px;width:auto;max-width:100%;display:block;background:#000}
.tippath{font-size:13px;color:#9aa0b0;margin-top:12px;word-break:break-all;line-height:1.7}
.plist{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px}
.pchip{font-size:15px;color:#5b6377;background:#f2f3f6;border:1px solid rgba(0,0,0,.07);
       border-radius:999px;padding:9px 18px;cursor:pointer;transition:.15s}
.pchip:hover{border-color:@ACCENT@;color:@ACCENT@}
.pchip.on{background:@ACCENT@;border-color:@ACCENT@;color:#fff;font-weight:600}
.detail{margin-top:44px}
.dcard{background:#fff;border:1px solid rgba(0,0,0,.07);border-radius:22px;
       padding:26px 30px;display:none}
.dcard.on{display:block}
.dhead{display:flex;align-items:center;gap:16px;flex-wrap:wrap}
.dno{font-size:26px;font-weight:800;color:@ACCENT@;letter-spacing:1px}
.dtag{font-size:15px;background:@ACCENT@;color:#fff;border-radius:999px;padding:5px 16px}
.dtime{font-size:15px;color:#8a90a2;margin-left:auto}
.dtitle{font-size:27px;font-weight:700;margin-top:14px;line-height:1.35;color:#12141f}
.dsum{font-size:19px;color:#4a5165;margin-top:10px;line-height:1.65}
.dsec{font-size:14px;color:#8a90a2;letter-spacing:2px;margin:20px 0 10px}
.dpoints{display:flex;gap:12px;flex-wrap:wrap;list-style:none}
.dpoints li{font-size:16px;color:#3a4155;background:#f2f3f6;border-radius:12px;
            padding:9px 16px;border:1px solid rgba(0,0,0,.05)}
.quote{font-size:16px;color:#4a5165;line-height:1.85;background:#f7f8fa;border-radius:14px;
       padding:16px 20px;border-left:4px solid @ACCENT@;white-space:pre-wrap;word-break:break-word}
.foot{margin-top:40px;text-align:center;font-size:14px;color:#a8aebc;letter-spacing:3px}
/* 水印双保险：页脚一行 + 右下角常驻（用户要求所有成果带「丸子的无限进步」）。
   常驻水印做成**不透明白底胶囊**：半透明时下层文字会透出来显得脏；
   不透明白底反而像有意贴上的品牌标。（它盖住的是当前片段的时间码，播放器上方已有同值。） */
.wmark{position:fixed;right:14px;bottom:12px;z-index:9999;pointer-events:none;
       font-size:12px;font-weight:700;letter-spacing:2px;color:@ACCENT@;
       background:#fff;border:1px solid rgba(0,0,0,.08);
       box-shadow:0 2px 10px rgba(0,0,0,.07);
       border-radius:999px;padding:5px 13px}
@media print{.wmark{position:absolute}}
"""

JS = """
var D = window.__RECV__ || {segs:[]};
var ABS_DIR = __ABS_DIR__;          // 注入的项目绝对目录（file:// 兜底用）
function setTip(t){
  var e = document.getElementById('modetip');
  if(!e){
    e = document.createElement('div'); e.id = 'modetip';
    e.style.cssText = 'font-size:12px;color:#9aa0b0;margin-top:6px';
    var pp = document.getElementById('ppath');
    if(pp && pp.parentNode) pp.parentNode.insertBefore(e, pp.nextSibling);
  }
  e.textContent = t;
}
function showTip(s){
  var box = document.getElementById('vbox');
  var d = document.getElementById('vtip');
  if(!d){
    d = document.createElement('div'); d.id = 'vtip';
    d.style.cssText = 'margin-top:12px;background:#FFF4E5;border:1px solid #F5C98A;color:#8a5a00;'
      + 'border-radius:14px;padding:14px 18px;font-size:14px;line-height:1.7';
    if(box && box.parentNode) box.parentNode.insertBefore(d, box.nextSibling);
  }
  d.innerHTML = '⚠️ 播放器无法加载该片段。请直接用系统播放器打开原片：<br><b>' + (s.video_rel || '') + '</b>';
}
function play(i){
  var s = D.segs[i]; if(!s) return;
  var v = document.getElementById('v');
  document.querySelectorAll('.pchip').forEach(function(el){
    el.classList.toggle('on', el.dataset.i === String(i));
  });
  document.querySelectorAll('.dcard').forEach(function(el){
    el.classList.toggle('on', el.dataset.i === String(i));
  });
  var dh = document.getElementById('dhead');
  if(dh) dh.textContent = '内容明细 · 第 ' + (i+1) + ' 个片段（共 ' + D.segs.length + ' 个）';
  document.getElementById('ptitle').textContent = s.idx + ' · ' + s.title;
  document.getElementById('pmeta').innerHTML =
    '<span>时间码 <b>' + s.tc + '</b></span><span>时长 <b>' + s.dur + '</b></span>' +
    '<span>标签 <b>' + s.tag + '</b></span>';
  var pp = document.getElementById('ppath');
  if(s.preview_rel){
    // 附一个下载入口：万一播放器仍加载不了，用户至少能拿到文件用系统播放器看
    pp.innerHTML = '📁 预览：' + s.preview_rel + '（约 ' + s.preview_mb + 'MB） · 原片：' + s.video_rel
      + ' · <a href="' + s.preview_rel + '" download style="font-weight:600">下载本段</a>';
  } else {
    pp.textContent = '⚠️ 未生成预览，原片路径：' + s.video_rel;
  }
  if(s.preview_rel){
    v.style.display = 'block';
    v.onerror = null;
    // 回退链：相对路径直连 → file:// 绝对路径
    var cands = [s.preview_rel,
                 'file:///' + ABS_DIR.replace(/\\\\/g, '/') + '/' + s.preview_rel];
    var ci = 0;
    function fallback(){
      if(ci < cands.length){ v.src = cands[ci++]; v.load(); setTip('回退直连 ' + ci + '/' + cands.length); }
      else { showTip(s); }
    }
    // 首选 fetch→blob：完全绕开预览服务不支持 HTTP Range 的问题（直连 <video> 拖不动进度条）。
    // ⚠️ 不要用 location.protocol 做门槛：预览面板可能以 blob:/data: 方式加载本页，
    // 一旦跳过就只剩相对路径（在该上下文里解析不了）→ 黑屏。让 fetch 自己失败再回退更稳。
    if(window.fetch){
      setTip('正在读取片段…');
      fetch(s.preview_rel, {cache:'no-store'}).then(function(r){
        if(!r.ok) throw new Error('HTTP ' + r.status);
        return r.blob();
      }).then(function(b){
        if(v._u) URL.revokeObjectURL(v._u);
        v._u = URL.createObjectURL(b);
        v.src = v._u; v.load();
        setTip('blob 模式 · ' + (b.size/1048576).toFixed(2) + 'MB');
      }).catch(function(e){
        console.warn('blob 失败，回退直连：', e);
        fallback();
      });
    } else {
      fallback();
    }
  } else {
    v.style.display = 'none';
    var box = document.getElementById('vbox');
    box.innerHTML = '<div style="color:#7f8aa3;font-size:16px;padding:60px 20px;text-align:center">'
      + '该片段未生成预览<br><span style="font-size:13px">'
      + '去掉 --no-preview 重跑 gen_dashboard.py 即可内嵌播放</span></div>';
  }
}
window.addEventListener('DOMContentLoaded', function(){ play(0); });
"""


def render_page(segs, meta, accent, abs_dir=""):
    """abs_dir：项目绝对目录（正斜杠），注入 JS 供 file:// 兜底拼接绝对路径。"""
    times = [s["end"] for s in segs]
    total = max(times) if times else 0
    # 唯一的片段跳转入口：播放器下方一排 chip（曾有一份重复的左侧选片列表，已去掉）
    chips = "".join(
        f'<span class="pchip" data-i="{i}" onclick="play({i})">'
        f'{s["idx"]} · {esc(head_tail(s["title"], 16, 0))}</span>'
        for i, s in enumerate(segs)
    )
    # 内容明细：全部片段都渲染出来，但只显示当前选中的那个（.on 由 JS 切）
    cards = ""
    for i, s in enumerate(segs):
        pts = "".join(f"<li>{esc(p)}</li>" for p in s["points"])
        pts_html = f'<div class="dsec">本段要点</div><ul class="dpoints">{pts}</ul>' if pts else ""
        quote = s["quote"] or "（本段未解析到字幕）"
        # 摘要与标题重复时不重复渲染（chapters.json 里 summary 常常就抄了 subtitle）
        sum_html = (f'<div class="dsum">{esc(s["summary"])}</div>'
                    if s["summary"] and s["summary"] != s["title"] else "")
        cards += f"""<div class="dcard" data-i="{i}">
  <div class="dhead"><span class="dno">第 {i + 1} 个片段</span>
    <span class="dtag">{esc(s['tag'])}</span>
    <span class="dtime">{s['tc']} · 时长 {s['dur']}</span></div>
  <div class="dtitle">{esc(s['title'])}</div>
  {sum_html}
  {pts_html}
  <div class="dsec">字幕原文（第 {i + 1} 个片段）</div>
  <div class="quote">{esc(quote)}</div>
</div>"""
    n = len(segs)
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>收片台 · {esc(meta['project_title'])}</title>
<style>{CSS.replace('@ACCENT@', accent)}</style></head>
<body>
<div class="wrap">
  <div class="topbar">
    <div>
      <div class="brandline">收片台 · 丸子的无限进步</div>
      <div class="project">{esc(meta['project_title'])}</div>
    </div>
    <div class="stats">
      <div class="stat"><div class="k">片段数</div><div class="v">{n}</div></div>
      <div class="stat"><div class="k">总时长</div><div class="v">{dur_text(total)}</div></div>
      <div class="stat"><div class="k">品牌</div><div class="v" style="font-size:19px">
        {esc(meta['brand'])}</div></div>
    </div>
  </div>

  <div class="stage">
    <h2>看片 · 共 {n} 个片段（点下方序号切换）</h2>
    <div class="player">
      <div class="ptitle" id="ptitle">—</div>
      <div class="pmeta" id="pmeta"></div>
      <div class="vbox" id="vbox"><video id="v" controls playsinline preload="metadata"></video></div>
      <div class="plist">{chips}</div>
      <div class="tippath" id="ppath"></div>
    </div>
  </div>

  <div class="detail">
    <h2 id="dhead">内容明细 · 第 1 个片段（共 {n} 个）</h2>
    {cards}
  </div>
  <div class="foot">丸子的无限进步 · 收片台 · 用 /podcast-video 自动生成</div>
</div>
<div class="wmark">丸子的无限进步</div>
<script>window.__RECV__ = {json.dumps({"segs": segs}, ensure_ascii=False)};</script>
<script>{JS.replace("__ABS_DIR__", json.dumps(abs_dir.replace("\\", "/"), ensure_ascii=False))}</script>
</body></html>"""


# ---------- 主流程 ----------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--chapters", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--transcript", default=None)
    ap.add_argument("--corrections", default=None)
    ap.add_argument("--subtitle", default=None)
    ap.add_argument("--video", default=None,
                    help="源视频路径（生成分视频预览用；默认找 总视频.mp4 / source_video.mp4）")
    ap.add_argument("--no-preview", action="store_true",
                    help="不转码预览（页面里的视频将无法内嵌播放）")
    ap.add_argument("--preview-h", type=int, default=PREVIEW_LADDER[0][0],
                    help=f"预览画面高度上限，默认 {PREVIEW_LADDER[0][0]}。成品页偏大时调小即可")
    args = ap.parse_args()

    if args.preview_h != PREVIEW_LADDER[0][0]:
        PREVIEW_LADDER[0] = (args.preview_h,) + tuple(PREVIEW_LADDER[0][1:])
        print(f"预览首档高度改为 {args.preview_h}p")

    with open(args.chapters, encoding="utf-8") as f:
        cfg = json.load(f)
    chapters = cfg["chapters"]
    # 浅色页面要用饱和深一档的主题色，否则白底上会发虚（原来那套是为深色底调的）
    accent = {"purple": "#6d5ae6", "blue": "#2f6fed", "green": "#0ea47a",
              "orange": "#e8590c"}.get(cfg.get("theme", "purple"), "#6d5ae6")

    corrections = []
    if args.corrections and os.path.exists(args.corrections):
        with open(args.corrections, encoding="utf-8") as f:
            corrections = json.load(f)

    # 字幕来源：优先 subtitle.ass（最贴近成片），否则 transcript.txt
    items = []
    if args.subtitle and os.path.exists(args.subtitle):
        items = [(st, tx) for st, en, tx in load_ass_events(args.subtitle)]
        print(f"字幕来源：{os.path.basename(args.subtitle)}（{len(items)} 条）")
    elif args.transcript and os.path.exists(args.transcript):
        items = load_transcript_blocks(args.transcript)
        print(f"字幕来源：{os.path.basename(args.transcript)}（{len(items)} 段）")
    else:
        print("！未找到字幕文件，内容明细里的「字幕原文」将为空")

    # 找分视频文件
    files = os.listdir(args.out)
    seg_dir = os.path.join(args.out, "_segments")
    seg_extras = os.listdir(seg_dir) if os.path.isdir(seg_dir) else []

    def find_video(idx, title):
        pats = [f"分视频_{idx}_", f"seg_sub_{idx}.mp4", f"seg_sub_{idx}.mp4"]
        for pat in pats:
            for fn in files:
                if fn.startswith(pat) and fn.endswith(".mp4"):
                    return os.path.join(args.out, fn)
        for fn in seg_extras:
            if fn == f"seg_sub_{idx}.mp4":
                return os.path.join(seg_dir, fn)
        return None

    prev_dir = os.path.join(args.out, "preview")

    # ---- 第一遍：定位每章的分视频 ----
    plans = []
    for ch in chapters:
        idx = str(ch["idx"])
        vpath = find_video(idx, ch.get("title", ""))
        if not vpath or not os.path.exists(vpath):
            fb = args.video or os.path.join(args.out, "总视频.mp4")
            vpath = fb if os.path.exists(fb) else None
            if vpath:
                print(f"  [{idx}] 未找到分视频，回落到 {os.path.basename(vpath)} 整片")
        plans.append((idx, ch, vpath))

    # ---- 第二遍：整批转码预览，一次性压进体积预算 ----
    previews = {}
    if not args.no_preview:
        tasks = [(idx, p) for idx, _, p in plans if p]
        if tasks:
            outs, rung_used = build_previews(tasks, prev_dir)
            previews = outs
            if rung_used[0] != PREVIEW_LADDER[0][0] or rung_used[2] != PREVIEW_LADDER[0][2]:
                print(f"  · 已自动降档到 {rung_used[0]}p / CRF{rung_used[2]}")

    # ---- 第三遍：组装片段数据 ----
    segs = []
    for idx, ch, vpath in plans:
        st, en = float(ch["start"]), float(ch["end"])
        title = ch.get("title", "")
        playable, prev_rel, vid_rel, prev_mb = False, "", "", "0"
        if vpath:
            vid_rel = os.path.relpath(vpath, args.out).replace("\\", "/")
            got = previews.get(idx)
            if got:
                playable = True
                prev_rel = "preview/" + os.path.basename(got)
                prev_mb = f"{os.path.getsize(got) / 1048576:.1f}"

        quote = clip_text(items, st, en, corrections) if items else ""
        summary = ch.get("summary") or ch.get("subtitle") or ch.get("title", "")
        if not is_subtitle(items) and items:
            # 逐字稿只有整段发言？用本章开头那段的摘要兜住「摘要」位置
            head = clip_text(items, st, min(en, st + 60), corrections)
            if head and not ch.get("summary"):
                summary = head.split("\n")[-1][:46]
        segs.append({
            "idx": idx,
            "tag": ch.get("tag", ""),
            "title": title,
            "summary": summary,
            "points": ch.get("points", []),
            "start": st,
            "end": en,
            "tc": f"{hhmmss(st)} → {hhmmss(en)}",
            "dur": dur_text(en - st),
            "quote": head_tail(quote, 220, 120),
            "playable": playable,
            "preview_rel": prev_rel,
            "preview_mb": prev_mb,
            "video_rel": vid_rel,
        })
        flag = "有预览" if playable else ("无预览(仅路径)" if vid_rel else "缺视频")
        print(f"  [{idx}] {title[:22]} · {flag}")

    meta = {"project_title": cfg.get("project_title", "未命名项目"),
            "brand": cfg.get("brand", "")}
    out_html = os.path.join(args.out, "收片台.html")
    with open(out_html, "w", encoding="utf-8") as f:
        f.write(render_page(segs, meta, accent, os.path.abspath(args.out)))

    # 体积闸门：预览面板单文件上限 10MB，超了用户只能看到「文件过大」页
    mb = os.path.getsize(out_html) / 1048576
    print(f"DONE: {out_html}（{mb:.2f}MB）")
    if mb * 1048576 > HTML_MAX:
        print(f"  ✗ 超过预览面板 {HTML_MAX // 1048576}MB 上限，页面将无法在线预览！")
        print(f"    减少内联内容的办法：① 让成片更短 ② 调小 PREVIEW_LADDER 首档高度"
              f" ③ 加 --no-preview 只留路径")
    elif mb > 8.5:
        print(f"  ! 已接近 {HTML_MAX // 1048576}MB 上限，再加片段可能打不开")


if __name__ == "__main__":
    main()
