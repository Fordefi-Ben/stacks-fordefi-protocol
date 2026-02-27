# Stacks Smart Contract Calls via Fordefi

Serialize and submit Clarity contract calls to Stacks mainnet via the Fordefi API. Transactions follow the SIP-005 binary wire format; Fordefi's MPC infrastructure signs and broadcasts them.

---

## Overview

```
call_contract.py  →  Fordefi API  →  Stacks Mainnet
  (serialize tx)     (MPC signer)    (broadcast)
```

Fordefi's Stacks integration accepts only `stacks_serialized_transaction`. You build the full unsigned transaction binary; Fordefi fills in the 65-byte signature and broadcasts.

---

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in your values
python call_contract.py
```

`.env` variables:

```env
FORDEFI_API_TOKEN=<bearer token from Fordefi console>
FORDEFI_PRIVATE_KEY_PATH=./private.pem
FORDEFI_VAULT_ID=<uuid of your Stacks vault>
STACKS_VAULT_ADDRESS=SP...
```

To target a different contract, edit the config block in `call_contract.py`:

```python
CONTRACT_ADDRESS = "SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7"
CONTRACT_NAME    = "v0-4-market"
FUNCTION_NAME    = "supply-collateral-add"
ARGS = [
    clarity_contract_principal("SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7", "wstx"),
    clarity_uint(1_000_000),   # 1 STX in µSTX
    clarity_uint(0),           # min-shares
    b"\x09",                   # Clarity none
]
```

---

## Transaction Serialization

Stacks transactions use the SIP-005 binary wire format. You construct the bytes directly. Structure for a contract call:

```
[version: 1]              0x00 = mainnet
[chain_id: 4]             0x00000001
[auth_type: 1]            0x04 = standard single-sig
[hash_mode: 1]            0x00 = P2PKH
[signer hash160: 20]      decoded from the sender's Stacks address
[nonce: 8]                big-endian u64, fetched from Hiro API
[fee: 8]                  big-endian u64, estimated via Fordefi predict
[key_encoding: 1]         0x00 = compressed public key
[signature: 65]           zeroed out; Fordefi fills this in
[anchor_mode: 1]          0x03 = any
[post_condition_mode: 1]  0x01 = allow, 0x02 = deny
[post_conditions_count: 4]
[post_conditions: ...]
[payload_type: 1]         0x02 = contract call
[contract_version: 1]     decoded from contract address
[contract_hash160: 20]    decoded from contract address
[contract_name: 1+N]      length-prefixed ascii
[function_name: 1+N]      length-prefixed ascii
[num_args: 4]             big-endian u32
[arg_0 ... arg_N]         Clarity-serialized values
```

### Address Decoding (C32Check)

Stacks addresses are C32Check encoded. Decoding produces 25 bytes: `version(1) + hash160(20) + checksum(4)`. Only the 20 hash160 bytes go into the transaction.

```python
_C32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"

def _decode_stacks_address(address: str) -> tuple[int, bytes]:
    value = 0
    for ch in address[2:]:
        value = value * 32 + _C32.index(ch.upper())
    raw = value.to_bytes(25, "big")
    return version_byte, raw[1:21]   # (version, hash160)
```

### Clarity Value Serialization

Each function argument is a Clarity value: a type tag byte followed by the encoded data.

| Helper | Tag | Encoding |
|---|---|---|
| `clarity_uint(n)` | `0x01` | 16-byte big-endian unsigned |
| `clarity_int(n)` | `0x00` | 16-byte big-endian signed |
| `clarity_bool(b)` | `0x03` / `0x04` | true / false |
| `clarity_string_ascii(s)` | `0x0d` | 4-byte len + ascii bytes |
| `clarity_string_utf8(s)` | `0x0e` | 4-byte len + utf-8 bytes |
| `clarity_buffer(data)` | `0x02` | 4-byte len + raw bytes |
| `clarity_principal(addr)` | `0x05` | version(1) + hash160(20) |
| `clarity_contract_principal(addr, name)` | `0x06` | version(1) + hash160(20) + 1-byte len + name |
| `b"\x09"` (inline) | `0x09` | Clarity `none`, no body |

Example: encoding `(supply-collateral-add wstx u1000000 u0 none)`:

```python
ARGS = [
    clarity_contract_principal("SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7", "wstx"),
    clarity_uint(1_000_000),
    clarity_uint(0),
    b"\x09",            # none
]
```

---

## Post-Conditions

Post-conditions declare which asset movements a transaction is permitted to make. The Stacks node enforces them before committing; if execution moves an asset not covered, the tx is rolled back (fees still charged).

### Modes

| Mode | Byte | Behaviour |
|---|---|---|
| **Allow** | `0x01` | Any asset movement is permitted |
| **Deny** | `0x02` | Only explicitly listed movements are permitted; anything else causes a rollback |

`call_contract.py` uses allow mode (`0x01`). The Zest Protocol `supply-collateral-add` function mints `v0-vault-stx::zft` receipt tokens back to the caller; in deny mode that unlisted movement caused an on-chain rollback.

### Deny Mode for Production

Allow mode removes a critical safeguard. With deny mode you make an explicit commitment about what the transaction is permitted to do:

- **Contract upgrades.** A contract upgraded after integration can drain additional tokens. Deny mode ensures unexpected transfers fail.
- **Cross-contract side-effects.** Clarity prevents re-entrancy, but inter-contract calls can trigger asset movements you didn't intend. Deny mode catches these at the protocol level.
- **Argument errors.** If you pass the wrong amount, the transaction fails on-chain before it can do damage.
- **Auditability.** Anyone reading the raw transaction can verify exactly which asset movements were authorized.

### Post-Condition Wire Format

Fungible token post-condition:

```
[type: 1]                 0x01 = fungible token
[principal_type: 1]       0x02 = standard principal
[principal: 21]           version(1) + hash160(20)
[asset_contract_ver: 1]
[asset_contract_hash: 20]
[asset_contract_name: 1+N]
[asset_name: 1+N]
[condition_code: 1]       0x01=eq 0x02=gt 0x03=gte 0x04=lt 0x05=lte
[amount: 8]               big-endian u64
```

STX post-condition (type `0x00`): omit asset info fields; principal is followed directly by condition code and amount.

### Example: Deny Mode with FT Post-Condition

```python
def post_condition_ft(sender, asset_contract, asset_contract_name, asset_name, code, amount):
    s_ver, s_hash = _decode_stacks_address(sender)
    a_ver, a_hash = _decode_stacks_address(asset_contract)
    pc  = b"\x01"                           # type: FT
    pc += b"\x02" + bytes([s_ver]) + s_hash # principal
    pc += bytes([a_ver]) + a_hash           # asset contract address
    pc += _lp1(asset_contract_name)
    pc += _lp1(asset_name)
    pc += bytes([code])
    pc += struct.pack(">Q", amount)
    return pc

post_conds = post_condition_ft(
    sender             = VAULT_ADDRESS,
    asset_contract     = "SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7",
    asset_contract_name= "v0-vault-stx",
    asset_name         = "zft",
    code               = 0x03,              # gte
    amount             = 0,
)

# In serialize_contract_call:
tx += b"\x02"                               # post_condition_mode = deny
tx += struct.pack(">I", 1)                  # 1 post-condition
tx += post_conds
```

---

## Fordefi Integration

### Request Signing

Transaction creation requests require two auth layers:

| Layer | How |
|---|---|
| Bearer token | `Authorization: Bearer <token>` on all requests |
| ECDSA P-256 signature | Required only for `POST /api/v1/transactions` |

The signed message is:
```
{path}|{timestamp_ms}|{request_body}
```

Signature is base64-encoded DER, sent as `x-signature`. Timestamp (ms) sent as `x-timestamp`.

### Transaction Payload

```python
{
    "vault_id": "<uuid>",
    "signer_type": "api_signer",
    "sign_mode": "auto",
    "type": "stacks_transaction",
    "details": {
        "type": "stacks_serialized_transaction",
        "chain": "stacks_mainnet",
        "serialized_transaction": "0x...",  # unsigned tx hex
        "push_mode": "auto",
        "fail_on_prediction_failure": False,
    }
}
```

Fordefi fills in the 65-byte signature field and broadcasts.

---

## Stacks Network Reference

| | Value |
|---|---|
| Fordefi chain | `stacks_mainnet` |
| Address prefix | `SP` |
| Version byte | `0x16` (22) |
| Chain ID | `0x00000001` |
| TX version | `0x00` |
| Hiro API | `https://api.mainnet.hiro.so` |
| Explorer | `https://explorer.hiro.so` |

---

## Further Reading

- [SIP-005: Stacks Transaction Wire Format](https://github.com/stacksgov/sips/blob/main/sips/sip-005/sip-005-blocks-and-transactions.md)
- [Fordefi Stacks Raw Transactions](https://docs.fordefi.com/reference/stacks-raw-transactions)
- [Fordefi API Authentication](https://docs.fordefi.com/developers/authentication)
- [Hiro Stacks API - Accounts (nonce)](https://docs.hiro.so/stacks/api/accounts/get-account-info)
- [Hiro Stacks API - Fee Estimation](https://docs.hiro.so/stacks/api/fees/get-approximate-fees)
- [Clarity Value Serialization](https://github.com/stacksgov/sips/blob/main/sips/sip-005/sip-005-blocks-and-transactions.md#clarity-value-serialization)
