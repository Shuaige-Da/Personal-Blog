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

    def test_chat_template_contains_only_the_streaming_client(self):
        page = self.client.get('/chat').get_data(as_text=True)

        self.assertEqual(page.count('/api/hermes/chat/stream'), 1)
        self.assertNotIn('RainWaveHermesEnhanced', page)
        self.assertNotIn('pollChatJob', page)

    def test_chat_keeps_composer_editable_and_respects_reader_scroll(self):
        page = self.client.get('/chat').get_data(as_text=True)

        self.assertNotIn('inputArea.disabled = busy', page)
        self.assertIn("content.textContent = '正在思考'", page)
        self.assertIn('if (!followLatest) return', page)
        self.assertIn('id="chat-jump-latest"', page)

    def test_blog_editor_exposes_full_writing_agent_with_attachments(self):
        page = self.client.get('/manage/blog/new').get_data(as_text=True)

        self.assertIn('id="writing-agent-workspace"', page)
        self.assertIn('id="writing-agent-drag-handle"', page)
        self.assertIn('id="writing-agent-surface"', page)
        self.assertNotIn('id="writing-agent-resize-handle"', page)
        self.assertIn('id="writing-copy-latest"', page)
        self.assertIn('id="writing-insert-latest"', page)
        self.assertIn('id="writing-insert-target"', page)
        self.assertIn('--writing-select-width: 132px', page)
        self.assertIn('width: calc(var(--writing-select-width) / 2)', page)
        self.assertIn('background: rgba(4, 17, 34, 0.32)', page)
        self.assertIn('<option value="content">文章正文</option>', page)
        self.assertIn('<option value="summary">文章摘要</option>', page)
        self.assertIn('<option value="tags">标签</option>', page)
        self.assertIn('id="writing-attachment-input"', page)
        self.assertIn('multiple hidden', page)
        self.assertIn("formData.set('context', context.text)", page)
        self.assertEqual(page.count("fetch('/api/hermes/chat/stream'"), 1)
        self.assertNotIn('agentInput.disabled = busy', page)
        self.assertIn('pointer-events: none;', page)
        self.assertIn('pointer-events: auto;', page)
        self.assertIn('aria-modal="false"', page)
        self.assertNotIn("document.body.style.overflow = 'hidden'", page)
        self.assertIn('document.body.append(fab, panel, backdrop)', page)
        self.assertIn("fab.addEventListener('pointerdown'", page)
        self.assertIn('positionPanelNearFab', page)
        self.assertIn('runWorkspaceAction(button.dataset.workspaceAction)', page)
        self.assertIn('workspaceResizeEdges', page)
        self.assertIn("messages.addEventListener('wheel'", page)
        self.assertIn('event.stopPropagation()', page)
        self.assertIn('--writing-workspace-scale', page)
        self.assertIn('backdrop-filter: blur(4px) saturate(122%)', page)
        self.assertNotIn('backdrop-filter: blur(30px)', page)
        self.assertIn('data-article-key="new"', page)
        self.assertIn('rainwave-writing-agent:', page)
        self.assertIn('persistWritingHistory', page)
        self.assertIn('restoreWritingHistory', page)
        self.assertIn('历史自动保存', page)
        self.assertIn("showInsertionStatus('已插入文章正文，工作台保持打开。')", page)
        self.assertIn("showInsertionStatus('已写入文章摘要，工作台保持打开。')", page)
        self.assertIn("showInsertionStatus('已追加到文章标签，工作台保持打开。')", page)
        self.assertIn('class="glass-card rw-editor-hero', page)
        self.assertIn("{{ '更新文章' if post else '保存文章' }}", Path(
            'frontend/templates/admin/edit_blog_post.html'
        ).read_text(encoding='utf-8'))

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
        self.assertRegex(page, r'/static/css/rainwave\.css\?v=\d+')
        self.assertRegex(page, r'/static/js/rainwave\.js\?v=\d+')

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

        css = Path('frontend/static/css/rainwave.css').read_text(encoding='utf-8')
        javascript = Path('frontend/static/js/rainwave.js').read_text(encoding='utf-8')
        self.assertIn('body.rw-immersive[data-endpoint="view_blog_post"]', css)
        self.assertIn('body[data-endpoint="view_blog_post"] .rw-article-shell', css)
        self.assertIn('overflow: visible;', css)
        self.assertIn("['index', 'articles', 'links', 'messages'].includes(endpoint)", javascript)
        self.assertNotIn("['index', 'articles', 'links', 'messages', 'view_blog_post']", javascript)
        self.assertIn('root: null,', javascript)

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
        music_dir = Path(self.upload_dir.name) / 'music'
        music_dir.mkdir(parents=True, exist_ok=True)
        (music_dir / 'available.flac').write_bytes(b'fLaC-test')
        db.session.add_all(
            [
                FileRecord(
                    filename='available.flac',
                    original_name='available.flac',
                    file_type='music',
                    user_id=self.admin.id,
                ),
                FileRecord(
                    filename='missing.mp3',
                    original_name='missing.mp3',
                    file_type='music',
                    user_id=self.admin.id,
                ),
            ]
        )
        db.session.commit()

        page = self.client.get('/manage/music').get_data(as_text=True)
        self.assertIn('data-rw-audio', page)
        self.assertIn('media-preview-audio-player', page)
        self.assertIn('data-audio-original-available="true"', page)
        self.assertIn('data-audio-original-available="false"', page)

        script = Path('frontend/static/js/rainwave.js').read_text(encoding='utf-8')
        self.assertIn("error?.name === 'AbortError'", script)
        self.assertIn('原音频文件不存在，请重新上传或删除此记录。', script)
        self.assertNotIn('无法播放：${error.message', script)

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

    def test_public_pages_default_to_vertical_circular_navigation(self):
        home = self.client.get('/').get_data(as_text=True)
        messages = self.client.get('/messages').get_data(as_text=True)

        self.assertIn('data-page-axis="vertical"', home)
        self.assertIn('data-page-prev', home)
        self.assertIn('href="/messages" data-page-prev', home)
        self.assertIn('href="/" data-page-next', messages)
        self.assertNotIn('rw-turn-edge', home)
        self.assertNotIn('rw-turn-edge', messages)
        self.assertIn('data-page-index="0"', home)
        self.assertIn('data-page-target-index="3"', home)

    def test_vertical_and_horizontal_navigation_use_distinct_full_page_motion(self):
        stylesheet = Path('frontend/static/css/rainwave.css').read_text(encoding='utf-8')
        script = Path('frontend/static/js/rainwave.js').read_text(encoding='utf-8')

        self.assertIn('translate3d(0, 30vh, 0)', stylesheet)
        self.assertIn('translate3d(30vw, 0, 0)', stylesheet)
        self.assertIn('.rw-immersive.rw-is-page-leaving .rw-app', stylesheet)
        self.assertIn("body.classList.add('rw-is-page-leaving')", script)
        self.assertIn('pageDirectionForAnchor', script)
        self.assertIn('window.setTimeout(() => window.location.assign(url), 220)', script)

    def test_all_public_pages_remove_visual_turn_capsules(self):
        for route in ('/', '/articles', '/links', '/messages'):
            with self.subTest(route=route):
                page = self.client.get(route).get_data(as_text=True)
                self.assertIn('data-page-prev hidden', page)
                self.assertIn('data-page-next hidden', page)
                self.assertNotIn('rw-turn-edge', page)

    def test_page_transition_setting_switches_public_axis(self):
        response = self.client.post(
            '/admin',
            data={
                'page-transition-axis': 'horizontal',
                'page-transition-submit': '更新翻页方向',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_setting('page_transition_axis'), 'horizontal')
        page = self.client.get('/articles').get_data(as_text=True)
        self.assertIn('data-page-axis="horizontal"', page)
        self.assertIn('data-page-next hidden', page)

    def test_invalid_saved_page_axis_falls_back_to_vertical(self):
        set_setting('page_transition_axis', 'diagonal')
        db.session.commit()

        page = self.client.get('/links').get_data(as_text=True)

        self.assertIn('data-page-axis="vertical"', page)
        self.assertIn('data-page-next hidden', page)

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
