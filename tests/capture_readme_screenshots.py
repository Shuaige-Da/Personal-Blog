"""Capture the final RainWave pages used by the repository README."""

import io
import os
from pathlib import Path
import sys
import time

from PIL import Image
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as conditions
from selenium.webdriver.support.ui import WebDriverWait

os.environ.setdefault('LOCAL_DEV', '1')

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.core.app import create_app
from backend.core.models import User


OUTPUT_DIR = ROOT / 'docs' / 'images'
BASE_URL = os.environ.get('RAINWAVE_BASE_URL', 'http://127.0.0.1:5000').rstrip('/')


def make_driver(width, height):
    """Create a deterministic headless Chrome viewport."""
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--disable-gpu')
    options.add_argument('--hide-scrollbars')
    options.add_argument('--force-device-scale-factor=1')
    options.add_argument(f'--window-size={width},{height}')
    options.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd(
        'Emulation.setDeviceMetricsOverride',
        {
            'width': width,
            'height': height,
            'deviceScaleFactor': 1,
            'mobile': False,
        },
    )
    return driver


def save_webp(driver, filename):
    """Save a browser screenshot as a compact repository-friendly WebP."""
    time.sleep(0.9)
    output = OUTPUT_DIR / filename
    with Image.open(io.BytesIO(driver.get_screenshot_as_png())) as screenshot:
        screenshot.convert('RGB').save(output, 'WEBP', quality=84, method=6)
        print(f'{filename}: {screenshot.width}x{screenshot.height}')


def assert_console_clean(driver, page_name):
    """Fail when Chrome reports a severe browser error."""
    severe = [
        entry
        for entry in driver.get_log('browser')
        if entry['level'] == 'SEVERE'
    ]
    if severe:
        raise AssertionError(f'{page_name} console errors: {severe}')


def build_admin_cookie():
    """Build a Flask-Login cookie for the first local administrator."""
    app = create_app({'RATELIMIT_ENABLED': False})
    with app.app_context():
        admin = User.query.filter_by(is_admin=True).order_by(User.id.asc()).first()
        if admin is None:
            return None
        admin_id = str(admin.id)

    with app.test_client() as client:
        with client.session_transaction() as browser_session:
            browser_session['_user_id'] = admin_id
            browser_session['_fresh'] = True
        cookie = client.get_cookie(app.config['SESSION_COOKIE_NAME'])
        if cookie is None:
            raise RuntimeError('Unable to create an authenticated administrator session.')
        return app.config['SESSION_COOKIE_NAME'], cookie.value


def capture_public_pages():
    """Capture desktop public pages and the responsive mobile homepage."""
    driver = make_driver(1440, 900)
    wait = WebDriverWait(driver, 10)
    try:
        driver.get(f'{BASE_URL}/')
        wait.until(conditions.visibility_of_element_located((By.ID, 'home-title')))
        save_webp(driver, 'home-desktop.webp')

        driver.get(f'{BASE_URL}/articles')
        wait.until(conditions.visibility_of_element_located((By.ID, 'articles-title')))
        save_webp(driver, 'articles-desktop.webp')

        cards = driver.find_elements(By.CSS_SELECTOR, '.rw-article-card')
        if cards:
            cards[0].click()
            wait.until(
                conditions.visibility_of_element_located(
                    (By.CSS_SELECTOR, '[data-article-content]')
                )
            )
            save_webp(driver, 'article-detail-desktop.webp')

        assert_console_clean(driver, 'public desktop')
    finally:
        driver.quit()

    driver = make_driver(390, 844)
    wait = WebDriverWait(driver, 10)
    try:
        driver.get(f'{BASE_URL}/')
        wait.until(conditions.visibility_of_element_located((By.ID, 'home-title')))
        save_webp(driver, 'home-mobile.webp')
        assert_console_clean(driver, 'public mobile')
    finally:
        driver.quit()


def capture_admin_pages():
    """Capture the primary authenticated administration pages."""
    cookie = build_admin_cookie()
    if cookie is None:
        print('Admin screenshots skipped: no local administrator exists.')
        return

    cookie_name, cookie_value = cookie
    driver = make_driver(1440, 900)
    wait = WebDriverWait(driver, 10)
    try:
        driver.get(BASE_URL)
        driver.add_cookie(
            {
                'name': cookie_name,
                'value': cookie_value,
                'path': '/',
                'sameSite': 'Lax',
            }
        )

        for route, selector, filename in (
            ('/blog', '.rw-dashboard-hero', 'admin-dashboard.webp'),
            ('/admin', '.settings-layout', 'admin-settings.webp'),
            ('/chat', '.chat-shell', 'admin-chat.webp'),
        ):
            driver.get(f'{BASE_URL}{route}')
            wait.until(conditions.visibility_of_element_located((By.CSS_SELECTOR, selector)))
            save_webp(driver, filename)

        assert_console_clean(driver, 'administrator desktop')
    finally:
        driver.quit()


if __name__ == '__main__':
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    capture_public_pages()
    capture_admin_pages()
    print(f'README screenshots saved to {OUTPUT_DIR}')
