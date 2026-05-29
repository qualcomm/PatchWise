## Step 3b — Kernel Coding Style Checklist

Apply every rule below to changed `.c`/`.h` files before writing the review.
Rules follow `Documentation/process/coding-style.rst`; flag violations with the
appropriate severity.

### Indentation & Whitespace
- Use hard tabs with 8-column stops for indentation; never use spaces for indent.
- No trailing whitespace.
- Keep lines ≤ 80 columns; tolerate up to 100 only when splitting hurts
  readability, such as long strings or function signatures.
- Use one blank line between logical blocks in a function and two between
  top-level definitions.
- No blank line immediately after `{` or before `}`.

### Braces & Spacing
- Put opening braces at end of line for compound statements and function bodies.
- Put closing braces on their own line except `} else {` and `} while (...);`.
- Omit braces for single-statement `if`/`for`/`while` bodies unless a companion
  branch uses braces.
- Use `if (`, `for (`, `while (`, `switch (`; use `return expr;` without
  parentheses unless wrapping requires them.
- No space between function name and `(`; use spaces around binary operators,
  no spaces after unary operators, and no spaces inside parentheses.

### Naming
- Use `lower_case_with_underscores` for variables/functions/file-scope symbols
  and `UPPER_CASE` for macros/constants.
- Prefer descriptive names; single-letter names are acceptable for loop counters.
- No Hungarian/type-encoding prefixes.
- Typedef only opaque types and function-pointer types; do not typedef a plain
  struct only to avoid `struct`.

### Functions
- Functions should do one thing and usually fit in ~50–70 lines.
- Flag excessive length or >5 indentation levels when readability suffers.
- Use bottom `return` with `goto` cleanup when appropriate.
- Keep `goto` labels flush-left and name them for what they undo, e.g.
  `err_free_buf:`.

### Comments
- Prefer `/* ... */`; avoid new `//` comments even though C99 permits them.
- Explain why, not what; remove commented-out code.
- Require kerneldoc (`/**`) for exported (`EXPORT_SYMBOL`) functions.

### Logging
- New `dev_info()`/`pr_info()` must be actionable, unexpected, or user-visible.
  Routine probe counts, boot breadcrumbs, and debug-only messages should use
  `dev_dbg()` or tracing. Flag `[MINOR]`, raising once at series level for a
  repeated pattern. Do not flag pre-existing noisy logs unless the patch adds or
  promotes them.

### File Headers & Copyright
- Follow the file/subsystem/vendor convention. Do not flag a missing year alone
  when the local template omits years, such as Qualcomm's standard copyright
  line. Flag only clear defects: misspelled entities, malformed `(c)`, or a new
  header inconsistent with a copied file family.

### Macros & Preprocessor
- Wrap multi-statement macros in `do { ... } while (0)`.
- Parenthesize macro arguments, e.g. `#define SQ(x) ((x) * (x))`.
- Prefer `static inline` over function-like macros where possible.
- In nested preprocessor blocks, indent `#` directives with one space per level,
  e.g. `# ifdef CONFIG_FOO`.

### Data Structures & Types
- Use kernel fixed-width types (`u8`, `u16`, `u32`, `u64`, `s32`, etc.) for
  fixed-width fields; use `int`/`long` for general-purpose values.
- Avoid `bool` in userspace- or hardware-shared structures.
- Use bit-fields only for hardware register maps; do not rely on their layout.
- Prefer `sizeof(var)` over `sizeof(type)`.

### Error Paths & Resource Management
- Check every allocation/API return value.
- Keep API-specific return semantics (`ERR_PTR`, `NULL`, or both) in Step 3c;
  this checklist should raise only generic missing-check or unwind-shape issues
  unless Step 3c proves semantic misuse.
- Use `devm_*` helpers where the driver model supports them.
- Unwind in reverse-init order with `goto` labels.
- Return negative errno values, never positive kernel errors. Match the errno
  to the failing operation. Reserve `-ENOMEM` for genuine allocation failures.
  For other failure classes, choose by semantics: `-ENODEV` when hardware,
  match data, or device descriptor is absent; `-EINVAL` when arguments or
  configuration are malformed; `-ENODATA`/`-ENOENT` when a lookup returned no
  data for a valid query; `-EIO` for transport/bus errors; `-EPROBE_DEFER`
  when a dependency is not yet ready. Quote the errno that matches the
  underlying API (e.g. preserve the value returned by the helper) rather
  than re-classifying it as `-ENOMEM`.

### Format Strings
- For every new or changed printf-like call (`dev_set_name()`, `snprintf()`,
  `dev_*()`, `pr_*()`, trace helpers), compare each format specifier with the
  argument type and signedness even when the object is not built by the current
  config. Use `%u` for unsigned integer values unless the argument is
  intentionally cast to a signed type.
