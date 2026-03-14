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
        options.add_argument("--disable-gpu")
        options.add_argument("--disable-software-rasterizer")
        options.add_argument(
            "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
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

    def search_top_influencers(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """搜索关键词领域最受欢迎的博主，按粉丝数/影响力排序"""
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            # 1. 先访问搜索页面
            self.driver.get(self.SEARCH_URL)
            time.sleep(2)

            if self._is_login_page():
                self.last_error = "当前账号未登录 Bilibili，无法执行搜索"
                return []

            # 2. 找到搜索框并输入关键词
            search_selectors = [
                (By.CSS_SELECTOR, "input[placeholder*='搜索']"),
                (By.CSS_SELECTOR, "input.nav-search-input"),
                (By.CSS_SELECTOR, "input#search-keyword"),
                (By.XPATH, "//input[contains(@placeholder, '搜索')]"),
            ]
            search_input = self._find_clickable(search_selectors, timeout=5)
            if search_input:
                search_input.clear()
                search_input.send_keys(keyword)
                search_input.send_keys("\n")
                time.sleep(3)
            else:
                # 直接用 URL 搜索
                self.driver.get(f"{self.SEARCH_URL}?keyword={quote(keyword)}")
                time.sleep(3)

            # 3. 点击「用户」tab 切换到用户搜索结果
            user_tab_selectors = [
                (By.XPATH, '//span[contains(text(), "用户")]/ancestor::a[@data-type="bili_user"]'),
                (By.XPATH, '//a[contains(@data-type, "bili_user")]'),
                (By.XPATH, '//a[contains(@href, "search_type=bili_user")]'),
                (By.XPATH, '//div[contains(@class, "filter")]//span[text()="用户"]/ancestor::a'),
                (By.CSS_SELECTOR, 'a[data-type="bili_user"]'),
                (By.XPATH, '//span[text()="用户"]/ancestor::a[1]'),
            ]
            user_tab = self._find_clickable(user_tab_selectors, timeout=5)
            if user_tab:
                print(f"[B站博主搜索] 点击用户tab: {user_tab.get_attribute('href')}")
                user_tab.click()
                time.sleep(3)
            else:
                print(f"[B站博主搜索] 未找到用户tab，尝试直接访问用户搜索URL")
                self.driver.get(f"{self.SEARCH_URL}?keyword={quote(keyword)}&search_type=bili_user")
                time.sleep(3)

            # 4. 滚动加载更多用户
            up_stats: dict[str, dict[str, Any]] = {}
            scroll_count = 0
            max_scrolls = 15

            while scroll_count < max_scrolls:
                # 等待页面加载
                time.sleep(1)

                # 获取用户列表项
                user_items = (
                    self.driver.find_elements(By.CSS_SELECTOR, ".bili-user-list-item") or
                    self.driver.find_elements(By.CSS_SELECTOR, ".user-list-item") or
                    self.driver.find_elements(By.CSS_SELECTOR, "[class*='user-list'] a") or
                    self.driver.find_elements(By.XPATH, '//a[contains(@href, "/space/")]')
                )

                print(f"[B站博主搜索] 第 {scroll_count} 次滚动，获取到 {len(user_items)} 个用户元素")

                for item in user_items:
                    try:
                        href = item.get_attribute("href") or ""
                        if not href or "/space/" not in href:
                            continue

                        # 从 URL 提取用户 ID
                        parsed = urlparse(href)
                        path = parsed.path.rstrip("/")
                        author_id = path.split("/")[-1]

                        if not author_id:
                            continue

                        # 获取用户名
                        name_elem = item.find_element(By.CSS_SELECTOR, ".user-name") or item
                        author = (name_elem.text or author_id).strip()

                        # 过滤太短的名字
                        if len(author) < 2:
                            continue

                        # 获取粉丝数
                        fans = 0
                        try:
                            fan_elem = item.find_element(By.XPATH, './/span[contains(text(), "粉丝")]')
                            fan_text = fan_elem.text if fan_elem else ""
                            fans = self._parse_count(fan_text.replace("粉丝", "").replace(",", ""))
                        except:
                            pass

                        # 过滤
                        if self._should_filter_author(author):
                            continue

                        if author_id not in up_stats:
                            up_stats[author_id] = {
                                "author_id": author_id,
                                "author": author,
                                "fans": fans,
                                "total_posts": 0,
                                "posts": [],
                            }
                        else:
                            if fans > up_stats[author_id]["fans"]:
                                up_stats[author_id]["fans"] = fans

                    except Exception as e:
                        continue

                # 检查是否已收集到足够多的 up 主
                if len(up_stats) >= limit * 2:
                    break

                # 滚动
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(1, 2))
                scroll_count += 1

            # 5. 按粉丝数排序
            influencers = list(up_stats.values())
            influencers.sort(key=lambda x: x.get("fans", 0), reverse=True)

            # 6. 返回结果
            result = []
            for inf in influencers[:limit]:
                result.append({
                    "author_id": inf["author_id"],
                    "author": inf["author"],
                    "fans": inf["fans"],
                    "total_posts": inf["total_posts"],
                    "platform": "bilibili",
                    "profile_url": f"https://space.bilibili.com/{inf['author_id']}",
                })

            if not result:
                self.last_error = f"未找到相关博主，当前页面URL: {self.driver.current_url}"

            return result
        except Exception as exc:
            self.last_error = f"搜索博主失败: {exc}"
            return []

    def _should_filter_author(self, author: str) -> bool:
        """过滤不想要的作者"""
        if not author:
            return True
        author_lower = author.lower()
        filters = ["test", "测试", "官方", "admin", "bot"]
        return any(f in author_lower for f in filters)

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

    def get_user_posts(self, user_id: str, limit: int = 20) -> list[dict[str, Any]]:
        """获取指定用户的最近帖子"""
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            # 访问用户空间页面
            user_url = f"https://space.bilibili.com/{user_id}"
            self.driver.get(user_url)
            time.sleep(3)

            posts: list[dict[str, Any]] = []
            scroll_count = 0
            seen_ids: set[str] = set()

            while len(posts) < limit and scroll_count < 15:
                # 尝试查找视频卡片
                video_items = self.driver.find_elements(By.CSS_SELECTOR, ".video-card")
                if not video_items:
                    video_items = self.driver.find_elements(By.CSS_SELECTOR, ".cube-list-item")

                for item in video_items:
                    try:
                        # 获取视频链接
                        link_el = item.find_elements(By.CSS_SELECTOR, "a[href*='/video/']")
                        if not link_el:
                            continue
                        link = link_el[0].get_attribute("href")
                        if not link:
                            continue

                        # 提取视频ID
                        import re
                        match = re.search(r'/video/([BbVv]+[\w]+)', link)
                        if not match:
                            continue
                        bvid = match.group(1)

                        if bvid in seen_ids:
                            continue
                        seen_ids.add(bvid)

                        # 获取标题
                        title_el = item.find_elements(By.CSS_SELECTOR, ".title, .video-title")
                        title = title_el[0].text if title_el else ""

                        # 获取播放量
                        play_el = item.find_elements(By.CSS_SELECTOR, ".play, .stat-item")
                        play_text = play_el[0].text if play_el else "0"

                        posts.append({
                            "post_id": bvid,
                            "title": title[:100] if title else f"视频 {bvid}",
                            "content": title,
                            "author_id": user_id,
                            "likes": 0,
                            "comments": 0,
                            "url": link,
                        })

                        if len(posts) >= limit:
                            break
                    except Exception:
                        continue

                if len(posts) >= limit:
                    break

                # 滚动加载更多
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                scroll_count += 1

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"获取用户帖子失败: {exc}"
            return []

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
