"""Bridge the remote lease protocol into the existing WorkerExecutor contract."""
from __future__ import annotations

from collections.abc import Callable

from .remote_worker import RemoteLease, RemoteWorkerExecutor
from .worker import WorkerResult, WorkerTask


class LeasedRemoteWorkerExecutor:
    """WorkerFabric-compatible executor with an explicit lease provider."""

    def __init__(
        self,
        executor: RemoteWorkerExecutor,
        lease_provider: Callable[[WorkerTask], RemoteLease],
    ):
        self.executor = executor
        self.lease_provider = lease_provider

    def execute(self, task: WorkerTask) -> WorkerResult:
        lease = self.lease_provider(task)
        return self.executor.execute(task, lease)
