from studio.worker_transport import WorkerRegistration, WorkerTransportSecurity


def test_worker_transport_requires_tls_and_explicit_credentials():
    security = WorkerTransportSecurity(
        base_url="https://studio.example.invalid",
        ca_certificate_path="/etc/studio/ca.pem",
        client_certificate_path="/etc/studio/worker.pem",
        client_key_path="/etc/studio/worker.key",
    )
    registration = WorkerRegistration(worker_id="worker-a", enrollment_token="out-of-band-token")
    security.validate()
    assert registration.worker_id == "worker-a"


def test_plain_http_transport_is_rejected():
    security = WorkerTransportSecurity(base_url="http://studio.example.invalid")
    try:
        security.validate()
    except ValueError:
        return
    raise AssertionError("plain HTTP must never be accepted for worker transport")
