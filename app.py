"""
多平台自动营销系统
登录平台账号 -> 搜索内容 -> 自动回复推广产品
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for

from storage import Storage
from bilibili_bot import BilibiliBot
from xiaohongshu import XiaohongshuBot, CommentGenerator, CommentStrategy, Product


BASE_DIR = Path(__file__).resolve().parent
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key")
storage = Storage(BASE_DIR / "data" / "marketing.db")

# 机器人实例缓存
bots = {}
# 后台任务
running_tasks = {}

PLATFORM_LABELS = {
    "x": "X.com",
    "bilibili": "哔哩哔哩",
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


def get_default_account_id(accounts: list[dict]) -> int | None:
    """优先使用最近登录且在线的账号作为默认账号"""
    online_accounts = [account for account in accounts if account.get("status") == "online"]
    if not online_accounts:
        return None
    online_accounts.sort(key=lambda item: item.get("last_login") or "", reverse=True)
    return online_accounts[0]["id"]


def get_bot_for_platform(platform: str):
    if platform == "bilibili":
        return BilibiliBot()
    return XiaohongshuBot()


def ensure_logged_in_bot(account: dict):
    account_id = account["id"]
    platform = account.get("platform", "x")
    if account_id in bots:
        return bots[account_id]

    bot = get_bot_for_platform(platform)
    if not account.get("cookie"):
        return None
    if not bot.login_by_cookie(account["cookie"]):
        return bot
    bots[account_id] = bot
    return bot


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

    bot = get_bot_for_platform(account.get("platform", "x"))
    bots[account_id] = bot

    success = bot.login_by_cookie(account.get("cookie", ""))

    if success:
        storage.update_xhs_account(account_id, {
            "status": "online",
            "last_login": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "cookie": bot.account.cookie if bot.account else "",
        })
        flash(f"{PLATFORM_LABELS.get(account.get('platform', 'x'), account.get('platform', 'x'))} Cookie 验证成功", "success")
    else:
        storage.update_xhs_account(account_id, {"status": "offline"})
        flash(
            bot.last_error
            or f"{PLATFORM_LABELS.get(account.get('platform', 'x'), account.get('platform', 'x'))} Cookie 验证失败",
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
    accounts = storage.list_xhs_accounts()
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
        hot_posts=hot_posts,
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
    platform = account.get("platform", "x")
    platform_label = PLATFORM_LABELS.get(platform, platform)

    bot = ensure_logged_in_bot(account)
    if bot is None:
        flash("账号缺少可用登录信息，请重新登录", "error")
        return redirect(url_for("search_page", account_id=account_id, keyword=keyword))
    if account_id not in bots and getattr(bot, "last_error", ""):
        flash(bot.last_error or "Cookie 登录失败，请到账号管理重新登录", "error")
        return redirect(url_for("search_page", account_id=account_id, keyword=keyword))

    posts = bot.search_posts(keyword, limit=limit_value)

    if not posts:
        flash(f"没有搜到{platform_label}内容。可能是 Cookie 已失效，或者页面结构变化导致抓取失败。", "warning")
        return redirect(url_for("search_page", account_id=account_id, keyword=keyword))

    checked_posts = []
    web_accessible_count = 0
    for post in posts:
        post["platform"] = platform
        is_accessible = bot.is_post_web_accessible(post.get("url", ""))
        post["web_accessible"] = is_accessible
        post["accessibility_checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        checked_posts.append(post)
        if is_accessible:
            web_accessible_count += 1

    # 保存到数据库
    saved_count = 0
    for post in checked_posts:
        storage.insert_xhs_hot_post(post)
        saved_count += 1

    # 更新统计
    storage.insert_xhs_stat({
        "posts_searched": saved_count,
    })

    flash(f"{platform_label}搜索完成，已保存 {saved_count} 条结果，其中网页可访问 {web_accessible_count} 条", "success")
    return redirect(url_for("search_page", account_id=account_id, keyword=keyword))


@app.post("/search/hot-posts/clear")
def clear_hot_posts():
    """一键清空已搜集推文"""
    account_id = request.form.get("account_id", type=int)
    platform = None
    if account_id:
        account = storage.get_xhs_account(account_id)
        platform = account.get("platform") if account else None
    if platform:
        deleted_count = storage.clear_xhs_hot_posts(platform)
        flash(f"已清空 {PLATFORM_LABELS.get(platform, platform)} 的 {deleted_count} 条已搜集内容", "success")
        return redirect(url_for("search_page", account_id=account_id))
    deleted_count = storage.clear_xhs_hot_posts()
    flash(f"已清空 {deleted_count} 条已搜集内容", "success")
    return redirect(url_for("search_page"))


# ==================== 评论任务 ====================

@app.get("/comments")
def comments_page():
    """营销回复任务页面"""
    status = request.args.get("status")
    account_id = request.args.get("account_id", type=int)
    products = storage.list_products()
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
        current_platform=current_platform,
        platform_labels=PLATFORM_LABELS,
        status=status,
    )


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
    max_comments = request.form.get("max_comments", "20").strip()
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
    platform = account.get("platform", "x")
    platform_label = PLATFORM_LABELS.get(platform, platform)

    product = storage.get_product(product_id)
    if not product:
        flash("产品不存在", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    bot = ensure_logged_in_bot(account)
    if bot is None:
        flash("账号缺少可用登录信息，请重新登录", "error")
        return redirect(url_for("comments_page", account_id=account_id))
    if account_id not in bots and getattr(bot, "last_error", ""):
        flash(bot.last_error or "Cookie 登录失败，请到账号管理重新登录", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    # 获取推文
    try:
        max_comments_value = max(1, min(int(max_comments), 50))
        min_likes_value = max(0, int(min_likes))
    except ValueError:
        flash("评论数量和点赞筛选必须是数字", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    hot_posts = storage.list_xhs_hot_posts(limit=200, platform=platform)
    hot_posts = [
        p for p in hot_posts
        if p["likes"] >= min_likes_value
        and p.get("web_accessible", False)
        and p.get("accessibility_checked_at")
    ]

    if not hot_posts:
        flash(f"没有找到已检测且可在网页端访问的{platform_label}内容，请先去搜索页重新搜索", "warning")
        return redirect(url_for("comments_page", account_id=account_id))

    # 过滤已回复的推文
    existing_tasks = storage.list_xhs_comment_tasks(status="success", platform=platform)
    commented_post_ids = {t["post_id"] for t in existing_tasks}
    posts_to_comment = [p for p in hot_posts if p["post_id"] not in commented_post_ids]

    if not posts_to_comment:
        flash(f"当前符合条件的{platform_label}内容都已经营销过了", "warning")
        return redirect(url_for("comments_page", account_id=account_id))

    web_accessible_posts = [
        post for post in posts_to_comment
        if post.get("web_accessible", False) and post.get("accessibility_checked_at")
    ]

    if not web_accessible_posts:
        flash(f"当前{platform_label}内容没有可在网页端打开的详情页，无法执行自动回复", "warning")
        return redirect(url_for("comments_page", account_id=account_id))

    # 转换策略
    try:
        strategy_enum = CommentStrategy(strategy)
    except ValueError:
        flash("评论策略无效", "error")
        return redirect(url_for("comments_page", account_id=account_id))

    # 批量回复
    success_count = 0
    failed_count = 0

    for post in web_accessible_posts[:max_comments_value]:
        # 生成评论
        comment_gen = CommentGenerator(build_product_model(product))
        comment_text = comment_gen.generate_comment(strategy_enum)

        # 回复
        success = bot.comment_post(post["post_id"], comment_text, post.get("url", ""))
        error_message = "" if success else (bot.last_error or "回复失败")

        # 保存任务
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

    # 更新统计
    storage.insert_xhs_stat({
        "comments_success": success_count,
        "comments_failed": failed_count,
    })

    if success_count and failed_count:
        flash(f"批量回复完成，成功 {success_count} 条，失败 {failed_count} 条", "warning")
    elif success_count:
        flash(f"批量回复完成，成功 {success_count} 条", "success")
    else:
        flash(f"批量回复未成功，失败 {failed_count} 条", "error")

    return redirect(url_for("comments_page", account_id=account_id))


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5055, debug=True)
