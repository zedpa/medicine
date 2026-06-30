"""T6 验收 AC-23…AC-26: 可视化纯函数(离线, Agg, 返回 PNG bytes 或 None)。"""
from src.viz import venn_png, bubble_png, network_png

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _is_png(b):
    return isinstance(b, (bytes, bytearray)) and b[:8] == PNG_MAGIC and len(b) > 100


def test_venn_png_and_empty():  # AC-23
    inter = {"intersection": ["PTGS2"], "drug_only": ["TRPA1", "RELA"],
             "disease_only": ["AGT", "ACE", "REN"],
             "counts": {"drug": 3, "disease": 4, "intersection": 1}}
    assert _is_png(venn_png(inter))
    empty = {"intersection": [], "drug_only": [], "disease_only": [],
             "counts": {"drug": 0, "disease": 0, "intersection": 0}}
    assert venn_png(empty) is None
    # 实时测试发现: 疾病未命中(疾病侧全空)时不应画无意义单圈
    degenerate = {"intersection": [], "drug_only": ["A", "B", "C"], "disease_only": [],
                  "counts": {"drug": 3, "disease": 0, "intersection": 0}}
    assert venn_png(degenerate) is None


def test_bubble_png_and_empty():  # AC-24
    rows = [{"term": "Renin-angiotensin system", "adj_p_value": 8e-9,
             "combined_score": 15419.0, "n_overlap": 4},
            {"term": "Vascular smooth muscle contraction", "adj_p_value": 6e-8,
             "combined_score": 3047.0, "n_overlap": 5}]
    assert _is_png(bubble_png(rows, "KEGG"))
    assert bubble_png([], "KEGG") is None


def test_network_png_and_empty():  # AC-25
    nodes = ["ACE", "AGT", "AGTR1", "REN"]
    edges = [{"a": "ACE", "b": "AGT", "score": 0.9},
             {"a": "ACE", "b": "AGTR1", "score": 0.7},
             {"a": "AGT", "b": "REN", "score": 0.8}]
    hubs = [{"gene": "ACE", "degree": 2}, {"gene": "AGT", "degree": 2}]
    assert _is_png(network_png(nodes, edges, hubs))
    assert _is_png(network_png(nodes, edges, None))      # hub 缺失不报错
    assert network_png([], [], []) is None


def test_network_png_caps_large_graph():  # 实时测试发现: 节点过多需截断渲染保证可读
    # 构造 100 节点环 + 一个高度数中心, 渲染应成功且不报错(完整网络仍在 Excel)
    nodes = [f"G{i}" for i in range(100)]
    edges = [{"a": f"G{i}", "b": f"G{(i + 1) % 100}", "score": 0.7} for i in range(100)]
    edges += [{"a": "G0", "b": f"G{i}", "score": 0.9} for i in range(2, 40)]  # G0 高度数
    assert _is_png(network_png(nodes, edges, None, max_nodes=30))


def test_no_side_effects_repeatable():  # AC-26
    rows = [{"term": "A", "adj_p_value": 1e-5, "combined_score": 100.0, "n_overlap": 2}]
    assert _is_png(bubble_png(rows, "T"))
    assert _is_png(bubble_png(rows, "T"))
