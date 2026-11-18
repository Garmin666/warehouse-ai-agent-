"""基于 SciPy 重构的仓库排班求解器（4时段、百货架、算人力版）。"""
from __future__ import annotations
import numpy as np
from scipy.optimize import milp, linprog, LinearConstraint, Bounds

PERIODS = ("8:00-10:00", "10:00-12:00", "14:00-16:00", "16:00-18:00")
T = len(PERIODS)
CAPACITY = 4
INITIAL_STOCK = 0
ORDERS_PER_WORKER = 160  # 每人每天处理单量

def run_model(inbound=1150, outbound=1100, costs=None):
    if costs is None:
        costs = [i + 1 for i in range(100)]  # 默认 100 个货架
    costs = list(costs)
    n_shelves = len(costs)

    max_in_capacity = n_shelves * T * CAPACITY
    max_out_capacity = n_shelves * T * CAPACITY

    if inbound > max_in_capacity or outbound > max_out_capacity:
        return {
            "status": "Infeasible",
            "error_reason": f"物理容量不足！当前 {n_shelves} 个货架，4个时段，最大容量为 {max_in_capacity} 批，无法满足入库 {inbound} 批。",
            "total_cost": None, "schedule": [], "shadow_prices": {},
            "max_in_capacity": max_in_capacity, "max_out_capacity": max_out_capacity
        }

    n_vars = 3 * n_shelves * T
    
    def idx(kind, i, t):
        return (kind * n_shelves + i) * T + t

    # 目标函数：最小化搬运成本
    c = np.zeros(n_vars)
    for i in range(n_shelves):
        for t in range(T):
            c[idx(0, i, t)] = costs[i]
            c[idx(1, i, t)] = costs[i]

    lb = np.zeros(n_vars)
    ub = np.full(n_vars, float(CAPACITY))
    bounds = Bounds(lb, ub)
    integrality = np.zeros(n_vars)
    integrality[0 : 2 * n_shelves * T] = 1

    A_eq, b_eq = [], []

    # 1. 总入库
    row = np.zeros(n_vars)
    for i in range(n_shelves):
        for t in range(T): row[idx(0, i, t)] = 1
    A_eq.append(row); b_eq.append(inbound)

    # 2. 总出库
    row = np.zeros(n_vars)
    for i in range(n_shelves):
        for t in range(T): row[idx(1, i, t)] = 1
    A_eq.append(row); b_eq.append(outbound)

    # 3. 库存平衡 (4 个时段)
    for i in range(n_shelves):
        for t in range(T):
            row = np.zeros(n_vars)
            row[idx(2, i, t)] = 1
            row[idx(0, i, t)] = -1
            row[idx(1, i, t)] = 1
            if t > 0:
                row[idx(2, i, t-1)] = -1
            A_eq.append(row); b_eq.append(0.0 if t > 0 else float(INITIAL_STOCK))

    try:
        res = milp(c, constraints=LinearConstraint(np.array(A_eq), b_eq, b_eq), integrality=integrality, bounds=bounds)
    except Exception as e:
        return {"status": "Error", "error_reason": str(e), "max_in_capacity": max_in_capacity, "max_out_capacity": max_out_capacity}

    if not res.success:
        return {
            "status": "Infeasible", "error_reason": "排班死锁，无法找到平衡方案",
            "total_cost": None, "shadow_prices": {}, "max_in_capacity": max_in_capacity, "max_out_capacity": max_out_capacity
        }

    # 影子价格（敏感性分析）
    shadow_prices = {}
    try:
        res_lp = linprog(c, A_eq=np.array(A_eq), b_eq=b_eq, bounds=list(zip(lb, ub)), method='highs')
        if res_lp.success:
            shadow_prices = {
                "total_inbound": round(res_lp.eqlin.marginals[0], 6),
                "total_outbound": round(res_lp.eqlin.marginals[1], 6)
            }
    except Exception:
        pass

    # 模拟排班结果
    schedule = []
    x = res.x
    for i in range(n_shelves):
        for t in range(T):
            schedule.append({
                "shelf": i + 1, "period": PERIODS[t],
                "in_flow": int(round(x[idx(0, i, t)])),
                "out_flow": int(round(x[idx(1, i, t)])),
                "stock": round(x[idx(2, i, t)], 2)
            })

    # ==========================================
    # 计算人力成本 (复刻你的 Excel)
    # ==========================================
    total_flow = inbound + outbound
    # 理论需要人数
    theoretical_workers = total_flow / ORDERS_PER_WORKER
    # 实际需要人数 (向上取整)
    actual_workers = int(np.ceil(theoretical_workers))
    # 假设你有 20 个工人
    available_workers = 20
    labor_utilization = total_flow / (available_workers * ORDERS_PER_WORKER)
    surplus_workers = available_workers - actual_workers

    return {
        "status": "Optimal",
        "total_cost": round(res.fun, 2),
        "shadow_prices": shadow_prices,
        "max_in_capacity": max_in_capacity,
        "max_out_capacity": max_out_capacity,
        "labor_metrics": {
            "total_flow": total_flow,
            "theoretical_workers": round(theoretical_workers, 2),
            "actual_workers_needed": actual_workers,
            "labor_utilization": f"{labor_utilization * 100:.1f}%",
            "surplus_workers": surplus_workers
        }
    }