import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import markdown
from sqlalchemy import event

from backend.admin.content import get_recent_entries_with_count
from backend.admin.blog import _render_cached_markdown, render_markdown_to_html
from backend.core.app import create_app
from backend.core.models import BlogPost, DiaryEntry, FileRecord, User, db


class DashboardPerformanceTests(unittest.TestCase):
    def setUp(self):
        self.upload_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                'TESTING': True,
                'LOCAL_DEV': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'UPLOAD_FOLDER': self.upload_dir.name,
                'WTF_CSRF_ENABLED': False,
                'RATELIMIT_ENABLED': False,
                'PROXY_FIX_ENABLED': False,
            }
        )
        self.context = self.app.app_context()
        self.context.push()
        self.admin = User(username='performance-admin', is_admin=True)
        self.admin.set_password('performance-test-password')
        db.session.add(self.admin)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.upload_dir.cleanup()

    def seed_dashboard_content(self, count=12):
        db.session.bulk_save_objects(
            [
                BlogPost(
                    title=f'Post {index}',
                    slug=f'post-{index}',
                    content_markdown='content',
                    content_html='<p>content</p>',
                    user_id=self.admin.id,
                )
                for index in range(count)
            ]
        )
        db.session.bulk_save_objects(
            [
                DiaryEntry(
                    title=f'Diary {index}',
                    content='dashboard diary content',
                    user_id=self.admin.id,
                )
                for index in range(count)
            ]
        )
        for file_type in ('image', 'video', 'music'):
            db.session.bulk_save_objects(
                [
                    FileRecord(
                        filename=f'{file_type}-{index}.bin',
                        original_name=f'{file_type}-{index}.bin',
                        file_type=file_type,
                        user_id=self.admin.id,
                    )
                    for index in range(count)
                ]
            )
        db.session.commit()

    def test_recent_slice_returns_full_count_with_one_query(self):
        self.seed_dashboard_content(count=25)
        statements = []

        def record_statement(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            statements.append(statement)

        event.listen(db.engine, 'before_cursor_execute', record_statement)
        try:
            items, total_count = get_recent_entries_with_count(
                FileRecord,
                FileRecord.upload_date,
                6,
                file_type='image',
            )
        finally:
            event.remove(db.engine, 'before_cursor_execute', record_statement)

        self.assertEqual(len(items), 6)
        self.assertEqual(total_count, 25)
        self.assertEqual(len(statements), 1)

    def test_dashboard_renders_bounded_previews_with_accurate_counts(self):
        self.seed_dashboard_content(count=12)
        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = str(self.admin.id)
            session['_fresh'] = True

        page = client.get('/blog').get_data(as_text=True)

        self.assertGreaterEqual(page.count('<strong>12</strong>'), 5)
        self.assertEqual(page.count('/static/uploads/images/'), 6)
        self.assertEqual(page.count('/static/uploads/videos/'), 4)
        self.assertEqual(page.count('/static/uploads/music/'), 4)
        self.assertEqual(page.count('dashboard diary content'), 4)
        self.assertEqual(page.count('/blog/post/post-'), 3)
        self.assertEqual(page.count('rw-dashboard-deferred'), 2)

    def test_background_and_clock_timers_pause_in_hidden_tabs(self):
        content = Path('frontend/static/js/rainwave.js').read_text(encoding='utf-8')

        self.assertNotIn('setInterval(renderClock', content)
        self.assertIn("document.addEventListener('visibilitychange', scheduleClock)", content)
        self.assertIn('backgroundVideos.forEach((video) => video?.pause())', content)

    def test_repeated_markdown_render_reuses_sanitized_result(self):
        source = '## Unique cache test\n\n`performance-regression-cache-key`'
        _render_cached_markdown.cache_clear()

        with patch('backend.admin.blog.markdown.markdown', wraps=markdown.markdown) as render:
            first = render_markdown_to_html(source)
            second = render_markdown_to_html(source)

        self.assertEqual(first, second)
        self.assertEqual(render.call_count, 1)


if __name__ == '__main__':
    unittest.main()
