<!-- Conditional fragment of code-logic.md — the diff shows stored-pointer / escaped-address patterns in the diff
(platform_set_drvdata/dev_set_drvdata/container_of/->priv/work/notifier
context). Apply on top of refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Stored pointer / escaped-address checklist

Apply when a helper stores a caller-provided pointer/address into a device
object, callback context, descriptor, `platform_data`, work item, or anything
that can outlive the current stack frame.
- Compare lifetimes: stack locals, compound literals, and function-local arrays
  die at return; heap/devm/static objects may outlive it.
- Identify the earliest consumer, including deferred probe, notifier, callback,
  workqueue, IRQ, DMA, IOMMU, and framework `dma_configure()`-style consumers.
- If helper and caller/consumer land in different patches, connect them with the
  series summary plus one targeted on-demand read before downgrading reachability.
- File `[BUG]` for the first reachable path storing a short-lived address in
  longer-lived state without immediate deep copy or a proven lifetime guarantee.
