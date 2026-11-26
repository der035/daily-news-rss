"""Route text completions to DashScope when DeepSeek billing blocks requests."""
import json
import os
import re
from threading import Event
from urllib.error import HTTPError
from urllib.request import Request, urlopen

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DASHSCOPE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
_deepseek_billing_blocked = Event()


def dashscope_endpoints(workspace):
    if re.fullmatch(r"[a-zA-Z0-9_-]{4,128}", workspace):
        return [
            f"https://{workspace}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions",
            DASHSCOPE_URL,
        ]
    return [DASHSCOPE_URL]


def completion(url, key, payload, timeout):
    request = Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=timeout) as response:
        return json.load(response)


def text_completion(payload, key, timeout, fallback_model="qwen-flash"):
    fallback_key = os.environ.get("DASHSCOPE_API_KEY", "").strip()
    if key and not _deepseek_billing_blocked.is_set():
        try:
            return completion(DEEPSEEK_URL, key, payload, timeout)
        except HTTPError as error:
            if error.code != 402 or not fallback_key:
                raise
            if not _deepseek_billing_blocked.is_set():
                print("DeepSeek returned HTTP 402. Using DashScope for text.", flush=True)
            _deepseek_billing_blocked.set()

    if not fallback_key:
        raise ValueError("No available credentials for text generation")

    workspace = os.environ.get("DASHSCOPE_WORKSPACE_ID", "").strip()
    fallback_payload = {**payload, "model": fallback_model, "enable_thinking": False}
    endpoints = dashscope_endpoints(workspace)
    for index, endpoint in enumerate(endpoints):
        try:
            return completion(endpoint, fallback_key, fallback_payload, timeout)
        except HTTPError as error:
            if index == len(endpoints) - 1 or error.code not in (401, 403, 404):
                raise
