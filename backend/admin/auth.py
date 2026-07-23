"""管理员认证与安全相关逻辑。

你可以把这个文件理解成后台的“门卫”：
1. 负责登录和退出。
2. 负责判断当前用户是不是管理员。
3. 负责加安全响应头。
4. 提供一些多个后台模块都会复用的小工具函数。
"""

from functools import wraps
from urllib.parse import urlsplit

from flask import current_app, flash, g, redirect, request, session, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from flask_wtf.csrf import CSRFProtect
import pyotp

from backend.core.forms import LoginForm
from backend.core.models import User, db


csrf = CSRFProtect()
login_manager = LoginManager()
login_manager.login_view = 'login'


@login_manager.user_loader
def load_user(user_id):
    """Load the current user for Flask-Login by primary key."""
    return db.session.get(User, int(user_id))


def build_content_security_policy():
    """Build the site's Content-Security-Policy header value."""
    directives = {
        'default-src': ["'self'"],
        'base-uri': ["'self'"],
        'form-action': ["'self'"],
        'frame-ancestors': ["'none'"],
        'object-src': ["'none'"],
        'img-src': ["'self'", 'data:', 'blob:'],
        'media-src': ["'self'", 'blob:'],
        'font-src': ["'self'"],
        'style-src': ["'self'", "'unsafe-inline'"],
        'script-src': ["'self'", f"'nonce-{g.csp_nonce}'"],
        'connect-src': ["'self'"],
        'frame-src': ["'self'"],
    }

    # 本地开发走 HTTP，不应强制升级 HTTPS。
    if not current_app.config.get('LOCAL_DEV', False):
        directives['upgrade-insecure-requests'] = []
    if current_app.config.get('TURNSTILE_SITE_KEY'):
        directives['script-src'].append('https://challenges.cloudflare.com')
        directives['frame-src'].append('https://challenges.cloudflare.com')
        directives['connect-src'].append('https://challenges.cloudflare.com')
    return '; '.join(
        f"{directive} {' '.join(sources)}".strip()
        for directive, sources in directives.items()
    )


def apply_security_headers(response):
    """Apply common browser security headers to the outgoing response."""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = (
        'camera=(), microphone=(), geolocation=(), browsing-topics=()'
    )
    response.headers['Content-Security-Policy'] = build_content_security_policy()

    if request.is_secure:
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers.setdefault('Cross-Origin-Opener-Policy', 'same-origin')
    response.headers.setdefault('Cross-Origin-Resource-Policy', 'same-origin')

    return response


def admin_required(view_func):
    """Restrict a route so only admin users can access it."""

    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not current_user.is_admin:
            flash('你没有权限访问此页面。')
            return redirect(url_for('index'))
        return view_func(*args, **kwargs)

    return wrapped_view


def create_record(model, **kwargs):
    """Create and persist a single database record."""
    entry = model(**kwargs)
    db.session.add(entry)
    db.session.commit()
    return entry


def get_safe_next_url(raw_target):
    """Validate a next URL and only allow local relative redirects."""
    if not raw_target:
        return None

    parsed = urlsplit(raw_target)
    if parsed.scheme or parsed.netloc:
        return None
    if not parsed.path.startswith('/'):
        return None
    return raw_target


def redirect_with_fallback(default_endpoint, **values):
    """Redirect to a safe next URL or fall back to the given endpoint."""
    next_url = get_safe_next_url(request.form.get('next'))
    if next_url:
        return redirect(next_url)
    return redirect(url_for(default_endpoint, **values))


def redirect_for_user(user):
    """Send an authenticated user to the dashboard available to them."""
    endpoint = 'blog' if user.is_admin else 'index'
    return redirect(url_for(endpoint))


def register_admin_routes(app):
    """Register login and logout routes for administrator access."""

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        """Authenticate a user and route them to the correct dashboard."""
        # 已登录用户就不必重复登录了，直接送去对应页面。
        if current_user.is_authenticated:
            return redirect_for_user(current_user)

        form = LoginForm()
        if form.validate_on_submit():
            # 先按用户名查用户，再检查密码是否正确。
            user = User.query.filter_by(username=form.username.data).first()
            if user is None or not user.check_password(form.password.data):
                flash('用户名或密码错误。')
                return redirect(url_for('login'))

            totp_secret = current_app.config.get('ADMIN_TOTP_SECRET', '').strip()
            if totp_secret and not pyotp.TOTP(totp_secret).verify(
                (form.totp_code.data or '').strip(),
                valid_window=1,
            ):
                flash('动态验证码错误。')
                return redirect(url_for('login'))

            session.clear()
            login_user(user, fresh=True)
            return redirect_for_user(user)

        from backend.admin.settings import render_with_background

        return render_with_background(
            'admin/login.html',
            'home_background',
            title='管理员登录',
            form=form,
        )

    @app.route('/logout', methods=['POST'])
    @login_required
    def logout():
        """Log the current user out and return to the homepage."""
        logout_user()
        return redirect(url_for('index'))
