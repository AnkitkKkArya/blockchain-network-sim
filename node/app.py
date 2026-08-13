"""
Phase 2: wrap the chain logic in a node API.

Each running instance of this file (or container, from Phase 5) is one
network node. Get this working with a single node first — no peers yet.
"""

import json
import os
import time
from dataclasses import asdict

from fastapi import FastAPI, HTTPException
from blockchain import Block, Blockchain
from consensus import is_valid_proof, proof_of_work, select_validator
from merkle import merkle_proof
from p2p import PeerRegistry
from wallet import verify_signature

app = FastAPI()

# Phase 7/8 prep: every node in a network must start from the same
# genesis block, or their chains fork from block 0 and nothing else
# (peering, longest-chain resolution) can bring them back in sync.
# INITIAL_BALANCES (a JSON object string) lets docker-compose hand
# every container the exact same seed data so their genesis blocks
# match. Unset means {} — an empty genesis, matching current test
# behavior/local single-node dev.
initial_balances = json.loads(os.environ.get("INITIAL_BALANCES", "{}"))

# Phase 15: CHAIN_STORAGE_PATH opts a node into surviving restarts/
# container recreation. Unset (the default, and every existing test's
# behavior) means purely in-memory, unchanged from before this phase.
# Set but the file doesn't exist yet (first boot) means build fresh
# from INITIAL_BALANCES same as always, then save immediately so a
# crash one block later still has genesis to fall back to.
CHAIN_STORAGE_PATH = os.environ.get("CHAIN_STORAGE_PATH")
if CHAIN_STORAGE_PATH and os.path.exists(CHAIN_STORAGE_PATH):
    blockchain = Blockchain.load_from_disk(CHAIN_STORAGE_PATH)
else:
    blockchain = Blockchain(initial_balances=initial_balances)
    if CHAIN_STORAGE_PATH:
        blockchain.save_to_disk(CHAIN_STORAGE_PATH)

registry = PeerRegistry()


def persist_chain():
    """Called after every point the chain actually changes (mine, receive, resolve)."""
    if CHAIN_STORAGE_PATH:
        blockchain.save_to_disk(CHAIN_STORAGE_PATH)


@app.on_event("startup")
def register_seed_peers():
    """
    Phase 5: in Docker, nodes don't know each other's addresses ahead of
    time the way local dev's manual /nodes/register curls assumed —
    docker-compose.yml sets SEED_PEERS per-container instead (container
    names resolve via Docker's embedded DNS on the shared network).
    Reading it here at startup replaces those manual calls with
    something that happens automatically as each container comes up.

    Silently skipping when unset (rather than erroring) is deliberate:
    a bare `uvicorn app:app` for local dev has no SEED_PEERS, and that's
    a normal, expected way to run a single unpeered node, not a
    misconfiguration.
    """
    seed_peers = os.environ.get("SEED_PEERS", "")
    for peer in seed_peers.split(","):
        peer = peer.strip()
        if peer:
            registry.register(peer)


@app.get("/chain")
def get_chain():
    """
    Done-when: curl localhost:5000/chain returns the current chain as JSON.
    """
    return {
        "chain": [asdict(block) for block in blockchain.chain],
        "length": len(blockchain.chain),
    }


@app.post("/transactions/new")
def new_transaction(transaction: dict, broadcast: bool = True):
    """
    Add locally first, then broadcast. That order matters: if broadcasting
    were first and the local add failed, peers would end up with a
    transaction this node itself never recorded.

    broadcast=False is used internally by PeerRegistry when relaying a
    transaction it received from a peer, so propagation stops after one
    hop instead of bouncing between mutually-registered peers forever.
    A real client submitting a new transaction always leaves it at the
    default True.

    Phase 6: a bad signature raises ValueError from add_transaction(),
    which becomes a 400 here — the client finds out immediately rather
    than the transaction silently vanishing (or worse, silently sitting
    in the mempool unsigned).
    """
    try:
        blockchain.add_transaction(transaction)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if broadcast:
        registry.broadcast_transaction(transaction)
    return {"message": "Transaction added to mempool"}


@app.get("/mempool")
def get_mempool():
    """
    Manual-verification-only endpoint for this phase: lets you curl two
    nodes and confirm broadcast_transaction() actually left them with
    matching pending_transactions.
    """
    return {"pending_transactions": blockchain.pending_transactions}


@app.get("/balance")
def get_balance(public_key: str):
    """
    Phase 7: confirmed chain balance only (mempool-pending spends are not
    reflected — see Blockchain.get_balance). public_key is a PEM string,
    which contains newlines and isn't a clean path segment, so it's a
    query param rather than /balance/{public_key}.
    """
    return {"public_key": public_key, "balance": blockchain.get_balance(public_key)}


@app.post("/stake")
def stake(public_key: str, amount: float, signature: str):
    """
    Phase 11: signature is pre-computed client-side (same pattern as
    /transactions/new — the caller's Wallet signs
    {"from": public_key, "to": f"STAKE:{public_key}", "amount": amount}
    locally and submits the result here), so the server never needs a
    private key to verify it's really that wallet choosing to stake.
    """
    try:
        blockchain.stake(public_key, amount, signature)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"message": "Stake transaction added to mempool"}


@app.get("/validators")
def get_validators():
    """
    Confirmed-chain-only, same rule as /balance — a stake sitting
    unmined in the mempool isn't an active validator yet.
    """
    return blockchain.get_active_validators()


@app.get("/headers")
def get_headers():
    """
    Phase 14: what a light client fetches — never full block bodies.
    Exactly the fields Block.compute_hash() hashes (index, timestamp,
    previous_hash, nonce, merkle_root) plus the block's own hash, so a
    light client can validate self-consistency + linkage entirely on its
    own without ever touching transaction data.
    """
    return {
        "headers": [
            {
                "index": block.index,
                "timestamp": block.timestamp,
                "previous_hash": block.previous_hash,
                "nonce": block.nonce,
                "merkle_root": block.merkle_root,
                "hash": block.hash,
            }
            for block in blockchain.chain
        ]
    }


@app.get("/block/{index}/proof")
def get_block_proof(index: int, tx_index: int):
    """
    Phase 14: a full node serves proofs on request so light clients never
    need full block bodies — merkle_proof() (Phase 8) does the actual
    work; this just looks up the right block/transaction and returns it
    alongside the block's merkle_root for the light client to check
    against its own already-validated header.
    """
    if index < 0 or index >= len(blockchain.chain):
        raise HTTPException(status_code=404, detail="Block index out of range")
    block = blockchain.chain[index]
    if tx_index < 0 or tx_index >= len(block.transactions):
        raise HTTPException(status_code=404, detail="Transaction index out of range")
    return {
        "index": index,
        "tx_index": tx_index,
        "transaction": block.transactions[tx_index],
        "proof": merkle_proof(block.transactions, tx_index),
        "merkle_root": block.merkle_root,
    }


@app.post("/nodes/register")
def register_node(node_address: str):
    registry.register(node_address)
    return {"message": f"Registered peer {node_address}"}


@app.get("/peers")
def get_peers():
    """
    Phase 16: visibility into which known peers are actually reachable.
    "active" is exactly the broadcast/resolve target list
    (PeerRegistry.active_peers()); "inactive" ones aren't forgotten —
    just paused after FAILURE_THRESHOLD consecutive failures, and drop
    back to active on the next successful contact or /nodes/register.
    """
    return {
        "active": sorted(registry.active_peers()),
        "inactive": sorted(registry.inactive_peers),
    }


@app.post("/blocks/receive")
def receive_block(block: dict, broadcast: bool = True):
    """
    A peer announced a mined block. Two cases:

    1. It extends our chain (previous_hash matches our last block, and
       its proof-of-work checks out) — accept it directly. Re-checking
       is_valid_proof() here, rather than trusting the sender, is the
       whole point of decentralized validation: every node verifies for
       itself instead of taking another node's word for it.

    2. It doesn't extend our chain — this is a fork (the peer mined
       from a different tip than we did, or we're just behind). Rather
       than discard the block, ask every known peer for their chain and
       adopt the longest valid one via resolve_conflicts(). This is the
       longest-chain rule doing its job: we don't try to reason about
       *this one block* in isolation, we let chain length settle it.

    broadcast=False (set by PeerRegistry.broadcast_block when relaying)
    stops us from re-announcing a block we just received, which would
    ping-pong it forever between mutually-registered peers — same fix
    as new_transaction's broadcast flag.

    Phase 11: a PoS block (validator_public_key set) is recorded as a
    proposal before anything else, win or lose — this is the "received
    block" half of equivocation tracking (the other half is /mine's own
    proposals). If that reveals a second, different block from the same
    validator at the same index, the validator is slashed immediately and
    this block is rejected regardless of whether it would otherwise have
    extended our chain.

    Phase 13: PoW/validator-signature validity and economic validity
    (validate_block_economics — signatures on ordinary transactions,
    same-block double-spends, coinbase inflation) are independent checks
    and both must pass; passing one was never a substitute for the other.
    """
    incoming = Block(**block)

    if incoming.validator_public_key and blockchain.record_proposal(
        incoming.validator_public_key, incoming.index, incoming.hash
    ):
        return {"message": "Equivocation detected, validator slashed", "index": incoming.index}

    if incoming.validator_public_key:
        header = {"index": incoming.index, "previous_hash": incoming.previous_hash}
        proof_ok = verify_signature(header, incoming.validator_signature, incoming.validator_public_key)
    else:
        proof_ok = is_valid_proof(incoming, blockchain.difficulty)

    economics_ok = blockchain.validate_block_economics(incoming, {})

    if incoming.previous_hash == blockchain.last_block.hash and proof_ok and economics_ok:
        blockchain.add_block(incoming)
        blockchain.pending_transactions = []
        persist_chain()
        if broadcast:
            registry.broadcast_block(block)
        return {"message": "Block accepted", "index": incoming.index}

    resolved = registry.resolve_conflicts(blockchain.chain)
    if len(resolved) > len(blockchain.chain):
        blockchain.chain = resolved
        blockchain.pending_transactions = []
        persist_chain()
        return {"message": "Fork resolved via longest chain", "length": len(blockchain.chain)}

    return {"message": "Block rejected, local chain retained", "length": len(blockchain.chain)}


@app.get("/mine")
def mine(miner_public_key: str, validator_signature: str = None):
    """
    Build a candidate block from whatever's in the mempool, then either
    spend proof-of-work or (Phase 11, CONSENSUS_MODE=pos) get it signed
    by the round's selected validator, and tell peers.

    Candidate fields are all derived from current chain state (index and
    previous_hash both come from last_block) rather than passed in —
    a miner doesn't get to choose where its block attaches, only what
    nonce makes it valid.

    Phase 9: block size is capped at MAX_TRANSACTIONS_PER_BLOCK, so when
    the mempool has more than that, the miner picks the highest-fee ones
    first (stable sort preserves original mempool order as the tiebreak)
    and leaves the rest pending for a future block rather than discarding
    them. The miner is paid BLOCK_REWARD plus every included transaction's
    fee, folded into one COINBASE transaction rather than paid out
    per-transaction — see Blockchain.get_balance for why that's simpler.

    Phase 11: CONSENSUS_MODE is read fresh here (not imported as a cached
    constant from consensus.py) so a node's mode can't get stuck on
    whatever it was at process startup. In "pos" mode, anyone can still
    call this endpoint, but only the validator select_validator() actually
    picked for this round succeeds — everyone else gets 403. That's what
    makes the selection meaningful instead of decorative: the caller
    proves it's really that validator by pre-signing the block's header
    (index + previous_hash, the two fields it can know in advance) with
    its own private key and passing the signature in, the same way a
    transaction's signature is computed client-side and submitted. The
    server never sees, needs, or could plausibly hold every validator's
    private key.
    """
    pending = blockchain.pending_transactions
    ranked_indices = sorted(
        range(len(pending)), key=lambda i: pending[i].get("fee", 0), reverse=True
    )
    selected_indices = set(ranked_indices[: Blockchain.MAX_TRANSACTIONS_PER_BLOCK])
    selected = [tx for i, tx in enumerate(pending) if i in selected_indices]
    remaining = [tx for i, tx in enumerate(pending) if i not in selected_indices]

    total_fees = sum(tx.get("fee", 0) for tx in selected)
    coinbase = {
        "from": "COINBASE",
        "to": miner_public_key,
        "amount": Blockchain.BLOCK_REWARD + total_fees,
    }

    candidate = Block(
        index=blockchain.last_block.index + 1,
        timestamp=time.time(),
        transactions=selected + [coinbase],
        previous_hash=blockchain.last_block.hash,
    )

    if os.environ.get("CONSENSUS_MODE", "pow") == "pos":
        active_validators = blockchain.get_active_validators()
        if not active_validators:
            raise HTTPException(status_code=400, detail="No active validators")

        selected_validator = select_validator(active_validators)
        if selected_validator != miner_public_key:
            raise HTTPException(
                status_code=403, detail="Not the validator selected for this round"
            )

        header = {"index": candidate.index, "previous_hash": candidate.previous_hash}
        if not validator_signature or not verify_signature(
            header, validator_signature, miner_public_key
        ):
            raise HTTPException(status_code=400, detail="Invalid or missing validator signature")

        candidate.hash = candidate.compute_hash()
        candidate.validator_public_key = miner_public_key
        candidate.validator_signature = validator_signature

        if blockchain.record_proposal(miner_public_key, candidate.index, candidate.hash):
            raise HTTPException(
                status_code=403, detail="Equivocation detected — validator slashed"
            )
    else:
        proof_of_work(candidate, blockchain.difficulty)
        candidate.hash = candidate.compute_hash()

    blockchain.add_block(candidate)
    blockchain.pending_transactions = remaining
    persist_chain()

    mined_block = asdict(candidate)
    registry.broadcast_block(mined_block)
    return mined_block


@app.post("/nodes/resolve")
def resolve_nodes():
    """
    Manual trigger for the longest-chain rule, independent of any block
    receipt — useful right after registering peers that may have mined
    divergent chains while unpeered, since nothing else forces a sync
    at registration time.
    """
    resolved = registry.resolve_conflicts(blockchain.chain)
    replaced = len(resolved) > len(blockchain.chain)
    if replaced:
        blockchain.chain = resolved
        blockchain.pending_transactions = []
        persist_chain()
    return {"replaced": replaced, "length": len(blockchain.chain)}
