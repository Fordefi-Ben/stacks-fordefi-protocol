;; counter.clar
;; A simple counter contract demonstrating state mutations.
;; Good for verifying successful deployment and function execution.

;; --- Data storage ---
(define-data-var counter uint u0)

;; --- Read-only functions ---

;; Returns the current counter value
(define-read-only (get-counter)
  (ok (var-get counter))
)

;; --- Public functions ---

;; Increments the counter by 1
(define-public (increment)
  (begin
    (var-set counter (+ (var-get counter) u1))
    (ok (var-get counter))
  )
)

;; Decrements the counter by 1 (with underflow protection)
(define-public (decrement)
  (begin
    (asserts! (> (var-get counter) u0) (err u1))
    (var-set counter (- (var-get counter) u1))
    (ok (var-get counter))
  )
)

;; Resets the counter to zero
(define-public (reset)
  (begin
    (var-set counter u0)
    (ok true)
  )
)
