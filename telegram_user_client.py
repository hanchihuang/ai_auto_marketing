"""
Telegram 用户账号客户端
使用 Telethon 库获取用户加入的群组
"""

from typing import Any


class TelegramUserClient:
    """Telegram 用户账号客户端"""

    def __init__(self, api_id: int, api_hash: str, phone: str, session_string: str | None = None):
        self.api_id = api_id
        self.api_hash = api_hash
        self.phone = phone
        self.session_string = session_string
        self.client = None
        self._connected = False

    def connect(self) -> bool:
        """连接 Telegram"""
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            if self.session_string:
                session = StringSession(self.session_string)
            else:
                session = StringSession()

            self.client = TelegramClient(session, self.api_id, self.api_hash)
            self.client.connect()
            self._connected = True
            return True
        except Exception as e:
            print(f"连接失败: {e}")
            return False

    def is_connected(self) -> bool:
        """检查是否已连接"""
        return self._connected and self.client and self.client.is_connected()

    def get_session_string(self) -> str | None:
        """获取会话字符串用于保存"""
        if self.client:
            return self.client.session.save()
        return None

    def get_dialogs(self, limit: int = 100) -> list[dict]:
        """获取对话列表（群组和频道）"""
        if not self.is_connected():
            if not self.connect():
                return []

        try:
            dialogs = self.client.get_dialogs(limit=limit)
            groups = []

            for dialog in dialogs:
                entity = dialog.entity
                # 只获取群组和超级群组
                if hasattr(entity, 'megagroup') and entity.megagroup:
                    groups.append({
                        "chat_id": entity.id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "type": "supergroup",
                    })
                elif hasattr(entity, 'broadcast'):
                    # 频道
                    pass
                elif hasattr(entity, 'group'):
                    groups.append({
                        "chat_id": entity.id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "type": "group",
                    })

            return groups
        except Exception as e:
            print(f"获取对话失败: {e}")
            return []

    def get_all_groups(self) -> list[dict]:
        """获取所有群组（不限制数量）"""
        if not self.is_connected():
            if not self.connect():
                return []

        try:
            groups = []
            # 获取所有对话
            for dialog in self.client.iter_dialogs():
                entity = dialog.entity

                # 超级群组
                if hasattr(entity, 'megagroup') and entity.megagroup:
                    groups.append({
                        "chat_id": entity.id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "type": "supergroup",
                    })
                # 普通群组
                elif hasattr(entity, 'group') and entity.group:
                    groups.append({
                        "chat_id": entity.id,
                        "title": entity.title,
                        "username": getattr(entity, 'username', None),
                        "type": "group",
                    })

            return groups
        except Exception as e:
            print(f"获取群组失败: {e}")
            return []

    def invite_bot_to_group(self, bot_username: str, chat_id: int) -> bool:
        """邀请 Bot 到群组"""
        if not self.is_connected():
            if not self.connect():
                return False

        try:
            from telethon import functions
            # 使用 AddChatUserRequest 添加 Bot
            result = self.client(
                functions.messages.AddChatUserRequest(
                    chat_id=chat_id,
                    user_id=bot_username,
                    fwd_limit=1
                )
            )
            return True
        except Exception as e:
            print(f"邀请 Bot 失败: {e}")
            return False

    def disconnect(self):
        """断开连接"""
        if self.client:
            self.client.disconnect()
            self._connected = False
