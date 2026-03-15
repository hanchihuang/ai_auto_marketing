from __future__ import annotations

import json
import os
import re
from typing import Any

import requests
from requests import HTTPError

from env_loader import load_local_env


class VisionLLMClient:
    def __init__(self) -> None:
        load_local_env()
        self.provider = (os.environ.get("VISION_PROVIDER") or "auto").strip().lower()
        self.nvidia_base_url = (os.environ.get("NVIDIA_API_BASE") or "https://integrate.api.nvidia.com/v1").rstrip("/")
        self.nvidia_api_key = (os.environ.get("NVIDIA_API_KEY") or "").strip()
        self.nvidia_models = self._parse_models(
            os.environ.get("NVIDIA_VISION_MODELS") or os.environ.get("NVIDIA_VISION_MODEL") or "moonshotai/kimi-k2.5"
        )
        self.openai_base_url = (os.environ.get("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self.openai_api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
        self.openai_models = self._parse_models(
            os.environ.get("OPENAI_VISION_MODELS") or os.environ.get("OPENAI_VISION_MODEL") or "gpt-5"
        )

    def is_available(self) -> bool:
        return self._resolve_provider() is not None

    def extract_bilibili_creators(self, screenshot_base64: str, keyword: str, limit: int = 10) -> list[dict[str, Any]]:
        provider = self._resolve_provider()
        if provider is None:
            return []

        prompt = (
            "你在识别哔哩哔哩搜索结果页里可见的UP主卡片。\n"
            f"目标关键词：{keyword}\n"
            f"最多返回 {limit} 个结果。\n"
            "请只返回 JSON，对象格式必须是："
            '{"creators":[{"author":"用户名","fans_text":"粉丝原文","fans":12345,"total_posts":123,'
            '"confidence":0.98,"reason":"简短依据"}]}\n'
            "要求：\n"
            "1. 只提取当前截图里清晰可见的用户卡片，不要编造。\n"
            "2. fans 必须是整数；无法判断时填 0。\n"
            "3. total_posts 无法判断时填 0。\n"
            "4. 按你判断的影响力从高到低排序。\n"
            "5. 不要输出 markdown，不要输出解释。"
        )

        content = [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{screenshot_base64}",
                },
            },
        ]
        raw = self._chat_completion(provider, content)
        if not raw:
            return []

        payload = self._extract_json_object(raw)
        creators = payload.get("creators", []) if isinstance(payload, dict) else []
        if not isinstance(creators, list):
            return []

        normalized: list[dict[str, Any]] = []
        for item in creators[:limit]:
            if not isinstance(item, dict):
                continue
            author = self._clean_text(str(item.get("author", "")))
            if not author:
                continue
            normalized.append({
                "author": author,
                "fans_text": self._clean_text(str(item.get("fans_text", ""))),
                "fans": self._safe_int(item.get("fans")),
                "total_posts": self._safe_int(item.get("total_posts")),
                "confidence": float(item.get("confidence", 0) or 0),
                "reason": self._clean_text(str(item.get("reason", ""))),
            })
        return normalized

    def _resolve_provider(self) -> str | None:
        if self.provider == "openai" and self.openai_api_key:
            return "openai"
        if self.provider == "nvidia" and self.nvidia_api_key:
            return "nvidia"
        if self.provider == "auto":
            if self.openai_api_key:
                return "openai"
            if self.nvidia_api_key:
                return "nvidia"
        return None

    def _chat_completion(self, provider: str, content: list[dict[str, Any]]) -> str:
        if provider == "openai":
            url = f"{self.openai_base_url}/chat/completions"
            api_key = self.openai_api_key
            models = self.openai_models
        else:
            url = f"{self.nvidia_base_url}/chat/completions"
            api_key = self.nvidia_api_key
            models = self.nvidia_models

        last_error: Exception | None = None
        for model in models:
            try:
                response = requests.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "temperature": 0.1,
                        "messages": [
                            {
                                "role": "user",
                                "content": content,
                            }
                        ],
                    },
                    timeout=60,
                )
                response.raise_for_status()
                data = response.json()
                return (((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
            except HTTPError as exc:
                last_error = exc
                continue
            except Exception as exc:
                last_error = exc
                continue
        if last_error:
            raise last_error
        return ""

    def _extract_json_object(self, text: str) -> dict[str, Any]:
        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            return json.loads(match.group(0))
        except Exception:
            return {}

    def _clean_text(self, text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text or "")
        return re.sub(r"\s+", " ", text).strip()

    def _safe_int(self, value: Any) -> int:
        if isinstance(value, bool):
            return 0
        if isinstance(value, (int, float)):
            return int(value)
        text = self._clean_text(str(value))
        if not text:
            return 0
        match = re.search(r"\d[\d,]*", text)
        if not match:
            return 0
        return int(match.group(0).replace(",", ""))

    def _parse_models(self, value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]
