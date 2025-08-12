import yt_dlp
import os
from PIL import Image
import subprocess

download_dir = "downloads"
if not os.path.exists(download_dir):
    os.makedirs(download_dir)

def download_video(video_url):
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'outtmpl': os.path.join(download_dir, '%(title)s.%(ext)s'),
        'writeinfojson': True,
        'writethumbnail': True,
        'cookiesfrombrowser': ('firefox',),
        'quiet': False,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
    except Exception as e:
        raise e

    print(f"视频已下载：{info['title']}")
    description = info.get('description', '').strip()
    source_link = f"https://www.youtube.com/watch?v={info.get('id', '')}"

    video_file_path = info.get('_filename') or info.get('requested_downloads', [{}])[0].get('filepath')
    if not video_file_path or not os.path.exists(video_file_path):
        raise FileNotFoundError(f"未找到视频文件，路径：{video_file_path}")

    output_video = os.path.join(download_dir, "video.mp4")
    cmd = ["ffmpeg", "-y", "-i", video_file_path, "-c:v", "copy", "-c:a", "aac", output_video]
    subprocess.run(cmd, check=True)
    print(f"已将视频 {video_file_path} 转换为 {output_video}")
    os.remove(video_file_path)

    webp_path = next((os.path.join(download_dir, f) for f in os.listdir(download_dir) if f.endswith(".webp")), None)
    png_path = os.path.join(download_dir, "cover.png")

    if webp_path and os.path.exists(webp_path):
        try:
            img = Image.open(webp_path).convert("RGB")
            img.save(png_path, "PNG")
            print(f"已将封面 {webp_path} 转换为 {png_path}")
            os.remove(webp_path)
        except Exception as e:
            print(f"封面转换失败: {e}")
    else:
        print(f"未找到封面 .webp 文件")

    return "video.mp4", "cover.png", description, source_link

