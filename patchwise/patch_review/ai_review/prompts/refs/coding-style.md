## Step 3b — Kernel Coding Style Checklist

Apply **every rule below** to all changed `.c` / `.h` files before writing the
review.  These rules come directly from `Documentation/process/coding-style.rst`
(the authoritative upstream reference).  Flag any violation with the appropriate
severity tag.

### Indentation & Whitespace
- Tabs (hard, 8-column) for indentation — never spaces.
- No trailing whitespace on any line.
- Lines ≤ 80 columns; tolerate up to 100 only when breaking would hurt
  readability (e.g. long string literals, function signatures).
- One blank line between logical blocks inside a function; two blank lines
  between top-level definitions.
- No blank line immediately after an opening brace or before a closing brace.

### Braces & Spacing
- Opening brace at end of line for all compound statements
  (`if`, `for`, `while`, `switch`, function bodies).
- Closing brace on its own line, except `} else {` and `} while (…);`.
- Single-statement `if`/`for`/`while` bodies: **no braces** unless the
  companion branch uses braces.
- Space after keywords: `if (`, `for (`, `while (`, `switch (`. Use `return expr;`
  without parentheses unless the expression wraps across lines; do not flag
  `return x;` as a style violation.
- No space between function name and `(`: `foo(args)` not `foo (args)`.
- Space around binary operators; no space after unary operators.
- No space inside parentheses: `(x + y)` not `( x + y )`.

### Naming
- `lower_case_with_underscores` for variables, functions, and file-scope
  symbols — never camelCase.
- `UPPER_CASE` for macros and `#define` constants.
- Descriptive names; avoid single-letter names except loop counters (`i`, `j`).
- No Hungarian notation or type-encoding prefixes.
- Typedefs only for opaque types and function-pointer types; never typedef a
  plain struct just to avoid writing `struct`.

### Functions
- Functions should do one thing and fit on one or two screens (~50–70 lines).
- Functions that exceed ~50–70 lines or have more than ~5 levels of indentation
  are candidates for splitting; flag when this significantly harms readability.
- Exit via a single `return` at the bottom when using `goto`-based cleanup.
- `goto` labels flush-left, named after what they undo (e.g. `err_free_buf:`).

### Comments
- Block comments: `/* … */` style, preferred for all comments to match
  established kernel convention.  `//` is technically permitted in C99 kernel
  files but avoid it in new code — existing kernel style overwhelmingly uses
  `/* */` and checkpatch will warn on `//` in many contexts.
- Comment *why*, not *what* — the code already says what.
- No commented-out code in submitted patches.
- Function kerneldoc (`/**`) required for exported (`EXPORT_SYMBOL`) functions.

### Logging
- New `dev_info()` / `pr_info()` messages should be actionable, unexpected, or
  user-visible.  Working drivers should be quiet: routine probe-time resource or
  entity counts, per-boot operational breadcrumbs, and messages useful only
  while debugging should use `dev_dbg()` or tracing instead.  Flag `[MINOR]`,
  and raise it once at series level when multiple patches share the pattern.  Do
  not flag existing noisy logs unless the patch adds or promotes them.

### File Headers & Copyright

- Respect project/vendor copyright conventions already used in the same
  subsystem or file family.  Do **not** flag a missing year by itself when the
  surrounding vendor template intentionally omits years (for example,
  Qualcomm's standard `Copyright (c) Qualcomm Technologies, Inc. and/or its
  subsidiaries.` line).  Only flag clear defects such as misspelled legal entity
  names, malformed `(c)` markers, or inconsistent new headers in a copied file
  family.

### Macros & Preprocessor
- Macros with multiple statements wrapped in `do { … } while (0)`.
- Macro arguments parenthesised: `#define SQ(x) ((x) * (x))`.
- Prefer `static inline` functions over function-like macros where possible.
- `#if`/`#ifdef` blocks indented with a space after `#`:
  `# ifdef CONFIG_FOO` inside nested blocks (one space per nesting level).

### Data Structures & Types
- Use kernel types (`u8`, `u16`, `u32`, `u64`, `s32`, etc.) for fixed-width
  fields; use `int`/`long` for general-purpose values.
- Avoid `bool` in structures shared with userspace or hardware.
- Bit-fields only for hardware register maps; never rely on their layout.
- `sizeof(var)` preferred over `sizeof(type)` to stay type-safe.

### Error Paths & Resource Management
- Check every allocation / API return value.
- Keep API return-value semantics (`ERR_PTR` vs `NULL` vs both) in Step 3c;
  this style checklist should only raise generic missing-check or unwind-shape
  issues unless the code-logic pass proves a concrete semantic misuse.
- Use `devm_*` helpers where the driver model supports it.
- Unwind in reverse-init order using `goto` labels.
- Return negative `errno` values (`-ENOMEM`, `-EINVAL`, …); never positive
  error codes from kernel functions.

