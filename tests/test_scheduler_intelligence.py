from studio.resources import ComputeResource, ResourceSnapshot
from studio.scheduler import Job, JobRequirements, JobState, Scheduler


def resources():
    return ResourceSnapshot(
        compute=(
            ComputeResource(
                "worker",
                16,
                64 * 1024**3,
                logical_slots=1,
                scratch_bytes=100 * 1024**3,
            ),
        )
    )


def test_queued_work_ages_and_eventually_precedes_repeated_newer_work():
    scheduler = Scheduler()
    scheduler.submit(Job("old", JobRequirements(), priority=0))
    scheduler.choose("worker", resources(), now=0, lease_seconds=1)
    scheduler.requeue("old", "worker")

    for index in range(1, 5):
        scheduler.submit(Job(f"new-{index}", JobRequirements(), priority=1))
        selected = scheduler.choose("worker", resources(), now=index * 60, lease_seconds=1)
        assert selected is not None
        assert selected.id != "old"
        scheduler.requeue(selected.id, "worker")

    selected = scheduler.choose("worker", resources(), now=5 * 60, lease_seconds=1)

    assert selected is not None
    assert selected.id == "old"


def test_equal_priority_queue_prefers_the_oldest_waiting_job():
    scheduler = Scheduler()
    scheduler.submit(Job("older", JobRequirements(), queued_at=90))
    scheduler.submit(Job("newer", JobRequirements(), queued_at=100))

    first = scheduler.choose("worker", resources(), now=100, lease_seconds=1)

    assert first is not None
    assert first.id == "older"
