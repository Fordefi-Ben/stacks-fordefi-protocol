"""
fordefi_client.py
-----------------
Shared Fordefi API client for all scripts in this protocol.

Handles:
  - Bearer token authentication (all endpoints)
  - ECDSA P-256 request signing (transaction endpoints only)
  - Base HTTP request helpers

Signing requirements:
  - POST /api/v1/transactions  → signed  (private key required)
  - POST /api/v1/vaults        → unsigned (bearer token only)
  - GET  *                     → unsigned (bearer token only)
"""

import base64
import json
import time
from pathlib import Path
from typing import Optional

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FORDEFI_BASE_URL = "https://api.fordefi.com"


# ---------------------------------------------------------------------------
# Request signing
# ---------------------------------------------------------------------------

def _load_private_key(pem_path: str) -> ec.EllipticCurvePrivateKey:
    """Load an ECDSA P-256 private key from a PEM file."""
    key_bytes = Path(pem_path).read_bytes()
    private_key = serialization.load_pem_private_key(key_bytes, password=None)
    if not isinstance(private_key.curve, ec.SECP256R1):
        raise ValueError("Private key must be on the NIST P-256 (secp256r1) curve.")
    return private_key


def _sign_request(private_key: ec.EllipticCurvePrivateKey, path: str, timestamp_ms: int, body: str) -> str:
    """
    Produce a base64-encoded DER ECDSA-P256-SHA256 signature for a Fordefi request.

    Signed message format: f"{path}|{timestamp_ms}|{body}"
    """
    message = f"{path}|{timestamp_ms}|{body}".encode("utf-8")
    der_sig = private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    return base64.b64encode(der_sig).decode("utf-8")


# ---------------------------------------------------------------------------
# FordefiClient class
# ---------------------------------------------------------------------------

class FordefiClient:
    """
    Thin wrapper around the Fordefi REST API.

    The private key is only required for transaction creation (signed endpoints).
    Vault management and read operations only need the bearer token.

    Usage — vault operations only (no signing key needed):
        client = FordefiClient(api_token=os.environ["FORDEFI_API_TOKEN"])

    Usage — transaction creation (signing key required):
        client = FordefiClient(
            api_token=os.environ["FORDEFI_API_TOKEN"],
            private_key_path=os.environ["FORDEFI_PRIVATE_KEY_PATH"],
        )
    """

    def __init__(self, api_token: str, private_key_path: Optional[str] = None):
        self.api_token = api_token
        self.private_key = _load_private_key(private_key_path) if private_key_path else None
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bearer_headers(self) -> dict:
        """Headers for unsigned requests (bearer token only)."""
        return {"Authorization": f"Bearer {self.api_token}"}

    def _signed_headers(self, path: str, body: str) -> dict:
        """Headers for signed requests (bearer token + ECDSA signature)."""
        if self.private_key is None:
            raise RuntimeError(
                "This endpoint requires request signing. "
                "Pass private_key_path= when constructing FordefiClient."
            )
        timestamp_ms = int(time.time() * 1000)
        signature = _sign_request(self.private_key, path, timestamp_ms, body)
        return {
            "Authorization": f"Bearer {self.api_token}",
            "x-signature": signature,
            "x-timestamp": str(timestamp_ms),
        }

    def _get(self, path: str) -> dict:
        """Unsigned GET (bearer token only)."""
        url = f"{FORDEFI_BASE_URL}{path}"
        resp = self.session.get(url, headers=self._bearer_headers())
        resp.raise_for_status()
        return resp.json()

    def _post_unsigned(self, path: str, payload: dict) -> dict:
        """Unsigned POST (bearer token only) — used for vault creation."""
        body = json.dumps(payload, separators=(",", ":"))
        url = f"{FORDEFI_BASE_URL}{path}"
        resp = self.session.post(url, data=body, headers=self._bearer_headers())
        resp.raise_for_status()
        return resp.json()

    def _post_signed(self, path: str, payload: dict) -> dict:
        """Signed POST (bearer token + ECDSA signature) — used for transactions."""
        body = json.dumps(payload, separators=(",", ":"))
        headers = self._signed_headers(path, body)
        url = f"{FORDEFI_BASE_URL}{path}"
        resp = self.session.post(url, data=body, headers=headers)
        resp.raise_for_status()
        return resp.json()

    # ------------------------------------------------------------------
    # Vault operations  (unsigned — bearer token only)
    # ------------------------------------------------------------------

    def list_vaults(self) -> list:
        """Return all vaults in the organisation."""
        result = self._get("/api/v1/vaults")
        return result.get("vaults", result)

    def get_vault(self, vault_id: str) -> dict:
        """Fetch details for a single vault by ID."""
        return self._get(f"/api/v1/vaults/{vault_id}")

    def create_vault(self, name: str, vault_group_id: Optional[str] = None) -> dict:
        """
        Create a new Stacks vault.  Does NOT require request signing.

        Args:
            name: Human-readable name for the vault.
            vault_group_id: Optional group to place the vault in.
                            Defaults to the organisation's default group.

        Returns:
            The created vault object, including its 'id' and 'address'.
        """
        payload: dict = {"name": name, "type": "stacks"}
        if vault_group_id:
            payload["vault_group_id"] = vault_group_id
        return self._post_unsigned("/api/v1/vaults", payload)

    # ------------------------------------------------------------------
    # Transaction operations  (signed — bearer token + ECDSA signature)
    # ------------------------------------------------------------------

    def create_transaction(self, payload: dict) -> dict:
        """
        Submit a transaction creation request.  Requires request signing.

        Args:
            payload: The full CreateTransaction body (see build_* helpers).

        Returns:
            The created transaction object, including its 'id' and 'status'.
        """
        return self._post_signed("/api/v1/transactions", payload)

    def get_transaction(self, transaction_id: str) -> dict:
        """Fetch the current state of a transaction by ID."""
        return self._get(f"/api/v1/transactions/{transaction_id}")

    def wait_for_transaction(
        self,
        transaction_id: str,
        poll_interval: int = 5,
        timeout: int = 300,
    ) -> dict:
        """
        Poll until a transaction reaches a terminal state.

        Terminal states: completed, failed, cancelled.

        Args:
            transaction_id: The Fordefi transaction ID.
            poll_interval: Seconds between polls.
            timeout: Maximum seconds to wait before raising TimeoutError.

        Returns:
            The final transaction object.
        """
        terminal_states = {"completed", "failed", "cancelled"}
        deadline = time.time() + timeout
        while time.time() < deadline:
            tx = self.get_transaction(transaction_id)
            state = tx.get("state", "").lower()
            print(f"  Transaction {transaction_id[:8]}... state: {state}")
            if state in terminal_states:
                return tx
            time.sleep(poll_interval)
        raise TimeoutError(
            f"Transaction {transaction_id} did not complete within {timeout}s."
        )


# ---------------------------------------------------------------------------
# Transaction payload builders
# ---------------------------------------------------------------------------

def build_stacks_contract_deploy(
    vault_id: str,
    contract_name: str,
    clarity_code: str,
    chain: str = "stacks_testnet",
    fee_priority: str = "medium",
    push_mode: str = "auto",
    note: str | None = None,
) -> dict:
    """
    Build a CreateTransaction payload for deploying a Clarity smart contract
    via Fordefi's Stacks transaction API.

    Args:
        vault_id:      The UUID of the Stacks vault that will sign and pay fees.
        contract_name: Name for the deployed contract (lowercase, hyphens allowed).
        clarity_code:  Full source code of the Clarity contract.
        chain:         'stacks_testnet' or 'stacks_mainnet'.
        fee_priority:  'low', 'medium', or 'high'.
        push_mode:     'auto'   → Fordefi broadcasts the tx to the network.
                       'manual' → Fordefi signs only; you broadcast the raw tx.
        note:          Optional human-readable note shown in the Fordefi UI.

    Returns:
        A dict ready to pass to FordefiClient.create_transaction().

    Note:
        Verify the exact 'type' and field names against your Fordefi docs version,
        as the Stacks transaction schema may be updated over time.
    """
    payload: dict = {
        "vault_id": vault_id,
        "signer_type": "api_signer",
        "type": "stacks_transaction",
        "details": {
            "type": "stacks_contract_deploy",
            "chain": chain,
            "contract_name": contract_name,
            "clarity_code": clarity_code,
            "fee": {
                "type": "priority",
                "priority": fee_priority,
            },
        },
        "push_mode": push_mode,
    }
    if note:
        payload["note"] = note
    return payload


def build_stacks_raw_transaction(
    vault_id: str,
    serialized_tx_hex: str,
    chain: str = "stacks_testnet",
    push_mode: str = "auto",
    note: str | None = None,
) -> dict:
    """
    Build a CreateTransaction payload for submitting a pre-serialized
    Stacks transaction (advanced use case).

    Use this when you need full control over the transaction structure,
    e.g. sponsored transactions or complex post-conditions.

    Args:
        vault_id:           UUID of the signing Stacks vault.
        serialized_tx_hex:  Hex-encoded serialized Stacks transaction bytes.
        chain:              'stacks_testnet' or 'stacks_mainnet'.
        push_mode:          'auto' or 'manual'.
        note:               Optional UI note.

    Returns:
        A dict ready to pass to FordefiClient.create_transaction().
    """
    payload: dict = {
        "vault_id": vault_id,
        "signer_type": "api_signer",
        "type": "stacks_transaction",
        "details": {
            "type": "stacks_raw_transaction",
            "chain": chain,
            "request_data": serialized_tx_hex,
        },
        "push_mode": push_mode,
    }
    if note:
        payload["note"] = note
    return payload
