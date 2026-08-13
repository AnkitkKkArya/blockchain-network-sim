"""
Phase 6 done-when check: run `pytest` from the project root.

The point isn't just "does a valid signature verify" — it's that
signing binds the transaction's *content*. A signature that still
verified after the amount changed would mean signing only proved
identity once, not integrity of what was actually agreed to.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "node"))

from wallet import Wallet, verify_signature  # noqa: E402


def test_valid_signature_verifies():
    wallet = Wallet()
    transaction = {"from": "alice", "to": "bob", "amount": 10}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    transaction["signature"] = signature

    assert verify_signature(transaction, signature, wallet.public_key_pem)


def test_mutated_transaction_fails_verification():
    wallet = Wallet()
    transaction = {"from": "alice", "to": "bob", "amount": 10}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    transaction["signature"] = signature

    transaction["amount"] = 10_000  # attacker mutates after signing

    assert not verify_signature(transaction, signature, wallet.public_key_pem)


def test_signature_from_wrong_wallet_fails_verification():
    wallet = Wallet()
    impostor = Wallet()
    transaction = {"from": "alice", "to": "bob", "amount": 10}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = impostor.public_key_pem
    transaction["signature"] = signature

    assert not verify_signature(transaction, signature, impostor.public_key_pem)


if __name__ == "__main__":
    # CLI-style walkthrough, runnable directly with `python tests/test_wallet.py`.
    wallet = Wallet()
    transaction = {"from": "alice", "to": "bob", "amount": 10}
    signature = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    transaction["signature"] = signature

    print("Generated wallet, public key (PEM):")
    print(wallet.public_key_pem)
    print(f"Signed transaction: {transaction}")
    print(f"verify_signature() on the untouched transaction: "
          f"{verify_signature(transaction, signature, wallet.public_key_pem)}")

    transaction["amount"] = 9999
    print(f"verify_signature() after mutating amount to {transaction['amount']}: "
          f"{verify_signature(transaction, signature, wallet.public_key_pem)}")
