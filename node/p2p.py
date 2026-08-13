"""
Phase 3: peer-to-peer propagation.

Nodes talk to each other over plain HTTP (via `requests`) rather than raw
sockets — simpler to reason about, same underlying idea: broadcast to
every known peer, let each validate independently.
"""

import requests

from blockchain import Block, validate_chain, validate_chain_economics


class PeerRegistry:
    def __init__(self):
        self.peers: set[str] = set()  # e.g. {"http://node2:5000"}

    def register(self, address: str):
        """Add address to self.peers."""
        self.peers.add(address)

    def broadcast_transaction(self, transaction: dict):
        """
        POST transaction to /transactions/new on every peer.
        Done-when: two locally running nodes end up with the same
        pending_transactions after one receives a new transaction.

        A peer being down/unreachable shouldn't block the local add or
        the rest of the broadcast — this is best-effort propagation, not
        a transaction that must atomically land everywhere.

        Sends broadcast=False so the receiving node adds it locally but
        doesn't re-broadcast: with mutually-registered peers, an
        unconditional rebroadcast on receipt would ping-pong the same
        transaction back and forth forever.
        """
        for peer in self.peers:
            try:
                requests.post(
                    f"{peer}/transactions/new",
                    json=transaction,
                    params={"broadcast": False},
                    timeout=5,
                )
            except requests.RequestException:
                continue

    def broadcast_block(self, block_dict: dict):
        """
        Notify every peer a new block was mined, so they can validate and
        either accept it or resolve a fork. Same best-effort semantics as
        broadcast_transaction — an unreachable peer just misses this
        announcement and will catch up later via resolve_conflicts().

        Sends broadcast=False for the same reason as broadcast_transaction:
        with mutually-registered peers, a receiving node that unconditionally
        rebroadcast an accepted block back out would ping-pong it forever.
        """
        for peer in self.peers:
            try:
                requests.post(
                    f"{peer}/blocks/receive",
                    json=block_dict,
                    params={"broadcast": False},
                    timeout=5,
                )
            except requests.RequestException:
                continue

    def resolve_conflicts(self, local_chain: list) -> list:
        """
        Fetch /chain from every peer, and if a longer *valid* chain
        exists, replace local_chain with it. This is the longest-chain
        rule — the actual fork-resolution mechanism.

        Peer chains arrive as plain dicts over HTTP, so they're rebuilt
        into Block objects before validate_chain() can recompute hashes
        over them (compute_hash() is a Block method, not something that
        works on raw dicts).

        Phase 13: a chain that's merely longer and structurally
        self-consistent (validate_chain) is no longer sufficient to
        adopt — validate_chain_economics also has to pass, or a longer
        chain built on forged signatures or a same-block double-spend
        would win purely on length.
        """
        longest_chain = local_chain
        max_length = len(local_chain)

        for peer in self.peers:
            try:
                response = requests.get(f"{peer}/chain", timeout=5)
                response.raise_for_status()
            except requests.RequestException:
                continue

            peer_chain = [Block(**block) for block in response.json().get("chain", [])]
            if (
                len(peer_chain) > max_length
                and validate_chain(peer_chain)
                and validate_chain_economics(peer_chain)
            ):
                max_length = len(peer_chain)
                longest_chain = peer_chain

        return longest_chain
