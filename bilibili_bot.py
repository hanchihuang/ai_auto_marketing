"""
Bilibili 自动营销机器人

能力：
1. 基于 Cookie 校验登录
2. 按关键词搜索视频
3. 在视频详情页尝试发表评论
"""

from __future__ import annotations

import json
import random
import time
from datetime import datetime
from typing import Any, Optional
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from xiaohongshu import XiaohongshuAccount


class BilibiliBot:
    BASE_URL = "https://www.bilibili.com"
    SEARCH_URL = "https://search.bilibili.com/all"
    FAST_MODE = True

    def __init__(self) -> None:
        self.driver: Optional[webdriver.Chrome] = None
        self.account: Optional[XiaohongshuAccount] = None
        self.last_error = ""
        self.cookie_string = ""

    def init_driver(self, headless: bool = False) -> None:
        options = Options()
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
        )
        if headless:
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

    def close(self) -> None:
        if self.driver:
            self.driver.quit()
            self.driver = None

    def login_by_cookie(self, cookie: str) -> bool:
        if not self.driver:
            self.init_driver()

        self.last_error = ""
        cookie = (cookie or "").strip()
        if not cookie:
            self.last_error = "Bilibili Cookie 不能为空"
            return False

        if "SESSDATA=" not in cookie:
            self.last_error = "Bilibili Cookie 缺少 SESSDATA，无法登录"
            return False

        try:
            self.cookie_string = cookie
            self.driver.get(self.BASE_URL)
            time.sleep(1)
            for item in self._parse_cookie_string(cookie):
                self.driver.add_cookie(item)

            self.driver.get(self.BASE_URL)
            time.sleep(2)

            if self._is_login_page():
                self.last_error = "Bilibili Cookie 登录失败，请重新复制浏览器 Cookie"
                return False

            nickname = self._safe_text(
                [
                    (By.CSS_SELECTOR, ".header-entry-mini"),
                    (By.CSS_SELECTOR, ".header-avatar-wrap"),
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
            self.last_error = f"Bilibili Cookie 登录失败: {exc}"
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
                    "domain": ".bilibili.com",
                    "path": "/",
                    "secure": True,
                }
            )
        return cookies

    def _is_login_page(self) -> bool:
        if not self.driver:
            return True
        body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        return "登录" in body and "注册" in body and "发布" not in body

    def search_posts(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            self.driver.get(f"{self.SEARCH_URL}?keyword={quote(keyword)}")
            time.sleep(2)

            posts: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            scroll_count = 0

            while len(posts) < limit and scroll_count < 4:
                cards = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/video/BV']")
                for card in cards:
                    post = self._parse_video_card(card, keyword)
                    if not post or post["post_id"] in seen_ids:
                        continue
                    seen_ids.add(post["post_id"])
                    posts.append(post)
                    if len(posts) >= limit:
                        break

                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(0.8, 1.5))
                scroll_count += 1

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"搜索失败: {exc}"
            return []

    def _parse_video_card(self, link, keyword: str) -> Optional[dict[str, Any]]:
        try:
            href = (link.get_attribute("href") or "").split("?")[0]
            if "/video/" not in href:
                return None
            parsed = urlparse(href)
            post_id = parsed.path.rstrip("/").split("/")[-1]
            card = link.find_element(By.XPATH, "./ancestor::*[self::div or self::article][1]")
            title = (link.get_attribute("title") or link.text or f"视频 {post_id}").strip()
            author = self._find_within(card, [(By.CSS_SELECTOR, ".up-name"), (By.CSS_SELECTOR, ".bili-video-card__info--author")])
            image = self._find_attr_within(card, [(By.CSS_SELECTOR, "img")], "src")
            metric_text = card.text
            likes = self._extract_count(metric_text, ["点赞", "like"])
            comments = self._extract_count(metric_text, ["评论", "弹幕"])
            collects = self._extract_count(metric_text, ["收藏"])

            return {
                "post_id": post_id,
                "platform": "bilibili",
                "title": title,
                "content": title,
                "author": author,
                "author_id": "",
                "cover_image": image,
                "likes": likes,
                "comments": comments,
                "collects": collects,
                "tags": [],
                "url": href,
                "search_keyword": keyword,
                "found_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
        except Exception:
            return None

    def _extract_count(self, text: str, markers: list[str]) -> int:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for index, line in enumerate(lines):
            if any(marker.lower() in line.lower() for marker in markers) and index > 0:
                return self._parse_count(lines[index - 1])
        return 0

    def _parse_count(self, raw: str) -> int:
        text = (raw or "").strip().lower().replace(",", "")
        if not text:
            return 0
        try:
            if text.endswith("万"):
                return int(float(text[:-1]) * 10000)
            digits = "".join(ch for ch in text if ch.isdigit() or ch == ".")
            return int(float(digits)) if digits else 0
        except Exception:
            return 0

    def _find_within(self, element, selectors: list[tuple[str, str]]) -> str:
        for by, selector in selectors:
            try:
                value = element.find_element(by, selector).text.strip()
                if value:
                    return value
            except Exception:
                continue
        return ""

    def _find_attr_within(self, element, selectors: list[tuple[str, str]], attr: str) -> str:
        for by, selector in selectors:
            try:
                value = element.find_element(by, selector).get_attribute(attr) or ""
                if value:
                    if value.startswith("//"):
                        return f"https:{value}"
                    return value
            except Exception:
                continue
        return ""

    def is_post_web_accessible(self, post_url: str) -> bool:
        if not self.driver or not post_url:
            return False
        if self.FAST_MODE:
            return True
        try:
            self.driver.get(post_url)
            time.sleep(1.5)
            return not bool(self._detect_uncommentable_page())
        except Exception:
            return False

    def comment_post(self, post_id: str, content: str, post_url: str = "") -> bool:
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        url = post_url or f"{self.BASE_URL}/video/{post_id}"
        try:
            self.driver.get(url)
            time.sleep(2)

            page_error = self._detect_uncommentable_page()
            if page_error:
                self.last_error = page_error
                return False

            aid = self.driver.execute_script(
                "return (window.__INITIAL_STATE__ && (window.__INITIAL_STATE__.aid || (window.__INITIAL_STATE__.videoData && window.__INITIAL_STATE__.videoData.aid))) || null;"
            )
            if aid:
                api_success, api_error = self._comment_via_api(int(aid), content, self.driver.current_url)
                if api_success:
                    return True
                self.last_error = api_error
                return False

            editor = self._find_clickable(
                [
                    (By.CSS_SELECTOR, "textarea.reply-box-textarea"),
                    (By.CSS_SELECTOR, "textarea.comment-textarea"),
                    (By.XPATH, '//textarea[contains(@placeholder, "发一条友善的评论")]'),
                    (By.XPATH, '//textarea[contains(@placeholder, "说点什么")]'),
                ],
                timeout=8,
            )
            if editor is None:
                self.last_error = "未找到哔哩哔哩评论输入框，可能当前账号无评论权限或页面结构变化"
                return False

            self._safe_click(editor)
            editor.clear()
            editor.send_keys(content)
            time.sleep(1)

            submit = self._find_clickable(
                [
                    (By.CSS_SELECTOR, ".comment-submit"),
                    (By.XPATH, '//button[contains(text(), "发布")]'),
                    (By.XPATH, '//button[contains(text(), "评论")]'),
                ],
                timeout=8,
            )
            if submit is None:
                self.last_error = "未找到哔哩哔哩评论发送按钮"
                return False

            self._safe_click(submit)
            time.sleep(3)
            return True
        except Exception as exc:
            self.last_error = f"评论失败: {exc}"
            return False

    def _comment_via_api(self, aid: int, content: str, referer_url: str) -> tuple[bool, str]:
        csrf = self._get_cookie_value("bili_jct")
        if not csrf:
            return False, "Bilibili Cookie 缺少 bili_jct，无法调用评论接口"

        payload = urlencode(
            {
                "oid": str(aid),
                "type": "1",
                "message": content,
                "plat": "1",
                "csrf": csrf,
            }
        ).encode("utf-8")

        req = Request(
            "https://api.bilibili.com/x/v2/reply/add",
            data=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "Origin": self.BASE_URL,
                "Referer": referer_url,
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
                ),
                "Cookie": self.cookie_string,
            },
            method="POST",
        )

        try:
            with urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="ignore"))
            if data.get("code") == 0:
                return True, ""
            return False, f"哔哩哔哩评论接口失败: {data.get('message') or data.get('msg') or data.get('code')}"
        except Exception as exc:
            return False, f"哔哩哔哩评论接口请求失败: {exc}"

    def _get_cookie_value(self, name: str) -> str:
        if self.cookie_string:
            for chunk in self.cookie_string.split(";"):
                part = chunk.strip()
                if part.startswith(f"{name}="):
                    return part.split("=", 1)[1]
        if self.driver:
            for cookie in self.driver.get_cookies():
                if cookie.get("name") == name:
                    return cookie.get("value", "")
        return ""

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
        try:
            self.driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center', inline: 'center'});",
                element,
            )
            time.sleep(0.3)
        except Exception:
            pass

        try:
            element.click()
            return
        except Exception:
            pass

        self.driver.execute_script("arguments[0].click();", element)

    def _safe_text(self, selectors: list[tuple[str, str]]) -> str:
        for by, selector in selectors:
            try:
                value = self.driver.find_element(by, selector).text.strip()
                if value:
                    return value
            except Exception:
                continue
        return ""

    def _detect_uncommentable_page(self) -> str:
        if not self.driver:
            return "浏览器未启动"
        current_url = self.driver.current_url or ""
        body = self.driver.find_element(By.TAG_NAME, "body").text
        blocked_markers = ["视频不见了", "稿件投诉", "啊叻？视频不见了？", "稍后再试"]
        if "/video/" not in current_url:
            return "当前页面不是哔哩哔哩视频详情页，无法评论"
        if any(marker in body for marker in blocked_markers):
            return "该哔哩哔哩内容当前不可访问，无法在网页端评论"
        if "登录后" in body and "评论" in body and "textarea" not in current_url:
            return "当前账号可能未登录或没有评论权限"
        return ""
