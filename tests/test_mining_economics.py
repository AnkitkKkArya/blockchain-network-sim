"""
Phase 9 done-when check: run `pytest` from the project root once
BLOCK_REWARD/MAX_TRANSACTIONS_PER_BLOCK/fee handling and /mine's
prioritization are implemented.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from blockchain import Blockchain  # noqa: E402
from wallet import Wallet  # noqa: E402


def _signed_transaction(wallet: Wallet, recipient: str, amount: float, fee: float = 0) -> dict:
    transaction = {"from": wallet.public_key_pem, "to": recipient, "amount": amount, "fee": fee}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    transaction["signature"] = signature
    return transaction


def _fresh_client(initial_balances: dict = None) -> TestClient:
    """
    app.py's `blockchain` is a single module-global instance created at
    import time from INITIAL_BALANCES. Swapping that global directly
    (rather than reloading the module or setting env vars) gives each
    test an isolated chain, since every endpoint looks up `blockchain`
    from module globals at call time.
    """
    app_module.blockchain = Blockchain(initial_balances=initial_balances)
    return TestClient(app_module.app)


def test_mine_with_empty_mempool_pays_exactly_block_reward():
    miner = Wallet()
    client = _fresh_client()

    response = client.get("/mine", params={"miner_public_key": miner.public_key_pem})
    assert response.status_code == 200

    balance = client.get("/balance", params={"public_key": miner.public_key_pem}).json()["balance"]
    assert balance == Blockchain.BLOCK_REWARD


def test_mine_selects_highest_fee_transactions_and_leaves_rest_pending():
    sender = Wallet()
    recipient = Wallet()
    miner = Wallet()
    client = _fresh_client(initial_balances={sender.public_key_pem: 1000.0})

    fees = [5, 4, 3, 2, 1]  # MAX_TRANSACTIONS_PER_BLOCK + 2 transactions, distinct fees
    assert len(fees) == Blockchain.MAX_TRANSACTIONS_PER_BLOCK + 2
    for fee in fees:
        transaction = _signed_transaction(sender, recipient.public_key_pem, 1, fee=fee)
        response = client.post("/transactions/new", json=transaction, params={"broadcast": False})
        assert response.status_code == 200

    response = client.get("/mine", params={"miner_public_key": miner.public_key_pem})
    assert response.status_code == 200
    mined_block = response.json()

    included_fees = sorted(
        tx["fee"] for tx in mined_block["transactions"] if tx.get("from") != "COINBASE"
    )
    assert included_fees == [3, 4, 5]

    remaining = client.get("/mempool").json()["pending_transactions"]
    remaining_fees = sorted(tx["fee"] for tx in remaining)
    assert remaining_fees == [1, 2]


def test_miner_balance_equals_reward_plus_included_fees():
    sender = Wallet()
    recipient = Wallet()
    miner = Wallet()
    client = _fresh_client(initial_balances={sender.public_key_pem: 1000.0})

    for fee in [5, 4, 3, 2, 1]:
        transaction = _signed_transaction(sender, recipient.public_key_pem, 1, fee=fee)
        client.post("/transactions/new", json=transaction, params={"broadcast": False})

    client.get("/mine", params={"miner_public_key": miner.public_key_pem})

    balance = client.get("/balance", params={"public_key": miner.public_key_pem}).json()["balance"]
    assert balance == Blockchain.BLOCK_REWARD + (5 + 4 + 3)
