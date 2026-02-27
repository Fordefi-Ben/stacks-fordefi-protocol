"""
1_create_vault.py
-----------------
Step 1: Create a Stacks vault in Fordefi.

A vault holds the cryptographic key for your Stacks address.
The vault address is where testnet STX will be sent in Step 2,
and from which contract deploy fees will be paid in Step 3.

Vault creation does NOT require request signing — only the bearer token.
You do not need to have run 0_generate_keys.py before this step.

Usage:
    python scripts/1_create_vault.py

Prerequisites:
    - .env file populated (copy from .env.example)
    - API User created in Fordefi console

Environment variables required:
    FORDEFI_API_TOKEN   Bearer token from the Fordefi console
"""

import json
import os
import sys
from pathlib import Path

# Allow running from project root or scripts/ directory
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv

from fordefi_client import FordefiClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

load_dotenv(Path(__file__).parent.parent / ".env")

VAULT_NAME = os.getenv("VAULT_NAME", "Stacks Testnet Vault")
VAULT_GROUP_ID = os.getenv("FORDEFI_VAULT_GROUP_ID")  # Optional

API_TOKEN = os.environ["FORDEFI_API_TOKEN"]

ENV_FILE = Path(__file__).parent.parent / ".env"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Vault creation only needs the bearer token — no signing key required.
    client = FordefiClient(api_token=API_TOKEN)

    print(f"Creating Stacks vault: '{VAULT_NAME}'...")

    vault = client.create_vault(name=VAULT_NAME, vault_group_id=VAULT_GROUP_ID)

    vault_id = vault["id"]
    # The Stacks address is nested under address data — path may vary by API version
    vault_address = (
        vault.get("address")
        or vault.get("addresses", {}).get("stacks")
        or vault.get("details", {}).get("address")
        or "<check Fordefi console>"
    )

    print()
    print("✅ Vault created successfully!")
    print(f"   Vault ID:      {vault_id}")
    print(f"   Stacks address: {vault_address}")
    print()

    # Persist the vault ID to the .env file so later scripts pick it up
    _update_env_file(vault_id)

    print("Next steps:")
    print("  • Copy the Stacks address above.")
    print("  • Run: python scripts/2_fund_vault.py")
    print()
    print("Full vault response:")
    print(json.dumps(vault, indent=2))


def _update_env_file(vault_id: str) -> None:
    """Append or update FORDEFI_VAULT_ID in the .env file."""
    if not ENV_FILE.exists():
        ENV_FILE.write_text(f"FORDEFI_VAULT_ID={vault_id}\n")
        print(f"📝 Created .env and set FORDEFI_VAULT_ID={vault_id}")
        return

    lines = ENV_FILE.read_text().splitlines(keepends=True)
    updated = False
    new_lines = []
    for line in lines:
        if line.startswith("FORDEFI_VAULT_ID="):
            new_lines.append(f"FORDEFI_VAULT_ID={vault_id}\n")
            updated = True
        else:
            new_lines.append(line)

    if not updated:
        new_lines.append(f"\nFORDEFI_VAULT_ID={vault_id}\n")

    ENV_FILE.write_text("".join(new_lines))
    print(f"📝 Updated .env with FORDEFI_VAULT_ID={vault_id}")


if __name__ == "__main__":
    main()
