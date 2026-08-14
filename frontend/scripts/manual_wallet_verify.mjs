#!/usr/bin/env node
/**
 * Phase F3 manual verification harness. Not part of the app, not a unit
 * test with mocks -- this imports the REAL src/lib/crypto.js and
 * src/api/client.js modules the Wallet.jsx UI itself calls, and drives
 * them against a live node exactly the way a user clicking through the
 * UI would: generate -> check balance (0) -> mine -> check balance
 * (reward) -> send a portion to a second wallet -> check both balances.
 *
 * No browser automation tool was available in this environment to
 * literally click through the React UI, so this is the most rigorous
 * substitute: the actual code paths Wallet.jsx uses, not a
 * reimplementation of them.
 *
 * Usage: node scripts/manual_wallet_verify.mjs
 */
import { generateWallet, signTransaction } from "../src/lib/crypto.js";
import { getBalance, mine, submitTransaction } from "../src/api/client.js";

const NODE_URL = process.env.NODE_URL || "http://localhost:5001";

function log(label, value) {
  console.log(`${label}: ${JSON.stringify(value)}`);
}

async function main() {
  console.log(`Manual wallet verification against ${NODE_URL}\n`);

  console.log("1. Generate wallet (src/lib/crypto.js's generateWallet(), same as the 'Generate");
  console.log("   wallet' button)");
  const alice = generateWallet();
  console.log(`   alice public key: ${alice.publicKeyPem.split("\n")[1].slice(0, 24)}...\n`);

  console.log("2. Check starting balance (src/api/client.js's getBalance(), same as the");
  console.log("   live balance display)");
  const startingBalance = await getBalance(NODE_URL, alice.publicKeyPem);
  log("   alice balance", startingBalance.balance);
  if (startingBalance.balance !== 0) throw new Error("expected a fresh wallet to start at 0");
  console.log("   -> confirmed 0, as expected\n");

  console.log("3. Mine a block as alice (src/api/client.js's mine(), same as the 'Mine a block'");
  console.log("   button under PoW)");
  const minedBlock = await mine(NODE_URL, alice.publicKeyPem);
  console.log(`   mined block index: ${minedBlock.index}\n`);

  console.log("4. Check balance again -- should reflect the mining reward");
  const balanceAfterMining = await getBalance(NODE_URL, alice.publicKeyPem);
  log("   alice balance", balanceAfterMining.balance);
  if (!(balanceAfterMining.balance > startingBalance.balance)) {
    throw new Error("expected balance to increase after mining");
  }
  console.log("   -> confirmed increased, reflecting BLOCK_REWARD\n");

  console.log("5. Generate a second, in-session wallet (bob) and send alice -> bob");
  console.log("   (src/lib/crypto.js's signTransaction() + src/api/client.js's");
  console.log("   submitTransaction(), same as the Send form)");
  const bob = generateWallet();
  const sendAmount = balanceAfterMining.balance / 2;
  const transaction = { from: alice.publicKeyPem, to: bob.publicKeyPem, amount: sendAmount, fee: 0 };
  transaction.signature = signTransaction(transaction, alice.privateKey);
  transaction.sender_public_key = alice.publicKeyPem;
  const submitResult = await submitTransaction(NODE_URL, transaction);
  log("   submit result", submitResult);

  console.log("\n6. Mine again (to confirm the pending transaction) as a third, throwaway wallet --");
  console.log("   not bob, so bob's own mining reward doesn't get mixed into the balance we're");
  console.log("   about to check was updated purely by the transfer");
  const confirmer = generateWallet();
  const secondBlock = await mine(NODE_URL, confirmer.publicKeyPem);
  console.log(`   mined block index: ${secondBlock.index}\n`);

  console.log("7. Confirm both balances updated correctly");
  const aliceFinal = await getBalance(NODE_URL, alice.publicKeyPem);
  const bobFinal = await getBalance(NODE_URL, bob.publicKeyPem);
  log("   alice final balance", aliceFinal.balance);
  log("   bob final balance", bobFinal.balance);

  const expectedAlice = balanceAfterMining.balance - sendAmount;
  if (aliceFinal.balance !== expectedAlice) {
    throw new Error(`alice balance mismatch: expected ${expectedAlice}, got ${aliceFinal.balance}`);
  }
  if (bobFinal.balance !== sendAmount) {
    throw new Error(`bob balance mismatch: expected ${sendAmount}, got ${bobFinal.balance}`);
  }

  console.log("\nPASS: full round-trip through the real crypto.js/client.js code paths --");
  console.log("generate, zero balance, mine, reward reflected, send, both balances correct.");
  process.exitCode = 0;
}

main().catch((err) => {
  console.error("\nFAIL:", err.message);
  process.exitCode = 1;
});
