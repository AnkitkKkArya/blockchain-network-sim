import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  DEFAULT_NODES,
  getBalance,
  getStatus,
  mine,
  mineProposePoS,
  mineSubmitPoS,
  stake as stakeRequest,
  submitTransaction,
} from "../api/client";
import { generateWallet, signTransaction } from "../lib/crypto";
import NodeSelector from "../components/NodeSelector";

function shortKey(pem) {
  if (!pem) return "";
  const body = pem.replace(/-----[A-Z ]+-----/g, "").replace(/\s+/g, "");
  return `${body.slice(0, 8)}…${body.slice(-8)}`;
}

function extractErrorMessage(err) {
  return err?.response?.data?.detail || err?.message || String(err);
}

/**
 * Phase F3: client-side wallet + interactive actions. The private key
 * only ever lives in React state (in memory) — no localStorage, no
 * cookies. Closing/reloading the tab loses it unless it was exported.
 */
export default function WalletPage() {
  const queryClient = useQueryClient();
  const [selectedNode, setSelectedNode] = useState(DEFAULT_NODES[0]);
  const [wallet, setWallet] = useState(null); // {privateKey, publicKeyPem} | null
  const [seenWallets, setSeenWallets] = useState([]); // [{label, publicKeyPem}]
  const [importError, setImportError] = useState(null);

  const [recipient, setRecipient] = useState("");
  const [amount, setAmount] = useState("");
  const [fee, setFee] = useState("");
  const [sendResult, setSendResult] = useState(null);

  const [stakeAmount, setStakeAmount] = useState("");
  const [stakeResult, setStakeResult] = useState(null);

  const [mineResult, setMineResult] = useState(null);
  const [mining, setMining] = useState(false);

  const { data: balanceData } = useQuery({
    queryKey: ["balance", selectedNode, wallet?.publicKeyPem],
    queryFn: () => getBalance(selectedNode, wallet.publicKeyPem),
    enabled: !!wallet,
    refetchInterval: 2000,
  });

  function rememberWallet(publicKeyPem, label) {
    setSeenWallets((prev) => {
      if (prev.some((w) => w.publicKeyPem === publicKeyPem)) return prev;
      return [...prev, { label, publicKeyPem }];
    });
  }

  function refreshBalance() {
    queryClient.invalidateQueries({ queryKey: ["balance", selectedNode, wallet?.publicKeyPem] });
  }

  function handleGenerate() {
    const newWallet = generateWallet();
    setWallet(newWallet);
    rememberWallet(newWallet.publicKeyPem, "you");
    setSendResult(null);
    setStakeResult(null);
    setMineResult(null);
  }

  function handleExport() {
    const blob = new Blob([JSON.stringify(wallet, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `wallet-${Date.now()}.json`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function handleImportFile(event) {
    const file = event.target.files[0];
    event.target.value = ""; // allow re-importing the same filename later
    if (!file) return;
    setImportError(null);

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(reader.result);
        if (!parsed.privateKey || !parsed.publicKeyPem) {
          throw new Error("File is missing privateKey/publicKeyPem");
        }
        setWallet(parsed);
        rememberWallet(parsed.publicKeyPem, "you (imported)");
      } catch (err) {
        setImportError(`Could not import wallet: ${err.message}`);
      }
    };
    reader.readAsText(file);
  }

  async function handleSend(event) {
    event.preventDefault();
    setSendResult(null);
    try {
      const transaction = {
        from: wallet.publicKeyPem,
        to: recipient.trim(),
        amount: Number(amount),
        fee: fee === "" ? 0 : Number(fee),
      };
      transaction.signature = signTransaction(transaction, wallet.privateKey);
      transaction.sender_public_key = wallet.publicKeyPem;

      const result = await submitTransaction(selectedNode, transaction);
      setSendResult({ ok: true, message: result.message });
      rememberWallet(transaction.to, "recipient");
      refreshBalance();
    } catch (err) {
      setSendResult({ ok: false, message: extractErrorMessage(err) });
    }
  }

  async function handleStake(event) {
    event.preventDefault();
    setStakeResult(null);
    try {
      const amountValue = Number(stakeAmount);
      const payload = {
        from: wallet.publicKeyPem,
        to: `STAKE:${wallet.publicKeyPem}`,
        amount: amountValue,
      };
      const signature = signTransaction(payload, wallet.privateKey);

      const result = await stakeRequest(selectedNode, wallet.publicKeyPem, amountValue, signature);
      setStakeResult({ ok: true, message: result.message });
      refreshBalance();
    } catch (err) {
      setStakeResult({ ok: false, message: extractErrorMessage(err) });
    }
  }

  async function handleMine() {
    setMineResult(null);
    setMining(true);
    try {
      const status = await getStatus(selectedNode);

      if (status.consensus_mode === "pos") {
        let proposal;
        try {
          proposal = await mineProposePoS(selectedNode, wallet.publicKeyPem);
        } catch (err) {
          if (err?.response?.status === 403) {
            setMineResult({ ok: false, message: "Not selected as validator this round — try again on the next block." });
            return;
          }
          throw err;
        }

        const header = {
          index: proposal.index,
          previous_hash: proposal.previous_hash,
          merkle_root: proposal.merkle_root,
        };
        const validatorSignature = signTransaction(header, wallet.privateKey);

        const mined = await mineSubmitPoS(selectedNode, {
          ...proposal,
          validator_signature: validatorSignature,
          miner_public_key: wallet.publicKeyPem,
        });
        setMineResult({ ok: true, message: `Mined block ${mined.index} (PoS)` });
      } else {
        const mined = await mine(selectedNode, wallet.publicKeyPem);
        setMineResult({ ok: true, message: `Mined block ${mined.index} (PoW)` });
      }
      refreshBalance();
    } catch (err) {
      if (err?.response?.status === 403) {
        setMineResult({ ok: false, message: "Not selected as validator this round — try again on the next block." });
      } else {
        setMineResult({ ok: false, message: extractErrorMessage(err) });
      }
    } finally {
      setMining(false);
    }
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-xl font-semibold tracking-tight">Blockchain Network — Wallet</h1>
        <NodeSelector nodes={DEFAULT_NODES} selected={selectedNode} onChange={setSelectedNode} />
      </div>

      {!wallet && (
        <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-6 space-y-4">
          <p className="text-sm text-slate-400">
            No wallet loaded. The private key only ever lives in memory for this tab — nothing is
            saved automatically.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <button
              onClick={handleGenerate}
              className="rounded-lg bg-teal-700 hover:bg-teal-600 px-4 py-2 text-sm font-medium"
            >
              Generate wallet
            </button>
            <label className="rounded-lg border border-slate-600 hover:border-slate-400 px-4 py-2 text-sm font-medium cursor-pointer">
              Import from file
              <input type="file" accept="application/json" className="hidden" onChange={handleImportFile} />
            </label>
          </div>
          {importError && <p className="text-rose-400 text-sm">{importError}</p>}
        </div>
      )}

      {wallet && (
        <div className="space-y-6">
          <div className="rounded-xl border border-teal-800 bg-slate-900/60 p-4">
            <div className="flex items-center justify-between flex-wrap gap-3">
              <div>
                <div className="text-xs uppercase tracking-wide text-slate-400">Active wallet</div>
                <div className="font-mono text-sm text-teal-300 mt-1">{shortKey(wallet.publicKeyPem)}</div>
                <div className="text-2xl font-semibold mt-2">
                  {balanceData ? balanceData.balance : "…"}
                  <span className="text-sm text-slate-400 font-normal ml-2">balance</span>
                </div>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleExport}
                  className="rounded-lg border border-slate-600 hover:border-slate-400 px-3 py-2 text-xs font-medium"
                >
                  Export to file
                </button>
                <button
                  onClick={() => setWallet(null)}
                  className="rounded-lg border border-rose-800 text-rose-300 hover:border-rose-600 px-3 py-2 text-xs font-medium"
                >
                  Clear wallet
                </button>
              </div>
            </div>
            <details className="mt-3">
              <summary className="text-xs text-slate-500 cursor-pointer">Show full public key PEM</summary>
              <pre className="text-xs text-slate-400 mt-2 whitespace-pre-wrap break-all">{wallet.publicKeyPem}</pre>
            </details>
          </div>

          <div className="grid md:grid-cols-2 gap-6">
            <form
              onSubmit={handleSend}
              className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3"
            >
              <h2 className="text-sm font-semibold">Send</h2>

              {seenWallets.length > 0 && (
                <select
                  onChange={(e) => e.target.value && setRecipient(e.target.value)}
                  defaultValue=""
                  className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-xs"
                >
                  <option value="">Pick a previously-seen wallet…</option>
                  {seenWallets.map((w) => (
                    <option key={w.publicKeyPem} value={w.publicKeyPem}>
                      {w.label} — {shortKey(w.publicKeyPem)}
                    </option>
                  ))}
                </select>
              )}

              <textarea
                required
                placeholder="Recipient public key (paste PEM)"
                value={recipient}
                onChange={(e) => setRecipient(e.target.value)}
                rows={3}
                className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-xs font-mono"
              />

              <div className="flex gap-3">
                <input
                  required
                  type="number"
                  step="any"
                  min="0"
                  placeholder="Amount"
                  value={amount}
                  onChange={(e) => setAmount(e.target.value)}
                  className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                />
                <input
                  type="number"
                  step="any"
                  min="0"
                  placeholder="Fee (optional)"
                  value={fee}
                  onChange={(e) => setFee(e.target.value)}
                  className="flex-1 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                />
              </div>

              <button
                type="submit"
                className="rounded-lg bg-teal-700 hover:bg-teal-600 px-4 py-2 text-sm font-medium w-full"
              >
                Sign &amp; send
              </button>

              {sendResult && (
                <p className={`text-xs ${sendResult.ok ? "text-teal-300" : "text-rose-400"}`}>
                  {sendResult.message}
                </p>
              )}
            </form>

            <div className="space-y-6">
              <form
                onSubmit={handleStake}
                className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3"
              >
                <h2 className="text-sm font-semibold">Stake</h2>
                <input
                  required
                  type="number"
                  step="any"
                  min="0"
                  placeholder="Amount to stake"
                  value={stakeAmount}
                  onChange={(e) => setStakeAmount(e.target.value)}
                  className="w-full bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm"
                />
                <button
                  type="submit"
                  className="rounded-lg bg-amber-700 hover:bg-amber-600 px-4 py-2 text-sm font-medium w-full"
                >
                  Sign &amp; stake
                </button>
                {stakeResult && (
                  <p className={`text-xs ${stakeResult.ok ? "text-teal-300" : "text-rose-400"}`}>
                    {stakeResult.message}
                  </p>
                )}
              </form>

              <div className="rounded-xl border border-slate-700 bg-slate-900/60 p-4 space-y-3">
                <h2 className="text-sm font-semibold">Mine</h2>
                <p className="text-xs text-slate-500">
                  Detects PoW vs PoS from the node's current status automatically. Under PoS, only
                  this round's selected validator will succeed.
                </p>
                <button
                  onClick={handleMine}
                  disabled={mining}
                  className="rounded-lg bg-slate-700 hover:bg-slate-600 disabled:opacity-50 px-4 py-2 text-sm font-medium w-full"
                >
                  {mining ? "Mining…" : "Mine a block"}
                </button>
                {mineResult && (
                  <p className={`text-xs ${mineResult.ok ? "text-teal-300" : "text-rose-400"}`}>
                    {mineResult.message}
                  </p>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
