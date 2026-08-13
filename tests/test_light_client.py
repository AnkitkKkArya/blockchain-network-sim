"""
Phase 14 done-when check: run `pytest` from the project root once
Block.merkle_root, light_client.LightClient, and app.py's /headers +
/block/{index}/proof are implemented.
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from blockchain import Block, Blockchain  # noqa: E402
from light_client import LightClient  # noqa: E402
from wallet import Wallet  # noqa: E402


def _fresh_client(initial_balances: dict = None) -> TestClient:
    app_module.blockchain = Blockchain(initial_balances=initial_balances)
    return TestClient(app_module.app)


def _signed_transaction(wallet: Wallet, recipient_pem: str, amount: float) -> dict:
    transaction = {"from": wallet.public_key_pem, "to": recipient_pem, "amount": amount, "fee": 0}
    transaction["signature"] = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    return transaction


def _mined_chain_with_one_payment():
    sender = Wallet()
    recipient = Wallet()
    miner = Wallet()
    client = _fresh_client(initial_balances={sender.public_key_pem: 100})

    payment = _signed_transaction(sender, recipient.public_key_pem, 40)
    client.post("/transactions/new", json=payment, params={"broadcast": False})
    client.get("/mine", params={"miner_public_key": miner.public_key_pem})

    return client, payment


def test_light_client_validates_headers_and_verifies_known_transaction():
    client, payment = _mined_chain_with_one_payment()

    headers = client.get("/headers").json()["headers"]
    assert all("transactions" not in header for header in headers)

    light_client = LightClient()
    assert light_client.sync_headers(headers) is True

    proof_response = client.get("/block/1/proof", params={"tx_index": 0}).json()
    assert proof_response["transaction"] == payment

    assert light_client.verify_transaction(proof_response["transaction"], 1, proof_response["proof"]) is True


def test_light_client_rejects_forged_proof_or_wrong_transaction():
    client, payment = _mined_chain_with_one_payment()

    headers = client.get("/headers").json()["headers"]
    light_client = LightClient()
    assert light_client.sync_headers(headers) is True

    proof_response = client.get("/block/1/proof", params={"tx_index": 0}).json()

    tampered_transaction = dict(payment)
    tampered_transaction["amount"] = 9999
    assert light_client.verify_transaction(tampered_transaction, 1, proof_response["proof"]) is False

    forged_proof = [["left", "0" * 64]]
    assert light_client.verify_transaction(payment, 1, forged_proof) is False


def test_light_client_rejects_tampered_previous_hash_header():
    client, _ = _mined_chain_with_one_payment()

    headers = client.get("/headers").json()["headers"]
    light_client = LightClient()
    assert light_client.sync_headers(headers) is True  # sanity: real chain validates

    tampered_headers = [dict(header) for header in headers]
    tampered_headers[1]["previous_hash"] = "0" * 64

    fresh_light_client = LightClient()
    assert fresh_light_client.sync_headers(tampered_headers) is False
    assert fresh_light_client.headers == []  # a failed sync leaves nothing adopted
