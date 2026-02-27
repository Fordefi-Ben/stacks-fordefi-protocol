"""
3_deploy_contract.py
--------------------
Step 3: Deploy a Clarity smart contract to Stacks testnet via the Fordefi API.

This is the core script of the protocol.  It:
  1. Reads the Clarity contract source code from a .clar file.
  2. Builds the Fordefi CreateTransaction payload.
  3. Signs and submits the request to Fordefi.
  4. Polls until the transaction reaches a terminal state.
  5. Prints the on-chain transaction ID and a Stacks Explorer link.

Usage:
    # Deploy the default hello_world.clar:
    python scripts/3_deploy_contract.py

    # Deploy a custom contract:
    python scripts/3_deploy_contract.py \
        --contract-file ./examples/counter.clar \
        --contract-name my-counter \
        --fee-priority high

Environment variables required:
    FORDEFI_API_TOKEN         Bearer token from the Fordefi console
    FORDEFI_PRIVATE_KEY_PATH  Path to private_key.pem
    FORDEFI_VAULT_ID          UUID of the Stacks vault (set by 1_create_vault.py)

Environment variables optional:
    STACKS_NETWORK            'testnet' (default) or 'mainnet'
    CONTRACT_NAME             Default contract name (overridden by --contract-name)
    CONTRACT_FILE_PATH        Default .clar file path (overridden by --contract-file)
"""

import argparse
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).parent))
from fordefi_client import FordefiClient, build_stacks_contract_deploy

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).parent.parent / ".env")

API_TOKEN = os.environ["FORDEFI_API_TOKEN"]
PRIVATE_KEY_PATH = os.getenv("FORDEFI_PRIVATE_KEY_PATH", "./keys/private_key.pem")
VAULT_ID = os.environ["FORDEFI_VAULT_ID"]
STACKS_NETWORK = os.getenv("STACKS_NETWORK", "testnet")

DEFAULT_CONTRACT_NAME = os.getenv("CONTRACT_NAME", "hello-world")
DEFAULT_CONTRACT_FILE = os.getenv(
    "CONTRACT_FILE_PATH",
    str(Path(__file__).parent.parent / "examples" / "hello_world.clar"),
)

EXPLORER_BASE = "https://explorer.hiro.so"


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy a Clarity smart contract via the Fordefi API."
    )
    parser.add_argument(
        "--contract-file",
        default=DEFAULT_CONTRACT_FILE,
        help=f"Path to the .clar file to deploy. Default: {DEFAULT_CONTRACT_FILE}",
    )
    parser.add_argument(
        "--contract-name",
        default=DEFAULT_CONTRACT_NAME,
        help=f"Name to give the deployed contract. Default: {DEFAULT_CONTRACT_NAME}",
    )
    parser.add_argument(
        "--fee-priority",
        choices=["low", "medium", "high"],
        default="medium",
        help="Transaction fee priority. Default: medium",
    )
    parser.add_argument(
        "--push-mode",
        choices=["auto", "manual"],
        default="auto",
        help=(
            "auto: Fordefi broadcasts the tx. "
            "manual: Fordefi signs only; you broadcast. Default: auto"
        ),
    )
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Return immediately after submitting (don't poll for completion).",
    )
    return parser.parse_args()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    args = parse_args()

    # -- Resolve and validate the contract file --------------------------------
    contract_path = Path(args.contract_file).resolve()
    if not contract_path.exists():
        print(f"❌ Contract file not found: {contract_path}")
        sys.exit(1)

    clarity_code = contract_path.read_text(encoding="utf-8")
    contract_name = args.contract_name.lower().replace(" ", "-")
    chain = f"stacks_{STACKS_NETWORK}"

    print("=" * 60)
    print("  Fordefi × Stacks — Contract Deployment")
    print("=" * 60)
    print(f"  Network:       {STACKS_NETWORK}")
    print(f"  Chain:         {chain}")
    print(f"  Vault ID:      {VAULT_ID}")
    print(f"  Contract name: {contract_name}")
    print(f"  Contract file: {contract_path.name}")
    print(f"  Fee priority:  {args.fee_priority}")
    print(f"  Push mode:     {args.push_mode}")
    print(f"  Code length:   {len(clarity_code)} chars")
    print("=" * 60)
    print()

    # -- Build the Fordefi transaction payload --------------------------------
    payload = build_stacks_contract_deploy(
        vault_id=VAULT_ID,
        contract_name=contract_name,
        clarity_code=clarity_code,
        chain=chain,
        fee_priority=args.fee_priority,
        push_mode=args.push_mode,
        note=f"Deploy {contract_name} to {STACKS_NETWORK}",
    )

    print("Transaction payload:")
    # Redact the full Clarity code to keep output readable
    display_payload = json.loads(json.dumps(payload))
    display_payload["details"]["clarity_code"] = (
        clarity_code[:80] + "..." if len(clarity_code) > 80 else clarity_code
    )
    print(json.dumps(display_payload, indent=2))
    print()

    # -- Submit to Fordefi ----------------------------------------------------
    client = FordefiClient(api_token=API_TOKEN, private_key_path=PRIVATE_KEY_PATH)

    print("Submitting transaction to Fordefi...")
    tx = client.create_transaction(payload)

    fordefi_tx_id = tx["id"]
    initial_state = tx.get("state", "unknown")

    print(f"✅ Transaction submitted!")
    print(f"   Fordefi TX ID: {fordefi_tx_id}")
    print(f"   Initial state: {initial_state}")
    print()

    if args.no_wait:
        print("--no-wait flag set. Exiting early.")
        print(f"Check status: python scripts/4_check_status.py --tx-id {fordefi_tx_id}")
        return

    # -- Poll until terminal state --------------------------------------------
    print("Polling for completion (this may take 30–120 seconds)...")
    final_tx = client.wait_for_transaction(fordefi_tx_id, poll_interval=8, timeout=300)

    final_state = final_tx.get("state", "unknown")
    print()

    if final_state == "completed":
        # Extract the on-chain Stacks transaction hash
        chain_tx_id = (
            final_tx.get("blockchain_txid")
            or final_tx.get("transaction_hash")
            or final_tx.get("details", {}).get("txid")
            or final_tx.get("details", {}).get("transaction_hash")
            or "<check Fordefi console>"
        )
        print("🎉 Contract deployed successfully!")
        print(f"   On-chain TX ID: {chain_tx_id}")
        print(
            f"   Explorer: {EXPLORER_BASE}/txid/{chain_tx_id}?chain={STACKS_NETWORK}"
        )
        print()
        print("Your contract is live at:")
        # Stacks contract addresses are in the form: <deployer_address>.<contract_name>
        print(f"   <vault_address>.{contract_name}")
        print("   (Find your vault address in the Fordefi console.)")
    elif final_state == "failed":
        print("❌ Transaction failed.")
        error = final_tx.get("failure_reason") or final_tx.get("error") or "Unknown error"
        print(f"   Reason: {error}")
        sys.exit(1)
    else:
        print(f"⚠️  Transaction ended in unexpected state: {final_state}")
        print(json.dumps(final_tx, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
