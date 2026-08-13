"""
Phase 1: Core chain logic.

Build this first, with no networking involved. Get it fully correct
and unit-tested before moving to app.py (Phase 2).
"""

import hashlib
import json
import time
from dataclasses import dataclass, field

from merkle import merkle_root
from wallet import verify_signature


@dataclass
class Block:
    index: int
    timestamp: float
    transactions: list
    previous_hash: str
    nonce: int = 0
    hash: str = field(default="")

    def compute_hash(self) -> str:
        """
        Hash the block's contents (excluding any hash field itself).
        Serialize index, timestamp, previous_hash, nonce deterministically
        (sorted keys!) and return the SHA-256 hex digest.

        Phase 8: transactions are folded in via merkle_root(transactions)
        rather than the raw list. Same tamper-evidence as before (any
        transaction change still changes this hash), but it's what lets
        merkle_proof/verify_merkle_proof prove one transaction's presence
        without needing the whole block.
        """
        block_contents = {
            "index": self.index,
            "timestamp": self.timestamp,
            "merkle_root": merkle_root(self.transactions),
            "previous_hash": self.previous_hash,
            "nonce": self.nonce,
        }
        block_string = json.dumps(block_contents, sort_keys=True)
        return hashlib.sha256(block_string.encode()).hexdigest()


class Blockchain:
    difficulty = 4  # leading zeros required — used from Phase 4 onward
    BLOCK_REWARD = 10.0
    MAX_TRANSACTIONS_PER_BLOCK = 3  # small on purpose, so prioritization is easy to observe/test

    def __init__(self, initial_balances: dict = None):
        self.chain: list[Block] = []
        self.pending_transactions: list = []
        self.create_genesis_block(initial_balances)

    def create_genesis_block(self, initial_balances: dict = None):
        """
        The genesis block is the chain's root of trust: it has no real
        predecessor, so previous_hash is the sentinel '0' by convention.
        We still compute and store its hash like any other block, so
        is_chain_valid() can treat block 0 uniformly with the rest —
        no special-casing "is this the first block" beyond skipping the
        previous_hash-link check.

        Phase 7: initial_balances (public_key_pem -> amount) is minted
        directly into the genesis block as one "GENESIS"-sender
        transaction per entry. These never go through add_transaction(),
        so they never touch verify_signature() — there's no private key
        to sign with for a mint, and none is needed since this is chain
        setup, not a transfer someone could forge.

        timestamp is hardcoded to 0 rather than time.time(): genesis
        isn't a real event that happened at some wall-clock moment, it's
        a fixed root every node constructs independently. Every other
        block still timestamps itself for real — this is block 0 only,
        so two nodes given the same initial_balances produce byte-identical
        genesis blocks (and therefore hashes) no matter when each process
        actually started.
        """
        transactions = []
        for public_key, amount in (initial_balances or {}).items():
            transactions.append({"from": "GENESIS", "to": public_key, "amount": amount})
        genesis = Block(index=0, timestamp=0, transactions=transactions, previous_hash="0")
        genesis.hash = genesis.compute_hash()
        self.chain.append(genesis)

    @property
    def last_block(self) -> Block:
        return self.chain[-1]

    def add_transaction(self, transaction: dict):
        """
        Transactions are only *proposed* here — they sit in the mempool
        (pending_transactions) until a block is mined (Phase 4) and they
        get bundled into a Block's immutable transactions list. Keeping
        this step separate from block creation mirrors real chains: the
        mempool is mutable/unordered, the chain is not.

        Phase 6: a transaction is rejected (raises ValueError) unless it
        verifies against its own claimed sender_public_key. This is the
        mempool gate — the only place unsigned/forged transactions get a
        chance to be turned away, since once something is in the mempool
        it's eligible to be mined into a block. Note this only proves
        "the sender authorized this exact transaction", not "the sender
        can actually afford it" — balance checking is Phase 7.
        """
        sender_public_key = transaction.get("sender_public_key")
        signature = transaction.get("signature")
        if not sender_public_key or not signature:
            raise ValueError("Transaction is missing sender_public_key or signature")
        if not verify_signature(transaction, signature, sender_public_key):
            raise ValueError("Transaction signature does not verify")
        amount = transaction.get("amount", 0)
        fee = transaction.get("fee", 0)
        if amount + fee > self.get_balance(sender_public_key):
            raise ValueError("Transaction amount exceeds sender's balance")
        self.pending_transactions.append(transaction)

    def get_balance(self, public_key: str) -> float:
        """
        Confirmed chain balance only — self.pending_transactions is
        deliberately excluded, so a wallet can't spend the same funds
        twice by having two not-yet-mined transactions both pass this
        check before either lands in a block.

        Phase 9: a spend debits (amount + fee), since the fee leaves the
        sender's balance same as the amount does. Fees aren't credited
        anywhere here — a miner's fee income is folded into that block's
        single COINBASE transaction (see app.py's /mine), so crediting
        `to` normally already accounts for it. That sidesteps get_balance()
        ever needing to know which address mined which block.
        """
        balance = 0.0
        for block in self.chain:
            for transaction in block.transactions:
                if transaction.get("to") == public_key:
                    balance += transaction.get("amount", 0)
                sender = transaction.get("from")
                if sender == public_key and sender not in ("GENESIS", "COINBASE"):
                    balance -= transaction.get("amount", 0) + transaction.get("fee", 0)
        return balance

    def add_block(self, block: Block) -> None:
        """
        Append a block the caller has already validated — proof-of-work
        checked (consensus.is_valid_proof) and linkage checked against
        last_block.hash. This method's only job is committing it to the
        chain; deciding whether a block is acceptable is a separate
        concern the caller (app.py's /mine and /blocks/receive) owns,
        same way is_chain_valid() stays pure validation with no mutation.
        """
        self.chain.append(block)

    def is_chain_valid(self, chain: list[Block] = None) -> bool:
        """
        Tamper evidence comes from two independent checks per block:

        1. Self-consistency: the block's stored `hash` must equal a fresh
           compute_hash() over its own fields. If anyone mutates a block's
           transactions/nonce/etc. after the fact, the stored hash goes
           stale and this catches it directly.

        2. Chain-linkage: each block's `previous_hash` must equal the
           actual hash of the block before it. This is what turns a list
           of blocks into a *chain* — you can't silently splice out or
           reorder a block without breaking the link to its neighbor.

        Together these mean tampering with block N is detectable either
        at block N itself (check 1) or, if the attacker also patches N's
        stored hash, at block N+1's previous_hash link (check 2) — unless
        every subsequent block is re-hashed too, which is the whole point
        of proof-of-work costing something (Phase 4).
        """
        chain = self.chain if chain is None else chain
        for i, block in enumerate(chain):
            if block.hash != block.compute_hash():
                return False
            if i > 0 and block.previous_hash != chain[i - 1].hash:
                return False
        return True


def validate_chain(chain: list) -> bool:
    """
    Thin wrapper around Blockchain.is_chain_valid() for callers (p2p.py)
    that have a candidate chain but no live Blockchain instance to call
    the instance method on — e.g. validating a peer's chain during
    resolve_conflicts(), before deciding whether to adopt it.
    """
    return Blockchain().is_chain_valid(chain)
