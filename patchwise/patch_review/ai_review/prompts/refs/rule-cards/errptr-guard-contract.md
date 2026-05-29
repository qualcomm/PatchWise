# Rule: errptr-guard-contract

## Trigger

C code assigns or returns the result of an `ERR_PTR`/`IS_ERR`-family API, or
stores a pointer from a helper that can return an encoded error pointer.

## Must Check

- Is an `ERR_PTR`-capable result checked with `IS_ERR()`/`IS_ERR_OR_NULL()` rather than a bare `!ptr` NULL test?
- Is a NULL-returning allocator result wrongly checked with `IS_ERR()` instead of `!ptr`?
- Before dereference, is the error pointer rejected and `PTR_ERR()` propagated?
- When a getter is swapped for a failure-tolerant variant (e.g. `_optional`), do downstream users still guard the sentinel they now can receive?
- When the `ERR_PTR` result was assigned into a long-lived field (`obj->cdev`, `obj->regmap`, `priv->client`, etc.) BEFORE the `IS_ERR` check, is that field reset to `NULL` (or otherwise made not-dereferenceable) on the failure path before the function returns? Returning `PTR_ERR()` is not enough if the bad pointer remains in long-lived state — a sibling `_unregister`/`_free`/`_remove` that bypasses an `if (!field)` guard will dereference the error pointer on a later call.

## Evidence Needed

- The API and its documented failure encoding (`NULL` vs `ERR_PTR`).
- The guard expression actually used at the call site.
- The first dereference of the returned pointer.
- For stored-pointer cases: the assignment site, every sibling path that reads/dereferences the field, and whether any `if (!field)` (or equivalent) guard catches an `ERR_PTR` (it does not — a `!= NULL` guard treats the error pointer as live).

## Safe Dismissal

Dismiss only when the guard matches the API's failure encoding and no
dereference precedes a correct check, or source proves the value can never be an
error/NULL on the reached path.

## Finding Template

```text
[BUG] Error-pointer result used without matching guard
File: <path>:<line>
Rule: errptr-guard-contract
Evidence: <API return contract and the guard/deref site>
Reasoning: <why the guard does not match the encoding, or deref precedes check>
Impact: <NULL/error-pointer dereference, leaked error code, oops>
Suggestion: <use IS_ERR()+PTR_ERR() or !ptr to match the API contract>
```

## Severity

`[BUG]` when a wrong or missing guard reaches a dereference; `[CONCERN]` when the
encoding is plausible but not proven from source.
