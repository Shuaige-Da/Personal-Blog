# -*- coding: utf-8 -*-
"""Blog post management module for administrator.

This module handles:
1. Blog post list, create, edit, delete
2. Markdown to HTML rendering
3. Public single post view
"""

import os
import re
import uuid
from functools import lru_cache

import html2text
import markdown
import nh3
from bs4 import BeautifulSoup
from flask import flash, jsonify, redirect, request, url_for
from flask_login import current_user, login_required

from backend.admin.auth import admin_required, redirect_with_fallback
from backend.admin.settings import render_with_background, save_uploaded_file
from backend.core.forms import BlogPostForm
from backend.core.models import BlogPost, db

MARKDOWN_EXTENSIONS = ('fenced_code', 'tables', 'toc', 'nl2br', 'codehilite')
MARKDOWN_EXTENSION_CONFIGS = {
    'codehilite': {
        'css_class': 'highlight',
        'linenums': False,
    },
    'toc': {
        'permalink': False,
    },
}
MARKDOWN_ALLOWED_TAGS = {
    'a', 'blockquote', 'br', 'code', 'del', 'em', 'h1', 'h2', 'h3',
    'h4', 'h5', 'h6', 'hr', 'img', 'li', 'ol', 'p', 'pre', 'span',
    'strong', 'table', 'tbody', 'td', 'th', 'thead', 'tr', 'ul',
}
MARKDOWN_ALLOWED_ATTRIBUTES = {
    'a': {'href', 'title'},
    'code': {'class'},
    'img': {'src', 'alt', 'title', 'width', 'height', 'loading'},
    'span': {'class'},
    'td': {'align'},
    'th': {'align'},
}
MAX_CACHED_MARKDOWN_CHARS = 20_000


def _render_markdown(markdown_text):
    rendered = markdown.markdown(
        markdown_text,
        extensions=MARKDOWN_EXTENSIONS,
        extension_configs=MARKDOWN_EXTENSION_CONFIGS,
    )
    return nh3.clean(
        rendered,
        tags=MARKDOWN_ALLOWED_TAGS,
        attributes=MARKDOWN_ALLOWED_ATTRIBUTES,
        url_schemes={'http', 'https', 'mailto'},
        link_rel='noopener noreferrer',
    )


@lru_cache(maxsize=64)
def _render_cached_markdown(markdown_text):
    """Cache repeated chat/history renders without retaining large documents."""
    return _render_markdown(markdown_text)


def render_markdown_to_html(markdown_text):
    """Render Markdown text to HTML.

    Extensions:
    - fenced_code: code blocks
    - tables: tables
    - toc: auto heading ids
    - nl2br: newline to br
    - codehilite: syntax highlighting
    """
    if len(markdown_text) <= MAX_CACHED_MARKDOWN_CHARS:
        return _render_cached_markdown(markdown_text)
    return _render_markdown(markdown_text)


def generate_unique_slug(title, existing_slug=None):
    """Generate a unique URL slug from title.

    Adds a short uuid suffix to ensure uniqueness.
    """
    slug_base = re.sub(r'[^\w\s-]', '', title.lower()).strip()
    slug_base = re.sub(r'[\s_]+', '-', slug_base)
    slug_base = slug_base[:80] or 'post'

    short_uuid = uuid.uuid4().hex[:8]
    new_slug = f'{slug_base}-{short_uuid}'

    if existing_slug and new_slug == existing_slug:
        return existing_slug

    return new_slug


def save_blog_post(form, existing_post=None):
    """Save a blog post (create or update).

    Returns the saved BlogPost object.
    """
    markdown_text = form.content_markdown.data
    html_content = render_markdown_to_html(markdown_text)

    # Handle slug.
    slug = form.slug.data.strip() if form.slug.data else ''
    if not slug:
        slug = generate_unique_slug(
            form.title.data,
            existing_slug=existing_post.slug if existing_post else None,
        )
    elif existing_post and existing_post.slug != slug:
        if BlogPost.query.filter_by(slug=slug).first():
            slug = generate_unique_slug(form.title.data)
    elif not existing_post and BlogPost.query.filter_by(slug=slug).first():
        slug = generate_unique_slug(form.title.data)

    # Handle cover image upload.
    cover_image = None
    if form.cover_image.data and form.cover_image.data.filename:
        saved_name, _ = save_uploaded_file(form.cover_image.data, 'images')
        if saved_name:
            cover_image = f'uploads/images/{saved_name}'

    if existing_post:
        # Update existing post.
        existing_post.title = form.title.data
        existing_post.slug = slug
        existing_post.content_markdown = markdown_text
        existing_post.content_html = html_content
        existing_post.summary = form.summary.data or ''
        existing_post.tags = form.tags.data or ''
        existing_post.is_published = form.is_published.data == 'published'
        if cover_image:
            existing_post.cover_image = cover_image
        db.session.commit()
        return existing_post

    # Create new post.
    post = BlogPost(
        title=form.title.data,
        slug=slug,
        content_markdown=markdown_text,
        content_html=html_content,
        summary=form.summary.data or '',
        cover_image=cover_image,
        tags=form.tags.data or '',
        is_published=form.is_published.data == 'published',
        user_id=current_user.id,
    )
    db.session.add(post)
    db.session.commit()
    return post


def register_blog_admin_routes(app):
    """Register blog management routes."""

    @app.route('/manage/blog')
    @login_required
    @admin_required
    def manage_blog():
        """Render the blog post management list."""
        posts = BlogPost.query.order_by(BlogPost.created_at.desc()).all()
        published_count = sum(1 for p in posts if p.is_published)
        draft_count = len(posts) - published_count

        return render_with_background(
            'admin/manage_blog.html',
            'blog_background',
            title='Blog Manager',
            posts=posts,
            total_count=len(posts),
            published_count=published_count,
            draft_count=draft_count,
        )

    @app.route('/manage/blog/new', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def new_blog_post():
        """Create a new blog post."""
        form = BlogPostForm()
        if form.validate_on_submit():
            post = save_blog_post(form)
            flash(f'Post "{post.title}" saved.')
            return redirect(url_for('manage_blog'))

        return render_with_background(
            'admin/edit_blog_post.html',
            'blog_background',
            title='New Blog Post',
            form=form,
            post=None,
        )

    @app.route('/manage/blog/edit/<int:post_id>', methods=['GET', 'POST'])
    @login_required
    @admin_required
    def edit_blog_post(post_id):
        """Edit an existing blog post."""
        post = db.get_or_404(BlogPost, post_id)
        form = BlogPostForm(obj=post)

        # Populate form data on GET.
        if form.is_published.data is None:
            form.is_published.data = 'published' if post.is_published else 'draft'

        if form.validate_on_submit():
            save_blog_post(form, existing_post=post)
            flash(f'Post "{post.title}" updated.')
            return redirect(url_for('manage_blog'))

        return render_with_background(
            'admin/edit_blog_post.html',
            'blog_background',
            title=f'Edit: {post.title}',
            form=form,
            post=post,
        )

    @app.route('/manage/blog/delete/<int:post_id>', methods=['POST'])
    @login_required
    @admin_required
    def delete_blog_post(post_id):
        """Delete a blog post."""
        post = db.get_or_404(BlogPost, post_id)
        title = post.title
        db.session.delete(post)
        db.session.commit()
        flash(f'Post "{title}" deleted.')
        return redirect_with_fallback('manage_blog')

    @app.route('/api/import-file', methods=['POST'])
    @login_required
    @admin_required
    def api_import_file():
        """Import a file (HTML/Markdown/text) and return its content as Markdown."""
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        uploaded = request.files['file']
        if not uploaded.filename:
            return jsonify({'error': 'No file selected'}), 400

        filename = uploaded.filename.lower()
        raw_bytes = uploaded.read()

        # Try to decode as UTF-8, fallback to GBK.
        try:
            content = raw_bytes.decode('utf-8')
        except UnicodeDecodeError:
            content = raw_bytes.decode('gbk', errors='replace')

        title = os.path.splitext(uploaded.filename)[0]

        if filename.endswith(('.md', '.markdown', '.txt')):
            # Markdown or plain text: use directly.
            return jsonify({'markdown': content, 'title': title})

        if filename.endswith(('.html', '.htm')):
            # HTML: extract body, convert to Markdown.
            soup = BeautifulSoup(content, 'html.parser')

            # Remove style, script, nav, footer, header tags.
            for tag in soup.find_all(['style', 'script', 'nav', 'footer', 'header']):
                tag.decompose()

            # Try to extract <article> or <main> or <body>.
            body = soup.find('article') or soup.find('main') or soup.find('body')
            if body is None:
                body = soup

            html_fragment = str(body)

            converter = html2text.HTML2Text()
            converter.ignore_links = False
            converter.ignore_images = False
            converter.ignore_emphasis = False
            converter.body_width = 0
            md_content = converter.handle(html_fragment)

            return jsonify({'markdown': md_content.strip(), 'title': title})

        return jsonify({'error': 'Unsupported file type. Use .md, .txt, .html'}), 400

    @app.route('/blog/post/<slug>')
    def view_blog_post(slug):
        """View a single published blog post (public)."""
        post = BlogPost.query.filter_by(slug=slug, is_published=True).first_or_404()
        return render_with_background(
            'public/blog_post.html',
            'blog_background',
            title=post.title,
            post=post,
        )
