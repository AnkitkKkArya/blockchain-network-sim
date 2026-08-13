"""
Phase 14: light client / SPV (Simplified Payment Verification).

A light client never downloads full blocks — it independently validates
the chain of HEADERS (index, timestamp, previous_hash, nonce,
merkle_root, hash) fetched from a node, then verifies any specific
transaction it cares about against a merkle proof fetched separately.
It never trusts a full node's word about a block's contents; only the
proof math (merkle.verify_merkle_proof) against its own locally-
validated merkle_root.
"""

import hashlib
import json

from merkle import verify_merkle_proof


class LightClient:
    def __init__(self):
        self.headers: list = []  # validated header dicts, index-ordered

    @staticmethod
    def _header_hash(header: dict) -> str:
        """
        Recomputes a header's hash the same way Block.compute_hash() does
        — same field set, same sorted-keys JSON discipline — but from a
        plain header dict with no transaction data in sight.
        """
        block_contents = {
            "index": header["index"],
            "timestamp": header["timestamp"],
            "merkle_root": header["merkle_root"],
            "previous_hash": header["previous_hash"],
            "nonce": header["nonce"],
        }
        block_string = json.dumps(block_contents, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()

    def sync_headers(self, headers: list) -> bool:
        """
        Validates a full header list independently — the same
        self-consistency + linkage logic as Blockchain.is_chain_valid(),
        but header-only: no transaction data is ever fetched or touched.
        Only replaces self.headers if the whole list checks out; a failed
        sync leaves whatever was previously validated in place.
        """
        for i, header in enumerate(headers):
            if header["hash"] != self._header_hash(header):
                return False
            if i > 0 and header["previous_hash"] != headers[i - 1]["hash"]:
                return False
        self.headers = headers
        return True

    def verify_transaction(self, transaction: dict, block_index: int, proof: list) -> bool:
        """
        Confirms `transaction` is really in block `block_index`, using a
        merkle proof obtained separately (e.g. a full node's
        GET /block/{index}/proof) — checked against this light client's
        OWN locally-validated header's merkle_root (from sync_headers),
        never against anything a full node merely claims about a block's
        contents. False for an unknown block_index, a forged proof, or
        a transaction that doesn't match what was actually proven.
        """
        matching = [header for header in self.headers if header["index"] == block_index]
        if not matching:
            return False
        root = matching[0]["merkle_root"]
        return verify_merkle_proof(transaction, proof, root)
