"""
Phase A done-when check: run `pytest` from the project root once
Blockchain.validate_chain_proof() is implemented and wired into
p2p.py's resolve_conflicts().
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Block, Blockchain, validate_chain_proof  # noqa: E402
from consensus import proof_of_work  # noqa: E402
from p2p import PeerRegistry  # noqa: E402


def _mine_block(bc: Blockchain) -> Block:
    """Real proof-of-work mining, same helper pattern as test_difficulty.py."""
    block = Block(
        index=bc.last_block.index + 1,
        timestamp=time.time(),
        transactions=[],
        previous_hash=bc.last_block.hash,
    )
    proof_of_work(block, bc.difficulty)
    block.hash = block.compute_hash()
    bc.add_block(block)
    return block


def test_honestly_mined_chain_passes():
    # Real default difficulty (4), not lowered: validate_chain_proof's
    # accumulator always starts at the class default, since that's what
    # every legitimately-constructed Blockchain actually starts at —
    # only adjust_difficulty() ever legitimately moves it from there.
    bc = Blockchain()
    for _ in range(3):
        _mine_block(bc)

    assert validate_chain_proof(bc.chain) is True


def test_unmined_block_fails():
    # Default difficulty (4), not the lowered 1 used elsewhere in this file:
    # a nonce of 0 has a real (1-in-16) chance of accidentally satisfying
    # difficulty=1, which would make this test flaky. At difficulty=4 that
    # chance is negligible (1 in 65536).
    bc = Blockchain()
    for _ in range(3):
        _mine_block(bc)

    tampered_chain = list(bc.chain)
    tampered_chain[2] = Block(
        index=tampered_chain[2].index,
        timestamp=tampered_chain[2].timestamp,
        transactions=tampered_chain[2].transactions,
        previous_hash=tampered_chain[2].previous_hash,
        nonce=0,
    )
    tampered_chain[2].hash = tampered_chain[2].compute_hash()

    assert validate_chain_proof(tampered_chain) is False


def test_resolve_conflicts_rejects_chain_with_fabricated_nonces(monkeypatch):
    """
    Before Phase A, resolve_conflicts only checked validate_chain (hash
    self-consistency/linkage) and validate_chain_economics (signatures/
    balances) — a longer candidate chain that was never actually mined,
    but is otherwise internally consistent, would have been adopted.
    """
    local = Blockchain()

    fabricated = Blockchain()  # same empty genesis as `local`
    for _ in range(2):
        block = Block(
            index=fabricated.last_block.index + 1,
            timestamp=time.time(),
            transactions=[],
            previous_hash=fabricated.last_block.hash,
            nonce=0,  # never mined — fabricated.difficulty (4) is not satisfied
        )
        block.hash = block.compute_hash()
        fabricated.chain.append(block)

    from dataclasses import asdict

    fabricated_chain_dicts = [asdict(b) for b in fabricated.chain]

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"chain": fabricated_chain_dicts}

    registry = PeerRegistry()
    registry.register("http://fake-peer:5000")
    monkeypatch.setattr("p2p.requests.get", lambda url, timeout=5: _FakeResponse())

    result = registry.resolve_conflicts(local.chain)

    assert result == local.chain  # fabricated (unmined) chain rejected despite being longer


def test_validates_correctly_across_a_difficulty_adjustment_boundary():
    """
    Mines past ADJUSTMENT_INTERVAL*2 blocks at the real starting
    difficulty (mining this fast easily triggers the "too fast, raise
    difficulty" branch — see test_difficulty.py), so adjust_difficulty()
    actually fires at least once mid-chain. validate_chain_proof must
    replay that same difficulty evolution — checking each block against
    whatever difficulty was in effect *at that point*, not the chain's
    final difficulty — for later blocks (mined at the new difficulty) to
    validate correctly. Not lowering difficulty here (unlike
    test_difficulty.py) since validate_chain_proof's accumulator always
    starts at the real class default — see test_honestly_mined_chain_passes.
    """
    bc = Blockchain()

    for _ in range(2 * Blockchain.ADJUSTMENT_INTERVAL):
        _mine_block(bc)

    assert bc.difficulty > 4  # sanity: an adjustment actually happened
    assert validate_chain_proof(bc.chain) is True
