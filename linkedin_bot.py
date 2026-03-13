"""
LinkedIn 自动营销机器人

能力：
1. 基于 Cookie 校验登录
2. 按关键词搜索帖子
3. 在帖子详情页尝试发表评论
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


class LinkedInBot:
    BASE_URL = "https://www.linkedin.com"
    SEARCH_URL = "https://www.linkedin.com/search/results/content/"

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
            self.last_error = "LinkedIn Cookie 不能为空"
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
                self.last_error = "LinkedIn Cookie 登录失败，请重新复制浏览器 Cookie"
                return False

            nickname = self._safe_text(
                [
                    (By.CSS_SELECTOR, ".profile-card-outline"),
                    (By.CSS_SELECTOR, ".feed-shared-update-v2__author-title"),
                    (By.CSS_SELECTOR, ".nav__profile-menu"),
                ]
            )
            self.account = XiaohongshuAccount(
                cookie=cookie,
                nickname=nickname or "LinkedIn User",
                status="online",
                last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            )
            return True
        except Exception as exc:
            self.last_error = f"LinkedIn Cookie 登录失败: {exc}"
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
                    "domain": ".linkedin.com",
                    "path": "/",
                    "secure": True,
                }
            )
        return cookies

    def _is_login_page(self) -> bool:
        if not self.driver:
            return True
        body = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        return "sign in" in body or "登录" in body

    def _safe_text(self, selectors: list[tuple]) -> str:
        """安全获取元素文本"""
        if not self.driver:
            return ""
        for selector in selectors:
            try:
                el = self.driver.find_element(*selector)
                if el:
                    return el.text.strip()
            except:
                continue
        return ""

    def search_posts(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            # 使用 LinkedIn 搜索 URL
            search_url = f"{self.SEARCH_URL}?keywords={quote(keyword)}&origin=GLOBAL_SEARCH_HEADER"
            self.driver.get(search_url)
            time.sleep(3)

            posts: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            scroll_count = 0
            max_scrolls = 10

            while len(posts) < limit and scroll_count < max_scrolls:
                # 解析当前页面帖子
                items = self.driver.find_elements(By.CSS_SELECTOR, ".feed-shared-update-v2")
                
                for item in items:
                    try:
                        post_id = item.get_attribute("data-id") or item.get_attribute("id") or str(time.time())
                        if post_id in seen_ids:
                            continue
                        seen_ids.add(post_id)

                        # 获取标题/内容
                        content_el = item.find_elements(By.CSS_SELECTOR, ".feed-shared-text")
                        content = content_el[0].text if content_el else ""

                        # 获取作者
                        author_el = item.find_elements(By.CSS_SELECTOR, ".feed-shared-update-v2__author")
                        author = author_el[0].text if author_el else "Unknown"

                        # 获取链接
                        link_el = item.find_elements(By.CSS_SELECTOR, "a[href*='/feed/']")
                        link = link_el[0].get_attribute("href") if link_el else ""

                        # 获取点赞数
                        like_el = item.find_elements(By.CSS_SELECTOR, ".social-details-social-activity .count-text")
                        likes_str = like_el[0].text if like_el else "0"
                        likes = self._parse_number(likes_str)

                        # 获取评论数
                        comment_el = item.find_elements(By.CSS_SELECTOR, ".comments-comment-item")
                        comments = len(comment_el) if comment_el else 0

                        if content or link:
                            posts.append({
                                "post_id": post_id,
                                "content": content[:500],
                                "author": author,
                                "url": link,
                                "likes": likes,
                                "comments": comments,
                            })

                        if len(posts) >= limit:
                            break
                    except Exception as e:
                        continue

                if len(posts) >= limit:
                    break

                # 滚动加载更多
                self.driver.execute_script("window.scrollBy(0, 800);")
                time.sleep(2)
                scroll_count += 1

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"搜索失败: {exc}"
            return []

    def _parse_number(self, text: str) -> int:
        """解析数字字符串"""
        text = text.strip().replace(",", "")
        multipliers = {"k": 1000, "K": 1000, "万": 10000}
        for suffix, mult in multipliers.items():
            if suffix in text:
                try:
                    return int(float(text.replace(suffix, "")) * mult)
                except:
                    return 0
        try:
            return int(text)
        except:
            return 0

    def comment_post(self, post_url: str, content: str) -> bool:
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            self.driver.get(post_url)
            time.sleep(3)

            # 找到评论输入框
            comment_box = None
            selectors = [
                ".comments-comment-box__input",
                ".feed-shared-update-v2__comments-container .comments-comment-box__input",
                ".comments-comment-box form",
                "button[aria-label='Comment']",
            ]
            
            for sel in selectors:
                try:
                    el = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if el:
                        comment_box = el
                        break
                except:
                    continue

            if not comment_box:
                # 尝试点击评论按钮打开输入框
                try:
                    comment_btn = self.driver.find_element(By.CSS_SELECTOR, "button[aria-label='Comment']")
                    comment_btn.click()
                    time.sleep(2)
                    comment_box = self.driver.find_element(By.CSS_SELECTOR, ".comments-comment-box__input")
                except:
                    pass

            if not comment_box:
                self.last_error = "未找到评论输入框"
                return False

            # 输入评论
            comment_box.click()
            time.sleep(1)
            self.driver.execute_script(f"arguments[0].innerHTML = '{content}';", comment_box)
            time.sleep(0.5)

            # 点击发送按钮
            send_selectors = [
                ".comments-comment-box__submit-button",
                "button[type='submit']",
            ]
            
            for sel in send_selectors:
                try:
                    send_btn = self.driver.find_element(By.CSS_SELECTOR, sel)
                    if send_btn and send_btn.is_enabled():
                        send_btn.click()
                        time.sleep(2)
                        return True
                except:
                    continue

            self.last_error = "未找到发送按钮"
            return False

        except Exception as exc:
            self.last_error = f"评论失败: {exc}"
            return False

    def batch_comment(self, posts: list[dict], comments: list[str]) -> list[dict]:
        """批量评论"""
        results = []
        for i, post in enumerate(posts):
            comment = random.choice(comments) if comments else "关注更多相关内容"
            success = self.comment_post(post["url"], comment)
            results.append({
                "post_id": post.get("post_id", ""),
                "content": comment,
                "success": success,
                "error": self.last_error if not success else "",
            })
            # 随机等待
            time.sleep(random.uniform(2, 5))
        return results
