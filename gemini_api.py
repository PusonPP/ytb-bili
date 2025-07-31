import os
from google import generativeai
from bangumi_api import get_bangumi_context

api_key = os.getenv("GEMINI_API_KEY")
generativeai.configure(api_key=api_key)
model = generativeai.GenerativeModel('gemini-1.5-pro')

def translate_and_generate_tags(title_ori: str):
    """
    给定一个视频的原始标题（可能包含日文/英文等），调用Gemini模型翻译为中文标题并生成标签。
    现在增加了对Bangumi的调用，会在Prompt中加入作品相关的背景信息以提高准确性。
    """
    # 1. 利用Bangumi API获取作品标准信息，构建上下文提示
    context_info = get_bangumi_context(title_ori)
    # 如果成功获取到作品信息，则将其作为“背景资料”加入Prompt前置部分
    if context_info:
        # 在提示词开头加入背景资料段落，然后接上原有的翻译与标签生成要求
        prompt = (
            f"{context_info}\n" if context_info else ""
        ) + f"""你是一个擅长中日双语的新闻情报媒体编辑，任务是将日语动画情报视频的标题翻译成中文，需遵守以下要求：

        翻译要准确，动画作品名称必须使用公认的中文译名，不能使用机翻或非官方名称。动画作品名称的翻译应与其通用译名一致，如遇到冷门作品无法判断，请保持原名称不译或翻译为英文（如原名称是英文或日文片假名），而不是猜测或套用其他动画的译名。若作品名称翻译错误或张冠李戴，将视为严重错误。注意只有在极少数你实在无法确定动画的中文译名是什么的情况下才可以保留原名，通常情况下都需要进行翻译。

        你的翻译标题应突出情报重点，具备吸引力。必要时可在标题前加一个格式为【】的标签，总结标题重点，不超过6个字。

        标题总长度不要超过70个字。

        请同时为视频生成10个中文标签，标签包括动画名称、角色名、声优、制作公司、类型等关键词，用英文逗号隔开。
        标题：{title_ori}

        输出格式：
        翻译：<翻译后的中文标题>
        标签：<标签1>, <标签2>, <标签3>, <标签4>, <标签5>, <标签6>, <标签7>, <标签8>, <标签9>, <标签10>
        """
    response = model.generate_content(prompt)
    return response.text
