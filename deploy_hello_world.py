"""
deploy_hello_world.py
---------------------
Deploy hello_world.clar to Stacks via the Fordefi API using
stacks_serialized_transaction (the only supported raw tx type).

The transaction is serialized unsigned (zeroed signature) — Fordefi
fills in the signature before broadcasting.

Requires .env:
    FORDEFI_API_TOKEN
    FORDEFI_PRIVATE_KEY_PATH
    FORDEFI_VAULT_ID
    STACKS_NETWORK          (mainnet | testnet)
    STACKS_VAULT_ADDRESS    (STX address of the Fordefi vault)
"""

import base64
import json
import os
import struct
import time
from pathlib import Path

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from dotenv import load_dotenv

load_dotenv()

API_TOKEN         = os.environ["FORDEFI_API_TOKEN"]
PRIVATE_KEY_PATH  = os.environ["FORDEFI_PRIVATE_KEY_PATH"]
VAULT_ID          = os.environ["FORDEFI_VAULT_ID"]
NETWORK           = os.getenv("STACKS_NETWORK", "mainnet")
VAULT_ADDRESS     = os.environ["STACKS_VAULT_ADDRESS"]   # e.g. SP1ADD74...

CLARITY_CODE  = Path("examples/hello_world.clar").read_text(encoding="utf-8")
CONTRACT_NAME = "hello-world"

HIRO_API = (
    "https://api.mainnet.hiro.so" if NETWORK == "mainnet"
    else "https://api.testnet.hiro.so"
)
FORDEFI_CHAIN = f"stacks_{NETWORK}"


# ---------------------------------------------------------------------------
# Stacks transaction serialization (SIP-005 wire format)
# ---------------------------------------------------------------------------
# Constants
TX_VERSION_MAINNET = 0x00
TX_VERSION_TESTNET = 0x80
CHAIN_ID_MAINNET   = 0x00000001
CHAIN_ID_TESTNET   = 0x80000000

AUTH_TYPE_STANDARD       = 0x04
HASH_MODE_P2PKH          = 0x00
PUB_KEY_ENCODING_COMPRESSED = 0x00

ANCHOR_MODE_ANY          = 0x03
POST_CONDITION_MODE_DENY = 0x02
PAYLOAD_SMART_CONTRACT   = 0x01


def _lp1(s: str) -> bytes:
    """Encode a string with a 1-byte length prefix."""
    encoded = s.encode("utf-8")
    return struct.pack(">B", len(encoded)) + encoded


def _lp4(s: str) -> bytes:
    """Encode a string with a 4-byte length prefix."""
    encoded = s.encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded


def _hash160(pubkey_bytes: bytes) -> bytes:
    """RIPEMD-160(SHA-256(pubkey)) — standard Bitcoin/Stacks signer hash."""
    import hashlib
    sha256 = hashlib.sha256(pubkey_bytes).digest()
    ripemd = hashlib.new("ripemd160", sha256).digest()
    return ripemd


def serialize_contract_deploy(
    sender_address: str,
    nonce: int,
    fee: int,
    contract_name: str,
    clarity_code: str,
    network: str = "mainnet",
) -> bytes:
    """
    Build an unsigned Stacks smart-contract-deploy transaction.

    The 65-byte signature field is left as zeros — Fordefi will sign it.

    Wire format (SIP-005):
        [version:1][chain_id:4]
        [auth_type:1][hash_mode:1][signer_hash:20][nonce:8][fee:8]
        [key_encoding:1][signature:65]
        [anchor_mode:1][post_condition_mode:1][post_conditions_count:4]
        [payload_type:1][contract_name:1+N][clarity_code:4+M]
    """
    version  = TX_VERSION_MAINNET if network == "mainnet" else TX_VERSION_TESTNET
    chain_id = CHAIN_ID_MAINNET   if network == "mainnet" else CHAIN_ID_TESTNET

    # Derive the signer hash from the vault address.
    # Stacks addresses are c32check-encoded; the raw hash160 is the 20-byte
    # body.  We decode it here using a simple c32 decode.
    signer_hash = _c32_address_decode(sender_address)  # 20 bytes

    tx = bytearray()

    # Header
    tx += struct.pack(">B", version)
    tx += struct.pack(">I", chain_id)

    # Authorization (standard single-sig)
    tx += struct.pack(">B", AUTH_TYPE_STANDARD)
    tx += struct.pack(">B", HASH_MODE_P2PKH)
    tx += signer_hash                          # 20 bytes
    tx += struct.pack(">Q", nonce)             # 8 bytes
    tx += struct.pack(">Q", fee)               # 8 bytes
    tx += struct.pack(">B", PUB_KEY_ENCODING_COMPRESSED)
    tx += bytes(65)                            # empty signature — Fordefi signs

    # Anchor mode + post conditions
    tx += struct.pack(">B", ANCHOR_MODE_ANY)
    tx += struct.pack(">B", POST_CONDITION_MODE_DENY)
    tx += struct.pack(">I", 0)                 # 0 post conditions

    # Payload: smart contract deploy
    tx += struct.pack(">B", PAYLOAD_SMART_CONTRACT)
    tx += _lp1(contract_name)                  # 1-byte len prefix
    tx += _lp4(clarity_code)                   # 4-byte len prefix

    return bytes(tx)


def _c32_address_decode(address: str) -> bytes:
    """
    Extract the 20-byte hash160 payload from a Stacks (c32check) address.

    Stacks addresses look like: SP1ADD74232012FBD68345FEF...
    The prefix (SP/ST/SM/SN) encodes version; the rest is c32-encoded
    [version_byte(1)] + [hash160(20)] + [checksum(4)] = 25 bytes decoded.
    We want bytes [1:21] (the hash160).
    """
    C32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
    # Strip the 1-char prefix letter (S) and version letter (P/T/M/N)
    payload_chars = address[2:]  # drop "SP" / "ST" etc.

    # Decode c32 → integer
    value = 0
    for ch in payload_chars:
        value = value * 32 + C32_ALPHABET.index(ch.upper())

    # Convert integer → bytes (25 bytes: 1 version + 20 hash + 4 checksum)
    raw = value.to_bytes(25, "big")
    return raw[1:21]  # the hash160


# ---------------------------------------------------------------------------
# Fetch nonce from Hiro API
# ---------------------------------------------------------------------------

def get_nonce(address: str) -> int:
    url = f"{HIRO_API}/v2/accounts/{address}?proof=0"
    resp = requests.get(url, timeout=15)
    resp.raise_for_status()
    return int(resp.json()["nonce"])


def estimate_fee(payload_hex: str, estimated_len: int) -> int:
    """
    POST /v2/fees/transaction — returns the middle fee estimate in microSTX.
    Falls back to 2000 microSTX if the node can't estimate.
    """
    url = f"{HIRO_API}/v2/fees/transaction"
    body = {"transaction_payload": payload_hex, "estimated_len": estimated_len}
    resp = requests.post(url, json=body, timeout=15)
    if not resp.ok:
        print(f"  Fee estimation failed ({resp.status_code}), using fallback 2000 µSTX")
        return 2000
    estimations = resp.json().get("estimations", [])
    # estimations[1] is the middle (medium) estimate
    fee = estimations[1]["fee"] if len(estimations) > 1 else estimations[0]["fee"]
    return max(fee, 200)  # floor at 200 µSTX


def _serialize_payload_only(contract_name: str, clarity_code: str) -> str:
    """Serialize just the TransactionPayload portion as hex (for fee estimation)."""
    payload = bytearray()
    payload += struct.pack(">B", PAYLOAD_SMART_CONTRACT)
    payload += _lp1(contract_name)
    payload += _lp4(clarity_code)
    return payload.hex()


# ---------------------------------------------------------------------------
# Fordefi request signing
# ---------------------------------------------------------------------------

def _sign_fordefi_request(private_key, path: str, body: str) -> dict:
    timestamp_ms = int(time.time() * 1000)
    message = f"{path}|{timestamp_ms}|{body}".encode()
    signature = base64.b64encode(
        private_key.sign(message, ec.ECDSA(hashes.SHA256()))
    ).decode()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
        "x-signature": signature,
        "x-timestamp": str(timestamp_ms),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # 1. Fetch current nonce
    print(f"Fetching nonce for {VAULT_ADDRESS}...")
    nonce = get_nonce(VAULT_ADDRESS)
    print(f"  Nonce: {nonce}")

    # 2. Estimate fee from the network
    payload_hex = _serialize_payload_only(CONTRACT_NAME, CLARITY_CODE)
    # Approximate full tx length: 5 header + 108 auth + 6 anchor/postcond + payload
    estimated_len = 5 + 108 + 6 + len(bytes.fromhex(payload_hex))
    print(f"Estimating fee (estimated tx size: {estimated_len} bytes)...")
    fee = estimate_fee(payload_hex, estimated_len)
    print(f"  Fee: {fee} µSTX")

    # 3. Serialize the unsigned transaction
    raw_tx = serialize_contract_deploy(
        sender_address=VAULT_ADDRESS,
        nonce=nonce,
        fee=fee,
        contract_name=CONTRACT_NAME,
        clarity_code=CLARITY_CODE,
        network=NETWORK,
    )
    serialized_hex = "0x" + raw_tx.hex()
    print(f"  Serialized tx: {len(raw_tx)} bytes")

    # 4. Build Fordefi payload
    payload = {
        "vault_id": VAULT_ID,
        "signer_type": "api_signer",
        "type": "stacks_transaction",
        "details": {
            "type": "stacks_serialized_transaction",
            "chain": FORDEFI_CHAIN,
            "serialized_transaction": serialized_hex,
            "push_mode": "auto",
            "fail_on_prediction_failure": False,
        },
    }

    # 5. Sign and submit to Fordefi
    path = "/api/v1/transactions"
    body = json.dumps(payload, separators=(",", ":"))

    private_key = serialization.load_pem_private_key(
        Path(PRIVATE_KEY_PATH).read_bytes(), password=None
    )
    headers = _sign_fordefi_request(private_key, path, body)

    print("Submitting to Fordefi...")
    resp = requests.post(f"https://api.fordefi.com{path}", data=body, headers=headers)

    if not resp.ok:
        print(f"HTTP {resp.status_code}: {resp.text}")
        resp.raise_for_status()

    tx = resp.json()
    print(f"✅ Submitted — Fordefi TX ID: {tx['id']}")
    print(f"   State: {tx.get('state')}")


if __name__ == "__main__":
    main()
