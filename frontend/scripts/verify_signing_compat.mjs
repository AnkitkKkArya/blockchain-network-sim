#!/usr/bin/env node
/**
 * Phase F2 (+ Phase F3 Part 1): prove a browser-compatible secp256k1
 * signing pipeline built in JS produces signatures the existing Python
 * backend's wallet.verify_signature() actually accepts -- before any
 * wallet UI gets built on top of that assumption. Standalone: run with
 * `node`, not part of the Vite app / bundled into anything shipped.
 *
 * Library choice: @noble/curves (not `elliptic`).
 *   - Audited, actively maintained, zero runtime dependencies, and the
 *     currently-recommended replacement for `elliptic` (which has had
 *     real signature-malleability/timing-safety issues and is
 *     effectively unmaintained).
 *   - Ships native ESM + TypeScript types and is tree-shakeable, which
 *     matters for Phase F3: this same signing code has to run inside a
 *     browser bundle, not just here in Node.
 *   - secp256k1 -- this project's curve, see node/wallet.py -- isn't
 *     supported by the browser-native Web Crypto API at all (Web
 *     Crypto only implements P-256/P-384/P-521), which is exactly why
 *     a userland curve library is required here in the first place.
 * No separate hashing library needed: secp256k1.sign()/.verify() default
 * to `prehash: true`, which hashes the raw message internally with the
 * curve's bound hasher -- SHA-256 for secp256k1, exactly matching
 * Python's ec.ECDSA(hashes.SHA256()). (An earlier version of this script
 * manually pre-hashed with @noble/hashes' sha256() AND left the default
 * prehash:true in place, silently double-hashing the payload -- see the
 * "double-hashing" note in runIntegerAmountTest() for how that was
 * diagnosed.)
 *
 * Two scenarios run here:
 *   1. Integer amount/fee (0/0), unfunded sender -- the original F2
 *      proof. Doesn't need funding since amount+fee=0 never exceeds a
 *      zero balance.
 *   2. Non-integer amount/fee (4.5/0.5) -- Phase F3 Part 1's question:
 *      does Python float formatting ("10.0") vs JS's ("10") diverge the
 *      signed payload for realistic decimal amounts? The sender is
 *      funded first by mining a block as itself (earning BLOCK_REWARD),
 *      so a genuine 200 here proves both signature AND balance checks
 *      passed -- not just "didn't get blocked by balance regardless".
 *
 * Usage:
 *   node scripts/verify_signing_compat.mjs
 * Requires a running node reachable at NODE_URL (default
 * http://localhost:5001) -- e.g. `docker-compose up -d node1` from the
 * project root, or a bare `uvicorn app:app --port 5001` from node/.
 */

import { secp256k1 } from '@noble/curves/secp256k1.js';

const NODE_URL = process.env.NODE_URL || 'http://localhost:5001';

// ---------------------------------------------------------------------
// Reproduce wallet.py's Wallet.public_key_pem EXACTLY.
//
// Confirmed against a real wallet.py-generated PEM, not assumed from a
// spec reading:
//   $ python -c "from wallet import Wallet; print(repr(Wallet().public_key_pem))"
//   '-----BEGIN PUBLIC KEY-----\nMFYwEAYHKoZIzj0CAQYFK4EEAAoDQgAE...==\n-----END PUBLIC KEY-----\n'
// i.e. standard PKCS#8 SubjectPublicKeyInfo (SPKI) DER, PEM-wrapped,
// '\n' line endings (not '\r\n'), base64 body wrapped at 64 chars/line,
// and a trailing '\n' after the END line.
//
// Decoding that PEM's base64 body confirms the DER SPKI structure for
// a secp256k1 key is a FIXED 23-byte prefix -- SEQUENCE header +
// AlgorithmIdentifier{id-ecPublicKey OID, secp256k1 OID} + BIT STRING
// header -- followed by the 65-byte uncompressed point (0x04 || X || Y):
//   3056301006072a8648ce3d020106052b8104000a034200 <65-byte point>
// That prefix never changes across keys (only the point does), so it's
// hardcoded here rather than built from an ASN.1 library.
const SECP256K1_SPKI_PREFIX_HEX = '3056301006072a8648ce3d020106052b8104000a034200';

function hexToBytes(hex) {
  return Uint8Array.from(Buffer.from(hex, 'hex'));
}

function concatBytes(...arrays) {
  const total = arrays.reduce((sum, a) => sum + a.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const a of arrays) {
    out.set(a, offset);
    offset += a.length;
  }
  return out;
}

function publicKeyToPem(uncompressedPublicKeyBytes) {
  const der = concatBytes(hexToBytes(SECP256K1_SPKI_PREFIX_HEX), uncompressedPublicKeyBytes);
  const base64 = Buffer.from(der).toString('base64');
  const lines = base64.match(/.{1,64}/g) ?? [];
  return `-----BEGIN PUBLIC KEY-----\n${lines.join('\n')}\n-----END PUBLIC KEY-----\n`;
}

function generateWallet() {
  const { secretKey } = secp256k1.keygen();
  const publicKeyUncompressed = secp256k1.getPublicKey(secretKey, false); // false = uncompressed
  return { secretKey, publicKeyPem: publicKeyToPem(publicKeyUncompressed) };
}

// ---------------------------------------------------------------------
// Reproduce wallet.py's _signing_payload() EXACTLY.
//
//   core = {k: v for k, v in transaction.items() if k not in ("signature", "sender_public_key")}
//   return json.dumps(core, sort_keys=True).encode()
//
// json.dumps(..., sort_keys=True) with no `separators` override uses
// Python's DEFAULT separators, ", " and ": " -- with the spaces. That
// is NOT what JSON.stringify produces (JS's default separators are
// "," and ":", no spaces), so plain JSON.stringify(sortedObj) would
// silently produce a byte-different payload. Confirmed by inspecting
// actual output:
//   >>> json.dumps({"amount": 10, "from": "A"}, sort_keys=True)
//   '{"amount": 10, "from": "A"}'
//
// Number formatting: JSON.stringify(4.5) === "4.5" and
// json.dumps(4.5) === "4.5" -- both languages use a shortest
// round-trip float-to-string algorithm and 4.5/0.5 are exactly
// representable in binary, so there's no rounding ambiguity to worry
// about for these values. See runFloatAmountTest()'s PASS/FAIL report
// for the empirical confirmation (this comment predicts it; the test
// is what actually proves it against the real backend).
function pythonSortedJsonDumps(obj) {
  const keys = Object.keys(obj).sort();
  const parts = keys.map((key) => `${JSON.stringify(key)}: ${JSON.stringify(obj[key])}`);
  return `{${parts.join(', ')}}`;
}

function signingPayloadBytes(transaction) {
  const { signature, sender_public_key, ...core } = transaction;
  return new TextEncoder().encode(pythonSortedJsonDumps(core));
}

function signTransaction(transaction, secretKey) {
  const payload = signingPayloadBytes(transaction);
  // Pass the RAW payload, not a pre-hashed digest: sign()/verify() default
  // to prehash:true and hash internally with SHA-256 for this curve --
  // matching Python's ec.ECDSA(hashes.SHA256()) exactly. Manually hashing
  // here first (an earlier version of this script did, via
  // @noble/hashes' sha256()) would leave prehash:true still in effect and
  // silently double-hash the payload -- a real bug this diagnosis caught:
  // JS-side self-verification (sign then verify with the same, wrongly
  // double-hashed input) passed trivially, but cross-verifying a genuine
  // Python-generated signature over the correct single-hashed digest
  // failed, which is what actually exposed it.
  //
  // format: 'der' matters too -- sign() defaults to a compact 64-byte
  // r||s encoding, but Python's cryptography EC sign() outputs DER (a
  // variable-length SEQUENCE{INTEGER r, INTEGER s}), and
  // wallet.verify_signature() expects DER via bytes.fromhex(signature).
  const signatureDerBytes = secp256k1.sign(payload, secretKey, { format: 'der' });
  return { payload, signatureHex: Buffer.from(signatureDerBytes).toString('hex') };
}

async function postTransaction(transaction) {
  const response = await fetch(`${NODE_URL}/transactions/new?broadcast=false`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(transaction),
  });
  return { status: response.status, body: await response.json() };
}

async function mine(minerPublicKeyPem) {
  const response = await fetch(
    `${NODE_URL}/mine?miner_public_key=${encodeURIComponent(minerPublicKeyPem)}`,
  );
  return { status: response.status, body: await response.json() };
}

async function getBalance(publicKeyPem) {
  const response = await fetch(`${NODE_URL}/balance?public_key=${encodeURIComponent(publicKeyPem)}`);
  const body = await response.json();
  return body.balance;
}

function printDiagnosisChecklist() {
  console.error('\nDiagnosis checklist (don\'t paper over this -- find the actual cause):');
  console.error('  - Wrong rejection reason ("balance" instead of "signature")? That is NOT a');
  console.error('    crypto failure -- something else is wrong with this script\'s test setup.');
  console.error('  - "signature does not verify": check, in order --');
  console.error('      1. Curve mismatch: is the backend definitely using SECP256K1, not secp256r1?');
  console.error('      2. Hashing mismatch: is the message being hashed exactly once with SHA-256 on');
  console.error('         both sides? (Real bug hit while writing this script: manually pre-hashing');
  console.error('         AND leaving sign()/verify()\'s default prehash:true in place silently');
  console.error('         double-hashes the payload in JS. Cross-verifying a genuine Python signature');
  console.error('         against a raw, not pre-hashed, JS payload is what exposed it -- a JS');
  console.error('         self-sign-then-verify round-trip stays internally consistent either way and');
  console.error('         will NOT catch this.)');
  console.error('      3. Signature encoding: is { format: \'der\' } really producing DER (30 ... SEQUENCE),');
  console.error('         not the default compact/raw r||s encoding? Compare the first byte to 0x30.');
  console.error('      4. Public key point encoding: uncompressed (0x04 prefix, 65 bytes) vs');
  console.error('         compressed (0x02/0x03 prefix, 33 bytes) -- the SPKI prefix above assumes');
  console.error('         uncompressed.');
  console.error('      5. Payload serialization: log the exact payload bytes above and diff them');
  console.error('         against Python\'s json.dumps(core, sort_keys=True).encode() for the same');
  console.error('         transaction dict -- key order, separators, and number formatting all matter.');
}

// ---------------------------------------------------------------------
// Scenario 1 (Phase F2): integer amount/fee, unfunded sender.
async function runIntegerAmountTest() {
  console.log('=== Test 1: integer amount/fee (0/0), unfunded sender ===\n');

  const sender = generateWallet();
  console.log('Generated public key (wallet.py-compatible PEM):');
  console.log(sender.publicKeyPem);

  const recipient = generateWallet();

  // amount/fee are 0 so this passes add_transaction()'s balance check
  // too (an unfunded, freshly-generated key has zero balance) -- the
  // thing under test here is signature verification specifically, not
  // funding this throwaway wallet first.
  const transaction = { from: sender.publicKeyPem, to: recipient.publicKeyPem, amount: 0, fee: 0 };
  const { payload, signatureHex } = signTransaction(transaction, sender.secretKey);
  console.log("Signing payload (must match Python's _signing_payload() byte-for-byte):");
  console.log('  ' + new TextDecoder().decode(payload) + '\n');
  console.log(`DER-encoded signature, hex (${signatureHex.length / 2} bytes): ${signatureHex}\n`);

  transaction.signature = signatureHex;
  transaction.sender_public_key = sender.publicKeyPem;

  const { status, body } = await postTransaction(transaction);
  console.log(`POST ${NODE_URL}/transactions/new -> HTTP ${status}`);
  console.log(body);

  if (status === 200) {
    console.log('\nPASS: a signature produced entirely in JS (@noble/curves) was accepted by the');
    console.log('existing Python wallet.verify_signature() with no format-conversion hacks.\n');
    return true;
  }

  console.error('\nFAIL: the Python backend rejected the JS-signed transaction.');
  console.error(`Detail: ${body.detail ?? '(no detail field)'}`);
  printDiagnosisChecklist();
  return false;
}

// ---------------------------------------------------------------------
// Scenario 2 (Phase F3 Part 1): non-integer amount/fee, funded sender.
async function runFloatAmountTest() {
  console.log('\n=== Test 2: non-integer amount/fee (4.5/0.5), funded sender ===\n');

  const sender = generateWallet();
  const recipient = generateWallet();

  console.log(`Mining a block as the sender itself to fund it (BLOCK_REWARD)...`);
  const mineResult = await mine(sender.publicKeyPem);
  if (mineResult.status !== 200) {
    console.error(`FAIL: could not fund the test sender -- mine() returned HTTP ${mineResult.status}`);
    console.error(mineResult.body);
    return false;
  }
  const balanceAfterMining = await getBalance(sender.publicKeyPem);
  console.log(`Sender balance after mining: ${balanceAfterMining}\n`);

  const transaction = { from: sender.publicKeyPem, to: recipient.publicKeyPem, amount: 4.5, fee: 0.5 };
  const { payload, signatureHex } = signTransaction(transaction, sender.secretKey);
  console.log("Signing payload (must match Python's _signing_payload() byte-for-byte):");
  console.log('  ' + new TextDecoder().decode(payload) + '\n');
  console.log(`DER-encoded signature, hex (${signatureHex.length / 2} bytes): ${signatureHex}\n`);

  transaction.signature = signatureHex;
  transaction.sender_public_key = sender.publicKeyPem;

  const { status, body } = await postTransaction(transaction);
  console.log(`POST ${NODE_URL}/transactions/new -> HTTP ${status}`);
  console.log(body);

  if (status === 200) {
    console.log('\nPASS: a non-integer amount/fee (4.5/0.5), signed in JS, was accepted -- both the');
    console.log('signature AND the balance check passed (sender was funded well above 5.0), so this');
    console.log('is a genuine end-to-end pass, not just "balance blocked it before signature mattered".');
    console.log('\nCONCLUSION: the int/float JSON-formatting concern does NOT affect client-signed');
    console.log('amount/fee fields in practice. Both languages render 4.5 and 0.5 identically (shortest');
    console.log('round-trip float-to-string, and both values are exactly representable in binary --');
    console.log('no rounding ambiguity). BLOCK_REWARD\'s "10.0" vs "10" formatting difference is a');
    console.log('server-side-only concern (the coinbase amount is never signed by any client) and');
    console.log('never reaches this code path. No special number-formatting logic is needed in');
    console.log('src/lib/crypto.js beyond the plain JSON.stringify already used for signing payload.\n');
    return true;
  }

  if (body.detail && body.detail.toLowerCase().includes('balance')) {
    console.error('\nFAIL (inconclusive): rejected for balance, not signature -- the sender was not');
    console.error('funded enough. This is a test-setup bug, not a crypto compatibility finding.');
    return false;
  }

  console.error('\nFAIL: the Python backend rejected the JS-signed non-integer transaction specifically');
  console.error('for its signature. This means Python and JS produced BYTE-DIFFERENT signing payloads');
  console.error('for a non-integer amount/fee -- diagnose the exact difference (compare the printed');
  console.error('payload above against a Python-side dump of json.dumps(core, sort_keys=True) for the');
  console.error('identical transaction dict) before building any wallet UI on this assumption.');
  console.error(`Detail: ${body.detail ?? '(no detail field)'}`);
  return false;
}

async function main() {
  console.log(`Verifying JS (@noble/curves secp256k1) <-> Python signature compatibility against ${NODE_URL}\n`);

  const integerPassed = await runIntegerAmountTest();
  const floatPassed = await runFloatAmountTest();

  console.log('\n=== Summary ===');
  console.log(`Test 1 (integer amount/fee):     ${integerPassed ? 'PASS' : 'FAIL'}`);
  console.log(`Test 2 (non-integer amount/fee): ${floatPassed ? 'PASS' : 'FAIL'}`);

  // process.exitCode (not process.exit()) lets Node drain pending I/O
  // (fetch's keep-alive sockets) before exiting naturally -- calling
  // process.exit() here race-crashed with an open fetch handle on
  // Windows (libuv assertion in src/win/async.c), a benign but noisy
  // shutdown quirk unrelated to the actual test results.
  process.exitCode = integerPassed && floatPassed ? 0 : 1;
}

main().catch((err) => {
  console.error('Script error:', err);
  process.exitCode = 1;
});
