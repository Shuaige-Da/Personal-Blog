# 这个文件专门放“不会经常变化，但会被多个文件共用”的常量。
# 这样可以避免把同样的配置写在很多地方。

# 上传后的媒体文件会按类型分别放到这些目录里。
MEDIA_FOLDERS = {
    'image': 'images',
    'video': 'videos',
    'music': 'music',
}

# 默认背景相关配置。
DEFAULT_BACKGROUND_ASSET = 'assets/backgrounds/rainwave-hero.jpg'
LEGACY_DEFAULT_BACKGROUND_ASSET = 'uploads/backgrounds/default-night.svg'
DEFAULT_BACKGROUND_KIND = 'image'
DEFAULT_BACKGROUND_MIME = 'image/jpeg'
DEFAULT_BACKGROUND_PLAYLIST_ENABLED = '0'
DEFAULT_BACKGROUND_PLAYLIST_PATHS = '[]'
DEFAULT_BACKGROUND_PLAYLIST_INTERVAL_SECONDS = '15'
DEFAULT_BACKGROUND_PLAYLIST_LIMIT = '10'

# 顶部时钟的默认配置。
DEFAULT_CLOCK_STYLE = 'digital'
CLOCK_STYLE_CHOICES = {'digital', 'text', 'analog'}
DEFAULT_CLOCK_HOUR_CYCLE = '24'
DEFAULT_CLOCK_SHOW_DATE = '1'
CLOCK_HOUR_CYCLE_CHOICES = {'12', '24'}
CLOCK_SHOW_DATE_CHOICES = {'0', '1'}

# 上传文件名的最大基础长度，避免文件名过长。
MAX_UPLOAD_BASENAME_LENGTH = 90

# 首页主视觉（标题和描述）的默认内容。
DEFAULT_HOMEPAGE_HERO_TITLE = '在夜色与回忆之间，记录生活的微光'
DEFAULT_HOMEPAGE_INTRO_DESCRIPTION = (
    '在夜色、音乐和生活碎片之间，慢慢记录日常，整理回忆，也把文章、'
    '网址推荐和留言汇成一个更完整的个人空间。'
)
DEFAULT_HOMEPAGE_TITLE_FONT = 'microsoft_yahei'
DEFAULT_HOMEPAGE_TITLE_COLOR = '#F8FBFF'
DEFAULT_HOMEPAGE_DESCRIPTION_FONT = 'microsoft_yahei'
DEFAULT_HOMEPAGE_DESCRIPTION_COLOR = '#F2F4FB'

# 首页可选字体。左边是保存到数据库的 key，右边是实际 CSS 字体族。
HOMEPAGE_FONT_FAMILIES = {
    'microsoft_yahei': '"Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif',
    'segoe_ui': '"Segoe UI", "Microsoft YaHei", sans-serif',
    'pingfang_sc': '"PingFang SC", "Microsoft YaHei", sans-serif',
    'simhei': '"SimHei", "Microsoft YaHei", sans-serif',
    'simsun': '"SimSun", "Songti SC", serif',
    'kaiti': '"KaiTi", "STKaiti", serif',
    'fangsong': '"FangSong", "STFangsong", serif',
    'georgia': 'Georgia, "Times New Roman", serif',
    'verdana': 'Verdana, "Segoe UI", sans-serif',
}

# 通过扩展名推断背景媒体类型时会用到这张映射表。
BACKGROUND_EXTENSION_HINTS = {
    'apng': ('image', 'image/apng'),
    'avif': ('image', 'image/avif'),
    'bmp': ('image', 'image/bmp'),
    'gif': ('image', 'image/gif'),
    'heic': ('image', 'image/heic'),
    'heif': ('image', 'image/heif'),
    'ico': ('image', 'image/x-icon'),
    'jfif': ('image', 'image/jpeg'),
    'jpe': ('image', 'image/jpeg'),
    'jpeg': ('image', 'image/jpeg'),
    'jpg': ('image', 'image/jpeg'),
    'jxl': ('image', 'image/jxl'),
    'png': ('image', 'image/png'),
    'svg': ('image', 'image/svg+xml'),
    'svgz': ('image', 'image/svg+xml'),
    'tif': ('image', 'image/tiff'),
    'tiff': ('image', 'image/tiff'),
    'webp': ('image', 'image/webp'),
    '3gp': ('video', 'video/3gpp'),
    'avi': ('video', 'video/x-msvideo'),
    'm2ts': ('video', 'video/mp2t'),
    'm4v': ('video', 'video/mp4'),
    'mkv': ('video', 'video/x-matroska'),
    'mov': ('video', 'video/quicktime'),
    'mp4': ('video', 'video/mp4'),
    'mpeg': ('video', 'video/mpeg'),
    'mpg': ('video', 'video/mpeg'),
    'mts': ('video', 'video/mp2t'),
    'ogv': ('video', 'video/ogg'),
    'ts': ('video', 'video/mp2t'),
    'webm': ('video', 'video/webm'),
}

# 媒体管理页的展示文案和配置。
# 不同媒体页共用一个模板，所以这里提前把每种媒体的标题、图标、按钮文案准备好。
MEDIA_LIBRARY = {
    'music': {
        'file_type': 'music',
        'folder': 'music',
        'title': '音乐管理',
        'headline': '管理你的音乐收藏',
        'description': '在这里上传、试听和整理博客里的音乐内容。',
        'icon': 'bi-headphones',
        'empty_text': '还没有上传音乐，先添加第一首吧。',
        'upload_button': '上传音乐',
        'endpoint': 'manage_music',
    },
    'images': {
        'file_type': 'image',
        'folder': 'images',
        'title': '图片管理',
        'headline': '管理你的图片画廊',
        'description': '这里可以集中维护博客图片，并预览当前画廊效果。',
        'icon': 'bi-images',
        'empty_text': '还没有上传图片，先添加第一张吧。',
        'upload_button': '上传图片',
        'endpoint': 'manage_images',
    },
    'videos': {
        'file_type': 'video',
        'folder': 'videos',
        'title': '视频管理',
        'headline': '管理你的视频内容',
        'description': '这里可以上传和清理视频，让博客中的视频区保持整洁。',
        'icon': 'bi-film',
        'empty_text': '还没有上传视频，先添加第一段吧。',
        'upload_button': '上传视频',
        'endpoint': 'manage_videos',
    },
}

# 博客文章发布状态选项。
BLOG_POST_STATUS_CHOICES = [
    ('published', '已发布'),
    ('draft', '草稿'),
]

# Hermes Agent 写作辅助动作。
HERMES_WRITING_ACTIONS = {'polish', 'expand', 'summarize', 'translate'}
