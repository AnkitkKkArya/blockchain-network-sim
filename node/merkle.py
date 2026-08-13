"""
Phase 8: Merkle trees.

A block's compute_hash() used to hash the raw transactions list
directly. That works, but it means proving "transaction X is in this
block" requires handing over every other transaction too, so the
verifier can re-serialize the whole list and check the hash. A Merkle
root lets a verifier check membership of one transaction against a
handful of sibling hashes (merkle_proof) instead — same tamper-evidence
guarantee, much smaller proof.
"""

import hashlib
import json


def _hash_transaction(transaction: dict) -> str:
    """
    Same sorted-keys JSON discipline as Block.compute_hash() and
    wallet._signing_payload(): both sides (building the tree, verifying
    a proof) must serialize identically or hashes silently diverge.
    """
    payload = json.dumps(transaction, sort_keys=True).encode()
    return hashlib.sha256(payload).hexdigest()


def _hash_pair(left: str, right: str) -> str:
    return hashlib.sha256((left + right).encode()).hexdigest()


def merkle_root(transactions: list) -> str:
    """
    Leaves are SHA-256 of each transaction; each level up pairs adjacent
    hashes and hashes their concatenation, until one hash remains. An odd
    node at any level is paired with itself (standard Bitcoin-style fix)
    rather than left unpaired, which would otherwise mean forking the
    tree's shape by leaf count instead of by pairing.

    An empty transaction list has no leaves to hash, so it's handled
    explicitly as the hash of an empty string — genesis blocks, and any
    block mined from an empty mempool, need this to not crash.
    """
    if not transactions:
        return hashlib.sha256(b"").hexdigest()

    level = [_hash_transaction(tx) for tx in transactions]
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def merkle_proof(transactions: list, index: int) -> list:
    """
    The sibling hash at each level needed to walk transactions[index]'s
    leaf hash back up to the root, tagged "left"/"right" for which side
    of the pairing the sibling sits on — verify_merkle_proof needs that
    to concatenate (sibling, node) or (node, sibling) in the right order,
    since _hash_pair isn't commutative.
    """
    level = [_hash_transaction(tx) for tx in transactions]
    proof = []
    while len(level) > 1:
        if len(level) % 2 == 1:
            level.append(level[-1])
        if index % 2 == 0:
            sibling_index = index + 1
            side = "right"
        else:
            sibling_index = index - 1
            side = "left"
        proof.append((side, level[sibling_index]))
        level = [_hash_pair(level[i], level[i + 1]) for i in range(0, len(level), 2)]
        index //= 2
    return proof


def verify_merkle_proof(transaction: dict, proof: list, root: str) -> bool:
    """
    Recompute the root by walking the transaction's own leaf hash up
    through the proof's siblings, and compare to the claimed root.
    """
    current = _hash_transaction(transaction)
    for side, sibling_hash in proof:
        if side == "right":
            current = _hash_pair(current, sibling_hash)
        else:
            current = _hash_pair(sibling_hash, current)
    return current == root
