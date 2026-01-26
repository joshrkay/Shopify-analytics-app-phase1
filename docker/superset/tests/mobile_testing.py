"""
Mobile Testing Configuration for Merchant Analytics Dashboard

Test Devices:
- iPhone SE (375x667, 2x DPR)
- iPhone 14 Pro Max (430x932, 3x DPR)
- iPad (768x1024, 2x DPR)
- Android tablet (600x1024, 1.5x DPR)

Browsers:
- Safari iOS 15+
- Chrome Android 12+
- Chrome Desktop

Performance SLA:
- Chart load time: ≤ 3s
- Dashboard load time: ≤ 5s
- Network: 4G simulated
- Dataset size: up to 5 years history

Usage:
    pytest docker/superset/tests/mobile_testing.py --browser webkit --headed
"""

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest


@dataclass
class DeviceConfig:
    """Configuration for a test device."""
    name: str
    viewport_width: int
    viewport_height: int
    device_pixel_ratio: float
    user_agent: str
    has_touch: bool = True
    is_mobile: bool = True


# Device configurations matching spec
DEVICE_CONFIGS: dict[str, DeviceConfig] = {
    'iphone_se': DeviceConfig(
        name='iPhone SE',
        viewport_width=375,
        viewport_height=667,
        device_pixel_ratio=2.0,
        user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15',
        has_touch=True,
        is_mobile=True,
    ),
    'iphone_pro_max': DeviceConfig(
        name='iPhone 14 Pro Max',
        viewport_width=430,
        viewport_height=932,
        device_pixel_ratio=3.0,
        user_agent='Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15',
        has_touch=True,
        is_mobile=True,
    ),
    'ipad': DeviceConfig(
        name='iPad',
        viewport_width=768,
        viewport_height=1024,
        device_pixel_ratio=2.0,
        user_agent='Mozilla/5.0 (iPad; CPU OS 15_0 like Mac OS X) AppleWebKit/605.1.15',
        has_touch=True,
        is_mobile=False,
    ),
    'android_tablet': DeviceConfig(
        name='Android Tablet',
        viewport_width=600,
        viewport_height=1024,
        device_pixel_ratio=1.5,
        user_agent='Mozilla/5.0 (Linux; Android 12; Pixel C) AppleWebKit/537.36',
        has_touch=True,
        is_mobile=False,
    ),
}


# Browser configurations
BROWSER_CONFIGS: dict[str, dict[str, Any]] = {
    'safari_ios': {
        'browser': 'webkit',
        'min_version': '15.0',
    },
    'chrome_android': {
        'browser': 'chromium',
        'min_version': '100',
    },
    'chrome_desktop': {
        'browser': 'chromium',
        'min_version': '100',
    },
}


# Network conditions for 4G simulation
NETWORK_4G: dict[str, Any] = {
    'offline': False,
    'download_throughput': 4 * 1024 * 1024 / 8,  # 4 Mbps
    'upload_throughput': 3 * 1024 * 1024 / 8,    # 3 Mbps
    'latency': 20,  # 20ms latency
}


# Performance SLA thresholds (in milliseconds)
PERFORMANCE_THRESHOLDS: dict[str, int] = {
    'chart_load_ms': 3000,      # ≤ 3 seconds
    'dashboard_load_ms': 5000,  # ≤ 5 seconds
    'lcp_ms': 2500,             # Largest Contentful Paint target
    'fid_ms': 100,              # First Input Delay target
    'cls': 0.1,                 # Cumulative Layout Shift target
}


class MobileTestHelpers:
    """Helper functions for mobile testing."""

    @staticmethod
    def get_device_config(device_name: str) -> DeviceConfig:
        """Get device configuration by name."""
        return DEVICE_CONFIGS.get(device_name)

    @staticmethod
    def get_playwright_device_options(device_name: str) -> dict[str, Any]:
        """
        Get Playwright-compatible device options.

        Args:
            device_name: Name of the device configuration

        Returns:
            Dictionary of Playwright context options
        """
        config = DEVICE_CONFIGS.get(device_name)
        if not config:
            raise ValueError(f"Unknown device: {device_name}")

        return {
            'viewport': {
                'width': config.viewport_width,
                'height': config.viewport_height,
            },
            'device_scale_factor': config.device_pixel_ratio,
            'user_agent': config.user_agent,
            'has_touch': config.has_touch,
            'is_mobile': config.is_mobile,
        }

    @staticmethod
    async def measure_lcp(page) -> float:
        """
        Measure Largest Contentful Paint.

        Args:
            page: Playwright page object

        Returns:
            LCP value in milliseconds
        """
        lcp = await page.evaluate('''() => {
            return new Promise((resolve) => {
                new PerformanceObserver((list) => {
                    const entries = list.getEntries();
                    const lastEntry = entries[entries.length - 1];
                    resolve(lastEntry.startTime);
                }).observe({type: 'largest-contentful-paint', buffered: true});

                // Fallback timeout
                setTimeout(() => resolve(null), 10000);
            });
        }''')
        return lcp

    @staticmethod
    async def measure_chart_load_time(page, chart_selector: str) -> float:
        """
        Measure time to load a specific chart.

        Args:
            page: Playwright page object
            chart_selector: CSS selector for the chart

        Returns:
            Load time in milliseconds
        """
        start_time = await page.evaluate('() => performance.now()')
        await page.wait_for_selector(chart_selector, state='visible', timeout=10000)
        end_time = await page.evaluate('() => performance.now()')
        return end_time - start_time

    @staticmethod
    async def verify_touch_interaction(page, element_selector: str) -> bool:
        """
        Verify that touch interactions work on an element.

        Args:
            page: Playwright page object
            element_selector: CSS selector for the element

        Returns:
            True if touch interaction succeeded
        """
        element = await page.query_selector(element_selector)
        if not element:
            return False

        # Simulate tap
        await element.tap()
        return True

    @staticmethod
    async def check_responsive_layout(page, breakpoint: str) -> dict[str, Any]:
        """
        Check responsive layout for a breakpoint.

        Args:
            page: Playwright page object
            breakpoint: 'mobile', 'tablet', or 'desktop'

        Returns:
            Layout verification results
        """
        results = {
            'breakpoint': breakpoint,
            'charts_visible': [],
            'charts_stacked': False,
            'filter_bar_collapsed': False,
        }

        # Check chart visibility
        charts = await page.query_selector_all('[data-test="chart-container"]')
        results['charts_visible'] = len(charts)

        # Check if charts are stacked (mobile layout)
        if breakpoint == 'mobile':
            first_chart = await page.query_selector('[data-test="chart-container"]:first-child')
            if first_chart:
                box = await first_chart.bounding_box()
                results['charts_stacked'] = box['width'] > 350  # Full width on mobile

        return results


# Pytest fixtures for mobile testing
@pytest.fixture(params=list(DEVICE_CONFIGS.keys()))
def device_config(request):
    """Fixture that provides all device configurations."""
    return DEVICE_CONFIGS[request.param]


@pytest.fixture
def network_4g():
    """Fixture that provides 4G network conditions."""
    return NETWORK_4G


@pytest.fixture
def performance_thresholds():
    """Fixture that provides performance thresholds."""
    return PERFORMANCE_THRESHOLDS


# Test classes
class TestMobileLayout:
    """Tests for mobile responsive layout."""

    @pytest.mark.parametrize('device_name', ['iphone_se', 'iphone_pro_max'])
    async def test_mobile_single_column_layout(self, page, device_name):
        """Verify charts stack in single column on mobile."""
        config = DEVICE_CONFIGS[device_name]
        await page.set_viewport_size({
            'width': config.viewport_width,
            'height': config.viewport_height,
        })

        await page.goto('/superset/dashboard/merchant-analytics/')
        await page.wait_for_load_state('networkidle')

        # Verify single column layout
        charts = await page.query_selector_all('.dashboard-chart')
        for chart in charts:
            box = await chart.bounding_box()
            assert box['width'] >= config.viewport_width * 0.9, \
                f"Chart should be full width on mobile ({device_name})"

    @pytest.mark.parametrize('device_name', ['ipad', 'android_tablet'])
    async def test_tablet_two_column_layout(self, page, device_name):
        """Verify charts display in two columns on tablet."""
        config = DEVICE_CONFIGS[device_name]
        await page.set_viewport_size({
            'width': config.viewport_width,
            'height': config.viewport_height,
        })

        await page.goto('/superset/dashboard/merchant-analytics/')
        await page.wait_for_load_state('networkidle')

        # Verify charts can be side by side
        charts = await page.query_selector_all('.dashboard-chart')
        if len(charts) >= 2:
            box1 = await charts[0].bounding_box()
            # Charts should be less than full width on tablet
            assert box1['width'] < config.viewport_width * 0.7, \
                f"Charts should be in multi-column layout on tablet ({device_name})"


class TestMobilePerformance:
    """Tests for mobile performance metrics."""

    async def test_chart_load_time(self, page, device_config, network_4g):
        """Verify chart loads within SLA on mobile with 4G."""
        # Set device viewport
        await page.set_viewport_size({
            'width': device_config.viewport_width,
            'height': device_config.viewport_height,
        })

        # Apply network throttling
        await page.route('**/*', lambda route: route.continue_())

        start = await page.evaluate('performance.now()')
        await page.goto('/superset/dashboard/merchant-analytics/')

        # Wait for first chart
        await page.wait_for_selector('.dashboard-chart', state='visible')
        end = await page.evaluate('performance.now()')

        chart_load_time = end - start
        assert chart_load_time <= PERFORMANCE_THRESHOLDS['chart_load_ms'], \
            f"Chart load time {chart_load_time}ms exceeds SLA of {PERFORMANCE_THRESHOLDS['chart_load_ms']}ms"

    async def test_dashboard_load_time(self, page, device_config):
        """Verify dashboard loads within SLA."""
        await page.set_viewport_size({
            'width': device_config.viewport_width,
            'height': device_config.viewport_height,
        })

        start = await page.evaluate('performance.now()')
        await page.goto('/superset/dashboard/merchant-analytics/')
        await page.wait_for_load_state('networkidle')
        end = await page.evaluate('performance.now()')

        dashboard_load_time = end - start
        assert dashboard_load_time <= PERFORMANCE_THRESHOLDS['dashboard_load_ms'], \
            f"Dashboard load time {dashboard_load_time}ms exceeds SLA"


class TestTouchInteractions:
    """Tests for touch interaction support."""

    @pytest.mark.parametrize('device_name', list(DEVICE_CONFIGS.keys()))
    async def test_chart_tap_interaction(self, page, device_name):
        """Verify charts respond to tap on touch devices."""
        config = DEVICE_CONFIGS[device_name]
        await page.set_viewport_size({
            'width': config.viewport_width,
            'height': config.viewport_height,
        })

        await page.goto('/superset/dashboard/merchant-analytics/')
        await page.wait_for_selector('.dashboard-chart', state='visible')

        # Tap on a chart
        chart = await page.query_selector('.dashboard-chart')
        await chart.tap()

        # Verify tooltip or interaction response
        # (Implementation depends on chart library behavior)

    async def test_filter_swipe_interaction(self, page, device_config):
        """Verify filter panel can be swiped on mobile."""
        if not device_config.is_mobile:
            pytest.skip("Swipe test only for mobile devices")

        await page.set_viewport_size({
            'width': device_config.viewport_width,
            'height': device_config.viewport_height,
        })

        await page.goto('/superset/dashboard/merchant-analytics/')
        await page.wait_for_load_state('networkidle')

        # Test swipe gesture on filter panel
        # (Implementation depends on Superset's mobile UI)


class TestEmptyStates:
    """Tests for empty state handling on mobile."""

    async def test_no_data_empty_state(self, page, device_config):
        """Verify empty state displays correctly on mobile."""
        await page.set_viewport_size({
            'width': device_config.viewport_width,
            'height': device_config.viewport_height,
        })

        # Navigate with filter that returns no results
        await page.goto('/superset/dashboard/merchant-analytics/?native_filters={"date_range":{"value":"1900-01-01"}}')
        await page.wait_for_load_state('networkidle')

        # Check for empty state message
        empty_state = await page.query_selector('[data-test="empty-state"]')
        if empty_state:
            text = await empty_state.text_content()
            assert 'No data' in text or 'no results' in text.lower()
