# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause

"""A dependency-free web dashboard for PatchWise observability.

Reads the appended run records from ``SANDBOX_PATH/ai_code_review/observability.json``
and the shared ``SANDBOX_PATH/tool_calls.log``, aggregates them weekly and in
total, and serves a single self-contained HTML page (FastAPI + uvicorn, no
external front-end assets — safe on air-gapped hosts) plus a ``/api/stats`` JSON
endpoint. The artifacts are re-read on every request, so the page reflects the
latest runs without a restart.

FastAPI/uvicorn are imported lazily inside ``run_dashboard_mode`` so the other
patchwise modes (which import this module for its CLI args) don't pay the cost.
"""

import datetime
import json
import logging
import re
from html import escape
from typing import Any, Dict, List, Tuple

from patchwise import SANDBOX_PATH, __version__

logger = logging.getLogger(__name__)

OBS_PATH = SANDBOX_PATH / "ai_code_review" / "observability.json"
TOOL_LOG_PATH = SANDBOX_PATH / "tool_calls.log"

# The call name is anchored right after `iter=<n> | call=`, and the ok flag is
# anchored to end-of-line — args (which may themselves contain `ok=...` or
# `call=...`) sit inside the greedy span between and can't be mistaken for either.
_TOOL_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| task=(?P<task>\S+) \| "
    r"iter=\d+ \| call=(?P<call>\w+)\(.*\| ok=(?P<ok>True|False)\s*$"
)


# ── loading ──────────────────────────────────────────────────────────────────


def load_runs() -> List[Dict[str, Any]]:
    """Return the list of run records; [] if the file is absent/corrupt."""
    try:
        with open(OBS_PATH) as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else [data]


def load_tool_calls() -> List[Tuple[datetime.datetime, str, str, bool]]:
    """Parse tool_calls.log into (timestamp, task, tool, ok) tuples."""
    out: List[Tuple[datetime.datetime, str, str, bool]] = []
    try:
        with open(TOOL_LOG_PATH) as f:
            for line in f:
                m = _TOOL_LINE.match(line)
                if not m:
                    continue
                ts = datetime.datetime.strptime(m["ts"], "%Y-%m-%d %H:%M:%S")
                out.append((ts, m["task"], m["call"], m["ok"] == "True"))
    except FileNotFoundError:
        pass
    return out


# ── aggregation ────────────────────────────────────────────────────────────────


def _week_key(dt: datetime.datetime) -> str:
    """ISO year-week label, e.g. '2026-W30'."""
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def _run_week(run: Dict[str, Any]) -> str:
    ts = run.get("timestamp")
    if not ts:
        return "undated"
    try:
        return _week_key(datetime.datetime.fromisoformat(ts))
    except ValueError:
        return "undated"


def _blank_stats() -> Dict[str, Any]:
    return {
        "runs": 0,
        "issues_before": 0,
        "issues_after": 0,
        "likely_fps": 0,
        "input": 0,
        "cached": 0,
        "reasoning": 0,
        "output": 0,
        "tokens": 0,
        "total_time": 0.0,
        "ai_wait": 0.0,
        "retries": 0,
        "plan_converged": 0,
        "iter_cap_hits": 0,
        "peak_prompt": 0,
        "plan_rounds": 0,
        "planner_tasks": 0,
    }


def _fold_run(acc: Dict[str, Any], run: Dict[str, Any]) -> None:
    # Pre-overhaul records stored tokens_used as a scalar total; new records use
    # the {input,cached,reasoning,output,total} breakdown. Normalize to a dict.
    toks = run.get("tokens_used")
    if not isinstance(toks, dict):
        toks = {"total": toks or 0}
    acc["runs"] += 1
    acc["issues_before"] += run.get("issues_before_filter") or 0
    acc["issues_after"] += run.get("issues_after_filter") or 0
    acc["likely_fps"] += run.get("total_likely_false_positives") or 0
    acc["input"] += toks.get("input") or 0
    acc["cached"] += toks.get("cached") or 0
    acc["reasoning"] += toks.get("reasoning") or 0
    acc["output"] += toks.get("output") or 0
    acc["tokens"] += toks.get("total") or 0
    acc["total_time"] += run.get("total_time") or 0.0
    acc["ai_wait"] += run.get("time_waiting_for_ai_response") or 0.0
    acc["retries"] += run.get("api_retries") or 0
    acc["plan_converged"] += 1 if run.get("plan_converged") else 0
    acc["iter_cap_hits"] += 1 if run.get("exec_iter_cap_hit") else 0
    acc["peak_prompt"] = max(acc["peak_prompt"], run.get("peak_prompt_tokens") or 0)
    acc["plan_rounds"] += run.get("total_plan_rounds") or 0
    acc["planner_tasks"] += run.get("total_planner_tasks") or 0


def aggregate_runs(
    runs: List[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Return (total_stats, {week: stats}) folded over the run records."""
    total = _blank_stats()
    weekly: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        _fold_run(total, run)
        _fold_run(weekly.setdefault(_run_week(run), _blank_stats()), run)
    return total, weekly


def aggregate_tools(
    calls: List[Tuple[datetime.datetime, str, str, bool]],
) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]]]:
    """Return (total, {week: stats}) where stats = {calls, ok, by_tool}."""

    def blank() -> Dict[str, Any]:
        return {"calls": 0, "ok": 0, "by_tool": {}}

    total = blank()
    weekly: Dict[str, Dict[str, Any]] = {}

    def fold(acc: Dict[str, Any], tool: str, ok: bool) -> None:
        acc["calls"] += 1
        acc["ok"] += 1 if ok else 0
        acc["by_tool"][tool] = acc["by_tool"].get(tool, 0) + 1

    for ts, _task, tool, ok in calls:
        fold(total, tool, ok)
        fold(weekly.setdefault(_week_key(ts), blank()), tool, ok)
    return total, weekly


# ── rendering ──────────────────────────────────────────────────────────────────

_STYLE = """
:root {
  --bg:#f4f6fa; --panel:#ffffff; --panel2:#eef1f7; --line:#dde2ed;
  --fg:#1a1d26; --dim:#5b6376; --faint:#9aa0b3;
  --accent:#2f6de0; --accent2:#5a3fd4; --ok:#1a9e52; --warn:#c47d0a; --bad:#d63a3f;
}
* { box-sizing: border-box; }
body { font: 14px/1.55 -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
       margin: 0; padding: 2.5rem 1.5rem; background: var(--bg);
       color: var(--fg); }
.wrap { max-width: 1140px; margin: 0 auto; }
header { display: flex; align-items: baseline; gap: .75rem; flex-wrap: wrap;
         margin-bottom: 2rem; }
h1 { font-size: 1.45rem; font-weight: 650; margin: 0; letter-spacing: -.01em; }
.sub { color: var(--dim); font-size: .85rem; }
h2 { font-size: .82rem; font-weight: 600; text-transform: uppercase; letter-spacing: .08em;
     color: var(--dim); margin: 2.4rem 0 .9rem; display: flex; align-items: center; gap: .6rem; }
h2::before { content: ""; width: 3px; height: 1em; border-radius: 2px;
             background: linear-gradient(var(--accent), var(--accent2)); }
.cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(172px, 1fr)); gap: .8rem; }
.subhead { color: var(--faint); font-size: .72rem; text-transform: uppercase; letter-spacing: .06em;
           margin: 1rem 0 .6rem; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
        padding: .9rem 1.05rem; transition: border-color .15s, transform .15s; }
.card:hover { border-color: #33405a; transform: translateY(-1px); }
.card .label { color: var(--dim); font-size: .7rem; text-transform: uppercase; letter-spacing: .05em; }
.card .value { font-size: 1.55rem; font-weight: 640; margin-top: .25rem; letter-spacing: -.01em; }
.card .value small { font-size: .78rem; color: var(--dim); font-weight: 400; margin-left: .15rem; }
.card .sub-rows { margin-top: .45rem; border-top: 1px solid var(--line); padding-top: .4rem;
                  display: flex; flex-direction: column; gap: .15rem; }
.card .sub-row { display: flex; justify-content: space-between; font-size: .75rem; color: var(--dim); }
.card .sub-row .sr-val { font-variant-numeric: tabular-nums; color: var(--fg); font-weight: 500; }
.panel { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
         overflow: hidden; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.empty { color: var(--dim); padding: 1.2rem 1.2rem; }
/* per-tool breakdown bar chart */
.bchart { width: 100%; height: auto; display: block; padding: .8rem 1.1rem 1rem; }
.bchart text { font: 12px -apple-system, "Segoe UI", Roboto, sans-serif; }
.bchart .c-lbl { fill: var(--dim); }
.bchart .c-val { fill: var(--fg); font-variant-numeric: tabular-nums; }
.bchart .c-track { fill: var(--panel2); }
.bchart .c-failbar { fill: var(--bad); }
.bchart .c-fail { fill: var(--bad); font-variant-numeric: tabular-nums; }
.bchart .c-okrate { fill: var(--faint); font-variant-numeric: tabular-nums; }
.bchart .c-legend { fill: var(--dim); }
/* tool-calls time-series chart */
.tc { padding: 1rem 1.1rem 1.2rem; }
.tc-head { display: flex; align-items: center; justify-content: space-between; gap: 1rem;
           margin-bottom: .5rem; }
.tc-tabs { display: inline-flex; background: var(--panel2); border: 1px solid var(--line);
           border-radius: 9px; padding: 3px; gap: 2px; }
.tc-btn, .bt-btn, .sc-btn { appearance: none; border: 0; background: transparent; color: var(--dim);
          font: inherit; font-size: .8rem; padding: .3rem .7rem; border-radius: 6px;
          cursor: pointer; transition: background .12s, color .12s; }
.tc-btn:hover, .bt-btn:hover, .sc-btn:hover { color: var(--fg); }
.tc-btn.on, .bt-btn.on, .sc-btn.on { background: linear-gradient(var(--accent), var(--accent2)); color: #fff; }
.tc-tot { color: var(--dim); font-size: .82rem; font-variant-numeric: tabular-nums; }
.tc-plot { position: relative; }
.tc-svg { width: 100%; height: auto; display: block; }
.bt { padding: 1rem 1.1rem 1.2rem; }
.bt-cap { color: var(--dim); font-size: .82rem; font-variant-numeric: tabular-nums;
          margin: .2rem 0 .2rem; }
.tc-grid { stroke: var(--line); stroke-width: 1; }
.tc-axis { fill: var(--faint); font: 11px ui-monospace, monospace; }
.tc-area { fill: rgba(47,109,224,.10); stroke: none; }
.tc-line { fill: none; stroke: var(--accent); stroke-width: 2; }
.tc-dot { fill: var(--accent); }
.tc-cursor { stroke: var(--faint); stroke-width: 1; stroke-dasharray: 3 3; }
.tc-tip { position: absolute; pointer-events: none; background: #fff; border: 1px solid var(--line);
          border-radius: 8px; padding: .35rem .55rem; font-size: .78rem; color: var(--fg);
          white-space: nowrap; box-shadow: 0 6px 20px rgba(0,0,0,.4); }
.tc-tip b { color: var(--accent); } .tc-tip span { color: var(--dim); margin-left: .4rem; }
.delta { font-size: .7rem; font-weight: 500; padding: .1rem .35rem; border-radius: 4px;
         margin-left: .3rem; vertical-align: middle; letter-spacing: 0; }
.delta-up   { background: rgba(95,208,138,.15); color: var(--ok); }
.delta-down { background: rgba(242,84,91,.15);  color: var(--bad); }
.delta-flat { background: rgba(139,147,167,.1); color: var(--faint); }
footer { margin-top: 3rem; padding-top: 1rem; border-top: 1px solid var(--line);
         color: var(--faint); font-size: .78rem; }
footer .mono { font-family: ui-monospace, monospace; }
"""


def _fmt_int(n: float) -> str:
    return f"{int(round(n)):,}"


def _fmt_tokens(n: float) -> str:
    n = float(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.2f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return _fmt_int(n)


def _fmt_dur(seconds: float) -> str:
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def _pct(num: float, den: float) -> str:
    return f"{100 * num / den:.0f}%" if den else "—"


def _delta_badge(curr: float, prev: float, invert: bool = False) -> str:
    """Return a finished delta <span> (or '' when there's no prior period).

    invert=True means higher is worse (e.g. retries, FP rate).
    """
    if not prev:
        return ""
    pct = (curr - prev) / prev * 100
    if abs(pct) < 1:
        cls, txt = "delta-flat", "±0%"
    else:
        up = pct > 0
        cls = "delta-up" if up != invert else "delta-down"
        txt = f"{'↑' if up else '↓'}{abs(pct):.0f}%"
    return f'<span class="delta {cls}">{txt}</span>'


def _card(
    label: str,
    value: str,
    sub: str = "",
    delta: str = "",
    highlight: bool = False,
    rows: List[Tuple[str, str]] = None,
) -> str:
    """A stat card; `delta` is a finished badge span, `rows` optional sub-rows."""
    tail = f" <small>{escape(sub)}</small>" if sub else ""
    val_style = ' style="color:var(--accent)"' if highlight else ""
    sub_html = ""
    if rows:
        inner = "".join(
            f'<div class="sub-row"><span>{escape(r[0])}</span>'
            f'<span class="sr-val">{escape(r[1])}</span></div>'
            for r in rows
        )
        sub_html = f'<div class="sub-rows">{inner}</div>'
    return (
        f'<div class="card"><div class="label">{escape(label)}</div>'
        f'<div class="value"{val_style}>{escape(value)}{tail}{delta}</div>'
        f"{sub_html}</div>"
    )


def _fmt_avg(n: float) -> str:
    """One-decimal mean, trimming a trailing .0 (e.g. 6.3, 12)."""
    return f"{n:.1f}".rstrip("0").rstrip(".")


def _avg_cards(stats: Dict[str, Any], scope: str, prev: Dict[str, Any] = None) -> str:
    """Per-patch averages for a scope ('this week' / 'total').

    When prev is supplied, delta badges compare each per-patch average against
    the prior period's per-patch average.
    """
    n = stats["runs"]
    if not n:
        return (
            '<div class="panel"><p class="empty">'
            f"No patches reviewed {escape(scope)}.</p></div>"
        )
    pn = (prev or {}).get("runs", 0)

    def d(curr_sum: float, prev_sum: float, invert: bool = False) -> str:
        if not n or not pn:
            return ""
        return _delta_badge(curr_sum / n, prev_sum / pn, invert=invert)

    def subhead(title: str) -> str:
        return f'<div class="subhead">{escape(title)}</div>'

    overview_cards = [
        _card("Patches", _fmt_int(n)),
        _card(
            "AI wait",
            _fmt_dur(stats["ai_wait"] / n),
            "per patch",
            d(stats["ai_wait"], (prev or {}).get("ai_wait", 0), invert=True),
        ),
        _card(
            "Time",
            _fmt_dur(stats["total_time"] / n),
            "per patch",
            d(stats["total_time"], (prev or {}).get("total_time", 0), invert=True),
        ),
        _card(
            "AI API Retries",
            _fmt_avg(stats["retries"] / n),
            "per patch",
            d(stats["retries"], (prev or {}).get("retries", 0), invert=True),
        ),
    ]
    plan_cards = [
        _card(
            "Plan rounds",
            _fmt_avg(stats["plan_rounds"] / n),
            delta=d(
                stats["plan_rounds"], (prev or {}).get("plan_rounds", 0), invert=True
            ),
        ),
        _card("Plan converged", _pct(stats["plan_converged"], n)),
    ]
    exec_cards = [
        _card("Iter cap hit", _pct(stats["iter_cap_hits"], n)),
    ]
    filter_cards = [
        _card(
            "Found",
            _fmt_avg(stats["issues_before"] / n),
            "issues/patch",
            d(stats["issues_before"], (prev or {}).get("issues_before", 0)),
        ),
        _card(
            "Kept",
            _fmt_avg(stats["issues_after"] / n),
            "issues/patch",
            d(stats["issues_after"], (prev or {}).get("issues_after", 0)),
        ),
        _card(
            "Likely FP",
            _fmt_avg(stats["likely_fps"] / n),
            "per patch",
            d(stats["likely_fps"], (prev or {}).get("likely_fps", 0), invert=True),
        ),
    ]
    token_cards = [
        _card(
            "Total",
            _fmt_tokens(stats["tokens"] / n),
            "per patch",
            d(stats["tokens"], (prev or {}).get("tokens", 0), invert=True),
            highlight=True,
        ),
        _card(
            "Input",
            _fmt_tokens(stats["input"] / n),
            "per patch",
            d(stats["input"], (prev or {}).get("input", 0), invert=True),
            rows=[
                ("Prompt", _fmt_tokens((stats["input"] - stats["cached"]) / n)),
                (
                    "Cached",
                    _fmt_tokens(stats["cached"] / n)
                    + f'  {_pct(stats["cached"], stats["input"])}',
                ),
            ],
        ),
        _card(
            "Reasoning",
            _fmt_tokens(stats["reasoning"] / n),
            "per patch",
            d(stats["reasoning"], (prev or {}).get("reasoning", 0), invert=True),
        ),
        _card(
            "Output",
            _fmt_tokens(stats["output"] / n),
            "per patch",
            d(stats["output"], (prev or {}).get("output", 0), invert=True),
        ),
    ]
    return (
        '<div class="cards">'
        + "".join(overview_cards)
        + "</div>"
        + subhead("Plan")
        + '<div class="cards">'
        + "".join(plan_cards)
        + "</div>"
        + subhead("Exec")
        + '<div class="cards">'
        + "".join(exec_cards)
        + "</div>"
        + subhead("Filter")
        + '<div class="cards">'
        + "".join(filter_cards)
        + "</div>"
        + subhead("Tokens per patch")
        + '<div class="cards">'
        + "".join(token_cards)
        + "</div>"
    )


# The trailing-window periods shown on every time-series toggle, in order.
_PERIOD_LABELS = {"day": "24h", "week": "7d", "month": "30d", "year": "1y"}


def _bucketed(
    times: List[datetime.datetime], now: datetime.datetime
) -> Dict[str, List[Dict[str, Any]]]:
    """Count events in trailing windows at four granularities, gaps filled with 0.

    Day:   each hour in the last 24 hours
    Week:  each day in the last 7 days
    Month: each day in the last 30 days
    Year:  each month in the last 365 days

    Each point is {t: sort-key, label: axis label, v: count}.
    """

    def series(window_start, key_fmt, label_fmt, step_next) -> List[Dict[str, Any]]:
        counts: Dict[str, int] = {}
        labels: Dict[str, str] = {}
        for dt in times:
            if dt >= window_start:
                k = dt.strftime(key_fmt)
                counts[k] = counts.get(k, 0) + 1
                labels[k] = dt.strftime(label_fmt)
        out: List[Dict[str, Any]] = []
        cur = window_start
        seen: set = set()
        while cur <= now:
            k = cur.strftime(key_fmt)
            if k not in seen:
                seen.add(k)
                out.append(
                    {
                        "t": k,
                        "label": labels.get(k, cur.strftime(label_fmt)),
                        "v": counts.get(k, 0),
                    }
                )
            cur = step_next(cur)
        return out

    def add_month(dt: datetime.datetime) -> datetime.datetime:
        y, m = dt.year + (dt.month // 12), dt.month % 12 + 1
        return datetime.datetime(y, m, 1)

    hour = lambda d: d + datetime.timedelta(hours=1)
    day = lambda d: d + datetime.timedelta(days=1)
    # Day: 24 hourly buckets — start from the hour 23h ago so the walk ends at now's hour.
    day_start = (now - datetime.timedelta(hours=23)).replace(
        minute=0, second=0, microsecond=0
    )
    midnight = {"hour": 0, "minute": 0, "second": 0, "microsecond": 0}
    week_start = (now - datetime.timedelta(days=6)).replace(
        **midnight
    )  # 7 daily buckets
    month_start = (now - datetime.timedelta(days=29)).replace(
        **midnight
    )  # 30 daily buckets
    # Year: monthly buckets covering the last 365 days
    year_cutoff = now - datetime.timedelta(days=365)
    year_start = datetime.datetime(year_cutoff.year, year_cutoff.month, 1)

    return {
        "day": series(day_start, "%Y-%m-%d %H", "%H:00", hour),
        "week": series(week_start, "%Y-%m-%d", "%b %d", day),
        "month": series(month_start, "%Y-%m-%d", "%b %d", day),
        "year": series(year_start, "%Y-%m", "%b %Y", add_month),
    }


def _timeseries_panel(
    cid: str, series: Dict[str, List[Dict[str, Any]]], unit: str
) -> str:
    """An interactive time-series chart with a 24h/7d/30d/1y toggle, drawn
    client-side. `cid` scopes the panel so several can coexist on one page;
    `unit` is the noun shown in the total and tooltip (e.g. 'calls', 'patches').
    """
    has_data = any(series.values())
    tabs = "".join(
        f'<button class="tc-btn" data-p="{p}">{lbl}</button>'
        for p, lbl in _PERIOD_LABELS.items()
    )
    payload = json.dumps({"series": series, "unit": unit, "hasData": has_data})
    return (
        f'<div class="panel tc" id="{cid}">'
        f'<div class="tc-head"><div class="tc-tabs">{tabs}</div>'
        '<div class="tc-tot"></div></div>'
        '<div class="tc-plot"><svg class="tc-svg" viewBox="0 0 760 300" '
        'preserveAspectRatio="xMidYMid meet" role="img"></svg>'
        '<div class="tc-tip" hidden></div></div>'
        f'<script>window.__initTS("{cid}",{payload})</script>'
        "</div>"
    )


_CHART_JS = r"""
window.__initTS=function(cid,cfg){
  var root=document.getElementById(cid); if(!root)return;
  var S=cfg.series, unit=cfg.unit, hasData=cfg.hasData;
  var period='week';
  if(!S.week||!S.week.length)period='month';
  if(!S[period]||!S[period].length)period=['day','week','month','year'].find(function(p){return S[p]&&S[p].length;})||'week';
  var svg=root.querySelector('.tc-svg'), tip=root.querySelector('.tc-tip'),
      tot=root.querySelector('.tc-tot'), btns=root.querySelectorAll('.tc-btn'), cursor=null;
  var W=760,H=300,m={l:46,r:18,t:18,b:40}, iw=W-m.l-m.r, ih=H-m.t-m.b, NS='http://www.w3.org/2000/svg';
  function el(n,a){var e=document.createElementNS(NS,n);for(var k in a)e.setAttribute(k,a[k]);return e;}
  var pts=[];
  function xat(i,n){return n<=1?m.l+iw/2:m.l+iw*i/(n-1);}
  function draw(){
    var d=S[period]||[], n=d.length;
    while(svg.firstChild)svg.removeChild(svg.firstChild);
    /* always draw 5 gridlines + y-axis labels */
    var ceil = n ? Math.max(1, Math.ceil(Math.max.apply(null,d.map(function(p){return p.v;}))/1)*1) : 1;
    /* round ceil to a nice number */
    if(ceil>1){var mag=Math.pow(10,Math.floor(Math.log10(ceil)));ceil=Math.ceil(ceil/mag)*mag;}
    var yat=function(v){return m.t+ih*(1-v/ceil);};
    for(var g=0;g<=4;g++){
      var v=ceil*g/4, y=yat(v);
      svg.appendChild(el('line',{x1:m.l,y1:y,x2:W-m.r,y2:y,'class':'tc-grid'}));
      var t=el('text',{x:m.l-8,y:y,'class':'tc-axis','text-anchor':'end','dominant-baseline':'central'});
      t.textContent=(v>=1000?(Math.round(v/100)/10)+'k':Math.round(v)); svg.appendChild(t);
    }
    /* empty state: centered "No data" label over the flat zero line */
    if(!hasData||!n){
      var sum_=d.reduce(function(a,p){return a+p.v;},0);
      tot.textContent=sum_.toLocaleString()+' '+unit;
      svg.appendChild(el('line',{x1:m.l,y1:yat(0),x2:W-m.r,y2:yat(0),'class':'tc-grid'}));
      var em=el('text',{x:W/2,y:m.t+ih/2,'class':'tc-axis','text-anchor':'middle','dominant-baseline':'central'});
      em.textContent='No data for this period'; svg.appendChild(em);
      return;
    }
    var sum=d.reduce(function(a,p){return a+p.v;},0);
    tot.textContent=sum.toLocaleString()+' '+unit;
    var line='';
    pts=[];
    d.forEach(function(p,i){
      var x=xat(i,n), y=yat(p.v); pts.push({x:x,y:y,p:p});
      line+=(i?'L':'M')+x.toFixed(1)+' '+y.toFixed(1)+' ';
    });
    var area='M'+xat(0,n).toFixed(1)+' '+yat(0).toFixed(1)+' '+line.replace(/^M/,'L')
         +'L'+xat(n-1,n).toFixed(1)+' '+yat(0).toFixed(1)+' Z';
    svg.appendChild(el('path',{d:area,'class':'tc-area'}));
    svg.appendChild(el('path',{d:line.trim(),'class':'tc-line'}));
    if(n<=60) d.forEach(function(p,i){svg.appendChild(el('circle',{cx:xat(i,n),cy:yat(p.v),r:2.5,'class':'tc-dot'}));});
    var maxT=Math.min(n,7), seen={};
    for(var k=0;k<maxT;k++){seen[maxT<=1?0:Math.round(k*(n-1)/(maxT-1))]=1;}
    Object.keys(seen).forEach(function(si){
      var i=+si;
      var t=el('text',{x:xat(i,n),y:H-m.b+18,'class':'tc-axis','text-anchor':'middle'});
      t.textContent=d[i].label; svg.appendChild(t);
    });
    cursor=el('line',{x1:0,y1:m.t,x2:0,y2:m.t+ih,'class':'tc-cursor',visibility:'hidden'});
    svg.appendChild(cursor);
  }
  function onMove(ev){
    var d=S[period]||[], n=d.length; if(!n)return;
    var r=svg.getBoundingClientRect(), fx=(ev.clientX-r.left)/r.width*W;
    var i=Math.round((fx-m.l)/(iw||1)*(n-1)); i=Math.max(0,Math.min(n-1,i));
    var pt=pts[i]; if(!pt||!cursor)return;
    cursor.setAttribute('x1',pt.x);cursor.setAttribute('x2',pt.x);cursor.setAttribute('visibility','visible');
    tip.hidden=false;
    tip.innerHTML='<b>'+pt.p.v.toLocaleString()+'</b> '+unit+'<span>'+pt.p.label+'</span>';
    /* pin tooltip: above point when in lower half, below when in upper half */
    var pr=root.querySelector('.tc-plot').getBoundingClientRect();
    var ptAbsY=pt.y/H*r.height;
    var midChart=r.height/2;
    var px=pt.x/W*r.width;
    tip.style.left=Math.min(pr.width-tip.offsetWidth-4,Math.max(0,px-tip.offsetWidth/2))+'px';
    if(ptAbsY>midChart){
      tip.style.top=Math.max(0,ptAbsY-tip.offsetHeight-10)+'px';
    } else {
      tip.style.top=(ptAbsY+14)+'px';
    }
  }
  function onLeave(){tip.hidden=true;if(cursor)cursor.setAttribute('visibility','hidden');}
  btns.forEach(function(b){b.addEventListener('click',function(){period=b.dataset.p;sync();draw();});});
  function sync(){btns.forEach(function(b){b.classList.toggle('on',b.dataset.p===period);});}
  svg.addEventListener('mousemove',onMove); svg.addEventListener('mouseleave',onLeave);
  sync(); draw();
};
"""


def _by_tool_stats(
    calls: List[Tuple[datetime.datetime, str, str, bool]],
) -> List[Dict[str, Any]]:
    """Per tool-kind {tool, calls, fail}, busiest first."""
    agg: Dict[str, Dict[str, int]] = {}
    for _dt, _task, tool, ok in calls:
        s = agg.setdefault(tool, {"calls": 0, "fail": 0})
        s["calls"] += 1
        if not ok:
            s["fail"] += 1
    return sorted(
        ({"tool": t, "calls": v["calls"], "fail": v["fail"]} for t, v in agg.items()),
        key=lambda r: -r["calls"],
    )


def _tool_breakdown_svg(rows: List[Dict[str, Any]], gid: str = "okfill") -> str:
    """Horizontal bars per tool-kind: bar length = calls, red sub-segment =
    failures, with the call count and failure rate labelled. `gid` must be
    unique per SVG on the page — several of these coexist (one per period) and a
    shared gradient id would resolve to the first (possibly hidden) definition,
    leaving the other charts' bars unfilled."""
    if not rows:
        return '<p class="empty">No tool calls in this period.</p>'
    peak = max(r["calls"] for r in rows)

    view_w = 760
    row_h = 30
    pad = 12
    top = 22  # legend row
    gutter = 200
    bar_x = gutter + 12
    val_x = view_w - 96  # aligned value column on the right
    bar_max = val_x - bar_x - 10
    height = pad * 2 + top + row_h * len(rows)

    parts = [
        f'<svg class="bchart" viewBox="0 0 {view_w} {height}" '
        f'preserveAspectRatio="xMinYMin meet" role="img" '
        f'aria-label="Calls and failure rate by tool">',
        f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">'
        '<stop offset="0" stop-color="#2f6de0"/>'
        '<stop offset="1" stop-color="#5a3fd4"/></linearGradient></defs>',
        f'<text class="c-legend" x="{bar_x}" y="12">calls</text>'
        f'<text class="c-legend" x="{val_x}" y="12">calls · fail%</text>',
    ]
    for i, r in enumerate(rows):
        calls_n, fail = r["calls"], r["fail"]
        rate = 100 * fail / calls_n
        y = pad + top + i * row_h + 6
        cy = pad + top + i * row_h + row_h / 2
        h = row_h - 12
        w = max(2.0, bar_max * calls_n / peak)
        wf = bar_max * fail / peak
        rate_cls = "c-fail" if fail else "c-okrate"
        parts.append(
            f'<text class="c-lbl" x="{gutter}" y="{cy:.0f}" text-anchor="end" '
            f'dominant-baseline="central">{escape(r["tool"])}</text>'
            f'<rect class="c-track" x="{bar_x}" y="{y}" width="{bar_max}" '
            f'height="{h}" rx="4"/>'
            f'<rect x="{bar_x}" y="{y}" width="{w:.1f}" height="{h}" rx="4" '
            f'fill="url(#{gid})"/>'
            + (
                f'<rect class="c-failbar" x="{bar_x}" y="{y}" width="{wf:.1f}" '
                f'height="{h}" rx="4"/>'
                if fail
                else ""
            )
            + f'<text class="c-val" x="{val_x}" y="{cy:.0f}" '
            f'dominant-baseline="central">{_fmt_int(calls_n)}</text>'
            f'<text class="{rate_cls}" x="{view_w - 8}" y="{cy:.0f}" '
            f'text-anchor="end" dominant-baseline="central">{rate:.0f}%</text>'
        )
    parts.append("</svg>")
    return "".join(parts)


# Trailing windows for the By-tool chart's Day/Week/Month/Year toggle
# (labels shared with the time-series toggle, see _PERIOD_LABELS).
_BT_WINDOWS = [("day", 1), ("week", 7), ("month", 30), ("year", 365)]


def _tool_breakdown_component(
    calls: List[Tuple[datetime.datetime, str, str, bool]], now: datetime.datetime
) -> str:
    """Per-tool calls & failure-rate bars with a Day/Week/Month/Year toggle.
    Each period is a trailing window ending at `now` (Day = last 24h, …). All
    four views are rendered and toggled client-side."""
    per_rows = {}
    for name, days in _BT_WINDOWS:
        cutoff = now - datetime.timedelta(days=days)
        per_rows[name] = _by_tool_stats([c for c in calls if c[0] >= cutoff])
    if not any(per_rows.values()):
        return (
            '<div class="panel"><p class="empty">No tool calls recorded yet.</p></div>'
        )
    # Prefer the week view (matches Activity); widen only if it has no data.
    default = next((n for n in ("week", "month", "year", "day") if per_rows[n]), "week")

    tabs = "".join(
        f'<button class="bt-btn" data-p="{n}">{_PERIOD_LABELS[n]}</button>'
        for n, _ in _BT_WINDOWS
    )
    views = []
    for name, _days in _BT_WINDOWS:
        rows = per_rows[name]
        total = sum(r["calls"] for r in rows)
        cap = f"{total:,} calls · last {_PERIOD_LABELS[name]}" if rows else ""
        hidden = "" if name == default else " hidden"
        views.append(
            f'<div class="bt-view" data-p="{name}"{hidden}>'
            f'<div class="bt-cap">{escape(cap)}</div>'
            f'{_tool_breakdown_svg(rows, gid=f"okfill-{name}")}</div>'
        )
    return (
        '<div class="panel bt" id="bt-tools">'
        f'<div class="tc-head"><div class="tc-tabs">{tabs}</div></div>'
        f'{"".join(views)}'
        '<script>window.__toggleGroup(document.getElementById("bt-tools"),'
        f'".bt-btn",".bt-view","p","{default}")</script>'
        "</div>"
    )


# Button/view group toggler shared by the By-tool tabs (root=panel, attr='p')
# and the This-week/Total scope switch (root=document, attr='s'): clicking a
# button flips its `.on` class and shows the view whose data-<attr> matches.
_TOGGLE_JS = r"""
window.__toggleGroup=function(root,btnSel,viewSel,attr,def){
  var btns=root.querySelectorAll(btnSel), views=root.querySelectorAll(viewSel), cur=def;
  function sync(){
    btns.forEach(function(b){b.classList.toggle('on',b.dataset[attr]===cur);});
    views.forEach(function(v){v.hidden=(v.dataset[attr]!==cur);});
  }
  btns.forEach(function(b){b.addEventListener('click',function(){cur=b.dataset[attr];sync();});});
  sync();
};
"""


def _patch_times(runs: List[Dict[str, Any]]) -> List[datetime.datetime]:
    out = []
    for r in runs:
        ts = r.get("timestamp")
        if not ts:
            continue
        try:
            out.append(datetime.datetime.fromisoformat(ts))
        except (ValueError, TypeError):
            continue
    return out


def render(now: datetime.datetime) -> str:
    runs = load_runs()
    calls = load_tool_calls()
    total, weekly = aggregate_runs(runs)
    this_week = weekly.get(_week_key(now), _blank_stats())
    prev_week_dt = now - datetime.timedelta(weeks=1)
    prev_week = weekly.get(_week_key(prev_week_dt), _blank_stats())
    call_times = [dt for dt, *_ in calls]

    scope_toggle = (
        '<div class="tc-tabs">'
        '<button class="sc-btn" data-s="week">This week</button>'
        '<button class="sc-btn" data-s="total">Total</button>'
        "</div>"
    )
    body = [
        "<header><h1>PatchWise observability</h1>"
        f'<span class="sub">AiCodeReview · '
        f'generated {escape(now.strftime("%Y-%m-%d %H:%M:%S"))}</span></header>',
        f"<h2>{scope_toggle}</h2>",
        f'<div class="sc-view" data-s="week">{_avg_cards(this_week, "this week", prev=prev_week)}</div>',
        f'<div class="sc-view" data-s="total">{_avg_cards(total, "yet")}</div>',
        "<h2>Patches reviewed</h2>",
        _timeseries_panel("ts-patches", _bucketed(_patch_times(runs), now), "patches"),
        "<h2>Activity</h2>",
        _timeseries_panel("ts-activity", _bucketed(call_times, now), "Tool calls"),
        "<h2>By tool · calls &amp; failure rate</h2>",
        _tool_breakdown_component(calls, now),
        f"<footer>patchwise {escape(__version__)}</footer>",
    ]
    return (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>PatchWise observability</title>"
        f"<style>{_STYLE}</style><script>{_CHART_JS}{_TOGGLE_JS}</script></head><body>"
        f'<div class="wrap">{"".join(body)}</div>'
        '<script>window.__toggleGroup(document,".sc-btn",".sc-view","s","week")</script>'
        "</body></html>"
    )


# ── server / CLI ───────────────────────────────────────────────────────────────


def stats_payload(now: datetime.datetime) -> Dict[str, Any]:
    """The full aggregation as a JSON-serializable dict (drives /api/stats)."""
    runs = load_runs()
    calls = load_tool_calls()
    total, weekly = aggregate_runs(runs)
    tool_total, _ = aggregate_tools(calls)
    return {
        "runs": len(runs),
        "total": total,
        "this_week": weekly.get(_week_key(now), _blank_stats()),
        "weekly": weekly,
        "patches_timeseries": _bucketed(_patch_times(runs), now),
        "tools": {
            "total": tool_total,
            "timeseries": _bucketed([dt for dt, *_ in calls], now),
            "by_tool": _by_tool_stats(calls),
        },
    }


def build_app() -> Any:
    """Construct the FastAPI app. Imports FastAPI lazily (see module docstring)."""
    from fastapi import FastAPI
    from fastapi.responses import HTMLResponse

    app = FastAPI(title="PatchWise observability", docs_url=None, redoc_url=None)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return render(datetime.datetime.now())

    @app.get("/api/stats")
    def api_stats() -> Dict[str, Any]:
        return stats_payload(datetime.datetime.now())

    return app


def add_dashboard_arguments(group: Any) -> None:
    group.add_argument(
        "--server",
        default="0.0.0.0",
        help=(
            "Host/interface to bind the dashboard to. Use the IPv4 literal "
            "127.0.0.1 (not 'localhost', which may resolve to IPv6 ::1 and break "
            "SSH port-forwarding). Use 0.0.0.0 to bind all interfaces. "
            "(default: %(default)s)"
        ),
    )
    group.add_argument(
        "--port",
        type=int,
        default=8001,
        help="Port to serve the dashboard on. (default: %(default)s)",
    )


def run_dashboard_mode(args: Any) -> None:
    import uvicorn

    url = f"http://{args.server}:{args.port}"
    logger.info("Serving PatchWise observability dashboard at %s (Ctrl-C to stop)", url)
    print(f"PatchWise dashboard: {url}  (JSON at {url}/api/stats)")
    # info level so the "Uvicorn running on ..." bind line and per-request access
    # logs are visible — the fastest way to tell whether an SSH tunnel is actually
    # delivering requests to the bound address.
    uvicorn.run(build_app(), host=args.server, port=args.port, log_level="info")
