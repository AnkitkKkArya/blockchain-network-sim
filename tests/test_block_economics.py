"""
Phase 13 done-when check: run `pytest` from the project root once
Blockchain.validate_block_economics() / validate_chain_economics() are
implemented and wired into app.py's /blocks/receive and p2p.py's
resolve_conflicts().
"""

import sys
import os
import time
from dataclasses import asdict

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Block, Blockchain  # noqa: E402
from p2p import PeerRegistry  # noqa: E402
from wallet import Wallet  # noqa: E402


def _signed_transaction(wallet: Wallet, recipient_pem: str, amount: float, fee: float = 0) -> dict:
    transaction = {"from": wallet.public_key_pem, "to": recipient_pem, "amount": amount, "fee": fee}
    transaction["signature"] = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    return transaction


def test_rejects_forged_signature():
    sender = Wallet()
    recipient = Wallet()
    bc = Blockchain(initial_balances={sender.public_key_pem: 100})

    forged = _signed_transaction(sender, recipient.public_key_pem, 10)
    forged["amount"] = 9999  # mutated after signing -> signature no longer matches

    block = Block(
        index=1, timestamp=time.time(), transactions=[forged], previous_hash=bc.last_block.hash
    )
    assert bc.validate_block_economics(block, {}) is False


def test_rejects_same_block_double_spend():
    """
    The Phase 7 gap this targets directly: two transactions from the same
    sender that each individually fit the sender's pre-block balance, but
    together spend more than it actually has.
    """
    sender = Wallet()
    recipient_a = Wallet()
    recipient_b = Wallet()
    bc = Blockchain(initial_balances={sender.public_key_pem: 100})

    spend_a = _signed_transaction(sender, recipient_a.public_key_pem, 70)
    spend_b = _signed_transaction(sender, recipient_b.public_key_pem, 70)
    block = Block(
        index=1,
        timestamp=time.time(),
        transactions=[spend_a, spend_b],
        previous_hash=bc.last_block.hash,
    )
    assert bc.validate_block_economics(block, {}) is False


def test_rejects_inflated_coinbase():
    miner = Wallet()
    bc = Blockchain()

    coinbase = {"from": "COINBASE", "to": miner.public_key_pem, "amount": Blockchain.BLOCK_REWARD + 1000}
    block = Block(
        index=1, timestamp=time.time(), transactions=[coinbase], previous_hash=bc.last_block.hash
    )
    assert bc.validate_block_economics(block, {}) is False


def test_accepts_honest_block():
    sender = Wallet()
    recipient = Wallet()
    miner = Wallet()
    bc = Blockchain(initial_balances={sender.public_key_pem: 100})

    payment = _signed_transaction(sender, recipient.public_key_pem, 40, fee=1)
    coinbase = {"from": "COINBASE", "to": miner.public_key_pem, "amount": Blockchain.BLOCK_REWARD + 1}
    block = Block(
        index=1,
        timestamp=time.time(),
        transactions=[payment, coinbase],
        previous_hash=bc.last_block.hash,
    )
    assert bc.validate_block_economics(block, {}) is True


def _mine_block(bc: Blockchain) -> Block:
    block = Block(
        index=len(bc.chain),
        timestamp=time.time(),
        transactions=list(bc.pending_transactions),
        previous_hash=bc.last_block.hash,
    )
    block.hash = block.compute_hash()
    bc.chain.append(block)
    bc.pending_transactions = []
    return block


def _staked_validator_chain(stake_amount: float) -> tuple:
    validator = Wallet()
    bc = Blockchain(initial_balances={validator.public_key_pem: 1000})
    payload = {
        "from": validator.public_key_pem,
        "to": f"STAKE:{validator.public_key_pem}",
        "amount": stake_amount,
    }
    signature = validator.sign_transaction(payload)
    bc.stake(validator.public_key_pem, stake_amount, signature)
    _mine_block(bc)
    assert bc.get_stake(validator.public_key_pem) == stake_amount
    return bc, validator


def test_accepts_legitimate_slash_burn_within_staked_amount():
    bc, validator = _staked_validator_chain(900)

    burn = {"from": f"STAKE:{validator.public_key_pem}", "to": bc.BURN_ADDRESS, "amount": 900}
    block = Block(
        index=bc.last_block.index + 1,
        timestamp=time.time(),
        transactions=[burn],
        previous_hash=bc.last_block.hash,
    )
    assert bc.validate_block_economics(block, {}) is True


def test_rejects_forged_slash_burn_exceeding_actual_stake():
    bc, validator = _staked_validator_chain(900)

    forged_burn = {"from": f"STAKE:{validator.public_key_pem}", "to": bc.BURN_ADDRESS, "amount": 5000}
    block = Block(
        index=bc.last_block.index + 1,
        timestamp=time.time(),
        transactions=[forged_burn],
        previous_hash=bc.last_block.hash,
    )
    assert bc.validate_block_economics(block, {}) is False


class _FakeResponse:
    def __init__(self, chain_dicts: list):
        self._chain_dicts = chain_dicts

    def raise_for_status(self):
        pass

    def json(self):
        return {"chain": self._chain_dicts}


def test_resolve_conflicts_rejects_longer_chain_with_overspent_transaction(monkeypatch):
    """
    Phase 12-style scenario, at the unit level: a peer offers a longer
    chain to overtake ours, but instead of an honest double-spend (the
    original attack — a legitimate reorg, still not fixed by this phase),
    this one contains a transaction spending more than its sender ever
    had. Before Phase 13, resolve_conflicts only checked length +
    validate_chain (hash self-consistency/linkage), which this candidate
    passes fine — it would have been adopted. Now validate_chain_economics
    must also pass, and doesn't.
    """
    local = Blockchain()
    registry = PeerRegistry()
    registry.register("http://fake-peer:5000")

    attacker = Wallet()  # never funded anywhere in this candidate chain
    victim = Wallet()

    forged_chain = Blockchain()  # same empty genesis as `local`
    overspend = _signed_transaction(attacker, victim.public_key_pem, 1000)
    block = Block(
        index=1,
        timestamp=time.time(),
        transactions=[overspend],
        previous_hash=forged_chain.last_block.hash,
    )
    block.hash = block.compute_hash()
    forged_chain.chain.append(block)  # length 2, longer than local's length 1

    forged_chain_dicts = [asdict(b) for b in forged_chain.chain]
    monkeypatch.setattr("p2p.requests.get", lambda url, timeout=5: _FakeResponse(forged_chain_dicts))

    result = registry.resolve_conflicts(local.chain)

    assert result == local.chain  # forged/overspent candidate rejected despite being longer
