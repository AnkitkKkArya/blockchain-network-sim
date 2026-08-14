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
  import.meta.env.VITE_NODE_URLS || "http://localhost:5001,http://localhost:5002,http://localhost:5003,http://localhost:5004,http://localhost:5005"
)
  .split(",")
  .map((url) => url.trim());

function client(baseURL) {
  return axios.create({ baseURL, timeout: 5000 });
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

// Phase F3 will add: submitTransaction, stake, mine/propose, mine/submit.
// Not implemented yet — this file is read-only endpoints only, on purpose,
// so F1 has zero risk of accidentally mutating chain state while just
// building the dashboard.
