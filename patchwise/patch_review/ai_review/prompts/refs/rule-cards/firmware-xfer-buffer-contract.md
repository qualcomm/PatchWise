# Rule: firmware-xfer-buffer-contract

## Trigger

Firmware, SCMI, mailbox, QMI, RPMSG, or vendor protocol code adds or changes a
message-transfer helper using APIs such as `xfer_get_init()`, `do_xfer()`,
`t->rx.len`, `rx_size`, `memcpy()`, flexible payload arrays, or caller-provided
TX/RX buffers.

## Must Check

- Is the firmware-controlled response length checked against the caller's
  destination buffer size before copying?
- Does the helper require the actual response length to match the expected
  structure size, so truncated replies cannot leave stale TX bytes or
  uninitialized stack data to be consumed as RX data?
- Are zero-length transfers guarded so `memcpy()`/`memmove()` is not called
  with a NULL source or destination, even when the length is zero?
- Are TX and RX lengths modeled independently when the same caller buffer is
  reused for both directions?
- Do all typed response structures account for endian conversion, flexible
  arrays, and minimum header sizes before reading fields?

## Evidence Needed

- Transfer allocation/init call with TX and RX sizes.
- The copy from firmware/framework RX storage into the caller buffer.
- The expected response size for each caller and the guard that enforces it.
- Any zero-length command path and its source/destination pointer values.

## Mandatory Attestation Record

When a diff adds a firmware/protocol helper that copies response bytes, include
in Code Logic Maps:

```yaml
firmware_xfer_buffer_audit:
  helper: <function at file:line>
  tx_size_source: <expression>
  expected_rx_size: <expression or per-command table>
  actual_rx_len_source: <expression, e.g. t->rx.len>
  rx_bounds_check: <YES line=... | NO — flag>
  exact_length_check: <YES line=... | NO — flag if typed response>
  zero_length_null_copy_guard: <YES | NO — flag if NULL+0 path exists>
```

Omitting this record for a newly added protocol transfer helper is a review gap.

## Safe Dismissal

Dismiss only when the framework guarantees the RX length cannot exceed the
allocated destination, the code rejects short typed replies before field reads,
and zero-length commands avoid NULL `memcpy()` operands.

## Finding Template

```text
[BUG] Firmware response length is copied without a complete buffer contract
File: <driver-path>:<copy-or-xfer-line>
Rule: firmware-xfer-buffer-contract
Evidence: <xfer sizes, actual rx length, destination size, missing guard>
Reasoning: <overflow, short-read/stale-data, or NULL zero-length memcpy path>
Impact: <stack/buffer overflow, uninitialized read, UB, or corrupted protocol state>
Suggestion: <validate exact/min/max RX length before copy/read and guard zero-length NULL copies>
```

## Severity

Use `[BUG]` for reachable overflow, uninitialized read, or NULL pointer passed
to copy helpers; `[CONCERN]` when firmware/framework length guarantees need
maintainer confirmation.
