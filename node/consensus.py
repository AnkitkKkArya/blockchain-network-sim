"""
Phase 4: Proof of Work.
Phase 6 (stretch): Proof of Stake mode, toggled by CONSENSUS_MODE.
"""

import os

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
    Phase 6 stretch. TODO: pick a validator address, weighted by stake
    (e.g. random.choices with weights=list(stakes.values())).
    Compare this file's two consensus paths side by side once both work —
    that comparison is the actual point of building this phase.
    """
    raise NotImplementedError
