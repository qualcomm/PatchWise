# Rule: atomic-context-sleep

## Trigger

Code runs in or adds an atomic/IRQ context — hardirq handler, `spin_lock`/
`spin_lock_irqsave` critical section, `clk_ops` callback, tasklet, or RCU read
section — and calls an API that may sleep.

## Must Check

- Does a function reachable from a hardirq `.handler`, spinlock-held region, or `clk_ops.enable/disable` call a sleeping API (`mutex_lock`, `msleep`/`usleep_range`, `*_GFP_KERNEL` allocation, `regulator_*`, `i2c`/`regmap` over a sleeping bus)?
- Is work that must sleep pushed to a threaded handler (`.thread_fn`) or workqueue instead of the hardirq path?
- Does a callback re-acquire a lock already held by its caller (non-recursive deadlock)?
- Are `might_sleep()`/`cant_sleep()` expectations consistent with the call site?

## Evidence Needed

- The context: handler registration flags, lock held across the call, or callback contract.
- The specific sleeping API invoked and its blocking guarantee.

## Safe Dismissal

Dismiss when source proves the call site is process context (threaded fn,
workqueue, ioctl) or the called API has a non-sleeping/atomic variant in use.

## Finding Template

```text
[BUG] Sleeping API invoked in atomic/IRQ context
File: <path>:<line>
Rule: atomic-context-sleep
Evidence: <context proof + sleeping API called>
Reasoning: <why this context forbids sleeping, or lock is held>
Impact: <scheduling-while-atomic, deadlock, might_sleep splat>
Suggestion: <move to threaded fn/workqueue, use atomic variant, or drop lock>
```

## Severity

`[BUG]` for a proven sleep in atomic context or self-deadlock; `[CONCERN]` when
context reachability is not fully proven from source.
