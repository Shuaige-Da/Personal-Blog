"""Flask 应用入口文件。

这个文件的职责很单一：
1. 创建 Flask 应用对象。
2. 加载配置。
3. 初始化数据库、登录系统、CSRF 防护。
4. 把不同功能模块的路由注册进来。

如果你以后想找“程序是从哪里开始跑起来的”，先看这个文件。
"""

import os
import secrets

from flask import Flask, g, request
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.middleware.proxy_fix import ProxyFix

from backend.admin.auth import apply_security_headers, csrf, login_manager, register_admin_routes
from backend.admin.blog import register_blog_admin_routes
from backend.admin.content import register_admin_feature_routes
from backend.admin.review import register_admin_review_routes
from backend.admin.settings import initialize_site_defaults, register_admin_settings_routes
from backend.core.config import (
    Config,
    PROJECT_ROOT,
    env_flag,
    get_local_dev_secret_key,
    require_secret_key,
    validate_secret_key,
)
from backend.admin.hermes import register_hermes_routes
from backend.core.models import db
from backend.public.pages import register_public_routes

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    headers_enabled=True,
)


def create_app(test_config=None):
    """Create and configure the Flask application instance."""
    project_root = str(PROJECT_ROOT)
    app = Flask(
        __name__,
        template_folder=os.path.join(project_root, 'frontend', 'templates'),
        static_folder=os.path.join(project_root, 'frontend', 'static'),
    )

    # 1. 读取 config.py 里的所有配置项。
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    if app.config.get('TESTING') and (
        not test_config or 'TRUSTED_HOSTS' not in test_config
    ):
        app.config['TRUSTED_HOSTS'] = ['localhost', '127.0.0.1']

    if app.config.get('TESTING') and not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = secrets.token_urlsafe(32)
    elif app.config.get('LOCAL_DEV') and not app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = get_local_dev_secret_key()
    elif app.config.get('SECRET_KEY'):
        app.config['SECRET_KEY'] = validate_secret_key(app.config['SECRET_KEY'])
    else:
        app.config['SECRET_KEY'] = require_secret_key()

    # 2. 让 Flask 在反向代理环境下也能正确识别真实 IP、协议和主机。
    if app.config.get('PROXY_FIX_ENABLED'):
        app.wsgi_app = ProxyFix(
            app.wsgi_app,
            x_for=app.config['PROXY_FIX_X_FOR'],
            x_proto=app.config['PROXY_FIX_X_PROTO'],
            x_host=app.config['PROXY_FIX_X_HOST'],
        )

    # 3. 初始化扩展组件。后面其它文件里会直接使用这些全局对象。
    db.init_app(app)
    csrf.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)

    @app.before_request
    def prepare_request_security_context():
        g.csp_nonce = secrets.token_urlsafe(18)

    @app.context_processor
    def inject_security_context():
        return {
            'csp_nonce': g.get('csp_nonce', ''),
            'turnstile_site_key': app.config.get('TURNSTILE_SITE_KEY', ''),
            'totp_required': bool(app.config.get('ADMIN_TOTP_SECRET')),
        }

    # 4. 注册不同业务模块的路由。
    # 这样 URL 和处理逻辑就按功能拆分到了独立文件中。
    register_public_routes(app)
    register_admin_routes(app)
    register_admin_feature_routes(app)
    register_admin_review_routes(app)
    register_admin_settings_routes(app)
    register_blog_admin_routes(app)
    register_hermes_routes(app)

    limiter.limit('5 per minute; 20 per hour')(app.view_functions['login'])
    limiter.limit('3 per hour')(app.view_functions['messages'])

    @app.after_request
    def add_security_headers(response):
        """Attach security-related headers to every response."""
        return apply_security_headers(response)

    @app.after_request
    def add_cache_policy(response):
        if request.path.startswith('/static/'):
            response.headers.setdefault('Cache-Control', 'public, max-age=604800')
        elif request.path.startswith(('/login', '/admin', '/manage', '/api/')):
            response.headers.setdefault('Cache-Control', 'no-store')
        return response

    # 5. 在应用上下文里初始化数据库默认数据、上传目录等。
    with app.app_context():
        initialize_site_defaults(app)

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(
        host=os.environ.get('FLASK_RUN_HOST', '127.0.0.1'),
        port=int(os.environ.get('FLASK_RUN_PORT', 5000)),
        debug=env_flag('FLASK_DEBUG'),
        use_reloader=env_flag('FLASK_AUTO_RELOAD', True),
    )
