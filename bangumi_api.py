import re
import os
import requests

BANGUMI_API_BASE = "https://api.bgm.tv"
USER_AGENT = "YtbBiliScript/1.0.0"

def extract_work_name(title: str) -> str:
    """
    从视频标题中尝试提取可能的作品名称。
    返回提取的名称；如果无法识别则返回空字符串。
    """
    m = re.search(r'《(.+?)》', title)
    if m:
        return m.group(1).strip()
    m = re.search(r'【(.+?)】', title)
    if m:
        return m.group(1).strip()
    m = re.search(r'「(.+?)」', title)
    if m:
        return m.group(1).strip()
    for sep in [':', '：', '-', '—']:
        if sep in title:
            candidate = title.split(sep, 1)[0].strip()
            if candidate:
                return candidate
    m = re.search(r'^(.+?)(第[\d一二三四五六七八九十]+[话話])', title)
    if m:
        return m.group(1).strip()
    m = re.search(r'^(.+?)(EP\s?\d+)', title, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r'^(.+?)(Episode\s?\d+)', title, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip()
    candidate = title.strip()
    candidate = re.sub(r'[\d\-、。．\.!\s]+$', '', candidate)
    return candidate.strip()

def get_bangumi_context(title: str) -> str:
    """
    给定一个视频原始标题，识别其中的作品名称并从Bangumi获取该作品的信息，
    返回格式化后的上下文提示字符串（含译名、原名、类别、年份、标签、staff等）。
    若未能获取信息则返回空字符串。
    """
    work_name = extract_work_name(title)
    if not work_name:
        return ""

    search_url = f"{BANGUMI_API_BASE}/v0/search/subjects"
    payload = {"keyword": work_name, "sort": "match"}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    token = os.getenv("BANGUMI_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.post(search_url, json=payload, params={"limit": 1}, headers=headers, timeout=10)
        response.raise_for_status()
    except Exception as e:
        print(f"[Bangumi API] 搜索请求失败：{e}")
        return ""
    data = response.json()
    if not isinstance(data, dict) or "data" not in data or len(data["data"]) == 0:
        return ""

    subject = data["data"][0]
    subject_id = subject.get("id")
    if not subject_id:
        return ""

    detail_url = f"{BANGUMI_API_BASE}/v0/subjects/{subject_id}"
    try:
        detail_resp = requests.get(detail_url, headers=headers, timeout=10)
        detail_resp.raise_for_status()
    except Exception as e:
        print(f"[Bangumi API] 获取详情失败：{e}")
        return ""
    subject_detail = detail_resp.json()

    name = subject_detail.get("name", "")
    name_cn = subject_detail.get("name_cn", "")
    official_title = name_cn if name_cn else name
    date_str = subject_detail.get("date", "")
    year = date_str.split("-")[0] if date_str else ""

    type_map = {
        1: "书籍", 2: "动画", 3: "音乐", 4: "游戏", 6: "三次元"
    }
    raw_type = subject_detail.get("type")
    category = type_map.get(raw_type, f"未知类型({raw_type})")

    tags = subject_detail.get("tags", [])
    tag_names = [tag["name"] for tag in tags[:10]]

    staff_dict = {}
    director = ""
    original = ""
    seiyuu = ""

    infobox = subject_detail.get("infobox", [])
    for item in infobox:
        key = item.get("key", "")
        value = item.get("value", "")
        if isinstance(value, list):
            parsed_list = []
            for v in value:
                if isinstance(v, dict):
                    name = v.get("v", "")
                    role = v.get("k", "")
                    if name and role:
                        parsed_list.append(f"{name}（{role}）")
                    elif name:
                        parsed_list.append(name)
                elif isinstance(v, str):
                    parsed_list.append(v)
            value = "、".join(parsed_list)
        if key and isinstance(value, str) and value.strip():
            staff_dict[key] = value

    director = staff_dict.get("导演") or staff_dict.get("监督", "")
    original = staff_dict.get("原作", "")
    seiyuu = staff_dict.get("主角声优", "") or staff_dict.get("声优", "")

    info_lines = ["【背景资料】"]
    if official_title:
        info_lines.append(f"作品标准译名：{official_title}")
    if name and name_cn and name != name_cn:
        info_lines.append(f"作品原名：{name}")
    if category:
        info_lines.append(f"类别：{category}")
    if year:
        info_lines.append(f"年份：{year}")
    if director:
        info_lines.append(f"导演：{director}")
    if original:
        info_lines.append(f"原作：{original}")
    if seiyuu:
        info_lines.append(f"主要声优：{seiyuu}")
    if tag_names:
        info_lines.append(f"标签：{', '.join(tag_names)}")

    return "\n".join(info_lines)

