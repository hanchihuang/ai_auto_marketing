"""
X.com 自动营销系统核心模块

说明：
1. 兼容现有应用对 XiaohongshuBot 命名的引用，实际行为已切换为 X.com
2. 账号登录只支持基于浏览器 Cookie 的登录校验
3. 搜索结果与评论动作均基于 X.com 网页版 DOM
"""

from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlparse

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait


class CommentStrategy(Enum):
    SOFT = "soft"
    MEDIUM = "medium"
    HARD = "hard"


COMMENT_TEMPLATES = {
    CommentStrategy.SOFT: [
        "这个话题说得很准，{product} 在这类场景下确实挺省事。",
        "同感，我最近也在用 {product} 处理类似问题。",
        "这个角度不错，顺手补充下 {product} 也挺适合。",
        "感谢分享，我觉得 {product} 在这里也有参考价值。",
        "这条很有共鸣，{product} 的确能解决一部分痛点。",
    ],
    CommentStrategy.MEDIUM: [
        "{product} 可以一起看看，处理这个问题还挺直接。",
        "如果想提高效率，{product} 这个方案值得试一下。",
        "相关工具里我更推荐 {product}，上手成本不高。",
        "这个方向上，{product} 的体验会更完整一些。",
    ],
    CommentStrategy.HARD: [
        "要解决这个问题可以直接看 {product}。",
        "{product} 已经覆盖这类需求了，需要的话可以了解下。",
        "如果你就在找现成方案，{product} 可以直接用。",
    ],
}


@dataclass
class XiaohongshuAccount:
    id: Optional[int] = None
    phone: str = ""
    cookie: str = ""
    nickname: str = ""
    avatar: str = ""
    follower_count: int = 0
    following_count: int = 0
    note_count: int = 0
    status: str = "offline"
    created_at: str = ""
    last_login: str = ""


@dataclass
class HotPost:
    id: Optional[int] = None
    post_id: str = ""
    title: str = ""
    content: str = ""
    author: str = ""
    author_id: str = ""
    cover_image: str = ""
    likes: int = 0
    comments: int = 0
    collects: int = 0
    tags: list[str] = field(default_factory=list)
    url: str = ""
    search_keyword: str = ""
    found_at: str = ""


@dataclass
class CommentTask:
    id: Optional[int] = None
    post_id: str = ""
    post_title: str = ""
    content: str = ""
    strategy: str = "soft"
    status: str = "pending"
    error_message: str = ""
    commented_at: str = ""


@dataclass
class Product:
    code: str = ""
    name: str = ""
    description: str = ""
    price: str = ""
    wechat_id: str = ""
    features: list[str] = field(default_factory=list)
    target_tags: list[str] = field(default_factory=list)


class XiaohongshuBot:
    """兼容旧类名，实际操作 X.com"""

    BASE_URL = "https://x.com"

    def __init__(self, config_path: Optional[Path] = None):
        self.driver: Optional[webdriver.Chrome] = None
        self.account: Optional[XiaohongshuAccount] = None
        self.config = self._load_config(config_path)
        self.last_error = ""

    def _load_config(self, config_path: Optional[Path]) -> dict[str, Any]:
        if config_path and config_path.exists():
            return json.loads(config_path.read_text(encoding="utf-8"))
        return {
            "comment_delay": (3, 8),
            "scroll_delay": (2, 4),
            "headless": False,
        }

    def init_driver(self, headless: bool = False) -> None:
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
        )
        if headless or self.config.get("headless"):
            options.add_argument("--headless=new")
        service = Service("/usr/bin/chromedriver")
        self.driver = webdriver.Chrome(service=service, options=options)
        self.driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
                    Object.defineProperty(navigator, 'webdriver', {
                        get: () => undefined
                    })
                """
            },
        )

    def login_by_phone(self, phone: str, password: str) -> bool:
        self.last_error = "X.com 版本当前只支持 Cookie 登录"
        return False

    def login_by_qrcode(self, wait_seconds: int = 120) -> bool:
        self.last_error = "X.com 网页版未接入扫码登录，请使用 Cookie 登录"
        return False

    def login_by_cookie(self, cookie: str) -> bool:
        if not self.driver:
            self.init_driver()

        self.last_error = ""
        cookie = (cookie or "").strip()
        if not cookie:
            self.last_error = "Cookie 不能为空"
            return False

        if "auth_token=" not in cookie:
            self.last_error = "X.com Cookie 缺少 auth_token，无法登录"
            return False

        try:
            self.driver.get(self.BASE_URL)
            time.sleep(2)
            for item in self._parse_cookie_string(cookie):
                self.driver.add_cookie(item)

            self.driver.get(f"{self.BASE_URL}/home")
            time.sleep(5)

            if self._is_login_page():
                self.last_error = "Cookie 登录失败，请重新从浏览器复制有效的 X.com Cookie"
                return False

            nickname = self._safe_text(
                [
                    (By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"] span'),
                    (By.XPATH, '//a[@href="/home"]'),
                ]
            )
            self.account = XiaohongshuAccount(
                cookie=cookie,
                nickname=nickname,
                status="online",
                last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            return True
        except Exception as exc:
            self.last_error = f"Cookie 登录失败: {exc}"
            return False

    def _parse_cookie_string(self, cookie: str) -> list[dict[str, Any]]:
        cookies = []
        for chunk in cookie.split(";"):
            part = chunk.strip()
            if not part or "=" not in part:
                continue
            name, value = part.split("=", 1)
            cookies.append(
                {
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".x.com",
                    "path": "/",
                    "secure": True,
                }
            )
        return cookies

    def _is_login_page(self) -> bool:
        if not self.driver:
            return True
        current_url = (self.driver.current_url or "").lower()
        body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        return "/i/flow/login" in current_url or "log in to x" in body or "登录 x" in body

    def search_posts(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            self.driver.get(f"{self.BASE_URL}/search?q={quote(keyword)}&src=typed_query&f=live")
            time.sleep(5)

            if self._is_login_page():
                self.last_error = "当前账号未登录 X.com，无法执行搜索"
                return []

            posts: list[dict[str, Any]] = []
            scroll_count = 0
            seen_ids: set[str] = set()

            while len(posts) < limit and scroll_count < 10:
                articles = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
                for article in articles:
                    post = self._parse_tweet(article, keyword)
                    if not post or post["post_id"] in seen_ids:
                        continue
                    # 过滤 Sober 用户发布的帖子
                    if self._should_filter_author(post.get("author", "")):
                        continue
                    seen_ids.add(post["post_id"])
                    posts.append(post)
                    if len(posts) >= limit:
                        break

                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(*self.config.get("scroll_delay", (2, 4))))
                scroll_count += 1

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"搜索失败: {exc}"
            return []

    def search_top_influencers(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """搜索关键词领域最受欢迎的博主，按影响力排序"""
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            # 方式1: 直接访问搜索 URL
            search_url = f"{self.BASE_URL}/search?q={quote(keyword)}&src=typed_query"
            self.driver.get(search_url)
            time.sleep(6)

            # 记录当前 URL 用于调试
            current_url = self.driver.current_url
            print(f"[搜索博主] 当前URL: {current_url}")

            if self._is_login_page():
                self.last_error = "当前账号未登录 X.com，无法执行搜索"
                return []

            # 检查页面是否正常加载了搜索结果
            page_source = self.driver.page_source
            print(f"[搜索博主] 页面包含搜索: {'Search' in page_source or '搜索' in page_source}")
            if "搜索" not in page_source and "Search" not in page_source:
                # 方式2: 如果 URL 方式失败，尝试手动点击搜索框并输入
                try:
                    # 尝试多种搜索框选择器
                    search_selectors = [
                        'input[aria-label="Search"]',
                        'input[data-testid="SearchBox_Input"]',
                        'input[placeholder*="Search"]',
                        'input[placeholder*="搜索"]',
                        'input[type="text"][role="combobox"]',
                    ]
                    search_input = None
                    for selector in search_selectors:
                        try:
                            search_input = self.driver.find_element(By.CSS_SELECTOR, selector)
                            if search_input:
                                break
                        except:
                            continue
                    
                    if search_input:
                        search_input.click()
                        time.sleep(2)
                        search_input.clear()
                        search_input.send_keys(keyword)
                        search_input.send_keys(Keys.RETURN)
                        time.sleep(5)
                except Exception as e:
                    self.last_error = f"自动输入搜索词失败: {e}"

            # 切换到热门标签（如果有的话）
            try:
                top_tab = self.driver.find_element(By.XPATH, '//a[contains(@href, "f=top") or contains(text(), "热门") or contains(text(), "Top")]')
                if top_tab:
                    top_tab.click()
                    time.sleep(3)
            except Exception:
                pass

            # 收集帖子和作者信息
            author_stats: dict[str, dict[str, Any]] = {}
            scroll_count = 0
            max_scrolls = 20

            def get_articles():
                els = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
                if not els:
                    els = self.driver.find_elements(By.CSS_SELECTOR, 'article[role="article"]')
                return els

            while scroll_count < max_scrolls:
                articles = get_articles()
                for article in articles:
                    post = self._parse_tweet_for_influencer(article, keyword)
                    if not post:
                        continue
                    author_id = post.get("author_id", "").strip()
                    author_name = (post.get("author", "") or "").strip() or author_id
                    if not author_id or self._should_filter_author(author_name):
                        continue

                    if author_id not in author_stats:
                        author_stats[author_id] = {
                            "author_id": author_id,
                            "author": author_name,
                            "total_likes": 0,
                            "total_posts": 0,
                            "posts": [],
                        }

                    stats = author_stats[author_id]
                    stats["total_likes"] += post.get("likes", 0)
                    stats["total_posts"] += 1
                    stats["posts"].append({
                        "post_id": post.get("post_id", ""),
                        "content": post.get("content", "")[:100],
                        "likes": post.get("likes", 0),
                        "url": post.get("url", ""),
                    })

                # 检查是否已收集到足够多的作者
                if len(author_stats) >= limit * 2:
                    break

                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(*self.config.get("scroll_delay", (2, 4))))
                scroll_count += 1

            # 按总点赞数排序，筛选出最受欢迎的博主
            influencers = list(author_stats.values())
            influencers.sort(key=lambda x: x["total_likes"], reverse=True)

            # 返回调试信息：显示每个作者收集到的帖子数和点赞数
            debug_info = []
            for inf in influencers[:10]:
                debug_info.append({
                    "author": inf["author"],
                    "posts_collected": inf["total_posts"],
                    "total_likes": inf["total_likes"],
                })

            # 计算平均点赞并返回结果
            result = []
            for inf in influencers[:limit]:
                avg_likes = inf["total_likes"] // inf["total_posts"] if inf["total_posts"] > 0 else 0
                result.append({
                    "author_id": inf["author_id"],
                    "author": inf["author"],
                    "total_posts": inf["total_posts"],
                    "total_likes": inf["total_likes"],
                    "avg_likes": avg_likes,
                    "posts": inf["posts"][:5],
                })

            if not result:
                self.last_error = f"未找到博主。调试信息: {debug_info}"

            return result
        except Exception as exc:
            self.last_error = f"搜索博主失败: {exc}"
            return []

    def _parse_tweet_for_influencer(self, article, keyword: str) -> Optional[dict[str, Any]]:
        """解析推文用于博主分析"""
        try:
            # 获取推文内容
            text = self._find_within(article, [(By.CSS_SELECTOR, '[data-testid="tweetText"]')])

            # 获取推文链接
            post_link = self._find_attr_within(
                article,
                [(By.XPATH, './/a[contains(@href, "/status/")]')],
                "href",
            )
            if not post_link:
                return None

            parsed = urlparse(post_link)
            path = parsed.path.rstrip("/")
            parts = [p for p in path.split("/") if p]
            post_id = parts[-1] if parts else ""
            # 路径通常为 username/status/postid 或 /username/status/postid
            author_id = parts[0] if len(parts) >= 3 else (parts[0] if parts else "")

            # 尝试多种方式获取作者显示名，最终用 author_id 兜底
            author = ""
            try:
                user_links = article.find_elements(By.XPATH, './/a[contains(@href, "/") and not(contains(@href, "/status/")) and not(contains(@href, "?"))]')
                for link in user_links:
                    href = (link.get_attribute("href") or "").strip()
                    if not href or "status" in href:
                        continue
                    if "x.com" in href.lower() or "twitter.com" in href.lower():
                        segs = href.rstrip("/").split("/")
                        uname = segs[-1] if segs else ""
                        if uname and uname != "search" and "?" not in uname:
                            author = uname
                            break
            except Exception:
                pass

            if not author:
                author = self._find_within(
                    article,
                    [
                        (By.CSS_SELECTOR, '[data-testid="User-Name"]'),
                        (By.XPATH, './/div[@data-testid="User-Name"]'),
                        (By.CSS_SELECTOR, '[data-testid="User-Name"] span'),
                    ],
                )

            if not author:
                import re
                mentions = re.findall(r"@([a-zA-Z0-9_]+)", article.text)
                if mentions:
                    author = mentions[0]

            author = (author or "").strip() or author_id
            if not author_id:
                author_id = author
            if not author_id:
                return None

            metric_text = article.text
            likes = self._extract_metric(metric_text, "like")
            comments = self._extract_metric(metric_text, "repl")

            return {
                "post_id": post_id,
                "content": text or "",
                "author": author,
                "author_id": author_id,
                "likes": likes,
                "comments": comments,
                "url": post_link.split("?")[0],
                "search_keyword": keyword,
            }
        except Exception:
            return None

    def get_user_posts(self, username: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取指定用户的最近帖子"""
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            # 访问用户主页
            user_url = f"{self.BASE_URL}/{username.lstrip('@')}"
            self.driver.get(user_url)
            time.sleep(5)

            if self._is_login_page():
                self.last_error = "当前账号未登录 X.com，无法获取用户帖子"
                return []

            posts: list[dict[str, Any]] = []
            scroll_count = 0
            seen_ids: set[str] = set()

            while len(posts) < limit and scroll_count < 15:
                articles = self.driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
                for article in articles:
                    post = self._parse_tweet_simple(article)
                    if not post or post["post_id"] in seen_ids:
                        continue
                    seen_ids.add(post["post_id"])
                    posts.append(post)
                    if len(posts) >= limit:
                        break

                if len(posts) >= limit:
                    break

                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(*self.config.get("scroll_delay", (2, 4))))
                scroll_count += 1

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"获取用户帖子失败: {exc}"
            return []

    def _parse_tweet_simple(self, article) -> Optional[dict[str, Any]]:
        """简化版推文解析"""
        try:
            text = self._find_within(article, [(By.CSS_SELECTOR, '[data-testid="tweetText"]')])
            post_link = self._find_attr_within(
                article,
                [(By.XPATH, './/a[contains(@href, "/status/")]')],
                "href",
            )
            if not post_link:
                return None

            parsed = urlparse(post_link)
            path = parsed.path.rstrip("/")
            post_id = path.split("/")[-1]
            author_id = path.split("/")[1] if len(path.split("/")) > 2 else ""

            metric_text = article.text
            likes = self._extract_metric(metric_text, "like")
            comments = self._extract_metric(metric_text, "repl")

            content = text or ""
            title = (content[:80] + "...") if len(content) > 80 else (content or f"推文 {post_id}")

            return {
                "post_id": post_id,
                "title": title,
                "content": content,
                "author_id": author_id,
                "likes": likes,
                "comments": comments,
                "url": post_link,
            }
        except Exception:
            return None

    def _should_filter_author(self, author_name: str) -> bool:
        """检查作者名是否应该被过滤（包含 Sober/sober）"""
        if not author_name:
            return False
        author_lower = author_name.lower()
        return "sober" in author_lower

    def _parse_tweet(self, article, keyword: str) -> Optional[dict[str, Any]]:
        try:
            text = self._find_within(article, [(By.CSS_SELECTOR, '[data-testid="tweetText"]')])
            post_link = self._find_attr_within(
                article,
                [(By.XPATH, './/a[contains(@href, "/status/")]')],
                "href",
            )
            if not post_link:
                return None

            parsed = urlparse(post_link)
            path = parsed.path.rstrip("/")
            post_id = path.split("/")[-1]
            author_id = path.split("/")[1] if len(path.split("/")) > 2 else ""
            author = self._find_within(
                article,
                [
                    (By.CSS_SELECTOR, '[data-testid="User-Name"]'),
                    (By.XPATH, './/div[@data-testid="User-Name"]'),
                ],
            )

            image = self._find_attr_within(article, [(By.CSS_SELECTOR, 'img[src*="twimg.com/media"]')], "src")
            metric_text = article.text
            likes = self._extract_metric(metric_text, "like")
            comments = self._extract_metric(metric_text, "repl")
            collects = self._extract_metric(metric_text, "bookmark")

            content = text or ""
            title = (content[:80] + "...") if len(content) > 80 else (content or f"推文 {post_id}")

            return {
                "post_id": post_id,
                "title": title,
                "content": content,
                "author": author,
                "author_id": author_id,
                "cover_image": image,
                "likes": likes,
                "comments": comments,
                "collects": collects,
                "tags": [],
                "url": post_link.split("?")[0],
                "search_keyword": keyword,
                "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception:
            return None

    def _extract_metric(self, text: str, token: str) -> int:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        
        # 情况1: "123 Like" 同一行
        for line in lines:
            lower = line.lower()
            if token in lower:
                # 提取数字
                import re
                numbers = re.findall(r'[\d,.]+', line)
                for num in numbers:
                    count = self._parse_count(num)
                    if count > 0:
                        return count
        
        # 情况2: "123" 在 "Like" 前面一行
        for index, line in enumerate(lines):
            lower = line.lower()
            if token in lower and index > 0:
                count = self._parse_count(lines[index - 1])
                if count > 0:
                    return count
        
        # 情况3: "Like" 在 "123" 前面一行
        for index, line in enumerate(lines):
            lower = line.lower()
            if token in lower and index < len(lines) - 1:
                count = self._parse_count(lines[index + 1])
                if count > 0:
                    return count
        
        return 0

    def _parse_count(self, raw: str) -> int:
        text = (raw or "").strip().lower().replace(",", "")
        if not text:
            return 0
        try:
            if text.endswith("k"):
                return int(float(text[:-1]) * 1000)
            if text.endswith("m"):
                return int(float(text[:-1]) * 1000000)
            digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
            return int(float(digits)) if digits else 0
        except Exception:
            return 0

    def _find_within(self, element, selectors: list[tuple[str, str]]) -> str:
        for by, selector in selectors:
            try:
                text = element.find_element(by, selector).text.strip()
                if text:
                    return text
            except Exception:
                continue
        return ""

    def _find_attr_within(self, element, selectors: list[tuple[str, str]], attr: str) -> str:
        for by, selector in selectors:
            try:
                value = element.find_element(by, selector).get_attribute(attr) or ""
                if value:
                    return value
            except Exception:
                continue
        return ""

    def _safe_text(self, selectors: list[tuple[str, str]]) -> str:
        for by, selector in selectors:
            try:
                value = self.driver.find_element(by, selector).text.strip()
                if value:
                    return value
            except Exception:
                continue
        return ""

    def comment_post(self, post_id: str, content: str, post_url: str = "") -> bool:
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        candidate_url = post_url or f"{self.BASE_URL}/i/web/status/{post_id}"
        try:
            self.driver.get(candidate_url)
            time.sleep(5)

            page_error = self._detect_uncommentable_page()
            if page_error:
                self.last_error = page_error
                return False

            self._dismiss_overlays()
            editor = self._find_reply_editor(timeout=4)
            if editor is None:
                reply_button = self._find_clickable(
                    [
                        (By.CSS_SELECTOR, '[data-testid="reply"]'),
                        (By.XPATH, '//button[contains(@aria-label, "Reply") or contains(@aria-label, "回复")]'),
                        (By.XPATH, '//*[contains(@aria-label, "Reply") or contains(@aria-label, "回复")]/ancestor::button[1]'),
                    ],
                    timeout=8,
                )
                if reply_button is not None:
                    self._safe_click(reply_button)
                    time.sleep(1.5)
                    self._dismiss_overlays()
                editor = self._find_reply_editor(timeout=8)
            if editor is None:
                self.last_error = "未找到回复输入框，可能当前账号无回复权限或页面结构变化"
                return False

            self._safe_click(editor)
            self.driver.execute_script("arguments[0].focus();", editor)
            try:
                editor.send_keys(Keys.CONTROL, "a")
                editor.send_keys(Keys.DELETE)
            except Exception:
                pass
            editor.send_keys(content)
            time.sleep(1)

            send_button = self._find_clickable(
                [
                    (By.CSS_SELECTOR, '[data-testid="tweetButton"]'),
                    (By.CSS_SELECTOR, '[data-testid="tweetButtonInline"]'),
                    (By.XPATH, '//div[@role="dialog"]//button[@data-testid="tweetButton"]'),
                    (By.XPATH, '//span[text()="Reply"]/ancestor::button'),
                ],
                timeout=8,
            )
            if send_button is None:
                self.last_error = "未找到回复发送按钮"
                return False

            self._safe_click(send_button)
            time.sleep(3)
            return True
        except Exception as exc:
            self.last_error = f"回复失败: {exc}"
            return False

    def _find_reply_editor(self, timeout: int = 5):
        selectors = [
            (By.CSS_SELECTOR, '[data-testid="tweetTextarea_0"]'),
            (By.XPATH, '//div[@role="dialog"]//*[@role="textbox"]'),
            (By.XPATH, '//*[@role="textbox" and @contenteditable="true"]'),
            (By.XPATH, '//*[@role="textbox"]'),
        ]

        end_at = time.time() + timeout
        while time.time() < end_at:
            for by, selector in selectors:
                try:
                    elements = self.driver.find_elements(by, selector)
                    for element in elements:
                        if not element.is_displayed():
                            continue
                        contenteditable = (element.get_attribute("contenteditable") or "").lower()
                        role = (element.get_attribute("role") or "").lower()
                        if role == "textbox" or contenteditable == "true":
                            return element
                except Exception:
                    continue
            time.sleep(0.5)
        return None

    def _find_clickable(self, selectors: list[tuple[str, str]], timeout: int = 5):
        for by, selector in selectors:
            try:
                return WebDriverWait(self.driver, timeout).until(
                    EC.element_to_be_clickable((by, selector))
                )
            except Exception:
                continue
        return None

    def _safe_click(self, element) -> None:
        """优先普通点击，失败后退化为滚动 + JS 点击"""
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                element,
            )
            time.sleep(0.3)
        except Exception:
            pass

        try:
            ActionChains(self.driver).move_to_element(element).pause(0.2).click(element).perform()
            return
        except Exception:
            pass

        try:
            element.click()
            return
        except Exception:
            pass

        try:
            self.driver.execute_script(
                """
                const el = arguments[0];
                el.focus();
                el.dispatchEvent(new MouseEvent('mouseover', {bubbles: true}));
                el.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}));
                el.dispatchEvent(new MouseEvent('mouseup', {bubbles: true}));
                el.click();
                """,
                element,
            )
            return
        except Exception as exc:
            raise exc

    def _dismiss_overlays(self) -> None:
        if not self.driver:
            return
        try:
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(0.3)
        except Exception:
            pass

        for selector in [
            '[data-testid="sheetDialog"] [aria-label="Close"]',
            '[aria-label="Close"]',
            '[data-testid="app-bar-close"]',
        ]:
            try:
                close_button = self.driver.find_element(By.CSS_SELECTOR, selector)
                if close_button.is_displayed():
                    self._safe_click(close_button)
                    time.sleep(0.3)
                    break
            except Exception:
                continue

    def _detect_uncommentable_page(self) -> str:
        if not self.driver:
            return "浏览器未启动"

        current_url = (self.driver.current_url or "").lower()
        body = self.driver.find_element(By.TAG_NAME, "body").text.lower()

        if self._is_login_page():
            return "当前页面跳转到了 X.com 登录页，Cookie 可能已失效"
        if "/status/" not in current_url:
            return "当前页面不是推文详情页，无法直接回复"
        blocked_markers = [
            "something went wrong",
            "this post is unavailable",
            "帖子不可用",
            "you’re unable to view this post",
            "cannot retrieve posts at this time",
        ]
        if any(marker in body for marker in blocked_markers):
            return "该推文当前不可访问，无法在网页端回复"
        return ""

    def is_post_web_accessible(self, post_url: str) -> bool:
        if not self.driver or not post_url:
            return False
        try:
            self.driver.get(post_url)
            time.sleep(3)
            return not bool(self._detect_uncommentable_page())
        except Exception:
            return False

    def batch_comment(
        self,
        posts: list[dict[str, Any]],
        product: Product,
        strategy: CommentStrategy = CommentStrategy.SOFT,
        max_comments: int = 20,
    ) -> list[CommentTask]:
        results = []
        commented = 0
        for post in posts:
            if commented >= max_comments:
                break
            comment_text = self.generate_comment(product, strategy)
            success = self.comment_post(post["post_id"], comment_text, post.get("url", ""))
            task = CommentTask(
                post_id=post["post_id"],
                post_title=post.get("title", ""),
                content=comment_text,
                strategy=strategy.value,
                status="success" if success else "failed",
                error_message="" if success else (self.last_error or "回复失败"),
                commented_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S") if success else "",
            )
            results.append(task)
            if success:
                commented += 1
            time.sleep(random.uniform(*self.config.get("comment_delay", (3, 8))))
        return results

    def generate_comment(self, product: Product, strategy: CommentStrategy = CommentStrategy.SOFT) -> str:
        template = random.choice(COMMENT_TEMPLATES[strategy])
        return template.format(
            product=product.name,
            wechat=product.wechat_id,
            price=product.price,
        )

    def get_profile(self) -> Optional[dict[str, Any]]:
        if not self.driver:
            return None
        try:
            self.driver.get(f"{self.BASE_URL}/home")
            time.sleep(3)
            nickname = self._safe_text([(By.CSS_SELECTOR, '[data-testid="SideNav_AccountSwitcher_Button"] span')])
            return {"nickname": nickname}
        except Exception:
            return None

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None


class CommentGenerator:
    def __init__(self, product: Product):
        self.product = product

    def _promo_link(self) -> str:
        sources = [self.product.description, self.product.wechat_id]
        for source in sources:
            if not source:
                continue
            match = re.search(r"https?://\S+", source)
            if match:
                return match.group(0).rstrip(".,);]")
        return ""

    def generate_soft_comment(self) -> str:
        promo_link = self._promo_link()
        templates = [
            f"这个方向我也关注过，{self.product.name} 在类似场景下挺顺手。链接：{promo_link}",
            f"补充一个思路：{self.product.name} 也能解决这个问题。链接：{promo_link}",
            f"说得很对，我最近就在用 {self.product.name} 做这件事。链接：{promo_link}",
        ]
        if not promo_link:
            templates = [
                f"这个方向我也关注过，{self.product.name} 在类似场景下挺顺手。",
                f"补充一个思路：{self.product.name} 也能解决这个问题。",
                f"说得很对，我最近就在用 {self.product.name} 做这件事。",
            ]
        return random.choice(templates)

    def generate_medium_comment(self) -> str:
        promo_link = self._promo_link()
        templates = [
            f"如果你在找现成方案，可以看看 {self.product.name}。链接：{promo_link}",
            f"{self.product.name} 在这个场景下会更直接一点。链接：{promo_link}",
            f"这种需求我一般会用 {self.product.name} 处理。链接：{promo_link}",
        ]
        if not promo_link:
            templates = [
                f"如果你在找现成方案，可以看看 {self.product.name}。",
                f"{self.product.name} 在这个场景下会更直接一点。",
                f"这种需求我一般会用 {self.product.name} 处理。",
            ]
        return random.choice(templates)

    def generate_hard_comment(self) -> str:
        promo_link = self._promo_link()
        templates = [
            f"需要现成方案的话可以直接看 {self.product.name}。链接：{promo_link}",
            f"{self.product.name} 就是针对这类需求做的。链接：{promo_link}",
            f"要落地的话，{self.product.name} 会更省时间。链接：{promo_link}",
        ]
        if not promo_link:
            templates = [
                f"需要现成方案的话可以直接看 {self.product.name}。",
                f"{self.product.name} 就是针对这类需求做的。",
                f"要落地的话，{self.product.name} 会更省时间。",
            ]
        return random.choice(templates)

    def generate_comment(self, strategy: CommentStrategy = CommentStrategy.SOFT) -> str:
        generators = {
            CommentStrategy.SOFT: self.generate_soft_comment,
            CommentStrategy.MEDIUM: self.generate_medium_comment,
            CommentStrategy.HARD: self.generate_hard_comment,
        }
        return generators[strategy]()


def load_products(config_path: Path) -> list[Product]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return [
        Product(
            code=p["code"],
            name=p["name"],
            description=p.get("description", ""),
            price=p.get("price", ""),
            wechat_id=p.get("wechat_id", ""),
            features=p.get("features", []),
            target_tags=p.get("target_tags", []),
        )
        for p in data
    ]
