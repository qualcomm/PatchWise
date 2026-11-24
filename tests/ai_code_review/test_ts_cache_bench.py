# Copyright (c) Qualcomm Technologies, Inc. and/or its subsidiaries.
# SPDX-License-Identifier: BSD-3-Clause
"""Benchmark: does the Redis ts-cache save time over re-parsing with tree-sitter?

Uses the full AiCodeReview pipeline on the pinned kernel (the `review` fixture
from test_tools.py) and runs TsIndex.lookup() over a fixed symbol workload in
three modes per rep:
  nocache  - cache stubbed out, every blob parsed
  cold     - real Redis, workload's keys deleted first (each blob parsed once + mset)
  warm     - real Redis, all hits
Keys live in a private namespace (bench-<pid>), so concurrent reviews sharing the
Redis cannot write them. Step 1 records every blob SHA the workload touches and
deletes those keys; they are deleted again before each rep so every cold run
starts empty. Teardown deletes the whole namespace.

Opt-in (slow, needs docker):
    PATCHWISE_TS_BENCH=1 pytest tests/ai_code_review/test_ts_cache_bench.py -s
    PATCHWISE_TS_BENCH_REPS=3 ...   # default 5
"""

import json
import os
import statistics
import time

import pytest

from test_tools import review  # noqa: F401  (session fixture: pinned kernel + docker)

from patchwise.patch_review.ai_review import ts_cache
from patchwise.patch_review.ai_review import ts_indexer
from patchwise.patch_review.ai_review.ts_indexer import TsIndex

pytestmark = pytest.mark.skipif(
    os.environ.get("PATCHWISE_TS_BENCH") != "1", reason="set PATCHWISE_TS_BENCH=1"
)

# Fixed order. What review models actually ask for: driver-level functions, ops
# structs and local macros (1-~200 candidate files), with names re-queried later.
SYMBOLS = [
    "dwc3_qcom_probe",
    "dwc3_core_init",
    "dwc3_pm_suspend",
    "DEFINE_RCG_DFS",
    "clk_rcg2_ops",
    "clk_regmap_mux_closest_ops",
    "of_clk_add_hw_provider",
    "geni_se_init",
    "geni_i2c_xfer",
    "spi_geni_probe",
    "ufs_qcom_init",
    "ufshcd_link_recovery",
    "qcom_scm_call",
    "rpmh_write_batch",
    "icc_provider_register",
    "qcom_smem_get",
    "qcom_glink_send",
    "msm_pinctrl_probe",
    "pinctrl_dev",
    "gpiochip_add_data_with_key",
    "devm_regulator_get_optional",
    "dev_pm_opp_set_rate",
    "regmap_update_bits_base",
    "do_sys_openat2",
    # perf: kernel/events/core.c (~15k lines) plus perf headers / arm PMU driver
    "perf_install_in_context",
    "perf_event_alloc",
    "ctx_sched_out",
    "perf_event_sched_in",
    "perf_event_context",
    "perf_output_begin",
    "perf_pmu_register",
    "perf_event_attr",
    "arm_pmu",
    "armv8pmu_handle_irq",
    # re-queries
    "dwc3_core_init",
    "clk_rcg2_ops",
    "geni_se_init",
    "msm_pinctrl_probe",
    "perf_event_alloc",
    "ctx_sched_out",
]
PHASES = ("rg", "hash", "mget", "read", "parse", "mset")
MODES = ("nocache", "cold", "warm")


class NullCache:
    """Cache stub: every mget misses; records the SHAs it was asked for."""

    def __init__(self):
        self.seen = set()

    def mget(self, shas):
        self.seen.update(shas)
        return dict.fromkeys(shas)

    def mset(self, _):
        pass


class Meter:
    """Accumulates wall time and call counts of wrapped callables, per run.

    Keeps timing out of ts_indexer: the benchmark wraps the calls it measures.
    """

    def __init__(self):
        self.t = {}

    def timed(self, fn, key, when=lambda *a, **kw: True):
        def wrapper(*a, **kw):
            if not when(*a, **kw):
                return fn(*a, **kw)
            t0 = time.perf_counter()
            try:
                return fn(*a, **kw)
            finally:
                self.t[key] = self.t.get(key, 0.0) + time.perf_counter() - t0
                self.t[key + "#"] = self.t.get(key + "#", 0) + 1

        return wrapper


def _noop_exec_cost(dm, n=40):
    """Median wall time of a do-nothing exec: the fixed per-exec round-trip cost."""
    xs = []
    for _ in range(n):
        t0 = time.perf_counter()
        dm.exec_command(["true"])
        xs.append(time.perf_counter() - t0)
    return statistics.median(xs)


def _run(index, meter):
    meter.t.clear()
    t0 = time.perf_counter()
    # rg output order is nondeterministic and lookup() is unranked: compare as sets.
    out = [
        sorted(json.dumps(d, sort_keys=True) for d in index.lookup(s)) for s in SYMBOLS
    ]
    total = time.perf_counter() - t0
    return (
        total,
        dict(meter.t),
        index.parsed,
        index.cached,
        out,
    )


def _clear(cache, shas):
    keys = [ts_cache.key(s) for s in shas]
    for i in range(0, len(keys), 1000):
        cache._client.delete(*keys[i : i + 1000])
    assert not any(
        cache._client.exists(*keys[i : i + 1000]) for i in range(0, len(keys), 1000)
    )


@pytest.fixture
def bench_namespace(review, monkeypatch):  # noqa: F811
    """Private Redis key namespace, deleted in teardown even if the test fails.

    The shared Redis also serves other reviews, which can write keys for
    identical blobs (unchanged headers) mid-run.
    """
    monkeypatch.setattr(ts_cache, "SCHEMA_VERSION", f"bench-{os.getpid()}")
    yield
    client = review.agent._ts_index._cache._client
    keys = list(client.scan_iter(ts_cache.key("*"), count=1000))
    for i in range(0, len(keys), 1000):
        client.delete(*keys[i : i + 1000])


def test_ts_cache_saves_time(review, bench_namespace, monkeypatch):  # noqa: F811
    base = review.agent._ts_index
    dm, blocklist, real = base._dm, base._blocklist, base._cache
    meter = Meter()

    def new(cache):
        index = TsIndex(docker_manager=dm, cache=cache, blocklist=blocklist)
        index._hash_files = meter.timed(index._hash_files, "hash")
        index._read_files = meter.timed(index._read_files, "read")
        return index

    # Session-scoped dm/cache: patch through monkeypatch so they are restored.
    for obj, attr, key, *when in (
        (dm, "_exec", "exec"),
        (dm, "exec_command", "rg", lambda cmd, *a, **kw: cmd[0] == "sh"),
        (real, "mget", "mget"),
        (real, "mset", "mset"),
        (ts_indexer, "parse_constructs", "parse"),
    ):
        monkeypatch.setattr(obj, attr, meter.timed(getattr(obj, attr), key, *when))
    reps = int(os.environ.get("PATCHWISE_TS_BENCH_REPS", "5"))

    noop = _noop_exec_cost(dm)
    # Step 1: discover every blob the workload touches, clear them from Redis.
    rec = NullCache()
    _, _, _, _, expected = _run(new(rec), meter)  # also primes page cache / rg
    shas = rec.seen
    _clear(real, shas)
    print(
        f"\nworkload: {len(SYMBOLS)} lookups, {len(shas)} distinct blobs; cleared from Redis"
    )

    res = {m: [] for m in MODES}
    for rep in range(reps):
        _clear(real, shas)
        for m in MODES:
            res[m].append(_run(new(NullCache() if m == "nocache" else real), meter))
        nc, cold, warm = (res[m][-1] for m in MODES)
        assert cold[2] == len(shas), "cold run did not parse every blob -- clear failed"
        assert warm[2] == 0, "warm run parsed -- unexpected cache miss"
        assert (
            cold[4] == warm[4] == nc[4] == expected
        ), "cached results differ from fresh parse"
        print(
            f"rep {rep + 1}/{reps}: "
            + "  ".join(f"{m}={res[m][-1][0]:.2f}s" for m in MODES)
        )

    print(
        f"\n{'mode':8} {'min':>7} {'median':>7} {'max':>7} {'stdev':>6}   median per phase (s)"
    )
    med = {}
    for m, rows in res.items():
        xs = [r[0] for r in rows]
        med[m] = statistics.median(xs)
        ph = " ".join(
            f"{k}={statistics.median(r[1].get(k, 0.0) for r in rows):.2f}"
            for k in PHASES
        )
        n = statistics.median(r[1].get("exec#", 0) for r in rows)
        exec_s = statistics.median(r[1].get("exec", 0.0) for r in rows)
        ph += f" | execs={n:.0f} exec_s={exec_s:.2f} overhead~{n * noop:.2f}"
        print(
            f"{m:8} {min(xs):7.2f} {med[m]:7.2f} {max(xs):7.2f} {statistics.pstdev(xs):6.2f}   {ph}"
            f" | parsed={rows[0][2]} cached={rows[0][3]}"
        )
    print(f"no-op docker exec: {noop * 1000:.1f} ms")
    saved = med["nocache"] - med["warm"]
    print(
        f"\nwarm vs nocache: {saved:+.2f}s ({saved / med['nocache']:.0%} saved); "
        f"cold overhead vs nocache: {med['cold'] - med['nocache']:+.2f}s; "
        f"Redis used_memory: {real.memory_bytes() / 2**20:.1f} MiB"
    )
    assert med["warm"] < med["nocache"], "warm cache is not faster than re-parsing"
