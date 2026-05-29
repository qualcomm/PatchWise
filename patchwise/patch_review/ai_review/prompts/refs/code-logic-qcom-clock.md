<!-- Conditional fragment of code-logic.md — the diff shows Qualcomm clock controller framework usage (qcom_cc_desc, clk_rcg2,
alpha PLL, freq_tbl, parent_map, hw_clk_ctrl, use_rpm). Apply on top of
refs/code-logic.md §3c.2 Data-Flow Picture base prose. -->

#### Qualcomm clock controller driver audit

Apply when a patch introduces or modifies a Qcom clock controller driver
(files matching `drivers/clk/qcom/*`). These rules target framework-specific
correctness hazards that pure C logic review misses.

**Mandatory attestation requirement:** for every new or modified Qcom CC driver
file, the Code Logic Maps `<pre>` block MUST include this record:

    qcom_clock_audit:
      parent_data_distinct: <PASS|FAIL — list each parent_map P_* and its .hw target>
      desc_sibling_compare: <sibling file> fields=[list present] missing=[list absent or NONE]
      hw_clk_ctrl_check: <PASS|N/A — for each RCG with .hw_clk_ctrl=true, state role and sibling match>
      use_rpm_check: <PRESENT|ABSENT — state whether .use_rpm is in qcom_cc_desc>

Omitting this record is a self-audit failure. Each line must quote source
evidence, not assert "verified" or "consistent with sibling."

---

**Parent-data / parent-map consistency.**

Each distinct `P_*` enum entry in `parent_map[]` must resolve to a distinct
clock source in the corresponding `parent_data[]` array. When the hardware has
a post-divider output (e.g. `OUT_EVEN`, `OUT_ODD`, `OUT_AUX`, `OUT_AUX2`), the
`parent_data` entry must reference a separate `clk_alpha_pll_postdiv` struct —
not the main PLL `clkr.hw`. Pointing two parent_map entries at the same `.hw`
without an intervening postdiv causes the clock framework to report the main PLL
rate for both, while hardware actually divides.

Bad-pattern shape:

    static const struct parent_map cc_parent_map[] = {
        { P_BI_TCXO, 0 },
        { P_CC_PLL0_OUT_EVEN, 3 },   /* physically runs at PLL/2 */
        { P_CC_PLL0_OUT_MAIN, 5 },
    };
    static const struct clk_parent_data cc_parent_data[] = {
        { .index = DT_BI_TCXO },
        { .hw = &cc_pll0.clkr.hw },   /* ← WRONG: same hw for EVEN and MAIN */
        { .hw = &cc_pll0.clkr.hw },
    };

Decisive evidence (all three required):
(1) two or more `P_*` entries in parent_map pointing to different mux-select
values; (2) the corresponding parent_data entries referencing the identical
`.hw` pointer (same struct); (3) absence of a `clk_alpha_pll_postdiv` struct
for the divided output in the file.

Severity: `[BUG]` — CCF reports wrong rate; `F()` table entries referencing the
divided parent compute incorrect divider/MN settings, programming hardware to
the wrong frequency.

**`qcom_cc_desc` sibling-field consistency.**

When a new Qcom CC driver is introduced, compare its `qcom_cc_desc` struct
fields against the nearest sibling driver of the same clock-controller class
(e.g. `camcc-milos.c` for `camcc-eliza.c`, `videocc-milos.c` for
`videocc-eliza.c`). Flag omissions of fields that ALL sibling drivers populate:

| Field | Purpose | Severity if missing |
|-------|---------|---------------------|
| `.use_rpm` | Enables runtime PM before PLL writes in `qcom_cc_really_probe` | `[BUG]` — writes to unpowered registers cause sync external abort |
| `.gdscs` / `.num_gdscs` | Registers power domains | `[CONCERN]` — consumers get -ENODEV |
| `.driver_data` | PLL config, critical CBCRs | `[CONCERN]` — PLLs unconfigured |

Decisive evidence (all three required):
(1) the new driver's `qcom_cc_desc` initialization (quote fields present);
(2) the sibling driver's `qcom_cc_desc` showing the missing field (name the
sibling file and use on-demand read to verify); (3) the `qcom_cc_really_probe`
code path that consumes the field (or state "PM enablement gate" for `.use_rpm`).

Valid dismissal: commit message or cover letter explicitly explains the omission
with hardware justification (e.g. rails always-on, no GDSCs on this block).
"Consistent with hardware" or "no impact" without quoting the commit message
justification is NOT a valid dismissal.

**`.hw_clk_ctrl` appropriateness on RCG2 clocks.**

`.hw_clk_ctrl = true` tells the framework the RCG is hardware-triggered — the
CMD_UPDATE bit is pulsed by hardware, not software. When set on a
software-controlled RCG (bus clocks like AHB, XO sources) using
`clk_rcg2_shared_ops`, `update_config()` waits for a hardware trigger that
never arrives, causing a timeout and failed clock configuration.

Bad-pattern shape:

    static struct clk_rcg2 video_cc_ahb_clk_src = {
        .cmd_rcgr = 0x8018,
        .hw_clk_ctrl = true,          /* ← WRONG on software-controlled AHB */
        .clkr.hw.init = &(const struct clk_init_data) {
            .ops = &clk_rcg2_shared_ops,
        },
    };

Decisive evidence (all three required):
(1) the RCG struct with `.hw_clk_ctrl = true` and `.ops = &clk_rcg2_shared_ops`
(quote both); (2) the equivalent RCG in the nearest sibling driver does NOT set
`.hw_clk_ctrl` (name the sibling and use on-demand read to verify); (3) the
clock's role — AHB bus clock or XO distribution clock — indicating software
control.

Valid dismissal: the RCG is genuinely hardware-gated (GDSC collapse trigger,
MVS hardware sequencer) AND the sibling driver also sets the flag for the
equivalent RCG. Quote the sibling's equivalent struct showing `.hw_clk_ctrl =
true`.

Severity: `[BUG]` — `update_config()` timeout leaves clock stuck in bootloader
state; downstream CBCRs may fail to enable.

**Freq-table / parent-rate cross-check.**

For `F()` entries referencing a divided PLL output (`P_*_OUT_EVEN`,
`P_*_OUT_ODD`, etc.), verify the arithmetic:
`expected_rate = parent_rate / pre_div * m / n`. If `parent_data` maps the P_*
to the main PLL (no postdiv struct), the CCF parent_rate is the full PLL
frequency, not the divided output. The `F()` macro parameters that produce the
desired rate from the full PLL frequency will program different hardware dividers
than intended for the post-divided rate.

Record in `codebase audit: callees ...`: the PLL configured frequency (from
`clk_alpha_pll_configure` call or `.config` struct), the postdiv factor (if
modeled), and the resulting parent rate fed to each `F()` entry.
