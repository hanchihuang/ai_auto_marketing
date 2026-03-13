"""
搜狗微信爬虫
爬取量化、AI相关文章的群二维码
使用 Playwright 绕过反爬虫机制
"""

import re
import time
import urllib.parse
from datetime import datetime, timedelta
from typing import Any

from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup


class SogouWechatSpider:
    """搜狗微信爬虫 - 使用Playwright"""

    BASE_URL = "https://weixin.sogou.com/weixin"

    def __init__(self, proxy: str | None = None):
        self.proxy = proxy
        self._playwright = None
        self._browser = None
        self._context = None
        self._page = None

    def _get_page(self):
        """获取或创建页面"""
        if self._page is not None:
            return self._page

        self._playwright = sync_playwright().start()

        launch_options = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ]
        }

        if self.proxy:
            launch_options["proxy"] = {"server": self.proxy}

        # 使用 Chromium，但模拟 Firefox UA 来绕过反爬
        self._browser = self._playwright.chromium.launch(**launch_options)
        
        # 使用 Firefox User-Agent 绕过反爬虫检测
        firefox_ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0"
        
        self._context = self._browser.new_context(
            user_agent=firefox_ua,
            viewport={"width": 1920, "height": 1080},
        )

        # 注入脚本来���藏 webdriver 标志
        self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        self._page = self._context.new_page()
        self._page.set_default_timeout(30000)

        return self._page

    def close(self):
        """关闭浏览器"""
        if self._page:
            self._page.close()
            self._page = None
        if self._context:
            self._context.close()
            self._context = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def __del__(self):
        """析构时关闭浏览器"""
        self.close()

    def _clean_html(self, text: str) -> str:
        """清理HTML实体"""
        import html
        return html.unescape(text) if text else text

    def search_articles(
        self,
        keyword: str,
        days: int = 7,
        page: int = 1,
        num: int = 10,
    ) -> list[dict]:
        """
        搜索微信文章

        Args:
            keyword: 搜索关键词
            days: 最近几天
            page: 页码
            num: 每页数量

        Returns:
            文章列表
        """
        try:
            page_obj = self._get_page()

            # 先访问搜狗微信首页
            print(f"访问首页...")
            page_obj.goto(self.BASE_URL, wait_until="domcontentloaded")
            time.sleep(2)

            # 在搜索框中输入关键词并提交表单
            print(f"搜索关键词: {keyword}")
            
            # 清空搜索框并输入关键词
            page_obj.fill('#query', keyword)
            
            # 点击搜索按钮 (type=2 表示搜文章)
            page_obj.click('input[value="搜文章"]')
            
            # 等待搜索结果加载
            time.sleep(5)

            # 如果需要翻页，使用分页链接
            if page > 1:
                # 找到分页并点击对应页码
                # 例如: page.click(f'a[data-page="{page}"]')
                pass

            # 检查是否被反爬
            if "antispider" in page_obj.url or "captcha" in page_obj.url:
                print("检测到反爬虫页面")
                return []

            # 获取页面源码
            html = page_obj.content()

            return self._parse_search_results(html, keyword)
        except Exception as e:
            print(f"搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _parse_search_results(self, html: str, keyword: str) -> list[dict]:
        """解析搜索结果"""
        articles = []
        soup = BeautifulSoup(html, "html.parser")

        # 使用正确的选择器
        items = soup.select("ul.news-list li")

        for item in items:
            try:
                # 获取标题和链接
                title_elem = item.select_one("h3 a")
                if not title_elem:
                    continue

                title = title_elem.get_text(strip=True)
                title = self._clean_html(title)

                link = title_elem.get("href", "")
                if not link:
                    continue

                # 处理搜狗重定向链接 - 需要使用完整URL才能正确重定向
                if link.startswith("/link?url="):
                    # 构建完整的重定向URL
                    link = f"https://weixin.sogou.com{link}"

                # 获取来源 - 注意：source 是时间
                source_elem = item.select_one(".s2")
                source = source_elem.get_text(strip=True) if source_elem else ""

                # 获取时间 - .s3 可能是空的，时间在 .s2 中
                time_elem = item.select_one(".s3")
                pub_time = time_elem.get_text(strip=True) if time_elem else source  # 使用 source 作为时间

                # 获取摘要
                abstract_elem = item.select_one("p.txt-info")
                abstract = abstract_elem.get_text(strip=True) if abstract_elem else ""

                articles.append({
                    "title": title,
                    "link": link,
                    "source": source,
                    "pub_time": pub_time,
                    "abstract": abstract,
                    "keyword": keyword,
                })
            except Exception as e:
                print(f"解析文章失败: {e}")
                continue

        return articles

    def get_article_detail(self, url: str) -> dict | None:
        """获取文章详情，包括群二维码"""
        try:
            page_obj = self._get_page()

            print(f"访问文章: {url}")
            page_obj.goto(url, wait_until="networkidle")

            # 等待页面加载
            time.sleep(3)

            # 检查是否被反爬
            if "antispider" in page_obj.url or "captcha" in page_obj.url:
                return {
                    "title": "",
                    "author": "",
                    "pub_time": "",
                    "url": url,
                    "content": "",
                    "qr_codes": [],
                    "blocked": True,
                }

            # 获取页面源码
            html = page_obj.content()

            return self._parse_article_detail(html, url)
        except Exception as e:
            print(f"获取文章详情失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _parse_article_detail(self, html: str, url: str) -> dict:
        """解析文章详情，提取群二维码"""
        soup = BeautifulSoup(html, "html.parser")

        # 获取标题
        title = ""
        title_elem = soup.select_one("#activity-name")
        if title_elem:
            title = title_elem.get_text(strip=True)
            title = self._clean_html(title)

        if not title:
            title_elem = soup.select_one("h1.rich_media_title")
            if title_elem:
                title = title_elem.get_text(strip=True)

        # 获取作者
        author = ""
        author_elem = soup.select_one("#js_author")
        if author_elem:
            author = author_elem.get_text(strip=True)

        # 获取发布时间
        pub_time = ""
        time_elem = soup.select_one("#js_publish_time")
        if time_elem:
            pub_time = time_elem.get_text(strip=True)

        # 查找群二维码
        qr_codes = []

        # 提取内容区域中的所有图片
        rich_content = soup.select_one("#js_content")
        if rich_content:
            for img in rich_content.find_all("img"):
                src = img.get("data-src", "") or img.get("src", "")
                alt = img.get("alt", "")

                if not src or src.startswith("data:"):
                    continue

                src_lower = src.lower()
                is_qr = False
                qr_type = "content_img"

                if any(x in src_lower for x in ["qrcode", "qrimage", "mmqrcode", "wxqrcode"]):
                    is_qr = True
                    qr_type = "qrcode_url"
                elif "群" in alt or "二维码" in alt:
                    is_qr = True
                    qr_type = "group_alt"
                else:
                    parent = img.parent
                    if parent:
                        parent_text = parent.get_text(strip=True).lower()
                        if "群" in parent_text or "二维码" in parent_text:
                            is_qr = True
                            qr_type = "parent_text"

                if is_qr:
                    qr_codes.append({
                        "type": qr_type,
                        "src": src,
                        "alt": alt,
                    })

        # 获取文章内容摘要
        content = ""
        if rich_content:
            content = rich_content.get_text(strip=True)[:500]

        return {
            "title": title,
            "author": author,
            "pub_time": pub_time,
            "url": url,
            "content": content,
            "qr_codes": qr_codes,
        }

    def batch_search(
        self,
        keywords: list[str],
        days: int = 7,
        max_pages: int = 3,
    ) -> list[dict]:
        """批量搜索多个关键词"""
        all_articles = []

        for keyword in keywords:
            print(f"搜索关键词: {keyword}")

            for page in range(1, max_pages + 1):
                articles = self.search_articles(keyword, days=days, page=page)

                if not articles:
                    break

                for article in articles:
                    detail = self.get_article_detail(article["link"])
                    if detail:
                        article.update(detail)

                    time.sleep(1)

                all_articles.extend(articles)
                time.sleep(2)

        return all_articles


# 测试
if __name__ == "__main__":
    spider = SogouWechatSpider()
    articles = spider.search_articles("量化", days=7, page=1)
    print(f"找到 {len(articles)} 篇文章")
    for i, a in enumerate(articles[:3]):
        print(f"\n文章 {i+1}: {a.get('title', '无标题')[:50]}")
        print(f"  链接: {a.get('link', '无')[:80]}")
    spider.close()