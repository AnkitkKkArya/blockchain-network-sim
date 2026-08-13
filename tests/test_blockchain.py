"""
Phase 1 done-when check: run `pytest` from the project root once
blockchain.py is implemented. All of these should pass.
"""

import sys
import os
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Blockchain, Block  # noqa: E402
from wallet import Wallet  # noqa: E402


def _signed_transaction(wallet: Wallet, sender: str, recipient: str, amount: int) -> dict:
    """
    Phase 6 requires every transaction add_transaction() accepts to
    carry a valid signature, so these Phase 1 fixtures need a wallet
    to sign with now — an unsigned dict is correctly rejected.
    """
    transaction = {"from": sender, "to": recipient, "amount": amount}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    transaction["signature"] = signature
    return transaction


def _mine_block(bc: Blockchain) -> Block:
    """
    Stand in for real mining (Phase 4 adds proof-of-work). Bundles the
    current mempool into a properly-linked, correctly-hashed block and
    appends it to the chain.
    """
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


def test_genesis_block_created():
    bc = Blockchain()
    assert len(bc.chain) == 1
    assert bc.chain[0].index == 0


def test_valid_chain_passes():
    wallet = Wallet()
    bc = Blockchain(initial_balances={wallet.public_key_pem: 10})
    bc.add_transaction(_signed_transaction(wallet, "A", "B", 10))
    # TODO once mining exists (Phase 4): mine a block here before asserting.
    assert bc.is_chain_valid()


def test_tampering_is_detected():
    wallet = Wallet()
    bc = Blockchain(initial_balances={wallet.public_key_pem: 15})
    bc.add_transaction(_signed_transaction(wallet, "A", "B", 10))
    _mine_block(bc)
    bc.add_transaction(_signed_transaction(wallet, "B", "C", 5))
    _mine_block(bc)

    assert bc.is_chain_valid()

    bc.chain[0].transactions.append({"from": "X", "to": "Y", "amount": 9999})

    assert not bc.is_chain_valid()


def test_add_transaction_rejects_bad_signature():
    """
    Phase 6: add_transaction() is the mempool gate — an unsigned or
    forged transaction must never make it in, since anything in the
    mempool is eligible to be mined into a block.
    """
    bc = Blockchain()
    with pytest.raises(ValueError):
        bc.add_transaction({"from": "A", "to": "B", "amount": 10})

    wallet = Wallet()
    transaction = _signed_transaction(wallet, "A", "B", 10)
    transaction["amount"] = 9999  # mutated after signing
    with pytest.raises(ValueError):
        bc.add_transaction(transaction)
