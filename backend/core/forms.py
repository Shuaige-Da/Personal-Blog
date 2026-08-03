"""WTForms 表单定义文件。

前端页面里的输入框、下拉框、提交按钮，大多都在这里定义。
好处是：
1. 前后端字段统一。
2. 校验规则集中管理。
3. 模板里可以直接渲染表单对象。
"""

from flask_wtf import FlaskForm
from flask_wtf.file import FileField, MultipleFileField
from wtforms import (
    IntegerField,
    PasswordField,
    SelectField,
    StringField,
    SubmitField,
    TextAreaField,
)
from wtforms.validators import DataRequired, Length, NumberRange, Optional

from backend.core.constants import BLOG_POST_STATUS_CHOICES


HOMEPAGE_FONT_CHOICES = [
    ('microsoft_yahei', 'Microsoft YaHei'),
    ('segoe_ui', 'Segoe UI'),
    ('pingfang_sc', 'PingFang SC'),
    ('simhei', 'SimHei'),
    ('simsun', 'SimSun'),
    ('kaiti', 'KaiTi'),
    ('fangsong', 'FangSong'),
    ('georgia', 'Georgia'),
    ('verdana', 'Verdana'),
]

BACKGROUND_TARGET_CHOICES = [
    ('home_background', '首页背景'),
    ('blog_background', '博客背景'),
]

CLOCK_STYLE_FIELD_CHOICES = [
    ('digital', '数字样式'),
    ('text', '文字样式'),
    ('analog', '钟表样式'),
]

CLOCK_HOUR_CYCLE_FIELD_CHOICES = [
    ('24', '24 小时制'),
    ('12', '12 小时制'),
]

CLOCK_SHOW_DATE_FIELD_CHOICES = [
    ('1', '显示日期'),
    ('0', '隐藏日期'),
]

PAGE_TRANSITION_AXIS_FIELD_CHOICES = [
    ('vertical', '纵向翻页（上下）'),
    ('horizontal', '横向翻页（左右）'),
]


class LoginForm(FlaskForm):
    """管理员登录表单。"""

    username = StringField('用户名', validators=[DataRequired()])
    password = PasswordField('密码', validators=[DataRequired()])
    totp_code = StringField('动态验证码', validators=[Optional(), Length(min=6, max=12)])
    submit = SubmitField('登录')


class MediaUploadForm(FlaskForm):
    """图片、视频、音乐共用的上传表单。"""

    file = FileField('选择文件', validators=[DataRequired()])
    submit = SubmitField('上传')


class DiaryForm(FlaskForm):
    """管理员发布日记时使用的表单。"""

    title = StringField('日记标题', validators=[DataRequired(), Length(max=120)])
    content = TextAreaField('日记内容', validators=[DataRequired()])
    submit = SubmitField('发布日记')


class BackgroundForm(FlaskForm):
    """上传单个背景图或背景视频时使用的表单。"""

    target = SelectField(
        '应用页面',
        choices=BACKGROUND_TARGET_CHOICES,
        validators=[DataRequired()],
    )
    image = FileField('背景媒体文件')
    submit = SubmitField('更新单个背景')


class BackgroundPlaylistForm(FlaskForm):
    """上传一组背景图片并开启轮播时使用的表单。"""

    target = SelectField(
        '轮播应用页面',
        choices=BACKGROUND_TARGET_CHOICES,
        validators=[DataRequired()],
    )
    folder = MultipleFileField('背景图片文件夹')
    interval_seconds = IntegerField(
        '切换间隔（秒）',
        validators=[DataRequired(), NumberRange(min=1, max=3600)],
        default=15,
    )
    image_limit = IntegerField(
        '参与轮播的图片数量',
        validators=[DataRequired(), NumberRange(min=1, max=500)],
        default=10,
    )
    submit = SubmitField('更新文件夹轮播')


class ClockSettingsForm(FlaskForm):
    """首页顶部时间组件设置表单。"""

    style = SelectField(
        '时钟样式',
        choices=CLOCK_STYLE_FIELD_CHOICES,
        validators=[DataRequired()],
    )
    hour_cycle = SelectField(
        '显示制式',
        choices=CLOCK_HOUR_CYCLE_FIELD_CHOICES,
        validators=[DataRequired()],
    )
    show_date = SelectField(
        '日期显示',
        choices=CLOCK_SHOW_DATE_FIELD_CHOICES,
        validators=[DataRequired()],
    )
    submit = SubmitField('更新时间样式')


class PageTransitionSettingsForm(FlaskForm):
    """前台沉浸式页面翻页方向设置表单。"""

    axis = SelectField(
        '翻页方向',
        choices=PAGE_TRANSITION_AXIS_FIELD_CHOICES,
        validators=[DataRequired()],
    )
    submit = SubmitField('更新翻页方向')


class HomepageTitleForm(FlaskForm):
    """首页欢迎标题设置表单。"""

    title = StringField('首页欢迎语', validators=[DataRequired(), Length(max=120)])
    title_font = SelectField(
        '欢迎语字体',
        choices=HOMEPAGE_FONT_CHOICES,
        validators=[DataRequired()],
    )
    title_color = StringField(
        '欢迎语颜色',
        validators=[DataRequired(), Length(max=20)],
        render_kw={'type': 'color'},
    )
    submit = SubmitField('保存欢迎语设置')


class HomepageDescriptionForm(FlaskForm):
    """首页个性描述设置表单。"""

    description = TextAreaField('首页个性描述', validators=[DataRequired(), Length(max=800)])
    description_font = SelectField(
        '个性描述字体',
        choices=HOMEPAGE_FONT_CHOICES,
        validators=[DataRequired()],
    )
    description_color = StringField(
        '个性描述颜色',
        validators=[DataRequired(), Length(max=20)],
        render_kw={'type': 'color'},
    )
    submit = SubmitField('保存个性描述设置')



class MessageForm(FlaskForm):
    """游客留言表单。"""

    nickname = StringField('昵称', validators=[DataRequired(), Length(max=80)])
    content = TextAreaField('留言内容', validators=[DataRequired(), Length(max=1000)])
    website = StringField('网站', validators=[Optional(), Length(max=0)])
    submit = SubmitField('发布留言')


class BlogPostForm(FlaskForm):
    """管理员发布博客文章的表单，支持 Markdown 编写和标签分类。"""

    title = StringField('文章标题', validators=[DataRequired(), Length(max=200)])
    slug = StringField('URL 别名', validators=[Optional(), Length(max=200)])
    content_markdown = TextAreaField(
        '文章内容 (Markdown)',
        validators=[DataRequired()],
        render_kw={'rows': '20', 'spellcheck': 'false'},
    )
    summary = TextAreaField(
        '文章摘要',
        validators=[Optional(), Length(max=500)],
        render_kw={'rows': '3'},
    )
    cover_image = FileField('封面图片 (可选)')
    tags = StringField(
        '标签 (逗号分隔)',
        validators=[Optional(), Length(max=500)],
    )
    is_published = SelectField(
        '发布状态',
        choices=BLOG_POST_STATUS_CHOICES,
        default='published',
    )
    submit = SubmitField('保存文章')
