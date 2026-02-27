# Deploying Clarity Smart Contracts on Stacks via Fordefi API

**End-to-End Guide — Python · Testnet · Fordefi API**

---

## Overview

This guide walks through every step needed to deploy a [Clarity](https://clarity-lang.org/) smart contract to the **Stacks testnet** using the **Fordefi API** as the signing and broadcasting layer.

Fordefi provides enterprise-grade MPC key custody, policy controls, and audit trails. Rather than managing raw private keys in your deployment pipeline, Fordefi acts as the secure signer — your scripts tell it *what* to sign; Fordefi's infrastructure handles the cryptography and broadcasts the transaction.

### What you will build

```
Your Script  →  Fordefi API  →  Stacks Testnet
   (Python)      (MPC Signer)     (Blockchain)
```

1. Create a Stacks vault in Fordefi (bearer token only)
2. Fund the vault with testnet STX
3. Generate an API signing key pair and register it
4. Deploy a Clarity contract (signed request)
5. Verify the deployment on-chain

---

## Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.11+ | `python --version` |
| Fordefi account | Request access at [fordefi.com](https://fordefi.com) |
| Fordefi API Signer | Running in your infrastructure (Docker recommended) |
| Internet access | To reach Fordefi API and Stacks testnet |

> **API Signer**: Programmatic transactions in Fordefi require a running API Signer process. This is a Docker container that co-signs transactions initiated by API Users. See [Fordefi API Signer Setup](https://docs.fordefi.com/developers/getting-started/set-up-an-api-signer/api-signer-docker) for instructions.

---

## Repository Structure

```
stacks-fordefi-protocol/
├── README.md                         ← You are here
├── requirements.txt                  ← Python dependencies
├── .env.example                      ← Environment variable template
├── keys/                             ← Generated key files (git-ignored)
│   ├── private_key.pem               ← API signing key (KEEP SECRET)
│   └── public_key.pem                ← Upload to Fordefi console
├── scripts/
│   ├── fordefi_client.py             ← Shared API client + payload builders
│   ├── 0_generate_keys.py            ← Generate ECDSA P-256 key pair
│   ├── 1_create_vault.py             ← Create a Stacks vault
│   ├── 2_fund_vault.py               ← Fund with testnet STX
│   ├── 3_deploy_contract.py          ← Deploy a Clarity contract  ← MAIN
│   └── 4_check_status.py             ← Verify deployment
└── examples/
    ├── hello_world.clar              ← Minimal contract for testing
    └── counter.clar                  ← Stateful counter contract
```

---

## Step-by-Step Guide

### Step 0 — Install dependencies

```bash
# Clone or unzip this project, then:
cd stacks-fordefi-protocol
pip install -r requirements.txt
cp .env.example .env
```

---

### Step 1 — Set up Fordefi console

Before running any scripts, complete these steps in the **Fordefi web console**:

#### 1a. Enable the API Signer

1. In the Fordefi console, go to **Settings → API Signers**.
2. Follow the [Docker setup guide](https://docs.fordefi.com/developers/getting-started/set-up-an-api-signer/api-signer-docker) to run the API Signer container in your environment.
3. The API Signer must be online before programmatic transactions can be processed.

#### 1b. Create an API User

1. Go to **User Management → API Users → Create API User**.
2. Set the role to **Trader** (required to create transactions).
3. Leave the public key field empty for now — you'll upload it in Step 3 before deploying.
4. Copy the **Access Token** that is generated. You will not be able to see it again.

#### 1c. Populate your `.env` file

Open `.env` and fill in:

```env
FORDEFI_API_TOKEN=<your_access_token_from_step_1b>
FORDEFI_PRIVATE_KEY_PATH=./keys/private_key.pem
STACKS_NETWORK=testnet
```

---

### Step 2 — Create a Stacks vault

> You can do this **before** generating keys — vault creation only needs your bearer token.

```bash
python scripts/1_create_vault.py
```

This calls `POST /api/v1/vaults` to create a new Stacks MPC wallet in Fordefi.

Expected output:
```
Creating Stacks vault: 'Stacks Testnet Vault'...

✅ Vault created successfully!
   Vault ID:       a1b2c3d4-e5f6-7890-abcd-ef1234567890
   Stacks address: ST1PQHQKV0RJXZFY1DGX8MNSNYVE3VGZJSRTPGZGM
```

The script automatically writes `FORDEFI_VAULT_ID` to your `.env` file.

> **Note**: Copy the **Stacks address** — you will need it in Step 3.

---

### Step 3 — Fund the vault with testnet STX

```bash
python scripts/2_fund_vault.py --address ST1PQHQKV0RJXZFY1DGX8MNSNYVE3VGZJSRTPGZGM
```

This hits the [Hiro Stacks Testnet Faucet](https://docs.hiro.so/stacks/hiro-faucet) and requests **500 testnet STX** for your vault address.

- Testnet STX has no real-world value.
- Each address can request from the faucet at most once per day.
- Wait **1–2 minutes** for the funds to arrive on-chain.

You can also fund your testnet address via the Hiro web faucet at: https://explorer.hiro.so/sandbox/faucet?chain=testnet

---

### Step 4 — Generate a key pair and register it

Signing is required for transaction creation. Do this before deploying.

```bash
python scripts/0_generate_keys.py
```

This creates:
- `keys/private_key.pem` — Your API request signing key. Never share or commit this.
- `keys/public_key.pem` — Upload this to the Fordefi API User.

After generating, register the public key:

1. Open the Fordefi console → **User Management → API Users → [your user] → Edit**.
2. Paste the contents of `keys/public_key.pem` into the **Public Key** field.
3. Save.

---

### Step 5 — Deploy a Clarity smart contract

```bash
python scripts/3_deploy_contract.py
```

This is the core step. The script:

1. Reads the `.clar` file.
2. Builds the Fordefi `CreateTransaction` request body.
3. Signs the request with your ECDSA P-256 private key.
4. Posts to `POST /api/v1/transactions`.
5. Polls until the transaction reaches a terminal state.
6. Prints the on-chain transaction ID and an Explorer link.

#### Deploy a custom contract

```bash
python scripts/3_deploy_contract.py \
  --contract-file ./examples/counter.clar \
  --contract-name my-counter \
  --fee-priority high
```

#### Options

| Flag | Default | Description |
|---|---|---|
| `--contract-file` | `./examples/hello_world.clar` | Path to the `.clar` file |
| `--contract-name` | `hello-world` | Name for the deployed contract |
| `--fee-priority` | `medium` | `low`, `medium`, or `high` |
| `--push-mode` | `auto` | `auto` (Fordefi broadcasts) or `manual` (sign only) |
| `--no-wait` | off | Return immediately after submit |

Expected output:
```
============================================================
  Fordefi × Stacks — Contract Deployment
============================================================
  Network:       testnet
  Chain:         stacks_testnet
  Vault ID:      a1b2c3d4-...
  Contract name: hello-world
  Contract file: hello_world.clar
  Fee priority:  medium
  Push mode:     auto
============================================================

Submitting transaction to Fordefi...
✅ Transaction submitted!
   Fordefi TX ID: f7e6d5c4-...
   Initial state: pending_signature

Polling for completion...
  Transaction f7e6d5c4... state: pending_signature
  Transaction f7e6d5c4... state: signed
  Transaction f7e6d5c4... state: completed

🎉 Contract deployed successfully!
   On-chain TX ID: 0xabcdef1234...
   Explorer: https://explorer.hiro.so/txid/0xabcdef1234...?chain=testnet
```

---

### Step 6 — Verify the deployment

```bash
# Check Fordefi transaction status
python scripts/4_check_status.py --tx-id f7e6d5c4-...

# Check the contract is live on-chain
python scripts/4_check_status.py --contract ST1PQHQ...GMM.hello-world

# Check vault balance
python scripts/4_check_status.py --address ST1PQHQ...GMM
```

---

## How Fordefi Request Signing Works

Not every endpoint requires signing. The rule is straightforward:

| Endpoint | Auth required |
|---|---|
| `GET *` | Bearer token only |
| `POST /api/v1/vaults` | Bearer token only |
| `POST /api/v1/transactions` | Bearer token **+ ECDSA signature** |

### Layer 1 — Bearer Token (all endpoints)
Your API User's access token, passed as:
```
Authorization: Bearer <token>
```

### Layer 2 — ECDSA P-256 Signature (transaction endpoints only)
Transaction creation requests must also be signed with your private key. This ensures that even if your bearer token were compromised, an attacker still cannot submit transactions without your private key.

**Signed message format:**
```
{path}|{timestamp_ms}|{request_body}
```

For example:
```
/api/v1/transactions|1708700000000|{"vault_id":"...","type":"stacks_transaction",...}
```

The signature is base64-encoded DER format, passed as:
```
x-signature: <base64_DER_signature>
x-timestamp: 1708700000000
```

`fordefi_client.py` handles all of this automatically — `create_vault()` uses an unsigned POST, while `create_transaction()` uses a signed POST.

---

## Fordefi Transaction Payload Reference

### Contract Deploy (high-level)

```python
{
    "vault_id": "<your-stacks-vault-uuid>",
    "signer_type": "api_signer",
    "type": "stacks_transaction",
    "details": {
        "type": "stacks_contract_deploy",
        "chain": "stacks_testnet",          # or "stacks_mainnet"
        "contract_name": "hello-world",
        "clarity_code": "(define-public ...)",
        "fee": {
            "type": "priority",
            "priority": "medium"             # "low" | "medium" | "high"
        }
    },
    "push_mode": "auto",                     # "auto" | "manual"
    "note": "Deploy hello-world to testnet"
}
```

### Raw Transaction (advanced)

For sponsored transactions, custom post-conditions, or other cases where you need full control over the serialized transaction bytes:

```python
{
    "vault_id": "<your-stacks-vault-uuid>",
    "signer_type": "api_signer",
    "type": "stacks_transaction",
    "details": {
        "type": "stacks_raw_transaction",
        "chain": "stacks_testnet",
        "request_data": "<hex-encoded-serialized-stacks-transaction>"
    },
    "push_mode": "auto"
}
```

> **Note**: When using `push_mode: "manual"`, Fordefi returns the signed transaction bytes in the completed transaction object. You then broadcast it yourself via:
> ```
> POST https://api.testnet.hiro.so/v2/transactions
> Content-Type: application/octet-stream
> Body: <raw transaction bytes>
> ```

---

## Post-Conditions

Post-conditions are a Stacks protocol feature that let you declare — at the transaction level — which asset movements are permitted. The node enforces these declarations before committing the transaction. If the actual on-chain execution moves an asset that isn't covered by a matching post-condition, the transaction is rolled back (fees are still charged).

### Post-condition modes

There are two modes, set as a single byte in the serialized transaction:

| Mode | Byte | Behaviour |
|---|---|---|
| **Allow** | `0x01` | Any asset movement is permitted, whether or not a post-condition covers it |
| **Deny** | `0x02` | Only asset movements explicitly covered by a listed post-condition are permitted; anything else causes a rollback |

`call_contract.py` currently uses **allow mode** (`0x01`) with zero post-conditions. This was necessary because the Zest Protocol `supply-collateral-add` function mints `v0-vault-stx::zft` receipt tokens back to the caller — an asset movement we didn't anticipate when building the transaction. In deny mode that rollback would abort the transaction, as we observed during testing.

### Why deny mode is better for production

Allow mode is fine for exploratory testing, but it removes a critical safeguard. In deny mode you are making an explicit, verifiable commitment about what the transaction will do to your assets. Some concrete risks that deny mode guards against:

**Rug-pull / malicious contract upgrades.** A contract you trusted at time-of-integration might later be upgraded to drain additional tokens. Deny mode means those unexpected transfers never succeed — your transaction reverts before any damage occurs.

**Re-entrancy side-effects.** Clarity prevents classic re-entrancy, but a contract calling into other contracts can trigger asset movements you didn't intend. Deny mode catches these at the protocol level.

**Fat-finger / misconfigured args.** If you pass the wrong amount or wrong asset as an argument, deny mode's post-conditions act as a final sanity check — the transaction won't clear unless the on-chain result matches your declared intent.

**Auditability.** A transaction carrying explicit post-conditions is self-documenting. An auditor can read the raw bytes and know exactly what asset movements the submitter authorised.

### Adding post-conditions in deny mode

To use deny mode properly, list every asset movement your transaction will trigger. For a fungible token transfer, the post-condition wire format is:

```
[type: 1 byte]          0x01 = fungible token post-condition
[principal_type: 1 byte] 0x02 = standard principal
[principal: 21 bytes]   version(1) + hash160(20)
[asset contract ver: 1]
[asset contract hash: 20]
[asset contract name: 1+N]
[asset name: 1+N]
[condition_code: 1 byte] 0x01=eq 0x02=gt 0x03=gte 0x04=lt 0x05=lte
[amount: 8 bytes]        big-endian u64
```

For an STX post-condition (type `0x00`) the asset info fields are omitted and the principal is followed directly by condition code and amount.

A helper to build a fungible token post-condition:

```python
def post_condition_ft(
    sender_address: str,
    asset_contract_address: str,
    asset_contract_name: str,
    asset_name: str,
    condition_code: int,   # 0x01=eq, 0x03=gte, etc.
    amount: int,
) -> bytes:
    sender_ver, sender_hash = _decode_stacks_address(sender_address)
    asset_ver, asset_hash   = _decode_stacks_address(asset_contract_address)
    pc = bytearray()
    pc += b"\x01"                              # post-condition type: FT
    pc += b"\x02"                              # principal type: standard
    pc += bytes([sender_ver]) + sender_hash    # 21 bytes
    pc += bytes([asset_ver]) + asset_hash      # asset contract address
    pc += _lp1(asset_contract_name)            # asset contract name
    pc += _lp1(asset_name)                     # asset name
    pc += bytes([condition_code])
    pc += struct.pack(">Q", amount)
    return bytes(pc)
```

Then in `serialize_contract_call`, switch to deny mode and include the post-condition:

```python
post_conds = post_condition_ft(
    sender_address        = sender_address,
    asset_contract_address= "SP1A27KFY4XERQCCRCARCYD1CC5N7M6688BSYADJ7",
    asset_contract_name   = "v0-vault-stx",
    asset_name            = "zft",
    condition_code        = 0x03,              # gte (receive at least some)
    amount                = 0,
)

tx += b"\x02"                                  # post_condition_mode = deny
tx += struct.pack(">I", 1)                     # 1 post-condition
tx += post_conds
```

This tells the protocol: "this transaction is only valid if the sender received at least 0 `zft` tokens." Combined with deny mode, any surprise asset movement outside that declaration causes an immediate rollback.

---

## Stacks Network Reference

| Property | Testnet | Mainnet |
|---|---|---|
| Fordefi chain value | `stacks_testnet` | `stacks_mainnet` |
| Address prefix | `ST` | `SP` |
| Hiro API base | `https://api.testnet.hiro.so` | `https://api.hiro.so` |
| Explorer | `https://explorer.hiro.so/?chain=testnet` | `https://explorer.hiro.so` |
| Faucet | `POST /extended/v1/faucets/stx` | N/A |

---

## Clarity Contract Quick Reference

Clarity is a **decidable**, **non-Turing-complete** smart contract language for Stacks.

### Key characteristics
- Interpreted on-chain (no compilation step needed for deployment)
- All functions are either `read-only` (no state changes) or `public` (state changes allowed)
- No unbounded loops — all execution terminates predictably
- Direct read access to Bitcoin block data

### Minimal contract template

```clarity
;; my-contract.clar

;; Data storage
(define-data-var my-value uint u0)

;; Read-only: returns current value (no fee, no signature)
(define-read-only (get-value)
  (ok (var-get my-value))
)

;; Public: modifies state (requires a transaction)
(define-public (set-value (new-val uint))
  (begin
    (var-set my-value new-val)
    (ok true)
  )
)
```

---

## Troubleshooting

### `FORDEFI_API_TOKEN` is invalid
Make sure you copied the full access token from the Fordefi console, with no trailing whitespace. Tokens do not expire by default but can be revoked.

### Transaction stuck in `pending_signature`
The API Signer must be running and connected to Fordefi. Check its logs and confirm it appears as "Online" in **Settings → API Signers** in the console.

### `ValueError: Private key must be on the NIST P-256 curve`
Re-run `0_generate_keys.py`. Ensure you are uploading `keys/public_key.pem` (not the private key) to the Fordefi console.

### `403 Forbidden` from Fordefi API
- Verify your API User has the **Trader** role.
- Verify the public key registered in Fordefi matches your `keys/public_key.pem`.
- Check that the timestamp on your machine is correct (clock skew > 30s can cause rejections).

### Contract deploy transaction failed
- Check the vault has sufficient STX for fees (run `4_check_status.py --address ...`).
- Verify your Clarity code is valid — use [Clarinet](https://github.com/hirosystems/clarinet) locally: `clarinet check`.
- Ensure `contract_name` is unique for your address (you cannot redeploy to the same name on the same address).

### Faucet rate limit
The Hiro testnet faucet allows one request per address per day. Use a different address or wait 24 hours.

---

## Security Checklist

- [ ] `keys/private_key.pem` is in `.gitignore` and never committed
- [ ] `.env` is in `.gitignore` and never committed
- [ ] API Signer is running in a secure, isolated environment
- [ ] API User role is **Trader** (not Admin)
- [ ] Fordefi policy rules are configured to restrict which contracts can be deployed
- [ ] For mainnet: test the complete flow on testnet first

---

## Going to Mainnet

When you are ready to deploy to mainnet:

1. Update `.env`: `STACKS_NETWORK=mainnet`
2. Create a **separate** mainnet vault in Fordefi (repeat Step 3).
3. Fund the mainnet vault with **real STX** from an exchange.
4. Update your Fordefi policy to require additional approvals for mainnet transactions.
5. Run `3_deploy_contract.py` with `--fee-priority high` for faster confirmation.

> ⚠️ Mainnet contract deployments are **irreversible**. Always thoroughly test on testnet first.

---

## Further Reading

- [Fordefi API Overview](https://docs.fordefi.com/developers/api-overview)
- [Fordefi Authentication](https://docs.fordefi.com/developers/authentication)
- [Fordefi Create Transactions](https://docs.fordefi.com/developers/getting-started/create-and-authenticate-transactions)
- [Fordefi API Signer (Docker)](https://docs.fordefi.com/developers/getting-started/set-up-an-api-signer/api-signer-docker)
- [Stacks Documentation](https://docs.stacks.co)
- [Clarity Language Reference](https://clarity-lang.org/)
- [Hiro Stacks API Reference](https://hirosystems.github.io/stacks-blockchain-api/)
- [Stacks Testnet Explorer](https://explorer.hiro.so/?chain=testnet)
- [Hiro Stacks.js (makeContractDeploy)](https://stacks.js.org/functions/_stacks_transactions.makeContractDeploy)
