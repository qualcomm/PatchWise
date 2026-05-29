# Rule: asoc-kcontrol-runtime-state

## Trigger

ASoC codec/component driver adds or changes mixer controls, especially
`SOC_*_EXT` controls with custom `.get`/`.put` callbacks, or DAI callbacks that
consume cached control state.

## Must Check

- Does each `.put` callback return `1` when it changes the control value and `0`
  only when the value is unchanged, so ALSA can notify userspace of state
  changes?
- If a control affects active playback/capture state, does `.put` either program
  the hardware immediately or document/prove that the control is intentionally
  latched until a later stream transition?
- Are cached control fields read by DAI/stream/IRQ/work callbacks protected by
  the same lock as control writes, copied once before multi-register programming,
  or otherwise proven single-threaded by ASoC core serialization?
- If one cached value is used for multiple hardware writes, is it snapshotted so
  both writes use the same value even if a control update races?

## Evidence Needed

- The control declaration (`SOC_SINGLE_EXT`, `SOC_ENUM_EXT`, etc.), `.get` and
  `.put` callbacks, and all cached fields they read/write.
- Every stream/DAI/work/IRQ path that consumes those fields and the lock or
  serialization held on each path.
- Hardware write sites that apply the cached value and whether active streams
  observe updates immediately or only after restart.

## Safe Dismissal

Dismiss only when `.put` return values follow ALSA semantics, active-stream
behavior is intentional and documented, and all cached control accesses are
serialized or snapshotted before multi-register programming.

## Finding Template

```text
[CONCERN] ASoC control cached state is not applied or serialized correctly
File: <codec-path>:<control-callback>
Rule: asoc-kcontrol-runtime-state
Evidence: <.put callback, cached field, and consumer path>
Reasoning: <why userspace notification, live hardware state, or concurrent reads can be wrong>
Impact: <missed mixer event, stale active playback setting, or inconsistent channel programming>
Suggestion: <return 1 on change, apply hardware immediately or document latch point, and serialize/snapshot cached state>
```

## Severity

`[BUG]` when a concrete race or stale value can corrupt active hardware state or
break a required control contract; `[CONCERN]` for likely live-control or
serialization issues needing maintainer confirmation; `[MINOR]` for only missing
change-notification return values with no runtime effect.
