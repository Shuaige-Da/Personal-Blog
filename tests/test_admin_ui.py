import io
from pathlib import Path
import tempfile
import unittest

from PIL import Image

from backend.core.app import create_app
from backend.admin.settings import get_setting, set_setting
from backend.core.models import BlogPost, DiaryEntry, FileRecord, User, db


class AdminUiTests(unittest.TestCase):
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
        self.admin = User(username='admin-ui-test', is_admin=True)
        self.admin.set_password('a-secure-test-password')
        db.session.add(self.admin)
        db.session.commit()
        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.admin.id)
            session['_fresh'] = True

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.upload_dir.cleanup()

    def test_all_admin_navigation_targets_render(self):
        routes = (
            '/blog',
            '/admin',
            '/manage/blog',
            '/manage/blog/new',
            '/manage/diaries',
            '/manage/music',
            '/manage/images',
            '/manage/videos',
            '/chat',
        )
        for route in routes:
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)

    def test_admin_header_exposes_primary_actions_and_logout(self):
        response = self.client.get('/admin')
        page = response.get_data(as_text=True)
        self.assertIn('个人博客', page)
        self.assertIn('设置中心', page)
        self.assertIn('写文章', page)
        self.assertIn('AI 助手', page)
        self.assertIn('退出登录', page)
        self.assertNotIn('data-site-clock', page)
        self.assertIn('rw-admin-quick-grid', page)

    def test_clock_is_limited_to_home_and_admin_dashboard(self):
        response = self.client.get('/')
        page = response.get_data(as_text=True)
        self.assertIn('data-site-clock', page)
        self.assertNotIn('rw-site-clock--embedded', page)

        articles_page = self.client.get('/articles').get_data(as_text=True)
        settings_page = self.client.get('/admin').get_data(as_text=True)
        dashboard_page = self.client.get('/blog').get_data(as_text=True)
        self.assertNotIn('data-site-clock', articles_page)
        self.assertNotIn('data-site-clock', settings_page)
        self.assertIn('data-site-clock', dashboard_page)
        self.assertIn('rw-site-clock--embedded', dashboard_page)

    def test_public_layout_hides_manual_background_switcher(self):
        page = self.client.get('/').get_data(as_text=True)
        self.assertNotIn('data-background-choice', page)
        self.assertNotIn('rw-background-switcher', page)

    def test_public_article_restores_table_of_contents(self):
        post = BlogPost(
            title='目录测试文章',
            slug='toc-test-post',
            content_markdown='## 第一节\n\n### 子章节',
            content_html='<h2 id="first">第一节</h2><h3 id="child">子章节</h3>',
            summary='目录测试',
            tags='测试,目录',
            is_published=True,
            user_id=self.admin.id,
        )
        db.session.add(post)
        db.session.commit()

        page = self.client.get('/blog/post/toc-test-post').get_data(as_text=True)
        self.assertIn('data-article-toc', page)
        self.assertIn('data-toc-list', page)
        self.assertIn('data-article-content', page)
        self.assertNotIn('data-site-clock', page)

    def test_background_playlist_renders_as_automatic_layers(self):
        background_dir = Path(self.upload_dir.name) / 'backgrounds'
        background_dir.mkdir(parents=True, exist_ok=True)
        for filename in ('playlist-one.jpg', 'playlist-two.jpg'):
            (background_dir / filename).write_bytes(b'playlist-test')

        set_setting('home_background_playlist_enabled', '1')
        set_setting(
            'home_background_playlist_paths',
            '["uploads/backgrounds/playlist-one.jpg", "uploads/backgrounds/playlist-two.jpg"]',
        )
        set_setting('home_background_playlist_interval_seconds', '7')
        set_setting('home_background_playlist_image_limit', '20')
        db.session.commit()

        response = self.client.get('/')
        page = response.get_data(as_text=True)
        self.assertIn('data-background-playlist', page)
        self.assertIn('data-background-interval="7"', page)
        self.assertIn('playlist-one.jpg', page)
        self.assertIn('playlist-two.jpg', page)

    def test_media_page_uses_themed_file_picker(self):
        response = self.client.get('/manage/images')
        page = response.get_data(as_text=True)
        self.assertIn('rw-file-picker', page)
        self.assertIn('media-file-input', page)
        self.assertIn('尚未选择文件', page)

    def test_music_page_exposes_themeable_audio_sources(self):
        page = self.client.get('/manage/music').get_data(as_text=True)
        self.assertIn('data-rw-audio', page)
        self.assertIn('media-preview-audio-player', page)

    def test_image_upload_button_persists_a_valid_file(self):
        image_stream = io.BytesIO()
        Image.new('RGB', (24, 24), '#79bfe9').save(image_stream, format='PNG')
        image_stream.seek(0)
        response = self.client.post(
            '/manage/images',
            data={
                'image-file': (image_stream, 'admin-ui-upload.png'),
                'image-submit': '上传图片',
            },
            content_type='multipart/form-data',
        )
        self.assertEqual(response.status_code, 302)
        record = FileRecord.query.filter_by(file_type='image').one()
        self.assertTrue(record.filename.endswith('.png'))
        self.assertEqual(record.original_name, 'admin-ui-upload.png')

    def test_clock_settings_button_updates_all_clock_values(self):
        response = self.client.post(
            '/admin',
            data={
                'site-clock-style': 'text',
                'site-clock-hour_cycle': '12',
                'site-clock-show_date': '0',
                'site-clock-submit': '更新时间样式',
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_setting('site_clock_style'), 'text')
        self.assertEqual(get_setting('site_clock_hour_cycle'), '12')
        self.assertEqual(get_setting('site_clock_show_date'), '0')

    def test_diary_create_and_delete_buttons_complete_the_flow(self):
        response = self.client.post(
            '/manage/diaries',
            data={
                'manage-diary-title': '管理按钮测试日记',
                'manage-diary-content': '这条记录用于验证新建和删除按钮。',
                'manage-diary-submit': '发布日记',
            },
        )
        self.assertEqual(response.status_code, 302)
        diary = DiaryEntry.query.one()
        delete_response = self.client.post(f'/delete-diary/{diary.id}')
        self.assertEqual(delete_response.status_code, 302)
        self.assertEqual(DiaryEntry.query.count(), 0)


if __name__ == '__main__':
    unittest.main()
