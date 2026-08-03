"""管理员设置中心。

这是项目里最“综合”的一个模块，负责：
1. 背景图 / 背景视频 / 背景轮播
2. 首页欢迎语和个性描述
3. 顶部时间组件设置
4. 默认站点设置初始化
5. 一些上传、渲染、旧数据兼容辅助函数

如果你觉得这个文件长，不用怕。
阅读时建议从文件最后的 register_admin_settings_routes() 开始往上看，
先看路由收表单，再倒回去看每个处理函数。
"""

import json
import mimetypes
import os
import re
import uuid

import filetype
from PIL import Image, UnidentifiedImageError
from flask import current_app, flash, g, redirect, render_template, request, url_for
from flask_login import login_required
from sqlalchemy import inspect, text
from werkzeug.utils import secure_filename

from backend.admin.auth import admin_required
from backend.core.constants import (
    BACKGROUND_EXTENSION_HINTS,
    CLOCK_HOUR_CYCLE_CHOICES,
    CLOCK_SHOW_DATE_CHOICES,
    CLOCK_STYLE_CHOICES,
    DEFAULT_BACKGROUND_ASSET,
    DEFAULT_BACKGROUND_KIND,
    DEFAULT_BACKGROUND_MIME,
    DEFAULT_BACKGROUND_PLAYLIST_ENABLED,
    DEFAULT_BACKGROUND_PLAYLIST_INTERVAL_SECONDS,
    DEFAULT_BACKGROUND_PLAYLIST_LIMIT,
    DEFAULT_BACKGROUND_PLAYLIST_PATHS,
    DEFAULT_CLOCK_HOUR_CYCLE,
    DEFAULT_CLOCK_SHOW_DATE,
    DEFAULT_CLOCK_STYLE,
    DEFAULT_HOMEPAGE_DESCRIPTION_COLOR,
    DEFAULT_HOMEPAGE_DESCRIPTION_FONT,
    DEFAULT_HOMEPAGE_HERO_TITLE,
    DEFAULT_HOMEPAGE_INTRO_DESCRIPTION,
    DEFAULT_HOMEPAGE_TITLE_COLOR,
    DEFAULT_HOMEPAGE_TITLE_FONT,
    DEFAULT_PAGE_TRANSITION_AXIS,
    HOMEPAGE_FONT_FAMILIES,
    LEGACY_DEFAULT_BACKGROUND_ASSET,
    MAX_UPLOAD_BASENAME_LENGTH,
    PAGE_TRANSITION_AXIS_CHOICES,
)
from backend.core.forms import (
    BackgroundForm,
    BackgroundPlaylistForm,
    ClockSettingsForm,
    HomepageDescriptionForm,
    HomepageTitleForm,
    PageTransitionSettingsForm,
)
from backend.core.models import Message, SiteSetting, User, db

UPLOAD_LIMITS = {
    'images': 12 * 1024 * 1024,
    'backgrounds': 200 * 1024 * 1024,
    'videos': 200 * 1024 * 1024,
    'music': 100 * 1024 * 1024,
}
IMAGE_MIME_TYPES = {'image/jpeg', 'image/png', 'image/webp', 'image/gif'}
VIDEO_MIME_TYPES = {'video/mp4', 'video/webm', 'video/quicktime'}
AUDIO_MIME_TYPES = {
    'audio/mpeg', 'audio/flac', 'audio/ogg', 'audio/wav', 'audio/x-wav',
    'audio/mp4',
}
ALLOWED_UPLOAD_MIMES = {
    'images': IMAGE_MIME_TYPES,
    'videos': VIDEO_MIME_TYPES,
    'music': AUDIO_MIME_TYPES,
    'backgrounds': IMAGE_MIME_TYPES | VIDEO_MIME_TYPES,
}
BACKGROUND_SETTING_KEYS = ('home_background', 'blog_background')
CLOCK_SETTING_DEFAULTS = {
    'site_clock_style': DEFAULT_CLOCK_STYLE,
    'site_clock_hour_cycle': DEFAULT_CLOCK_HOUR_CYCLE,
    'site_clock_show_date': DEFAULT_CLOCK_SHOW_DATE,
}
HOMEPAGE_HERO_SETTING_DEFAULTS = {
    'homepage_hero_title': DEFAULT_HOMEPAGE_HERO_TITLE,
    'homepage_hero_title_font': DEFAULT_HOMEPAGE_TITLE_FONT,
    'homepage_hero_title_color': DEFAULT_HOMEPAGE_TITLE_COLOR,
    'homepage_intro_description': DEFAULT_HOMEPAGE_INTRO_DESCRIPTION,
    'homepage_intro_description_font': DEFAULT_HOMEPAGE_DESCRIPTION_FONT,
    'homepage_intro_description_color': DEFAULT_HOMEPAGE_DESCRIPTION_COLOR,
}
PAGE_TRANSITION_SETTING_DEFAULTS = {
    'page_transition_axis': DEFAULT_PAGE_TRANSITION_AXIS,
}


def ensure_upload_dirs():
    """Ensure the upload directories exist before files are saved."""
    # 程序第一次启动时，如果目录不存在，就自动创建。
    for directory in ('images', 'videos', 'music', 'backgrounds'):
        os.makedirs(os.path.join(current_app.config['UPLOAD_FOLDER'], directory), exist_ok=True)


def get_settings(defaults):
    """Return multiple setting values through one request-cached query."""
    cache = g.setdefault('_site_setting_cache', {})
    missing_keys = [key for key in defaults if key not in cache]

    if missing_keys:
        stored_values = {
            setting.key: setting.value
            for setting in SiteSetting.query.filter(
                SiteSetting.key.in_(missing_keys)
            ).all()
        }
        for key in missing_keys:
            cache[key] = stored_values.get(key, defaults[key])

    return {key: cache[key] for key in defaults}


def get_setting(key, default_value=''):
    """Return a site setting value, or a default when missing."""
    return get_settings({key: default_value})[key]


def set_setting(key, value):
    """Create or update a single site setting in the current session."""
    setting = SiteSetting.query.filter_by(key=key).first()
    if setting is None:
        setting = SiteSetting(key=key, value=value)
        db.session.add(setting)
    else:
        setting.value = value
    g.setdefault('_site_setting_cache', {})[key] = value


def update_settings(settings):
    """Batch update site settings with one lookup and no implicit commit."""
    if not settings:
        return

    stored_settings = {
        setting.key: setting
        for setting in SiteSetting.query.filter(SiteSetting.key.in_(settings)).all()
    }
    cache = g.setdefault('_site_setting_cache', {})
    for key, value in settings.items():
        setting = stored_settings.get(key)
        if setting is None:
            db.session.add(SiteSetting(key=key, value=value))
        else:
            setting.value = value
        cache[key] = value


def parse_json_setting(key, default_value):
    """Read a JSON setting safely and fall back on invalid content."""
    raw_value = get_setting(key, '')
    if not raw_value:
        return default_value

    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return default_value


def is_submitted(form):
    """Check whether a specific submit button triggered the POST request."""
    return request.method == 'POST' and request.form.get(form.submit.name) is not None


def get_ordered_entries(model, sort_column, **filters):
    """Fetch model records ordered by newest first with optional filters."""
    # 这是一个通用查询工具，很多页面都要“按时间倒序显示列表”。
    query = model.query
    if filters:
        query = query.filter_by(**filters)
    return query.order_by(sort_column.desc()).all()


def sanitize_upload_filename(original_name):
    """Sanitize an uploaded filename and enforce a safe length limit."""
    filename = secure_filename(original_name or '')
    if not filename:
        return ''

    stem, extension = os.path.splitext(filename)
    safe_extension = extension[:20]
    max_stem_length = max(1, MAX_UPLOAD_BASENAME_LENGTH - len(safe_extension))
    safe_stem = (stem or 'file')[:max_stem_length]
    return f'{safe_stem}{safe_extension}'


def save_uploaded_file(storage, folder):
    """Validate and persist an uploaded file under a generated name."""
    original_name = storage.filename or ''
    filename = sanitize_upload_filename(original_name)
    if not filename:
        return None, None

    storage.stream.seek(0, os.SEEK_END)
    size = storage.stream.tell()
    storage.stream.seek(0)
    limit = UPLOAD_LIMITS.get(folder, 12 * 1024 * 1024)
    if size <= 0 or size > limit:
        flash(f'文件大小无效或超过 {limit // 1024 // 1024} MB 限制。')
        return None, original_name

    header = storage.stream.read(4096)
    storage.stream.seek(0)
    kind = filetype.guess(header)
    detected_mime = kind.mime if kind else ''
    detected_extension = kind.extension if kind else ''
    allowed_mimes = ALLOWED_UPLOAD_MIMES.get(folder, set())
    if detected_mime not in allowed_mimes:
        flash('文件真实格式与允许的媒体类型不匹配。')
        return None, original_name

    if detected_mime in IMAGE_MIME_TYPES:
        try:
            image = Image.open(storage.stream)
            image.verify()
        except (UnidentifiedImageError, OSError, ValueError):
            flash('图片文件无法安全解码。')
            storage.stream.seek(0)
            return None, original_name
        finally:
            storage.stream.seek(0)

    extension = detected_extension or os.path.splitext(filename)[1].lstrip('.')
    unique_name = f'{uuid.uuid4().hex}.{extension.lower()}'
    save_path = os.path.join(current_app.config['UPLOAD_FOLDER'], folder, unique_name)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    storage.save(save_path)
    if folder == 'backgrounds':
        g.pop('_background_library_assets', None)
    return unique_name, original_name


def detect_background_media(filename='', content_type=''):
    """Detect whether a background asset should be treated as image or video."""
    normalized_type = (content_type or '').split(';', 1)[0].strip().lower()
    if normalized_type.startswith('image/'):
        return 'image', normalized_type
    if normalized_type.startswith('video/'):
        return 'video', normalized_type

    extension = os.path.splitext((filename or '').lower())[1].lstrip('.')
    hinted_media = BACKGROUND_EXTENSION_HINTS.get(extension)
    if hinted_media:
        return hinted_media

    guessed_type, _ = mimetypes.guess_type(filename or '')
    guessed_type = (guessed_type or '').lower()
    if guessed_type.startswith('image/'):
        return 'image', guessed_type
    if guessed_type.startswith('video/'):
        return 'video', guessed_type

    return None, ''


def normalize_background_library_path(path):
    """Return a safe static path for selectable server background assets."""
    normalized = (path or '').replace('\\', '/').strip().lstrip('/')
    normalized = re.sub(r'/+', '/', normalized)
    if '..' in normalized.split('/'):
        return ''

    allowed_prefixes = ('uploads/backgrounds/', 'assets/backgrounds/')
    if not normalized.startswith(allowed_prefixes):
        return ''
    return normalized


def background_library_file_path(static_path):
    """Map a static background path to an absolute filesystem path."""
    normalized = normalize_background_library_path(static_path)
    if not normalized:
        return None

    static_root = os.path.abspath(current_app.static_folder)
    absolute_path = os.path.abspath(os.path.join(static_root, *normalized.split('/')))
    if not absolute_path.startswith(static_root + os.sep):
        return None
    return absolute_path


def list_background_library_assets():
    """List existing server-side backgrounds that can be selected in settings."""
    cached_assets = g.get('_background_library_assets')
    if cached_assets is not None:
        return cached_assets

    static_root = os.path.abspath(current_app.static_folder)
    roots = (
        ('uploads/backgrounds', os.path.join(static_root, 'uploads', 'backgrounds')),
        ('assets/backgrounds', os.path.join(static_root, 'assets', 'backgrounds')),
    )
    assets = []

    for static_prefix, directory in roots:
        if not os.path.isdir(directory):
            continue

        for filename in sorted(os.listdir(directory)):
            absolute_path = os.path.join(directory, filename)
            if not os.path.isfile(absolute_path):
                continue

            static_path = f'{static_prefix}/{filename}'
            kind, mime_type = detect_background_media(static_path)
            if kind not in {'image', 'video'}:
                continue

            assets.append(
                {
                    'path': static_path,
                    'name': filename,
                    'source': 'uploaded' if static_prefix.startswith('uploads') else 'built-in',
                    'url': url_for('static', filename=static_path),
                    'kind': kind,
                    'mime_type': mime_type,
                    'modified_at': os.path.getmtime(absolute_path),
                }
            )

    sorted_assets = sorted(
        assets,
        key=lambda item: (item['source'] != 'uploaded', -item['modified_at'], item['name']),
    )
    g._background_library_assets = sorted_assets
    return sorted_assets


def apply_background_library_selection(setting_key, static_path):
    """Use an existing server-side background asset for one background slot."""
    normalized = normalize_background_library_path(static_path)
    absolute_path = background_library_file_path(normalized)
    if not absolute_path or not os.path.isfile(absolute_path):
        raise ValueError('Selected background file does not exist.')

    background_kind, background_mime = detect_background_media(normalized)
    if background_kind not in {'image', 'video'}:
        raise ValueError('Selected background file is not a supported media type.')

    update_settings(
        {
            setting_key: normalized,
            f'{setting_key}_kind': background_kind,
            f'{setting_key}_mime': background_mime,
        }
    )
    clear_background_playlist_settings(setting_key)


def save_background_playlist_files(storages):
    """Save valid background playlist images and return their static paths."""
    saved_paths = []

    for storage in storages:
        if storage is None:
            continue

        original_name = storage.filename or ''
        if not original_name:
            continue

        kind, _ = detect_background_media(
            filename=original_name,
            content_type=storage.content_type,
        )
        if kind != 'image':
            continue

        saved_name, _ = save_uploaded_file(storage, 'backgrounds')
        if not saved_name:
            continue

        saved_paths.append(f'uploads/backgrounds/{saved_name}')

    return saved_paths


def get_background_playlist_assets(setting_key):
    """Build playlist metadata for a background that rotates across images."""
    # 这个函数的目标不是上传文件，
    # 而是把数据库里存的轮播配置整理成模板可直接使用的数据结构。
    enabled_key = f'{setting_key}_playlist_enabled'
    paths_key = f'{setting_key}_playlist_paths'
    interval_key = f'{setting_key}_playlist_interval_seconds'
    limit_key = f'{setting_key}_playlist_limit'
    values = get_settings(
        {
            enabled_key: DEFAULT_BACKGROUND_PLAYLIST_ENABLED,
            paths_key: DEFAULT_BACKGROUND_PLAYLIST_PATHS,
            interval_key: DEFAULT_BACKGROUND_PLAYLIST_INTERVAL_SECONDS,
            limit_key: DEFAULT_BACKGROUND_PLAYLIST_LIMIT,
        }
    )
    enabled = values[enabled_key] == '1'
    stored_paths = parse_json_setting(paths_key, [])

    interval_seconds_value = bounded_int(
        values[interval_key],
        default=DEFAULT_BACKGROUND_PLAYLIST_INTERVAL_SECONDS,
        minimum=1,
        maximum=3600,
    )
    image_limit_value = bounded_int(
        values[limit_key],
        default=DEFAULT_BACKGROUND_PLAYLIST_LIMIT,
        minimum=1,
        maximum=500,
    )

    assets = []
    for path in stored_paths:
        kind, mime_type = detect_background_media(path)
        if kind != 'image':
            continue

        assets.append(
            {
                'path': path,
                'url': url_for('static', filename=path),
                'kind': 'image',
                'mime_type': mime_type,
                'is_video': False,
            }
        )

    if image_limit_value < len(assets):
        assets = assets[:image_limit_value]

    return {
        'enabled': enabled and bool(assets),
        'assets': assets,
        'interval_seconds': interval_seconds_value,
        'image_limit': image_limit_value,
    }


def bounded_int(value, *, default, minimum, maximum):
    """Convert a value to an integer constrained to the supplied range."""
    try:
        parsed_value = int(value)
    except (TypeError, ValueError):
        parsed_value = int(default)
    return max(minimum, min(parsed_value, maximum))


def clear_background_playlist_settings(setting_key):
    """Reset playlist-related settings for a background slot."""
    update_settings(
        {
            f'{setting_key}_playlist_enabled': DEFAULT_BACKGROUND_PLAYLIST_ENABLED,
            f'{setting_key}_playlist_paths': DEFAULT_BACKGROUND_PLAYLIST_PATHS,
            f'{setting_key}_playlist_interval_seconds': DEFAULT_BACKGROUND_PLAYLIST_INTERVAL_SECONDS,
            f'{setting_key}_playlist_limit': DEFAULT_BACKGROUND_PLAYLIST_LIMIT,
        }
    )


def get_clock_settings():
    """Return validated clock settings for template rendering."""
    values = get_settings(CLOCK_SETTING_DEFAULTS)
    style = values['site_clock_style']
    if style not in CLOCK_STYLE_CHOICES:
        style = DEFAULT_CLOCK_STYLE

    hour_cycle = values['site_clock_hour_cycle']
    if hour_cycle not in CLOCK_HOUR_CYCLE_CHOICES:
        hour_cycle = DEFAULT_CLOCK_HOUR_CYCLE

    show_date = values['site_clock_show_date']
    if show_date not in CLOCK_SHOW_DATE_CHOICES:
        show_date = DEFAULT_CLOCK_SHOW_DATE

    return {
        'style': style,
        'hour_cycle': hour_cycle,
        'show_date': show_date == '1',
    }


def normalize_hex_color(value, fallback):
    """Normalize a hex color string or return a fallback value."""
    candidate = (value or '').strip()
    if re.fullmatch(r'#[0-9A-Fa-f]{6}', candidate):
        return candidate.upper()
    return fallback


def get_homepage_hero_settings():
    """Assemble homepage title and description settings for templates."""
    values = get_settings(HOMEPAGE_HERO_SETTING_DEFAULTS)
    title_font_key = values['homepage_hero_title_font']
    if title_font_key not in HOMEPAGE_FONT_FAMILIES:
        title_font_key = DEFAULT_HOMEPAGE_TITLE_FONT

    description_font_key = values['homepage_intro_description_font']
    if description_font_key not in HOMEPAGE_FONT_FAMILIES:
        description_font_key = DEFAULT_HOMEPAGE_DESCRIPTION_FONT

    return {
        'title': values['homepage_hero_title'],
        'description': values['homepage_intro_description'],
        'title_font': title_font_key,
        'title_font_family': HOMEPAGE_FONT_FAMILIES[title_font_key],
        'title_color': normalize_hex_color(
            values['homepage_hero_title_color'],
            DEFAULT_HOMEPAGE_TITLE_COLOR,
        ),
        'description_font': description_font_key,
        'description_font_family': HOMEPAGE_FONT_FAMILIES[description_font_key],
        'description_color': normalize_hex_color(
            values['homepage_intro_description_color'],
            DEFAULT_HOMEPAGE_DESCRIPTION_COLOR,
        ),
    }


def get_page_transition_settings():
    """Return the validated public-page transition configuration."""
    values = get_settings(PAGE_TRANSITION_SETTING_DEFAULTS)
    axis = values['page_transition_axis']
    if axis not in PAGE_TRANSITION_AXIS_CHOICES:
        axis = DEFAULT_PAGE_TRANSITION_AXIS
    return {'axis': axis}


def get_background_asset(setting_key):
    """Build the background asset payload consumed by templates."""
    get_settings(build_background_setting_defaults(setting_key))

    # 优先使用轮播配置；如果没有轮播，再回退到单个背景图/视频。
    playlist = get_background_playlist_assets(setting_key)
    if playlist['enabled']:
        first_asset = playlist['assets'][0]
        return {
            **first_asset,
            'is_playlist': len(playlist['assets']) > 1,
            'playlist_assets': playlist['assets'],
            'playlist_interval_seconds': playlist['interval_seconds'],
            'playlist_image_limit': playlist['image_limit'],
        }

    kind_key = f'{setting_key}_kind'
    mime_key = f'{setting_key}_mime'
    values = get_settings(
        {
            setting_key: DEFAULT_BACKGROUND_ASSET,
            kind_key: '',
            mime_key: '',
        }
    )
    path = values[setting_key]
    if path.startswith(('uploads/', 'assets/')) and background_library_file_path(path) is None:
        path = DEFAULT_BACKGROUND_ASSET
    stored_kind = values[kind_key]
    stored_mime = values[mime_key]
    kind, mime_type = detect_background_media(path, stored_mime)

    if stored_kind in {'image', 'video'}:
        kind = stored_kind
    if not kind:
        kind = DEFAULT_BACKGROUND_KIND
    if stored_mime:
        mime_type = stored_mime

    return {
        'path': path,
        'url': url_for('static', filename=path),
        'kind': kind,
        'mime_type': mime_type,
        'is_video': kind == 'video',
        'is_playlist': False,
        'playlist_assets': [],
        'playlist_interval_seconds': 0,
        'playlist_image_limit': 0,
    }


def render_with_background(template_name, background_setting_key, **context):
    """Render a template with the current background and clock context."""
    # 这是全站很重要的复用函数：
    # 它会把背景资源和时间组件设置一起塞给模板。
    render_defaults = {
        **build_background_setting_defaults(background_setting_key),
        **PAGE_TRANSITION_SETTING_DEFAULTS,
    }
    show_clock = request.endpoint in {'index', 'blog'}
    if show_clock:
        render_defaults.update(CLOCK_SETTING_DEFAULTS)
    get_settings(render_defaults)

    active_background = get_background_asset(background_setting_key)

    return render_template(
        template_name,
        background_asset=active_background,
        clock_settings=get_clock_settings() if show_clock else None,
        current_endpoint=request.endpoint,
        page_transition=get_page_transition_settings(),
        **context,
    )


def ensure_varchar_column_capacity(table_name, column_name, required_length):
    """Enlarge a MySQL VARCHAR column when legacy schema is too short."""
    inspector = inspect(db.engine)
    if not inspector.has_table(table_name):
        return

    columns = {column['name']: column for column in inspector.get_columns(table_name)}
    target_column = columns.get(column_name)
    current_length = getattr(target_column.get('type'), 'length', None) if target_column else None

    if current_length is None or current_length >= required_length:
        return

    if db.engine.dialect.name == 'mysql':
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    f'ALTER TABLE `{table_name}` MODIFY COLUMN {column_name} '
                    f'VARCHAR({required_length})'
                )
            )


def ensure_text_column(table_name, column_name):
    """Convert a legacy MySQL column to TEXT when needed."""
    inspector = inspect(db.engine)
    if not inspector.has_table(table_name):
        return

    columns = {column['name']: column for column in inspector.get_columns(table_name)}
    target_column = columns.get(column_name)
    current_length = getattr(target_column.get('type'), 'length', None) if target_column else None

    if current_length is None:
        return

    if db.engine.dialect.name == 'mysql':
        with db.engine.begin() as connection:
            connection.execute(
                text(
                    f'ALTER TABLE `{table_name}` MODIFY COLUMN {column_name} TEXT NOT NULL'
                )
            )


def ensure_password_hash_column_capacity():
    """Guarantee the password hash column is large enough for modern hashes."""
    ensure_varchar_column_capacity('user', 'password_hash', 512)


def ensure_site_setting_value_column_capacity():
    """Guarantee the setting value column can store long text content."""
    ensure_text_column('site_setting', 'value')


def bootstrap_admin_from_env():
    """Create an initial admin account from environment variables if requested."""
    admin_username = os.environ.get('INIT_ADMIN_USERNAME')
    admin_password = os.environ.get('INIT_ADMIN_PASSWORD')

    if not admin_username and not admin_password:
        return

    if not admin_username or not admin_password:
        raise RuntimeError(
            'INIT_ADMIN_USERNAME and INIT_ADMIN_PASSWORD must be set together.'
        )

    if len(admin_password) < 12:
        raise RuntimeError(
            'INIT_ADMIN_PASSWORD must be at least 12 characters long.'
        )

    existing_user = User.query.filter_by(username=admin_username).first()
    if existing_user is None:
        admin = User(username=admin_username, is_admin=True)
        admin.set_password(admin_password)
        db.session.add(admin)
        return

    if not existing_user.is_admin:
        raise RuntimeError(
            f'User "{admin_username}" already exists and is not an admin account.'
        )


def build_background_setting_defaults(setting_key):
    """Build default settings for one background slot."""
    return {
        setting_key: DEFAULT_BACKGROUND_ASSET,
        f'{setting_key}_kind': DEFAULT_BACKGROUND_KIND,
        f'{setting_key}_mime': DEFAULT_BACKGROUND_MIME,
        f'{setting_key}_playlist_enabled': DEFAULT_BACKGROUND_PLAYLIST_ENABLED,
        f'{setting_key}_playlist_paths': DEFAULT_BACKGROUND_PLAYLIST_PATHS,
        f'{setting_key}_playlist_interval_seconds': DEFAULT_BACKGROUND_PLAYLIST_INTERVAL_SECONDS,
        f'{setting_key}_playlist_limit': DEFAULT_BACKGROUND_PLAYLIST_LIMIT,
    }


def build_default_settings():
    """Collect the complete initial setting set for a fresh database."""
    settings = {
        **CLOCK_SETTING_DEFAULTS,
        **HOMEPAGE_HERO_SETTING_DEFAULTS,
        **PAGE_TRANSITION_SETTING_DEFAULTS,
    }
    for setting_key in BACKGROUND_SETTING_KEYS:
        settings.update(build_background_setting_defaults(setting_key))
    return settings


def initialize_site_defaults(app):
    """Create tables, migrate simple legacy fields, and seed default settings."""
    # 启动时统一做一些“保底初始化”动作：
    # 创建表、修正字段长度、补默认设置、必要时创建管理员。
    ensure_upload_dirs()
    db.create_all()
    ensure_password_hash_column_capacity()
    ensure_site_setting_value_column_capacity()

    default_settings = build_default_settings()
    existing_settings = {
        setting.key: setting
        for setting in SiteSetting.query.filter(SiteSetting.key.in_(default_settings.keys())).all()
    }

    bootstrap_admin_from_env()

    for key, value in default_settings.items():
        setting = existing_settings.get(key)
        if setting is None:
            db.session.add(SiteSetting(key=key, value=value))
            continue

        if setting.value == LEGACY_DEFAULT_BACKGROUND_ASSET:
            setting.value = value

    for setting_key in BACKGROUND_SETTING_KEYS:
        setting = existing_settings.get(setting_key)
        if setting and setting.value.startswith(('uploads/', 'assets/')):
            if background_library_file_path(setting.value) is None:
                setting.value = DEFAULT_BACKGROUND_ASSET

    db.session.commit()


def validate_choice(value, valid_choices, flash_message):
    """Validate a select value against allowed choices and flash on failure."""
    if value in valid_choices:
        return True

    flash(flash_message)
    return False


def populate_admin_forms(
    clock_settings_form,
    page_transition_form,
    homepage_title_form,
    homepage_description_form,
):
    """Populate admin settings forms with the current stored values."""
    # GET 打开设置页时，把数据库当前值回填到表单中。
    current_clock_settings = get_clock_settings()
    homepage_hero_settings = get_homepage_hero_settings()
    page_transition_settings = get_page_transition_settings()
    clock_settings_form.style.data = current_clock_settings['style']
    clock_settings_form.hour_cycle.data = current_clock_settings['hour_cycle']
    clock_settings_form.show_date.data = '1' if current_clock_settings['show_date'] else '0'
    page_transition_form.axis.data = page_transition_settings['axis']
    homepage_title_form.title.data = homepage_hero_settings['title']
    homepage_title_form.title_font.data = homepage_hero_settings['title_font']
    homepage_title_form.title_color.data = homepage_hero_settings['title_color']
    homepage_description_form.description.data = homepage_hero_settings['description']
    homepage_description_form.description_font.data = homepage_hero_settings['description_font']
    homepage_description_form.description_color.data = homepage_hero_settings['description_color']


def update_homepage_text_settings(
    *,
    text_value,
    font_value,
    color_value,
    text_key,
    font_key,
    color_key,
    default_color,
):
    """Persist one text-based homepage setting block with font and color."""
    update_settings(
        {
            text_key: text_value.strip(),
            font_key: font_value,
            color_key: normalize_hex_color(color_value, default_color),
        }
    )
    db.session.commit()


def handle_background_playlist_form(background_playlist_form):
    """Validate and save rotating background playlist settings."""
    # 这个表单只接收图片，因为轮播目前设计成图片切换。
    if not background_playlist_form.validate():
        flash('文件夹轮播提交失败，请检查切换时间和图片数量设置。')
        return redirect(url_for('admin'))

    setting_key = background_playlist_form.target.data
    folder_files = background_playlist_form.folder.data or []
    saved_paths = save_background_playlist_files(folder_files)
    existing_paths = parse_json_setting(f'{setting_key}_playlist_paths', [])

    if not saved_paths and not existing_paths:
        flash('请至少选择一张图片上传，文件夹轮播仅支持图片。')
        return redirect(url_for('admin'))

    final_paths = saved_paths or existing_paths
    image_limit = min(background_playlist_form.image_limit.data, len(final_paths))
    update_settings(
        {
            f'{setting_key}_playlist_enabled': '1',
            f'{setting_key}_playlist_paths': json.dumps(final_paths),
            f'{setting_key}_playlist_interval_seconds': str(
                background_playlist_form.interval_seconds.data
            ),
            f'{setting_key}_playlist_limit': str(image_limit),
        }
    )
    db.session.commit()
    flash(f'文件夹轮播已更新，当前将循环播放 {image_limit} 张图片。')
    return redirect(url_for('admin'))


def handle_clock_settings_form(clock_settings_form):
    """Validate and save site clock display settings."""
    # 下拉框提交时，先验证值是否在允许范围内，再写入数据库。
    if not clock_settings_form.validate():
        flash('时间组件设置提交失败，请重新选择。')
        return redirect(url_for('admin'))

    selected_style = clock_settings_form.style.data
    if not validate_choice(selected_style, CLOCK_STYLE_CHOICES, '无效的时钟样式。'):
        return redirect(url_for('admin'))

    selected_hour_cycle = clock_settings_form.hour_cycle.data
    if not validate_choice(
        selected_hour_cycle,
        CLOCK_HOUR_CYCLE_CHOICES,
        '无效的时间显示制式。',
    ):
        return redirect(url_for('admin'))

    selected_show_date = clock_settings_form.show_date.data
    if not validate_choice(
        selected_show_date,
        CLOCK_SHOW_DATE_CHOICES,
        '无效的日期显示选项。',
    ):
        return redirect(url_for('admin'))

    update_settings(
        {
            'site_clock_style': selected_style,
            'site_clock_hour_cycle': selected_hour_cycle,
            'site_clock_show_date': selected_show_date,
        }
    )
    db.session.commit()
    flash('顶部时间组件设置已更新。')
    return redirect(url_for('admin'))


def handle_page_transition_form(page_transition_form):
    """Validate and save the public-page navigation axis."""
    if not page_transition_form.validate():
        flash('翻页方向设置提交失败，请重新选择。')
        return redirect(url_for('admin'))

    selected_axis = page_transition_form.axis.data
    if not validate_choice(
        selected_axis,
        PAGE_TRANSITION_AXIS_CHOICES,
        '无效的翻页方向。',
    ):
        return redirect(url_for('admin'))

    set_setting('page_transition_axis', selected_axis)
    db.session.commit()
    flash('前台翻页方向已更新。')
    return redirect(url_for('admin'))


def handle_homepage_title_form(homepage_title_form):
    """Validate and save the homepage title text settings."""
    if not homepage_title_form.validate():
        flash('欢迎语设置提交失败，请检查内容长度。')
        return redirect(url_for('admin'))

    selected_title_font = homepage_title_form.title_font.data
    if not validate_choice(selected_title_font, HOMEPAGE_FONT_FAMILIES, '欢迎语字体选项无效。'):
        return redirect(url_for('admin'))

    update_homepage_text_settings(
        text_value=homepage_title_form.title.data,
        font_value=selected_title_font,
        color_value=homepage_title_form.title_color.data,
        text_key='homepage_hero_title',
        font_key='homepage_hero_title_font',
        color_key='homepage_hero_title_color',
        default_color=DEFAULT_HOMEPAGE_TITLE_COLOR,
    )
    flash('欢迎语设置已更新。')
    return redirect(url_for('admin'))


def handle_homepage_description_form(homepage_description_form):
    """Validate and save the homepage description text settings."""
    if not homepage_description_form.validate():
        flash('个性描述设置提交失败，请检查内容长度和颜色格式。')
        return redirect(url_for('admin'))

    selected_description_font = homepage_description_form.description_font.data
    if not validate_choice(
        selected_description_font,
        HOMEPAGE_FONT_FAMILIES,
        '个性描述字体选项无效。',
    ):
        return redirect(url_for('admin'))

    update_homepage_text_settings(
        text_value=homepage_description_form.description.data,
        font_value=selected_description_font,
        color_value=homepage_description_form.description_color.data,
        text_key='homepage_intro_description',
        font_key='homepage_intro_description_font',
        color_key='homepage_intro_description_color',
        default_color=DEFAULT_HOMEPAGE_DESCRIPTION_COLOR,
    )
    flash('个性描述设置已更新。')
    return redirect(url_for('admin'))


def handle_background_upload_form(background_form):
    """Validate and save a single homepage or blog background asset."""
    # 单个背景既支持图片，也支持视频。
    if not background_form.validate_on_submit():
        flash('提交失败，请检查表单内容。')
        return redirect(url_for('admin'))

    storage = background_form.image.data
    setting_key = background_form.target.data
    selected_library_path = request.form.get('library_background_path', '').strip()
    has_uploaded_file = bool(storage and getattr(storage, 'filename', ''))

    if not has_uploaded_file and selected_library_path:
        try:
            apply_background_library_selection(setting_key, selected_library_path)
        except ValueError as error:
            flash(str(error))
            return redirect(url_for('admin'))

        db.session.commit()
        flash('背景图已更新。')
        return redirect(url_for('admin'))

    if not has_uploaded_file:
        flash('请选择本地背景文件，或从服务器已有背景中选择一张。')
        return redirect(url_for('admin'))

    background_kind, background_mime = detect_background_media(
        filename=storage.filename,
        content_type=storage.content_type,
    )
    if background_kind not in {'image', 'video'}:
        flash('请上传浏览器可以直接显示的图片、动图或视频文件作为背景。')
        return redirect(url_for('admin'))

    saved_name, _ = save_uploaded_file(storage, 'backgrounds')
    if not saved_name:
        flash('背景图上传失败。')
        return redirect(url_for('admin'))

    update_settings(
        {
            setting_key: f'uploads/backgrounds/{saved_name}',
            f'{setting_key}_kind': background_kind,
            f'{setting_key}_mime': background_mime,
        }
    )
    clear_background_playlist_settings(setting_key)
    db.session.commit()
    flash('背景图已更新。')
    return redirect(url_for('admin'))


def handle_background_library_form():
    """Apply an already uploaded server background asset."""
    setting_key = request.form.get('library_target', '').strip()
    if setting_key not in {'home_background', 'blog_background'}:
        flash('请选择有效的背景应用页面。')
        return redirect(url_for('admin'))

    selected_path = request.form.get('library_background_path', '').strip()
    try:
        apply_background_library_selection(setting_key, selected_path)
    except ValueError as error:
        flash(str(error))
        return redirect(url_for('admin'))

    db.session.commit()
    flash('已使用服务器中的背景文件。')
    return redirect(url_for('admin'))


def register_admin_settings_routes(app):
    """Register the admin settings center route."""

    @app.route('/admin', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def admin():
        """Render and process the centralized admin settings page."""
        # 后台这个页面有多个表单共用同一个 URL，
        # 所以这里要判断“这次 POST 到底是谁提交的”。
        background_form = BackgroundForm(prefix='background-single')
        background_playlist_form = BackgroundPlaylistForm(prefix='background-playlist')
        clock_settings_form = ClockSettingsForm(prefix='site-clock')
        page_transition_form = PageTransitionSettingsForm(prefix='page-transition')
        homepage_title_form = HomepageTitleForm(prefix='homepage-title')
        homepage_description_form = HomepageDescriptionForm(prefix='homepage-description')

        if request.method == 'GET':
            get_settings(build_default_settings())
            populate_admin_forms(
                clock_settings_form,
                page_transition_form,
                homepage_title_form,
                homepage_description_form,
            )

        if is_submitted(background_playlist_form):
            return handle_background_playlist_form(background_playlist_form)
        if is_submitted(clock_settings_form):
            return handle_clock_settings_form(clock_settings_form)
        if is_submitted(page_transition_form):
            return handle_page_transition_form(page_transition_form)
        if is_submitted(homepage_title_form):
            return handle_homepage_title_form(homepage_title_form)
        if is_submitted(homepage_description_form):
            return handle_homepage_description_form(homepage_description_form)
        if request.method == 'POST' and request.form.get('background_library_submit') is not None:
            return handle_background_library_form()
        if request.method == 'POST':
            return handle_background_upload_form(background_form)

        return render_with_background(
            'admin/admin.html',
            'blog_background',
            title='设置中心',
            background_form=background_form,
            background_playlist_form=background_playlist_form,
            clock_settings_form=clock_settings_form,
            page_transition_form=page_transition_form,
            homepage_title_form=homepage_title_form,
            homepage_description_form=homepage_description_form,
            messages=get_ordered_entries(Message, Message.created_at),
            home_background_asset=get_background_asset('home_background'),
            blog_background_asset=get_background_asset('blog_background'),
            background_library_assets=list_background_library_assets(),
        )
