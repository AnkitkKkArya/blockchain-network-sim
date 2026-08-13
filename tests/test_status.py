"""
Phase 17 done-when check: run `pytest` from the project root once
GET /status is implemented.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from blockchain import Blockchain  # noqa: E402
from wallet import Wallet  # noqa: E402


def _fresh_client(initial_balances: dict = None) -> TestClient:
    app_module.blockchain = Blockchain(initial_balances=initial_balances)
    return TestClient(app_module.app)


def test_status_reflects_chain_length_and_mempool_size():
    sender = Wallet()
    recipient = Wallet()
    miner = Wallet()
    client = _fresh_client(initial_balances={sender.public_key_pem: 100})

    initial_status = client.get("/status").json()
    assert initial_status["chain_length"] == 1  # genesis only
    assert initial_status["mempool_size"] == 0
    assert initial_status["consensus_mode"] == "pow"
    assert "difficulty" in initial_status
    assert "active_peer_count" in initial_status
    assert "active_validator_count" not in initial_status  # not in pos mode

    transaction = {"from": sender.public_key_pem, "to": recipient.public_key_pem, "amount": 10, "fee": 0}
    transaction["signature"] = sender.sign_transaction(transaction)
    transaction["sender_public_key"] = sender.public_key_pem
    client.post("/transactions/new", json=transaction, params={"broadcast": False})

    after_submit = client.get("/status").json()
    assert after_submit["mempool_size"] == 1
    assert after_submit["chain_length"] == 1

    client.get("/mine", params={"miner_public_key": miner.public_key_pem})

    after_mine = client.get("/status").json()
    assert after_mine["chain_length"] == 2
    assert after_mine["mempool_size"] == 0
