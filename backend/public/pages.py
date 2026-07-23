"""游客前台页面路由。

这个文件负责所有"普通访问者能看到和能操作"的页面：
1. 首页
2. 文章浏览
3. 网址浏览
4. 留言浏览与发布（需管理员审核）
"""

from xml.sax.saxutils import escape

import requests
from flask import Response, current_app, flash, redirect, request, send_from_directory, url_for

from backend.admin.auth import create_record
from backend.admin.settings import (
    get_homepage_hero_settings,
    render_with_background,
)
from backend.core.forms import MessageForm
from backend.core.models import BlogPost, Link, Message, db


def verify_turnstile():
    """Validate Turnstile when production keys are configured."""
    secret = current_app.config.get('TURNSTILE_SECRET_KEY', '').strip()
    if not secret:
        return True

    token = request.form.get('cf-turnstile-response', '').strip()
    if not token:
        return False

    try:
        response = requests.post(
            'https://challenges.cloudflare.com/turnstile/v0/siteverify',
            data={
                'secret': secret,
                'response': token,
                'remoteip': request.remote_addr,
            },
            timeout=5,
        )
        return bool(response.ok and response.json().get('success'))
    except (requests.RequestException, ValueError):
        return False


def register_public_routes(app):
    """Register all public-facing pages for visitors."""

    @app.route('/')
    def index():
        """Render the homepage with the current hero text and background."""
        homepage_hero = get_homepage_hero_settings()
        recent_posts = (
            BlogPost.query.filter_by(is_published=True)
            .order_by(BlogPost.created_at.desc())
            .limit(2)
            .all()
        )
        return render_with_background(
            'public/index.html',
            'home_background',
            title='首页',
            homepage_hero=homepage_hero,
            recent_posts=recent_posts,
        )

    @app.route('/articles')
    def articles():
        """Show approved blog posts."""
        pagination = (
            BlogPost.query.filter_by(is_published=True)
            .order_by(BlogPost.created_at.desc())
            .paginate(page=request.args.get('page', 1, type=int), per_page=6)
        )
        return render_with_background(
            'public/articles.html',
            'home_background',
            title='文章',
            blog_posts=pagination.items,
            pagination=pagination,
        )

    @app.route('/links')
    def links():
        """Show approved links."""
        pagination = (
            Link.query.filter_by(is_approved=True)
            .order_by(Link.created_at.desc())
            .paginate(page=request.args.get('page', 1, type=int), per_page=9)
        )
        return render_with_background(
            'public/links.html',
            'home_background',
            title='网址',
            items=pagination.items,
            pagination=pagination,
        )

    @app.route('/messages', methods=['GET', 'POST'])
    def messages():
        """Show approved guestbook messages and accept new submissions (pending approval)."""
        form = MessageForm(prefix='public-message')
        if request.method == 'POST' and form.website.data:
            flash('留言已提交，等待管理员审核后显示。')
            return redirect(url_for('messages'))

        if form.validate_on_submit():
            if not verify_turnstile():
                flash('人机验证失败，请稍后重试。')
                return redirect(url_for('messages'))
            # 留言需要管理员审核，提交后不立即显示。
            create_record(
                Message,
                nickname=form.nickname.data,
                content=form.content.data,
                is_approved=False,
            )
            flash('留言已提交，等待管理员审核后显示。')
            return redirect(url_for('messages'))

        pagination = (
            Message.query.filter_by(is_approved=True)
            .order_by(Message.created_at.desc())
            .paginate(page=request.args.get('page', 1, type=int), per_page=12)
        )
        return render_with_background(
            'public/messages.html',
            'home_background',
            title='留言',
            form=form,
            items=pagination.items,
            pagination=pagination,
        )

    @app.route('/sitemap.xml')
    def sitemap():
        urls = [
            url_for('index', _external=True),
            url_for('articles', _external=True),
            url_for('links', _external=True),
            url_for('messages', _external=True),
        ]
        published_slugs = db.session.scalars(
            db.select(BlogPost.slug).where(BlogPost.is_published.is_(True))
        )
        urls.extend(
            url_for('view_blog_post', slug=slug, _external=True)
            for slug in published_slugs
        )
        body = ''.join(f'<url><loc>{escape(url)}</loc></url>' for url in urls)
        return Response(
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            f'{body}</urlset>',
            mimetype='application/xml',
        )

    @app.route('/robots.txt')
    def robots():
        body = '\n'.join(
            [
                'User-agent: *',
                'Allow: /',
                'Disallow: /admin',
                'Disallow: /manage',
                'Disallow: /api',
                f"Sitemap: {url_for('sitemap', _external=True)}",
                '',
            ]
        )
        return Response(body, mimetype='text/plain')

    @app.route('/favicon.ico')
    def favicon():
        return send_from_directory(
            current_app.static_folder,
            'assets/favicon.png',
            mimetype='image/png',
            max_age=604800,
        )
