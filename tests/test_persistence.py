"""
Phase 15 done-when check: run `pytest` from the project root once
Blockchain.save_to_disk()/load_from_disk() are implemented.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from blockchain import Block, Blockchain  # noqa: E402
from wallet import Wallet  # noqa: E402


def _signed_transaction(wallet: Wallet, recipient_pem: str, amount: float) -> dict:
    transaction = {"from": wallet.public_key_pem, "to": recipient_pem, "amount": amount, "fee": 0}
    transaction["signature"] = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
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


def test_save_and_load_round_trip_identical_chain_and_balances(tmp_path):
    sender = Wallet()
    recipient_a = Wallet()
    recipient_b = Wallet()
    bc = Blockchain(initial_balances={sender.public_key_pem: 100})

    bc.add_transaction(_signed_transaction(sender, recipient_a.public_key_pem, 30))
    _mine_block(bc)
    bc.add_transaction(_signed_transaction(sender, recipient_b.public_key_pem, 20))
    _mine_block(bc)
    bc.difficulty = 6  # confirm this survives the round-trip too

    storage_path = tmp_path / "chain.json"
    bc.save_to_disk(str(storage_path))

    loaded = Blockchain.load_from_disk(str(storage_path))

    assert len(loaded.chain) == len(bc.chain)
    assert [block.hash for block in loaded.chain] == [block.hash for block in bc.chain]
    assert loaded.difficulty == 6

    for address in (sender.public_key_pem, recipient_a.public_key_pem, recipient_b.public_key_pem):
        assert loaded.get_balance(address) == bc.get_balance(address)


def test_save_and_load_preserves_validator_proposals(tmp_path):
    bc = Blockchain()
    bc.validator_proposals[("some-validator-pubkey", 3)] = "some-block-hash"

    storage_path = tmp_path / "chain.json"
    bc.save_to_disk(str(storage_path))

    loaded = Blockchain.load_from_disk(str(storage_path))
    assert loaded.validator_proposals == bc.validator_proposals
