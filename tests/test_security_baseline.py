import io
import tempfile
import unittest
from pathlib import Path

from PIL import Image
from werkzeug.datastructures import FileStorage

from backend.admin.blog import render_markdown_to_html
from backend.admin.settings import save_uploaded_file
from backend.core.app import create_app
from backend.core.models import BlogPost, User, db


class SecurityBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                'TESTING': True,
                'LOCAL_DEV': True,
                'SQLALCHEMY_DATABASE_URI': 'sqlite:///:memory:',
                'UPLOAD_FOLDER': self.temp_dir.name,
                'WTF_CSRF_ENABLED': False,
                'RATELIMIT_ENABLED': False,
                'PROXY_FIX_ENABLED': False,
            }
        )
        self.ctx = self.app.app_context()
        self.ctx.push()
        self.user = User(username='owner', is_admin=True)
        self.user.set_password('a-secure-test-password')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.temp_dir.cleanup()

    def add_post(self, *, slug, published):
        post = BlogPost(
            title='安全测试文章',
            slug=slug,
            content_markdown='正文',
            content_html='<p>正文</p>',
            summary='摘要',
            tags='测试',
            is_published=published,
            user_id=self.user.id,
        )
        db.session.add(post)
        db.session.commit()
        return post

    def test_draft_slug_is_not_public(self):
        self.add_post(slug='hidden-draft', published=False)
        response = self.app.test_client().get('/blog/post/hidden-draft')
        self.assertEqual(response.status_code, 404)

    def test_published_post_remains_public(self):
        self.add_post(slug='public-post', published=True)
        response = self.app.test_client().get('/blog/post/public-post')
        self.assertEqual(response.status_code, 200)

    def test_markdown_html_is_allowlist_sanitized(self):
        rendered = render_markdown_to_html(
            '# 标题\n\n<script>alert(1)</script>'
            '\n\n<a href="javascript:alert(2)" onclick="alert(3)">链接</a>'
        )
        self.assertNotIn('<script', rendered)
        self.assertNotIn('onclick', rendered)
        self.assertNotIn('javascript:', rendered)
        self.assertIn('<h1', rendered)

    def test_csp_disallows_unsafe_inline_scripts(self):
        response = self.app.test_client().get('/')
        policy = response.headers['Content-Security-Policy']
        script_policy = next(
            directive for directive in policy.split('; ') if directive.startswith('script-src')
        )
        self.assertNotIn("'unsafe-inline'", script_policy)
        self.assertIn("'nonce-", script_policy)

    def test_fake_image_upload_is_rejected(self):
        storage = FileStorage(
            stream=io.BytesIO(b'<script>alert(1)</script>'),
            filename='portrait.jpg',
            content_type='image/jpeg',
        )
        with self.app.test_request_context('/manage/images', method='POST'):
            saved_name, _ = save_uploaded_file(storage, 'images')
        self.assertIsNone(saved_name)

    def test_valid_png_upload_uses_detected_extension(self):
        stream = io.BytesIO()
        Image.new('RGB', (32, 32), '#4f91c8').save(stream, format='PNG')
        stream.seek(0)
        storage = FileStorage(
            stream=stream,
            filename='portrait.txt',
            content_type='text/plain',
        )
        with self.app.test_request_context('/manage/images', method='POST'):
            saved_name, _ = save_uploaded_file(storage, 'images')
        self.assertTrue(saved_name.endswith('.png'))
        self.assertTrue((Path(self.temp_dir.name) / 'images' / saved_name).exists())


if __name__ == '__main__':
    unittest.main()
