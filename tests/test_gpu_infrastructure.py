import json

from studio.gpu_infrastructure import (
    GpuDeviceObservation,
    GpuHostObservation,
    parse_nvidia_smi_gpu_csv,
    parse_nvidia_smi_header,
)


def test_parse_nvidia_smi_gpu_csv_preserves_real_identity_fields():
    output = (
        "0, GPU-aaa, NVIDIA Test GPU, 81920, 1024, 00000000:17:00.0, 10.0\n"
        "1, GPU-bbb, NVIDIA Test GPU, 81920, 2048, 00000000:18:00.0, 10.0\n"
    )
    devices = parse_nvidia_smi_gpu_csv(output)
    assert devices == (
        GpuDeviceObservation(
            index=0,
            uuid="GPU-aaa",
            name="NVIDIA Test GPU",
            memory_total_mib=81920,
            memory_used_mib=1024,
            pci_bus_id="00000000:17:00.0",
            compute_capability="10.0",
        ),
        GpuDeviceObservation(
            index=1,
            uuid="GPU-bbb",
            name="NVIDIA Test GPU",
            memory_total_mib=81920,
            memory_used_mib=2048,
            pci_bus_id="00000000:18:00.0",
            compute_capability="10.0",
        ),
    )


def test_parse_nvidia_smi_header_requires_observed_driver_and_cuda_versions():
    header = "NVIDIA-SMI 580.95.05    Driver Version: 580.95.05    CUDA Version: 13.0"
    assert parse_nvidia_smi_header(header) == ("580.95.05", "13.0")


def test_host_observation_digest_is_deterministic_and_contains_no_fake_capacity():
    observation = GpuHostObservation(
        worker_id="worker-a",
        driver_version="580.95.05",
        cuda_supported_version="13.0",
        gpus=(
            GpuDeviceObservation(0, "GPU-aaa", "NVIDIA Test GPU", 81920, 0, "00000000:17:00.0", "10.0"),
        ),
        topology_text="GPU0 GPU1\n",
        dcgm_available=False,
        dcgm_version=None,
        health_json=None,
    )
    payload = json.loads(observation.canonical_json())
    assert payload["gpus"][0]["uuid"] == "GPU-aaa"
    assert observation.digest() == observation.digest()
    assert observation.gpu_count == 1


def test_empty_probe_data_is_not_a_gpu():
    assert parse_nvidia_smi_gpu_csv("") == ()
