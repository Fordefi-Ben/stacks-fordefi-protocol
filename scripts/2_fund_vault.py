"""
2_fund_vault.py
---------------
Step 2: Fund the Fordefi Stacks vault with testnet STX.

Uses the official Stacks testnet faucet to request 500 STX
to the vault address.  Testnet STX has no real-world value.

Usage:
    python scripts/2_fund_vault.py --address ST1PQHQKV0RJXZFY1DGX8MNSNYVE3VGZJSRTPGZGM
      OR
    python scripts/2_fund_vault.py
      (will prompt for the address if not set in .env as STACKS_VAULT_ADDRESS)

Prerequisites:
    - Vault created (run 1_create_vault.py first)
    - Vault's Stacks address available

Environment variables (optional):
    STACKS_VAULT_ADDRESS   The ST... testnet address of the vault
"""

import argparse
import os
import sys
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

HIRO_TESTNET_API = "https://api.testnet.hiro.so"
FAUCET_ENDPOINT = f"{HIRO_TESTNET_API}/extended/v1/faucets/stx"
EXPLORER_BASE = "https://explorer.hiro.so"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Fund a Stacks testnet address from the Hiro faucet."
    )
    parser.add_argument(
        "--address",
        default=os.getenv("STACKS_VAULT_ADDRESS"),
        help="The Stacks testnet address to fund (starts with ST...).",
    )
    args = parser.parse_args()

    address = args.address
    if not address:
        address = input("Enter the Stacks testnet vault address (ST...): ").strip()

    if not address.startswith("ST"):
        print("⚠️  Warning: Stacks testnet addresses typically start with 'ST'.")

    print(f"\nRequesting testnet STX for address: {address}")
    print(f"Faucet endpoint: {FAUCET_ENDPOINT}")

    response = requests.post(
        FAUCET_ENDPOINT,
        params={"address": address},
        headers={"Content-Type": "application/json"},
        timeout=30,
    )

    if response.status_code == 200:
        data = response.json()
        tx_id = data.get("txId") or data.get("txid") or data.get("tx_id", "unknown")
        print()
        print("✅ Faucet request successful!")
        print(f"   Transaction ID: {tx_id}")
        print(f"   Explorer: {EXPLORER_BASE}/txid/{tx_id}?chain=testnet")
        print()
        print("ℹ️  It may take 1-2 minutes for the STX to appear in your vault.")
        print("   Waiting 15 seconds, then checking balance...")
        time.sleep(15)
        _check_balance(address)
    elif response.status_code == 429:
        print("⚠️  Rate limited by faucet. Wait a few minutes and try again.")
        print("   Each address can request from the faucet at most once per day.")
    else:
        print(f"❌ Faucet request failed: {response.status_code}")
        print(response.text)
        sys.exit(1)

    print("\nNext step: Run python scripts/3_deploy_contract.py")


def _check_balance(address: str) -> None:
    """Query the Stacks API for the current STX balance."""
    url = f"{HIRO_TESTNET_API}/extended/v1/address/{address}/balances"
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        balance_ustx = int(data.get("stx", {}).get("balance", 0))
        balance_stx = balance_ustx / 1_000_000
        print(f"   Current balance: {balance_stx:.6f} STX ({balance_ustx} microSTX)")
    except Exception as e:
        print(f"   Could not fetch balance: {e}")


if __name__ == "__main__":
    main()
