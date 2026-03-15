# AI Auto Marketing

多平台自动营销工具，支持批量爬取微信文章、智能提取群二维码、跨平台内容搜索、博主搜索与批量评论。

## 核心功能

| 功能 | 说明 |
|------|------|
| 微信文章爬虫 | 使用 Playwright 批量爬取微信公众号/搜狗微信文章，智能提取群二维码 |
| 跨平台搜索 | 支持 X.com、哔哩哔哩，按关键词抓取内容（标题、链接、点赞、评论等） |
| 博主搜索 | 支持 X.com、哔哩哔哩按关键词搜索领域博主，B 站支持视觉识别兜底 |
| 批量评论 | 根据产品信息自动生成营销文案，支持 soft/medium/hard 三种策略 |
| 双平台工作流 | 一次输入关键词，X.com 和哔哩哔哩并行执行"搜索+评论" |
| GitHub 推送 | 采集结果整理后自动推送到 GitHub 仓库 |

## 快速开始

```bash
# 安装依赖
pip install -r requirements.txt

# 可选：配置视觉模型（.env 默认不会被 git 提交）
cat > .env <<'EOF'
VISION_PROVIDER=nvidia
NVIDIA_API_KEY=your_nvapi_key
NVIDIA_VISION_MODELS=moonshotai/kimi-k2.5
EOF

# 启动服务
python app.py
```

访问 http://127.0.0.1:5055

### 环境要求

- Python 3.13+
- Google Chrome + chromedriver
- 可选：OpenAI 或 NVIDIA 兼容 OpenAI Chat Completions 的视觉模型接口

## 使用流程

1. **添加账号** - 在 `/accounts` 页面添加 X.com 或哔哩哔哩 Cookie
2. **配置产品** - 在 `/products` 填写产品名称、描述、推广链接
3. **搜索内容** - 在 `/search` 输入关键词，获取目标平台内容
4. **搜索博主** - 在 `/search/influencers` 输入关键词，定位目标领域博主
5. **执行评论** - 在回复任务页批量执行评论

## 视觉识别兜底

- B 站博主搜索优先使用页面结构化数据；若页面结构变化导致无法解析，则自动截取当前页面并调用视觉模型识别可见 UP 主卡片。
- 已修复 B 站搜索页用户数据归一化返回错误；当前会优先解析页面内 `window.__pinia` 的用户结果，再回退到视觉识别。
- 默认支持 `NVIDIA integrate.api.nvidia.com/v1`，也支持直接切换到 OpenAI。
- 本地 `.env` 会在启动时自动加载，且已被 `.gitignore` 忽略，不会提交到 GitHub。

## 项目结构

```
.
├── app.py                    # Flask 主应用
├── env_loader.py             # 本地 .env 自动加载
├── storage.py                # SQLite 数据层
├── bilibili_bot.py           # 哔哩哔哩自动化
├── vision_client.py          # OpenAI / NVIDIA 视觉模型客户端
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
- 视觉识别属于兜底路径，准确率取决于截图清晰度和模型质量
