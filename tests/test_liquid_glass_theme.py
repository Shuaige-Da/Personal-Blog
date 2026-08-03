from pathlib import Path
import tempfile
import unittest

from backend.admin.settings import get_setting, set_setting
from backend.core.app import create_app
from backend.core.models import User, db


class LiquidGlassThemeTests(unittest.TestCase):
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
        self.admin = User(username='glass-admin', is_admin=True)
        self.admin.set_password('liquid-glass-test-password')
        db.session.add(self.admin)
        db.session.commit()
        self.client = self.app.test_client()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.context.pop()
        self.upload_dir.cleanup()

    def login_admin(self):
        with self.client.session_transaction() as session:
            session['_user_id'] = str(self.admin.id)
            session['_fresh'] = True

    def test_public_theme_defaults_to_stable_rainwave(self):
        page = self.client.get('/').get_data(as_text=True)

        self.assertIn('data-ui-theme="rainwave"', page)
        self.assertNotIn('css/liquid-glass.css', page)
        self.assertNotIn('data-liquid-refraction-canvas', page)

    def test_saved_liquid_theme_loads_isolated_material_assets(self):
        set_setting('ui_theme', 'liquid_ios')
        db.session.commit()

        page = self.client.get('/articles').get_data(as_text=True)

        self.assertIn('data-ui-theme="liquid_ios"', page)
        self.assertRegex(page, r'/static/css/liquid-glass\.css\?v=\d+')
        self.assertRegex(page, r'/static/js/liquid-glass\.js\?v=\d+')
        self.assertIn('data-liquid-refraction-canvas', page)
        self.assertIn('data-liquid-glass', page)

    def test_invalid_saved_theme_falls_back_to_rainwave(self):
        set_setting('ui_theme', 'unknown-theme')
        db.session.commit()

        page = self.client.get('/links').get_data(as_text=True)

        self.assertIn('data-ui-theme="rainwave"', page)
        self.assertNotIn('css/liquid-glass.css', page)

    def test_admin_theme_form_persists_selection(self):
        self.login_admin()
        response = self.client.post(
            '/admin',
            data={
                'ui-theme-theme': 'liquid_ios',
                'ui-theme-submit': '应用前台主题',
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(get_setting('ui_theme'), 'liquid_ios')

    def test_regular_admin_pages_remain_on_stable_theme(self):
        set_setting('ui_theme', 'liquid_ios')
        db.session.commit()
        self.login_admin()

        page = self.client.get('/admin').get_data(as_text=True)

        self.assertIn('data-ui-theme="rainwave"', page)
        self.assertNotIn('css/liquid-glass.css', page)
        self.assertIn('打开材质实验台', page)

    def test_glass_lab_renders_complete_component_set_for_admin(self):
        self.login_admin()
        page = self.client.get('/admin/glass-lab').get_data(as_text=True)

        self.assertIn('data-ui-theme="liquid_ios"', page)
        self.assertIn('css/liquid-glass-lab.css', page)
        self.assertIn('js/liquid-glass-lab.js', page)
        for marker in (
            'data-liquid-select',
            'data-liquid-switch',
            'data-liquid-action="heart"',
            'data-liquid-play',
            'data-liquid-lens-source',
            'data-liquid-lens-output',
            'data-liquid-nav-item',
            'data-lab-control="refraction"',
        ):
            self.assertIn(marker, page)

    def test_glass_lab_requires_authentication(self):
        response = self.client.get('/admin/glass-lab')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.headers['Location'])

    def test_engine_contains_real_refraction_and_progressive_fallbacks(self):
        script = Path('frontend/static/js/liquid-glass.js').read_text(encoding='utf-8')
        lab_script = Path('frontend/static/js/liquid-glass-lab.js').read_text(encoding='utf-8')
        stylesheet = Path('frontend/static/css/liquid-glass.css').read_text(encoding='utf-8')

        self.assertIn("getContext('webgl'", script)
        self.assertIn('texture2D', script)
        self.assertIn('vec2 chroma', script)
        self.assertIn("getContext('2d'", script)
        self.assertIn('lg-webgl-fallback', script)
        self.assertIn('prefers-reduced-motion', script)
        self.assertIn("addEventListener('visibilitychange'", script)
        self.assertIn('setPointerCapture', script)
        self.assertIn("event.key === 'Enter'", script)
        self.assertIn('drawImage(this.source', lab_script)
        self.assertIn('const zoom = 1.28', lab_script)
        self.assertIn('.lg-glass-layer--edge', stylesheet)
        self.assertIn('.lg-glass-layer--specular', stylesheet)
        self.assertIn('.lg-glass-layer--noise', stylesheet)

    def test_liquid_assets_are_included_in_cache_version(self):
        set_setting('ui_theme', 'liquid_ios')
        db.session.commit()
        page = self.client.get('/').get_data(as_text=True)

        self.assertRegex(page, r'/static/css/rainwave\.css\?v=\d+')
        self.assertRegex(page, r'/static/css/liquid-glass\.css\?v=\d+')
        self.assertRegex(page, r'/static/js/liquid-glass\.js\?v=\d+')


if __name__ == '__main__':
    unittest.main()
