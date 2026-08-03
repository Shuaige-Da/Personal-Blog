"""数据库模型定义文件。

可以把这个文件理解为“数据库表结构的 Python 写法”。
每个类通常就对应数据库里的一张表。
"""

from datetime import UTC, datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utc_now():
    """Return a timezone-aware UTC timestamp."""
    return datetime.now(UTC)


class User(UserMixin, db.Model):
    """Application user model with optional administrator privileges."""

    # 主键：每个用户唯一的编号。
    id = db.Column(db.Integer, primary_key=True)
    # 登录用户名，要求唯一。
    username = db.Column(db.String(64), index=True, unique=True)
    # 存密码哈希，不直接存明文密码。
    password_hash = db.Column(db.String(512))
    # 是否为管理员。True 才能进入后台。
    is_admin = db.Column(db.Boolean, default=False)

    def set_password(self, password):
        """Hash and store the user's password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Verify a plaintext password against the stored hash."""
        return check_password_hash(self.password_hash, password)


class FileRecord(db.Model):
    """Uploaded file metadata for images, videos, and music."""

    id = db.Column(db.Integer, primary_key=True)
    # 服务器里实际保存后的文件名。
    filename = db.Column(db.String(128))
    # 用户上传时原始文件名，方便后台展示。
    original_name = db.Column(db.String(128))
    # 文件类型：image / video / music。
    file_type = db.Column(db.String(20))
    # 上传时间。
    upload_date = db.Column(db.DateTime(timezone=True), default=utc_now)
    # 关联上传者。
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<FileRecord {self.filename}>'


class AudioPlaybackVariant(db.Model):
    """Lossless browser playback copy for an uploaded audio original."""

    id = db.Column(db.Integer, primary_key=True)
    file_record_id = db.Column(
        db.Integer,
        db.ForeignKey('file_record.id'),
        nullable=False,
        unique=True,
        index=True,
    )
    filename = db.Column(db.String(180), nullable=False)
    source_mime_type = db.Column(db.String(120), nullable=False, default='application/octet-stream')
    mime_type = db.Column(db.String(120), nullable=False, default='audio/wav')
    codec = db.Column(db.String(40), nullable=False)
    sample_rate = db.Column(db.Integer, nullable=True)
    channels = db.Column(db.Integer, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)

    file_record = db.relationship(
        'FileRecord',
        backref=db.backref(
            'audio_variant',
            uselist=False,
            cascade='all, delete-orphan',
        ),
    )


class DiaryEntry(db.Model):
    """Diary entry created by the administrator."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<DiaryEntry {self.title}>'


class SiteSetting(db.Model):
    """Key-value storage for homepage and system settings."""

    # 这里不是一堆固定列，而是 key-value 结构。
    # 例如：key='homepage_hero_title'，value='欢迎来到...'
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(64), unique=True, nullable=False)
    value = db.Column(db.Text, nullable=False)

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<SiteSetting {self.key}>'


class Article(db.Model):
    """Visitor-submitted article waiting for moderation or display."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    content = db.Column(db.Text, nullable=False)
    author_name = db.Column(db.String(80), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<Article {self.title}>'


class Link(db.Model):
    """Visitor-submitted link recommendation."""

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(160), nullable=False)
    url = db.Column(db.String(255), nullable=False)
    description = db.Column(db.Text, nullable=False)
    author_name = db.Column(db.String(80), nullable=False)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<Link {self.title}>'


class Message(db.Model):
    """Visitor guestbook message shown on the public message board."""

    id = db.Column(db.Integer, primary_key=True)
    nickname = db.Column(db.String(80), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    is_approved = db.Column(db.Boolean, default=False, nullable=False)

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<Message {self.nickname}>'


class BlogPost(db.Model):
    """管理员发布的长文博客文章，支持 Markdown 编写和标签分类。"""

    id = db.Column(db.Integer, primary_key=True)
    # 文章标题。
    title = db.Column(db.String(200), nullable=False)
    # URL 别名，用于生成友好的永久链接。
    slug = db.Column(db.String(200), unique=True, nullable=False)
    # Markdown 原文，保存后可以用 Markdown 库渲染成 HTML。
    content_markdown = db.Column(db.Text, nullable=False)
    # 渲染后的 HTML，保存时生成，避免每次访问都重新渲染。
    content_html = db.Column(db.Text, nullable=False)
    # 摘要/简介，显示在文章列表中。
    summary = db.Column(db.String(500), nullable=True)
    # 封面图路径（可选）。
    cover_image = db.Column(db.String(255), nullable=True)
    # 标签，逗号分隔，例如 "Flask,Python,博客"。
    tags = db.Column(db.String(500), nullable=True)
    # 是否已发布。True 表示已公开，False 表示草稿。
    is_published = db.Column(db.Boolean, default=True, nullable=False)
    # 创建时间和更新时间。
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(db.DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    # 关联作者。
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<BlogPost {self.title}>'


class HermesConversation(db.Model):
    """A website chat thread backed by a Hermes server-side conversation."""

    id = db.Column(db.Integer, primary_key=True)
    conversation_key = db.Column(db.String(160), unique=True, nullable=False, index=True)
    title = db.Column(db.String(160), nullable=False, default='New chat')
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    user = db.relationship('User', backref='hermes_conversations')
    messages = db.relationship(
        'HermesMessage',
        backref='conversation',
        cascade='all, delete-orphan',
        lazy='select',
        order_by='HermesMessage.created_at',
    )

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<HermesConversation {self.title}>'


class HermesMessage(db.Model):
    """A display copy of one message in a website Hermes conversation."""

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey('hermes_conversation.id'),
        nullable=False,
        index=True,
    )
    role = db.Column(db.String(20), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, index=True)
    attachments = db.relationship(
        'HermesAttachment',
        backref='message',
        cascade='all, delete-orphan',
        lazy='select',
        order_by='HermesAttachment.created_at',
    )

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<HermesMessage {self.role}>'


class HermesAttachment(db.Model):
    """Private file attached to one administrator chat message."""

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey('hermes_conversation.id'),
        nullable=False,
        index=True,
    )
    message_id = db.Column(
        db.Integer,
        db.ForeignKey('hermes_message.id'),
        nullable=False,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    stored_name = db.Column(db.String(180), nullable=False, unique=True)
    original_name = db.Column(db.String(255), nullable=False)
    mime_type = db.Column(db.String(120), nullable=False)
    size_bytes = db.Column(db.Integer, nullable=False)
    kind = db.Column(db.String(20), nullable=False)
    extracted_text_name = db.Column(db.String(180), nullable=True)
    truncated = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now, index=True)

    conversation = db.relationship('HermesConversation', foreign_keys=[conversation_id])

    def __repr__(self):
        return f'<HermesAttachment {self.original_name}>'


class HermesChatJob(db.Model):
    """Background task state for a website Hermes chat request."""

    id = db.Column(db.Integer, primary_key=True)
    job_key = db.Column(db.String(64), unique=True, nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='pending', index=True)
    error = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), default=utc_now)
    updated_at = db.Column(
        db.DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        index=True,
    )
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False, index=True)
    conversation_id = db.Column(
        db.Integer,
        db.ForeignKey('hermes_conversation.id'),
        nullable=False,
        index=True,
    )
    user_message_id = db.Column(
        db.Integer,
        db.ForeignKey('hermes_message.id'),
        nullable=False,
        index=True,
    )
    assistant_message_id = db.Column(
        db.Integer,
        db.ForeignKey('hermes_message.id'),
        nullable=True,
        index=True,
    )

    conversation = db.relationship('HermesConversation', foreign_keys=[conversation_id])
    user_message = db.relationship('HermesMessage', foreign_keys=[user_message_id])
    assistant_message = db.relationship(
        'HermesMessage',
        foreign_keys=[assistant_message_id],
    )

    def __repr__(self):
        """Return a readable debug representation."""
        return f'<HermesChatJob {self.status}>'
