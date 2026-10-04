"""Integration test on the supplied data: the legacy pipeline is reproduced exactly."""
import legacy as LG


def test_legacy_benchmarks_reproduced():
    tables = {q: LG.legacy_table(q) for q in (0.99, 0.95)}
    res = LG.check(tables)
    assert res["all_benchmarks_reproduced"], res
