"""
Phase 3: peer-to-peer propagation.

Nodes talk to each other over plain HTTP (via `requests`) rather than raw
sockets — simpler to reason about, same underlying idea: broadcast to
every known peer, let each validate independently.
"""

import requests

from blockchain import Block, validate_chain, validate_chain_economics, validate_chain_proof


class PeerRegistry:
    # Phase 16: consecutive broadcast/request failures before a peer is
    # paused. Small on purpose — a genuinely flaky peer should drop out
    # quickly rather than eating a multi-second timeout on every single
    # broadcast for a long time.
    FAILURE_THRESHOLD = 3

    def __init__(self):
        self.peers: set[str] = set()  # every peer ever registered — never forgotten
        self.inactive_peers: set[str] = set()  # a subset of self.peers, currently paused
        self.failure_counts: dict[str, int] = {}  # consecutive failures, per peer

    def register(self, address: str):
        """
        Add address to self.peers. A (re-)register — manual or repeated —
        also reactivates the peer and resets its failure count: treating
        an explicit /nodes/register call as a fresh signal the peer is
        expected to be reachable again, same as a successful response
        would.
        """
        self.peers.add(address)
        self.failure_counts[address] = 0
        self.inactive_peers.discard(address)

    def active_peers(self) -> set:
        """Known peers minus the ones paused for repeated failures — the actual broadcast/request target list."""
        return self.peers - self.inactive_peers

    def _record_success(self, peer: str):
        self.failure_counts[peer] = 0
        self.inactive_peers.discard(peer)

    def _record_failure(self, peer: str):
        self.failure_counts[peer] = self.failure_counts.get(peer, 0) + 1
        if self.failure_counts[peer] >= self.FAILURE_THRESHOLD:
            self.inactive_peers.add(peer)

    def broadcast_transaction(self, transaction: dict):
        """
        POST transaction to /transactions/new on every active peer.
        Done-when: two locally running nodes end up with the same
        pending_transactions after one receives a new transaction.

        A peer being down/unreachable shouldn't block the local add or
        the rest of the broadcast — this is best-effort propagation, not
        a transaction that must atomically land everywhere. Repeated
        failures against the same peer now feed into Phase 16's health
        tracking rather than being silently retried forever.

        Sends broadcast=False so the receiving node adds it locally but
        doesn't re-broadcast: with mutually-registered peers, an
        unconditional rebroadcast on receipt would ping-pong the same
        transaction back and forth forever.
        """
        for peer in self.active_peers():
            try:
                requests.post(
                    f"{peer}/transactions/new",
                    json=transaction,
                    params={"broadcast": False},
                    timeout=5,
                )
                self._record_success(peer)
            except requests.RequestException:
                self._record_failure(peer)
                continue

    def broadcast_block(self, block_dict: dict):
        """
        Notify every active peer a new block was mined, so they can
        validate and either accept it or resolve a fork. Same
        best-effort semantics as broadcast_transaction — an unreachable
        peer just misses this announcement and will catch up later via
        resolve_conflicts(), and repeated failures pause it the same way.

        Sends broadcast=False for the same reason as broadcast_transaction:
        with mutually-registered peers, a receiving node that unconditionally
        rebroadcast an accepted block back out would ping-pong it forever.
        """
        for peer in self.active_peers():
            try:
                requests.post(
                    f"{peer}/blocks/receive",
                    json=block_dict,
                    params={"broadcast": False},
                    timeout=5,
                )
                self._record_success(peer)
            except requests.RequestException:
                self._record_failure(peer)
                continue

    def resolve_conflicts(self, local_chain: list) -> list:
        """
        Fetch /chain from every active peer, and if a longer *valid*
        chain exists, replace local_chain with it. This is the
        longest-chain rule — the actual fork-resolution mechanism.

        Peer chains arrive as plain dicts over HTTP, so they're rebuilt
        into Block objects before validate_chain() can recompute hashes
        over them (compute_hash() is a Block method, not something that
        works on raw dicts).

        Phase 13: a chain that's merely longer and structurally
        self-consistent (validate_chain) is no longer sufficient to
        adopt — validate_chain_economics also has to pass, or a longer
        chain built on forged signatures or a same-block double-spend
        would win purely on length.

        Phase A: neither of those confirms a block was ever actually
        mined (or, for a PoS block, validator-signed) — validate_chain_proof
        also has to pass, or a longer chain with fabricated nonces would
        still win on length alone.
        """
        longest_chain = local_chain
        max_length = len(local_chain)

        for peer in self.active_peers():
            try:
                response = requests.get(f"{peer}/chain", timeout=5)
                response.raise_for_status()
                self._record_success(peer)
            except requests.RequestException:
                self._record_failure(peer)
                continue

            peer_chain = [Block(**block) for block in response.json().get("chain", [])]
            if (
                len(peer_chain) > max_length
                and validate_chain(peer_chain)
                and validate_chain_economics(peer_chain)
                and validate_chain_proof(peer_chain)
            ):
                max_length = len(peer_chain)
                longest_chain = peer_chain

        return longest_chain
