#!/usr/bin/env python
"""
Phase 18: CLI wallet tool — a thin wrapper over the existing HTTP API,
replacing raw curl for interactive use. Every subcommand does exactly
what its endpoint already expects: sign locally with the wallet's own
private key where a signature is needed (same pattern every earlier
phase already established — the server never sees a private key), then
hit the node.

Usage:
    python scripts/wallet_cli.py generate alice.json
    python scripts/wallet_cli.py balance http://localhost:5001 alice.json
    python scripts/wallet_cli.py send http://localhost:5001 alice.json bob.json 10 --fee 1
    python scripts/wallet_cli.py stake http://localhost:5001 alice.json 900
    python scripts/wallet_cli.py mine http://localhost:5001 alice.json
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "node"))

import requests  # noqa: E402
from wallet import Wallet  # noqa: E402


def _load_wallet(wallet_file: str) -> Wallet:
    data = json.loads(Path(wallet_file).read_text())
    return Wallet.from_private_key_pem(data["private_key_pem"])


def _resolve_public_key(value: str) -> str:
    """
    `send`'s recipient can be given as another wallet file (the common
    case — PEM strings are multi-line and awkward to paste as a raw CLI
    arg) or, if no such file exists, treated as a literal PEM string.
    """
    path = Path(value)
    if path.exists():
        return json.loads(path.read_text())["public_key_pem"]
    return value


def cmd_generate(args):
    wallet = Wallet()
    data = {"private_key_pem": wallet.private_key_pem, "public_key_pem": wallet.public_key_pem}
    Path(args.wallet_file).write_text(json.dumps(data, indent=2))
    print(f"Generated new wallet -> {args.wallet_file}")
    print(f"Public key:\n{wallet.public_key_pem}")


def cmd_balance(args):
    wallet = _load_wallet(args.wallet_file)
    response = requests.get(f"{args.node_url}/balance", params={"public_key": wallet.public_key_pem})
    response.raise_for_status()
    print(f"Balance: {response.json()['balance']}")


def cmd_send(args):
    wallet = _load_wallet(args.wallet_file)
    recipient_pem = _resolve_public_key(args.to_pubkey)
    transaction = {
        "from": wallet.public_key_pem,
        "to": recipient_pem,
        "amount": args.amount,
        "fee": args.fee,
    }
    transaction["signature"] = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem

    response = requests.post(f"{args.node_url}/transactions/new", json=transaction)
    print(f"[{response.status_code}] {response.json()}")


def cmd_stake(args):
    wallet = _load_wallet(args.wallet_file)
    payload = {
        "from": wallet.public_key_pem,
        "to": f"STAKE:{wallet.public_key_pem}",
        "amount": args.amount,
    }
    signature = wallet.sign_transaction(payload)

    response = requests.post(
        f"{args.node_url}/stake",
        params={"public_key": wallet.public_key_pem, "amount": args.amount, "signature": signature},
    )
    print(f"[{response.status_code}] {response.json()}")


def cmd_mine(args):
    wallet = _load_wallet(args.wallet_file)
    response = requests.get(f"{args.node_url}/mine", params={"miner_public_key": wallet.public_key_pem})
    print(f"[{response.status_code}] {response.json()}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="CLI wallet for the blockchain-network-sim node API")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generate_parser = subparsers.add_parser("generate", help="Create a new wallet and save it to a file")
    generate_parser.add_argument("wallet_file")
    generate_parser.set_defaults(func=cmd_generate)

    balance_parser = subparsers.add_parser("balance", help="Check a wallet's confirmed balance")
    balance_parser.add_argument("node_url")
    balance_parser.add_argument("wallet_file")
    balance_parser.set_defaults(func=cmd_balance)

    send_parser = subparsers.add_parser("send", help="Sign and submit a transaction")
    send_parser.add_argument("node_url")
    send_parser.add_argument("wallet_file")
    send_parser.add_argument("to_pubkey", help="Recipient's wallet file, or a raw PEM string")
    send_parser.add_argument("amount", type=float)
    send_parser.add_argument("--fee", type=float, default=0)
    send_parser.set_defaults(func=cmd_send)

    stake_parser = subparsers.add_parser("stake", help="Stake to become an active validator")
    stake_parser.add_argument("node_url")
    stake_parser.add_argument("wallet_file")
    stake_parser.add_argument("amount", type=float)
    stake_parser.set_defaults(func=cmd_stake)

    mine_parser = subparsers.add_parser("mine", help="Mine a block, paid out to this wallet")
    mine_parser.add_argument("node_url")
    mine_parser.add_argument("wallet_file")
    mine_parser.set_defaults(func=cmd_mine)

    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
