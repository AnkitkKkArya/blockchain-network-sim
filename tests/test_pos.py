"""
Phase 11 done-when check (staking, get_active_validators(),
select_validator()), updated for Phase B's two-step PoS mining flow
(GET /mine/propose, POST /mine/submit).

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
from merkle import merkle_root as compute_merkle_root  # noqa: E402
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


def _bootstrap_staked_validator(client: TestClient, validator: Wallet, stake_amount: float = 900):
    """Stakes and confirms `validator` under PoW, before any CONSENSUS_MODE=pos switch — staking itself needs a mined block, so there'd otherwise be no active validator yet to select from."""
    bootstrap_miner = Wallet()
    _stake(client, validator, stake_amount)
    response = client.get("/mine", params={"miner_public_key": bootstrap_miner.public_key_pem})
    assert response.status_code == 200


def _sign_header(wallet: Wallet, index: int, previous_hash: str, merkle_root_value: str) -> str:
    header = {"index": index, "previous_hash": previous_hash, "merkle_root": merkle_root_value}
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


def test_selected_validator_can_mine_pos_block_via_propose_then_submit(monkeypatch):
    validator = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})
    _bootstrap_staked_validator(client, validator)
    assert client.get("/validators").json() == {validator.public_key_pem: 900.0}

    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    propose = client.get("/mine/propose", params={"miner_public_key": validator.public_key_pem})
    assert propose.status_code == 200, propose.text
    candidate = propose.json()
    assert set(candidate.keys()) == {"index", "previous_hash", "merkle_root", "transactions"}

    signature = _sign_header(validator, candidate["index"], candidate["previous_hash"], candidate["merkle_root"])
    submit = client.post(
        "/mine/submit",
        json={
            **candidate,
            "validator_signature": signature,
            "miner_public_key": validator.public_key_pem,
        },
    )
    assert submit.status_code == 200, submit.text
    mined_block = submit.json()
    assert mined_block["validator_public_key"] == validator.public_key_pem
    assert mined_block["validator_signature"] == signature
    assert mined_block["index"] == candidate["index"]
    assert mined_block["merkle_root"] == candidate["merkle_root"]


def test_mine_propose_rejects_unselected_validator(monkeypatch):
    validator = Wallet()
    outsider = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})
    _bootstrap_staked_validator(client, validator)

    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    # `outsider` never staked, so it's not in get_active_validators() at
    # all — select_validator() can only ever return `validator`, making
    # this deterministic (no reliance on random selection landing a
    # particular way).
    response = client.get("/mine/propose", params={"miner_public_key": outsider.public_key_pem})
    assert response.status_code == 403


def test_mine_is_pow_only_and_rejects_pos_mode(monkeypatch):
    miner = Wallet()
    client = _fresh_client()
    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    response = client.get("/mine", params={"miner_public_key": miner.public_key_pem})
    assert response.status_code == 400
    assert "/mine/propose" in response.json()["detail"]


def test_mine_submit_rejects_transactions_not_matching_claimed_merkle_root(monkeypatch):
    validator = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})
    _bootstrap_staked_validator(client, validator)
    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    candidate = client.get("/mine/propose", params={"miner_public_key": validator.public_key_pem}).json()
    signature = _sign_header(validator, candidate["index"], candidate["previous_hash"], candidate["merkle_root"])

    # Tamper with the transactions after signing, leaving merkle_root as
    # the original (now-mismatched) value — exactly what the old
    # single-call design couldn't catch, since it never signed content.
    tampered = dict(candidate)
    tampered["transactions"] = tampered["transactions"] + [
        {"from": "COINBASE", "to": validator.public_key_pem, "amount": 99999}
    ]

    submit = client.post(
        "/mine/submit",
        json={**tampered, "validator_signature": signature, "miner_public_key": validator.public_key_pem},
    )
    assert submit.status_code == 400
    assert "merkle_root" in submit.json()["detail"]


def test_mine_submit_rejects_economically_invalid_transactions(monkeypatch):
    validator = Wallet()
    attacker = Wallet()  # never funded anywhere on this chain
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})
    _bootstrap_staked_validator(client, validator)
    monkeypatch.setenv("CONSENSUS_MODE", "pos")

    bc = app_module.blockchain
    index = bc.last_block.index + 1
    previous_hash = bc.last_block.hash

    overspend = {"from": attacker.public_key_pem, "to": validator.public_key_pem, "amount": 5000, "fee": 0}
    overspend["signature"] = attacker.sign_transaction(overspend)
    overspend["sender_public_key"] = attacker.public_key_pem
    coinbase = {"from": "COINBASE", "to": validator.public_key_pem, "amount": Blockchain.BLOCK_REWARD}
    transactions = [overspend, coinbase]
    merkle_root_value = compute_merkle_root(transactions)

    # Honestly signed over the real (matching) merkle_root — only the
    # transaction content itself is invalid, proving step 5's
    # validate_block_economics() call is real, not decorative.
    signature = _sign_header(validator, index, previous_hash, merkle_root_value)

    submit = client.post(
        "/mine/submit",
        json={
            "index": index,
            "previous_hash": previous_hash,
            "merkle_root": merkle_root_value,
            "transactions": transactions,
            "validator_signature": signature,
            "miner_public_key": validator.public_key_pem,
        },
    )
    assert submit.status_code == 400
    assert "economic" in submit.json()["detail"].lower()


def test_equivocation_burns_stake_to_zero():
    validator = Wallet()
    client = _fresh_client(initial_balances={validator.public_key_pem: 1000.0})
    _bootstrap_staked_validator(client, validator)

    bc = app_module.blockchain
    assert bc.get_stake(validator.public_key_pem) == 900.0

    next_index = bc.last_block.index + 1
    first_proposal = bc.record_proposal(validator.public_key_pem, next_index, "hash-a")
    assert first_proposal is False
    assert bc.get_stake(validator.public_key_pem) == 900.0

    second_proposal = bc.record_proposal(validator.public_key_pem, next_index, "hash-b")
    assert second_proposal is True
    assert bc.get_stake(validator.public_key_pem) == 0.0
