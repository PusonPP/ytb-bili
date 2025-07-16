import os
from google import generativeai

# 初始化 Gemini
api_key = os.getenv("GEMINI_API_KEY")
generativeai.configure(api_key=api_key)
model = generativeai.GenerativeModel('gemini-1.5-pro')

def translate_and_generate_tags(title_en: str):
    prompt = f"""
请把以下日语视频标题翻译为中文，注意要突出情报重点，使标题具备吸引力，在你的标题前面加一个【】，并在其中用不超过6个字总结标题的重点信息。如果其中有英文则保留英文不进行翻译，标题最多不要超过70个字。并为这个视频生成 8 个合适的中文标签，包括动画作品名称等关键信息，标签用英文逗号隔开。
标题：{title_en}

输出格式：
翻译：<翻译后的中文标题>
标签：<标签1>, <标签2>, <标签3>, <标签4>, <标签5>, <标签6>
"""
    response = model.generate_content(prompt)
    return response.text
