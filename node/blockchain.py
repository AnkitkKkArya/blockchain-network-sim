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
    # Phase 11: set only for PoS-mined blocks (the validator that signed
    # this block, and its signature over the block's header). None for
    # every PoW block, including all Phase 1-10 blocks/tests — neither
    # field is part of compute_hash()'s payload, so adding them here
    # doesn't change any existing block's hash.
    validator_public_key: str = None
    validator_signature: str = None

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
    BLOCK_REWARD = 10.0
    MAX_TRANSACTIONS_PER_BLOCK = 3  # small on purpose, so prioritization is easy to observe/test
    TARGET_BLOCK_TIME = 2  # seconds
    ADJUSTMENT_INTERVAL = 5  # blocks
    BURN_ADDRESS = "BURNED"  # Phase 11: slashed stake lands here, unspendable by anyone

    def __init__(self, initial_balances: dict = None):
        self.chain: list[Block] = []
        self.pending_transactions: list = []
        # Phase 10: an instance attribute, not a class attribute — each
        # Blockchain adjusts its own difficulty based on its own mining
        # pace, and a class attribute would leak one instance's adjustment
        # onto every other instance sharing the class (e.g. across tests).
        self.difficulty = 4  # leading zeros required — used from Phase 4 onward
        # Phase 11: every validator block proposal ever seen (accepted
        # onto this chain or not), keyed by (validator_public_key, index).
        # This is what equivocation detection compares against — a
        # validator signing two different blocks at the same index is
        # only visible here, not in self.chain, since at most one of the
        # two ever lands on any given node's chain.
        self.validator_proposals: dict = {}
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

    def stake(self, validator_public_key: str, amount: float, signature: str):
        """
        Phase 11: staking is a real, signature-verified spend from
        validator_public_key to the synthetic address
        f"STAKE:{validator_public_key}" — going through add_transaction()'s
        normal signature/balance checks means becoming a validator costs
        something and can't be forged, same as any other transfer. Like
        any transaction, this only lands in the mempool; it isn't counted
        by get_stake()/get_active_validators() (confirmed-chain-only,
        same rule as get_balance()) until a block including it is mined.
        """
        transaction = {
            "from": validator_public_key,
            "to": f"STAKE:{validator_public_key}",
            "amount": amount,
            "sender_public_key": validator_public_key,
            "signature": signature,
        }
        self.add_transaction(transaction)

    def get_stake(self, validator_public_key: str) -> float:
        return self.get_balance(f"STAKE:{validator_public_key}")

    def get_active_validators(self) -> dict:
        """
        Every public key that ever self-staked (sent a transaction to its
        own f"STAKE:{...}" address), mapped to its current stake, filtered
        to stake > 0 — so a validator slashed down to nothing drops out
        without needing separate bookkeeping.
        """
        validators = set()
        for block in self.chain:
            for transaction in block.transactions:
                sender = transaction.get("from")
                if sender and transaction.get("to") == f"STAKE:{sender}":
                    validators.add(sender)
        return {v: self.get_stake(v) for v in validators if self.get_stake(v) > 0}

    def slash(self, validator_public_key: str):
        """
        Burns a validator's entire current stake by minting a transaction
        from its f"STAKE:{...}" address to BURN_ADDRESS directly into a new
        block, the same way genesis mints GENESIS transactions directly
        rather than through add_transaction(): there's no private key for
        a "STAKE:<pubkey>" address to authorize a withdrawal with, and
        this is a protocol-level penalty the validator never agrees to,
        not a transfer it signs. It has to land on-chain immediately
        (not the mempool) since get_stake() only reads confirmed balance.
        """
        stake_address = f"STAKE:{validator_public_key}"
        amount = self.get_balance(stake_address)
        if amount <= 0:
            return
        burn_transaction = {"from": stake_address, "to": self.BURN_ADDRESS, "amount": amount}
        block = Block(
            index=self.last_block.index + 1,
            timestamp=time.time(),
            transactions=[burn_transaction],
            previous_hash=self.last_block.hash,
        )
        block.hash = block.compute_hash()
        self.add_block(block)

    def record_proposal(self, validator_public_key: str, index: int, block_hash: str) -> bool:
        """
        Records a validator's block proposal at a given index, and
        returns True iff this call just revealed equivocation (slashing
        the validator as a side effect). Tracking every proposal seen —
        not just ones that land on this node's own chain — is what
        catches a validator handing two different blocks for the same
        index to two different peers, even though at most one of those
        blocks is ever accepted by any single node.
        """
        key = (validator_public_key, index)
        seen_hash = self.validator_proposals.get(key)
        if seen_hash is not None and seen_hash != block_hash:
            self.slash(validator_public_key)
            return True
        self.validator_proposals[key] = block_hash
        return False

    def add_block(self, block: Block) -> None:
        """
        Append a block the caller has already validated — proof-of-work
        checked (consensus.is_valid_proof) and linkage checked against
        last_block.hash. This method's only job is committing it to the
        chain; deciding whether a block is acceptable is a separate
        concern the caller (app.py's /mine and /blocks/receive) owns,
        same way is_chain_valid() stays pure validation with no mutation.

        adjust_difficulty() runs here rather than being called separately
        by each caller, since this is the one place every accepted block
        (mined locally or received from a peer) actually lands on the chain.
        """
        self.chain.append(block)
        self.adjust_difficulty()

    def adjust_difficulty(self):
        """
        Phase 10: every ADJUSTMENT_INTERVAL blocks, compare how long that
        window actually took against TARGET_BLOCK_TIME * ADJUSTMENT_INTERVAL,
        and nudge difficulty up (mining too fast) or down (too slow, floored
        at 1) accordingly. Left unchanged if elapsed time is within 2x of
        target in either direction — small variance is expected noise, not
        a signal to react to.

        The window's lower bound is deliberately excluded when it's genesis
        (index 0): genesis's timestamp is hardcoded to 0 (see
        create_genesis_block), not a real wall-clock moment, so using it in
        an elapsed-time calculation would produce a huge, meaningless
        "elapsed" and spuriously ratchet difficulty up on the very first
        adjustment window.
        """
        chain_length = len(self.chain)
        if chain_length % self.ADJUSTMENT_INTERVAL != 0:
            return
        if chain_length <= self.ADJUSTMENT_INTERVAL:
            return

        window_start = self.chain[-1 - self.ADJUSTMENT_INTERVAL]
        if window_start.index == 0:
            return

        elapsed = self.chain[-1].timestamp - window_start.timestamp
        target = self.TARGET_BLOCK_TIME * self.ADJUSTMENT_INTERVAL
        if elapsed < target / 2:
            self.difficulty += 1
        elif elapsed > target * 2:
            self.difficulty = max(1, self.difficulty - 1)

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
