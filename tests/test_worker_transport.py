from studio.worker_transport import WorkerRegistration, WorkerTransportSecurity


def test_worker_transport_requires_tls_and_explicit_credentials(tmp_path):
    ca_certificate = tmp_path / "ca.pem"
    client_certificate = tmp_path / "worker.pem"
    client_key = tmp_path / "worker.key"
    for path in (ca_certificate, client_certificate, client_key):
        path.write_text("provisioned-out-of-band-credential", encoding="utf-8")

    security = WorkerTransportSecurity(
        base_url="https://studio.example.invalid",
        ca_certificate_path=str(ca_certificate),
        client_certificate_path=str(client_certificate),
        client_key_path=str(client_key),
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
