# AI Auto Marketing

基于 Flask 的本地化自动营销面板，围绕 `X.com`、`哔哩哔哩`、`LinkedIn` 和 `搜狗微信` 提供账号管理、内容搜索、批量评论、博主定向触达、微信文章抓取与 Tardis 专项营销流程。

项目当前入口是 [app.py](./app.py)，默认启动在 `http://127.0.0.1:5055`。

## 当前能力

| 模块 | 当前状态 | 说明 |
| --- | --- | --- |
| 账号管理 | 可用 | 支持为 `X.com`、`哔哩哔哩`、`LinkedIn` 保存 Cookie 并校验登录状态 |
| 内容搜索 | 可用 | 按关键词抓取平台内容并落库到 SQLite，支持按平台查看 |
| 批量评论 | 可用 | 基于产品信息自动生成评论，支持 `soft` / `medium` / `hard` |
| 指定用户帖子营销 | 可用 | 输入用户标识，批量抓取其最近帖子并执行评论 |
| 博主搜索 | 部分可用 | `X.com`、`哔哩哔哩` 支持；`LinkedIn` 当前未接入博主搜索 |
| 一键工作流 | 可用 | 对在线账号并发执行“搜索 + 批量评论” |
| Tardis 专项活动 | 可用 | 内置高意图关键词、过滤词和专用评论策略 |
| 微信文章抓取 | 可用 | 通过搜狗微信抓取文章详情，并提取群二维码 |
| 视觉识别兜底 | 可用 | B 站博主搜索结构化解析失败时，自动调用视觉模型识别截图中的 UP 主卡片 |

## 技术栈

- Flask
- SQLite
- Selenium + ChromeDriver
- Playwright
- BeautifulSoup
- OpenCV + pyzbar
- Requests

## 运行要求

- Python `3.10+`
- 已安装 Google Chrome
- `chromedriver` 位于 `/usr/bin/chromedriver`
- Playwright Chromium 已安装

依赖来自 [requirements.txt](./requirements.txt)：

```bash
pip install -r requirements.txt
playwright install chromium
```

## 启动

```bash
python app.py
```

启动后访问：

- `http://127.0.0.1:5055/`

## 主要页面

- `/accounts`：添加平台账号、保存 Cookie、验证登录
- `/products`：维护营销产品信息
- `/search`：按关键词搜索内容
- `/comments`：对已采集内容执行批量评论
- `/user-posts`：对指定用户最近帖子批量评论
- `/search/influencers`：搜索博主并自动评论其最近帖子
- `/tardis`：单关键词 Tardis 营销活动
- `/tardis/batch`：多关键词、多平台 Tardis 批量营销
- `/wechat`：搜狗微信文章抓取和二维码提取
- `/stats`：查看统计信息

## 平台行为说明

### X.com

- 使用 Cookie 登录，要求 Cookie 中包含 `auth_token`
- 支持内容搜索、博主搜索、指定用户帖子抓取、评论执行
- 类名仍保留为 `XiaohongshuBot`，实际行为已经切换为 X.com，见 [xiaohongshu.py](./xiaohongshu.py)

### 哔哩哔哩

- 使用 Cookie 登录，要求包含 `SESSDATA`
- 支持视频搜索、评论、UP 主搜索
- UP 主搜索优先走页面结构化数据，失败时回退到视觉识别，见 [bilibili_bot.py](./bilibili_bot.py) 和 [vision_client.py](./vision_client.py)

### LinkedIn

- 支持 Cookie 登录、内容搜索、评论
- 当前没有接入博主搜索工作流
- 相关实现位于 [linkedin_bot.py](./linkedin_bot.py)

### 搜狗微信

- 通过 Playwright 打开搜狗微信搜索页并抓取文章
- 进入文章详情后提取二维码图片或截图数据
- 数据存储在 `data/marketing.db` 的 `wechat_articles` 表

## 产品与评论策略

通用产品字段包含：

- `code`
- `name`
- `description`
- `price`
- `wechat_id`
- `target_tags`

普通产品使用通用评论生成器；当产品 `code=tardis` 时，会自动切换到 Tardis 专用评论逻辑。

### 通用策略

- `soft`
- `medium`
- `hard`

### Tardis 专用策略

- `diagnosis`
- `value_add`
- `sample`
- `demo`

Tardis 关键词、过滤词和文案模板定义在 [tardis_marketing.py](./tardis_marketing.py)。

## 环境变量

应用启动时会自动加载本地 `.env`，见 [env_loader.py](./env_loader.py)。

### Flask

```env
FLASK_SECRET_KEY=replace-this
```

### 视觉模型

默认支持 OpenAI 兼容接口和 NVIDIA 兼容接口：

```env
VISION_PROVIDER=auto

OPENAI_API_KEY=
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_VISION_MODELS=gpt-5

NVIDIA_API_KEY=
NVIDIA_API_BASE=https://integrate.api.nvidia.com/v1
NVIDIA_VISION_MODELS=moonshotai/kimi-k2.5
```

说明：

- `VISION_PROVIDER=auto` 时，优先使用 OpenAI，其次 NVIDIA
- 未配置 API Key 时，B 站视觉识别兜底不会生效，但结构化解析仍会尝试执行

## 数据存储

默认数据库路径：

- `data/marketing.db`

主要表：

- `xhs_accounts`
- `xhs_hot_posts`
- `xhs_comment_tasks`
- `products`
- `xhs_stats`
- `wechat_articles`
- `telegram_user_accounts`
- `telegram_groups`
- `telegram_marketing_tasks`

表初始化逻辑见 [storage.py](./storage.py)。

## 项目结构

```text
.
├── app.py
├── storage.py
├── env_loader.py
├── xiaohongshu.py
├── bilibili_bot.py
├── linkedin_bot.py
├── vision_client.py
├── sogou_wechat_spider.py
├── tardis_marketing.py
├── templates/
└── data/
```

## 已知限制

- 自动化高度依赖平台页面结构，页面改版会直接影响搜索和评论稳定性
- 所有平台当前都依赖人工提供 Cookie，Cookie 失效后需要重新更新
- ChromeDriver 路径当前写死为 `/usr/bin/chromedriver`
- 微信二维码有时会被微信图片防盗链保护，前端会给出降级提示
- B 站视觉识别依赖外部模型接口，速度和准确率取决于截图质量与模型表现
- 仓库中仍保留部分历史命名，例如 `xhs_*` 数据表和 `XiaohongshuBot` 类名，实际业务已扩展到多平台
