# multiproc_main.py
# 生产者-消费者并行版：VOD 与直播都投递；直播限时录制；多个 worker 并发处理
# 本版：彻底禁用代理（环境变量与 yt-dlp 内部），playlist 失败→UU→UC→RSS 回退；退出不阻塞。

import os, time, signal, subprocess, multiprocessing as mp
from collections import defaultdict
import yt_dlp
from yt_dlp.utils import DownloadError
import re
import urllib.request, urllib.error
import xml.etree.ElementTree as ET

from gemini_api import gemini_extract_entities, translate_and_generate_tags
from bangumi_api import get_bangumi_context, get_character_info
from download_video import download_video, FrameOverflowError

def _disable_env_proxies():
    for k in (
        "HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY",
        "http_proxy","https_proxy","all_proxy","no_proxy"
    ):
        os.environ.pop(k, None)
# 进程启动即清掉代理
_disable_env_proxies()

# ======== 配置 ========
CHECK_INTERVAL     = 100                  # 轮询间隔（秒）
NUM_WORKERS        = max(2, os.cpu_count() // 2)
BASE_DOWNLOAD_DIR  = "downloads"
LIVE_MAX_SEC       = 30 * 60              # 直播录制最长 30 分钟（可改）

# ----- 分区映射（与 gemini_api.py 中提示词保持一致）-----
TID_NAME2ID = {
    "单机游戏": 4,
    "手机游戏": 172,
    "网络游戏": 65,
    "动画资讯": 51,
    "音乐": 130,
}
TID_VALID = set(TID_NAME2ID.values())
DEFAULT_TID = 51

# 你的订阅清单（省略... 与之前一致）
playlist_urls = [
    "https://www.youtube.com/playlist?list=UUDb0peSmF5rLX7BvuTcJfCw",
    "https://www.youtube.com/playlist?list=UU14QT5j2nQI8lKBCGtrrBQA",
    "https://www.youtube.com/playlist?list=UUjfAEJZdfbIjVHdo5yODfyQ",
    "https://www.youtube.com/playlist?list=UUkVvAm5jb62IMIJQj4wPVGA",
    "https://www.youtube.com/playlist?list=UUR61XV4ROXhkcfLO31hTGuw",
    "https://www.youtube.com/playlist?list=UUpGY2vcoKXf7K6tFzsbSv7w",
    "https://www.youtube.com/playlist?list=UUmDLyFjSutfb1MK7F6cMVSA",
    "https://www.youtube.com/playlist?list=UUY5fcqgSrQItPAX_Z5Frmwg",
    "https://www.youtube.com/playlist?list=UU14Yc2Qv92DMuyNRlHvpo2Q",
    "https://www.youtube.com/playlist?list=UU8yS5dCzbiPGf1HnAwwcnhQ",
    "https://www.youtube.com/playlist?list=UU4DBD52LI7V3AcNs-3EnwNA",
    "https://www.youtube.com/playlist?list=UU-cXutYzvqARF5wNKx1KCNA",
    "https://www.youtube.com/playlist?list=UUX34wuta-mYtZhKr3lS5nwg",
    "https://www.youtube.com/playlist?list=UUb-ekPowbBlQhyt7ZXPiu5Q",
    "https://www.youtube.com/playlist?list=UUOa1eeVIm2_K_EGJrMUM10A",
    "https://www.youtube.com/playlist?list=UUi3c8HJxjiidVUYn4L4zQJw",
    "https://www.youtube.com/playlist?list=UUpmsvJysavBvOKMBoLeO18Q",
    "https://www.youtube.com/playlist?list=UU6VPE3kztGEtFVcJI0oIiUg",
    "https://www.youtube.com/playlist?list=UUeOMz8AiNhsDhEovu5_3ujQ",
    "https://www.youtube.com/playlist?list=UUGIG9CIkPxfLXiC84-DNx_Q",
    "https://www.youtube.com/playlist?list=UU5S8dDswLqbnm9fuZ8Z2ntQ",
    "https://www.youtube.com/playlist?list=UUAWxPGGuIfWME2KTLUmSCHw",
    "https://www.youtube.com/playlist?list=UU47AYUs8AVU1QsT5LhpXjaw",
    "https://www.youtube.com/playlist?list=UU0U2GG9WNndvt1wK41l9iqg",
    "https://www.youtube.com/playlist?list=UUqmVOBOLzaLEOb6Tpb4zPYQ",
    "https://www.youtube.com/playlist?list=UUTkyJbRhal4voLZxmdRSssQ",
    "https://www.youtube.com/playlist?list=UUprIf-GE_T1djzPBH00Ka1g",
    "https://www.youtube.com/playlist?list=UUQ5URCSs1f5Cz9rh-cDGxNQ",
    "https://www.youtube.com/playlist?list=UUdMGYXL38w6htx6Yf9YJa-w",
    "https://www.youtube.com/playlist?list=UUvi81mltkpbF2UEvC_e864g",
    "https://www.youtube.com/playlist?list=UUuxfK38dUXj6oY_L4JjTCkA",
    "https://www.youtube.com/playlist?list=UU2dXx-3RXeeP8hA5AGt8vuw",
    "https://www.youtube.com/playlist?list=UUn5KG-OoKv5Qgc5Pym9-64w",
    "https://www.youtube.com/playlist?list=UUA698bls2pjQyiqP9N-iaeg",
    "https://www.youtube.com/playlist?list=UUXBgKqFxSjKADEuMLkc1Bpg",
    "https://www.youtube.com/playlist?list=UUkH3CcMfqww9RsZvPRPkAJA",
    "https://www.youtube.com/playlist?list=UUvoQlzEzqa6vQA8hq9GNNug",
    "https://www.youtube.com/playlist?list=UUR0J2NYGuC8epsa1O4DMmXQ",
    "https://www.youtube.com/playlist?list=UUlgrS5WzqIn_0Ba4yly0edg",
    "https://www.youtube.com/playlist?list=UUFoS_FzutpGb3EDH3dZ47sw",
    "https://www.youtube.com/playlist?list=UUmzieQGdu7fTXaPqi2AuXyg",
    "https://www.youtube.com/playlist?list=UUvCnMeBahhM8wfADjUhNBvQ",
    "https://www.youtube.com/playlist?list=UUrzCIt5o0X88G9bCdrdbv6g",
    "https://www.youtube.com/playlist?list=UUDKOsemhPLrK4JnsZqkxHLA",
    "https://www.youtube.com/playlist?list=UUiPSajGFI4ja74nYPU1MexA",
    "https://www.youtube.com/playlist?list=UUiS882YPwZt1NfaM0gR0D9Q",
    "https://www.youtube.com/playlist?list=UUtJM9OX9cWtRRxQzgvcOccA",
    "https://www.youtube.com/playlist?list=UUO8okJvgXmbmyJTkUMWvURg",
    "https://www.youtube.com/playlist?list=UUmgf8DJrAXFnU7j3u0kklUQ",
    "https://www.youtube.com/playlist?list=UU_SI1j1d8vJo_rYMV5o_dRg",
    "https://www.youtube.com/playlist?list=UUnBj9CULLD4Zbk_uZh2hnZQ",
    "https://www.youtube.com/playlist?list=UUUXfRsEIJ9xO1DT7TbEWksw",
    "https://www.youtube.com/playlist?list=UUPityslSknKsWUq9iy8p9fw",
    "https://www.youtube.com/playlist?list=UUN-bFIdJM0gQlgX7h6LKcZA",
    "https://www.youtube.com/playlist?list=UUOa1eeVIm2_K_EGJrMUM10A",
    "https://www.youtube.com/playlist?list=UUjmvcdZFiJQkZ8R9_IEAefg",
    "https://www.youtube.com/playlist?list=UUN_7YAeN-_nPyh41kPzlueg",
    "https://www.youtube.com/playlist?list=UUJwGWV914kBlV4dKRn7AEFA",
    "https://www.youtube.com/playlist?list=UUuxfK38dUXj6oY_L4JjTCkA",
    "https://www.youtube.com/playlist?list=UUs4ms7uVxO8wVvQoEocz8jw",
    "https://www.youtube.com/playlist?list=UUe3uJZIjfYwNNR0S6W3GvEA",
    "https://www.youtube.com/playlist?list=UUNWWdKniJyzQA3RiJ5LMoVw",
    "https://www.youtube.com/playlist?list=UU_A_w2KhC3emxNZWQ3pYpfQ",
    "https://www.youtube.com/playlist?list=UUpRh2xmGtaVhFVuyCB271pw",
    "https://www.youtube.com/playlist?list=UUejtUitnpnf8Be-v5NuDSLw",
    "https://www.youtube.com/playlist?list=UU6pGDc4bFGD1_36IKv3FnYg",
    "https://www.youtube.com/playlist?list=UUBSs9x2KzSLhyyA9IKyt4YA",
    "https://www.youtube.com/playlist?list=UUo-Z2r9KeM1uv11uLdnsBMg",
    "https://www.youtube.com/playlist?list=UUaghC0OZwAdidMrbvxkcrPg",
    "https://www.youtube.com/playlist?list=UUyuEAZQzRqhcaLZvQd9ZUNA",
    "https://www.youtube.com/playlist?list=UU6SmH9mR82nj28_NNg_rZvA",
    "https://www.youtube.com/playlist?list=UUM0d5CqnNiJu4zsPTnwmjAQ",
    "https://www.youtube.com/playlist?list=UUoIkccJcBM1MBJEgQ4p5p7Q",
]

def _clear_dir(dir_path: str):
    if not os.path.exists(dir_path):
        return
    cnt = 0
    for name in os.listdir(dir_path):
        p = os.path.join(dir_path, name)
        try:
            if os.path.isfile(p) or os.path.islink(p):
                os.remove(p); cnt += 1
            elif os.path.isdir(p):
                import shutil; shutil.rmtree(p); cnt += 1
        except Exception as e:
            print(f"[清理] 无法删除 {p}: {e}")
    print(f"[清理] 已清空 {dir_path}（{cnt} 项）")

def _clear_system_caches(non_blocking: bool = True, timeout: int = 3):
    """非阻塞清缓存；root 直写，否则 sudo -n 尝试，不要求密码。"""
    try:
        subprocess.run(["sync"], check=False, timeout=timeout)
    except Exception:
        pass
    path = "/proc/sys/vm/drop_caches"
    try:
        if os.geteuid() == 0 and os.access(path, os.W_OK):
            with open(path, "w") as f:
                f.write("3\n")
            print("[缓存] drop_caches=3 已写入（root）")
            return
    except Exception as e:
        print(f"[缓存] root 写入失败（忽略）：{e}")
    if non_blocking:
        try:
            r = subprocess.run(
                ["sudo", "-n", "sh", "-lc", "sync; echo 3 > /proc/sys/vm/drop_caches"],
                check=False, timeout=timeout, capture_output=True, text=True
            )
            if r.returncode == 0:
                print("[缓存] sudo -n 清理成功")
            else:
                print(f"[缓存] sudo -n 不可用（code={r.returncode}），已跳过")
        except Exception as e:
            print(f"[缓存] 跳过（sudo -n 异常）：{e}")

def _post_to_bilibili(video_file, translated_title, description, tags_line, cover_path, source_link, tid: int = 51):
    if not tags_line:
        tags_line = "YouTube搬运"
    cmd = [
        "biliup_rs", "upload", video_file,
        "--title", translated_title,
        "--desc", description,
        "--tag", tags_line,
        "--tid", str(tid),
        "--cover", cover_path,
        "--limit", "1",
        "--copyright", "2",
        "--source", source_link,
        "--submit", "app"
    ]
    print(f"[DEBUG] 投稿命令: {' '.join(cmd)}")
    subprocess.run(cmd, check=True)

# ---------- playlist 取最新视频：稳健实现（禁用代理） ----------

def _build_ydl_opts_for_meta():
    """仅取元数据：禁用代理、IPv4、Cookies、重试。"""
    cookies_txt = os.getenv("YTDLP_COOKIES")
    ydl_opts = {
        "extract_flat": True,
        "playlistend": 1,
        "quiet": True,
        "retries": 10,
        "extractor_retries": 8,
        "sleep_interval_requests": 1,
        "max_sleep_interval_requests": 3,
        "proxy": "",                      # ←← 禁用代理
        "source_address": "0.0.0.0",      # IPv4
        "geo_bypass": True,
    }
    if cookies_txt and os.path.exists(cookies_txt):
        ydl_opts["cookies"] = cookies_txt
    else:
        ydl_opts["cookiesfrombrowser"] = ("firefox",)
    return ydl_opts

def _uu_to_uc(playlist_id: str) -> str | None:
    pid = (playlist_id or "").strip()
    if re.fullmatch(r"[Uu][Uu][0-9A-Za-z_-]{22}", pid):
        return "UC" + pid[2:]
    return None

def _rss_latest_by_uc(uc_id: str):
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={uc_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = r.read()
    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    root = ET.fromstring(data)
    entry = root.find("atom:entry", ns)
    if entry is None:
        return None
    vid = entry.findtext("yt:videoId", default="", namespaces=ns)
    title = entry.findtext("atom:title", default="", namespaces=ns)
    if not vid:
        return None
    return title, vid

def _get_latest_meta_from_playlist(url: str):
    """yt-dlp 读 tab；失败且是 UU… 则 RSS 回退；watch 再取 is_live/duration。"""
    # 1) playlist/tab
    try:
        ydl_opts = _build_ydl_opts_for_meta()
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
        for entry in info.get("entries", []) or []:
            vid = entry.get("id")
            title = entry.get("title") or ""
            vurl = f"https://www.youtube.com/watch?v={vid}"
            # watch 元数据：同样禁用代理 + IPv4
            is_live, live_status, duration = False, None, 0
            try:
                watch_opts = {"quiet": True, "geo_bypass": True, "proxy": "", "source_address": "0.0.0.0"}
                watch_opts["cookiesfrombrowser"] = ("firefox",)
                with yt_dlp.YoutubeDL(watch_opts) as y2:
                    meta = y2.extract_info(vurl, download=False)
                is_live = bool(meta.get("is_live"))
                live_status = meta.get("live_status")
                duration = meta.get("duration") or 0
            except Exception as e:
                print(f"[警告] 获取 {vid} 详细信息失败：{e}")
            return title, vid, vurl, is_live, live_status, duration
    except Exception as e:
        print(f"[提示] playlist/tab 提取失败：{e}")

    # 2) UU→UC→RSS 回退
    m = re.search(r"(?:[?&]list=|^)([0-9A-Za-z_-]{24})", url.strip())
    pid = m.group(1) if m else (url.strip() if re.fullmatch(r"[0-9A-Za-z_-]{24}", url.strip()) else "")
    uc = _uu_to_uc(pid) if pid else None
    if uc:
        try:
            rss = _rss_latest_by_uc(uc)
            if rss:
                title, vid = rss
                vurl = f"https://www.youtube.com/watch?v={vid}"
                is_live, live_status, duration = False, None, 0
                try:
                    watch_opts = {"quiet": True, "geo_bypass": True, "proxy": "", "source_address": "0.0.0.0"}
                    watch_opts["cookiesfrombrowser"] = ("firefox",)
                    with yt_dlp.YoutubeDL(watch_opts) as y2:
                        meta = y2.extract_info(vurl, download=False)
                    is_live = bool(meta.get("is_live"))
                    live_status = meta.get("live_status")
                    duration = meta.get("duration") or 0
                except Exception as e:
                    print(f"[警告] RSS→watch 取详细失败：{e}")
                return title, vid, vurl, is_live, live_status, duration
        except (urllib.error.HTTPError, urllib.error.URLError, ET.ParseError) as e:
            print(f"[提示] RSS 回退失败：{e}")

    return None, None, None, False, None, 0

# ---------- worker / producer ----------

def worker_loop(idx: int, task_q: mp.Queue, stop_ev: mp.Event):
    work_dir = os.path.join(BASE_DOWNLOAD_DIR, f"worker-{idx}")
    os.makedirs(work_dir, exist_ok=True)
    print(f"[Worker-{idx}] 启动：{work_dir}")

    while not stop_ev.is_set():
        try:
            task = task_q.get(timeout=1)
        except Exception:
            continue
        if task is None:
            break

        title, video_url, is_live, live_cap = task
        print(f"[Worker-{idx}] 处理：{title}  live={is_live} cap={live_cap}")

        try:
            vfile, cfile, desc, link = download_video(
                video_url, work_dir=work_dir,
                is_live=is_live,
                live_max_sec=live_cap if is_live else None
            )

            # —— Gemini 标注/翻译/标签 ——
            entities = gemini_extract_entities(title)
            ctx_list = []
            if entities["work"]:
                ctx_list.append(get_bangumi_context(entities["work"]))
            if entities["characters"]:
                for name in entities["characters"]:
                    ci = get_character_info(name)
                    if ci: ctx_list.append(ci)
            translated = translate_and_generate_tags(title, "\n".join([s for s in ctx_list if s]).strip())
            if not translated:
                print(f"[Worker-{idx}] [跳过] Gemini 翻译失败")
                continue

            lines = [x.strip() for x in translated.strip().splitlines() if x.strip()]
            assert len(lines) >= 2 and lines[0].startswith("翻译：") and lines[1].startswith("标签："), f"Gemini 返回异常：{translated}"
            translated_title = lines[0].replace("翻译：","").strip()
            tags_line = lines[1].replace("标签：","").strip() or "YouTube搬运"
            desc_for_post = (desc or "")[:1800]

            # —— 解析第三行 “分区：<tid或中文名>” —— 
            tid = DEFAULT_TID
            if len(lines) >= 3 and lines[2].startswith("分区："):
                val = lines[2].split("：", 1)[1].strip()
                m = re.search(r"\d+", val)
                if m:
                    t = int(m.group())
                    if t in TID_VALID:
                        tid = t
                else:
                    tid = TID_NAME2ID.get(val, DEFAULT_TID)

            _post_to_bilibili(
                os.path.join(work_dir, vfile),
                translated_title,
                desc_for_post,
                tags_line,
                os.path.join(work_dir, cfile),
                link,
                tid=tid,
            )
        except FrameOverflowError as e:
            print(f"[Worker-{idx}] [熔断] {e}")
        except DownloadError as e:
            print(f"[Worker-{idx}] [下载错误] {e}")
        except Exception as e:
            print(f"[Worker-{idx}] [异常] {e}")
        finally:
            _clear_dir(work_dir)
            try:
                _clear_system_caches(non_blocking=True, timeout=2)
            except Exception:
                pass

    print(f"[Worker-{idx}] 退出")

def producer_loop(task_q: mp.Queue, stop_ev: mp.Event):
    last_ids = defaultdict(str)
    while not stop_ev.is_set():
        for pu in playlist_urls:
            try:
                title, vid, vurl, is_live, live_status, duration = _get_latest_meta_from_playlist(pu)
            except Exception as e:
                print(f"[警告] 拉取 {pu} 失败：{e}")
                continue

            if not vid:
                continue

            if not last_ids[pu]:
                last_ids[pu] = vid
                print(f"[首次记录] {pu} -> {vid} ({title})")
                continue

            if vid == last_ids[pu]:
                continue

            last_ids[pu] = vid

            if live_status == "is_upcoming":
                print(f"[跳过] 尚未开播：{title}")
                continue

            is_live_task = bool(is_live or live_status == "is_live")
            live_cap = LIVE_MAX_SEC if is_live_task else None

            try:
                task_q.put_nowait((title, vurl, is_live_task, live_cap))
                typ = "直播" if is_live_task else "视频"
                print(f"[排队] {typ}：{title}")
            except Exception as e:
                print(f"[警告] 入队失败：{e}")

        for _ in range(CHECK_INTERVAL):
            if stop_ev.is_set(): break
            time.sleep(1)

def main():
    os.makedirs(BASE_DOWNLOAD_DIR, exist_ok=True)
    manager = mp.Manager()
    task_q: mp.Queue = manager.Queue(maxsize=200)
    stop_ev = mp.Event()

    workers = []
    for i in range(NUM_WORKERS):
        p = mp.Process(target=worker_loop, args=(i, task_q, stop_ev), daemon=True)
        p.start()
        workers.append(p)

    def _sig(sig, frame):
        print("\n[主进程] 收到信号，准备退出")
        stop_ev.set()
    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    try:
        producer_loop(task_q, stop_ev)
    finally:
        stop_ev.set()
        for _ in workers:
            task_q.put(None)
        for p in workers:
            p.join(timeout=10)
        for p in workers:
            if p.is_alive():
                print(f"[主进程] 终止滞留的 worker PID={p.pid}")
                p.terminate()

if __name__ == "__main__":
    main()
