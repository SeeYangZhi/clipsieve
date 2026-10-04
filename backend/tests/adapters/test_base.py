import hashlib

from clipsieve.adapters.base import AdapterHealth, hash_creator


def test_hash_creator_is_salted_sha256_hex():
    out = hash_creator("UCabc123", "pepper")
    assert out == hashlib.sha256(b"pepper:UCabc123").hexdigest()
    assert len(out) == 64


def test_hash_creator_differs_by_salt():
    assert hash_creator("UCabc123", "a") != hash_creator("UCabc123", "b")


def test_hash_creator_never_returns_raw_id():
    assert hash_creator("UCabc123", "") != "UCabc123"


def test_adapter_health_dataclass():
    h = AdapterHealth(ok=False, message="no chrome")
    assert h.ok is False and h.message == "no chrome"


def test_cover_fetcher_is_none_for_an_adapter_without_the_optional_method():
    from clipsieve.adapters.base import cover_fetcher

    class Plain:
        platform = "x"

        def search(self, queries, limit):
            return iter(())

        def fetch_media(self, post, dest):
            return post

        def healthcheck(self):
            return AdapterHealth(ok=True, message="ok")

    assert cover_fetcher(Plain()) is None


def test_cover_fetcher_returns_the_bound_method_when_callable():
    from clipsieve.adapters.base import cover_fetcher

    class WithCover:
        platform = "x"
        fetch_cover_calls = 0

        def fetch_cover(self, post, dest):
            self.fetch_cover_calls += 1
            return None

    adapter = WithCover()
    fetch = cover_fetcher(adapter)
    assert fetch is not None and fetch(None, None) is None
    assert adapter.fetch_cover_calls == 1

    class NotCallable:
        fetch_cover = "thumb.jpg"

    assert cover_fetcher(NotCallable()) is None


def test_cover_name_matches_the_extraction_thumbnail_name():
    # adapters/ and evidence/ may not import each other (backend/AGENTS.md), so the shared file
    # name is pinned here: extract.write_thumbnail keeps an existing COVER_NAME file.
    from clipsieve.adapters.base import COVER_NAME
    from clipsieve.evidence.extract import THUMB_NAME

    assert COVER_NAME == THUMB_NAME == "thumb.jpg"
