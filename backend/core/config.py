"""项目配置文件。

这里主要解决三件事：
1. 读环境变量。
2. 组装数据库连接和密钥。
3. 区分本地开发环境和生产环境。

Flask 启动时会把这里的 Config 类加载进去。
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlsplit

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
LOCAL_DEV_SECRET_FILE = PROJECT_ROOT / '.local-dev-secret-key'


def env_flag(name, default=False):
    """Parse a truthy environment variable into a boolean value."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}


def is_local_development():
    """Determine whether the app is running in a local development mode."""
    return (
        env_flag('LOCAL_DEV')
        or env_flag('FLASK_DEBUG')
        or os.environ.get('FLASK_ENV', '').strip().lower() == 'development'
    )


def get_local_dev_secret_key():
    """Create or reuse a local development secret key stored on disk."""
    if LOCAL_DEV_SECRET_FILE.exists():
        secret_key = LOCAL_DEV_SECRET_FILE.read_text(encoding='utf-8').strip()
        if len(secret_key) >= 32:
            return secret_key

    secret_key = secrets.token_urlsafe(48)
    LOCAL_DEV_SECRET_FILE.write_text(secret_key, encoding='utf-8')
    return secret_key


def require_secret_key():
    """Load a valid secret key and fail fast when production is misconfigured."""
    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        if is_local_development():
            return get_local_dev_secret_key()
        raise RuntimeError(
            'SECRET_KEY is required. Generate a long random value and inject it '
            'through the process environment.'
        )

    return validate_secret_key(secret_key)


def validate_secret_key(secret_key):
    """Validate an explicitly supplied session secret."""
    if secret_key == 'rainwave-top-change-this-to-a-long-random-string':
        raise RuntimeError('SECRET_KEY is still using the placeholder value.')

    if len(secret_key) < 32:
        raise RuntimeError('SECRET_KEY must be at least 32 characters long.')

    return secret_key


def build_database_uri():
    """Build the database connection string from environment variables."""
    database_url = os.environ.get('DATABASE_URL')
    if database_url:
        return database_url

    mysql_host = os.environ.get('MYSQL_HOST')
    mysql_port = os.environ.get('MYSQL_PORT', '3306')
    mysql_user = os.environ.get('MYSQL_USER')
    mysql_password = os.environ.get('MYSQL_PASSWORD')
    mysql_db = os.environ.get('MYSQL_DB')

    if all([mysql_host, mysql_user, mysql_password, mysql_db]):
        return (
            f'mysql+pymysql://{mysql_user}:{mysql_password}'
            f'@{mysql_host}:{mysql_port}/{mysql_db}?charset=utf8mb4'
        )

    return 'sqlite:///' + str(PROJECT_ROOT / 'app.db')


def build_trusted_hosts():
    """Build the list of allowed hostnames for incoming requests."""
    default_hosts = 'rainwave.top,www.rainwave.top'
    if is_local_development():
        default_hosts = '127.0.0.1,localhost'

    hosts = os.environ.get('TRUSTED_HOSTS', default_hosts)
    return [host.strip() for host in hosts.split(',') if host.strip()]


def validate_database_uri(database_uri):
    """Apply basic safety checks to the configured database connection."""
    parsed = urlsplit(database_uri)
    is_mysql = parsed.scheme.startswith('mysql')
    if not is_mysql:
        return database_uri

    username = parsed.username or ''
    if username == 'root' and not env_flag('ALLOW_ROOT_DATABASE_USER'):
        raise RuntimeError(
            'Refusing to start with MySQL root account. '
            'Create a dedicated application database user or set '
            'ALLOW_ROOT_DATABASE_USER=true only for temporary debugging.'
        )

    return database_uri


class Config:
    """Flask 使用的最终配置对象。"""

    LOCAL_DEV = is_local_development()
    # Resolve the secret inside create_app so an isolated TESTING config can be
    # injected without production environment variables at import time.
    SECRET_KEY = os.environ.get('SECRET_KEY')
    SQLALCHEMY_DATABASE_URI = validate_database_uri(build_database_uri())
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(str(PROJECT_ROOT), 'frontend', 'static', 'uploads')
    MAX_CONTENT_LENGTH = 220 * 1024 * 1024
    MAX_FORM_MEMORY_SIZE = 512 * 1024
    MAX_FORM_PARTS = 64
    SESSION_COOKIE_SECURE = not LOCAL_DEV
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_NAME = 'rainwave_session' if LOCAL_DEV else '__Host-rainwave_session'
    REMEMBER_COOKIE_SECURE = not LOCAL_DEV
    REMEMBER_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    PERMANENT_SESSION_LIFETIME = timedelta(hours=12)
    WTF_CSRF_TIME_LIMIT = 3600
    TRUSTED_HOSTS = build_trusted_hosts()
    PREFERRED_URL_SCHEME = 'http' if LOCAL_DEV else 'https'
    RATELIMIT_STORAGE_URI = os.environ.get('RATELIMIT_STORAGE_URI', 'memory://')
    TURNSTILE_SITE_KEY = os.environ.get('TURNSTILE_SITE_KEY', '')
    TURNSTILE_SECRET_KEY = os.environ.get('TURNSTILE_SECRET_KEY', '')
    ADMIN_TOTP_SECRET = os.environ.get('ADMIN_TOTP_SECRET', '')
    PROXY_FIX_ENABLED = env_flag('PROXY_FIX_ENABLED', not LOCAL_DEV)
    PROXY_FIX_X_FOR = int(os.environ.get('PROXY_FIX_X_FOR', '1'))
    PROXY_FIX_X_PROTO = int(os.environ.get('PROXY_FIX_X_PROTO', '1'))
    PROXY_FIX_X_HOST = int(os.environ.get('PROXY_FIX_X_HOST', '1'))

    # Hermes Agent 配置。未配置时使用模拟响应，方便本地开发。
    HERMES_API_URL = os.environ.get('HERMES_API_URL', '')
    HERMES_API_KEY = os.environ.get('HERMES_API_KEY', '')
    FFMPEG_BINARY = os.environ.get('FFMPEG_BINARY', 'ffmpeg')
    FFPROBE_BINARY = os.environ.get('FFPROBE_BINARY', 'ffprobe')
    AUDIO_PROCESS_TIMEOUT_SECONDS = int(os.environ.get('AUDIO_PROCESS_TIMEOUT_SECONDS', '300'))
    HERMES_ATTACHMENT_FOLDER = os.environ.get(
        'HERMES_ATTACHMENT_FOLDER',
        os.path.join(str(PROJECT_ROOT), 'instance', 'hermes_attachments'),
    )
    HERMES_ATTACHMENT_MAX_COUNT = int(os.environ.get('HERMES_ATTACHMENT_MAX_COUNT', '5'))
    HERMES_ATTACHMENT_IMAGE_MAX_BYTES = int(
        os.environ.get('HERMES_ATTACHMENT_IMAGE_MAX_BYTES', str(10 * 1024 * 1024))
    )
    HERMES_ATTACHMENT_DOCUMENT_MAX_BYTES = int(
        os.environ.get('HERMES_ATTACHMENT_DOCUMENT_MAX_BYTES', str(20 * 1024 * 1024))
    )
    HERMES_ATTACHMENT_TOTAL_MAX_BYTES = int(
        os.environ.get('HERMES_ATTACHMENT_TOTAL_MAX_BYTES', str(30 * 1024 * 1024))
    )
    HERMES_ATTACHMENT_TEXT_MAX_CHARS = int(
        os.environ.get('HERMES_ATTACHMENT_TEXT_MAX_CHARS', '100000')
    )
    HERMES_ATTACHMENT_TURN_TEXT_MAX_CHARS = int(
        os.environ.get('HERMES_ATTACHMENT_TURN_TEXT_MAX_CHARS', '200000')
    )
    HERMES_EDITOR_CONTEXT_MAX_CHARS = int(
        os.environ.get('HERMES_EDITOR_CONTEXT_MAX_CHARS', '50000')
    )
