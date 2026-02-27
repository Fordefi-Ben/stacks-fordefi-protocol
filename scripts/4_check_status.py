"""
4_check_status.py
-----------------
Step 4: Verify a deployment by checking both Fordefi and the Stacks blockchain.

Usage:
    # Check a Fordefi transaction:
    python scripts/4_check_status.py --tx-id <fordefi_transaction_uuid>

    # Check a deployed contract on-chain:
    python scripts/4_check_status.py --contract ST1PQHQ...GMM.my-contract

    # Check both:
    python scripts/4_check_status.py \
        --tx-id <fordefi_tx_id> \
        --contract ST1PQHQ...GMM.my-contract

Environment variables required:
    FORDEFI_API_TOKEN
    FORDEFI_PRIVATE_KEY_PATH
"""

import argparse
import json
import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from fordefi_client import FordefiClient

load_dotenv(Path(__file__).parent.parent / ".env")

API_TOKEN = os.environ["FORDEFI_API_TOKEN"]
PRIVATE_KEY_PATH = os.getenv("FORDEFI_PRIVATE_KEY_PATH", "./keys/private_key.pem")
STACKS_NETWORK = os.getenv("STACKS_NETWORK", "testnet")

HIRO_API_BASE = {
    "testnet": "https://api.testnet.hiro.so",
    "mainnet": "https://api.hiro.so",
}
EXPLORER_BASE = "https://explorer.hiro.so"


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def check_fordefi_tx(tx_id: str) -> None:
    """Print the current state of a Fordefi transaction."""
    print(f"\n{'─'*50}")
    print(f"  Fordefi Transaction: {tx_id}")
    print(f"{'─'*50}")

    client = FordefiClient(api_token=API_TOKEN, private_key_path=PRIVATE_KEY_PATH)
    tx = client.get_transaction(tx_id)

    state = tx.get("state", "unknown")
    created_at = tx.get("created_at", "")
    modified_at = tx.get("modified_at", "")
    tx_type = tx.get("type", "")

    print(f"  State:      {state}")
    print(f"  Type:       {tx_type}")
    print(f"  Created:    {created_at}")
    print(f"  Modified:   {modified_at}")

    # On-chain tx hash (field name may vary by API version)
    chain_txid = (
        tx.get("blockchain_txid")
        or tx.get("transaction_hash")
        or tx.get("details", {}).get("txid")
    )
    if chain_txid:
        print(f"  Chain TXID: {chain_txid}")
        print(f"  Explorer:   {EXPLORER_BASE}/txid/{chain_txid}?chain={STACKS_NETWORK}")

    if state == "failed":
        err = tx.get("failure_reason") or tx.get("error") or "No reason provided"
        print(f"  ❌ Failure reason: {err}")

    print()


def check_contract_on_chain(contract_id: str) -> None:
    """
    Verify a Clarity contract is deployed on-chain via the Hiro Stacks API.

    contract_id format: <deployer_address>.<contract_name>
                 e.g.:  ST1PQHQKV0RJXZFY1DGX8MNSNYVE3VGZJSRTPGZGM.hello-world
    """
    print(f"\n{'─'*50}")
    print(f"  On-chain Contract: {contract_id}")
    print(f"{'─'*50}")

    base_url = HIRO_API_BASE.get(STACKS_NETWORK, HIRO_API_BASE["testnet"])
    url = f"{base_url}/v2/contracts/interface/{contract_id}"

    resp = requests.get(url, timeout=15)

    if resp.status_code == 200:
        data = resp.json()
        funcs = data.get("functions", [])
        read_fns = [f["name"] for f in funcs if f.get("access") == "read_only"]
        pub_fns = [f["name"] for f in funcs if f.get("access") == "public"]

        print(f"  ✅ Contract is DEPLOYED and verified on {STACKS_NETWORK}!")
        print(f"  Public functions:    {', '.join(pub_fns) if pub_fns else '(none)'}")
        print(f"  Read-only functions: {', '.join(read_fns) if read_fns else '(none)'}")
        print(f"  Explorer: {EXPLORER_BASE}/address/{contract_id}?chain={STACKS_NETWORK}")
    elif resp.status_code == 404:
        print(f"  ⏳ Contract not found yet. It may still be confirming.")
        print(f"     Wait ~30 seconds and try again.")
        print(f"     Explorer: {EXPLORER_BASE}/address/{contract_id}?chain={STACKS_NETWORK}")
    else:
        print(f"  ❌ Unexpected response: {resp.status_code}")
        print(f"  Body: {resp.text[:300]}")

    print()


def check_address_balance(address: str) -> None:
    """Print the STX balance for a vault address."""
    print(f"\n{'─'*50}")
    print(f"  Balance check: {address}")
    print(f"{'─'*50}")

    base_url = HIRO_API_BASE.get(STACKS_NETWORK, HIRO_API_BASE["testnet"])
    url = f"{base_url}/extended/v1/address/{address}/balances"

    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        stx = data.get("stx", {})
        balance_ustx = int(stx.get("balance", 0))
        locked_ustx = int(stx.get("locked", 0))
        print(f"  STX balance: {balance_ustx / 1e6:.6f} STX  ({balance_ustx} microSTX)")
        if locked_ustx:
            print(f"  Locked:      {locked_ustx / 1e6:.6f} STX")
    except Exception as e:
        print(f"  Could not fetch balance: {e}")

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verify a Fordefi transaction and/or on-chain Stacks contract."
    )
    parser.add_argument("--tx-id", help="Fordefi transaction UUID to check.")
    parser.add_argument(
        "--contract",
        help="On-chain contract to verify. Format: <address>.<name>",
    )
    parser.add_argument(
        "--address",
        help="Stacks address to check balance for.",
    )
    args = parser.parse_args()

    if not any([args.tx_id, args.contract, args.address]):
        parser.print_help()
        print("\n⚠️  Provide at least one of --tx-id, --contract, or --address.")
        sys.exit(1)

    if args.tx_id:
        check_fordefi_tx(args.tx_id)

    if args.contract:
        check_contract_on_chain(args.contract)

    if args.address:
        check_address_balance(args.address)


if __name__ == "__main__":
    main()
