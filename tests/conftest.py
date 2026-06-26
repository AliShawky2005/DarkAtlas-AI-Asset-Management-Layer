"""
Pytest configuration.

We use asyncio mode "auto" so async test functions work without
needing the @pytest.mark.asyncio decorator on every test.
"""

import pytest


# Tell pytest-asyncio to treat all async tests as asyncio tests automatically
def pytest_configure(config):
    config.addinivalue_line(
        "markers", "asyncio: mark test as async"
    )