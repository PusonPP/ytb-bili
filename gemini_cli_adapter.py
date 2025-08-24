# -*- coding: utf-8 -*-
"""
gemini_cli_adapter.py
统一入口：ask_gemini_text(prompt)
- 先走 Gemini CLI（OAuth 免费 1000/日），并过滤 stdout 噪声；
- 失败再走官方 SDK（仅当设置 GEMINI_API_KEY），并安全解析 candidates.parts.text。
"""

from __future__ import annotations
import os
import re
import shutil
import subprocess
from typing import Optional, List, Any

DEFAULT_MODEL = os.getenv("GEMINI_CLI_MODEL", "gemini-2.5-pro")
CLI_TIMEOUT_SEC = int(os.getenv("GEMINI_CLI_TIMEOUT", "90"))

_ANSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
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
    return shutil.which("gemini") is not None

def _run_gemini_cli(prompt: str, model: str = DEFAULT_MODEL) -> Optional[str]:
    """
    优先用 CLI；若启用了沙箱但容器引擎不可用或报错，则自动无沙箱重试。
    - 通过环境变量控制：
      GEMINI_CLI_SANDBOX=1/true   → 优先尝试沙箱（需 docker 或 podman）
      GEMINI_CLI_REQUIRE_SANDBOX=1 → 必须沙箱，失败就放弃（不做无沙箱重试）
    """
    if not _has_gemini_cli():
        return None

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    env.setdefault("CI", "1")

    want_sandbox = os.getenv("GEMINI_CLI_SANDBOX", "").lower() in ("1", "true", "yes", "on")
    require_sandbox = os.getenv("GEMINI_CLI_REQUIRE_SANDBOX", "").lower() in ("1", "true", "yes", "on")
    has_docker = shutil.which("docker") is not None
    has_podman = shutil.which("podman") is not None
    can_sandbox = (has_docker or has_podman)

    def _run(args):
        try:
            return subprocess.run(
                args, capture_output=True, text=True, env=env, timeout=CLI_TIMEOUT_SEC
            )
        except FileNotFoundError:
            print("[Gemini CLI] 未找到 gemini 可执行文件。"); return None
        except subprocess.TimeoutExpired:
            print(f"[Gemini CLI] 超时（>{CLI_TIMEOUT_SEC}s）。"); return None
        except Exception as e:
            print(f"[Gemini CLI] 调用异常：{e}"); return None

    # --- 优先尝试“带沙箱”的调用（当且仅当用户要求且系统具备容器引擎） ---
    if want_sandbox and can_sandbox:
        args = ["gemini", "--sandbox", "-m", model, "-p", prompt]
        res = _run(args)
        if res and res.returncode == 0:
            cleaned = _clean_cli_output(res.stdout)
            if cleaned:
                return cleaned
        # 沙箱失败：
        if res:
            out = (res.stdout or "").strip(); err = (res.stderr or "").strip()
            print(f"[Gemini CLI] 沙箱模式失败：code={res.returncode}, stdout={out[:200]}, stderr={err[:200]}")
        if require_sandbox:
            # 强制要求沙箱时，不做无沙箱重试
            return None

    # --- 无沙箱调用（默认走这条；或沙箱失败后降级） ---
    args = ["gemini", "-m", model, "-p", prompt]
    res = _run(args)
    if not res:
        return None
    if res.returncode != 0:
        out = (res.stdout or "").strip(); err = (res.stderr or "").strip()
        print(f"[Gemini CLI] 非 0 退出码：{res.returncode}, stdout={out[:200]}, stderr={err[:200]}")
        return None

    cleaned = _clean_cli_output(res.stdout)
    if not cleaned:
        print("[Gemini CLI] 输出为空（或仅含噪声行）。")
        return None
    return cleaned

def _extract_text_from_api_response(resp: Any) -> Optional[str]:
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
    SDK 回退：强制 text/plain，禁用 tools；若异常或无文本，做指数退避重试。
    """
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        print("[Gemini API] 未设置 GEMINI_API_KEY，跳过回退。")
        return None

    import time
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        mdl = genai.GenerativeModel(
            model_name,
            generation_config={"response_mime_type": "text/plain"},
            tools=[],
        )

        def _try_once(p: str) -> Optional[str]:
            resp = mdl.generate_content(p)
            return _extract_text_from_api_response(resp)

        # 尝试 3 次：正常 → 强约束 → 强约束 + 退避
        attempts = [
            prompt,
            prompt + "\n\n请只输出纯文本，不要返回 JSON，不要包含代码块或额外解释。",
            prompt + "\n\n只输出纯文本，不要 JSON/代码块/额外说明。"
        ]
        delay = 1.0
        last_text = None
        for i, p in enumerate(attempts, 1):
            try:
                text = _try_once(p)
                if text:
                    return text
                last_text = text
            except Exception as e:
                print(f"[Gemini API] 第{i}次调用异常：{e}")
            time.sleep(delay); delay *= 2  # 1s → 2s
        return last_text
    except Exception as e:
        print(f"[Gemini API] 调用异常：{e}")
        return None

def ask_gemini_text(prompt: str, model_name: str = DEFAULT_MODEL) -> Optional[str]:
    out = _run_gemini_cli(prompt, model=model_name)
    if out:
        return out
    return _run_gemini_api(prompt, model_name=model_name)
