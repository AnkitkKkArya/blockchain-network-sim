"""
Phase 6: transaction signing.

Uses the `cryptography` package's `ec` module (ECDSA over SECP256K1 —
the same curve Bitcoin and Ethereum use) rather than the `ecdsa`
package, since `cryptography` is the more actively maintained,
audited implementation and this project doesn't need anything the
lighter-weight `ecdsa` package would save us.

A signature proves two things at once: that the sender holds the
private key for sender_public_key (identity), and that these exact
transaction contents are what got signed (integrity). Phase 1's
Block.compute_hash()/is_chain_valid() do the equivalent job for
blocks — this is the same idea one level down, at the transaction
level, before a transaction ever reaches a block.
"""

import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec


def _signing_payload(transaction: dict) -> bytes:
    """
    The bytes a signature actually covers: every transaction field
    except `signature` and `sender_public_key` themselves. Excluding
    those two isn't a security hole — swapping in a different
    sender_public_key without the matching private key still fails
    verification, since the signature is mathematically tied to one
    specific key pair — it just keeps "what was signed" and "who/how
    it's attached" cleanly separate, and keeps sign/verify using
    identical serialization (sorted keys, same as Block.compute_hash())
    so both sides agree on what "this transaction's content" means.
    """
    core = {k: v for k, v in transaction.items() if k not in ("signature", "sender_public_key")}
    return json.dumps(core, sort_keys=True).encode()


class Wallet:
    def __init__(self):
        self._private_key = ec.generate_private_key(ec.SECP256K1())
        self.public_key = self._private_key.public_key()

    @property
    def public_key_pem(self) -> str:
        """
        PEM text is what actually travels inside a transaction's
        sender_public_key field — JSON has no native way to carry a
        cryptography key object, so it has to be a string.
        """
        return self.public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        ).decode()

    @property
    def private_key_pem(self) -> str:
        """
        Phase 18: lets a wallet be saved to disk and reloaded later (the
        CLI wallet tool's `generate` + every other subcommand) — nothing
        before this phase needed a wallet to outlive one process. No
        password/encryption on the PEM: this project's "private keys"
        are already throwaway/local-dev-only (see docker-compose.yml's
        seed wallet), not something meant to protect real value.
        """
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ).decode()

    @classmethod
    def from_private_key_pem(cls, pem: str) -> "Wallet":
        """Reconstructs a Wallet from private_key_pem's output — the CLI's load path."""
        wallet = cls.__new__(cls)
        wallet._private_key = serialization.load_pem_private_key(pem.encode(), password=None)
        wallet.public_key = wallet._private_key.public_key()
        return wallet

    def sign_transaction(self, transaction: dict) -> str:
        """
        Sign the transaction's content with this wallet's private key.
        Returns a hex string (not raw bytes) so it drops straight into
        a JSON transaction dict as the "signature" field.
        """
        payload = _signing_payload(transaction)
        signature = self._private_key.sign(payload, ec.ECDSA(hashes.SHA256()))
        return signature.hex()


def verify_signature(transaction: dict, signature: str, public_key) -> bool:
    """
    True iff `signature` is a valid ECDSA signature, over this exact
    transaction's content, by the holder of `public_key`.

    `public_key` may be a PEM string (as stored in a transaction's
    sender_public_key field) or an already-loaded
    EllipticCurvePublicKey, so callers can pass either the raw
    transaction field or a key they already have in hand.

    Returns False rather than raising for any failure mode — malformed
    hex, a mismatched key, a mutated payload — because callers
    (blockchain.add_transaction) just need a yes/no on "is this
    transaction acceptable", not to handle a grab-bag of exception
    types individually.
    """
    try:
        if isinstance(public_key, str):
            public_key = serialization.load_pem_public_key(public_key.encode())
        payload = _signing_payload(transaction)
        public_key.verify(bytes.fromhex(signature), payload, ec.ECDSA(hashes.SHA256()))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False
