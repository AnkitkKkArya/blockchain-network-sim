import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { DEFAULT_NODES, getStatus } from "../api/client";
import NodeSelector from "../components/NodeSelector";
import StatusCard from "../components/StatusCard";

/**
 * Phase F1: read-only dashboard. Polls the selected node's /status every
 * 2s so chain growth, difficulty adjustment, and mempool activity are
 * visible without a manual refresh -- this becomes the base every later
 * phase's UI sits inside (wallet actions in F3, the fork graph in F4).
 */
export default function Dashboard() {
  const [selectedNode, setSelectedNode] = useState(DEFAULT_NODES[0]);

  const { data: status, isLoading, isError, error } = useQuery({
    queryKey: ["status", selectedNode],
    queryFn: () => getStatus(selectedNode),
    refetchInterval: 2000,
  });

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold tracking-tight">
          Blockchain Network — Status
        </h1>
        <NodeSelector nodes={DEFAULT_NODES} selected={selectedNode} onChange={setSelectedNode} />
      </div>

      {isLoading && <p className="text-slate-400 text-sm">Loading…</p>}

      {isError && (
        <div className="rounded-xl border border-rose-800 bg-rose-950/40 p-4 text-rose-300 text-sm">
          Couldn't reach {selectedNode} — is the docker-compose network running?
          <div className="text-rose-400/70 mt-1">{String(error?.message)}</div>
        </div>
      )}

      {status && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatusCard label="Chain length" value={status.chain_length} accent="teal" />
          <StatusCard label="Difficulty" value={status.difficulty} accent="amber" />
          <StatusCard label="Consensus mode" value={status.consensus_mode} />
          <StatusCard label="Mempool size" value={status.mempool_size} />
          <StatusCard label="Active peers" value={status.active_peer_count} accent="teal" />
          {status.consensus_mode === "pos" && (
            <StatusCard label="Active validators" value={status.active_validator_count} accent="amber" />
          )}
        </div>
      )}

      <div className="mt-8 text-xs text-slate-500">
        Phase F1 — read-only status only. Wallet actions (F3) and the fork
        graph (F4) aren't built yet.
      </div>
    </div>
  );
}
