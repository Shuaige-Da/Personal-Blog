import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from sqlalchemy import event

from backend.admin.settings import (
    apply_background_library_selection,
    get_clock_settings,
    handle_background_upload_form,
    list_background_library_assets,
    set_setting,
    update_settings,
)
from backend.core.forms import BackgroundForm
from backend.core.models import SiteSetting, db


class BackgroundLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        static_root = root / 'static'
        upload_root = static_root / 'uploads'
        (static_root / 'assets' / 'backgrounds').mkdir(parents=True)
        (upload_root / 'backgrounds').mkdir(parents=True)
        (static_root / 'assets' / 'backgrounds' / 'default.svg').write_text(
            '<svg></svg>',
            encoding='utf-8',
        )
        (upload_root / 'backgrounds' / 'custom.jpg').write_bytes(b'image')
        (upload_root / 'backgrounds' / 'movie.mp4').write_bytes(b'video')
        (upload_root / 'backgrounds' / 'notes.txt').write_text('skip', encoding='utf-8')

        self.app = Flask(__name__, static_folder=str(static_root))
        self.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite:///:memory:',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
            UPLOAD_FOLDER=str(upload_root),
            SECRET_KEY='test-secret',
        )
        self.app.add_url_rule('/admin', 'admin', lambda: '')
        db.init_app(self.app)
        self.ctx = self.app.app_context()
        self.ctx.push()
        db.create_all()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()
        self.temp_dir.cleanup()

    def test_list_background_library_assets_includes_uploads_and_assets(self):
        with self.app.test_request_context('/admin'):
            assets = list_background_library_assets()

        paths = {asset['path'] for asset in assets}
        self.assertIn('assets/backgrounds/default.svg', paths)
        self.assertIn('uploads/backgrounds/custom.jpg', paths)
        self.assertIn('uploads/backgrounds/movie.mp4', paths)
        self.assertNotIn('uploads/backgrounds/notes.txt', paths)

    def test_background_library_scan_is_cached_for_one_request(self):
        with patch('backend.admin.settings.os.listdir', wraps=os.listdir) as listdir:
            with self.app.test_request_context('/admin'):
                first_result = list_background_library_assets()
                second_result = list_background_library_assets()

        self.assertIs(first_result, second_result)
        self.assertEqual(listdir.call_count, 2)

    def test_clock_settings_are_loaded_in_one_cached_query(self):
        statements = []

        def record_statement(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            if 'site_setting' in statement and statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)

        event.listen(db.engine, 'before_cursor_execute', record_statement)
        try:
            with self.app.test_request_context('/admin'):
                first_result = get_clock_settings()
                second_result = get_clock_settings()
        finally:
            event.remove(db.engine, 'before_cursor_execute', record_statement)

        self.assertEqual(first_result, second_result)
        self.assertEqual(len(statements), 1)

    def test_batch_setting_update_uses_one_lookup(self):
        set_setting('first', 'old')
        db.session.commit()
        statements = []

        def record_statement(
            connection,
            cursor,
            statement,
            parameters,
            context,
            executemany,
        ):
            if 'site_setting' in statement and statement.lstrip().upper().startswith('SELECT'):
                statements.append(statement)

        event.listen(db.engine, 'before_cursor_execute', record_statement)
        try:
            with self.app.test_request_context('/admin'):
                update_settings({'first': 'new', 'second': 'created', 'third': 'created'})
                db.session.commit()
        finally:
            event.remove(db.engine, 'before_cursor_execute', record_statement)

        values = {item.key: item.value for item in SiteSetting.query.all()}
        self.assertEqual(values['first'], 'new')
        self.assertEqual(values['second'], 'created')
        self.assertEqual(values['third'], 'created')
        self.assertEqual(len(statements), 1)

    def test_apply_background_library_selection_updates_setting_and_clears_playlist(self):
        set_setting('blog_background_playlist_enabled', '1')
        set_setting('blog_background_playlist_paths', '["uploads/backgrounds/old.jpg"]')
        db.session.commit()

        apply_background_library_selection(
            'blog_background',
            'uploads/backgrounds/custom.jpg',
        )
        db.session.commit()

        values = {item.key: item.value for item in SiteSetting.query.all()}
        self.assertEqual(values['blog_background'], 'uploads/backgrounds/custom.jpg')
        self.assertEqual(values['blog_background_kind'], 'image')
        self.assertEqual(values['blog_background_playlist_enabled'], '0')
        self.assertEqual(values['blog_background_playlist_paths'], '[]')

    def test_single_background_submit_can_use_selected_library_asset(self):
        self.app.config['WTF_CSRF_ENABLED'] = False
        set_setting('home_background_playlist_enabled', '1')
        set_setting('home_background_playlist_paths', '["uploads/backgrounds/old.jpg"]')
        db.session.commit()

        with self.app.test_request_context(
            '/admin',
            method='POST',
            data={
                'background-single-target': 'home_background',
                'library_background_path': 'uploads/backgrounds/custom.jpg',
                'background-single-submit': '1',
            },
        ):
            response = handle_background_upload_form(BackgroundForm(prefix='background-single'))

        values = {item.key: item.value for item in SiteSetting.query.all()}
        self.assertEqual(response.status_code, 302)
        self.assertEqual(values['home_background'], 'uploads/backgrounds/custom.jpg')
        self.assertEqual(values['home_background_kind'], 'image')
        self.assertEqual(values['home_background_playlist_enabled'], '0')
        self.assertEqual(values['home_background_playlist_paths'], '[]')


if __name__ == '__main__':
    unittest.main()
