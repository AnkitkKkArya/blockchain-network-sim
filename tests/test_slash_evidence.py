"""
Done-when check for the evidence-based slash-block exemption: a slash
block only counts as legitimate in validate_chain_proof() if it carries
cryptographically-verifiable equivocation_evidence — not merely the
right shape (STAKE:-sender, BURNED-recipient, no validator).
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Block, Blockchain, validate_chain_proof, verify_equivocation_evidence  # noqa: E402
from consensus import proof_of_work  # noqa: E402
from wallet import Wallet  # noqa: E402


def _sign_header(wallet: Wallet, header: dict) -> str:
    return wallet.sign_transaction(header)


def _staked_validator_chain(stake_amount: float = 900):
    validator = Wallet()
    bc = Blockchain(initial_balances={validator.public_key_pem: 1000})
    payload = {
        "from": validator.public_key_pem,
        "to": f"STAKE:{validator.public_key_pem}",
        "amount": stake_amount,
    }
    signature = validator.sign_transaction(payload)
    bc.stake(validator.public_key_pem, stake_amount, signature)

    # Real proof-of-work, not a direct chain append: validate_chain_proof
    # (this test file's whole point) requires every non-slash block to
    # actually satisfy PoW, so the stake-confirmation block must be
    # honestly mined for these tests to isolate the slash-block exemption
    # specifically, rather than failing on an unrelated unmined block.
    block = Block(
        index=len(bc.chain),
        timestamp=time.time(),
        transactions=list(bc.pending_transactions),
        previous_hash=bc.last_block.hash,
    )
    proof_of_work(block, bc.difficulty)
    block.hash = block.compute_hash()
    bc.chain.append(block)
    bc.pending_transactions = []

    return bc, validator


def test_genuine_equivocation_produces_verifiable_slash_evidence():
    bc, validator = _staked_validator_chain()

    next_index = bc.last_block.index + 1
    header_a = {"index": next_index, "previous_hash": "chain-branch-a", "merkle_root": "root-a"}
    header_b = {"index": next_index, "previous_hash": "chain-branch-b", "merkle_root": "root-b"}
    signature_a = _sign_header(validator, header_a)
    signature_b = _sign_header(validator, header_b)

    first = bc.record_proposal(validator.public_key_pem, next_index, header_a, signature_a)
    assert first is False
    second = bc.record_proposal(validator.public_key_pem, next_index, header_b, signature_b)
    assert second is True  # equivocation detected, slash triggered

    assert bc.get_stake(validator.public_key_pem) == 0.0

    slash_block = bc.last_block
    evidence = slash_block.transactions[0]["equivocation_evidence"]
    assert verify_equivocation_evidence(validator.public_key_pem, evidence) is True


def test_validate_chain_proof_accepts_genuine_slash_block_unmined():
    bc, validator = _staked_validator_chain()

    next_index = bc.last_block.index + 1
    header_a = {"index": next_index, "previous_hash": "chain-branch-a", "merkle_root": "root-a"}
    header_b = {"index": next_index, "previous_hash": "chain-branch-b", "merkle_root": "root-b"}
    bc.record_proposal(
        validator.public_key_pem, next_index, header_a, _sign_header(validator, header_a)
    )
    bc.record_proposal(
        validator.public_key_pem, next_index, header_b, _sign_header(validator, header_b)
    )

    # The slash block landed via slash()'s direct chain append — never
    # mined (nonce=0) or validator-signed — yet the whole chain, evidence
    # included, must still validate.
    assert validate_chain_proof(bc.chain) is True


def test_validate_chain_proof_rejects_slash_shaped_block_with_fabricated_evidence():
    """
    The actual exploit this phase closes: before the evidence
    requirement, any block shaped like a slash (STAKE:-sender,
    BURNED-recipient, no validator) was accepted by validate_chain_proof()
    regardless of whether real equivocation ever happened — letting an
    attacker forge a burn against ANY validator's stake without mining
    anything.
    """
    bc, validator = _staked_validator_chain()

    forged_burn = {
        "from": f"STAKE:{validator.public_key_pem}",
        "to": bc.BURN_ADDRESS,
        "amount": 900,
        "equivocation_evidence": [],  # no real evidence at all
    }
    forged_block = Block(
        index=bc.last_block.index + 1,
        timestamp=time.time(),
        transactions=[forged_burn],
        previous_hash=bc.last_block.hash,
    )
    forged_block.hash = forged_block.compute_hash()  # unmined — nonce stays 0

    candidate_chain = bc.chain + [forged_block]
    assert validate_chain_proof(candidate_chain) is False


def test_honest_resubmission_with_same_header_does_not_trigger_equivocation():
    bc, validator = _staked_validator_chain()

    next_index = bc.last_block.index + 1
    header = {"index": next_index, "previous_hash": "same-branch", "merkle_root": "same-root"}
    signature = _sign_header(validator, header)

    first = bc.record_proposal(validator.public_key_pem, next_index, header, signature)
    assert first is False

    # Identical header content resubmitted (e.g. a retried /mine/submit)
    # — must NOT look like equivocation, confirming the header-content
    # comparison fix (not the old block.hash comparison, which would
    # have differed here purely due to timestamp on a real block).
    second = bc.record_proposal(validator.public_key_pem, next_index, dict(header), signature)
    assert second is False
    assert bc.get_stake(validator.public_key_pem) == 900.0  # never slashed
