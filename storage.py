"""
数据存储模块
支持 SQLite 数据库存储
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


class Storage:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                -- 小红书账号表
                CREATE TABLE IF NOT EXISTS xhs_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT UNIQUE NOT NULL,
                    platform TEXT DEFAULT 'x',
                    cookie TEXT,
                    nickname TEXT,
                    avatar TEXT,
                    follower_count INTEGER DEFAULT 0,
                    following_count INTEGER DEFAULT 0,
                    note_count INTEGER DEFAULT 0,
                    status TEXT DEFAULT 'offline',
                    created_at TEXT NOT NULL,
                    last_login TEXT
                );

                -- 热帖记录表
                CREATE TABLE IF NOT EXISTS xhs_hot_posts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT UNIQUE NOT NULL,
                    platform TEXT DEFAULT 'x',
                    title TEXT,
                    content TEXT,
                    author TEXT,
                    author_id TEXT,
                    cover_image TEXT,
                    likes INTEGER DEFAULT 0,
                    comments INTEGER DEFAULT 0,
                    collects INTEGER DEFAULT 0,
                    tags_json TEXT,
                    url TEXT,
                    search_keyword TEXT,
                    web_accessible INTEGER DEFAULT 1,
                    accessibility_checked_at TEXT,
                    found_at TEXT NOT NULL,
                    last_updated TEXT
                );

                -- 评论任务表
                CREATE TABLE IF NOT EXISTS xhs_comment_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id TEXT NOT NULL,
                    platform TEXT DEFAULT 'x',
                    post_title TEXT,
                    content TEXT NOT NULL,
                    strategy TEXT DEFAULT 'soft',
                    status TEXT DEFAULT 'pending',
                    error_message TEXT,
                    commented_at TEXT,
                    created_at TEXT NOT NULL
                );

                -- 产品表
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    code TEXT UNIQUE NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    price TEXT,
                    wechat_id TEXT,
                    features_json TEXT,
                    target_tags_json TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT
                );

                -- 运营统计表
                CREATE TABLE IF NOT EXISTS xhs_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    comments_success INTEGER DEFAULT 0,
                    comments_failed INTEGER DEFAULT 0,
                    posts_searched INTEGER DEFAULT 0,
                    accounts_active INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );

                -- Telegram 用户账号表（用于获取群组）
                CREATE TABLE IF NOT EXISTS telegram_user_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    api_id INTEGER NOT NULL,
                    api_hash TEXT NOT NULL,
                    phone TEXT NOT NULL,
                    session_string TEXT,
                    bot_username TEXT,
                    added_at TEXT NOT NULL
                );

                -- 微信文章表（搜狗微信爬虫）
                CREATE TABLE IF NOT EXISTS wechat_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    link TEXT NOT NULL UNIQUE,
                    source TEXT,
                    author TEXT,
                    pub_time TEXT,
                    abstract TEXT,
                    keyword TEXT,
                    content TEXT,
                    qr_code_url TEXT,
                    qr_code_type TEXT,
                    crawled_at TEXT NOT NULL
                );

                -- Telegram 群组表
                CREATE TABLE IF NOT EXISTS telegram_groups (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id INTEGER UNIQUE NOT NULL,
                    title TEXT NOT NULL,
                    username TEXT,
                    type TEXT DEFAULT 'group',
                    member_count INTEGER,
                    invite_link TEXT,
                    is_blocked INTEGER DEFAULT 0,
                    block_reason TEXT,
                    added_at TEXT NOT NULL,
                    last_message_at TEXT
                );

                -- Telegram 营销任务表
                CREATE TABLE IF NOT EXISTS telegram_marketing_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    group_id INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT DEFAULT 'pending',
                    sent_at TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(conn, "xhs_accounts", "platform", "TEXT DEFAULT 'x'")
            self._ensure_column(conn, "xhs_hot_posts", "platform", "TEXT DEFAULT 'x'")
            self._ensure_column(conn, "xhs_hot_posts", "web_accessible", "INTEGER DEFAULT 1")
            self._ensure_column(conn, "xhs_hot_posts", "accessibility_checked_at", "TEXT")
            self._ensure_column(conn, "xhs_comment_tasks", "platform", "TEXT DEFAULT 'x'")

    def _ensure_column(
        self,
        conn: sqlite3.Connection,
        table_name: str,
        column_name: str,
        definition: str,
    ) -> None:
        columns = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        existing = {row[1] for row in columns}
        if column_name not in existing:
            conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")

    # ==================== 小红书账号管理 ====================

    def insert_xhs_account(self, payload: dict[str, Any]) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO xhs_accounts (
                    phone, platform, cookie, nickname, avatar, follower_count,
                    following_count, note_count, status, created_at, last_login
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("phone", ""),
                    payload.get("platform", "x"),
                    payload.get("cookie", ""),
                    payload.get("nickname", ""),
                    payload.get("avatar", ""),
                    payload.get("follower_count", 0),
                    payload.get("following_count", 0),
                    payload.get("note_count", 0),
                    payload.get("status", "offline"),
                    now,
                    payload.get("last_login", ""),
                ),
            )
            return cursor.lastrowid

    def update_xhs_account(self, account_id: int, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE xhs_accounts SET
                    platform = COALESCE(?, platform),
                    cookie = COALESCE(?, cookie),
                    nickname = COALESCE(?, nickname),
                    avatar = COALESCE(?, avatar),
                    follower_count = COALESCE(?, follower_count),
                    following_count = COALESCE(?, following_count),
                    note_count = COALESCE(?, note_count),
                    status = COALESCE(?, status),
                    last_login = COALESCE(?, last_login)
                WHERE id = ?
                """,
                (
                    payload.get("platform"),
                    payload.get("cookie"),
                    payload.get("nickname"),
                    payload.get("avatar"),
                    payload.get("follower_count"),
                    payload.get("following_count"),
                    payload.get("note_count"),
                    payload.get("status"),
                    payload.get("last_login"),
                    account_id,
                ),
            )

    def list_xhs_accounts(self, platform: str | None = None) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if platform:
                rows = conn.execute(
                    "SELECT * FROM xhs_accounts WHERE platform = ? ORDER BY id DESC",
                    (platform,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM xhs_accounts ORDER BY id DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def get_xhs_account(self, account_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM xhs_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_xhs_account_by_phone(self, phone: str, platform: str | None = None) -> dict[str, Any] | None:
        with self._connect() as conn:
            if platform:
                row = conn.execute(
                    "SELECT * FROM xhs_accounts WHERE phone = ? AND platform = ?",
                    (phone, platform),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM xhs_accounts WHERE phone = ?",
                    (phone,),
                ).fetchone()
        return dict(row) if row else None

    def delete_xhs_account(self, account_id: int) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM xhs_accounts WHERE id = ?",
                (account_id,),
            )
            return cursor.rowcount > 0

    # ==================== 热帖管理 ====================

    def insert_xhs_hot_post(self, payload: dict[str, Any]) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO xhs_hot_posts (
                    post_id, platform, title, content, author, author_id, cover_image,
                    likes, comments, collects, tags_json, url, search_keyword,
                    web_accessible, accessibility_checked_at, found_at, last_updated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["post_id"],
                    payload.get("platform", "x"),
                    payload.get("title", ""),
                    payload.get("content", ""),
                    payload.get("author", ""),
                    payload.get("author_id", ""),
                    payload.get("cover_image", ""),
                    payload.get("likes", 0),
                    payload.get("comments", 0),
                    payload.get("collects", 0),
                    json.dumps(payload.get("tags", []), ensure_ascii=False),
                    payload.get("url", ""),
                    payload.get("search_keyword", ""),
                    1 if payload.get("web_accessible", True) else 0,
                    payload.get("accessibility_checked_at", now),
                    payload.get("found_at", now),
                    now,
                ),
            )
            return cursor.lastrowid

    def list_xhs_hot_posts(
        self,
        limit: int = 100,
        web_accessible_only: bool = False,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if web_accessible_only:
                if platform:
                    rows = conn.execute(
                        """
                        SELECT * FROM xhs_hot_posts
                        WHERE COALESCE(web_accessible, 1) = 1 AND platform = ?
                        ORDER BY likes DESC, found_at DESC LIMIT ?
                        """,
                        (platform, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        """
                        SELECT * FROM xhs_hot_posts
                        WHERE COALESCE(web_accessible, 1) = 1
                        ORDER BY likes DESC, found_at DESC LIMIT ?
                        """,
                        (limit,),
                    ).fetchall()
            else:
                if platform:
                    rows = conn.execute(
                        "SELECT * FROM xhs_hot_posts WHERE platform = ? ORDER BY likes DESC, found_at DESC LIMIT ?",
                        (platform, limit),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM xhs_hot_posts ORDER BY likes DESC, found_at DESC LIMIT ?",
                        (limit,),
                    ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["tags"] = json.loads(item.pop("tags_json", "[]"))
            item["web_accessible"] = bool(item.get("web_accessible", 1))
            result.append(item)
        return result

    def get_xhs_hot_post(self, post_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM xhs_hot_posts WHERE post_id = ?",
                (post_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["tags"] = json.loads(item.pop("tags_json", "[]"))
        item["web_accessible"] = bool(item.get("web_accessible", 1))
        return item

    def delete_xhs_hot_post(self, post_id: str) -> bool:
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM xhs_hot_posts WHERE post_id = ?",
                (post_id,),
            )
            return cursor.rowcount > 0

    def clear_xhs_hot_posts(self, platform: str | None = None) -> int:
        with self._connect() as conn:
            if platform:
                cursor = conn.execute("DELETE FROM xhs_hot_posts WHERE platform = ?", (platform,))
            else:
                cursor = conn.execute("DELETE FROM xhs_hot_posts")
            return cursor.rowcount

    # ==================== 评论任务管理 ====================

    def insert_xhs_comment_task(self, payload: dict[str, Any]) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO xhs_comment_tasks (
                    post_id, platform, post_title, content, strategy, status,
                    error_message, commented_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["post_id"],
                    payload.get("platform", "x"),
                    payload.get("post_title", ""),
                    payload["content"],
                    payload.get("strategy", "soft"),
                    payload.get("status", "pending"),
                    payload.get("error_message", ""),
                    payload.get("commented_at", ""),
                    now,
                ),
            )
            return cursor.lastrowid

    def update_xhs_comment_task(self, task_id: int, payload: dict[str, Any]) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE xhs_comment_tasks SET
                    status = COALESCE(?, status),
                    error_message = COALESCE(?, error_message),
                    commented_at = COALESCE(?, commented_at)
                WHERE id = ?
                """,
                (
                    payload.get("status"),
                    payload.get("error_message"),
                    payload.get("commented_at"),
                    task_id,
                ),
            )

    def list_xhs_comment_tasks(
        self,
        status: str | None = None,
        platform: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as conn:
            if status:
                if platform:
                    rows = conn.execute(
                        "SELECT * FROM xhs_comment_tasks WHERE status = ? AND platform = ? ORDER BY id DESC",
                        (status, platform),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM xhs_comment_tasks WHERE status = ? ORDER BY id DESC",
                        (status,),
                    ).fetchall()
            else:
                if platform:
                    rows = conn.execute(
                        "SELECT * FROM xhs_comment_tasks WHERE platform = ? ORDER BY id DESC",
                        (platform,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT * FROM xhs_comment_tasks ORDER BY id DESC"
                    ).fetchall()
        return [dict(row) for row in rows]

    def get_xhs_comment_task(self, task_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM xhs_comment_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None

    # ==================== 产品管理 ====================

    def insert_product(self, payload: dict[str, Any]) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO products (
                    code, name, description, price, wechat_id,
                    features_json, target_tags_json, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["code"],
                    payload["name"],
                    payload.get("description", ""),
                    payload.get("price", ""),
                    payload.get("wechat_id", ""),
                    json.dumps(payload.get("features", []), ensure_ascii=False),
                    json.dumps(payload.get("target_tags", []), ensure_ascii=False),
                    payload.get("status", "active"),
                    now,
                    now,
                ),
            )
            return cursor.lastrowid

    def update_product(self, product_id: int, payload: dict[str, Any]) -> None:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE products SET
                    name = COALESCE(?, name),
                    description = COALESCE(?, description),
                    price = COALESCE(?, price),
                    wechat_id = COALESCE(?, wechat_id),
                    features_json = COALESCE(?, features_json),
                    target_tags_json = COALESCE(?, target_tags_json),
                    status = COALESCE(?, status),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    payload.get("name"),
                    payload.get("description"),
                    payload.get("price"),
                    payload.get("wechat_id"),
                    json.dumps(payload.get("features"), ensure_ascii=False) if payload.get("features") else None,
                    json.dumps(payload.get("target_tags"), ensure_ascii=False) if payload.get("target_tags") else None,
                    payload.get("status"),
                    now,
                    product_id,
                ),
            )

    def list_products(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM products WHERE status = 'active' ORDER BY id DESC"
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["features"] = json.loads(item.pop("features_json", "[]"))
            item["target_tags"] = json.loads(item.pop("target_tags_json", "[]"))
            result.append(item)
        return result

    def get_product(self, product_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE id = ?",
                (product_id,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["features"] = json.loads(item.pop("features_json", "[]"))
        item["target_tags"] = json.loads(item.pop("target_tags_json", "[]"))
        return item

    def get_product_by_code(self, code: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM products WHERE code = ?",
                (code,),
            ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["features"] = json.loads(item.pop("features_json", "[]"))
        item["target_tags"] = json.loads(item.pop("target_tags_json", "[]"))
        return item

    # ==================== 运营统计 ====================

    def insert_xhs_stat(self, payload: dict[str, Any]) -> int:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        today = datetime.now().strftime("%Y-%m-%d")
        with self._connect() as conn:
            # 检查今天是否已有记录
            existing = conn.execute(
                "SELECT id FROM xhs_stats WHERE date = ?",
                (today,),
            ).fetchone()

            if existing:
                conn.execute(
                    """
                    UPDATE xhs_stats SET
                        comments_success = comments_success + ?,
                        comments_failed = comments_failed + ?,
                        posts_searched = posts_searched + ?,
                        accounts_active = COALESCE(?, accounts_active)
                    WHERE date = ?
                    """,
                    (
                        payload.get("comments_success", 0),
                        payload.get("comments_failed", 0),
                        payload.get("posts_searched", 0),
                        payload.get("accounts_active"),
                        today,
                    ),
                )
                return existing[0]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO xhs_stats (
                        date, comments_success, comments_failed,
                        posts_searched, accounts_active, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        today,
                        payload.get("comments_success", 0),
                        payload.get("comments_failed", 0),
                        payload.get("posts_searched", 0),
                        payload.get("accounts_active", 0),
                        now,
                    ),
                )
                return cursor.lastrowid

    def get_xhs_stats(self, days: int = 7) -> dict[str, Any]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM xhs_stats
                ORDER BY date DESC
                LIMIT ?
                """,
                (days,),
            ).fetchall()

        total_success = 0
        total_failed = 0
        total_posts = 0
        records = []

        for row in rows:
            item = dict(row)
            total_success += item["comments_success"]
            total_failed += item["comments_failed"]
            total_posts += item["posts_searched"]
            records.append(item)

        return {
            "records": records,
            "total_success": total_success,
            "total_failed": total_failed,
            "total_posts": total_posts,
            "total_comments": total_success + total_failed,
            "success_rate": round(total_success / (total_success + total_failed) * 100, 1) if (total_success + total_failed) > 0 else 0,
        }

    def get_xhs_daily_stats(self, date: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM xhs_stats WHERE date = ?",
                (date,),
            ).fetchone()
        return dict(row) if row else None

    # ==================== Telegram 群组管理 ====================

    def insert_telegram_group(self, payload: dict[str, Any]) -> int:
        """添加 Telegram 群组"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO telegram_groups (
                    chat_id, title, username, type, member_count,
                    invite_link, is_blocked, block_reason, added_at, last_message_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["chat_id"],
                    payload.get("title", ""),
                    payload.get("username"),
                    payload.get("type", "group"),
                    payload.get("member_count"),
                    payload.get("invite_link"),
                    payload.get("is_blocked", 0),
                    payload.get("block_reason", ""),
                    now,
                    payload.get("last_message_at"),
                ),
            )
            return cursor.lastrowid

    def update_telegram_group(self, group_id: int, payload: dict[str, Any]) -> None:
        """更新 Telegram 群组信息"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_groups SET
                    title = COALESCE(?, title),
                    username = COALESCE(?, username),
                    member_count = COALESCE(?, member_count),
                    invite_link = COALESCE(?, invite_link),
                    is_blocked = COALESCE(?, is_blocked),
                    block_reason = COALESCE(?, block_reason),
                    last_message_at = COALESCE(?, last_message_at)
                WHERE id = ?
                """,
                (
                    payload.get("title"),
                    payload.get("username"),
                    payload.get("member_count"),
                    payload.get("invite_link"),
                    payload.get("is_blocked"),
                    payload.get("block_reason"),
                    payload.get("last_message_at"),
                    group_id,
                ),
            )

    def list_telegram_groups(
        self,
        blocked_only: bool = False,
        search_keyword: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出 Telegram 群组"""
        with self._connect() as conn:
            sql = "SELECT * FROM telegram_groups WHERE 1=1"
            params = []

            if blocked_only:
                sql += " AND is_blocked = 1"

            if search_keyword:
                sql += " AND title LIKE ?"
                params.append(f"%{search_keyword}%")

            sql += " ORDER BY added_at DESC"

            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_telegram_group(self, group_id: int) -> dict[str, Any] | None:
        """获取 Telegram 群组"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
        return dict(row) if row else None

    def get_telegram_group_by_chat_id(self, chat_id: int) -> dict[str, Any] | None:
        """通过 chat_id 获取 Telegram 群组"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_groups WHERE chat_id = ?",
                (chat_id,),
            ).fetchone()
        return dict(row) if row else None

    def delete_telegram_group(self, group_id: int) -> bool:
        """删除 Telegram 群组"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM telegram_groups WHERE id = ?",
                (group_id,),
            )
            return cursor.rowcount > 0

    def block_telegram_group(self, group_id: int, reason: str = "") -> None:
        """屏蔽 Telegram 群组"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE telegram_groups SET is_blocked = 1, block_reason = ? WHERE id = ?",
                (reason, group_id),
            )

    def unblock_telegram_group(self, group_id: int) -> None:
        """取消屏蔽 Telegram 群组"""
        with self._connect() as conn:
            conn.execute(
                "UPDATE telegram_groups SET is_blocked = 0, block_reason = '' WHERE id = ?",
                (group_id,),
            )

    def get_active_telegram_groups(self) -> list[dict[str, Any]]:
        """获取未屏蔽的群组列表"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM telegram_groups WHERE is_blocked = 0 ORDER BY title"
            ).fetchall()
        return [dict(row) for row in rows]

    # ==================== Telegram 用户账号 ====================

    def insert_telegram_user_account(self, payload: dict[str, Any]) -> int:
        """添加 Telegram 用户账号"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR REPLACE INTO telegram_user_accounts (
                    api_id, api_hash, phone, session_string, bot_username, added_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["api_id"],
                    payload["api_hash"],
                    payload["phone"],
                    payload.get("session_string", ""),
                    payload.get("bot_username", ""),
                    now,
                ),
            )
            return cursor.lastrowid

    def list_telegram_user_accounts(self) -> list[dict[str, Any]]:
        """获取所有 Telegram 用户账号"""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM telegram_user_accounts ORDER BY added_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_telegram_user_account(self, account_id: int) -> dict[str, Any] | None:
        """获取 Telegram 用户账号"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_user_accounts WHERE id = ?",
                (account_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_telegram_user_account(self, account_id: int) -> bool:
        """删除 Telegram 用户账号"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM telegram_user_accounts WHERE id = ?",
                (account_id,),
            )
            return cursor.rowcount > 0

    def update_telegram_user_account(self, account_id: int, payload: dict[str, Any]) -> None:
        """更新 Telegram 用户账号"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_user_accounts SET
                    session_string = COALESCE(?, session_string),
                    bot_username = COALESCE(?, bot_username)
                WHERE id = ?
                """,
                (
                    payload.get("session_string"),
                    payload.get("bot_username"),
                    account_id,
                ),
            )

    # ==================== 微信文章（搜狗微信爬虫） ====================

    def insert_wechat_article(self, payload: dict[str, Any]) -> int:
        """保存微信文章，使用 title + keyword 组合作为唯一标识避免重复"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = payload.get("title", "")
        keyword = payload.get("keyword", "")

        if not title:
            return -1

        with self._connect() as conn:
            # 先检查是否已存在（用 title + keyword 组合判断）
            existing = conn.execute(
                "SELECT id FROM wechat_articles WHERE title = ? AND keyword = ?",
                (title, keyword)
            ).fetchone()

            if existing:
                return existing[0]  # 返回已存在的ID，不插入

            cursor = conn.execute(
                """
                INSERT INTO wechat_articles (
                    title, link, source, author, pub_time, abstract, keyword, content,
                    qr_code_url, qr_code_type, crawled_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload.get("title"),
                    payload.get("link"),
                    payload.get("source"),
                    payload.get("author"),
                    payload.get("pub_time"),
                    payload.get("abstract"),
                    payload.get("keyword"),
                    payload.get("content"),
                    payload.get("qr_code_url"),
                    payload.get("qr_code_type"),
                    now,
                ),
            )
            return cursor.lastrowid

    def list_wechat_articles(
        self,
        keyword: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """获取微信文章列表"""
        sql = "SELECT * FROM wechat_articles"
        params = []

        if keyword:
            sql += " WHERE keyword = ?"
            params.append(keyword)

        sql += " ORDER BY crawled_at DESC LIMIT ?"
        params.append(limit)

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [dict(row) for row in rows]

    def get_wechat_article(self, article_id: int) -> dict[str, Any] | None:
        """获取微信文章详情"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM wechat_articles WHERE id = ?",
                (article_id,),
            ).fetchone()
            return dict(row) if row else None

    def delete_wechat_article(self, article_id: int) -> bool:
        """删除微信文章"""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM wechat_articles WHERE id = ?",
                (article_id,),
            )
            return cursor.rowcount > 0

    def clear_wechat_articles(self, keyword: str | None = None) -> int:
        """清空微信文章"""
        with self._connect() as conn:
            if keyword:
                cursor = conn.execute(
                    "DELETE FROM wechat_articles WHERE keyword = ?",
                    (keyword,),
                )
            else:
                cursor = conn.execute("DELETE FROM wechat_articles")
            return cursor.rowcount

    def get_blocked_keywords(self) -> list[str]:
        """获取黑名单关键词列表"""
        return ["sober", "greek", "Greek", "格致", "戒酒", "戒毒", "康复", "recovery", "aa"]

    def save_blocked_keywords(self, keywords: list[str]) -> None:
        """保存自定义黑名单关键词"""
        # 这里可以用配置文件或者数据库存储，目前使用默认列表
        # 如果需要持久化，可以添加到数据库的设置表中
        pass

    # ==================== Telegram 营销任务 ====================

    def insert_telegram_marketing_task(self, payload: dict[str, Any]) -> int:
        """创建 Telegram 营销任务"""
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT INTO telegram_marketing_tasks (
                    group_id, content, status, sent_at, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    payload["group_id"],
                    payload["content"],
                    payload.get("status", "pending"),
                    payload.get("sent_at", ""),
                    payload.get("error_message", ""),
                    now,
                ),
            )
            return cursor.lastrowid

    def update_telegram_marketing_task(
        self, task_id: int, payload: dict[str, Any]
    ) -> None:
        """更新 Telegram 营销任务"""
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE telegram_marketing_tasks SET
                    status = COALESCE(?, status),
                    sent_at = COALESCE(?, sent_at),
                    error_message = COALESCE(?, error_message)
                WHERE id = ?
                """,
                (
                    payload.get("status"),
                    payload.get("sent_at"),
                    payload.get("error_message"),
                    task_id,
                ),
            )

    def list_telegram_marketing_tasks(
        self,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """列出 Telegram 营销任务"""
        with self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM telegram_marketing_tasks WHERE status = ? ORDER BY id DESC",
                    (status,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM telegram_marketing_tasks ORDER BY id DESC"
                ).fetchall()
        return [dict(row) for row in rows]

    def get_telegram_marketing_task(self, task_id: int) -> dict[str, Any] | None:
        """获取 Telegram 营销任务"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM telegram_marketing_tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        return dict(row) if row else None
