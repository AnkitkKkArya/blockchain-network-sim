# Blockchain network simulation

[![tests](https://github.com/AnkitkKkArya/blockchain-network-sim/actions/workflows/tests.yml/badge.svg)](https://github.com/AnkitkKkArya/blockchain-network-sim/actions/workflows/tests.yml)

A multi-node blockchain simulation, built phase by phase to internalize the mechanics
(hashing/chaining, P2P propagation, consensus, forks, containerized networking).

## Phase -> file map

| Phase | What you're building | File(s) |
|---|---|---|
| 1 | Core chain logic: Block, Blockchain, hashing, validation | `node/blockchain.py`, `tests/test_blockchain.py` |
| 2 | Node HTTP API wrapping the chain | `node/app.py` |
| 3 | Peer registration + transaction/block broadcast | `node/p2p.py` |
| 4 | Proof of Work + longest-chain fork resolution | `node/consensus.py` |
| 5 | Containerize, run N nodes on a shared network | `node/Dockerfile`, `docker-compose.yml` |
| 6 (stretch) | Proof of Stake mode toggle | `node/consensus.py` (extend) |

## Running (once Phase 1-2 are implemented)

```bash
cd node
pip install -r requirements.txt
uvicorn app:app --reload --port 5000
```

## Running the network (once Phase 5 is implemented)

```bash
docker-compose up --build
```

## Phase 12: the attack

`scripts/attack_demo.py` runs a 51%-style double-spend against the 5-node network: an
attacker pays a merchant on the honest, connected nodes (1-4) and the payment gets mined
and is visible everywhere — meanwhile node5, isolated from the network *before* that
payment ever happened, has been secretly mining a private fork containing a conflicting
transaction that sends the same funds elsewhere. Once node5's private chain is longer and
reconnects, the honest nodes' `/nodes/resolve` adopts it via the ordinary longest-valid-chain
rule, and the merchant's payment simply disappears — no code was exploited, this is the
protocol working exactly as designed. It works because "longest valid chain wins" is
unconditional: nothing in this project treats a mined transaction as more final the longer
it sits under other blocks. Real chains mitigate this by convention rather than protocol —
merchants wait for multiple *confirmations* (additional blocks mined on top) before treating
a payment as settled, since each extra confirmation means an attacker's private fork has to
out-mine that much more honest work to still end up longer; a single confirmation is
considered risky for exactly this reason, which is why high-value payments on Bitcoin
typically wait for 6+.

```bash
python scripts/attack_demo.py
```

## Done-when checkpoints

- **Phase 1**: unit tests catch tampering — altering any past block's data breaks `is_chain_valid()`.
- **Phase 2**: `curl localhost:5000/chain` returns the current chain as JSON.
- **Phase 3**: two locally running nodes share the same mempool after one receives a transaction.
- **Phase 4**: forcing two nodes to mine near-simultaneously produces a fork that resolves via longest-chain rule on next sync.
- **Phase 5**: killing one container's network connection, then reconnecting it, results in it re-syncing to the network's longest chain.
