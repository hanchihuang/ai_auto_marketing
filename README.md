# AI Auto Marketing

多平台自动营销工具，支持批量爬取微信文章、智能提取群二维码、跨平台内容搜索与批量评论。

## 核心功能

| 功能 | 说明 |
|------|------|
| 微信文章爬虫 | 使用 Playwright 批量爬取微信公众号/搜狗微信文章，智能提取群二维码 |
| 跨平台搜索 | 支持 X.com、哔哩哔哩，按关键词抓取内容（标题、链接、点赞、评论等） |
| 批量评论 | 根据产品信息自动生成营销文案，支持 soft/medium/hard 三种策略 |
| 双平台工作流 | 一次输入关键词，X.com 和哔哩哔哩并行执行"搜索+评论" |
| GitHub 推送 | 采集结果整理后自动推送到 GitHub 仓库 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 启动服务
python app.py
```

访问 http://127.0.0.1:5055

### 环境要求

- Python 3.13+
- Google Chrome + chromedriver

## 使用流程

1. **添加账号** - 在 `/accounts` 页面添加 X.com 或哔哩哔哩 Cookie
2. **配置产品** - 在 `/products` 填写产品名称、描述、推广链接
3. **搜索内容** - 在 `/search` 输入关键词，获取目标平台内容
4. **执行评论** - 在回复任务页批量执行评论

## 项目结构

```
.
├── app.py                    # Flask 主应用
├── storage.py                # SQLite 数据层
├── bilibili_bot.py           # 哔哩哔哩自动化
├── xiaohongshu.py            # X.com 自动化
├── linkedin_bot.py           # 领英自动化（暂不可用）
├── sogou_wechat_spider.py    # 搜狗微信爬虫
├── tardis_marketing.py       # Tardis 批量营销
├── templates/                # 前端模板
└── data/                     # SQLite 数据库
```

## 技术栈

- Flask + SQLite
- Selenium / Playwright
- Chrome / chromedriver

## 局限性

- 平台页面结构变化可能影响自动化稳定性
- Cookie 过期后需重新提取
- 部分账号可能无评论权限
