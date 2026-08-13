"""
Phase 11 done-when check: run `pytest` from the project root once
staking, get_active_validators(), select_validator(), and /mine's PoS
branch are implemented.

CONSENSUS_MODE is set via monkeypatch.setenv (per-test, auto-reverted)
rather than changed at module scope, so Phase 1-10 tests keep running
under the default PoW behavior unaffected.
"""

import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from fastapi.testclient import TestClient  # noqa: E402

import app as app_module  # noqa: E402
from blockchain import Blockchain  # noqa: E402
from consensus import select_validator  # noqa: E402
from wallet import Wallet  # noqa: E402


def _fresh_client(initial_balances: dict = None) -> TestClient:
    """
    Same isolation trick as test_mining_economics.py: app.py's
    `blockchain` is a single module-global instance, so swapping it
    directly gives each test an isolated chain.
    """
    app_module.blockchain = Blockchain(initial_balances=initial_balances)
    return TestClient(app_module.app)


def _stake(client: TestClient, wallet: Wallet, amount: float):
    # amount must be a float here, matching how FastAPI parses the query
    # param server-side (Blockchain.stake's `amount: float`) — signing an
    # int (900) vs a float (900.0) produces different JSON, and thus a
    # signature that fails verification against the server's payload.
    amount = float(amount)
    payload = {"from": wallet.public_key_pem, "to": f"STAKE:{wallet.public_key_pem}", "amount": amount}
    signature = wallet.sign_transaction(payload)
    response = client.post(
        "/stake",
        params={"public_key": wallet.public_key_pem, "amount": amount, "signature": signature},
    )
    assert response.status_code == 200, response.text


def _validator_header_signature(wallet: Wallet, index: int, previous_hash: str) -> str:
    header = {"index": index, "previous_hash": previous_hash}
    return wallet.sign_transaction(header)


def test_get_active_validators_reflects_multiple_stakes():
    v1 = Wallet()
    v2 = Wallet()
    miner = Wallet()
    client = _fresh_client(initial_balances={v1.public_key_pem: 1000.0, v2.public_key_pem: 1000.0})

    _stake(client, v1, 900)
    _stake(client, v2, 100)

    # Stakes only count once confirmed on-chain (same rule as /balance) —
    # mine under the default PoW mode to land them.
    response = client.get("/mine", params={"miner_public_key": miner.public_key_pem})
    assert response.status_code == 200

    validators = client.get("/validators").json()
    assert validators == {v1.public_key_pem: 900.0, v2.public_key_pem: 100.0}


def test_select_validator_weighted_by_stake():
    stakes = {"A": 900, "B": 100}
    counts = Counter(select_validator(stakes) for _ in range(1000))

    a_share = counts["A"] / 1000
    assert 0.80 <= a_share <= 0.98, f"expected ~90% for A, got {a_share:.2%}"
    assert counts["B"] > 0


def test_selected_validator_can_mine_pos_block(monkeypatch):
    validator = Wallet()
    bootstrap_miner = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})

    _stake(client, validator, 900)
    # Confirm the stake under PoW first — before CONSENSUS_MODE flips to
    # "pos", since there'd otherwise be no active validator yet to select
    # from (a chicken-and-egg problem: staking itself needs a mined block).
    bootstrap = client.get("/mine", params={"miner_public_key": bootstrap_miner.public_key_pem})
    assert bootstrap.status_code == 200
    assert client.get("/validators").json() == {validator.public_key_pem: 900.0}

    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    bc = app_module.blockchain
    index = bc.last_block.index + 1
    previous_hash = bc.last_block.hash
    signature = _validator_header_signature(validator, index, previous_hash)

    response = client.get(
        "/mine",
        params={"miner_public_key": validator.public_key_pem, "validator_signature": signature},
    )
    assert response.status_code == 200, response.text
    mined_block = response.json()
    assert mined_block["validator_public_key"] == validator.public_key_pem
    assert mined_block["validator_signature"] == signature
    assert mined_block["index"] == index


def test_mine_rejects_unselected_validator(monkeypatch):
    validator = Wallet()
    outsider = Wallet()
    bootstrap_miner = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})

    _stake(client, validator, 900)
    client.get("/mine", params={"miner_public_key": bootstrap_miner.public_key_pem})

    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    bc = app_module.blockchain
    signature = _validator_header_signature(outsider, bc.last_block.index + 1, bc.last_block.hash)

    # `outsider` never staked, so it's not in get_active_validators() at
    # all — select_validator() can only ever return `validator`, making
    # this deterministic (no reliance on random selection landing a
    # particular way).
    response = client.get(
        "/mine",
        params={"miner_public_key": outsider.public_key_pem, "validator_signature": signature},
    )
    assert response.status_code == 403


def test_equivocation_burns_stake_to_zero():
    validator = Wallet()
    bootstrap_miner = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})

    _stake(client, validator, 900)
    client.get("/mine", params={"miner_public_key": bootstrap_miner.public_key_pem})

    bc = app_module.blockchain
    assert bc.get_stake(validator.public_key_pem) == 900.0

    next_index = bc.last_block.index + 1
    first_proposal = bc.record_proposal(validator.public_key_pem, next_index, "hash-a")
    assert first_proposal is False
    assert bc.get_stake(validator.public_key_pem) == 900.0

    second_proposal = bc.record_proposal(validator.public_key_pem, next_index, "hash-b")
    assert second_proposal is True
    assert bc.get_stake(validator.public_key_pem) == 0.0
