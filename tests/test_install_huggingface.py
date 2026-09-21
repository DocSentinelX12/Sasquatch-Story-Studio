from scripts.install_huggingface import is_transient_huggingface_error, retry_operation

def test_retry_operation_retries_transient_failure_then_returns_value():
    attempts = []
    def operation():
        attempts.append(len(attempts) + 1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return "ok"
    result = retry_operation(operation, attempts=3, delay_seconds=0, is_retryable=lambda exc: str(exc) == "transient", sleep_fn=lambda _: None)
    assert result == "ok"
    assert attempts == [1, 2, 3]

def test_retry_operation_does_not_retry_non_transient_failure():
    attempts = []
    def operation():
        attempts.append(1)
        raise RuntimeError("permanent")
    try:
        retry_operation(operation, attempts=3, delay_seconds=0, is_retryable=lambda exc: str(exc) == "transient", sleep_fn=lambda _: None)
    except RuntimeError as exc:
        assert str(exc) == "permanent"
    else:
        raise AssertionError("non-transient failure was incorrectly retried")
    assert attempts == [1]

def test_transient_huggingface_error_classification_covers_transport_reset():
    from huggingface_hub.utils import httpx
    assert is_transient_huggingface_error(httpx.ConnectError("connection reset by peer"))
    assert not is_transient_huggingface_error(RuntimeError("invalid repository"))