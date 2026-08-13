"""
Phase 4: Proof of Work.
Phase 6 (stretch): Proof of Stake mode, toggled by CONSENSUS_MODE.
"""

import os
import random

CONSENSUS_MODE = os.environ.get("CONSENSUS_MODE", "pow")  # "pow" or "pos"


def proof_of_work(block, difficulty: int) -> int:
    """
    Phase 4. Increment block.nonce until block.compute_hash() starts with
    `difficulty` leading zero hex characters. Return the nonce.

    This is the CPU-bound "race" — the part that makes PoW's cost
    tangible instead of abstract. The nonce is the only field we're free
    to change without altering the block's meaning (index/transactions/
    previous_hash are all fixed by the chain state), so it's what gets
    brute-forced. Starting from whatever nonce the block already has
    (0 for a fresh candidate) rather than resetting keeps this reusable
    if a caller ever wants to resume a search.
    """
    computed_hash = block.compute_hash()
    target = "0" * difficulty
    while not computed_hash.startswith(target):
        block.nonce += 1
        computed_hash = block.compute_hash()
    return block.nonce


def is_valid_proof(block, difficulty: int) -> bool:
    """
    Check block.compute_hash() has the required leading zeros.

    This is the cheap side of PoW's asymmetry: finding a valid nonce
    costs real CPU work (proof_of_work above), but *verifying* one is a
    single hash computation. That asymmetry is what makes proof-of-work
    a workable consensus mechanism — everyone can cheaply check a claim
    that was expensive to produce.
    """
    return block.compute_hash().startswith("0" * difficulty)


def select_validator(stakes: dict) -> str:
    """
    Phase 11: weighted-by-stake random selection — a validator with a
    bigger stake is proportionally more likely to be picked for this
    round, but never guaranteed to win one. This is what makes "stake"
    meaningful without needing verifiable randomness (VRF): every node
    computes the same selection from the same stakes dict independently.

    Returns None for an empty stakes dict (no active validators to pick
    from) rather than raising — callers (app.py's /mine) treat that as
    "no PoS block can be produced this round," not an error in the
    selection logic itself.
    """
    if not stakes:
        return None
    validators = list(stakes.keys())
    weights = list(stakes.values())
    return random.choices(validators, weights=weights, k=1)[0]
