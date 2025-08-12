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
        if not lines[0].startswith("翻译：") or not lines[1].startswith("标签："):
            raise ValueError(f"Gemini 返回格式异常：\n{translated_data}")

        translated_title = lines[0].replace("翻译：", "").strip()
        tags_line = lines[1].replace("标签：", "").strip() or "YouTube搬运"

        try:
            post_to_bilibili(
                video_file, translated_title, description, tags_line, cover_path, source_link
            )
        except Exception as e:
            print(f"[上传失败] {e}")
        finally:
            if os.path.exists(video_file):
                os.remove(video_file)
            if os.path.exists(cover_path):
                os.remove(cover_path)
            print(f"[清理] 已删除本地文件：{video_file} 与 {cover_path}")


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
                continue
        except Exception as e:
            print(f"[异常] 获取视频时长失败：{e}")
            continue

        print(f"[检测到新视频] {title}，时长 {duration} 秒")
        if duration > 60 * 60:
            print(f"[跳过] 视频时长超过 60 分钟，未搬运：{title}")
            continue

        video_queue.append((title, video_url))
        print(f"[排队] 已加入搬运队列：{title}")

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
