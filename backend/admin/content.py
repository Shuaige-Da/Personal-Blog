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
from sqlalchemy.orm import selectinload

from backend.admin.auth import admin_required, create_record, redirect_with_fallback
from backend.admin.audio import (
    AudioProcessingError,
    create_wav_variant,
    remove_audio_files,
    save_audio_original,
)
from backend.admin.settings import (
    get_ordered_entries,
    render_with_background,
    save_uploaded_file,
)
from backend.core.constants import MEDIA_FOLDERS, MEDIA_LIBRARY
from backend.core.forms import DiaryForm, MediaUploadForm
from backend.core.models import BlogPost, DiaryEntry, FileRecord, db

DASHBOARD_PREVIEW_LIMITS = {
    'blog_posts': 3,
    'diaries': 4,
    'image': 6,
    'music': 4,
    'video': 4,
}


def annotate_audio_availability(items):
    """Attach filesystem availability flags used by the admin audio player."""
    folder = os.path.join(current_app.config['UPLOAD_FOLDER'], 'music')
    for item in items:
        item.audio_source_available = os.path.isfile(
            os.path.join(folder, item.filename)
        )
        item.audio_fallback_available = bool(
            item.audio_variant
            and os.path.isfile(os.path.join(folder, item.audio_variant.filename))
        )
    return items


def get_recent_entries_with_count(model, sort_column, limit, **filters):
    """Return a bounded recent slice and its full count in one query."""
    statement = db.select(
        model,
        db.func.count(model.id).over().label('total_count'),
    )
    for attribute, value in filters.items():
        statement = statement.where(getattr(model, attribute) == value)
    statement = statement.order_by(sort_column.desc()).limit(limit)

    if model is FileRecord and filters.get('file_type') == 'music':
        statement = statement.options(selectinload(FileRecord.audio_variant))

    rows = db.session.execute(statement).all()
    if not rows:
        return [], 0
    items = [row[0] for row in rows]
    if model is FileRecord and filters.get('file_type') == 'music':
        annotate_audio_availability(items)
    return items, int(rows[0].total_count)


def get_media_entries(file_type):
    """Load one media library, eager-loading playback data only for music."""
    query = FileRecord.query.filter_by(file_type=file_type)
    if file_type == 'music':
        query = query.options(selectinload(FileRecord.audio_variant))
    items = query.order_by(FileRecord.upload_date.desc()).all()
    if file_type == 'music':
        annotate_audio_availability(items)
    return items


def create_media_record(storage, file_type, user_id):
    """Save an uploaded media file and create its database record."""
    # 先把物理文件保存到 static/uploads 对应目录。
    if file_type == 'music':
        created_paths = []
        try:
            saved_name, original_name, stream = save_audio_original(storage)
            created_paths.append(
                os.path.join(
                    current_app.config['UPLOAD_FOLDER'],
                    'music',
                    saved_name,
                )
            )
            record = FileRecord(
                filename=saved_name,
                original_name=original_name,
                file_type=file_type,
                user_id=user_id,
            )
            db.session.add(record)
            db.session.flush()
            variant = create_wav_variant(record, stream)
            created_paths.append(
                os.path.join(
                    current_app.config['UPLOAD_FOLDER'],
                    'music',
                    variant.filename,
                )
            )
            db.session.add(variant)
            db.session.commit()
            return True
        except Exception as error:
            db.session.rollback()
            for path in created_paths:
                if os.path.isfile(path):
                    os.remove(path)
            if isinstance(error, AudioProcessingError):
                flash(str(error))
            else:
                current_app.logger.exception('Music upload transaction failed')
                flash('音频保存失败，原件和播放副本均已回滚。')
            return False

    folder = MEDIA_FOLDERS[file_type]
    saved_name, original_name = save_uploaded_file(storage, folder)
    if not saved_name:
        if original_name is None:
            flash('文件名无效，请重新选择文件。')
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

        return redirect(url_for(config['endpoint']))

    return render_with_background(
        'admin/manage_media.html',
        'blog_background',
        title=config['title'],
        form=form,
        items=get_media_entries(config['file_type']),
        media_config=config,
    )


def register_admin_feature_routes(app):
    """Register admin content management routes."""

    @app.route('/blog')
    @login_required
    @admin_required
    def blog():
        """Render the main admin blog dashboard."""
        blog_posts, blog_count = get_recent_entries_with_count(
            BlogPost,
            BlogPost.created_at,
            DASHBOARD_PREVIEW_LIMITS['blog_posts'],
        )
        diaries, diary_count = get_recent_entries_with_count(
            DiaryEntry,
            DiaryEntry.created_at,
            DASHBOARD_PREVIEW_LIMITS['diaries'],
        )
        images, image_count = get_recent_entries_with_count(
            FileRecord,
            FileRecord.upload_date,
            DASHBOARD_PREVIEW_LIMITS['image'],
            file_type='image',
        )
        videos, video_count = get_recent_entries_with_count(
            FileRecord,
            FileRecord.upload_date,
            DASHBOARD_PREVIEW_LIMITS['video'],
            file_type='video',
        )
        music, music_count = get_recent_entries_with_count(
            FileRecord,
            FileRecord.upload_date,
            DASHBOARD_PREVIEW_LIMITS['music'],
            file_type='music',
        )
        return render_with_background(
            'admin/blog.html',
            'blog_background',
            title='RainWave 的个人博客',
            images=images,
            videos=videos,
            music=music,
            diaries=diaries,
            blog_posts=blog_posts,
            blog_count=blog_count,
            diary_count=diary_count,
            music_count=music_count,
            image_count=image_count,
            video_count=video_count,
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
        if record.file_type == 'music':
            remove_audio_files(record)
        elif os.path.exists(file_path):
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
