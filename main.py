import os
import time
import subprocess
import yt_dlp
from collections import deque
from gemini_api import translate_and_generate_tags
from download_video import download_video

# 已记录的最后视频 ID
last_video_ids = {}

# 视频队列
video_queue = deque()

# 监控播放列表
playlist_urls = [
    "https://www.youtube.com/playlist?list=UUb7pea6mapotr_bULeklChA",
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
    # 默认不使用代理
    ydl_opts = {
        'quiet': True,
        'cookiesfrombrowser': ('firefox', 'ua6vti8s.default'),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=False)
            return info.get('duration', 0)
    except Exception as e:
        if "This video is not available in your country" in str(e) or "Sign in to confirm you’re not a bot" in str(e):
            print(f"[地区限制] 检测到访问受限，切换代理重试：{e}")

            # 使用代理重试
            ydl_opts['proxy'] = 'socks5://127.0.0.1:1081'
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(video_url, download=False)
                return info.get('duration', 0)
        else:
            raise e


def process_queue():
    """逐个处理排队的视频"""
    while video_queue:
        title, video_url = video_queue.popleft()

        video_file_name, cover_file_name, description, source_link = download_video(video_url)
        video_file = os.path.join(download_dir, video_file_name)
        cover_path = os.path.join(download_dir, cover_file_name)

        translated_data = translate_and_generate_tags(title)

        lines = [line.strip() for line in translated_data.strip().splitlines() if line.strip()]

        if len(lines) < 2:
            raise ValueError(f"Gemini API 返回格式不正确:\n{translated_data}")

        translated_title = lines[0].replace("翻译：", "").strip()
        tags_line = lines[1].replace("标签：", "").strip() or "YouTube搬运"

        post_to_bilibili(video_file, translated_title, description, tags_line, cover_path, source_link)

        os.remove(video_file)
        os.remove(cover_path)
        print(f"[完成] 已上传 {translated_title}，并删除本地文件。")

def check_for_new_videos():
    """检测所有 playlist 是否有新视频"""
    for playlist_url in playlist_urls:
        title, video_id, video_url = get_latest_video_from_playlist(playlist_url)
        if not video_id:
            print(f"[警告] 无法获取 {playlist_url} 的最新视频")
            continue

        # 首次记录
        if playlist_url not in last_video_ids:
            last_video_ids[playlist_url] = video_id
            print(f"[首次记录] {playlist_url} 最新视频为 {video_id}")
            continue

        # 未更新
        if video_id == last_video_ids[playlist_url]:
            continue

        # 新视频，更新记录
        last_video_ids[playlist_url] = video_id

        # 检查视频时长
        duration = get_video_duration(video_url)
        print(f"[检测到新视频] {title}，时长 {duration} 秒")
        if duration > 6 * 60:
            print(f"[跳过] 视频时长超过 6 分钟，未搬运：{title}")
            continue

        video_queue.append((title, video_url))
        print(f"[排队] 已加入搬运队列：{title}")

def main():
    """持续运行"""
    while True:
        try:
            check_for_new_videos()
            process_queue()
        except Exception as e:
            print(f"[异常] 处理过程中出错: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
