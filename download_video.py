# download_video.py
# 目标：尽可能获取并上传“最高分辨率”的成品到 B 站；绕开 WEB 端 SABR 只剩 360p 的问题
# 关键点：
# 1) 依次尝试 android -> ios -> mweb -> web 四类客户端，只要某个客户端能“看到”≥720p，就用它下载合并。
# 2) 支持通过环境变量注入 YouTube PO Token（YTDLP_YT_PO_TOKENS），解锁 web 端高清直链。
# 3) yt_dlp 直接合并为 MP4；用视频 id 精确定位合并成品；封面文件名用 glob.escape 处理 [id]。

import os
import glob
import json
import subprocess
from typing import Optional, List, Dict, Any

import yt_dlp
from PIL import Image

download_dir = "downloads"
os.makedirs(download_dir, exist_ok=True)

OUT_TMPL = os.path.join(download_dir, "%(title).80s [%(id)s].%(ext)s")

# 可调阈值：我们认为“高清”起步为 720p；你可改成 1080
HD_MIN_HEIGHT = 720

# 客户端尝试顺序（从最可能有高清直链到兜底）
CLIENT_TRIES: List[List[str]] = [
    ["android"],
    ["ios"],
    ["mweb"],
    ["android", "ios", "mweb", "web"],  # 最后兜底：全部试
]

def _ffprobe_vinfo(path: str) -> Optional[dict]:
    try:
        res = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,codec_name,avg_frame_rate",
                "-of", "json", path
            ],
            capture_output=True, text=True, check=True
        )
        data = json.loads(res.stdout)
        return (data.get("streams") or [None])[0]
    except Exception as e:
        print(f"[调试] ffprobe 失败：{e}")
        return None

def _formats_table(formats: List[Dict[str, Any]]) -> List[str]:
    """把可用 format 列出来，便于判定是否存在 ≥720p 的视频轨"""
    rows = []
    for f in formats or []:
        v = f.get("vcodec") != "none"
        a = f.get("acodec") != "none"
        h = f.get("height")
        fps = f.get("fps")
        proto = f.get("protocol")
        fid = f.get("format_id")
        note = f.get("format_note")
        rows.append(f"{fid:>5}  {str(h):>4}p  v={v} a={a}  fps={fps}  proto={proto}  note={note}")
    return rows

def _has_hd(formats: List[Dict[str, Any]]) -> bool:
    for f in formats or []:
        if f.get("vcodec") != "none" and isinstance(f.get("height"), int) and f["height"] >= HD_MIN_HEIGHT and f.get("url"):
            # 排除明显 DRM 的（yt_dlp 通常会标注 drm 或不可下载；这里以无 url 过滤）
            return True
    return False

def _pick_final_mp4_by_id(yt_id: str) -> Optional[str]:
    suffix = f" [{yt_id}].mp4"
    pattern = os.path.join(download_dir, "*" + glob.escape(suffix))
    cands = sorted(glob.glob(pattern))
    return cands[0] if cands else None

def _find_thumb_png_by_id(yt_id: str) -> Optional[str]:
    suffix = f" [{yt_id}].png"
    pattern = os.path.join(download_dir, "*" + glob.escape(suffix))
    m = sorted(glob.glob(pattern))
    return m[0] if m else None

def _find_thumb_webp_by_id(yt_id: str) -> Optional[str]:
    suffix = f" [{yt_id}].webp"
    pattern = os.path.join(download_dir, "*" + glob.escape(suffix))
    m = sorted(glob.glob(pattern))
    return m[0] if m else None

def _base_ydl_opts() -> Dict[str, Any]:
    # 可选：从环境注入 PO Tokens（格式：CLIENT.CONTEXT+TOKEN，多项逗号分隔）
    # 例如：web.gvs+XXXXX,web.player+YYYYY
    po_env = os.getenv("YTDLP_YT_PO_TOKENS", "").strip()
    po_tokens = [s.strip() for s in po_env.split(",") if s.strip()] if po_env else []

    opts: Dict[str, Any] = {
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "outtmpl": OUT_TMPL,
        "writeinfojson": True,
        "writethumbnail": True,
        "postprocessors": [
            {"key": "FFmpegThumbnailsConvertor", "format": "png", "when": "post_process"},
        ],
        "format_sort": ["res:desc", "fps:desc", "vcodec:av01,h264,vp9", "acodec:m4a,opus"],
        "format_sort_force": True,
        "trim_filenames": 120,
        # 如果你的服务器没有 Firefox，这行删掉；若需要登录，可改用 --cookies 文件
        "cookiesfrombrowser": ("firefox",),
        "noplaylist": True,
        "quiet": False,
        # 让 yt-dlp 把“需要 PO Token 的格式”也列出来，便于我们判断（只是列，不代表能下载）
        "extractor_args": {
            "youtube": {
                "formats": ["missing_pot"],  # 帮助你看见“缺 PO Token 的高清格式”
            }
        },
    }
    if po_tokens:
        # 自动注入 PO Token（有就用，没有就算了）
        opts["extractor_args"]["youtube"]["po_token"] = po_tokens
    return opts

def _probe_formats(url: str, clients: List[str], base_opts: Dict[str, Any]) -> Dict[str, Any]:
    """对指定客户端顺序做一次“只提取不下载”，返回 info。"""
    opts = dict(base_opts)
    # 强制客户端优先级（避免 WEB 命中 SABR 只有 360p）
    ea = dict(opts.get("extractor_args", {}))
    you = dict(ea.get("youtube", {}))
    you["player_client"] = clients
    ea["youtube"] = you
    opts["extractor_args"] = ea
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def _download_with_clients(url: str, base_opts: Dict[str, Any], clients: List[str]) -> Dict[str, Any]:
    """按指定客户端集合真正执行下载"""
    opts = dict(base_opts)
    ea = dict(opts.get("extractor_args", {}))
    you = dict(ea.get("youtube", {}))
    you["player_client"] = clients
    ea["youtube"] = you
    opts["extractor_args"] = ea
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)

def download_video(video_url: str):
    """
    返回: ("video.mp4", "cover.png", description, source_link)
    """
    base_opts = _base_ydl_opts()

    # 第一阶段：逐个客户端“看清晰度”
    picked_clients = None
    picked_info = None
    for clients in CLIENT_TRIES:
        try:
            info_try = _probe_formats(video_url, clients, base_opts)
        except Exception as e:
            print(f"[调试] 客户端 {clients} 预检失败：{e}")
            continue

        fmts = info_try.get("formats") or []
        print("\n".join(["[可用清晰度 - clients=%s]" % ",".join(clients)] + _formats_table(fmts)))

        if _has_hd(fmts):
            picked_clients = clients
            picked_info = info_try
            print(f"[选择] 使用客户端 {clients}（已发现 ≥{HD_MIN_HEIGHT}p 的视频轨）")
            break

        # 没发现 ≥720p，继续试下一个客户端
        if picked_info is None:
            picked_info = info_try  # 兜底保存一次，用于后续描述/封面提取

    if picked_clients is None:
        # 没有任何客户端看到 ≥720p，要么视频本身就是 360/480，要么高清被 SABR/DRM/地区限制
        # 我们使用“最后一次预检的客户端”继续下载，至少不阻塞流程
        picked_clients = CLIENT_TRIES[-1]
        print(f"[提示] 所有客户端都没看到 ≥{HD_MIN_HEIGHT}p。将用 {picked_clients} 兜底下载。")

    # 第二阶段：真正下载（合并为 MP4）
    info = _download_with_clients(video_url, base_opts, picked_clients)

    title = info.get("title", "")
    yt_id = info.get("id", "")
    print(f"视频已下载并合并：{title}")

    description = (info.get("description") or "").strip()
    source_link = f"https://www.youtube.com/watch?v={yt_id}"

    # 精确找到最终 mp4
    final_mp4 = _pick_final_mp4_by_id(yt_id)

    # 兜底：从 requested_downloads 里找 .mp4
    if (not final_mp4) or (not os.path.exists(final_mp4)):
        for it in (info.get("requested_downloads") or []):
            fp = it.get("filepath") or it.get("_filename")
            if fp and fp.endswith(".mp4") and os.path.exists(fp):
                final_mp4 = fp
                break

    # 再兜底：有些配置会合并成 mkv
    if (not final_mp4) or (not os.path.exists(final_mp4)):
        alt = os.path.join(download_dir, "*" + glob.escape(f" [{yt_id}].mkv"))
        mkvs = sorted(glob.glob(alt))
        if mkvs:
            final_mp4 = mkvs[0]

    if (not final_mp4) or (not os.path.exists(final_mp4)):
        raise FileNotFoundError(f"未找到最终合并后的成品文件（id={yt_id}）")

    vi = _ffprobe_vinfo(final_mp4)
    if vi:
        print(f"[确认] 最终成品分辨率：{vi.get('width')}x{vi.get('height')}，codec={vi.get('codec_name')}，fps={vi.get('avg_frame_rate')}")

    # 与主流程对齐：固定输出名 video.mp4
    fixed_video = os.path.join(download_dir, "video.mp4")
    try:
        if os.path.abspath(final_mp4) != os.path.abspath(fixed_video):
            os.replace(final_mp4, fixed_video)
    except Exception:
        import shutil
        shutil.copy2(final_mp4, fixed_video)

    # 处理封面：优先用 yt_dlp 转出的 png；否则从 webp 转
    fixed_cover = os.path.join(download_dir, "cover.png")
    cover_png = _find_thumb_png_by_id(yt_id)
    if cover_png and os.path.exists(cover_png):
        try:
            if os.path.abspath(cover_png) != os.path.abspath(fixed_cover):
                os.replace(cover_png, fixed_cover)
        except Exception:
            import shutil
            shutil.copy2(cover_png, fixed_cover)
    else:
        webp = _find_thumb_webp_by_id(yt_id)
        if webp and os.path.exists(webp):
            try:
                Image.open(webp).convert("RGB").save(fixed_cover, "PNG")
            except Exception as e:
                print(f"[警告] 缩略图 webp→png 失败：{e}")
        else:
            print("[提示] 未生成 cover.png（可检查 ffmpeg/写权限或添加 --writethumbnail）")

    return "video.mp4", "cover.png", description, source_link
