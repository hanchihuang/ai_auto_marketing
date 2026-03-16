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
import re
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
from vision_client import VisionLLMClient


class BilibiliBot:
    BASE_URL = "https://www.bilibili.com"
    SEARCH_URL = "https://search.bilibili.com/all"
    # up主搜索URL - 可以直接按粉丝数排序
    UPUSER_SEARCH_URL = "https://search.bilibili.com/upuser"
    FAST_MODE = True
    KEYWORD_ALIASES = {
        "crypto": ["加密货币", "数字货币", "区块链", "比特币", "web3"],
        "bitcoin": ["比特币", "btc", "加密货币", "数字货币"],
        "web3": ["web3", "区块链", "加密货币", "数字货币"],
        "ai": ["人工智能", "AI", "AIGC", "机器学习"],
        "saas": ["SaaS", "软件服务", "企业软件", "创业"],
        "programming": ["编程", "程序员", "开发", "代码"],
        "coding": ["编程", "程序员", "开发", "代码"],
    }

    def __init__(self) -> None:
        self.driver: Optional[webdriver.Chrome] = None
        self.account: Optional[XiaohongshuAccount] = None
        self.last_error = ""
        self.cookie_string = ""
        self.vision_client = VisionLLMClient()

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
            # 先清除旧 cookie
            self.driver.delete_all_cookies()
            self.driver.get(self.BASE_URL)
            time.sleep(2)

            for item in self._parse_cookie_string(cookie):
                self.driver.add_cookie(item)

            # 刷新页面让 cookie 生效
            self.driver.get(self.BASE_URL)
            time.sleep(3)

            # 增强的登录检测
            if self._is_login_page():
                # 尝试检查页面中是否有登录按钮
                try:
                    login_buttons = self.driver.find_elements(By.CSS_SELECTOR, ".header-login")
                    if not login_buttons:
                        # 可能是登录状态但页面结构变化
                        avatar = self.driver.find_elements(By.CSS_SELECTOR, ".header-avatar-wrap, .bili-avatar, .user-panel .avatar")
                        if avatar:
                            # 实际已登录
                            nickname = self._safe_text(
                                [
                                    (By.CSS_SELECTOR, ".header-username"),
                                    (By.CSS_SELECTOR, ".user-name"),
                                    (By.CSS_SELECTOR, ".username"),
                                ]
                            )
                            self.account = XiaohongshuAccount(
                                cookie=cookie,
                                nickname=nickname or "B站用户",
                                status="online",
                                last_login=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                            )
                            return True
                except Exception:
                    pass
                self.last_error = "Bilibili Cookie 登录失败，请重新复制浏览器 Cookie"
                return False

            nickname = self._safe_text(
                [
                    (By.CSS_SELECTOR, ".header-entry-mini"),
                    (By.CSS_SELECTOR, ".header-avatar-wrap"),
                    (By.CSS_SELECTOR, ".bili-avatar"),
                    (By.CSS_SELECTOR, ".user-name"),
                ]
            )
            self.account = XiaohongshuAccount(
                cookie=cookie,
                nickname=nickname or "B站用户",
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
            # 增强 URL 构建
            search_url = f"{self.SEARCH_URL}?keyword={quote(keyword)}&search_type=video&_platform=web"
            self.driver.get(search_url)
            time.sleep(3)

            # 检查是否被重定向到登录页
            if self._is_login_page():
                self.last_error = "当前账号未登录 Bilibili，无法执行搜索"
                return []

            # 等待搜索结果加载
            try:
                WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "a[href*='/video/BV']"))
                )
            except Exception:
                # 可能没有结果或页面结构变化
                pass

            posts: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            scroll_count = 0

            while len(posts) < limit and scroll_count < 6:
                # 尝试多种选择器获取视频卡片
                try:
                    cards = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/video/BV']")
                except Exception:
                    cards = []

                # 如果没有找到，尝试其他选择器
                if not cards:
                    try:
                        cards = self.driver.find_elements(By.CSS_SELECTOR, ".video-card a, .video-item a, .bili-video-card a")
                    except Exception:
                        cards = []

                for card in cards:
                    try:
                        post = self._parse_video_card(card, keyword)
                        if not post or post["post_id"] in seen_ids:
                            continue
                        seen_ids.add(post["post_id"])
                        posts.append(post)
                        if len(posts) >= limit:
                            break
                    except Exception:
                        continue

                if len(posts) >= limit:
                    break

                # 滚动加载更多
                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(random.uniform(1, 2))
                scroll_count += 1

            if not posts:
                self.last_error = f"未找到关键词'{keyword}'相关的视频内容"

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"搜索失败: {exc}"
            return []

    def search_top_influencers(self, keyword: str, limit: int = 20) -> list[dict[str, Any]]:
        """搜索关键词领域最受欢迎的博主，按粉丝数排序

        使用 B 站 up主搜索页面：https://search.bilibili.com/upuser
        """
        if not self.driver:
            raise Exception("请先登录")

        self.last_error = ""
        try:
            up_stats: dict[str, dict[str, Any]] = {}
            for search_keyword in self._expand_influencer_keywords(keyword):
                self._collect_top_influencers_via_api(search_keyword, up_stats, limit)
                if len(up_stats) >= limit:
                    break
                self._collect_top_influencers_for_keyword(search_keyword, up_stats, limit)
                if self.last_error:
                    return []
                if len(up_stats) >= limit:
                    break

            if not up_stats:
                vision_results = self._search_top_influencers_with_vision(keyword, limit)
                for inf in vision_results:
                    up_stats[inf["author_id"]] = inf

            # 按粉丝数排序
            influencers = list(up_stats.values())
            influencers.sort(key=lambda x: x.get("fans", 0), reverse=True)

            result = []
            for inf in influencers[:limit]:
                result.append({
                    "author_id": inf["author_id"],
                    "author": inf["author"],
                    "fans": inf["fans"],
                    "total_posts": inf["total_posts"],
                    "platform": "bilibili",
                    "profile_url": inf["profile_url"],
                })

            if not result:
                self.last_error = f"未找到关键词'{keyword}'相关的B站博主"

            return result
        except Exception as exc:
            self.last_error = f"搜索博主失败: {exc}"
            return []

    def _expand_influencer_keywords(self, keyword: str) -> list[str]:
        text = self._clean_text(keyword)
        if not text:
            return []

        candidates: list[str] = [text]
        tokens = [token for token in re.split(r"[\s/_-]+", text.lower()) if token]
        for token in tokens:
            candidates.extend(self.KEYWORD_ALIASES.get(token, []))
        if text.lower() in self.KEYWORD_ALIASES:
            candidates.extend(self.KEYWORD_ALIASES[text.lower()])

        seen: set[str] = set()
        normalized: list[str] = []
        for item in candidates:
            value = self._clean_text(item)
            key = value.lower()
            if not value or key in seen:
                continue
            seen.add(key)
            normalized.append(value)
        return normalized

    def _collect_top_influencers_for_keyword(
        self,
        keyword: str,
        up_stats: dict[str, dict[str, Any]],
        limit: int,
    ) -> None:
        if not self.driver or not keyword:
            return

        upuser_url = f"{self.UPUSER_SEARCH_URL}?keyword={quote(keyword)}&order=fans"
        self.driver.get(upuser_url)
        time.sleep(5)

        if self._is_login_page():
            self.last_error = "当前账号未登录 Bilibili，无法执行搜索"
            return

        print(f"[B站博主搜索] 访问: {self.driver.current_url}")
        scroll_count = 0
        max_scrolls = 8

        while scroll_count < max_scrolls:
            time.sleep(1)

            try:
                js_data = self.driver.execute_script("""
                    function pickUserModule(searchAllResponse) {
                        if (!searchAllResponse) return null;
                        var modules = Array.isArray(searchAllResponse.result) ? searchAllResponse.result : [];
                        for (var i = 0; i < modules.length; i++) {
                            var item = modules[i] || {};
                            if (item.result_type === 'bili_user' || item.result_type === 'upuser') {
                                return item;
                            }
                        }
                        return null;
                    }

                    var searchAllResponse =
                        window.__pinia?.searchResponse?.searchAllResponse ||
                        window.__pinia?.state?.value?.searchResponse?.searchAllResponse ||
                        window.__INITIAL_STATE__?.searchResponse?.searchAllResponse ||
                        null;
                    var module = pickUserModule(searchAllResponse);
                    var users = module && Array.isArray(module.data) ? module.data : [];
                    if ((!users || users.length === 0) && searchAllResponse?.egg_hit?.result) {
                        users = searchAllResponse.egg_hit.result;
                    }

                    var normalized = users.map(function(user) {
                        var mid = user.mid || user.uid || user.id || '';
                        return {
                            id: String(mid || ''),
                            name: user.uname || user.name || '',
                            fans: Number(user.fans || 0),
                            videos: Number(user.videos || 0),
                            href: mid ? ('https://space.bilibili.com/' + mid) : '',
                            sample_title: user.res && user.res[0] ? (user.res[0].title || '') : '',
                        };
                    }).filter(function(user) {
                        return user.id && user.name;
                    });

                    return JSON.stringify(normalized);
                """)

                if js_data and js_data.strip():
                    try:
                        users_data = json.loads(js_data)
                        if users_data:
                            print(f"[B站博主搜索] 关键词 {keyword} 从JS获取到 {len(users_data)} 个用户")
                            for u in users_data:
                                author_id = u.get("id", "")
                                author = self._clean_text(u.get("name", author_id))
                                fans = u.get("fans", 0)
                                videos = u.get("videos", 0)
                                href = u.get("href", "")
                                sample_title = self._clean_text(u.get("sample_title", ""))

                                if author_id and author and self._should_filter_author(author) is False:
                                    record = up_stats.setdefault(author_id, {
                                        "author_id": author_id,
                                        "author": author,
                                        "fans": 0,
                                        "total_posts": 0,
                                        "posts": [],
                                        "profile_url": href or f"https://space.bilibili.com/{author_id}",
                                    })
                                    record["fans"] = max(record.get("fans", 0), fans)
                                    record["total_posts"] = max(record.get("total_posts", 0), videos)
                                    if sample_title and not record["posts"]:
                                        record["posts"] = [{
                                            "content": sample_title,
                                            "url": record["profile_url"],
                                            "likes": 0,
                                        }]
                    except Exception as e:
                        print(f"[B站博主搜索] 解析JS数据失败: {e}")
            except Exception as e:
                print(f"[B站博主搜索] JS获取失败: {e}")

            if len(up_stats) < limit:
                try:
                    scroll_pos = scroll_count * 800
                    self.driver.execute_script(f"window.scrollTo(0, {scroll_pos});")
                    time.sleep(1)

                    all_links = self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/space/']")
                    for link in all_links:
                        try:
                            href = link.get_attribute("href") or ""
                            if not href or "/space/" not in href:
                                continue

                            author_id = href.split("/")[-1].split("?")[0]
                            if not author_id:
                                continue

                            author = self._clean_text(link.text.strip())
                            if not author or len(author) < 2:
                                author = author_id

                            if self._should_filter_author(author):
                                continue

                            if author_id not in up_stats:
                                up_stats[author_id] = {
                                    "author_id": author_id,
                                    "author": author,
                                    "fans": 0,
                                    "total_posts": 0,
                                    "posts": [],
                                    "profile_url": href,
                                }
                        except Exception:
                            continue
                except Exception as e:
                    print(f"[B站博主搜索] DOM遍历失败: {e}")

            print(f"[B站博主搜索] 关键词 {keyword} 当前已收集 {len(up_stats)} 个博主")

            if len(up_stats) >= limit:
                break

            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            scroll_count += 1

    def _collect_top_influencers_via_api(
        self,
        keyword: str,
        up_stats: dict[str, dict[str, Any]],
        limit: int,
    ) -> None:
        if not self.driver or not keyword or len(up_stats) >= limit:
            return

        try:
            page = 1
            max_pages = min(5, max(1, (limit + 19) // 20 + 1))
            while page <= max_pages and len(up_stats) < limit:
                payload = self._fetch_bilibili_user_search_api(keyword, page=page)
                users = self._extract_bilibili_user_results(payload)
                if not users:
                    break

                print(f"[B站博主搜索] 关键词 {keyword} 从API获取到 {len(users)} 个用户，页码 {page}")
                before_count = len(up_stats)
                for user in users:
                    author_id = user.get("author_id", "")
                    author = self._clean_text(user.get("author", author_id))
                    if not author_id or not author or self._should_filter_author(author):
                        continue

                    record = up_stats.setdefault(author_id, {
                        "author_id": author_id,
                        "author": author,
                        "fans": 0,
                        "total_posts": 0,
                        "posts": [],
                        "profile_url": user.get("profile_url") or f"https://space.bilibili.com/{author_id}",
                    })
                    record["fans"] = max(record.get("fans", 0), self._safe_int(user.get("fans")))
                    record["total_posts"] = max(record.get("total_posts", 0), self._safe_int(user.get("total_posts")))

                    sample_title = self._clean_text(user.get("sample_title", ""))
                    if sample_title and not record["posts"]:
                        record["posts"] = [{
                            "content": sample_title,
                            "url": record["profile_url"],
                            "likes": 0,
                        }]

                if len(up_stats) == before_count:
                    break
                page += 1
        except Exception as exc:
            print(f"[B站博主搜索] API获取失败: {exc}")

    def _fetch_bilibili_user_search_api(self, keyword: str, page: int = 1) -> dict[str, Any]:
        if not self.driver:
            return {}

        params = urlencode({
            "search_type": "bili_user",
            "keyword": keyword,
            "order": "fans",
            "order_sort": 0,
            "user_type": 1,
            "page": page,
        })
        api_url = f"https://api.bilibili.com/x/web-interface/search/type?{params}"

        script = """
            const url = arguments[0];
            const done = arguments[arguments.length - 1];
            fetch(url, {
                credentials: 'include',
                headers: {
                    'Accept': 'application/json, text/plain, */*',
                    'X-Requested-With': 'XMLHttpRequest'
                }
            })
            .then(async (resp) => {
                const text = await resp.text();
                done(JSON.stringify({
                    ok: resp.ok,
                    status: resp.status,
                    body: text
                }));
            })
            .catch((err) => {
                done(JSON.stringify({
                    ok: false,
                    status: 0,
                    error: String(err)
                }));
            });
        """
        raw = self.driver.execute_async_script(script, api_url)
        if not raw:
            return {}

        result = json.loads(raw)
        if not result.get("ok"):
            status = result.get("status", 0)
            error = self._clean_text(result.get("error", "") or result.get("body", ""))
            raise RuntimeError(f"HTTP {status}: {error[:200]}")

        body = result.get("body", "")
        if not body:
            return {}
        payload = json.loads(body)
        if payload.get("code") not in (0, None):
            raise RuntimeError(f"code={payload.get('code')} message={payload.get('message')}")
        return payload

    def _extract_bilibili_user_results(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        data = payload.get("data")
        if not isinstance(data, dict):
            return []

        raw_results = data.get("result")
        if not isinstance(raw_results, list):
            return []

        users: list[dict[str, Any]] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            author_id = str(item.get("mid") or item.get("uid") or item.get("id") or "").strip()
            author = self._clean_text(str(item.get("uname") or item.get("name") or ""))
            if not author_id or not author:
                continue
            users.append({
                "author_id": author_id,
                "author": author,
                "fans": item.get("fans", 0),
                "total_posts": item.get("videos", 0),
                "profile_url": f"https://space.bilibili.com/{author_id}",
                "sample_title": self._clean_text(str(item.get("usign") or item.get("official_verify") or "")),
            })
        return users

    def _clean_text(self, text: str) -> str:
        if not text:
            return ""
        text = re.sub(r"<[^>]+>", "", text)
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

    def _search_top_influencers_with_vision(self, keyword: str, limit: int) -> list[dict[str, Any]]:
        if not self.driver or not self.vision_client.is_available():
            return []

        try:
            screenshot_base64 = self.driver.get_screenshot_as_base64()
            creators = self.vision_client.extract_bilibili_creators(
                screenshot_base64=screenshot_base64,
                keyword=keyword,
                limit=limit,
            )
            if not creators:
                return []

            links = self._collect_space_links()
            results: list[dict[str, Any]] = []
            for item in creators:
                author = self._clean_text(item.get("author", ""))
                if not author or self._should_filter_author(author):
                    continue

                matched = self._match_creator_link(author, links)
                author_id = matched.get("author_id") or author
                profile_url = matched.get("profile_url") or ""
                results.append({
                    "author_id": author_id,
                    "author": author,
                    "fans": item.get("fans", 0),
                    "total_posts": item.get("total_posts", 0),
                    "posts": [],
                    "profile_url": profile_url or f"https://space.bilibili.com/{author_id}",
                })
            print(f"[B站博主搜索] VLM识别到 {len(results)} 个博主")
            return results
        except Exception as exc:
            print(f"[B站博主搜索] VLM识别失败: {exc}")
            return []

    def _collect_space_links(self) -> list[dict[str, str]]:
        if not self.driver:
            return []
        links: list[dict[str, str]] = []
        for link in self.driver.find_elements(By.CSS_SELECTOR, "a[href*='/space/']"):
            try:
                href = (link.get_attribute("href") or "").strip()
                if not href or "/space/" not in href:
                    continue
                author = self._clean_text(link.text or "")
                author_id = href.rstrip("/").split("/")[-1].split("?")[0]
                links.append({
                    "author": author,
                    "author_id": author_id,
                    "profile_url": href,
                })
            except Exception:
                continue
        return links

    def _match_creator_link(self, author: str, links: list[dict[str, str]]) -> dict[str, str]:
        author_key = self._normalize_author(author)
        if not author_key:
            return {}

        for link in links:
            link_author = self._normalize_author(link.get("author", ""))
            if link_author and link_author == author_key:
                return link
        for link in links:
            link_author = self._normalize_author(link.get("author", ""))
            if link_author and (author_key in link_author or link_author in author_key):
                return link
        return {}

    def _normalize_author(self, author: str) -> str:
        return re.sub(r"[\W_]+", "", (author or "").lower())

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
            normalized_user_id = self._normalize_bilibili_user_id(user_id)
            if not normalized_user_id:
                self.last_error = "请输入有效的 B站 UID 或空间链接"
                return []

            # 直接进入投稿页，避免个人主页结构差异
            user_url = f"https://space.bilibili.com/{normalized_user_id}/upload/video"
            self.driver.get(user_url)
            time.sleep(5)

            posts: list[dict[str, Any]] = []
            seen_ids: set[str] = set()
            scroll_count = 0

            while len(posts) < limit and scroll_count < 6:
                time.sleep(3)
                video_links = self.driver.find_elements(By.CSS_SELECTOR, "a")

                for link_el in video_links:
                    try:
                        link = (link_el.get_attribute("href") or "").strip()
                        if not link:
                            continue

                        match = re.search(r"/video/(BV[\w]+)", link, re.I)
                        if not match:
                            continue
                        bvid = match.group(1)
                        if bvid in seen_ids:
                            continue

                        title = self._clean_text(link_el.text or "")
                        if not title:
                            title = self._clean_text(
                                link_el.get_attribute("title")
                                or link_el.get_attribute("aria-label")
                                or ""
                            )
                        # 过滤掉播放量/时长等非标题文本
                        if title and (len(title) < 6 or re.fullmatch(r"[\d\s:]+", title)):
                            continue

                        seen_ids.add(bvid)

                        posts.append({
                            "post_id": bvid,
                            "title": title[:100] if title else f"视频 {bvid}",
                            "content": title or f"视频 {bvid}",
                            "author_id": normalized_user_id,
                            "likes": 0,
                            "comments": 0,
                            "url": link.split("?")[0],
                        })

                        if len(posts) >= limit:
                            break
                    except Exception:
                        continue

                if len(posts) >= limit:
                    break

                self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                time.sleep(2)
                scroll_count += 1

            if not posts:
                posts = self._fallback_search_user_posts_by_titles(normalized_user_id, limit)
            if not posts:
                self.last_error = f"未找到 UID {normalized_user_id} 的可见视频投稿"

            return posts[:limit]
        except Exception as exc:
            self.last_error = f"获取用户帖子失败: {exc}"
            return []

    def _normalize_bilibili_user_id(self, user_id: str) -> str:
        value = (user_id or "").strip()
        if not value:
            return ""
        match = re.search(r"space\.bilibili\.com/(\d+)", value)
        if match:
            return match.group(1)
        match = re.search(r"(\d+)", value)
        if match:
            return match.group(1)
        return ""

    def _fallback_search_user_posts_by_titles(self, user_id: str, limit: int) -> list[dict[str, Any]]:
        if not self.driver:
            return []

        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
        except Exception:
            return []

        candidates = self._extract_bilibili_video_titles(body_text)
        author_name = candidates[0] if candidates else ""
        search_queries = []
        if author_name:
            search_queries.append(author_name)
        search_queries.extend(candidates[2:])
        posts: list[dict[str, Any]] = []
        seen_ids: set[str] = set()

        for title in search_queries[: min(limit * 3, 20)]:
            try:
                matched_posts = self.search_posts(title, limit=5)
            except Exception:
                matched_posts = []

            for post in matched_posts:
                post_id = post.get("post_id", "")
                post_title = self._clean_text(post.get("title", "") or post.get("content", ""))
                if not post_id or post_id in seen_ids:
                    continue
                if title != author_name and title not in post_title and post_title not in title:
                    continue
                seen_ids.add(post_id)
                posts.append({
                    "post_id": post_id,
                    "title": post.get("title", "") or title,
                    "content": post.get("content", "") or title,
                    "author_id": user_id,
                    "likes": post.get("likes", 0),
                    "comments": post.get("comments", 0),
                    "url": post.get("url", ""),
                })
                break

            if len(posts) >= limit:
                break

        return posts[:limit]

    def _extract_bilibili_video_titles(self, body_text: str) -> list[str]:
        lines = [self._clean_text(line) for line in (body_text or "").splitlines()]
        titles: list[str] = []
        noise = {
            "首页", "番剧", "直播", "游戏中心", "会员购", "漫画", "赛事", "下载客户端", "关注", "发消息",
            "主页", "动态", "投稿", "合集和系列", "课堂", "视频", "图文", "音频", "TA的视频", "播放全部",
            "最新发布", "最多播放", "最多收藏", "更多筛选", "关注数", "粉丝数", "获赞数", "播放数",
        }
        for line in lines:
            if not line or line in noise:
                continue
            if len(line) < 6:
                continue
            if re.fullmatch(r"[\d.\s:+万]+", line):
                continue
            if re.fullmatch(r"\d{2}-\d{2}", line) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", line):
                continue
            if line not in titles:
                titles.append(line)
        return titles

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
