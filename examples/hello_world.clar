;; hello-world.clar
;; A minimal Clarity smart contract for testnet deployment validation.

;; --- Data storage ---
(define-data-var message (string-ascii 64) "Hello, Stacks!")

;; --- Read-only functions ---

;; Returns the stored greeting message
(define-read-only (get-message)
  (ok (var-get message))
)

;; Returns a personalised greeting
(define-read-only (greet (name (string-ascii 32)))
  (ok (concat "Hello, " name "!"))
)

;; --- Public functions ---

;; Allows the contract owner to update the message
(define-public (set-message (new-message (string-ascii 64)))
  (begin
    (asserts! (is-eq tx-sender contract-caller) (err u401))
    (var-set message new-message)
    (ok true)
  )
)
