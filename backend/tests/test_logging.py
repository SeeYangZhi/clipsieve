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
    structlog.contextvars.clear_contextvars()
