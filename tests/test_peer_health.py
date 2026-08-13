"""
Phase 16 done-when check: run `pytest` from the project root once
PeerRegistry's failure-count/active-inactive tracking is implemented.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from p2p import PeerRegistry  # noqa: E402

# Nothing listens here; connections fail fast (connection refused) rather
# than hanging for the full request timeout.
DUMMY_PEER = "http://127.0.0.1:59999"


def test_peer_marked_inactive_after_threshold_failures():
    registry = PeerRegistry()
    registry.register(DUMMY_PEER)
    assert DUMMY_PEER in registry.active_peers()

    for _ in range(PeerRegistry.FAILURE_THRESHOLD):
        registry.broadcast_transaction({"from": "A", "to": "B", "amount": 1})

    assert DUMMY_PEER in registry.inactive_peers
    assert DUMMY_PEER not in registry.active_peers()


def test_inactive_peer_excluded_from_subsequent_broadcast_targets():
    registry = PeerRegistry()
    registry.register(DUMMY_PEER)
    for _ in range(PeerRegistry.FAILURE_THRESHOLD):
        registry.broadcast_transaction({"from": "A", "to": "B", "amount": 1})
    assert DUMMY_PEER in registry.inactive_peers

    # One more broadcast: the dummy peer must not even be attempted, so
    # its failure count should NOT climb any further.
    failures_before = registry.failure_counts[DUMMY_PEER]
    registry.broadcast_transaction({"from": "A", "to": "B", "amount": 1})
    assert registry.failure_counts[DUMMY_PEER] == failures_before


def test_inactive_peer_still_listed_as_known():
    registry = PeerRegistry()
    registry.register(DUMMY_PEER)
    for _ in range(PeerRegistry.FAILURE_THRESHOLD):
        registry.broadcast_transaction({"from": "A", "to": "B", "amount": 1})

    assert DUMMY_PEER in registry.peers  # never forgotten, only paused
    assert DUMMY_PEER in registry.inactive_peers


def test_reregistering_reactivates_a_peer():
    registry = PeerRegistry()
    registry.register(DUMMY_PEER)
    for _ in range(PeerRegistry.FAILURE_THRESHOLD):
        registry.broadcast_transaction({"from": "A", "to": "B", "amount": 1})
    assert DUMMY_PEER in registry.inactive_peers

    registry.register(DUMMY_PEER)
    assert DUMMY_PEER in registry.active_peers()
    assert registry.failure_counts[DUMMY_PEER] == 0
