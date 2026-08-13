"""
Phase 12: 51%-style double-spend demo.

Narrative: an attacker pays a merchant on the honest 5-node network,
the payment gets mined and is visible everywhere — then the attacker,
who has been secretly mining a private fork on an isolated node the
whole time, reconnects that longer fork and the honest nodes adopt it
via the ordinary longest-valid-chain rule, silently erasing the
merchant's payment.

This script is pure orchestration: it drives the existing HTTP API
(/transactions/new, /mine, /chain, /balance, /nodes/resolve) plus the
`docker` CLI (network disconnect/connect, exec) against a real
docker-compose network. It does not add or change any behavior in
blockchain.py / app.py / consensus.py / wallet.py / merkle.py — the
whole scenario is achievable with what those already expose.

Usage:
    python scripts/attack_demo.py

Requires Docker (docker-compose or the `docker compose` plugin) and
this repo's docker-compose.yml / node/ image. Rewrites
docker-compose.yml's INITIAL_BALANCES to fund a freshly-generated
attacker wallet, then brings the 5-node network up from scratch.
"""

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "node"))

import requests  # noqa: E402
from wallet import Wallet  # noqa: E402

COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
HONEST_PORTS = {"node1": 5001, "node2": 5002, "node3": 5003, "node4": 5004}
NODE5_PORT = 5005
ATTACKER_FUNDING = 100.0
PAYMENT_AMOUNT = 40.0
PAYMENT_FEE = 1.0


def banner(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def log(message: str):
    print(f"  -> {message}")


def run(cmd: list, **kwargs) -> subprocess.CompletedProcess:
    print(f"  $ {' '.join(cmd)}")
    return subprocess.run(
        cmd, check=True, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs
    )


def compose_base_cmd() -> list:
    """Prefer the standalone docker-compose CLI; fall back to `docker compose`."""
    if shutil.which("docker-compose"):
        return ["docker-compose"]
    return ["docker", "compose"]


def compose(*args) -> subprocess.CompletedProcess:
    return run(compose_base_cmd() + list(args), cwd=str(REPO_ROOT))


def sign_transaction(wallet: Wallet, to: str, amount: float, fee: float = 0) -> dict:
    transaction = {"from": wallet.public_key_pem, "to": to, "amount": amount, "fee": fee}
    transaction["signature"] = wallet.sign_transaction(transaction)
    transaction["sender_public_key"] = wallet.public_key_pem
    return transaction


def fund_attacker_in_compose(attacker_pem: str):
    """
    Rewrite docker-compose.yml's x-initial-balances anchor so every node's
    genesis block funds the attacker (and only the attacker — the
    merchant starts with nothing). All 5 services share this anchor, so
    one edit keeps every node's genesis identical (Phase 8's requirement).
    """
    content = COMPOSE_FILE.read_text()
    balances_json = json.dumps({attacker_pem: ATTACKER_FUNDING})
    new_line = f"  INITIAL_BALANCES: '{balances_json}'"
    # repl must be a function, not the literal string: re.sub treats backslash
    # sequences in a *string* replacement specially (\n -> a real newline, \1
    # -> a backreference), which would mangle the PEM's escaped \n's inside
    # the JSON into actual newlines and silently break the funding.
    updated, count = re.subn(
        r"^  INITIAL_BALANCES: .*$", lambda _match: new_line, content, count=1, flags=re.MULTILINE
    )
    if count == 0:
        raise RuntimeError(
            "Could not find an INITIAL_BALANCES line in docker-compose.yml to update — "
            "the x-initial-balances anchor may have moved or been renamed."
        )
    COMPOSE_FILE.write_text(updated)
    log(f"docker-compose.yml INITIAL_BALANCES now funds only the attacker with {ATTACKER_FUNDING}")


def wait_for_nodes(ports: list, timeout_seconds: int = 90):
    deadline = time.time() + timeout_seconds
    for port in ports:
        while True:
            try:
                response = requests.get(f"http://localhost:{port}/chain", timeout=2)
                if response.status_code == 200:
                    log(f"node on port {port} is up")
                    break
            except requests.RequestException:
                pass
            if time.time() > deadline:
                raise RuntimeError(f"node on port {port} never became reachable")
            time.sleep(1)


def container_id(service: str) -> str:
    return compose("ps", "-q", service).stdout.strip()


def discover_network_name(reference_container: str) -> str:
    result = run(
        [
            "docker",
            "inspect",
            "-f",
            "{{range $k, $v := .NetworkSettings.Networks}}{{$k}}{{end}}",
            reference_container,
        ]
    )
    return result.stdout.strip()


def docker_exec_python(container: str, code: str, env: dict = None) -> str:
    """
    Run a short Python snippet inside `container` via `docker exec`. Used
    for everything that happens on node5 once it's network-disconnected:
    its published port (5005) stops being routable from the host at that
    point, but a command executed inside the container's own network
    namespace can still reach its server over loopback. `requests` is
    already a project dependency baked into the image, so no extra
    tooling (curl, etc.) is needed inside the container.
    """
    cmd = ["docker", "exec"]
    for key, value in (env or {}).items():
        cmd += ["-e", f"{key}={value}"]
    cmd += [container, "python", "-c", code]
    result = run(cmd)
    return result.stdout.strip()


def node5_submit_transaction(container: str, transaction: dict):
    code = (
        "import json, os, requests\n"
        "tx = json.loads(os.environ['TX_JSON'])\n"
        "r = requests.post('http://localhost:5000/transactions/new', json=tx)\n"
        "print(r.status_code)\n"
        "print(r.text)\n"
    )
    output = docker_exec_python(container, code, env={"TX_JSON": json.dumps(transaction)})
    print(f"    node5 /transactions/new -> {output}")


def node5_mine(container: str, miner_pem: str) -> dict:
    code = (
        "import os, requests\n"
        "r = requests.get('http://localhost:5000/mine', params={'miner_public_key': os.environ['MINER_PEM']})\n"
        "print(r.status_code)\n"
    )
    output = docker_exec_python(container, code, env={"MINER_PEM": miner_pem})
    print(f"    node5 /mine -> {output}")
    return node5_chain_info(container)


def node5_chain_info(container: str) -> dict:
    code = "import requests; r = requests.get('http://localhost:5000/chain'); print(r.json()['length'])"
    length = int(docker_exec_python(container, code))
    return {"length": length}


def print_honest_state(label: str, merchant_pem: str):
    print(f"  {label}")
    for name, port in HONEST_PORTS.items():
        chain = requests.get(f"http://localhost:{port}/chain", timeout=5).json()
        balance = requests.get(
            f"http://localhost:{port}/balance", params={"public_key": merchant_pem}, timeout=5
        ).json()["balance"]
        print(f"    {name} (:{port}): chain length={chain['length']:<3} merchant balance={balance}")


def main():
    banner("STEP 1: generate wallets, fund the attacker's genesis balance")
    attacker = Wallet()
    attacker_alt = Wallet()  # a second address the attacker also controls
    merchant = Wallet()
    honest_miner = Wallet()  # arbitrary miner identity for the honest network
    log("generated attacker, attacker_alt, merchant, honest_miner wallets")
    log("merchant starts with NO initial balance — only the attacker is funded")

    fund_attacker_in_compose(attacker.public_key_pem)

    banner("Bringing up the 5-node network")
    # Phase 15: each node now persists its chain to a named volume
    # (CHAIN_STORAGE_PATH), which `docker-compose down` alone does NOT
    # remove — without -v, a second run of this script would load each
    # node's STALE chain from a previous run instead of starting fresh
    # from the newly-funded attacker wallet's genesis, breaking this
    # demo's fresh-network assumption.
    compose("down", "-v")
    compose("up", "-d", "--build")
    wait_for_nodes(list(HONEST_PORTS.values()) + [NODE5_PORT])

    node5_container = container_id("node5")
    network_name = discover_network_name(node5_container)
    log(f"node5 container: {node5_container}")
    log(f"docker network: {network_name}")

    banner("Registering node5 with the honest nodes")
    log("docker-compose.yml's SEED_PEERS only points node5 -> nodes 1-4, never the reverse,")
    log("so /nodes/resolve on 1-4 would have nothing to ask about node5's chain in step 5.")
    log("Fixing that with the existing /nodes/register endpoint (no code change needed):")
    for name, port in HONEST_PORTS.items():
        response = requests.post(
            f"http://localhost:{port}/nodes/register",
            params={"node_address": "http://node5:5000"},
            timeout=5,
        )
        log(f"{name} registered node5 -> {response.status_code} {response.json()}")

    banner("STEP 2: disconnect node5 BEFORE any payment happens")
    run(["docker", "network", "disconnect", network_name, node5_container])
    log("node5 is now isolated — it will never see the honest payment below")

    banner("STEP 3: honest payment — attacker pays merchant on nodes 1-4")
    payment = sign_transaction(attacker, merchant.public_key_pem, PAYMENT_AMOUNT, PAYMENT_FEE)
    submit = requests.post("http://localhost:5001/transactions/new", json=payment, timeout=10)
    log(f"POST node1 /transactions/new -> {submit.status_code} {submit.json()}")

    mine = requests.get(
        "http://localhost:5001/mine", params={"miner_public_key": honest_miner.public_key_pem}, timeout=30
    )
    log(f"GET node1 /mine -> {mine.status_code}, block index {mine.json()['index']}")

    time.sleep(1)  # let broadcast_block's synchronous peer POSTs settle
    print_honest_state("Honest network state AFTER the payment is mined:", merchant.public_key_pem)
    merchant_balance_before = requests.get(
        "http://localhost:5001/balance", params={"public_key": merchant.public_key_pem}, timeout=5
    ).json()["balance"]
    attacker_balance_before = requests.get(
        "http://localhost:5001/balance", params={"public_key": attacker.public_key_pem}, timeout=5
    ).json()["balance"]
    honest_chain_length = requests.get("http://localhost:5001/chain", timeout=5).json()["length"]

    banner("STEP 4: on isolated node5, the attacker double-spends the SAME funds")
    double_spend = sign_transaction(attacker, attacker_alt.public_key_pem, PAYMENT_AMOUNT, fee=0)
    log("submitting a different transaction from the same attacker wallet — same money, sent to")
    log("attacker_alt instead of the merchant (node5 has never heard of the merchant payment)")
    node5_submit_transaction(node5_container, double_spend)

    info = node5_mine(node5_container, attacker.public_key_pem)
    log(f"node5 chain length after mining the double-spend: {info['length']}")

    while info["length"] <= honest_chain_length:
        info = node5_mine(node5_container, attacker.public_key_pem)
        log(f"node5 mining alone... chain length now {info['length']} (honest network is at {honest_chain_length})")
    log(f"node5's private chain (length {info['length']}) now exceeds the honest network's (length {honest_chain_length})")

    banner("STEP 5: reconnect node5 and let the honest nodes resolve")
    # --alias node5 matters: docker-compose sets that DNS alias (the service
    # name other containers use, e.g. "http://node5:5000" in SEED_PEERS) when
    # it originally creates the attachment, but a bare `docker network
    # connect` after a disconnect does NOT restore it automatically — without
    # this flag node5 rejoins the network with a working IP but no name the
    # other containers can resolve, and /nodes/resolve silently finds nothing.
    run(["docker", "network", "connect", "--alias", "node5", network_name, node5_container])
    time.sleep(2)  # give the reattached interface a moment before we hit it via peer HTTP calls

    for name, port in HONEST_PORTS.items():
        resolved = requests.post(f"http://localhost:{port}/nodes/resolve", timeout=15).json()
        log(f"POST {name} /nodes/resolve -> {resolved}")

    print_honest_state("Honest network state AFTER resolving against node5's longer chain:", merchant.public_key_pem)
    merchant_balance_after = requests.get(
        "http://localhost:5001/balance", params={"public_key": merchant.public_key_pem}, timeout=5
    ).json()["balance"]
    attacker_balance_after = requests.get(
        "http://localhost:5001/balance", params={"public_key": attacker.public_key_pem}, timeout=5
    ).json()["balance"]
    attacker_alt_balance_after = requests.get(
        "http://localhost:5001/balance", params={"public_key": attacker_alt.public_key_pem}, timeout=5
    ).json()["balance"]

    banner("STEP 6: summary")
    print(f"  merchant balance   : {merchant_balance_before}  ->  {merchant_balance_after}")
    print(f"  attacker balance   : {attacker_balance_before}  ->  {attacker_balance_after}")
    print(f"  attacker_alt balance (where the money actually ended up): {attacker_alt_balance_after}")
    print(
        "\n  A payment that was mined, broadcast, and visible on every honest node's chain\n"
        "  was silently reversed once a longer competing chain surfaced, because every\n"
        "  node in this network unconditionally adopts whichever valid chain is longest\n"
        "  — with no notion of a transaction ever being permanently 'final'.\n"
    )


if __name__ == "__main__":
    main()
