"""
Telegram 自动营销机器人
支持群组搜索、自动发送营销消息、黑名单过滤
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


@dataclass
class TelegramGroup:
    """Telegram 群组信息"""
    chat_id: int
    title: str
    username: str | None
    type: str
    member_count: int | None
    invite_link: str | None


@dataclass
class TelegramMessage:
    """Telegram 消息信息"""
    message_id: int
    chat_id: int
    text: str
    date: int


class TelegramBot:
    """Telegram 营销机器人"""

    API_BASE = "https://api.telegram.org/bot"

    def __init__(self, token: str | None = None, proxy: str | None = None):
        self.token = token
        self.last_error = ""

        # 优先使用环境变量中的代理设置
        if not proxy:
            proxy = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy") or os.environ.get("https_proxy")

        # 如果环境变量没有代理，则自动检测
        if not proxy:
            # 尝试多个常用代理端口
            for port in [7897, 7890, 1080, 8080]:
                test_proxy = f"http://127.0.0.1:{port}"
                try:
                    test_resp = requests.get(
                        "https://api.telegram.org",
                        proxies={"http": test_proxy, "https": test_proxy},
                        timeout=3,
                    )
                    if test_resp.status_code == 200:
                        proxy = test_proxy
                        break
                except Exception:
                    continue

        self.proxy = proxy
        self._session = requests.Session()

        # 配置重试策略来处理 SSL 错误和临时网络问题
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "POST", "OPTIONS"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self._session.mount("http://", adapter)
        self._session.mount("https://", adapter)

        if proxy:
            self._session.proxies = {
                "http": proxy,
                "https": proxy,
            }
        # 添加更好的 SSL 配置
        self._session.verify = True

    def set_token(self, token: str) -> bool:
        """设置 bot token"""
        self.token = token
        return self.test_connection()

    def test_connection(self) -> bool:
        """测试连接"""
        if not self.token:
            self.last_error = "未设置 Bot Token"
            return False

        try:
            # 添加超时和重试
            resp = self._session.get(
                f"{self.API_BASE}{self.token}/getMe",
                timeout=15
            )
            data = resp.json()
            if data.get("ok"):
                self.bot_name = data["result"].get("username", "")
                return True
            self.last_error = data.get("description", "连接失败")
            return False
        except Exception as e:
            self.last_error = str(e)
            return False

    def get_updates(self, timeout: int = 60) -> list[dict]:
        """获取最新消息"""
        if not self.token:
            return []

        try:
            resp = self._session.get(
                f"{self.API_BASE}{self.token}/getUpdates",
                params={"timeout": timeout, "limit": 100},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                return data.get("result", [])
            return []
        except Exception:
            return []

    def get_my_chats(self, timeout: int = 10) -> list[dict]:
        """
        获取 Bot 加入的群组列表
        通过 getUpdates 监听消息，从消息中提取群组信息
        注意：需要先在群组中发送消息，机器人才能感知到群组
        """
        if not self.token:
            return []

        updates = self.get_updates(timeout=timeout)
        chats = {}

        for update in updates:
            # 从 message 中获取群组信息
            message = update.get("message", {})
            chat = message.get("chat", {})

            chat_id = chat.get("id")
            if chat_id and chat.get("type") in ["group", "supergroup"]:
                if chat_id not in chats:
                    chats[chat_id] = {
                        "chat_id": chat_id,
                        "title": chat.get("title", "未知"),
                        "username": chat.get("username"),
                        "type": chat.get("type"),
                    }

            # 从 my_chat_member 也能获取群组信息
            my_chat_member = update.get("my_chat_member", {})
            if my_chat_member:
                chat = my_chat_member.get("chat", {})
                chat_id = chat.get("id")
                if chat_id and chat.get("type") in ["group", "supergroup"]:
                    if chat_id not in chats:
                        chats[chat_id] = {
                            "chat_id": chat_id,
                            "title": chat.get("title", "未知"),
                            "username": chat.get("username"),
                            "type": chat.get("type"),
                        }

        return list(chats.values())

    def get_chat(self, chat_id: int) -> dict | None:
        """获取群组信息"""
        if not self.token:
            return None

        try:
            resp = self._session.get(
                f"{self.API_BASE}{self.token}/getChat",
                params={"chat_id": chat_id},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            self.last_error = data.get("description", "获取群组信息失败")
            return None
        except Exception as e:
            self.last_error = str(e)
            return None

    def get_chat_member_count(self, chat_id: int) -> int | None:
        """获取群组成员数量"""
        if not self.token:
            return None

        try:
            resp = self._session.get(
                f"{self.API_BASE}{self.token}/getChatMemberCount",
                params={"chat_id": chat_id},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            return None
        except Exception:
            return None

    def send_message(
        self,
        chat_id: int,
        text: str,
        parse_mode: str = "Markdown",
        disable_web_page_preview: bool = True,
    ) -> bool:
        """发送消息到群组"""
        if not self.token:
            self.last_error = "未设置 Bot Token"
            return False

        try:
            resp = self._session.post(
                f"{self.API_BASE}{self.token}/sendMessage",
                params={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": parse_mode,
                    "disable_web_page_preview": disable_web_page_preview,
                },
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                return True
            self.last_error = data.get("description", "发送消息失败")
            return False
        except Exception as e:
            self.last_error = str(e)
            return False

    def search_groups_by_keyword(
        self,
        keyword: str,
        blacklist_keywords: list[str] | None = None,
    ) -> list[TelegramGroup]:
        """
        通过关键词搜索群组

        由于 Telegram API 不支持直接搜索群组，这里通过以下方式实现：
        1. 使用已保存的群组列表进行匹配
        2. 支持通过邀请链接加入群组后再搜索

        返回匹配关键词且不在黑名单中的群组
        """
        if blacklist_keywords is None:
            blacklist_keywords = ["sober", "greek", "Greek", "格致", "戒酒", "戒毒", "康复"]

        matched_groups = []

        # 这里需要用户先通过其他方式获取群组列表
        # 可以通过 /start 命令监听用户加入的群组
        # 或者通过搜索邀请链接的方式

        return matched_groups

    def is_blacklisted(self, group_title: str, blacklist_keywords: list[str]) -> bool:
        """
        检查群组是否在黑名单中

        如果群组标题包含黑名单关键词，返回 True
        """
        title_lower = group_title.lower()
        for keyword in blacklist_keywords:
            if keyword.lower() in title_lower:
                return True
        return False

    def send_marketing_message(
        self,
        chat_id: int,
        content: str,
        blacklist_keywords: list[str] | None = None,
    ) -> tuple[bool, str]:
        """
        发送营销消息，返回 (是否成功, 状态信息)

        如果群组在黑名单中，拒绝发送
        """
        if blacklist_keywords is None:
            blacklist_keywords = ["sober", "greek", "Greek", "格致", "戒酒", "戒毒", "康复"]

        # 先获取群组信息检查是否在黑名单
        chat_info = self.get_chat(chat_id)
        if not chat_info:
            return False, f"无法获取群组信息: {self.last_error}"

        title = chat_info.get("title", "")
        if self.is_blacklisted(title, blacklist_keywords):
            return False, f"群组 '{title}' 在黑名单中，已跳过"

        # 发送消息
        if self.send_message(chat_id, content):
            return True, f"消息已发送到群组: {title}"

        return False, self.last_error

    def batch_send_to_groups(
        self,
        groups: list[dict],
        content: str,
        blacklist_keywords: list[str] | None = None,
    ) -> dict:
        """
        批量发送到多个群组

        groups: 群组列表 [{"chat_id": xxx, "title": "xxx"}, ...]
        返回发送结果统计
        """
        if blacklist_keywords is None:
            blacklist_keywords = ["sober", "greek", "Greek", "格致", "戒酒", "戒毒", "康复"]

        success_count = 0
        failed_count = 0
        skipped_blacklist = 0
        results = []

        for group in groups:
            chat_id = group.get("chat_id")
            title = group.get("title", "")

            # 检查黑名单
            if self.is_blacklisted(title, blacklist_keywords):
                skipped_blacklist += 1
                results.append({
                    "chat_id": chat_id,
                    "title": title,
                    "status": "skipped",
                    "reason": "在黑名单中",
                })
                continue

            # 发送消息
            if self.send_message(chat_id, content):
                success_count += 1
                results.append({
                    "chat_id": chat_id,
                    "title": title,
                    "status": "success",
                })
            else:
                failed_count += 1
                results.append({
                    "chat_id": chat_id,
                    "title": title,
                    "status": "failed",
                    "reason": self.last_error,
                })

            # 避免发送过快
            time.sleep(0.5)

        return {
            "success_count": success_count,
            "failed_count": failed_count,
            "skipped_blacklist": skipped_blacklist,
            "total": len(groups),
            "results": results,
        }

    def get_invite_link(self, chat_id: int) -> str | None:
        """获取群组邀请链接"""
        if not self.token:
            return None

        try:
            resp = self._session.get(
                f"{self.API_BASE}{self.token}/exportChatInviteLink",
                params={"chat_id": chat_id},
                timeout=15,
            )
            data = resp.json()
            if data.get("ok"):
                return data.get("result")
            return None
        except Exception:
            return None


class TelegramAccountManager:
    """Telegram 账号管理器"""

    def __init__(self, storage: Any):
        self.storage = storage

    def save_account(self, bot_token: str, nickname: str = "") -> tuple[bool, str]:
        """保存账号"""
        bot = TelegramBot(bot_token)
        if not bot.test_connection():
            return False, bot.last_error

        # 存储账号信息
        account_data = {
            "phone": bot_token[:20] + "...",
            "platform": "telegram",
            "cookie": bot_token,
            "nickname": nickname or bot.bot_name,
            "status": "online",
        }

        # 检查是否已存在
        existing = self.storage.get_xhs_account_by_phone(account_data["phone"], "telegram")
        if existing:
            self.storage.update_xhs_account(existing["id"], account_data)
            return True, "账号已更新"
        else:
            self.storage.insert_xhs_account(account_data)
            return True, "账号已保存"

    def list_accounts(self) -> list[dict]:
        """列出所有 Telegram 账号"""
        return self.storage.list_xhs_accounts(platform="telegram")
