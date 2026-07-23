"""管理员审核模块。

这个文件只做“审核和清理”：
1. 审核游客投稿的文章
2. 审核游客投稿的网址
3. 删除文章、网址、留言
"""

from flask import flash
from flask_login import login_required

from backend.admin.auth import admin_required, redirect_with_fallback
from backend.admin.content import delete_entry
from backend.core.models import Article, Link, Message, db


def approve_entry(model, entry_id, success_message, fallback_endpoint='admin'):
    """Approve a submitted entry and redirect back to the review page."""
    # 审核本质上就是把 is_approved 改成 True。
    entry = db.get_or_404(model, entry_id)
    entry.is_approved = True
    db.session.commit()
    flash(success_message)
    return redirect_with_fallback(fallback_endpoint)


def register_admin_review_routes(app):
    """Register review and moderation routes for user submissions."""

    @app.route('/approve-article/<int:article_id>', methods=['POST'])
    @login_required
    @admin_required
    def approve_article(article_id):
        """Approve a pending article submission."""
        return approve_entry(Article, article_id, '文章已审核通过。')

    @app.route('/approve-link/<int:link_id>', methods=['POST'])
    @login_required
    @admin_required
    def approve_link(link_id):
        """Approve a pending link submission."""
        return approve_entry(Link, link_id, '网址已审核通过。')

    @app.route('/approve-message/<int:message_id>', methods=['POST'])
    @login_required
    @admin_required
    def approve_message(message_id):
        """Approve a pending guestbook message."""
        return approve_entry(Message, message_id, '留言已审核通过。')

    @app.route('/delete-article/<int:article_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_article(article_id):
        """Delete an article submission."""
        return delete_entry(Article, article_id, '文章已删除。')

    @app.route('/delete-link/<int:link_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_link(link_id):
        """Delete a link submission."""
        return delete_entry(Link, link_id, '网址已删除。')

    @app.route('/delete-message/<int:message_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_message(message_id):
        """Delete a guestbook message."""
        return delete_entry(Message, message_id, '留言已删除。')
