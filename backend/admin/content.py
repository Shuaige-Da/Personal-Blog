"""管理员内容管理模块。

这个文件负责登录后才能操作的“内容型功能”：
1. 个人博客总览页
2. 日记管理
3. 图片 / 视频 / 音乐管理
4. 删除文件和删除日记
"""

import os

from flask import current_app, flash, redirect, url_for
from flask_login import current_user, login_required

from backend.admin.auth import admin_required, create_record, redirect_with_fallback
from backend.admin.settings import (
    get_ordered_entries,
    render_with_background,
    save_uploaded_file,
)
from backend.core.constants import MEDIA_FOLDERS, MEDIA_LIBRARY
from backend.core.forms import DiaryForm, MediaUploadForm
from backend.core.models import BlogPost, DiaryEntry, FileRecord, db


def create_media_record(storage, file_type, user_id):
    """Save an uploaded media file and create its database record."""
    # 先把物理文件保存到 static/uploads 对应目录。
    folder = MEDIA_FOLDERS[file_type]
    saved_name, original_name = save_uploaded_file(storage, folder)
    if not saved_name:
        return False

    create_record(
        FileRecord,
        filename=saved_name,
        original_name=original_name,
        file_type=file_type,
        user_id=user_id,
    )
    return True


def delete_entry(model, entry_id, success_message, fallback_endpoint='admin'):
    """Delete a generic content entry and redirect back safely."""
    entry = db.get_or_404(model, entry_id)
    db.session.delete(entry)
    db.session.commit()
    flash(success_message)
    return redirect_with_fallback(fallback_endpoint)


def render_media_manager(library_key):
    """Render a reusable admin page for one media library type."""
    # 这里的 config 来自 constants.py，
    # 它决定当前页面是“音乐管理”还是“图片管理”还是“视频管理”。
    config = MEDIA_LIBRARY[library_key]
    form = MediaUploadForm(prefix=config['file_type'])

    if form.validate_on_submit():
        if create_media_record(form.file.data, config['file_type'], current_user.id):
            flash(f"{config['upload_button']}成功。")
            return redirect(url_for(config['endpoint']))

        flash('上传失败，请检查文件名后重试。')
        return redirect(url_for(config['endpoint']))

    return render_with_background(
        'admin/manage_media.html',
        'blog_background',
        title=config['title'],
        form=form,
        items=get_ordered_entries(
            FileRecord,
            FileRecord.upload_date,
            file_type=config['file_type'],
        ),
        media_config=config,
    )


def register_admin_feature_routes(app):
    """Register admin content management routes."""

    @app.route('/blog')
    @login_required
    @admin_required
    def blog():
        """Render the main admin blog dashboard."""
        # 这里把各类内容都查出来，一次性传给模板展示。
        blog_posts = BlogPost.query.order_by(BlogPost.created_at.desc()).limit(5).all()
        return render_with_background(
            'admin/blog.html',
            'blog_background',
            title='RainWave 的个人博客',
            images=get_ordered_entries(FileRecord, FileRecord.upload_date, file_type='image'),
            videos=get_ordered_entries(FileRecord, FileRecord.upload_date, file_type='video'),
            music=get_ordered_entries(FileRecord, FileRecord.upload_date, file_type='music'),
            diaries=get_ordered_entries(DiaryEntry, DiaryEntry.created_at),
            blog_posts=blog_posts,
        )

    @app.route('/manage/diaries', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manage_diaries():
        """Create and manage diary entries."""
        form = DiaryForm(prefix='manage-diary')
        if form.validate_on_submit():
            create_record(
                DiaryEntry,
                title=form.title.data,
                content=form.content.data,
                user_id=current_user.id,
            )
            flash('日记已发布。')
            return redirect(url_for('manage_diaries'))

        return render_with_background(
            'admin/manage_diaries.html',
            'blog_background',
            title='日记管理',
            form=form,
            diaries=get_ordered_entries(DiaryEntry, DiaryEntry.created_at),
        )

    @app.route('/manage/music', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manage_music():
        """Manage uploaded music files."""
        return render_media_manager('music')

    @app.route('/manage/images', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manage_images():
        """Manage uploaded image files."""
        return render_media_manager('images')

    @app.route('/manage/videos', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def manage_videos():
        """Manage uploaded video files."""
        return render_media_manager('videos')

    @app.route('/delete/<int:file_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_file(file_id):
        """Delete an uploaded media file and its database record."""
        record = db.get_or_404(FileRecord, file_id)
        folder = MEDIA_FOLDERS.get(record.file_type)
        if folder is None:
            flash('文件类型不支持删除。')
            return redirect_with_fallback('blog')

        file_path = os.path.join(current_app.config['UPLOAD_FOLDER'], folder, record.filename)
        if os.path.exists(file_path):
            os.remove(file_path)

        db.session.delete(record)
        db.session.commit()
        flash('文件已删除。')
        return redirect_with_fallback('blog')

    @app.route('/delete-diary/<int:entry_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_diary(entry_id):
        """Delete a diary entry."""
        return delete_entry(DiaryEntry, entry_id, '日记已删除。', 'manage_diaries')
