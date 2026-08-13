"""
Phase 7 done-when check: run `pytest` from the project root once
get_balance()/initial_balances/the balance check are implemented.
"""

import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Blockchain, Block  # noqa: E402
from wallet import Wallet  # noqa: E402


def _signed_transaction(wallet: Wallet, sender: str, recipient: str, amount: float) -> dict:
    transaction = {"from": sender, "to": recipient, "amount": amount}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    transaction["signature"] = signature
    return transaction


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


def test_genesis_funding_reflected_in_balance():
    wallet = Wallet()
    bc = Blockchain(initial_balances={wallet.public_key_pem: 100})
    assert bc.get_balance(wallet.public_key_pem) == 100


def test_balance_decreases_after_mined_spend():
    sender = Wallet()
    recipient = Wallet()
    bc = Blockchain(initial_balances={sender.public_key_pem: 100})

    bc.add_transaction(_signed_transaction(sender, sender.public_key_pem, recipient.public_key_pem, 30))
    _mine_block(bc)

    assert bc.get_balance(sender.public_key_pem) == 70
    assert bc.get_balance(recipient.public_key_pem) == 30


def test_same_initial_balances_produce_identical_genesis_hash():
    """
    Phase 8 prerequisite: every node in the network constructs its own
    Blockchain() independently (one per container/process), so nodes only
    agree on a genesis block if identical initial_balances deterministically
    produce an identical hash. This is what makes docker-compose.yml handing
    every service the same INITIAL_BALANCES actually work.

    No time mocking needed: create_genesis_block() hardcodes timestamp=0
    for block 0, so this is the real proof two independently-constructed
    chains agree, not an artifact of a frozen clock.
    """
    wallet = Wallet()
    balances = {wallet.public_key_pem: 100.0}

    bc1 = Blockchain(initial_balances=balances)
    bc2 = Blockchain(initial_balances=balances)

    assert bc1.chain[0].hash == bc2.chain[0].hash


def test_add_transaction_rejects_overspend():
    sender = Wallet()
    recipient = Wallet()
    bc = Blockchain(initial_balances={sender.public_key_pem: 10})

    overspend = _signed_transaction(sender, sender.public_key_pem, recipient.public_key_pem, 9999)
    with pytest.raises(ValueError):
        bc.add_transaction(overspend)
