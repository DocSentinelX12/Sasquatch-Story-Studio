import pytest

from studio.gpu_capabilities import (
    CapabilityState,
    GpuVerificationContext,
    admit_gpu_workload,
    derive_gpu_capabilities,
)
from studio.gpu_infrastructure import GpuDeviceObservation, GpuHostObservation, GpuTelemetryObservation, TelemetryEvidence, TelemetryStatus
from studio.hardware_requirements import GpuPlacement, HardwareRequirements


def _telemetry(now=100, health="healthy"):
    def observed(value, source="test"):
        return TelemetryEvidence(TelemetryStatus.OBSERVED, value, source, now)

    unavailable = lambda: TelemetryEvidence(TelemetryStatus.UNAVAILABLE, None, "test", now)
    return GpuTelemetryObservation(
        temperature_c=observed(50),
        power_usage_w=observed(200),
        power_limit_w=observed(700),
        utilization_percent=observed(10),
        memory_utilization_percent=observed(5),
        ecc_errors=observed(0),
        mig_mode=observed(0),
        nvlink_state=observed(True),
        pcie_link_generation=observed(4),
        pcie_link_width=observed(16),
        pcie_tx_kb_s=observed(10),
        pcie_rx_kb_s=observed(10),
        xid_errors=unavailable(),
        dcgm_health=observed(health),
        collector_identity="test",
    )


def _host(now=100, telemetry=True):
    gpu = GpuDeviceObservation(
        0,
        "GPU-aaa",
        "NVIDIA Test GPU",
        81920,
        0,
        "00000000:17:00.0",
        "10.0",
        _telemetry(now) if telemetry else GpuTelemetryObservation.unavailable("test", now),
    )
    return GpuHostObservation(
        "worker-a",
        "580.95.05",
        "13.0",
        (gpu,),
        "GPU0",
        True,
        "4.0",
        '{"overall health":"healthy"}',
        observed_at=now,
        collector_identity="test",
    )


def test_observed_gpu_is_not_production_eligible_until_admitted():
    capabilities = derive_gpu_capabilities(_host(), now=100)
    assert capabilities.records[0].base.state is CapabilityState.VERIFIED
    assert capabilities.records[0].health.state is CapabilityState.VERIFIED
    decision = admit_gpu_workload(HardwareRequirements(min_gpu_count=1), capabilities, now=100)
    assert decision.eligible
    assert decision.gpu_uuids == ("GPU-aaa",)


def test_stale_health_evidence_cannot_satisfy_health_admission():
    host = _host(now=100)
    capabilities = derive_gpu_capabilities(host, now=100)
    decision = admit_gpu_workload(
        HardwareRequirements(min_gpu_count=1),
        capabilities,
        now=200,
        freshness_seconds={"health": 50},
    )
    assert not decision.eligible
    assert "stale" in decision.reason


def test_missing_topology_cannot_satisfy_nvlink_admission():
    host = _host()
    host = GpuHostObservation(
        host.worker_id,
        host.driver_version,
        host.cuda_supported_version,
        host.gpus,
        None,
        host.dcgm_available,
        host.dcgm_version,
        host.health_json,
        observed_at=host.observed_at,
        collector_identity=host.collector_identity,
    )
    capabilities = derive_gpu_capabilities(host, now=100)
    decision = admit_gpu_workload(
        HardwareRequirements(min_gpu_count=1, placement=GpuPlacement.SAME_NVLINK_DOMAIN),
        capabilities,
        now=100,
    )
    assert not decision.eligible
    assert "topology" in decision.reason


def test_nccL_requirement_requires_exact_evidence_coverage():
    host = _host()
    capabilities = derive_gpu_capabilities(host, now=100)
    decision = admit_gpu_workload(
        HardwareRequirements(min_gpu_count=1, require_nccl=True),
        capabilities,
        now=100,
    )
    assert not decision.eligible
    assert "NCCL" in decision.reason


def test_gpu_direct_requirement_requires_explicit_network_evidence():
    host = _host()
    capabilities = derive_gpu_capabilities(host, now=100)
    decision = admit_gpu_workload(
        HardwareRequirements(min_gpu_count=1, require_gpu_direct_network=True),
        capabilities,
        now=100,
    )
    assert not decision.eligible
    assert "GPU-direct" in decision.reason
