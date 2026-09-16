from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation
from studio.gpu_worker_agent import GpuWorkerAgent


def test_worker_agent_registration_payload_is_derived_from_observation():
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-aaa", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),),
        topology_text="GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )
    agent = GpuWorkerAgent("worker-a", lambda: observation)
    payload = agent.registration_payload()
    assert payload["worker_id"] == "worker-a"
    assert payload["hardware_observation_digest"] == observation.digest()
    assert payload["gpu_count"] == 1


def test_worker_agent_does_not_claim_verified_health_without_dcgm_evidence():
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(GpuDeviceObservation(0, "GPU-aaa", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),),
        topology_text="GPU0",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )
    agent = GpuWorkerAgent("worker-a", lambda: observation)
    assert agent.heartbeat_payload()["health_evidence"] == "nvidia_smi_inventory_only"
