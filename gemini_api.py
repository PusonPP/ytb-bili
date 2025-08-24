# -*- coding: utf-8 -*-
"""
基于原 gemini_api (2).py 的增强版：
- 统一入口：优先 Gemini CLI（OAuth 免费 1000/日），失败回退到官方 SDK API。
- 解决 SDK 无文本 Part 时 `response.text` 异常。
- 过滤 CLI 在非交互模式下输出到 stdout 的噪声行（如 "Loaded cached credentials."），
  确保上层解析只看到模型正文。
- 保留原函数签名：translate_and_generate_tags / gemini_extract_entities。
"""

import os
import re
import shutil
import subprocess
from typing import Optional, Dict, List, Any
from gemini_cli_adapter import ask_gemini_text

# 保留原有导入（若你别处使用到了）
from google import generativeai  # 官方 SDK
from bangumi_api import get_bangumi_context  # 如未用到可移除

# ========== 可配置参数 ==========
DEFAULT_MODEL = os.getenv("GEMINI_CLI_MODEL", "gemini-2.5-pro")
CLI_TIMEOUT_SEC = int(os.getenv("GEMINI_CLI_TIMEOUT", "90"))

# ========== CLI 工具：降噪处理 ==========
_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# 常见的非 LLM 输出行（不同版本 CLI 可能略有差异，这里尽量覆盖）
_NOISE_PATTERNS = [
    re.compile(r"^Loaded cached credentials\.\s*$", re.IGNORECASE),
    re.compile(r"^Using model\b.*$", re.IGNORECASE),
    re.compile(r"^Authenticated as\b.*$", re.IGNORECASE),
    re.compile(r"^Checkpoint.*$", re.IGNORECASE),
    re.compile(r"^>GEMINI\b.*$", re.IGNORECASE),
    re.compile(r"^\[Sandbox\].*$", re.IGNORECASE),
]

def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s or "")

def _clean_cli_output(out: str) -> str:
    """
    过滤 gemini CLI 在非交互模式下混入 stdout 的非 LLM 文本行。
    仅剔除常见提示语与空白行，保留模型输出。
    """
    out = _strip_ansi(out or "").strip()
    if not out:
        return ""
    keep: List[str] = []
    for ln in out.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        if any(pat.match(ln) for pat in _NOISE_PATTERNS):
            continue
        keep.append(ln)
    return "\n".join(keep).strip()

def _has_gemini_cli() -> bool:
    """检查 PATH 中是否存在 'gemini' 可执行文件。"""
    return shutil.which("gemini") is not None

def _run_gemini_cli(prompt: str, model: str = DEFAULT_MODEL) -> Optional[str]:
    """
    以非交互方式调用 Gemini CLI：
      gemini --sandbox -m <model> -p "<prompt>"

    - 使用 --sandbox 限制工具执行，避免非交互触发工具操作。
    - 通过环境变量 NO_COLOR/CI 关闭颜色和交互 UI。
    - 返回前调用 _clean_cli_output() 过滤噪声行，保证仅保留模型正文。
    """
    if not _has_gemini_cli():
        return None

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")  # 关闭彩色输出
    env.setdefault("CI", "1")        # 标记非交互环境

    args = [
        "gemini",
        "--sandbox",
        "-m", model,
        "-p", prompt,
    ]

    try:
        res = subprocess.run(
            args, capture_output=True, text=True, env=env, timeout=CLI_TIMEOUT_SEC
        )
    except FileNotFoundError:
        print("[Gemini CLI] 未找到 gemini 可执行文件。")
        return None
    except subprocess.TimeoutExpired:
        print(f"[Gemini CLI] 超时（>{CLI_TIMEOUT_SEC}s）。")
        return None
    except Exception as e:
        print(f"[Gemini CLI] 调用异常：{e}")
        return None

    if res.returncode != 0:
        out = (res.stdout or "").strip()
        err = (res.stderr or "").strip()
        print(f"[Gemini CLI] 非 0 退出码：{res.returncode}, stdout={out[:200]}, stderr={err[:200]}")
        return None

    cleaned = _clean_cli_output(res.stdout)
    if not cleaned:
        print("[Gemini CLI] 输出为空（或仅含噪声行）。")
        return None
    return cleaned

# ========== SDK 回退：安全提取文本 ==========
def _extract_text_from_api_response(resp: Any) -> Optional[str]:
    """
    安全解析官方 SDK 的响应对象，不依赖 resp.text。
    - 优先遍历 candidates[].content.parts[] 中的 text 字段，拼接为纯文本。
    - 若被安全策略拦截或 candidates 为空，返回 None。
    """
    try:
        pf = getattr(resp, "prompt_feedback", None)
        if pf and getattr(pf, "block_reason", None):
            print(f"[Gemini API] 请求被拦截，block_reason={pf.block_reason}")
            return None

        candidates = getattr(resp, "candidates", None) or []
        if not candidates:
            print("[Gemini API] 无 candidates 返回。")
            return None

        for idx, cand in enumerate(candidates):
            fr = getattr(cand, "finish_reason", None)
            if fr is not None:
                # finish_reason=1(Stop) 也可能无文本 Part，这里仅做日志
                print(f"[Gemini API] candidate[{idx}].finish_reason={fr}")

            content = getattr(cand, "content", None)
            parts = getattr(content, "parts", None) if content else None
            if not parts:
                continue

            texts: List[str] = []
            for p in parts:
                t = getattr(p, "text", None)
                if t:
                    texts.append(str(t))

            if texts:
                text = "\n".join(texts).strip()
                if text:
                    return text

        print("[Gemini API] candidates 中未找到任何文本 Part。")
        return None
    except Exception as e:
        print(f"[Gemini API] 解析响应异常：{e}")
        return None

def _run_gemini_api(prompt: str, model_name: str = DEFAULT_MODEL) -> Optional[str]:
    """
    回退方式：通过 google.generativeai SDK 调用。
    - 强制 response_mime_type='text/plain'，并禁用工具（tools=[]）。
    - 若仍无文本 Part，则追加一次“强约束纯文本”的重试。
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[Gemini API] 未设置 GEMINI_API_KEY，跳过回退。")
        return None

    try:
        generativeai.configure(api_key=api_key)
        model_obj = generativeai.GenerativeModel(
            model_name,
            generation_config={
                "response_mime_type": "text/plain",
                # 如需：可在此添加温度/长度等参数
                # "temperature": 0.7,
            },
            tools=[],
        )

        resp = model_obj.generate_content(prompt)
        text = _extract_text_from_api_response(resp)
        if text:
            return text

        # 二次兜底：强化“只输出纯文本”的指令
        hard_prompt = (
            prompt + "\n\n请只输出纯文本，不要返回 JSON，不要包含代码块或额外解释。"
        )
        resp2 = model_obj.generate_content(hard_prompt)
        text2 = _extract_text_from_api_response(resp2)
        return text2
    except Exception as e:
        print(f"[Gemini API] 调用异常：{e}")
        return None

def _ask_gemini_text(prompt: str, model_name: str = DEFAULT_MODEL) -> Optional[str]:
    """
    统一入口：
      1) 先走 CLI（OAuth 免费 1000/日）
      2) 再走 API 回退（仅当配置了 GEMINI_API_KEY）
    """
    out = _run_gemini_cli(prompt, model=model_name)
    if out:
        return out
    return _run_gemini_api(prompt, model_name=model_name)

# ========== 业务函数（对外接口保持不变） ==========
def translate_and_generate_tags(title_ori: str, context_info: str):
    """
    返回严格两行：
      翻译：<翻译后的中文标题>
      标签：<标签1>, <标签2>, ..., <标签10>
    """
    ctx = (f"{context_info}\n" if context_info else "")
    prompt = f"""{ctx}你是一名擅长中日双语的ACGN相关情报编辑，任务是将日语/英文ACGN情报标题翻译成中文，并给出 10 个中文标签。
要求：
1) 动画作品名称使用公认中文译名，如不确定名称请自行搜索查询分析。
2) 标题可创意改写，突出情报重点，并使标题具有吸引力。如果情况合适，你可以在标题前加一个【】，并在其中用不多于6个字来简短概括情报类型和内容
3) 严格只输出下列两行（不要额外说明或代码块）：
   翻译：<翻译后的中文标题>
   标签：<标签1>, <标签2>, ..., <标签10>

标题：{title_ori}
    """.strip()

    raw = ask_gemini_text(prompt)
    if not raw:
        return None

    trans_line, tags_line = None, None
    for ln in (l.strip() for l in raw.splitlines() if l.strip()):
        if ln.startswith("翻译：") and trans_line is None:
            trans_line = ln
        elif ln.startswith("标签：") and tags_line is None:
            tags_line = ln
        if trans_line and tags_line:
            break

    if not (trans_line and tags_line):
        # 回显原始结果，便于排查
        raise ValueError(f"Gemini 返回格式异常：\n{raw}")

    return f"{trans_line}\n{tags_line}"


def gemini_extract_entities(title: str) -> dict:
    """
    返回：
      {
        "work": "xxx" | None,
        "characters": ["a", "b"]
      }
    """
    prompt = f"""
请从以下视频标题中提取“作品名称关键词”和“角色名称”。只要关键词，能看出作品是什么就行，不要完整全称。
例如标题中出现 “HUNDRED LINE -最終防衛学園-”，只需提取“最終防衛学園”。

严格按如下格式输出（不要多余说明或代码块）：
- 若两类都存在：
  作品：<作品关键词>
  角色：<角色1>, <角色2>
- 若只有作品：
  作品：<作品关键词>
- 若只有角色：
  角色：<角色1>, <角色2>
- 若都没有：
  无可提取实体

标题：{title}
    """.strip()

    raw = ask_gemini_text(prompt)
    result = {"work": None, "characters": []}

    if not raw:
        return result

    for ln in (l.strip() for l in raw.splitlines() if l.strip()):
        if ln.startswith("作品："):
            result["work"] = ln.replace("作品：", "").strip() or None
        elif ln.startswith("角色："):
            names = ln.replace("角色：", "").strip()
            if names:
                result["characters"] = [n.strip() for n in names.split(",") if n.strip()]
        elif "无可提取实体" in ln:
            result["work"] = None
            result["characters"] = []
            break
    return result