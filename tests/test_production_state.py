import pytest

from studio.production_state import (
    Dependency,
    ProductionState,
    ProductionStateError,
    StateNode,
    hash_state,
)


def node(node_id, kind, episode_id, revision=1, data=None):
    payload = data or {"id": node_id, "revision": revision}
    return StateNode(
        node_id=node_id,
        kind=kind,
        revision=revision,
        content_hash=hash_state(payload),
        episode_id=episode_id,
        status="canonical",
        data=payload,
    )


def test_dependency_graph_invalidates_only_downstream_nodes():
    state = ProductionState("series")
    state.add_node(node("series", "series", None))
    state.add_node(node("ep1", "episode", "ep1"))
    state.add_node(node("ep2", "episode", "ep2"))
    state.add_node(node("shot1", "shot", "ep1"))
    state.add_node(node("anim1", "job", "ep1"))
    state.add_node(node("master1", "artifact", "ep1"))
    state.add_node(node("shot2", "shot", "ep2"))

    state.add_dependency(Dependency("shot1", 1, "anim1"))
    state.add_dependency(Dependency("anim1", 1, "master1"))

    invalidated = {item.node_id for item in state.stale_nodes("shot1")}
    assert invalidated == {"anim1", "master1"}
    assert "shot2" not in invalidated


def test_cross_episode_dependency_is_rejected():
    state = ProductionState("series")
    state.add_node(node("series", "series", None))
    state.add_node(node("ep1", "episode", "ep1"))
    state.add_node(node("ep2", "episode", "ep2"))
    state.add_node(node("shot1", "shot", "ep1"))
    state.add_node(node("shot2", "shot", "ep2"))

    with pytest.raises(ProductionStateError, match="cross-episode"):
        state.add_dependency(Dependency("shot1", 1, "shot2"))


def test_dependency_revision_must_match_current_upstream():
    state = ProductionState("series")
    state.add_node(node("series", "series", None))
    state.add_node(node("ep1", "episode", "ep1"))
    state.add_node(node("shot1", "shot", "ep1"))
    state.add_node(node("anim1", "job", "ep1"))
    state.add_node(node("shot1", "shot", "ep1", revision=2))

    with pytest.raises(ProductionStateError, match="stale"):
        state.add_dependency(Dependency("shot1", 1, "anim1"))


def test_dependency_cycles_are_rejected():
    state = ProductionState("series")
    state.add_node(node("series", "series", None))
    state.add_node(node("ep1", "episode", "ep1"))
    state.add_node(node("a", "shot", "ep1"))
    state.add_node(node("b", "job", "ep1"))
    state.add_dependency(Dependency("a", 1, "b"))

    with pytest.raises(ProductionStateError, match="cycle"):
        state.add_dependency(Dependency("b", 1, "a"))


def test_state_hash_is_deterministic():
    state = ProductionState("series")
    state.add_node(node("series", "series", None))
    state.add_node(node("ep1", "episode", "ep1"))
    first = state.content_hash()
    second = state.content_hash()
    assert first == second
    assert len(first) == 64
