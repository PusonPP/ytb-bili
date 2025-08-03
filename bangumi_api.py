import re
import os
import requests

BANGUMI_API_BASE = "https://api.bgm.tv"
headers = {
    "User-Agent": "ytb-bili-bot/1.0",
    "Accept": "application/json"
}

def get_bangumi_context(work_name: str) -> str:
    if not work_name:
        return ""
    search_url = f"{BANGUMI_API_BASE}/v0/search/subjects"
    payload = {"keyword": work_name, "sort": "match"}
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

def get_character_info(char_name: str) -> str:
    search_url = f"{BANGUMI_API_BASE}/v0/search/characters"
    payload = {
        "keyword": char_name,
        "limit": 1,
        "filter": {},
        "nsfw": False
    }

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "ytb-bili-bot/1.0"
    }

    try:
        resp = requests.post(search_url, json=payload, headers=headers, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if not data.get("data"):
            return ""

        char = data["data"][0]
        char_id = char["id"]

        detail_url = f"{BANGUMI_API_BASE}/v0/characters/{char_id}"
        detail_resp = requests.get(detail_url, headers=headers, timeout=10)
        detail_resp.raise_for_status()
        detail = detail_resp.json()

        name = detail.get("name", "").strip()
        name_cn = detail.get("name_cn", "").strip()
        summary = detail.get("summary", "").strip()

        if not name_cn and "infobox" in detail:
            for item in detail["infobox"]:
                if item.get("key") == "简体中文名":
                    name_cn = item.get("value", "").strip()
                    break

        lines = []
        if name_cn:
            lines.append(f"角色标准译名：{name_cn}")
        if name and name != name_cn:
            lines.append(f"角色原名：{name}")
        if summary:
            lines.append(f"角色简介：{summary}")

        return "\n".join(lines)

    except Exception as e:
        print(f"[Bangumi API] 角色查询异常：{e}")
        return ""