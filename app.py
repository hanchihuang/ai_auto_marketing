"""
多平台自动营销系统
登录平台账号 -> 搜索内容 -> 自动回复推广产品
"""

from __future__ import annotations

import os
import random
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

from env_loader import load_local_env
from storage import Storage
from bilibili_bot import BilibiliBot
from xiaohongshu import XiaohongshuBot, CommentGenerator, CommentStrategy, Product
from sogou_wechat_spider import SogouWechatSpider
from linkedin_bot import LinkedInBot
from tardis_marketing import (
    TardisCommentGenerator,
    TardisCommentStrategy,
    TardisProduct,
    TardisCampaign,
    TARDIS_KEYWORDS,
    ALL_TARDIS_KEYWORDS,
    FULL_TARDIS_KEYWORDS,
    EXCLUDE_FILTERS,
    get_keywords_by_priority,
    build_search_query,
)


BASE_DIR = Path(__file__).resolve().parent
load_local_env(BASE_DIR / ".env")
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
storage = Storage(BASE_DIR / "data" / "marketing.db")

# 爬虫进度状态
crawl_progress = {
    "status": "idle",  # idle, running, completed, error
    "current_keyword": "",
    "current_page": 0,
    "total_keywords": 0,
    "total_pages": 0,
    "total_articles": 0,
    "total_qr_codes": 0,
    "message": "",
}

# 机器人实例缓存
bots = {}
# 后台任务
running_tasks = {}

PLATFORM_LABELS = {
    "x": "X.com",
    "bilibili": "哔哩哔哩",
    "linkedin": "领英",
}


def build_product_model(product: dict) -> Product:
    """将数据库产品记录映射为评论生成器使用的 Product 模型"""
    return Product(
        code=product.get("code", ""),
        name=product.get("name", ""),
        description=product.get("description", ""),
        price=product.get("price", ""),
        wechat_id=product.get("wechat_id", ""),
        features=product.get("features", []) or [],
        target_tags=product.get("target_tags", []) or [],
    )


def is_tardis_product(product: dict) -> bool:
    """判断是否为 Tardis 产品"""
    return product.get("code", "").lower() == "tardis"


def get_comment_generator(product: dict):
    """根据产品类型获取合适的评论生成器"""
    if is_tardis_product(product):
        return TardisCommentGenerator(TardisProduct(
            name=product.get("name", "Tardis"),
            description=product.get("description", ""),
            website="https://tardis.dev",
        ))
    return CommentGenerator(build_product_model(product))


def get_default_account_id(accounts: list[dict]) -> int | None:
    """优先使用最近登录且在线的账号作为默认账号"""
    online_accounts = [account for account in accounts if account.get("status") == "online"]
    if not online_accounts:
        return None
    online_accounts.sort(key=lambda item: item.get("last_login") or "", reverse=True)
    return online_accounts[0]["id"]


def get_default_account_by_platform(accounts: list[dict], platform: str) -> dict | None:
    """优先返回指定平台最近登录且在线的账号"""
    candidates = [
        account for account in accounts
        if account.get("platform") == platform and account.get("status") == "online"
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: item.get("last_login") or "", reverse=True)
    return candidates[0]


def get_bot_for_platform(platform: str):
    if platform == "bilibili":
        return BilibiliBot()
    elif platform == "linkedin":
        return LinkedInBot()
    return XiaohongshuBot()


def ensure_logged_in_bot(account: dict):
    import logging
    logger = logging.getLogger(__name__)

    account_id = account["id"]
    platform = account.get("platform", "x")
    if account_id in bots:
        return bots[account_id]

    bot = get_bot_for_platform(platform)
    if not account.get("cookie"):
        logger.warning(f"[ensure_logged_in_bot] 账号 {account_id} 没有 cookie")
        return None

    login_success = bot.login_by_cookie(account["cookie"])
    logger.info(f"[ensure_logged_in_bot] 账号 {account_id} 登录结果: {login_success}, last_error: {getattr(bot, 'last_error', 'N/A')}")

    if not login_success:
        # 登录失败，返回 None 让调用方知道需要重新登录
        return None

    bots[account_id] = bot
    return bot


def search_posts_for_account(account: dict, keyword: str, limit_value: int) -> dict:
    """执行内容搜索并保存结果"""
    platform = account.get("platform", "x")
    platform_label = PLATFORM_LABELS.get(platform, platform)

    bot = ensure_logged_in_bot(account)
    if bot is None:
        return {"ok": False, "message": "账号缺少可用登录信息，请重新登录"}
    if account["id"] not in bots and getattr(bot, "last_error", ""):
        return {"ok": False, "message": bot.last_error or "Cookie 登录失败，请到账号管理重新登录"}

    posts = bot.search_posts(keyword, limit=limit_value)
    if not posts:
        return {
            "ok": False,
            "message": f"没有搜到{platform_label}内容。可能是 Cookie 已失效，或者页面结构变化导致抓取失败。",
        }

    checked_posts = []
    web_accessible_count = 0
    for post in posts:
        post["platform"] = platform
        if platform == "bilibili":
            # 快速模式下不逐条打开详情页校验，真正评论时再检查可访问性
            is_accessible = True
        else:
            is_accessible = bot.is_post_web_accessible(post.get("url", ""))
        post["web_accessible"] = is_accessible
        post["accessibility_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        checked_posts.append(post)
        if is_accessible:
            web_accessible_count += 1

    saved_count = 0
    for post in checked_posts:
        storage.insert_xhs_hot_post(post)
        saved_count += 1

    storage.insert_xhs_stat({
        "posts_searched": saved_count,
    })

    return {
        "ok": True,
        "saved_count": saved_count,
        "web_accessible_count": web_accessible_count,
        "platform_label": platform_label,
    }


def batch_comment_for_account(
    account: dict,
    product: dict,
    strategy: str,
    max_comments_value: int,
    min_likes_value: int,
) -> dict:
    """执行批量回复并保存结果"""
    platform = account.get("platform", "x")
    platform_label = PLATFORM_LABELS.get(platform, platform)

    bot = ensure_logged_in_bot(account)
    if bot is None:
        return {"ok": False, "message": "账号缺少可用登录信息，请重新登录"}
    if account["id"] not in bots and getattr(bot, "last_error", ""):
        return {"ok": False, "message": bot.last_error or "Cookie 登录失败，请到账号管理重新登录"}

    hot_posts = storage.list_xhs_hot_posts(limit=200, platform=platform)
    hot_posts = [
        p for p in hot_posts
        if p["likes"] >= min_likes_value
        and p.get("web_accessible", False)
        and p.get("accessibility_checked_at")
    ]

    if not hot_posts:
        return {
            "ok": False,
            "message": f"没有找到已检测且可在网页端访问的{platform_label}内容，请先去搜索页重新搜索",
        }

    existing_tasks = storage.list_xhs_comment_tasks(status="success", platform=platform)
    commented_post_ids = {t["post_id"] for t in existing_tasks}
    posts_to_comment = [p for p in hot_posts if p["post_id"] not in commented_post_ids]

    if not posts_to_comment:
        return {"ok": False, "message": f"当前符合条件的{platform_label}内容都已经营销过了"}

    web_accessible_posts = [
        post for post in posts_to_comment
        if post.get("web_accessible", False) and post.get("accessibility_checked_at")
    ]

    if not web_accessible_posts:
        return {"ok": False, "message": f"当前{platform_label}内容没有可在网页端打开的详情页，无法执行自动回复"}

    # 判断是否为 Tardis 产品，使用对应的评论策略
    if is_tardis_product(product):
        try:
            strategy_enum = TardisCommentStrategy(strategy)
        except ValueError:
            # 如果不是有效的 Tardis 策略，回退到诊断型
            strategy_enum = TardisCommentStrategy.DIAGNOSIS
    else:
        try:
            strategy_enum = CommentStrategy(strategy)
        except ValueError:
            return {"ok": False, "message": "评论策略无效"}

    success_count = 0
    failed_count = 0
    cd_detected = False  # 检测到评论冷却

    for post in web_accessible_posts[:max_comments_value]:
        # 根据产品类型使用不同的评论生成器
        comment_gen = get_comment_generator(product)
        
        if is_tardis_product(product):
            # Tardis 产品使用专用评论生成器
            tardis_strategy = TardisCommentStrategy(strategy) if strategy in [s.value for s in TardisCommentStrategy] else TardisCommentStrategy.DIAGNOSIS
            comment_text = comment_gen.generate_comment(tardis_strategy, post.get("content", ""))
        else:
            # 普通产品使用原有评论生成器
            comment_text = comment_gen.generate_comment(CommentStrategy(strategy))
            
        success = bot.comment_post(post["post_id"], comment_text, post.get("url", ""))
        error_message = "" if success else (bot.last_error or "回复失败")

        # 检测评论冷却/风控，停止批量操作
        if not success and ("cd时间" in error_message or "不能评论" in error_message or "请稍后再试" in error_message):
            cd_detected = True
            print(f"[{platform_label}] 检测到评论冷却，停止批量任务")
            # 剩余帖子不再继续评论，留到下次
            break

        storage.insert_xhs_comment_task({
            "post_id": post["post_id"],
            "platform": platform,
            "post_title": post.get("title", ""),
            "content": comment_text,
            "strategy": strategy,
            "status": "success" if success else "failed",
            "error_message": error_message,
            "commented_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if success else "",
        })

        if success:
            success_count += 1
        else:
            failed_count += 1

        # 每次评论后等待一段时间，避免过快触发风控
        if success and not cd_detected:
            time.sleep(2)  # 成功评论后等待2秒

    storage.insert_xhs_stat({
        "comments_success": success_count,
        "comments_failed": failed_count,
    })

    return {
        "ok": True,
        "success_count": success_count,
        "failed_count": failed_count,
        "platform_label": platform_label,
    }


@app.get("/")
def dashboard():
    """仪表盘首页"""
    accounts = storage.list_xhs_accounts()
    hot_posts = storage.list_xhs_hot_posts(limit=50)
    comment_tasks = storage.list_xhs_comment_tasks()
    products = storage.list_products()
    stats = storage.get_xhs_stats()

    success_tasks = [t for t in comment_tasks if t["status"] == "success"]
    failed_tasks = [t for t in comment_tasks if t["status"] == "failed"]

    return render_template(
        "dashboard.html",
        accounts=accounts,
        hot_posts=hot_posts,
        comment_tasks=comment_tasks,
        products=products,
        stats=stats,
        success_count=len(success_tasks),
        failed_count=len(failed_tasks),
        now=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


# ==================== 账号管理 ====================

@app.get("/accounts")
def accounts_page():
    """账号管理页面"""
    accounts = storage.list_xhs_accounts()
    return render_template("accounts.html", accounts=accounts)


@app.post("/accounts")
def add_account():
    """添加账号"""
    phone = request.form.get("phone", "").strip()
    platform = request.form.get("platform", "x").strip() or "x"
    cookie = request.form.get("cookie", "").strip()
    nickname = request.form.get("nickname", "").strip()

    if not phone:
        abort(400, "账号标识不能为空")

    # 检查是否已存在
    existing = storage.get_xhs_account_by_phone(phone, platform)
    if existing:
        abort(400, "该账号已存在")

    storage.insert_xhs_account({
        "phone": phone,
        "platform": platform,
        "cookie": cookie,
        "nickname": nickname,
        "status": "offline",
    })

    return redirect(url_for("accounts_page"))


@app.post("/accounts/<int:account_id>/login")
def login_account(account_id: int):
    """验证平台 Cookie"""
    account = storage.get_xhs_account(account_id)
    if not account:
        abort(404, "账号不存在")

    platform = account.get("platform", "x")

    bot = get_bot_for_platform(platform)
    bots[account_id] = bot

    success = bot.login_by_cookie(account.get("cookie", ""))

    if success:
        storage.update_xhs_account(account_id, {
            "status": "online",
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cookie": bot.account.cookie if bot.account else "",
        })
        flash(f"{PLATFORM_LABELS.get(platform, platform)} Cookie 验证成功", "success")
    else:
        storage.update_xhs_account(account_id, {"status": "offline"})
        flash(
            bot.last_error
            or f"{PLATFORM_LABELS.get(platform, platform)} Cookie 验证失败",
            "error",
        )

    return redirect(url_for("accounts_page"))


@app.post("/accounts/<int:account_id>/logout")
def logout_account(account_id: int):
    """登出账号"""
    if account_id in bots:
        bots[account_id].close()
        del bots[account_id]

    storage.update_xhs_account(account_id, {"status": "offline"})
    return redirect(url_for("accounts_page"))


@app.post("/accounts/<int:account_id>/delete")
def delete_account(account_id: int):
    """删除账号"""
    if account_id in bots:
        bots[account_id].close()
        del bots[account_id]

    storage.delete_xhs_account(account_id)
    return redirect(url_for("accounts_page"))


# ==================== 热帖搜索 ====================

@app.get("/search")
def search_page():
    """内容搜索页面"""
    account_id = request.args.get("account_id", type=int)
    keyword = request.args.get("keyword", "").strip()
    products = storage.list_products()
    default_product_id = products[0]["id"] if products else None
    accounts = storage.list_xhs_accounts()
    default_workflow_accounts = {
        platform: get_default_account_by_platform(accounts, platform)
        for platform in PLATFORM_LABELS
    }
    default_account_id = get_default_account_id(accounts)
    selected_account_id = account_id or default_account_id
    selected_account = storage.get_xhs_account(selected_account_id) if selected_account_id else None
    current_platform = selected_account.get("platform", "x") if selected_account else "x"

    hot_posts = []
    if selected_account_id:
        hot_posts = storage.list_xhs_hot_posts(limit=100, platform=current_platform)
        if keyword:
            hot_posts = [post for post in hot_posts if post.get("search_keyword") == keyword]

    return render_template(
        "search.html",
        account_id=selected_account_id,
        default_account_id=default_account_id,
        current_platform=current_platform,
        platform_labels=PLATFORM_LABELS,
        keyword=keyword,
        accounts=accounts,
        products=products,
        default_product_id=default_product_id,
        default_workflow_accounts=default_workflow_accounts,
        hot_posts=hot_posts,
        full_keywords=FULL_TARDIS_KEYWORDS,
    )


@app.get("/search/hot-posts")
def search_hot_posts_redirect():
    """避免直接访问 POST 路由时出现错误页"""
    return redirect(url_for("search_page"))


@app.post("/search/hot-posts")
def search_hot_posts():
    """搜索平台内容"""
    account_id = request.form.get("account_id", type=int)
    keyword = request.form.get("keyword", "").strip()
    limit = request.form.get("limit", "30").strip()

    if not account_id:
        flash("请选择账号", "error")
        return redirect(url_for("search_page"))

    if not keyword:
        flash("请输入搜索关键词", "error")
        return redirect(url_for("search_page", account_id=account_id))

    try:
        limit_value = max(10, min(int(limit), 100))
    except ValueError:
        flash("搜索数量必须是数字", "error")
        return redirect(url_for("search_page", account_id=account_id, keyword=keyword))

    account = storage.get_xhs_account(account_id)
    if not account or account["status"] != "online":
        flash("账号未登录或状态异常", "error")
        return redirect(url_for("search_page", account_id=account_id, keyword=keyword))
    result = search_posts_for_account(account, keyword, limit_value)
    if not result["ok"]:
        flash(result["message"], "warning")
        return redirect(url_for("search_page", account_id=account_id, keyword=keyword))

    flash(
        f"{result['platform_label']}搜索完成，已保存 {result['saved_count']} 条结果，其中网页可访问 {result['web_accessible_count']} 条",
        "success",
    )
    return redirect(url_for("search_page", account_id=account_id, keyword=keyword))


# ==================== 博主搜索 ====================

@app.get("/search/influencers")
def search_influencers_page():
    """博主搜索页面"""
    import logging
    logger = logging.getLogger(__name__)

    account_id = request.args.get("account_id", type=int)
    keyword = request.args.get("keyword", "").strip()
    accounts = storage.list_xhs_accounts()
    default_account_id = get_default_account_id(accounts)
    selected_account_id = account_id or default_account_id
    selected_account = storage.get_xhs_account(selected_account_id) if selected_account_id else None

    influencers = []
    error_message = ""
    debug_info = ""
    platform = "x"
    if selected_account_id and keyword:
        account = storage.get_xhs_account(selected_account_id)
        platform = account.get("platform", "x") if account else "x"
        logger.info(f"[搜索博主] 账号: {account}, 关键词: {keyword}, 平台: {platform}")
        if account and account["status"] == "online":
            try:
                bot = ensure_logged_in_bot(account)
                if bot and hasattr(bot, "search_top_influencers"):
                    logger.info(f"[搜索博主] 开始搜索...")
                    influencers = bot.search_top_influencers(keyword, limit=20)
                    logger.info(f"[搜索博主] 搜索完成，结果数: {len(influencers)}, last_error: {getattr(bot, 'last_error', 'N/A')}")
                    if hasattr(bot, "last_error") and bot.last_error:
                        error_message = bot.last_error
                    bots.pop(account["id"], None)
                    bot.close()
                else:
                    error_message = f"当前平台 ({PLATFORM_LABELS.get(platform, platform)}) 暂不支持博主搜索功能"
            except Exception as e:
                logger.error(f"[搜索博主] 异常: {e}")
                error_message = f"搜索出错: {str(e)}"
        elif account and account["status"] != "online":
            error_message = "账号未在线，请先在账号管理中验证登录状态"

    return render_template(
        "search_influencers.html",
        account_id=selected_account_id,
        default_account_id=default_account_id,
        keyword=keyword,
        accounts=accounts,
        influencers=influencers,
        error_message=error_message,
        debug_info=debug_info,
        platform=platform,
    )


@app.post("/search/hot-posts/clear")
def clear_hot_posts():
    """一键清空已搜集推文"""
    account_id = request.form.get("account_id", type=int)
    requested_platform = request.form.get("platform", "").strip()
    platform = requested_platform if requested_platform in PLATFORM_LABELS else None

    if platform:
        deleted_count = storage.clear_xhs_hot_posts(platform)
        flash(f"已清空 {PLATFORM_LABELS.get(platform, platform)} 的 {deleted_count} 条已保存帖子", "success")
        if account_id:
            return redirect(url_for("search_page", account_id=account_id))
        return redirect(url_for("search_page"))

    if account_id:
        account = storage.get_xhs_account(account_id)
        platform = account.get("platform") if account else None
    if platform:
        deleted_count = storage.clear_xhs_hot_posts(platform)
        flash(f"已清空 {PLATFORM_LABELS.get(platform, platform)} 的 {deleted_count} 条已保存帖子", "success")
        return redirect(url_for("search_page", account_id=account_id))
    deleted_count = storage.clear_xhs_hot_posts()
    flash(f"已清空全部平台的 {deleted_count} 条已保存帖子", "success")
    return redirect(url_for("search_page"))


# ==================== 评论任务 ====================

@app.get("/comments")
def comments_page():
    """营销回复任务页面"""
    status = request.args.get("status")
    account_id = request.args.get("account_id", type=int)
    products = storage.list_products()
    default_product_id = products[0]["id"] if products else None
    accounts = storage.list_xhs_accounts()
    default_account_id = get_default_account_id(accounts)
    selected_account_id = account_id or default_account_id
    selected_account = storage.get_xhs_account(selected_account_id) if selected_account_id else None
    current_platform = selected_account.get("platform", "x") if selected_account else "x"
    tasks = storage.list_xhs_comment_tasks(status, platform=current_platform)
    return render_template(
        "comments.html",
        tasks=tasks,
        products=products,
        accounts=accounts,
        default_account_id=selected_account_id,
        default_product_id=default_product_id,
        current_platform=current_platform,
        platform_labels=PLATFORM_LABELS,
        status=status,
    )


# ==================== 用户帖子营销 ====================

@app.get("/user-posts")
def user_posts_page():
    """指定用户帖子营销页面"""
    account_id = request.args.get("account_id", type=int)
    accounts = storage.list_xhs_accounts()
    default_account_id = get_default_account_id(accounts)
    selected_account_id = account_id or default_account_id
    selected_account = storage.get_xhs_account(selected_account_id) if selected_account_id else None
    current_platform = selected_account.get("platform", "x") if selected_account else "x"
    products = storage.list_products()

    return render_template(
        "user_posts.html",
        accounts=accounts,
        default_account_id=selected_account_id,
        current_platform=current_platform,
        platform_labels=PLATFORM_LABELS,
        products=products,
    )


@app.post("/user-posts/comment")
def user_posts_comment():
    """对指定用户的帖子进行批量评论"""
    account_id = request.form.get("account_id", type=int)
    product_id = request.form.get("product_id", type=int)
    target_username = request.form.get("username", "").strip()
    strategy = request.form.get("strategy", "soft")
    max_comments = request.form.get("max_comments", "50").strip()

    if not account_id:
        flash("请选择账号", "error")
        return redirect(url_for("user_posts_page"))

    if not target_username:
        flash("请输入目标用户名", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    if not product_id:
        flash("请选择产品", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    try:
        max_comments_value = max(1, min(int(max_comments), 50))
    except ValueError:
        flash("评论数量必须是数字", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    account = storage.get_xhs_account(account_id)
    if not account or account["status"] != "online":
        flash("账号未登录", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    product = storage.get_product(product_id)
    if not product:
        flash("产品不存在", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    platform = account.get("platform", "x")
    platform_label = PLATFORM_LABELS.get(platform, platform)

    bot = ensure_logged_in_bot(account)
    if bot is None:
        flash("账号缺少可用登录信息", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    # 获取用户帖子
    try:
        if platform == "x":
            posts = bot.get_user_posts(target_username, limit=50)
        elif platform == "bilibili":
            # B站使用数字UID
            posts = bot.get_user_posts(target_username, limit=50)
        else:
            flash(f"暂不支持 {platform_label} 的用户帖子获取", "error")
            return redirect(url_for("user_posts_page", account_id=account_id))
    except Exception as e:
        flash(f"获取用户帖子失败: {e}", "error")
        return redirect(url_for("user_posts_page", account_id=account_id))

    if not posts:
        flash(f"未找到用户 @{target_username} 的帖子", "warning")
        return redirect(url_for("user_posts_page", account_id=account_id))

    # 过滤已评论的帖子
    existing_tasks = storage.list_xhs_comment_tasks(status="success", platform=platform)
    commented_post_ids = {t["post_id"] for t in existing_tasks}
    posts_to_comment = [p for p in posts if p["post_id"] not in commented_post_ids]

    if not posts_to_comment:
        flash(f"用户 @{target_username} 的帖子都已经营销过了", "warning")
        return redirect(url_for("user_posts_page", account_id=account_id))

    # 执行评论
    success_count = 0
    failed_count = 0

    for post in posts_to_comment[:max_comments_value]:
        comment_gen = get_comment_generator(product)
        comment_text = comment_gen.generate_comment(CommentStrategy(strategy))

        success = bot.comment_post(post["post_id"], comment_text, post.get("url", ""))
        error_message = "" if success else (bot.last_error or "回复失败")

        storage.insert_xhs_comment_task({
            "post_id": post["post_id"],
            "platform": platform,
            "post_title": post.get("title", ""),
            "content": comment_text,
            "strategy": strategy,
            "status": "success" if success else "failed",
            "error_message": error_message,
            "commented_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if success else "",
        })

        if success:
            success_count += 1
        else:
            failed_count += 1
            # 检测评论冷却
            if "cd时间" in error_message or "不能评论" in error_message or "请稍后再试" in error_message:
                print(f"[{platform_label}] 检测到评论冷却，停止批量任务")
                break

        time.sleep(random.uniform(3, 8))

    flash(f"用户 @{target_username} 帖子营销完成，成功 {success_count} 条，失败 {failed_count} 条",
          "success" if success_count > 0 else "warning")
    return redirect(url_for("user_posts_page", account_id=account_id))


@app.get("/comments/batch")
def batch_comment_page_redirect():
    """避免直接访问 POST 路由时出现错误页"""
    return redirect(url_for("comments_page"))


@app.post("/comments/batch")
def batch_comment():
    """批量营销回复"""
    account_id = request.form.get("account_id", type=int)
    product_id = request.form.get("product_id", type=int)
    strategy = request.form.get("strategy", "soft")
    max_comments = request.form.get("max_comments", "100").strip()
    min_likes = request.form.get("min_likes", "0").strip()

    if not account_id:
        flash("请选择账号", "error")
        return redirect(url_for("comments_page"))

    if not product_id:
        flash("请选择产品", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    account = storage.get_xhs_account(account_id)
    if not account or account["status"] != "online":
        flash("账号未登录", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    product = storage.get_product(product_id)
    if not product:
        flash("产品不存在", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    # 获取推文
    try:
        max_comments_value = max(1, min(int(max_comments), 100))
        min_likes_value = max(0, int(min_likes))
    except ValueError:
        flash("评论数量和点赞筛选必须是数字", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    result = batch_comment_for_account(
        account=account,
        product=product,
        strategy=strategy,
        max_comments_value=max_comments_value,
        min_likes_value=min_likes_value,
    )
    if not result["ok"]:
        flash(result["message"], "warning")
        return redirect(url_for("comments_page", account_id=account_id))

    if result["success_count"] and result["failed_count"]:
        flash(f"批量回复完成，成功 {result['success_count']} 条，失败 {result['failed_count']} 条", "warning")
    elif result["success_count"]:
        flash(f"批量回复完成，成功 {result['success_count']} 条", "success")
    else:
        flash(f"批量回复未成功，失败 {result['failed_count']} 条", "error")

    return redirect(url_for("comments_page", account_id=account_id))


@app.post("/workflow/run")
def run_workflow():
    """一键执行：先搜索再批量回复"""
    keyword = request.form.get("keyword", "").strip()
    product_id = request.form.get("product_id", type=int)
    strategy = request.form.get("strategy", "soft")
    limit = request.form.get("limit", "100").strip()
    max_comments = request.form.get("max_comments", "100").strip()
    min_likes = request.form.get("min_likes", "0").strip()

    if not keyword:
        flash("请输入搜索关键词", "error")
        return redirect(url_for("search_page"))
    if not product_id:
        flash("请选择产品", "error")
        return redirect(url_for("search_page", keyword=keyword))

    try:
        limit_value = max(10, min(int(limit), 100))
        max_comments_value = max(1, min(int(max_comments), 100))
        min_likes_value = max(0, int(min_likes))
    except ValueError:
        flash("搜索数量、回复数量和点赞筛选必须是数字", "error")
        return redirect(url_for("search_page", keyword=keyword))

    product = storage.get_product(product_id)
    if not product:
        flash("产品不存在", "error")
        return redirect(url_for("search_page", keyword=keyword))

    accounts = storage.list_xhs_accounts()
    workflow_accounts = {
        platform: get_default_account_by_platform(accounts, platform)
        for platform in ["x", "bilibili", "linkedin"]
    }
    available_accounts = {platform: account for platform, account in workflow_accounts.items() if account}
    if not available_accounts:
        flash("未找到可用的在线账号，请至少保持一个 X.com、哔哩哔哩或领英账号在线", "error")
        return redirect(url_for("search_page", keyword=keyword))

    cleared_counts = {}
    for platform in ["x", "bilibili", "linkedin"]:
        cleared_counts[platform] = storage.clear_xhs_hot_posts(platform)
    flash(
        (
            f"执行前已自动清空历史帖子："
            f"X.com {cleared_counts.get('x', 0)} 条，"
            f"哔哩哔哩 {cleared_counts.get('bilibili', 0)} 条，"
            f"领英 {cleared_counts.get('linkedin', 0)} 条"
        ),
        "warning",
    )

    def run_platform_workflow(account: dict) -> dict:
        search_result = search_posts_for_account(account, keyword, limit_value)
        if not search_result["ok"]:
            return {
                "platform": account.get("platform", ""),
                "platform_label": PLATFORM_LABELS.get(account.get("platform", ""), account.get("platform", "")),
                "ok": False,
                "message": search_result["message"],
            }

        comment_result = batch_comment_for_account(
            account=account,
            product=product,
            strategy=strategy,
            max_comments_value=max_comments_value,
            min_likes_value=min_likes_value,
        )
        if not comment_result["ok"]:
            return {
                "platform": account.get("platform", ""),
                "platform_label": search_result["platform_label"],
                "ok": False,
                "message": (
                    f"搜索完成，已保存 {search_result['saved_count']} 条；"
                    f"但批量评论未执行：{comment_result['message']}"
                ),
            }

        return {
            "platform": account.get("platform", ""),
            "platform_label": search_result["platform_label"],
            "ok": True,
            "saved_count": search_result["saved_count"],
            "web_accessible_count": search_result["web_accessible_count"],
            "success_count": comment_result["success_count"],
            "failed_count": comment_result["failed_count"],
        }

    workflow_results = {}
    with ThreadPoolExecutor(max_workers=len(available_accounts)) as executor:
        future_map = {
            executor.submit(run_platform_workflow, account): platform
            for platform, account in available_accounts.items()
        }
        for future in as_completed(future_map):
            platform = future_map[future]
            try:
                workflow_results[platform] = future.result()
            except Exception as exc:
                workflow_results[platform] = {
                    "platform": platform,
                    "platform_label": PLATFORM_LABELS.get(platform, platform),
                    "ok": False,
                    "message": f"执行异常：{exc}",
                }

    for platform, label in PLATFORM_LABELS.items():
        if platform not in available_accounts:
            flash(f"{label} 未找到在线账号，已跳过", "warning")

    overall_success = False
    for platform in PLATFORM_LABELS:
        result = workflow_results.get(platform)
        if not result:
            continue
        if result["ok"]:
            overall_success = overall_success or result["success_count"] > 0
            flash(
                (
                    f"{result['platform_label']} 一键工作流完成："
                    f"已搜索保存 {result['saved_count']} 条，"
                    f"网页可访问 {result['web_accessible_count']} 条，"
                    f"评论成功 {result['success_count']} 条，"
                    f"失败 {result['failed_count']} 条"
                ),
                "success" if result["success_count"] > 0 else "warning",
            )
        else:
            flash(f"{result['platform_label']} 工作流未完成：{result['message']}", "warning")

    return redirect(url_for("comments_page"))


@app.post("/comments/<int:task_id>/retry")
def retry_comment(task_id: int):
    """重试回复"""
    task = storage.get_xhs_comment_task(task_id)
    if not task:
        abort(404, "任务不存在")

    account_id = request.form.get("account_id", type=int)
    if not account_id:
        abort(400, "请选择账号")

    account = storage.get_xhs_account(account_id)
    if not account or account["status"] != "online":
        abort(400, "账号未登录")

    bot = ensure_logged_in_bot(account)
    if bot is None:
        abort(400, "账号缺少可用登录信息")
    if account_id not in bots and getattr(bot, "last_error", ""):
        abort(400, bot.last_error)

    # 重试回复
    success = bot.comment_post(task["post_id"], task["content"])

    storage.update_xhs_comment_task(task_id, {
        "status": "success" if success else "failed",
        "error_message": "" if success else "重试回复失败",
        "commented_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S") if success else "",
    })

    if success:
        storage.insert_xhs_stat({"comments_success": 1})
    else:
        storage.insert_xhs_stat({"comments_failed": 1})

    return redirect(url_for("comments_page"))


# ==================== 产品管理 ====================

@app.get("/products")
def products_page():
    """产品管理页面"""
    products = storage.list_products()
    return render_template("products.html", products=products)


# ==================== Tardis 营销活动 ====================

@app.get("/tardis")
def tardis_campaign_page():
    """Tardis 营销活动页面"""
    accounts = storage.list_xhs_accounts()
    online_accounts = [a for a in accounts if a.get("status") == "online"]
    return render_template(
        "tardis_campaign.html",
        accounts=online_accounts,
        tardis_keywords=TARDIS_KEYWORDS,
    )


@app.post("/tardis/campaign")
def run_tardis_campaign():
    """执行 Tardis 营销活动"""
    account_id = request.form.get("account_id", type=int)
    keyword = request.form.get("keyword", "").strip()
    strategy = request.form.get("strategy", "diagnosis")
    limit = request.form.get("limit", "50").strip()
    max_comments = request.form.get("max_comments", "30").strip()

    if not account_id:
        flash("请选择账号", "error")
        return redirect(url_for("tardis_campaign_page"))

    if not keyword:
        flash("请选择或输入关键词", "error")
        return redirect(url_for("tardis_campaign_page"))

    try:
        limit_value = max(10, min(int(limit), 100))
        max_comments_value = max(1, min(int(max_comments), 50))
    except ValueError:
        flash("搜索数量和评论数量必须是数字", "error")
        return redirect(url_for("tardis_campaign_page"))

    # 构建带过滤的搜索关键词
    search_keyword = build_search_query(keyword, add_filters=True)

    account = storage.get_xhs_account(account_id)
    if not account or account["status"] != "online":
        flash("账号未登录", "error")
        return redirect(url_for("tardis_campaign_page"))

    # 获取 Tardis 产品
    products = storage.list_products()
    tardis_product = None
    for p in products:
        if p.get("code", "").lower() == "tardis":
            tardis_product = p
            break

    if not tardis_product:
        # 创建临时 Tardis 产品
        tardis_product = {
            "code": "tardis",
            "name": "Tardis",
            "description": "Raw Tick-Level Market Data API - 提供 spot / perpetual / futures / options 的原始 tick 数据",
            "price": "详见官网",
            "wechat_id": "",
        }

    # 先清空历史帖子
    storage.clear_xhs_hot_posts("x")
    flash("已清空历史帖子，开始执行 Tardis 营销活动", "info")

    # 搜索帖子
    search_result = search_posts_for_account(account, search_keyword, limit_value)
    if not search_result.get("ok"):
        flash(f"搜索失败: {search_result.get('message')}", "error")
        return redirect(url_for("tardis_campaign_page"))

    flash(f"搜索完成，找到 {search_result.get('saved_count', 0)} 条帖子", "success")

    # 执行批量评论
    comment_result = batch_comment_for_account(
        account=account,
        product=tardis_product,
        strategy=strategy,
        max_comments_value=max_comments_value,
        min_likes_value=0,
    )

    if comment_result.get("ok"):
        flash(
            f"Tardis 营销完成！成功评论 {comment_result.get('success_count', 0)} 条，失败 {comment_result.get('failed_count', 0)} 条",
            "success" if comment_result.get("success_count", 0) > 0 else "warning",
        )
    else:
        flash(f"评论失败: {comment_result.get('message')}", "error")

    return redirect(url_for("tardis_campaign_page"))


# ==================== Tardis 批量营销活动 ====================

@app.get("/tardis/batch")
def tardis_batch_campaign_page():
    """Tardis 批量营销活动页面"""
    accounts = storage.list_xhs_accounts()
    online_accounts = [a for a in accounts if a.get("status") == "online"]
    return render_template(
        "tardis_batch_campaign.html",
        accounts=online_accounts,
        full_keywords=FULL_TARDIS_KEYWORDS,
    )


@app.post("/tardis/batch_campaign")
def run_tardis_batch_campaign():
    """执行 Tardis 批量营销活动 - 遍历所有关键词"""
    from tardis_marketing import FULL_TARDIS_KEYWORDS

    # 获取参数
    x_account_id = request.form.get("x_account_id", type=int)
    bilibili_account_id = request.form.get("bilibili_account_id", type=int)
    platforms = request.form.getlist("platforms")  # 可以是 ["x"], ["bilibili"], 或 ["x", "bilibili"]
    strategy = request.form.get("strategy", "diagnosis")
    search_limit = request.form.get("search_limit", "100").strip()
    comment_limit = request.form.get("comment_limit", "100").strip()
    keywords_input = request.form.get("keywords_input", "").strip()
    use_all_keywords = request.form.get("use_all_keywords") == "on"

    if not platforms:
        flash("请选择至少一个平台", "error")
        return redirect(url_for("tardis_batch_campaign_page"))

    # 确定使用的关键词
    if use_all_keywords:
        keywords = FULL_TARDIS_KEYWORDS
    elif keywords_input:
        keywords = [k.strip() for k in keywords_input.split(",") if k.strip()]
    else:
        flash("请选择使用全部关键词或输入自定义关键词", "error")
        return redirect(url_for("tardis_batch_campaign_page"))

    # 验证账号
    accounts_dict = {}
    if "x" in platforms:
        if not x_account_id:
            flash("选择了 X.com 平台，请选择 X.com 账号", "error")
            return redirect(url_for("tardis_batch_campaign_page"))
        x_account = storage.get_xhs_account(x_account_id)
        if not x_account or x_account.get("status") != "online":
            flash("X.com 账号未登录或状态异常", "error")
            return redirect(url_for("tardis_batch_campaign_page"))
        accounts_dict["x"] = x_account

    if "bilibili" in platforms:
        if not bilibili_account_id:
            flash("选择了哔哩哔哩平台，请选择哔哩哔哩账号", "error")
            return redirect(url_for("tardis_batch_campaign_page"))
        bilibili_account = storage.get_xhs_account(bilibili_account_id)
        if not bilibili_account or bilibili_account.get("status") != "online":
            flash("哔哩哔哩账号未登录或状态异常", "error")
            return redirect(url_for("tardis_batch_campaign_page"))
        accounts_dict["bilibili"] = bilibili_account

    # 解析数量限制
    try:
        search_limit_value = max(10, min(int(search_limit), 100))
        comment_limit_value = max(1, min(int(comment_limit), 100))
    except ValueError:
        flash("搜索数量和评论数量必须是数字", "error")
        return redirect(url_for("tardis_batch_campaign_page"))

    # 获取 Tardis 产品
    products = storage.list_products()
    tardis_product = None
    for p in products:
        if p.get("code", "").lower() == "tardis":
            tardis_product = p
            break
    if not tardis_product:
        tardis_product = {
            "code": "tardis",
            "name": "Tardis",
            "description": "Raw Tick-Level Market Data API",
            "price": "详见官网",
            "wechat_id": "",
        }

    # 统计结果
    total_stats = {
        "keywords_processed": 0,
        "posts_found": 0,
        "comments_success": 0,
        "comments_failed": 0,
    }

    # 遍历每个关键词
    for keyword in keywords:
        keyword = keyword.strip()
        if not keyword:
            continue

        total_stats["keywords_processed"] += 1
        search_keyword = build_search_query(keyword, add_filters=True)

        # 对每个平台执行
        for platform in platforms:
            account = accounts_dict.get(platform)
            if not account:
                continue

            # 清空该平台的帖子
            storage.clear_xhs_hot_posts(platform)

            # 搜索
            search_result = search_posts_for_account(account, search_keyword, search_limit_value)
            if search_result.get("ok"):
                total_stats["posts_found"] += search_result.get("saved_count", 0)

            # 评论
            comment_result = batch_comment_for_account(
                account=account,
                product=tardis_product,
                strategy=strategy,
                max_comments_value=comment_limit_value,
                min_likes_value=0,
            )
            if comment_result.get("ok"):
                total_stats["comments_success"] += comment_result.get("success_count", 0)
                total_stats["comments_failed"] += comment_result.get("failed_count", 0)

    flash(
        f"批量营销完成！共处理 {total_stats['keywords_processed']} 个关键词，"
        f"找到 {total_stats['posts_found']} 条帖子，"
        f"成功评论 {total_stats['comments_success']} 条，失败 {total_stats['comments_failed']} 条",
        "success" if total_stats["comments_success"] > 0 else "warning",
    )

    return redirect(url_for("tardis_batch_campaign_page"))


@app.post("/products")
def add_product():
    """添加产品"""
    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    price = request.form.get("price", "").strip()
    wechat_id = request.form.get("wechat_id", "").strip()
    target_tags = request.form.get("target_tags", "").strip()

    if not code or not name:
        abort(400, "产品代码和名称不能为空")

    tags = [t.strip() for t in target_tags.split(",") if t.strip()]

    storage.insert_product({
        "code": code,
        "name": name,
        "description": description,
        "price": price,
        "wechat_id": wechat_id,
        "target_tags": tags,
    })

    return redirect(url_for("products_page"))


@app.post("/products/<int:product_id>/delete")
def delete_product(product_id: int):
    """删除产品"""
    storage.update_product(product_id, {"status": "deleted"})
    return redirect(url_for("products_page"))


@app.post("/products/edit")
def edit_product():
    """编辑产品"""
    product_id = request.form.get("product_id", type=int)
    code = request.form.get("code", "").strip()
    name = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    price = request.form.get("price", "").strip()
    wechat_id = request.form.get("wechat_id", "").strip()
    target_tags = request.form.get("target_tags", "").strip()

    if not product_id or not code or not name:
        abort(400, "产品ID、代码和名称不能为空")

    tags = [t.strip() for t in target_tags.split(",") if t.strip()]

    storage.update_product(product_id, {
        "code": code,
        "name": name,
        "description": description,
        "price": price,
        "wechat_id": wechat_id,
        "target_tags": tags,
    })

    flash("产品更新成功", "success")
    return redirect(url_for("products_page"))


# ==================== 统计报表 ====================

@app.get("/stats")
def stats_page():
    """统计页面"""
    stats = storage.get_xhs_stats(days=30)
    accounts = storage.list_xhs_accounts()
    return render_template(
        "stats.html",
        stats=stats,
        accounts=accounts,
    )


# ==================== API 接口 ====================

@app.get("/api/accounts")
def api_accounts():
    """获取账号列表"""
    accounts = storage.list_xhs_accounts()
    return jsonify(accounts)


@app.get("/api/hot-posts")
def api_hot_posts():
    """获取热帖列表"""
    limit = request.args.get("limit", "50").strip()
    platform = request.args.get("platform")
    posts = storage.list_xhs_hot_posts(int(limit), platform=platform)
    return jsonify(posts)


@app.get("/api/comment-tasks")
def api_comment_tasks():
    """获取评论任务列表"""
    status = request.args.get("status")
    platform = request.args.get("platform")
    tasks = storage.list_xhs_comment_tasks(status, platform=platform)
    return jsonify(tasks)


@app.get("/api/stats")
def api_stats():
    """获取统计数据"""
    days = request.args.get("days", "7").strip()
    stats = storage.get_xhs_stats(int(days))
    return jsonify(stats)


# ==================== 设置 ====================

@app.get("/settings")
def settings_page():
    """设置页面"""
    return render_template("settings.html")


# ==================== 搜狗微信爬虫 ====================

@app.get("/wechat")
def wechat_page():
    """搜狗微信爬虫页面"""
    articles = storage.list_wechat_articles(limit=100)
    return render_template("wechat_spider.html", articles=articles, progress=crawl_progress)


@app.get("/wechat/progress")
def wechat_progress():
    """获取爬取进度"""
    return jsonify(crawl_progress)


@app.get("/wechat/qr_image")
def wechat_qr_image():
    """代理微信二维码图片；若返回的是微信防盗链占位图则返回 404 并提示"""
    from urllib.parse import unquote
    from flask import Response

    url = request.args.get("url", "")
    if not url:
        abort(404)
    url = unquote(url)

    if "/s?" in url:
        abort(403)
    if "wx.qlogo.cn" not in url and "mmbiz.qpic.cn" not in url:
        abort(403)

    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Referer": "https://mp.weixin.qq.com/",
            },
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
            content_type = resp.headers.get("Content-Type", "image/png")
        from sogou_wechat_spider import is_wechat_placeholder_image
        if is_wechat_placeholder_image(data):
            return Response(
                '{"error":"wechat_placeholder","message":"此图片来自微信公众平台，未经允许不可引用，无法显示。请复制文章链接在微信内打开查看二维码。"}',
                status=404,
                mimetype="application/json",
            )
        return Response(data, mimetype=content_type)
    except Exception as e:
        app.logger.warning(f"qr_image proxy failed: {e}")
        abort(502)


@app.post("/wechat/fetch_qr")
def wechat_fetch_qr():
    """从文章链接中提取二维码图片"""
    from urllib.parse import unquote

    article_url = request.form.get("url", "")
    if not article_url:
        return jsonify({"success": False, "error": "缺少 URL"})

    article_url = unquote(article_url)
    print(f"提取文章二维码: {article_url[:80]}...")

    try:
        # 使用爬虫访问文章并获取二维码
        spider = SogouWechatSpider()
        detail = spider.get_article_detail(article_url)
        spider.close()

        if not detail:
            return jsonify({"success": False, "error": "获取文章失败"})

        qr_codes = detail.get("qr_codes", [])
        if qr_codes:
            # 优先返回页面截图得到的 base64（可绕过防盗链），否则返回 CDN URL
            first = qr_codes[0]
            if first.get("screenshot_base64"):
                return jsonify({
                    "success": True,
                    "qr_url": first.get("src", ""),
                    "qr_image_data": f"data:image/png;base64,{first['screenshot_base64']}",
                })
            qr_url = first.get("src", "")
            for qr in qr_codes:
                src = qr.get("src", "")
                if "mmbiz.qpic.cn" in src or "wx.qlogo.cn" in src:
                    qr_url = src
                    break
            return jsonify({"success": True, "qr_url": qr_url})
        else:
            return jsonify({
                "success": False,
                "error": "文章中未找到二维码，或二维码图片受微信公众平台保护无法获取。请复制链接在微信内打开查看。",
            })

    except Exception as e:
        app.logger.error(f"fetch_qr failed: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)})


@app.post("/wechat/update_qr")
def wechat_update_qr():
    """更新文章的二维码URL"""
    article_id = request.form.get("article_id", type=int)
    qr_url = request.form.get("qr_url", "")

    if not article_id or not qr_url:
        return jsonify({"success": False, "error": "缺少参数"})

    try:
        storage.db.execute(
            "UPDATE wechat_articles SET qr_code_url = ? WHERE id = ?",
            (qr_url, article_id)
        )
        storage.db.commit()
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.post("/wechat/crawl")
def wechat_crawl():
    """执行爬取"""
    global crawl_progress

    keywords = request.form.get("keywords", "").strip()
    days = int(request.form.get("days", 7))
    max_pages = int(request.form.get("max_pages", 3))

    if not keywords:
        flash("请输入搜索关键词", "error")
        return redirect(url_for("wechat_page"))

    # 解析关键词
    keyword_list = [k.strip() for k in keywords.split(",") if k.strip()]

    if not keyword_list:
        flash("请输入有效的关键词", "error")
        return redirect(url_for("wechat_page"))

    # 初始化进度状态
    crawl_progress["status"] = "running"
    crawl_progress["total_keywords"] = len(keyword_list)
    crawl_progress["total_pages"] = max_pages
    crawl_progress["total_articles"] = 0
    crawl_progress["total_qr_codes"] = 0
    crawl_progress["current_keyword"] = ""
    crawl_progress["current_page"] = 0

    # 创建爬虫实例
    spider = SogouWechatSpider()

    # 执行爬取
    total_articles = 0
    total_qr_codes = 0

    for idx, keyword in enumerate(keyword_list):
        crawl_progress["current_keyword"] = keyword
        crawl_progress["message"] = f"正在搜索关键词: {keyword}"

        for page in range(1, max_pages + 1):
            crawl_progress["current_page"] = page
            crawl_progress["message"] = f"正在搜索「{keyword}」第 {page} 页..."

            articles = spider.search_articles(keyword, days=days, page=page)

            if not articles:
                break

            for i, article in enumerate(articles):
                crawl_progress["message"] = f"正在处理第 {i+1}/{len(articles)} 篇文章..."

                # 获取文章详情（包括二维码）
                detail = spider.get_article_detail(article["link"])

                if detail:
                    article.update(detail)

                    # 提取二维码
                    qr_code_url = ""
                    qr_code_type = ""
                    if detail.get("qr_codes"):
                        qr_code_url = detail["qr_codes"][0].get("src", "")
                        qr_code_type = detail["qr_codes"][0].get("type", "")

                    # 保存到数据库
                    article_data = {
                        "title": article.get("title"),
                        "link": article.get("link"),
                        "source": article.get("source"),
                        "author": article.get("author"),
                        "pub_time": article.get("pub_time"),
                        "abstract": article.get("abstract"),
                        "keyword": keyword,
                        "content": article.get("content"),
                        "qr_code_url": qr_code_url,
                        "qr_code_type": qr_code_type,
                    }

                    storage.insert_wechat_article(article_data)
                    total_articles += 1
                    crawl_progress["total_articles"] = total_articles

                    if qr_code_url:
                        total_qr_codes += 1
                        crawl_progress["total_qr_codes"] = total_qr_codes

                # 避免请求过快
                time.sleep(1)

            # 避免被封
            time.sleep(2)

    # 完成
    spider.close()
    crawl_progress["status"] = "completed"
    crawl_progress["message"] = f"爬取完成！共获取 {total_articles} 篇文章，其中 {total_qr_codes} 篇包含二维码"

    flash(f"爬取完成！共获取 {total_articles} 篇文章，其中 {total_qr_codes} 篇包含二维码", "success")
    return redirect(url_for("wechat_page"))


@app.post("/wechat/delete")
def wechat_delete_article():
    """删除文章"""
    article_id = request.form.get("article_id")

    if not article_id:
        flash("参数错误", "error")
        return redirect(url_for("wechat_page"))

    try:
        article_id = int(article_id)
    except ValueError:
        flash("参数错误", "error")
        return redirect(url_for("wechat_page"))

    storage.delete_wechat_article(article_id)
    flash("文章已删除", "success")
    return redirect(url_for("wechat_page"))


@app.post("/wechat/clear")
def wechat_clear_articles():
    """清空文章"""
    keyword = request.form.get("keyword", "").strip()

    count = storage.clear_wechat_articles(keyword if keyword else None)
    flash(f"已清空 {count} 篇文章", "success")
    return redirect(url_for("wechat_page"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=True)
