# ai_auto_marketing

一个基于 Flask + Selenium 的多平台自动营销原型，目前接入：

- `X.com`
- `哔哩哔哩`

核心能力：

- 账号管理：按平台保存 Cookie，并验证登录状态
- 内容搜索：按关键词抓取平台内容
- 自动营销回复：基于产品信息生成营销文案并自动回复/评论
- 统计与记录：保存搜索结果、回复任务、成功/失败状态

## 当前结构

- [app.py](/home/user/图片/ai_auto_marketing/app.py)：Flask 主应用
- [storage.py](/home/user/图片/ai_auto_marketing/storage.py)：SQLite 存储层
- [xiaohongshu.py](/home/user/图片/ai_auto_marketing/xiaohongshu.py)：当前承载 `X.com` 自动化逻辑
- [bilibili_bot.py](/home/user/图片/ai_auto_marketing/bilibili_bot.py)：哔哩哔哩自动化逻辑
- [templates](/home/user/图片/ai_auto_marketing/templates)：页面模板
- [data/marketing.db](/home/user/图片/ai_auto_marketing/data/marketing.db)：本地 SQLite 数据库

## 运行环境

- Python 3.13+
- Chrome
- chromedriver，默认路径 `/usr/bin/chromedriver`

依赖安装：

```bash
pip install -r requirements.txt
```

启动：

```bash
python app.py
```

默认访问地址：

```text
http://127.0.0.1:5055
```

## 使用方式

### 1. 添加账号

进入 `/accounts` 页面，添加平台账号：

- `X.com`：Cookie 至少包含 `auth_token`
- `哔哩哔哩`：Cookie 至少包含 `SESSDATA`

添加后点击“验证 Cookie”。

### 2. 配置产品

进入 `/products` 页面添加产品信息。

说明：

- 回复文案会自动带上产品宣传链接
- 链接优先从 `description` 或 `wechat_id` 字段里提取 `http/https` 地址

### 3. 搜索内容

进入 `/search` 页面：

- 选择账号
- 输入关键词
- 搜索对应平台内容

系统会记录：

- 标题/内容
- 链接
- 点赞/评论等指标
- 网页是否可访问

### 4. 批量营销回复

进入 `/comments` 页面：

- 选择账号
- 选择产品
- 选择策略
- 执行批量回复

当前支持：

- `soft`
- `medium`
- `hard`

## 当前实现说明

这是一个网页自动化原型，不是稳定生产系统。平台页面结构、风控、权限限制会直接影响成功率。

已知现实限制：

- 平台 DOM 结构变化会导致搜索或回复失败
- 某些内容页虽然能打开，但未必允许当前账号回复/评论
- 营销内容越硬，越容易被平台限制
- Cookie 失效后需要重新从浏览器提取

## 数据说明

当前使用 SQLite，本地数据默认保存在：

```text
data/marketing.db
```

已支持多平台隔离：

- 账号表带 `platform`
- 搜索结果带 `platform`
- 回复记录带 `platform`

## 后续建议

- 把 `xiaohongshu.py` 重命名为更中性的 `x_bot.py`
- 把平台能力抽象成统一接口
- 为每个平台单独维护搜索/评论选择器
- 增加更明确的推广链接字段，而不是依赖 `description` 提取
- 增加 `.env` 配置和正式的进程守护方式
