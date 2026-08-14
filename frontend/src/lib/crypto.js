/**
 * Phase F3: client-side wallet crypto, using exactly the pipeline proven
 * compatible against the real Python backend in
 * scripts/verify_signing_compat.mjs (Phase F2 + F3 Part 1) — same curve
 * (secp256k1 via @noble/curves), same PEM construction, same payload
 * serialization, same DER signature encoding. Nothing here is a new
 * assumption; every choice below is empirically verified, not guessed.
 *
 * Confirmed by that script, against a live node, before this file was
 * written:
 *   - @noble/curves' sign()/verify() default (prehash: true) hashes the
 *     raw message internally with SHA-256, matching Python's
 *     ec.ECDSA(hashes.SHA256()) exactly — do NOT pre-hash the payload
 *     yourself, or you'll silently double-hash it.
 *   - Signatures must be DER-encoded ({ format: 'der' }), not the
 *     library's default compact r||s.
 *   - Non-integer amount/fee values (e.g. 4.5, 0.5) serialize identically
 *     in both languages — no special number formatting needed.
 */
import { secp256k1 } from "@noble/curves/secp256k1.js";

// Fixed 23-byte DER prefix for a secp256k1 SubjectPublicKeyInfo (SEQUENCE
// header + AlgorithmIdentifier{id-ecPublicKey, secp256k1 OIDs} + BIT
// STRING header), verified byte-for-byte against real wallet.py output —
// see verify_signing_compat.mjs for how this was confirmed. Only the
// 65-byte uncompressed point that follows differs per key.
const SECP256K1_SPKI_PREFIX_HEX = "3056301006072a8648ce3d020106052b8104000a034200";

function hexToBytes(hex) {
  const clean = hex.startsWith("0x") ? hex.slice(2) : hex;
  const bytes = new Uint8Array(clean.length / 2);
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = parseInt(clean.substr(i * 2, 2), 16);
  }
  return bytes;
}

function bytesToHex(bytes) {
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
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

function bytesToBase64(bytes) {
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function publicKeyToPem(uncompressedPublicKeyBytes) {
  const der = concatBytes(hexToBytes(SECP256K1_SPKI_PREFIX_HEX), uncompressedPublicKeyBytes);
  const base64 = bytesToBase64(der);
  const lines = base64.match(/.{1,64}/g) ?? [];
  return `-----BEGIN PUBLIC KEY-----\n${lines.join("\n")}\n-----END PUBLIC KEY-----\n`;
}

/**
 * Creates a new secp256k1 keypair. privateKey is a hex string (not raw
 * bytes) so it round-trips cleanly through JSON for wallet export/import —
 * signTransaction() converts it back internally.
 */
export function generateWallet() {
  const { secretKey } = secp256k1.keygen();
  const publicKeyUncompressed = secp256k1.getPublicKey(secretKey, false); // false = uncompressed
  return {
    privateKey: bytesToHex(secretKey),
    publicKeyPem: publicKeyToPem(publicKeyUncompressed),
  };
}

/**
 * Reproduces wallet.py's _signing_payload() exactly:
 *   core = {k: v for k, v in transaction.items() if k not in ("signature", "sender_public_key")}
 *   return json.dumps(core, sort_keys=True).encode()
 *
 * json.dumps(..., sort_keys=True) with no `separators` override uses
 * Python's default ", " / ": " separators — NOT plain JSON.stringify's
 * compact "," / ":" — so keys are sorted and re-serialized by hand here
 * rather than just calling JSON.stringify on a sorted object.
 */
function signingPayload(dictionary) {
  const { signature, sender_public_key, ...core } = dictionary;
  const keys = Object.keys(core).sort();
  const parts = keys.map((key) => `${JSON.stringify(key)}: ${JSON.stringify(core[key])}`);
  return new TextEncoder().encode(`{${parts.join(", ")}}`);
}

/**
 * Signs any transaction-shaped (or PoS header-shaped) plain object with
 * privateKey (a hex string from generateWallet()), matching
 * wallet.py's Wallet.sign_transaction() semantics: same field exclusions
 * (signature, sender_public_key never signed), same DER + SHA-256
 * scheme. Returns a hex string signature — the caller attaches it (and
 * sender_public_key, where applicable) to the object being submitted,
 * same two-step pattern every backend endpoint already expects.
 */
export function signTransaction(transaction, privateKey) {
  const payload = signingPayload(transaction);
  const secretKey = hexToBytes(privateKey);
  const signatureDerBytes = secp256k1.sign(payload, secretKey, { format: "der" });
  return bytesToHex(signatureDerBytes);
}
