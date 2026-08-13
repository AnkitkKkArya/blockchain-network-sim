"""
Phase 8 done-when check: run `pytest` from the project root once
merkle.py is implemented.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from merkle import merkle_root, merkle_proof, verify_merkle_proof  # noqa: E402


def _transactions(n: int) -> list:
    return [{"from": f"A{i}", "to": f"B{i}", "amount": i} for i in range(n)]


def test_merkle_root_is_deterministic():
    transactions = _transactions(4)
    assert merkle_root(transactions) == merkle_root(transactions)


def test_changing_one_transaction_changes_root():
    transactions = _transactions(4)
    original_root = merkle_root(transactions)

    mutated = [dict(tx) for tx in transactions]
    mutated[2]["amount"] = 9999

    assert merkle_root(mutated) != original_root


def test_merkle_proof_verifies_against_real_root():
    transactions = _transactions(4)
    root = merkle_root(transactions)

    proof = merkle_proof(transactions, 2)
    assert verify_merkle_proof(transactions[2], proof, root)


def test_merkle_proof_fails_on_tampering():
    transactions = _transactions(4)
    root = merkle_root(transactions)
    proof = merkle_proof(transactions, 2)

    tampered_transaction = dict(transactions[2])
    tampered_transaction["amount"] = 9999
    assert not verify_merkle_proof(tampered_transaction, proof, root)

    tampered_proof = list(proof)
    side, sibling_hash = tampered_proof[0]
    tampered_proof[0] = (side, "0" * len(sibling_hash))
    assert not verify_merkle_proof(transactions[2], tampered_proof, root)


def test_odd_number_of_transactions():
    transactions = _transactions(5)
    root = merkle_root(transactions)

    for index in range(len(transactions)):
        proof = merkle_proof(transactions, index)
        assert verify_merkle_proof(transactions[index], proof, root)

    mutated = [dict(tx) for tx in transactions]
    mutated[4]["amount"] = 9999
    assert merkle_root(mutated) != root
