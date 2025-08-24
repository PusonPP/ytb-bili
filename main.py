import os
import time
import subprocess
import yt_dlp
from collections import deque
from gemini_api import gemini_extract_entities, translate_and_generate_tags
from bangumi_api import get_bangumi_context, get_character_info
from download_video import download_video
from yt_dlp.utils import DownloadError

last_video_ids = {}

video_queue = deque()

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
]
CHECK_INTERVAL = 60
download_dir = "downloads"
if not os.path.exists(download_dir):
    os.makedirs(download_dir)

def post_to_bilibili(video_file, translated_title, description, tags_line, cover_path, source_link):
    if not tags_line:
        tags_line = "YouTube搬运"

    command = [
        "biliup_rs", "upload", video_file,
        "--title", translated_title,
        "--desc", description,
        "--tag", tags_line,
        "--tid", "51",
        "--cover", cover_path,
        "--limit", "1",
        "--copyright", "2",
        "--source", source_link,
        "--submit", "app"
    ]
    print(f"[DEBUG] 最终投稿命令: {' '.join(command)}")
    subprocess.run(command, check=True)

def get_latest_video_from_playlist(url):
    ydl_opts = {'extract_flat': True, 'playlistend': 1, 'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        for entry in info.get('entries', []):
            return entry.get('title'), entry.get('id'), f"https://www.youtube.com/watch?v={entry.get('id')}"
    return None, None, None

def get_video_duration(video_url):
    ydl_opts = {
        'quiet': True,
        'cookiesfrombrowser': ('firefox',),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info.get('duration', 0)
    except Exception as e:
        raise e

def process_queue():
    while video_queue:
        title, video_url = video_queue.popleft()
        video_file_name, cover_file_name, description, source_link = download_video(video_url)

        video_file = os.path.join(download_dir, video_file_name)
        cover_path = os.path.join(download_dir, cover_file_name)

        entities = gemini_extract_entities(title)
        print(f"[信息] 提取结果：{entities}")

        context_info = ""
        if entities["work"]:
            context_info += get_bangumi_context(entities["work"]) + "\n"
        if entities["characters"]:
            for name in entities["characters"]:
                char_info = get_character_info(name)
                if char_info:
                    context_info += char_info + "\n"

        translated_data = translate_and_generate_tags(title, context_info.strip())
        if not translated_data:
            print("[跳过] Gemini 翻译失败，跳过该视频")
            return

        lines = [line.strip() for line in translated_data.strip().splitlines() if line.strip()]
        if not lines or len(lines) < 2 or not lines[0].startswith("翻译：") or not lines[1].startswith("标签："):
            raise ValueError(f"Gemini 返回格式异常：\n{translated_data}")

        translated_title = lines[0].replace("翻译：", "").strip()
        tags_line = lines[1].replace("标签：", "").strip() or "YouTube搬运"

        # === 新增：投稿简介长度限制到 1800 字 ===
        desc_for_post = description or ""
        if len(desc_for_post) > 1800:
            desc_for_post = desc_for_post[:1800]
        # ======================================

        try:
            post_to_bilibili(
                video_file,
                translated_title,
                desc_for_post,        # ← 使用截断后的简介
                tags_line,
                cover_path,
                source_link
            )
        except Exception as e:
            print(f"[上传失败] {e}")
        finally:
            # 统一清空 downloads 目录，避免 .info.json / 缓存文件堆积
            clear_downloads(download_dir)

def check_for_new_videos():
    """检测所有 playlist 是否有新视频"""
    for playlist_url in playlist_urls:
        title, video_id, video_url = get_latest_video_from_playlist(playlist_url)
        if not video_id:
            print(f"[警告] 无法获取 {playlist_url} 的最新视频")
            continue

        if playlist_url not in last_video_ids:
            last_video_ids[playlist_url] = video_id
            print(f"[首次记录] {playlist_url} 最新视频为 {video_id}")
            continue

        if video_id == last_video_ids[playlist_url]:
            continue

        last_video_ids[playlist_url] = video_id

        try:
            duration = get_video_duration(video_url)
        except DownloadError as e:
            error_msg = str(e)
            if "not made this video available in your country" in error_msg:
                print(f"[跳过] 视频因地区限制无法访问：{title}")
                continue
            else:
                print(f"[异常] 无法获取视频时长：{error_msg}")
                continue  # 或者 raise，视你的策略而定
        except Exception as e:
            print(f"[异常] 获取视频时长失败：{e}")
            continue

        print(f"[检测到新视频] {title}，时长 {duration} 秒")
        if duration > 60 * 60:
            print(f"[跳过] 视频时长超过 60 分钟，未搬运：{title}")
            continue

        video_queue.append((title, video_url))
        print(f"[排队] 已加入搬运队列：{title}")

def clear_downloads(dir_path=download_dir):
    """
    清空 downloads 目录下的所有文件/子目录（投稿完成后调用）。
    - 同时删除 .info.json、.vtt、缩略图残留、以及任何中间文件；
    - 若以后在 downloads 里放了临时子目录，也会一并清理；
    - 出错时逐项容错，尽量不影响主流程。
    """
    if not os.path.exists(dir_path):
        return
    removed = 0
    for name in os.listdir(dir_path):
        path = os.path.join(dir_path, name)
        try:
            if os.path.isfile(path) or os.path.islink(path):
                os.remove(path)
                removed += 1
            elif os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
                removed += 1
        except Exception as e:
            print(f"[清理] 无法删除 {path}: {e}")
    print(f"[清理] 已清空 {dir_path}（共删除 {removed} 项）。")

def main():
    while True:
        try:
            check_for_new_videos()
            process_queue()
        except Exception as e:
            print(f"[异常] 处理过程中出错: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
