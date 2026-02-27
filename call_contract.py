"""
call_contract.py
----------------
Call a Clarity smart contract function on Stacks via the Fordefi API.

Requires .env:
    FORDEFI_API_TOKEN
    FORDEFI_PRIVATE_KEY_PATH
    FORDEFI_VAULT_ID
    STACKS_NETWORK          (mainnet | testnet)
    STACKS_VAULT_ADDRESS    (STX address of the Fordefi vault)

Usage: edit CONTRACT_ADDRESS, CONTRACT_NAME, FUNCTION_NAME, and ARGS below.
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

API_TOKEN        = os.environ["FORDEFI_API_TOKEN"]
PRIVATE_KEY_PATH = os.environ["FORDEFI_PRIVATE_KEY_PATH"]
VAULT_ID         = os.environ["FORDEFI_VAULT_ID"]
NETWORK          = os.getenv("STACKS_NETWORK", "mainnet")
VAULT_ADDRESS    = os.environ["STACKS_VAULT_ADDRESS"]

HIRO_API = (
    "https://api.mainnet.hiro.so" if NETWORK == "mainnet"
    else "https://api.testnet.hiro.so"
)
FORDEFI_CHAIN = f"stacks_{NETWORK}"

# ---------------------------------------------------------------------------
# Stacks address decoding
# ---------------------------------------------------------------------------

_ADDR_VERSION = {
    "SP": 22,   # mainnet single-sig  (0x16)
    "SM": 20,   # mainnet multi-sig   (0x14)
    "ST": 26,   # testnet single-sig  (0x1a)
    "SN": 21,   # testnet multi-sig   (0x15)
}
_C32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def _decode_stacks_address(address: str) -> tuple[int, bytes]:
    """Return (version_byte, hash160) from a Stacks address string."""
    prefix = address[:2].upper()
    version = _ADDR_VERSION[prefix]
    value = 0
    for ch in address[2:]:
        value = value * 32 + _C32.index(ch.upper())
    raw = value.to_bytes(25, "big")   # version(1) + hash160(20) + checksum(4)
    return version, raw[1:21]


# ---------------------------------------------------------------------------
# Clarity value serialization
# ---------------------------------------------------------------------------

def clarity_uint(n: int) -> bytes:
    return b"\x01" + n.to_bytes(16, "big")

def clarity_int(n: int) -> bytes:
    return b"\x00" + n.to_bytes(16, "big", signed=True)

def clarity_bool(b: bool) -> bytes:
    return b"\x03" if b else b"\x04"

def clarity_string_ascii(s: str) -> bytes:
    encoded = s.encode("ascii")
    return b"\x0d" + struct.pack(">I", len(encoded)) + encoded

def clarity_string_utf8(s: str) -> bytes:
    encoded = s.encode("utf-8")
    return b"\x0e" + struct.pack(">I", len(encoded)) + encoded

def clarity_buffer(data: bytes) -> bytes:
    return b"\x02" + struct.pack(">I", len(data)) + data

def clarity_principal(address: str) -> bytes:
    """Standard principal (no contract suffix)."""
    ver, hash160 = _decode_stacks_address(address)
    return b"\x05" + bytes([ver]) + hash160

def clarity_contract_principal(address: str, contract: str) -> bytes:
    """Contract principal (address.contract-name)."""
    ver, hash160 = _decode_stacks_address(address)
    name = contract.encode("ascii")
    return b"\x06" + bytes([ver]) + hash160 + bytes([len(name)]) + name


# ---------------------------------------------------------------------------
# Configure your contract call here
# ---------------------------------------------------------------------------
CONTRACT_ADDRESS = "SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7"
CONTRACT_NAME    = "v0-4-market"
FUNCTION_NAME    = "supply-collateral-add"
ARGS = [
    clarity_contract_principal("SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7", "wstx"),
    clarity_uint(1_000_000),   # 1 STX
    clarity_uint(0),           # min-shares
    b"\x09",                   # none (skip Pyth)
]


# Args: list of Clarity values built with the helpers below
#ARGS = [
#    clarity_string_ascii("Hello from Fordefi!"),
#]


# ---------------------------------------------------------------------------
# Transaction serialization (SIP-005)
# ---------------------------------------------------------------------------

TX_VERSION   = {True: 0x00, False: 0x80}   # mainnet → 0x00
CHAIN_ID     = {True: 0x00000001, False: 0x80000000}

def _lp1(s: str) -> bytes:
    b = s.encode("ascii")
    return bytes([len(b)]) + b


def serialize_contract_call(
    sender_address: str,
    nonce: int,
    fee: int,
    contract_address: str,
    contract_name: str,
    function_name: str,
    args: list[bytes],
    network: str = "mainnet",
) -> bytes:
    """
    Build an unsigned Stacks contract-call transaction (payload type 0x02).

    Wire format (SIP-005):
        [version:1][chain_id:4]
        [auth_type:1][hash_mode:1][signer_hash:20][nonce:8][fee:8]
        [key_encoding:1][signature:65]
        [anchor_mode:1][post_condition_mode:1][post_conditions_count:4]
        [payload_type:1]
        [contract_addr_version:1][contract_hash160:20]
        [contract_name:1+N][function_name:1+N]
        [num_args:4][arg_0 ... arg_N]
    """
    is_mainnet = (network == "mainnet")
    version  = TX_VERSION[is_mainnet]
    chain_id = CHAIN_ID[is_mainnet]

    _, signer_hash    = _decode_stacks_address(sender_address)
    contract_ver, contract_hash = _decode_stacks_address(contract_address)

    tx = bytearray()

    # Header
    tx += struct.pack(">B", version)
    tx += struct.pack(">I", chain_id)

    # Authorization (standard single-sig)
    tx += b"\x04"                          # auth_type = standard
    tx += b"\x00"                          # hash_mode = P2PKH
    tx += signer_hash                      # 20 bytes
    tx += struct.pack(">Q", nonce)         # 8 bytes
    tx += struct.pack(">Q", fee)           # 8 bytes
    tx += b"\x00"                          # key_encoding = compressed
    tx += bytes(65)                        # empty signature — Fordefi signs

    # Anchor + post conditions
    tx += b"\x03"                          # anchor_mode = any
    tx += b"\x01"                          # post_condition_mode = allow
    tx += struct.pack(">I", 0)             # 0 post conditions

    # Payload: contract call (type 0x02)
    tx += b"\x02"
    tx += bytes([contract_ver])
    tx += contract_hash
    tx += _lp1(contract_name)
    tx += _lp1(function_name)
    tx += struct.pack(">I", len(args))
    for arg in args:
        tx += arg

    return bytes(tx)


# ---------------------------------------------------------------------------
# Hiro API helpers
# ---------------------------------------------------------------------------

def get_nonce(address: str) -> int:
    resp = requests.get(f"{HIRO_API}/v2/accounts/{address}?proof=0", timeout=15)
    resp.raise_for_status()
    return int(resp.json()["nonce"])


def estimate_fee(payload_hex: str, estimated_len: int) -> int:
    resp = requests.post(
        f"{HIRO_API}/v2/fees/transaction",
        json={"transaction_payload": payload_hex, "estimated_len": estimated_len},
        timeout=15,
    )
    if not resp.ok:
        print(f"  Fee estimation failed ({resp.status_code}), using fallback 2000 µSTX")
        return 2000
    estimations = resp.json().get("estimations", [])
    fee = estimations[1]["fee"] if len(estimations) > 1 else estimations[0]["fee"]
    return max(fee, 200)


def _serialize_call_payload_only(
    contract_address: str,
    contract_name: str,
    function_name: str,
    args: list[bytes],
) -> str:
    """Payload-only hex for fee estimation."""
    contract_ver, contract_hash = _decode_stacks_address(contract_address)
    p = bytearray()
    p += b"\x02"
    p += bytes([contract_ver])
    p += contract_hash
    p += _lp1(contract_name)
    p += _lp1(function_name)
    p += struct.pack(">I", len(args))
    for arg in args:
        p += arg
    return p.hex()


# ---------------------------------------------------------------------------
# Fordefi request signing
# ---------------------------------------------------------------------------

def _sign_fordefi_request(private_key, path: str, body: str) -> dict:
    timestamp_ms = int(time.time() * 1000)
    message = f"{path}|{timestamp_ms}|{body}".encode()
    sig = base64.b64encode(private_key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_TOKEN}",
        "x-signature": sig,
        "x-timestamp": str(timestamp_ms),
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print(f"Calling {CONTRACT_ADDRESS}.{CONTRACT_NAME}::{FUNCTION_NAME}")

    # 1. Nonce
    nonce = get_nonce(VAULT_ADDRESS)
    print(f"  Nonce: {nonce}")

    # 2. Fee estimate
    payload_hex = _serialize_call_payload_only(
        CONTRACT_ADDRESS, CONTRACT_NAME, FUNCTION_NAME, ARGS
    )
    estimated_len = 5 + 108 + 6 + len(bytes.fromhex(payload_hex))
    fee = estimate_fee(payload_hex, estimated_len)
    print(f"  Fee: {fee} µSTX")

    # 3. Serialize unsigned tx
    raw_tx = serialize_contract_call(
        sender_address=VAULT_ADDRESS,
        nonce=nonce,
        fee=fee,
        contract_address=CONTRACT_ADDRESS,
        contract_name=CONTRACT_NAME,
        function_name=FUNCTION_NAME,
        args=ARGS,
        network=NETWORK,
    )
    serialized_hex = "0x" + raw_tx.hex()
    print(f"  Serialized tx: {len(raw_tx)} bytes")

    # 4. Fordefi payload
    payload = {
        "vault_id": VAULT_ID,
        "signer_type": "api_signer",
        "sign_mode": "auto",
        "type": "stacks_transaction",
        "details": {
            "type": "stacks_serialized_transaction",
            "chain": FORDEFI_CHAIN,
            "serialized_transaction": serialized_hex,
            "push_mode": "auto",
            "fail_on_prediction_failure": False,
        },
    }

    # 5. Sign and submit
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
