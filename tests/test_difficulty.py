"""
Phase 10 done-when check: run `pytest` from the project root once
Blockchain.adjust_difficulty() is implemented.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Blockchain, Block  # noqa: E402
from consensus import proof_of_work  # noqa: E402


def _mine_block(bc: Blockchain) -> Block:
    """
    Real proof-of-work mining (unlike the fabricated-timestamp blocks used
    below for the genesis-skip/floor tests): this is what test 1 needs to
    actually observe wall-clock elapsed time at difficulty=1.
    """
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


def test_difficulty_increases_after_fast_mining():
    """
    ADJUSTMENT_INTERVAL=5 means the first window (chain length 6) is
    genesis-anchored and skipped (see test below) — it's never a multiple
    of 5 anyway, so it wouldn't fire regardless. The first window that can
    actually fire is chain length 10 (window_start = chain[4], not
    genesis). Mining 2*ADJUSTMENT_INTERVAL blocks at difficulty=1, with no
    artificial delay, guarantees we pass through that checkpoint fast
    enough to trigger the "mining too fast" branch.
    """
    bc = Blockchain()
    bc.difficulty = 1

    for _ in range(2 * Blockchain.ADJUSTMENT_INTERVAL):
        _mine_block(bc)

    assert bc.difficulty > 1


def test_genesis_anchored_window_does_not_adjust():
    """
    Directly targets the bug the genesis-index-0 check exists to avoid:
    genesis's timestamp is a hardcoded 0, not a real wall-clock moment, so
    if a window's lower bound is genesis, elapsed-time math over it is
    meaningless and must be skipped even when it "looks" huge.

    ADJUSTMENT_INTERVAL is overridden to 1 so the very next block's window
    is genesis-anchored (chain length 2, window_start = chain[-2] =
    chain[0] = genesis) without needing to mine a real 5-block window.
    """
    bc = Blockchain()
    bc.ADJUSTMENT_INTERVAL = 1
    initial_difficulty = bc.difficulty

    block = Block(index=1, timestamp=1_000_000, transactions=[], previous_hash=bc.last_block.hash)
    block.hash = block.compute_hash()
    bc.add_block(block)

    assert bc.difficulty == initial_difficulty


def test_difficulty_never_drops_below_1():
    """
    A huge elapsed time (mining way slower than target) should decrement
    difficulty, but never past 1. ADJUSTMENT_INTERVAL is overridden to 1
    so each block after the first is its own adjustment window, and
    fabricated timestamps (rather than real slow mining) make "too slow"
    deterministic without actually waiting.
    """
    bc = Blockchain()
    bc.difficulty = 1
    bc.ADJUSTMENT_INTERVAL = 1

    # chain length 2: window_start is genesis (index 0) -> skipped, same as
    # the test above. This block just gives the next window a non-genesis
    # lower bound.
    first = Block(index=1, timestamp=1000, transactions=[], previous_hash=bc.last_block.hash)
    first.hash = first.compute_hash()
    bc.add_block(first)

    # chain length 3: window_start = chain[1] (`first`, not genesis) ->
    # this window fires. elapsed is enormous, so difficulty would try to
    # go to 0 if not floored.
    second = Block(
        index=2, timestamp=1000 + 1_000_000, transactions=[], previous_hash=first.hash
    )
    second.hash = second.compute_hash()
    bc.add_block(second)

    assert bc.difficulty == 1
