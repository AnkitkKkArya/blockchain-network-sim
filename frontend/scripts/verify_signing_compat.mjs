#!/usr/bin/env node
/**
 * Phase F2: prove a browser-compatible secp256k1 signing pipeline built
 * in JS produces signatures the existing Python backend's
 * wallet.verify_signature() actually accepts -- before any wallet UI
 * gets built on top of that assumption. Standalone: run with `node`,
 * not part of the Vite app / bundled into anything shipped.
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
 * "double-hashing" note in main() for how that was diagnosed.)
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
// Step 3: reproduce wallet.py's Wallet.public_key_pem EXACTLY.
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

// ---------------------------------------------------------------------
// Step 2: reproduce wallet.py's _signing_payload() EXACTLY.
//
//   core = {k: v for k, v in transaction.items() if k not in ("signature", "sender_public_key")}
//   return json.dumps(core, sort_keys=True).encode()
//
// json.dumps(..., sort_keys=True) with no `separators` override uses
// Python's DEFAULT separators, ", " and ": " -- with the spaces. That
// is NOT what JSON.stringify produces (JS's default separators are
// "," and ":", no spaces), so plain JSON.stringify(sortedObj) would
// silently produce a byte-different payload and thus a signature that
// verifies fine in JS but fails Python. Confirmed by inspecting actual
// output:
//   >>> json.dumps({"amount": 10, "from": "A"}, sort_keys=True)
//   '{"amount": 10, "from": "A"}'
// This only needs to handle flat dicts of strings/numbers, which is
// all this project's transactions ever are -- see the note in main()
// about float formatting for what a more general Phase F3 serializer
// would additionally need to handle.
function pythonSortedJsonDumps(obj) {
  const keys = Object.keys(obj).sort();
  const parts = keys.map((key) => `${JSON.stringify(key)}: ${JSON.stringify(obj[key])}`);
  return `{${parts.join(', ')}}`;
}

function signingPayloadBytes(transaction) {
  const { signature, sender_public_key, ...core } = transaction;
  return new TextEncoder().encode(pythonSortedJsonDumps(core));
}

async function main() {
  console.log(`Verifying JS (@noble/curves secp256k1) <-> Python signature compatibility against ${NODE_URL}\n`);

  // 1. Generate a secp256k1 key pair in JS.
  const { secretKey } = secp256k1.keygen();
  const publicKeyUncompressed = secp256k1.getPublicKey(secretKey, false); // false = uncompressed (0x04 || X || Y)
  const publicKeyPem = publicKeyToPem(publicKeyUncompressed);
  console.log('Generated public key (wallet.py-compatible PEM):');
  console.log(publicKeyPem);

  const recipientKeygen = secp256k1.keygen();
  const recipientPem = publicKeyToPem(secp256k1.getPublicKey(recipientKeygen.secretKey, false));

  // 2. Sign a test payload -- same shape and serialization as wallet.py.
  // amount/fee are 0 so this passes add_transaction()'s balance check
  // too (an unfunded, freshly-generated key has zero balance) -- the
  // thing under test here is signature verification specifically, not
  // funding this throwaway wallet first.
  const transaction = { from: publicKeyPem, to: recipientPem, amount: 0, fee: 0 };
  const payload = signingPayloadBytes(transaction);
  console.log('Signing payload (must match Python\'s _signing_payload() byte-for-byte):');
  console.log('  ' + new TextDecoder().decode(payload) + '\n');

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
  const signatureDerHex = Buffer.from(signatureDerBytes).toString('hex');

  transaction.signature = signatureDerHex;
  transaction.sender_public_key = publicKeyPem;

  console.log(`DER-encoded signature, hex (${signatureDerHex.length / 2} bytes): ${signatureDerHex}\n`);

  // 4. POST it to the running Python backend and confirm acceptance.
  const response = await fetch(`${NODE_URL}/transactions/new?broadcast=false`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(transaction),
  });
  const body = await response.json();

  console.log(`POST ${NODE_URL}/transactions/new -> HTTP ${response.status}`);
  console.log(body);

  if (response.status === 200) {
    console.log('\nPASS: a signature produced entirely in JS (@noble/curves) was accepted by the');
    console.log('existing Python wallet.verify_signature() with no format-conversion hacks.');
    console.log(
      'Note for Phase F3: this script sidesteps float formatting (amount=0 as an int on both',
    );
    console.log(
      'sides) -- Python renders 10.0 as "10.0" while JSON.stringify(10.0) renders "10". Any',
    );
    console.log(
      'transaction field that is a Python float must be serialized to match that exact string',
    );
    console.log('representation, or the signed payload bytes will diverge.');
    process.exit(0);
  }

  console.error('\nFAIL: the Python backend rejected the JS-signed transaction.');
  console.error(`Detail: ${body.detail ?? '(no detail field)'}`);
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
  process.exit(1);
}

main().catch((err) => {
  console.error('Script error:', err);
  process.exit(1);
});
