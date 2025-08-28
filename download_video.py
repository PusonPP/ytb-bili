# download_video.py
# 功能：多客户端尝试取高清；支持直播录制“限时 + 进度钩子”双保险；下载后做帧数熔断；固化输出名；缩略图处理
# 本版：彻底禁用一切代理（环境变量与 yt-dlp 内部）。保留 IPv4 强制与其余逻辑。

import os, glob, json, subprocess
from typing import Optional, List, Dict, Any
import yt_dlp
from yt_dlp.utils import DownloadError
from PIL import Image

# -------- 可调参数 --------
HD_MIN_HEIGHT = 720          # 认为高清的最低分辨率
MAX_FRAMES    = 200_000      # 帧数熔断阈值，超过判定为长流/异常，放弃
# -------------------------

def _disable_env_proxies():
    """清空所有代理相关环境变量，确保本进程与子逻辑完全不用代理。"""
    for k in (
        "HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY",
        "http_proxy","https_proxy","all_proxy","no_proxy"
    ):
        os.environ.pop(k, None)
# 模块导入即清掉
_disable_env_proxies()

class FrameOverflowError(RuntimeError):
    """下载完成后检测到帧数超过阈值，触发熔断。"""

def _ffprobe_json(args: list) -> dict:
    res = subprocess.run(args, capture_output=True, text=True, check=True)
    return json.loads(res.stdout or "{}")

def _ffprobe_vinfo(path: str) -> Optional[dict]:
    try:
        data = _ffprobe_json([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,codec_name,avg_frame_rate",
            "-of", "json", path
        ])
        return (data.get("streams") or [None])[0]
    except Exception as e:
        print(f"[调试] ffprobe 失败：{e}")
        return None

def _get_frame_count(path: str) -> Optional[int]:
    """统计真实帧数：直播/首映录制很容易超大，这里用帧数兜底熔断。"""
    try:
        data = _ffprobe_json([
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-count_frames",
            "-show_entries", "stream=nb_read_frames",
            "-of", "json", path
        ])
        streams = data.get("streams") or []
        if streams and "nb_read_frames" in streams[0]:
            return int(streams[0]["nb_read_frames"])
    except Exception as e:
        print(f"[警告] 统计帧数失败：{e}")
    return None

def _formats_table(formats: List[Dict[str, Any]]) -> List[str]:
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
            return True
    return False

def _pick_by_id(work_dir: str, yt_id: str, exts=("mp4","mkv","png","webp")) -> Optional[str]:
    for ext in exts:
        patt = os.path.join(work_dir, "*" + glob.escape(f" [{yt_id}].{ext}"))
        cands = sorted(glob.glob(patt))
        if cands:
            return cands[0]
    return None

def _base_ydl_opts(work_dir: str) -> Dict[str, Any]:
    """所有下载调用的基础选项：禁用代理、强制 IPv4、带 cookie。"""
    po_env = os.getenv("YTDLP_YT_PO_TOKENS", "").strip()
    po_tokens = [s.strip() for s in po_env.split(",") if s.strip()] if po_env else []
    opts: Dict[str, Any] = {
        "format": "bv*+ba/best",
        "merge_output_format": "mp4",
        "outtmpl": os.path.join(work_dir, "%(title).80s [%(id)s].%(ext)s"),
        "writeinfojson": True,
        "writethumbnail": True,
        "postprocessors": [{"key": "FFmpegThumbnailsConvertor", "format": "png", "when": "post_process"}],
        "format_sort": ["res:desc", "fps:desc", "vcodec:av01,h264,vp9", "acodec:m4a,opus"],
        "format_sort_force": True,
        "trim_filenames": 120,
        "cookiesfrombrowser": ("firefox",),    # 可按需换 cookies 文件
        "proxy": "",                           # ←← 完全禁用代理（等同 --proxy ""）
        "source_address": "0.0.0.0",           # 强制 IPv4，避免 v6 判国错位
        "geo_bypass": True,
        "noplaylist": True,
        "quiet": False,
        "extractor_args": {
            "youtube": {
                "formats": ["missing_pot"],
                **({"po_token": po_tokens} if po_tokens else {}),
            }
        },
    }
    return opts

def _probe_formats(url: str, clients: List[str], base_opts: Dict[str, Any]) -> Dict[str, Any]:
    opts = dict(base_opts)
    # 再保险：每次尝试都显式禁用代理并保持 IPv4
    opts["source_address"] = "0.0.0.0"
    opts["proxy"] = ""
    ea = dict(opts.get("extractor_args", {}))
    you = dict(ea.get("youtube", {}))
    you["player_client"] = clients
    ea["youtube"] = you
    opts["extractor_args"] = ea
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=False)

def _download_with_clients(url: str, base_opts: Dict[str, Any], clients: List[str]) -> Dict[str, Any]:
    opts = dict(base_opts)
    opts["source_address"] = "0.0.0.0"
    opts["proxy"] = ""
    ea = dict(opts.get("extractor_args", {}))
    you = dict(ea.get("youtube", {}))
    you["player_client"] = clients
    ea["youtube"] = you
    opts["extractor_args"] = ea
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)

# 先 web 再其它：某些视频只允 web
CLIENT_TRIES: List[List[str]] = [
    ["web"], ["android"], ["ios"], ["mweb"], ["android","ios","mweb","web"],
]

def download_video(video_url: str, work_dir: str = "downloads",
                   is_live: bool = False,
                   live_max_sec: Optional[int] = None):
    """
    返回: ("video.mp4", "cover.png", description, source_link)
    - work_dir:   每个 worker 的独立下载目录
    - is_live:    是否直播任务（决定是否开启限时/从头录制）
    - live_max_sec: 直播录制的最大时长（秒）。None/0 表示不限制（不推荐）
    """
    os.makedirs(work_dir, exist_ok=True)
    base_opts = _base_ydl_opts(work_dir)

    # —— 直播限时下载：进度钩子 + sections 双保险 ——
    def _live_limit_hook(d):
        if not is_live or not live_max_sec:
            return
        elapsed = d.get("elapsed")
        if elapsed and elapsed >= live_max_sec:
            raise DownloadError("LIVE_TIME_LIMIT_REACHED")

    if is_live and live_max_sec:
        base_opts["progress_hooks"] = [_live_limit_hook]
        base_opts["download_sections"] = [f"*0-{live_max_sec}"]
        base_opts.setdefault("hls_use_mpegts", True)

    # 第一阶段：逐客户端探清晰度
    picked_clients, picked_info = None, None
    for clients in CLIENT_TRIES:
        try:
            info_try = _probe_formats(video_url, clients, base_opts)
        except Exception as e:
            print(f"[调试] 客户端 {clients} 预检失败：{e}")
            continue
        fmts = info_try.get("formats") or []
        print("\n".join(["[可用清晰度 - clients=%s]" % ",".join(clients)] + _formats_table(fmts)))
        if _has_hd(fmts):
            picked_clients, picked_info = clients, info_try
            print(f"[选择] 使用客户端 {clients}（已发现 ≥{HD_MIN_HEIGHT}p）")
            break
        if picked_info is None:
            picked_info = info_try

    if picked_clients is None:
        picked_clients = CLIENT_TRIES[-1]
        print(f"[提示] 未发现 ≥{HD_MIN_HEIGHT}p，用 {picked_clients} 兜底下载。")

    # 第二阶段：真正下载（仅 A/B，已彻底移除“地区代理回退”）
    def _try_download_with_fallbacks(url, base_opts, prefer_clients):
        last_err = None

        # A) IPv4 + prefer_clients
        opts_v4 = dict(base_opts)
        opts_v4["source_address"] = "0.0.0.0"
        opts_v4["proxy"] = ""
        opts_v4["geo_bypass"] = True
        try:
            return _download_with_clients(url, opts_v4, prefer_clients)
        except Exception as e:
            last_err = e
            print(f"[回退A] IPv4 + {prefer_clients} 失败：{e}")

        # B) 改客户端类型
        for clients in (["web"], ["android"], ["ios"], ["mweb"]):
            if clients == prefer_clients:
                continue
            try:
                return _download_with_clients(url, opts_v4, clients)
            except Exception as e:
                last_err = e
                print(f"[回退B({clients})] 失败：{e}")

        raise last_err or RuntimeError("下载失败（未知原因）")

    info = _try_download_with_fallbacks(video_url, base_opts, picked_clients)

    title = info.get("title", "")
    yt_id = info.get("id", "")
    print(f"视频已下载/录制：{title}")

    description = (info.get("description") or "").strip()
    source_link = f"https://www.youtube.com/watch?v={yt_id}"

    # 定位成品
    final_path = _pick_by_id(work_dir, yt_id, exts=("mp4","mkv"))
    if not final_path or not os.path.exists(final_path):
        for it in (info.get("requested_downloads") or []):
            fp = it.get("filepath") or it.get("_filename")
            if fp and os.path.exists(fp):
                final_path = fp
                break
        if not final_path or not os.path.exists(final_path):
            raise FileNotFoundError(f"未找到合并成品（id={yt_id}）")

    # 帧数熔断（直播/长视频兜底）
    frames = _get_frame_count(final_path)
    if frames is not None and frames > MAX_FRAMES:
        try: os.remove(final_path)
        except Exception: pass
        raise FrameOverflowError(f"帧数 {frames} > {MAX_FRAMES}，判定为长流，已放弃。")

    vi = _ffprobe_vinfo(final_path)
    if vi:
        print(f"[确认] 成品：{vi.get('width')}x{vi.get('height')} codec={vi.get('codec_name')} fps={vi.get('avg_frame_rate')}")

    # 规范输出名
    fixed_video = os.path.join(work_dir, "video.mp4")
    if os.path.abspath(final_path) != os.path.abspath(fixed_video):
        try: os.replace(final_path, fixed_video)
        except Exception:
            import shutil; shutil.copy2(final_path, fixed_video)

    # 缩略图：优先 png，否则 webp 转 png
    fixed_cover = os.path.join(work_dir, "cover.png")
    png = _pick_by_id(work_dir, yt_id, exts=("png",))
    if png and os.path.exists(png):
        if os.path.abspath(png) != os.path.abspath(fixed_cover):
            try: os.replace(png, fixed_cover)
            except Exception:
                import shutil; shutil.copy2(png, fixed_cover)
    else:
        webp = _pick_by_id(work_dir, yt_id, exts=("webp",))
        if webp and os.path.exists(webp):
            try:
                Image.open(webp).convert("RGB").save(fixed_cover, "PNG")
            except Exception as e:
                print(f"[警告] webp→png 失败：{e}")
        else:
            print("[提示] 未生成 cover.png")

    return "video.mp4", "cover.png", description, source_link
