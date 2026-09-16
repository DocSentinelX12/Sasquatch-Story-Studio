from dataclasses import dataclass

from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_worker_agent import GpuWorkerAgent


@dataclass
class Transport:
    responses: list[dict]

    def __post_init__(self):
        self.calls = []

    def post_json(self, path, payload, *, bearer_token):
        self.calls.append((path, payload, bearer_token))
        return self.responses.pop(0)


def observation() -> GpuHostObservation:
    return GpuHostObservation(
        worker_id="worker-a",
        driver_version="test-driver",
        cuda_supported_version="12.8",
        gpus=(GpuDeviceObservation(0, "GPU-0", "Test GPU", 16384, 0, "0000:01:00.0", "8.0"),),
        topology_text="GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )


def test_agent_registers_and_heartbeats_with_observed_identity():
    transport = Transport([{"worker_id": "worker-a", "access_token": "access-token"}, {"worker_id": "worker-a"}])
    agent = GpuWorkerAgent("worker-a", observer=observation)

    access = agent.register_remote(transport, "enrollment-token")
    agent.heartbeat_remote(transport, access)

    assert access.worker_id == "worker-a"
    assert transport.calls[0][0] == "/v1/worker/register"
    assert transport.calls[1][0] == "/v1/worker/heartbeat"
    assert transport.calls[0][1]["gpu_uuids"] == ("GPU-0",)
    assert transport.calls[1][2] == "access-token"
