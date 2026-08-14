/**
 * Phase F1: a thin client over the node API, parameterized by base URL
 * rather than hardcoded to one node — every later phase (F3 wallet
 * actions, F4 multi-node fork visualization) needs to hit whichever
 * node the user has selected, and several nodes at once for F4.
 *
 * Defaults assume the docker-compose port mapping (5001-5005 -> each
 * node's internal :5000). Override via VITE_NODE_URLS if your setup
 * differs.
 */
import axios from "axios";

export const DEFAULT_NODES = (
  import.meta.env?.VITE_NODE_URLS || "http://localhost:5001,http://localhost:5002,http://localhost:5003,http://localhost:5004,http://localhost:5005"
)
  .split(",")
  .map((url) => url.trim());

const DEFAULT_TIMEOUT_MS = 5000;
// PoW mining searches for a nonce satisfying the current difficulty --
// unlike every other endpoint here, its duration isn't bounded by network
// latency, it's bounded by how long that search takes (observed: several
// seconds at the default difficulty=4 under real load, occasionally
// longer). The default timeout above is far too tight for it and would
// abort a mine that's genuinely still in progress server-side (confirmed
// by hand: a "timed out" mine() call had still landed the block on the
// chain a moment later).
const MINE_TIMEOUT_MS = 60000;

function client(baseURL, timeout = DEFAULT_TIMEOUT_MS) {
  return axios.create({ baseURL, timeout });
}

export async function getStatus(nodeUrl) {
  const { data } = await client(nodeUrl).get("/status");
  return data;
}

export async function getChain(nodeUrl) {
  const { data } = await client(nodeUrl).get("/chain");
  return data;
}

export async function getHeaders(nodeUrl) {
  const { data } = await client(nodeUrl).get("/headers");
  return data;
}

export async function getPeers(nodeUrl) {
  const { data } = await client(nodeUrl).get("/peers");
  return data;
}

export async function getMempool(nodeUrl) {
  const { data } = await client(nodeUrl).get("/mempool");
  return data;
}

export async function getBalance(nodeUrl, publicKeyPem) {
  const { data } = await client(nodeUrl).get("/balance", {
    params: { public_key: publicKeyPem },
  });
  return data;
}

// --- Phase F3: mutating endpoints (wallet actions) ---

export async function submitTransaction(nodeUrl, transaction) {
  const { data } = await client(nodeUrl).post("/transactions/new", transaction);
  return data;
}

export async function stake(nodeUrl, publicKeyPem, amount, signature) {
  const { data } = await client(nodeUrl).post("/stake", null, {
    params: { public_key: publicKeyPem, amount, signature },
  });
  return data;
}

// PoW mining. Returns 400 if the node is in CONSENSUS_MODE=pos — callers
// should check getStatus(nodeUrl).consensus_mode first (see Wallet.jsx)
// rather than relying on this failing to detect the mode.
export async function mine(nodeUrl, minerPublicKeyPem) {
  const { data } = await client(nodeUrl, MINE_TIMEOUT_MS).get("/mine", {
    params: { miner_public_key: minerPublicKeyPem },
  });
  return data;
}

// PoS two-step flow, step 1: ask the node to build candidate block
// content (mempool selection + coinbase) for miner_public_key, unsigned.
// 403s if miner_public_key isn't this round's selected validator.
export async function mineProposePoS(nodeUrl, minerPublicKeyPem) {
  const { data } = await client(nodeUrl).get("/mine/propose", {
    params: { miner_public_key: minerPublicKeyPem },
  });
  return data;
}

// PoS two-step flow, step 2: submit the validator's signature over
// {index, previous_hash, merkle_root} from mineProposePoS's response,
// finalizing the block.
export async function mineSubmitPoS(nodeUrl, payload) {
  const { data } = await client(nodeUrl).post("/mine/submit", payload);
  return data;
}
