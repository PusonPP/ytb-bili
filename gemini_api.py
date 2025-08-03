import os
from google import generativeai
from bangumi_api import get_bangumi_context

api_key = os.getenv("GEMINI_API_KEY")
generativeai.configure(api_key=api_key)
model = generativeai.GenerativeModel('gemini-2.5-pro')

def translate_and_generate_tags(title_ori: str, context_info: str):
    """
    传入视频标题与上游构建好的背景上下文，调用 Gemini 翻译与标签生成。
    """
    prompt = (
        f"{context_info}\n" if context_info else ""
    ) + f"""你是一个擅长中日双语的新闻情报媒体编辑，任务是将日语动画情报视频的标题翻译成中文，需遵守以下要求：

翻译要准确，动画作品名称必须使用公认的中文译名，不能使用机翻或非官方名称。动画作品名称的翻译应与其通用译名一致，如遇到冷门作品无法判断，请保持原名称不译或翻译为英文（如原名称是英文或日文片假名），而不是猜测或套用其他动画的译名。若作品名称翻译错误或张冠李戴，将视为严重错误。注意只有在极少数你实在无法确定动画的中文译名是什么的情况下才可以保留原名，通常情况下都需要进行翻译。

你的翻译标题应突出原标题情报重点，但不用全部按照原标题翻译，请你发挥你的创造性，根据给出的相关背景信息起一个足够具有吸引力的标题。必要时可在标题前加一个格式为【】的标签，总结标题重点，不超过6个字。

标题总长度不要超过70个字。

请同时为视频生成10个中文标签，标签包括动画名称、角色名、声优、制作公司、类型、相关tag等关键词，用英文逗号隔开。
标题：{title_ori}

输出格式：
翻译：<翻译后的中文标题>
标签：<标签1>, <标签2>, ..., <标签10>
"""
    for attempt in range(2): 
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            print(f"[Gemini] 第 {attempt + 1} 次调用失败：{e}")
            if attempt == 0:
                print("[Gemini] 准备重试一次……")
            else:
                print("[Gemini] 已重试失败，跳过该视频。")
                return None

def gemini_extract_entities(title: str) -> dict:
    prompt = f"""
请从以下视频标题中提取出提到的作品名称关键词与角色名称。注意，你不需要把作品的完整名称都提取出来，只需要提取关键词，比如标题中出现的作品是 HUNDRED LINE -最終防衛学園-，则你只需要提取 最終防衛学園 。请你按如下格式进行输出：
- 如果两个都存在：
作品：xxx
角色：xxx, xxx
- 如果只有作品：
作品：xxx
- 如果只有角色：
角色：xxx
- 如果都没有：
无可提取实体

标题：{title}
""".strip()

    response = model.generate_content(prompt)
    lines = response.text.strip().splitlines()

    result = {"work": None, "characters": []}
    for line in lines:
        if line.startswith("作品："):
            result["work"] = line.replace("作品：", "").strip()
        elif line.startswith("角色："):
            result["characters"] = [name.strip() for name in line.replace("角色：", "").split(",")]
        elif "无可提取实体" in line:
            return result  # 空内容

    return result

