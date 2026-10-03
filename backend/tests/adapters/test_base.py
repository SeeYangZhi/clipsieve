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
