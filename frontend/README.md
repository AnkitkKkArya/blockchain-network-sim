# Frontend — blockchain network dashboard

React + Vite + Tailwind + react-flow (`@xyflow/react`) for the fork graph,
recharts for supplementary charts, react-query for polling multiple nodes.

## Phase -> file map

| Phase | What | File(s) |
|---|---|---|
| F1 | Scaffold + read-only status dashboard | `src/api/client.js`, `src/pages/Dashboard.jsx`, `src/components/{NodeSelector,StatusCard}.jsx` |
| F2 | Cross-language (JS <-> Python) signature compatibility check | `scripts/` (standalone, not part of the app build) |
| F3 | Client-side wallet + interactive actions (send/stake/mine) | `src/api/client.js` (extended), `src/pages/Wallet.jsx`, `src/lib/crypto.js` |
| F4 | Multi-node chain/fork graph visualizer | `src/pages/ChainGraph.jsx`, `src/components/BlockNode.jsx` |
| F5 | Guided attack/fork demo mode | `src/pages/AttackDemo.jsx` |

## Running

Requires the backend docker-compose network running (see the project root
README) -- this only reads from / writes to nodes at localhost:5001-5005 by
default (override with a `.env` file setting `VITE_NODE_URLS`).

```bash
npm install
npm run dev
```

## Done-when checkpoints

- **F1**: selecting any of the 5 nodes in the dropdown shows real,
  live-updating `/status` data (chain length, difficulty, mempool size,
  peers), and shows a clear error if a node is unreachable.
- **F2**: a signature produced in the browser verifies successfully against
  the existing Python `verify_signature()`, confirmed by an actual test
  against a running node -- not just "the JS library didn't throw."
- **F3**: a wallet generated entirely in the browser can fund, sign, and
  successfully mine a transaction with no `curl` involved.
- **F4**: disconnecting a node and mining on both sides visibly renders as
  two diverging branches in the graph, not just two different chain-length
  numbers.
- **F5**: the full Phase 12 attack narrative is walkable via UI buttons,
  with the graph updating live at each step.
