import structlog

from clipsieve.logging import configure_logging, get_logger


def test_configure_logging_binds_and_renders(capsys):
    configure_logging("DEBUG")
    log = get_logger("test")
    structlog.contextvars.bind_contextvars(run_id="run_x")
    log.info("hello", post_id="local:fx-001")
    err = capsys.readouterr().err
    assert "hello" in err
    assert "run_id=run_x" in err
    assert "post_id=local:fx-001" in err


# The two tests below run after the one above (pytest keeps file order). Its captured stderr
# is closed by then, and its bound context must not survive into them.


def test_logging_after_captured_configure_does_not_hit_closed_stream():
    structlog.get_logger().info("x")


def test_contextvars_do_not_leak_between_tests():
    assert structlog.contextvars.get_contextvars() == {}
