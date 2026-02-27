"""
0_generate_keys.py
------------------
Step 0: Generate an ECDSA P-256 key pair for Fordefi API request signing.

Run this once before any other script.  Keep the private key secure —
it is used to sign every API request you send to Fordefi.

Usage:
    python scripts/0_generate_keys.py

Output:
    keys/private_key.pem   ← KEEP SECRET; used at runtime to sign requests
    keys/public_key.pem    ← Upload to Fordefi when registering your API User
"""

import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

KEYS_DIR = Path(__file__).parent.parent / "keys"
PRIVATE_KEY_PATH = KEYS_DIR / "private_key.pem"
PUBLIC_KEY_PATH = KEYS_DIR / "public_key.pem"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    KEYS_DIR.mkdir(exist_ok=True)

    # Safety check: don't overwrite an existing key pair
    if PRIVATE_KEY_PATH.exists():
        print(f"⚠️  Private key already exists at {PRIVATE_KEY_PATH}")
        print("   Delete it manually if you want to regenerate.")
        return

    print("Generating ECDSA P-256 key pair...")

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    # Serialize private key — PKCS8 PEM, no encryption
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )

    # Serialize public key — SubjectPublicKeyInfo PEM
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )

    PRIVATE_KEY_PATH.write_bytes(private_pem)
    os.chmod(PRIVATE_KEY_PATH, 0o600)  # Restrict to owner read/write only

    PUBLIC_KEY_PATH.write_bytes(public_pem)

    print(f"✅ Private key saved to: {PRIVATE_KEY_PATH}  (permissions: 600)")
    print(f"✅ Public key saved to:  {PUBLIC_KEY_PATH}")
    print()
    print("Next steps:")
    print("  1. Log into the Fordefi console.")
    print("  2. Navigate to User Management → API Users.")
    print("  3. Create a new API User with the 'Trader' role.")
    print("  4. Upload the contents of keys/public_key.pem to the API User.")
    print("  5. Copy the generated access token into your .env file as FORDEFI_API_TOKEN.")
    print()
    print("⚠️  NEVER commit keys/private_key.pem to version control.")


if __name__ == "__main__":
    main()
