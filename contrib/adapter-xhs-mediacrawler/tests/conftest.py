import pytest


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    from clipsieve_xhs.settings import get_xhs_settings

    get_xhs_settings.cache_clear()
    yield
    get_xhs_settings.cache_clear()
