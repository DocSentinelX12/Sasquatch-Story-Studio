"""Authoritative, versioned production state and dependency graph.

This module is deliberately independent of AI runtimes. It records production
truth, provenance, and dependency relationships so downstream systems can make
surgical regeneration decisions without guessing what is safe to rebuild.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

NodeKind = Literal[
    "series",
    "episode",
    "scene",
    "shot",
    "asset",
    "job",
    "artifact",
    "approval",
]

NodeStatus = Literal["draft", "proposed", "canonical", "superseded", "retired"]


class ProductionStateError(ValueError):
    """Raised when canonical production state would become invalid."""


@dataclass(frozen=True)
class StateNode:
    """Immutable revision of one production object."""

    node_id: str
    kind: NodeKind
    revision: int
    content_hash: str
    episode_id: str | None
    status: NodeStatus = "draft"
    data: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        if not self.node_id.strip():
            raise ProductionStateError("node_id is required")
        if self.revision < 1:
            raise ProductionStateError("revision must be >= 1")
        if len(self.content_hash) != 64 or any(c not in "0123456789abcdef" for c in self.content_hash):
            raise ProductionStateError("content_hash must be a lowercase SHA-256 digest")
        if self.kind == "episode" and self.episode_id not in (None, self.node_id):
            raise ProductionStateError("episode node must identify itself as its episode_id")
        if self.kind != "series" and self.episode_id is None:
            raise ProductionStateError("non-series nodes require episode_id")


@dataclass(frozen=True)
class Dependency:
    """A directed dependency: dependent requires upstream at a specific revision."""

    upstream_id: str
    upstream_revision: int
    downstream_id: str


@dataclass(frozen=True)
class Invalidation:
    """Reason a downstream node can no longer be considered current."""

    node_id: str
    reason: str
    caused_by: str


@dataclass
class ProductionState:
    """Versioned canonical state for one series and its independent episodes."""

    series_id: str
    nodes: dict[str, StateNode] = field(default_factory=dict)
    dependencies: set[Dependency] = field(default_factory=set)

    def add_node(self, node: StateNode) -> None:
        if node.kind == "series" and node.node_id != self.series_id:
            raise ProductionStateError("series node does not match series_id")
        if node.kind != "series" and node.episode_id is None:
            raise ProductionStateError("episode-local node requires episode_id")
        if node.kind != "series" and node.episode_id is not None:
            episode = self.nodes.get(node.episode_id)
            if episode is not None and episode.kind != "episode":
                raise ProductionStateError("episode_id points to a non-episode node")
        existing = self.nodes.get(node.node_id)
        if existing is not None and node.revision <= existing.revision:
            raise ProductionStateError(
                f"node {node.node_id} revision must increase beyond {existing.revision}"
            )
        self.nodes[node.node_id] = node

    def add_dependency(self, dependency: Dependency) -> None:
        upstream = self.nodes.get(dependency.upstream_id)
        downstream = self.nodes.get(dependency.downstream_id)
        if upstream is None or downstream is None:
            raise ProductionStateError("dependencies require both nodes to exist")
        if dependency.upstream_revision != upstream.revision:
            raise ProductionStateError(
                f"dependency revision for {dependency.upstream_id} is stale"
            )
        if upstream.kind != "series" and downstream.kind != "series":
            if upstream.episode_id != downstream.episode_id:
                raise ProductionStateError("cross-episode dependencies are not canonical")
        if dependency.upstream_id == dependency.downstream_id:
            raise ProductionStateError("a node cannot depend on itself")
        if self._would_cycle(dependency):
            raise ProductionStateError("dependency would create a cycle")
        self.dependencies.add(dependency)

    def dependencies_for(self, node_id: str) -> tuple[Dependency, ...]:
        return tuple(sorted(
            (d for d in self.dependencies if d.downstream_id == node_id),
            key=lambda d: (d.upstream_id, d.upstream_revision),
        ))

    def dependents_of(self, node_id: str) -> tuple[str, ...]:
        return tuple(sorted(d.downstream_id for d in self.dependencies if d.upstream_id == node_id))

    def stale_nodes(self, changed_node_id: str) -> tuple[Invalidation, ...]:
        """Return the smallest transitive downstream invalidation set.

        The changed node itself is not returned. Callers can replace it with a
        new revision, then use this result to invalidate only its descendants.
        """
        if changed_node_id not in self.nodes:
            raise ProductionStateError(f"unknown changed node: {changed_node_id}")
        seen: set[str] = set()
        queue = [changed_node_id]
        invalidations: list[Invalidation] = []
        while queue:
            current = queue.pop(0)
            for downstream in self.dependents_of(current):
                if downstream in seen:
                    continue
                seen.add(downstream)
                invalidations.append(
                    Invalidation(
                        node_id=downstream,
                        reason=f"upstream dependency changed: {current}",
                        caused_by=changed_node_id,
                    )
                )
                queue.append(downstream)
        return tuple(invalidations)

    def assert_current(self, node_id: str) -> None:
        """Fail closed if any recorded dependency revision no longer matches."""
        node = self.nodes.get(node_id)
        if node is None:
            raise ProductionStateError(f"unknown node: {node_id}")
        for dependency in self.dependencies_for(node_id):
            upstream = self.nodes.get(dependency.upstream_id)
            if upstream is None or upstream.revision != dependency.upstream_revision:
                raise ProductionStateError(
                    f"node {node_id} has a stale dependency: {dependency.upstream_id}"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "series_id": self.series_id,
            "nodes": {
                node_id: asdict(node)
                for node_id, node in sorted(self.nodes.items())
            },
            "dependencies": [
                asdict(item)
                for item in sorted(
                    self.dependencies,
                    key=lambda d: (d.downstream_id, d.upstream_id, d.upstream_revision),
                )
            ],
        }

    def content_hash(self) -> str:
        payload = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _would_cycle(self, candidate: Dependency) -> bool:
        children: dict[str, set[str]] = {}
        for dependency in self.dependencies:
            children.setdefault(dependency.upstream_id, set()).add(dependency.downstream_id)
        children.setdefault(candidate.upstream_id, set()).add(candidate.downstream_id)
        stack = [candidate.downstream_id]
        visited: set[str] = set()
        while stack:
            current = stack.pop()
            if current == candidate.upstream_id:
                return True
            if current in visited:
                continue
            visited.add(current)
            stack.extend(children.get(current, ()))
        return False


def hash_state(data: dict[str, Any]) -> str:
    """Hash canonical JSON data for a node revision."""
    payload = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
