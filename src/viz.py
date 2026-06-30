"""可视化（T6）：纯函数，输入数据 -> 300dpi PNG bytes（或 None）。

韦恩图(venn_png)、富集气泡图(bubble_png)、PPI 网络图(network_png)。
matplotlib Agg 后端（无显示器可跑、离线可测）；纯展示层，不引入任何口径/阈值。
标签均为英文/基因符号，避免中文字体缺失。
"""
from __future__ import annotations

import io
import math
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402


def _fig_to_png(fig) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=300, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def venn_png(intersection: dict) -> Optional[bytes]:
    """药物×疾病 韦恩图。三区全空时返回 None。"""
    if not intersection:
        return None
    c = intersection.get("counts", {})
    n_drug_only = len(intersection.get("drug_only", []))
    n_dis_only = len(intersection.get("disease_only", []))
    n_inter = len(intersection.get("intersection", []))
    # 退化情形: 无疾病侧(疾病未命中)或全空 -> 不画无意义单圈, 返回 None
    if (n_dis_only + n_inter) == 0 or (n_drug_only + n_dis_only + n_inter) == 0:
        return None
    try:
        from matplotlib_venn import venn2
        fig, ax = plt.subplots(figsize=(5, 4))
        venn2(subsets=(n_drug_only, n_dis_only, n_inter),
              set_labels=("Drug targets", "Disease targets"), ax=ax)
        ax.set_title("Drug–Disease target overlap")
        return _fig_to_png(fig)
    except Exception:
        # 退化：两圆示意 + 计数文本（不依赖 matplotlib_venn）
        fig, ax = plt.subplots(figsize=(5, 4))
        ax.add_patch(plt.Circle((0.38, 0.5), 0.30, color="#4C72B0", alpha=0.45))
        ax.add_patch(plt.Circle((0.62, 0.5), 0.30, color="#DD8452", alpha=0.45))
        ax.text(0.27, 0.5, str(n_drug_only), ha="center", va="center")
        ax.text(0.73, 0.5, str(n_dis_only), ha="center", va="center")
        ax.text(0.50, 0.5, str(n_inter), ha="center", va="center", fontweight="bold")
        ax.text(0.27, 0.85, "Drug", ha="center"); ax.text(0.73, 0.85, "Disease", ha="center")
        ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")
        ax.set_title("Drug–Disease target overlap")
        return _fig_to_png(fig)


def bubble_png(rows, title: str = "") -> Optional[bytes]:
    """富集气泡图：y=term, x=-log10(adj_p), 点大小=n_overlap, 颜色=combined_score。空则 None。"""
    rows = [r for r in (rows or []) if r.get("term")]
    if not rows:
        return None
    rows = rows[:15][::-1]  # 取前 15, 反转使最显著在顶部
    terms = [str(r["term"])[:42] for r in rows]

    def _neglog(p):
        try:
            return -math.log10(p) if p and p > 0 else 0.0
        except (ValueError, TypeError):
            return 0.0
    x = [_neglog(r.get("adj_p_value")) for r in rows]
    sizes = [max(20, (r.get("n_overlap") or 1) * 40) for r in rows]
    colors = [r.get("combined_score") or 0 for r in rows]

    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.42 * len(rows))))
    sc = ax.scatter(x, range(len(rows)), s=sizes, c=colors, cmap="viridis",
                    edgecolors="gray", linewidths=0.5)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels(terms, fontsize=8)
    ax.set_xlabel("-log10(adjusted P)")
    ax.set_title(f"Enrichment: {title}" if title else "Enrichment")
    fig.colorbar(sc, ax=ax, label="combined score")
    ax.margins(y=0.02)
    return _fig_to_png(fig)


def _spring_layout(nodes, edges, iterations=90):
    """轻量 Fruchterman-Reingold 布局（无 networkx 依赖）。确定性初值。

    k（理想间距）取较大常数以拉开节点，缓解 hub-and-spoke 时高度数簇挤成一团。
    """
    n = len(nodes)
    idx = {g: i for i, g in enumerate(nodes)}
    # 圆周确定性初始化（避免随机，保证可复现）
    pos = {g: [math.cos(2 * math.pi * i / n), math.sin(2 * math.pi * i / n)]
           for i, g in enumerate(nodes)}
    k = 2.2 / math.sqrt(n) if n else 1.0
    adj = [(idx[e["a"]], idx[e["b"]]) for e in edges if e["a"] in idx and e["b"] in idx]
    names = list(nodes)
    for it in range(iterations):
        disp = {g: [0.0, 0.0] for g in nodes}
        for i in range(n):
            for j in range(i + 1, n):
                gi, gj = names[i], names[j]
                dx = pos[gi][0] - pos[gj][0]
                dy = pos[gi][1] - pos[gj][1]
                dist = math.hypot(dx, dy) or 0.01
                rep = k * k / dist
                disp[gi][0] += dx / dist * rep; disp[gi][1] += dy / dist * rep
                disp[gj][0] -= dx / dist * rep; disp[gj][1] -= dy / dist * rep
        for a, b in adj:
            ga, gb = names[a], names[b]
            dx = pos[ga][0] - pos[gb][0]
            dy = pos[ga][1] - pos[gb][1]
            dist = math.hypot(dx, dy) or 0.01
            att = dist * dist / k
            disp[ga][0] -= dx / dist * att; disp[ga][1] -= dy / dist * att
            disp[gb][0] += dx / dist * att; disp[gb][1] += dy / dist * att
        t = 0.1 * (1 - it / iterations)
        for g in nodes:
            d = math.hypot(*disp[g]) or 0.01
            pos[g][0] += disp[g][0] / d * min(d, t)
            pos[g][1] += disp[g][1] / d * min(d, t)
    return pos


def network_png(nodes, edges, hubs=None, max_nodes=60) -> Optional[bytes]:
    """PPI 网络图：spring 布局，hub 节点按度数放大/着色。空边返回 None。

    可读性：节点过多(>max_nodes)时只渲染度数最高的 max_nodes 个及其内部边
    (完整网络仍在 Excel/GraphML 中)，避免标签糊成一团。
    """
    nodes = list(nodes or [])
    edges = [e for e in (edges or []) if e.get("a") and e.get("b")]
    if not edges or len(nodes) < 2:
        return None
    deg = {}
    for e in edges:
        for g in (e["a"], e["b"]):
            deg[g] = deg.get(g, 0) + 1
    nodes = [g for g in nodes if g in deg] or list(deg.keys())

    truncated = 0
    if len(nodes) > max_nodes:
        truncated = len(nodes) - max_nodes
        keep = set(sorted(nodes, key=lambda g: (-deg.get(g, 0), g))[:max_nodes])
        nodes = [g for g in nodes if g in keep]
        edges = [e for e in edges if e["a"] in keep and e["b"] in keep]
        if not edges:
            return None
    # 环形布局: 按度数排序均布圆周 -> 节点零重叠、标签置于圈外、确定性可复现。
    # 相比力导向, 对「密集核心+悬挂节点」的 PPI 更可读(不塌成一团、不被外围点压缩)。
    order = sorted(nodes, key=lambda g: (-deg.get(g, 0), g))
    n = len(order)
    pos = {}
    for i, g in enumerate(order):
        ang = 2 * math.pi * i / n - math.pi / 2     # 从顶部开始, 顺时针
        pos[g] = (math.cos(ang), math.sin(ang))

    fig, ax = plt.subplots(figsize=(7.5, 7.5))
    # 边: 浅色细线(弦), 度数越相关越淡 -> 突出节点与标签
    for e in edges:
        if e["a"] in pos and e["b"] in pos:
            ax.plot([pos[e["a"]][0], pos[e["b"]][0]],
                    [pos[e["a"]][1], pos[e["b"]][1]],
                    color="#9ecae1", linewidth=0.5, alpha=0.35, zorder=1)
    xs = [pos[g][0] for g in order]
    ys = [pos[g][1] for g in order]
    sizes = [80 + deg.get(g, 1) * 55 for g in order]
    colors = [deg.get(g, 1) for g in order]
    sc = ax.scatter(xs, ys, s=sizes, c=colors, cmap="OrRd", edgecolors="#555",
                    linewidths=0.6, zorder=2)
    fig.colorbar(sc, ax=ax, fraction=0.046, pad=0.04, label="degree (connectivity)")
    # 标签置于圈外、按角度对齐 -> 互不重叠且可读(hub 加粗)
    hub_set = {h["gene"] for h in (hubs or [])[:10]}
    for i, g in enumerate(order):
        ang = 2 * math.pi * i / n - math.pi / 2
        x, y = math.cos(ang) * 1.08, math.sin(ang) * 1.08
        ha = "left" if math.cos(ang) > 0.01 else ("right" if math.cos(ang) < -0.01 else "center")
        ax.text(x, y, g, fontsize=7, ha=ha, va="center",
                fontweight="bold" if g in hub_set else "normal", zorder=3)
    ax.set_aspect("equal")
    ax.set_xlim(-1.45, 1.45)
    ax.set_ylim(-1.4, 1.4)
    title = "PPI network · ring layout (node size/color = degree; hubs in bold)"
    if truncated:
        title += f"\n(top {len(order)} hub nodes shown; {truncated} more in Excel/GraphML)"
    ax.set_title(title, fontsize=10)
    ax.axis("off")
    return _fig_to_png(fig)
