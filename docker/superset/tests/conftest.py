"""
Pytest configuration for Superset dashboard tests.

Provides fixtures for:
- Playwright browser setup
- Device emulation
- Network throttling
- Authentication
"""

import os
import pytest
from playwright.async_api import async_playwright


# Superset configuration
SUPERSET_URL = os.getenv('SUPERSET_URL', 'http://localhost:8088')
SUPERSET_USER = os.getenv('SUPERSET_USER', 'admin')
SUPERSET_PASSWORD = os.getenv('SUPERSET_PASSWORD', 'admin')


@pytest.fixture(scope='session')
def event_loop():
    """Create event loop for async tests."""
    import asyncio
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope='session')
async def browser():
    """Create browser instance for test session."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()


@pytest.fixture
async def context(browser):
    """Create browser context for each test."""
    context = await browser.new_context()
    yield context
    await context.close()


@pytest.fixture
async def page(context):
    """Create page for each test."""
    page = await context.new_page()
    yield page
    await page.close()


@pytest.fixture
async def authenticated_page(page):
    """Create authenticated page with Superset login."""
    # Navigate to login
    await page.goto(f'{SUPERSET_URL}/login/')

    # Fill login form
    await page.fill('input[name="username"]', SUPERSET_USER)
    await page.fill('input[name="password"]', SUPERSET_PASSWORD)
    await page.click('input[type="submit"]')

    # Wait for redirect after login
    await page.wait_for_load_state('networkidle')

    yield page


@pytest.fixture
def dashboard_url():
    """Get merchant analytics dashboard URL."""
    return f'{SUPERSET_URL}/superset/dashboard/merchant-analytics/'


# Device fixtures from mobile_testing.py
from .mobile_testing import DEVICE_CONFIGS, NETWORK_4G, PERFORMANCE_THRESHOLDS


@pytest.fixture(params=list(DEVICE_CONFIGS.keys()))
def device_config(request):
    """Parametrized fixture for all device configurations."""
    return DEVICE_CONFIGS[request.param]


@pytest.fixture
def iphone_se_config():
    """iPhone SE device configuration."""
    return DEVICE_CONFIGS['iphone_se']


@pytest.fixture
def iphone_pro_max_config():
    """iPhone 14 Pro Max device configuration."""
    return DEVICE_CONFIGS['iphone_pro_max']


@pytest.fixture
def ipad_config():
    """iPad device configuration."""
    return DEVICE_CONFIGS['ipad']


@pytest.fixture
def android_tablet_config():
    """Android tablet device configuration."""
    return DEVICE_CONFIGS['android_tablet']


@pytest.fixture
def network_4g():
    """4G network throttling configuration."""
    return NETWORK_4G


@pytest.fixture
def performance_thresholds():
    """Performance SLA thresholds."""
    return PERFORMANCE_THRESHOLDS


@pytest.fixture
async def mobile_page(page, iphone_se_config):
    """Page configured for mobile device."""
    await page.set_viewport_size({
        'width': iphone_se_config.viewport_width,
        'height': iphone_se_config.viewport_height,
    })
    yield page


@pytest.fixture
async def tablet_page(page, ipad_config):
    """Page configured for tablet device."""
    await page.set_viewport_size({
        'width': ipad_config.viewport_width,
        'height': ipad_config.viewport_height,
    })
    yield page
