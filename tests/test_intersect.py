"""T1 验收 AC-1, AC-2: 交集纯函数。"""
from src.intersect import intersect_targets


def test_basic_intersection_sorted():  # AC-1
    r = intersect_targets({"A", "B", "C"}, {"B", "C", "D"})
    assert r["intersection"] == ["B", "C"]
    assert r["drug_only"] == ["A"]
    assert r["disease_only"] == ["D"]
    assert r["counts"] == {"drug": 3, "disease": 3, "intersection": 2}


def test_empty_sides_robust():  # AC-2
    r = intersect_targets(set(), {"X"})
    assert r["intersection"] == []
    assert r["disease_only"] == ["X"]
    assert r["counts"] == {"drug": 0, "disease": 1, "intersection": 0}

    r2 = intersect_targets({"Y"}, set())
    assert r2["intersection"] == []
    assert r2["drug_only"] == ["Y"]
    assert r2["counts"] == {"drug": 1, "disease": 0, "intersection": 0}
