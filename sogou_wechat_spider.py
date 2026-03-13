"""
搜狗微信爬虫
爬取量化、AI相关文章的群二维码
使用 Playwright 绕过反爬虫机制
"""

import io
import re
import time
import urllib.parse
import requests
from datetime import datetime, timedelta
from typing import Any

import cv2
import numpy as np
from pyzbar.pyzbar import decode as decode_qrcode
from PIL import Image
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
                # 等待分页加载
                time.sleep(2)
                # 尝试点击对应的页码
                try:
                    # 搜狗微信的分页选择器
                    page_link = page_obj.query_selector(f'a[data-page="{page}"]')
                    if page_link:
                        page_link.click()
                        time.sleep(3)
                    else:
                        # 尝试其他分页选择器
                        page_link = page_obj.query_selector(f'.pc_next_{page}')
                        if page_link:
                            page_link.click()
                            time.sleep(3)
                        else:
                            # 尝试点击下一页按钮
                            next_btn = page_obj.query_selector('.pc_next, a:has-text("下一页")')
                            if next_btn:
                                for _ in range(page - 1):
                                    next_btn.click()
                                    time.sleep(2)
                except Exception as e:
                    print(f"翻页失败: {e}")

            # 检查是否被反爬
            if "antispider" in page_obj.url or "captcha" in page_obj.url:
                print("检测到反爬虫页面")
                return []

            # 获取页面源码
            html = page_obj.content()

            return self._parse_search_results(html, keyword, days)
        except Exception as e:
            print(f"搜索失败: {e}")
            import traceback
            traceback.print_exc()
            return []

    def _parse_search_results(self, html: str, keyword: str, days: int = 7) -> list[dict]:
        """解析搜索结果
        
        Args:
            html: 页面HTML
            keyword: 搜索关键词
            days: 过滤最近几天的文章
        """
        articles = []
        soup = BeautifulSoup(html, "html.parser")

        # 计算截止日期
        cutoff_date = datetime.now() - timedelta(days=days)
        
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

                # 处理搜狗重定向链接 - 需要添加完整 URL 前缀才能访问
                if link.startswith("/link?url="):
                    # 构建完整的重定向URL
                    link = f"https://weixin.sogou.com{link}"
                elif not link.startswith("http"):
                    # 非法链接，跳过
                    continue

                # 获取来源 - 注意：source 是时间
                source_elem = item.select_one(".s2")
                source = source_elem.get_text(strip=True) if source_elem else ""

                # 获取时间 - .s3 可能是空的，时间在 .s2 中
                time_elem = item.select_one(".s3")
                pub_time = time_elem.get_text(strip=True) if time_elem else source  # 使用 source 作为时间

                # 解析文章日期并过滤
                article_date = self._parse_article_date(pub_time)
                if article_date and article_date < cutoff_date:
                    # 文章超过指定天数，跳过
                    continue

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

    def _parse_article_date(self, date_str: str) -> datetime | None:
        """解析文章日期字符串
        
        支持格式:
        - 2024年1月15日
        - 1月15日
        - 3小时前
        - 刚刚
        - 今天
        - 昨天
        """
        if not date_str:
            return None
            
        date_str = date_str.strip()
        now = datetime.now()
        
        try:
            # 完整日期格式: 2024年1月15日
            match = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
            if match:
                year, month, day = map(int, match.groups())
                return datetime(year, month, day)
            
            # 月日格式: 1月15日 (需要判断是今年还是去年)
            match = re.match(r'(\d{1,2})月(\d{1,2})日', date_str)
            if match:
                month, day = map(int, match.groups())
                # 如果解析出的日期在未来，则认为是去年
                year = now.year
                parsed = datetime(year, month, day)
                if parsed > now:
                    parsed = datetime(year - 1, month, day)
                return parsed
            
            # 今天
            if '今天' in date_str:
                return now
            
            # 昨天
            if '昨天' in date_str:
                return now - timedelta(days=1)
            
            # N小时前
            match = re.search(r'(\d+)\s*小时前', date_str)
            if match:
                hours = int(match.group(1))
                return now - timedelta(hours=hours)
            
            # N分钟前
            match = re.search(r'(\d+)\s*分钟前', date_str)
            if match:
                minutes = int(match.group(1))
                return now - timedelta(minutes=minutes)
            
            # 刚刚
            if '刚刚' in date_str:
                return now
                
        except Exception as e:
            print(f"日期解析失败: {date_str}, {e}")
            
        return None

    def get_article_detail(self, url: str) -> dict | None:
        """获取文章详情，包括群二维码"""
        try:
            page_obj = self._get_page()

            print(f"访问文章: {url}")
            page_obj.goto(url, wait_until="domcontentloaded")

            # 等待页面加载
            time.sleep(3)

            # 检查并处理验证码
            if self._handle_verification(page_obj):
                print("已处理验证，等待内容加载...")
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

            return self._parse_article_detail(html, url, page_obj)
        except Exception as e:
            print(f"获取文章详情失败: {e}")
            import traceback
            traceback.print_exc()
            return None

    def _handle_verification(self, page) -> bool:
        """处理微信验证滑块"""
        try:
            # 检查是否有验证滑块
            slider = page.query_selector('.reward-slider, .slider, [class*="slider"], [id*="slider"]')
            if slider:
                print("检测到验证滑块，尝试等待自动通过...")
                
                # 等待一段时间让验证自动完成（如果有的话）
                # 或者尝试滑动
                for attempt in range(3):
                    time.sleep(2)
                    
                    # 检查滑块是否消失
                    if not page.query_selector('.reward-slider, .slider, [class*="slider"]'):
                        print("验证已通过")
                        return True
                    
                    # 尝试拖动滑块
                    try:
                        slider = page.query_selector('.reward-slider, .slider, [class*="slider"], [id*="slider"]')
                        if slider:
                            box = slider.bounding_box()
                            if box:
                                # 随机拖动距离
                                import random
                                move_x = box['x'] + box['width'] * random.uniform(0.6, 0.9)
                                page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                                page.mouse.down()
                                page.mouse.move(move_x, box['y'] + box['height'] / 2, steps=10)
                                page.mouse.up()
                    except Exception as e:
                        print(f"滑动尝试 {attempt + 1} 失败: {e}")
                
                return True
            
            # 检查其他验证元素
            verify_elements = page.query_selector_all('[class*="verify"], [id*="verify"], [class*="captcha"]')
            if verify_elements:
                print(f"检测到验证元素 {len(verify_elements)} 个")
                time.sleep(2)
                return True
                
            return False
        except Exception as e:
            print(f"验证处理出错: {e}")
            return False

    def _parse_article_detail(self, html: str, url: str, page=None) -> dict:
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

        # 方法1: 从内容区域提取（初步筛选 + 图像验证）
        rich_content = soup.select_one("#js_content")
        if rich_content:
            qr_codes.extend(self._extract_qr_codes_from_element(rich_content))

        # 方法2: 从整个页面提取（处理懒加载）
        if not qr_codes:
            qr_codes.extend(self._extract_qr_codes_from_element(soup))

        # 方法3: 使用Playwright截图识别（如果有page对象）
        if not qr_codes and page:
            qr_codes.extend(self._extract_qr_codes_from_page(page))

        # 方法4: 兜底 - 如果以上方法都没找到，遍历所有图片进行图像验证
        if not qr_codes and page:
            qr_codes.extend(self._verify_all_images(page))

        # 方法5: 在页面内对疑似二维码的 img 做区域截图再识别（可拿到页面实际渲染图，绕过防盗链）
        if not qr_codes and page:
            in_page_qr = self._get_qr_from_page_screenshot(page)
            if in_page_qr:
                qr_codes.extend(in_page_qr)

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

    def _is_wechat_placeholder(self, image_np: np.ndarray) -> bool:
        """判断是否为微信防盗链占位图（黑底+右下角白框「此图片来自微信公众平台」）"""
        try:
            if image_np is None or image_np.size == 0:
                return True
            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY) if len(image_np.shape) == 3 else image_np
            mean_val = float(np.mean(gray))
            # 占位图绝大部分为黑色，整体亮度很低
            if mean_val < 25:
                return True
            # 可选：检查是否大部分像素接近黑色
            black_ratio = np.sum(gray < 40) / gray.size
            if black_ratio > 0.85:
                return True
            return False
        except Exception:
            return False

    def _is_valid_qr_code(self, image_url: str) -> bool:
        """下载图片并验证是否为有效的二维码；若为微信占位图则判定为无效"""
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/115.0",
                "Referer": "https://mp.weixin.qq.com/",
            }
            response = requests.get(image_url, headers=headers, timeout=10)
            if response.status_code != 200:
                return False

            image_bytes = io.BytesIO(response.content)
            image = Image.open(image_bytes).convert("RGB")
            image_np = np.array(image)

            # 先判断是否为微信防盗链占位图，避免误判为“无二维码”
            if self._is_wechat_placeholder(image_np):
                print(f"检测到微信防盗链占位图，已跳过: {image_url[:60]}...")
                return False

            gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
            decoded_objects = decode_qrcode(gray)

            if decoded_objects:
                for obj in decoded_objects:
                    data = obj.data.decode("utf-8", errors="ignore")
                    if data and len(data) > 0:
                        return True
            return False
        except Exception as e:
            return False

    def _extract_qr_codes_from_element(self, element) -> list:
        """从HTML元素中提取二维码"""
        qr_codes = []
        
        for img in element.find_all("img"):
            # 优先使用 data-src（懒加载）
            src = img.get("data-src", "") or img.get("src", "")
            alt = img.get("alt", "")
            
            if not src or src.startswith("data:"):
                continue

            # 跳过文章页 URL（非图片），微信有时会把当前页 URL 填进 img
            if "weixin.qq.com/s?" in src or "mp.weixin.qq.com/s?" in src:
                continue

            src_lower = src.lower()
            is_qr = False
            qr_type = "content_img"

            # 检查URL/文件名是否包含二维码关键词
            qr_keywords = ["qrcode", "qrimage", "mmqrcode", "wxqrcode", "qr-image", "qr_code", "qr-code"]
            if any(x in src_lower for x in qr_keywords):
                is_qr = True
                qr_type = "qrcode_url"
            # 检查alt文本
            elif "群" in alt or "二维码" in alt or "群二维码" in alt:
                is_qr = True
                qr_type = "group_alt"
            else:
                # 检查父元素文本
                parent = img.parent
                if parent:
                    parent_text = parent.get_text(strip=True)
                    if "群" in parent_text or "二维码" in parent_text or "加微信" in parent_text:
                        is_qr = True
                        qr_type = "parent_text"

            # 额外检查：图片尺寸通常是正方形（二维码特征）
            style = img.get("style", "")
            if not is_qr and style:
                # 如果样式中有 width/height 且接近正方形，可能是二维码
                import re
                width_match = re.search(r'width:\s*(\d+)px', style)
                height_match = re.search(r'height:\s*(\d+)px', style)
                if width_match and height_match:
                    w, h = int(width_match.group(1)), int(height_match.group(1))
                    if w > 50 and h > 50 and abs(w - h) < 20:
                        # 正方形图片，可能是二维码
                        is_qr = True
                        qr_type = "square_img"

            # 只有初步判断为二维码的图片才进行真正的图像验证
            if is_qr:
                # 下载图片并验证是否为真正的二维码
                if self._is_valid_qr_code(src):
                    qr_codes.append({
                        "type": qr_type + "_verified",
                        "src": src,
                        "alt": alt,
                    })
                    print(f"验证通过二维码: type={qr_type}, src={src[:60]}...")
                else:
                    print(f"图片非二维码（图像识别验证失败）: src={src[:60]}...")

        return qr_codes

    def _extract_qr_codes_from_page(self, page) -> list:
        """从Playwright页面对象提取二维码（处理动态加载）"""
        qr_codes = []
        
        try:
            # 使用JavaScript查找所有图片元素，优先取真实图片地址（data-src）
            images = page.evaluate('''
                () => {
                    const images = [];
                    document.querySelectorAll('img').forEach(img => {
                        // 优先 data-src / data-original（懒加载真实图），避免用成文章页 URL
                        let src = (img.dataset.src || img.dataset.original || img.src || '').trim();
                        const alt = img.alt || '';
                        
                        // 跳过文章链接（非图片）
                        if (src.indexOf('weixin.qq.com/s?') !== -1 || src.indexOf('mp.weixin.qq.com/s?') !== -1) return;
                        if (!src || src.startsWith('data:')) return;
                        
                        let isQr = false;
                        let type = 'page_img';
                        
                        const srcLower = src.toLowerCase();
                        if (srcLower.includes('qrcode') || srcLower.includes('mmqrcode') || 
                            srcLower.includes('wxqrcode') || srcLower.includes('qr_image') ||
                            srcLower.includes('mmbiz.qpic.cn') || srcLower.includes('wx.qlogo.cn')) {
                            isQr = true;
                            type = 'qrcode_url';
                        } else if (alt.includes('群') || alt.includes('二维码')) {
                            isQr = true;
                            type = 'group_alt';
                        }
                        
                        // 检查父元素
                        if (!isQr && img.parentElement) {
                            const parentText = img.parentElement.innerText || '';
                            if (parentText.includes('群') || parentText.includes('二维码') || parentText.includes('加微信')) {
                                isQr = true;
                                type = 'parent_text';
                            }
                        }
                        
                        images.push({src, alt, type, isQr});
                    });
                    return images;
                }
            ''')
            
            for img in images:
                if img.get("isQr") or img.get("type") in ["qrcode_url", "group_alt", "parent_text"]:
                    src = img.get("src", "")
                    # 下载图片并验证是否为真正的二维码
                    if self._is_valid_qr_code(src):
                        qr_codes.append({
                            "type": img.get("type", "page_detected") + "_verified",
                            "src": src,
                            "alt": img.get("alt", ""),
                        })
                        print(f"JS检测到二维码（已验证）: {img.get('type')}, src={img.get('src', '')[:60]}...")
                    else:
                        print(f"JS检测图片非二维码（验证失败）: src={src[:60]}...")
                    
        except Exception as e:
            print(f"JS二维码检测失败: {e}")

        return qr_codes

    def _verify_all_images(self, page) -> list:
        """兜底方法：遍历所有图片进行图像验证"""
        qr_codes = []

        try:
            # 使用JavaScript获取所有图片
            images = page.evaluate('''
                () => {
                    const images = [];
                    document.querySelectorAll('img').forEach(img => {
                        let src = (img.dataset.src || img.dataset.original || img.src || '').trim();
                        if (src.indexOf('weixin.qq.com/s?') !== -1 || src.indexOf('mp.weixin.qq.com/s?') !== -1) return;
                        if (!src || src.startsWith('data:')) return;
                        // 跳过微信头像
                        if (src.includes('wx.qlogo.cn') && !src.toLowerCase().includes('qr')) return;
                        images.push({src, alt: img.alt || ''});
                    });
                    return images;
                }
            ''')

            print(f"兜底检测：遍历 {len(images)} 张图片进行二维码验证...")

            for img in images:
                src = img.get("src", "")
                if self._is_valid_qr_code(src):
                    qr_codes.append({
                        "type": "full_scan_verified",
                        "src": src,
                        "alt": img.get("alt", ""),
                    })
                    print(f"兜底检测找到二维码: src={src[:60]}...")

        except Exception as e:
            print(f"兜底二维码检测失败: {e}")

        return qr_codes

    def _get_qr_from_page_screenshot(self, page) -> list:
        """在页面内对疑似二维码的 img 做区域截图并识别，可拿到浏览器实际渲染的图（有时能绕过防盗链）"""
        import base64
        qr_codes = []
        try:
            # 优先在正文区域找可能为二维码的 img
            selector = "#js_content img, .rich_media_content img"
            imgs = page.query_selector_all(selector)
            for img in imgs:
                try:
                    src = img.get_attribute("src") or img.get_attribute("data-src") or ""
                    if not src or "weixin.qq.com/s?" in src or src.startswith("data:"):
                        continue
                    box = img.bounding_box()
                    if not box or box.get("width", 0) < 50 or box.get("height", 0) < 50:
                        continue
                    screenshot_bytes = img.screenshot(type="png")
                    if not screenshot_bytes:
                        continue
                    image_np = np.frombuffer(screenshot_bytes, dtype=np.uint8)
                    image_np = cv2.imdecode(image_np, cv2.IMREAD_COLOR)
                    if image_np is None:
                        continue
                    if self._is_wechat_placeholder(image_np):
                        continue
                    gray = cv2.cvtColor(image_np, cv2.COLOR_BGR2GRAY)
                    decoded = decode_qrcode(gray)
                    if decoded:
                        for obj in decoded:
                            if obj.data and len(obj.data) > 0:
                                b64 = base64.b64encode(screenshot_bytes).decode("ascii")
                                qr_codes.append({
                                    "type": "page_screenshot_verified",
                                    "src": src,
                                    "alt": img.get_attribute("alt") or "",
                                    "screenshot_base64": b64,
                                })
                                print(f"页面截图识别到二维码: src={src[:50]}...")
                                return qr_codes
                except Exception as e:
                    continue
        except Exception as e:
            print(f"页面截图二维码检测失败: {e}")
        return qr_codes

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


def is_wechat_placeholder_image(image_bytes: bytes) -> bool:
    """根据图片字节判断是否为微信防盗链占位图（供 app 代理等使用）"""
    try:
        if not image_bytes or len(image_bytes) < 100:
            return True
        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        image_np = np.array(image)
        gray = cv2.cvtColor(image_np, cv2.COLOR_RGB2GRAY)
        mean_val = float(np.mean(gray))
        if mean_val < 25:
            return True
        black_ratio = np.sum(gray < 40) / gray.size
        return black_ratio > 0.85
    except Exception:
        return False


# 测试
if __name__ == "__main__":
    spider = SogouWechatSpider()
    articles = spider.search_articles("量化", days=7, page=1)
    print(f"找到 {len(articles)} 篇文章")
    for i, a in enumerate(articles[:3]):
        print(f"\n文章 {i+1}: {a.get('title', '无标题')[:50]}")
        print(f"  链接: {a.get('link', '无')[:80]}")
    spider.close()