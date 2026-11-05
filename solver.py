"""基于 SciPy 重构的仓库排班求解器（云端极致稳定版）。"""
from __future__ import annotations
import numpy as np
from scipy.optimize import milp, linprog, LinearConstraint, Bounds

PERIODS = ("上午", "下午")
CAPACITY = 4
INITIAL_STOCK = 0


def run_model(inbound=32, outbound=31, costs=None):
    if costs is None:
        costs = [1, 2, 2, 3]
    costs = list(costs)
    n_shelves = len(costs)
    T = len(PERIODS)

    if inbound < 0 or outbound < 0:
        return {"status": "Infeasible", "error_reason": "入库量和出库量不能为负数。", "total_cost": None, "schedule": [], "shadow_prices": {}}

    # 1. 物理极限预检
    max_in_capacity = n_shelves * T * CAPACITY
    max_out_capacity = n_shelves * T * CAPACITY

    if inbound > max_in_capacity:
        return {
            "status": "Infeasible",
            "error_reason": f"入库需求({inbound}批)超过了最大入库物理容量({max_in_capacity}批)。当前只有 {n_shelves} 个货架，每个货架每天最多进 {CAPACITY * T} 批货。",
            "total_cost": None, "schedule": [], "shadow_prices": {},
            "max_in_capacity": max_in_capacity, "max_out_capacity": max_out_capacity
        }
    if outbound > max_out_capacity:
        return {
            "status": "Infeasible",
            "error_reason": f"出库需求({outbound}批)超过了最大出库物理容量({max_out_capacity}批)。",
            "total_cost": None, "schedule": [], "shadow_prices": {},
            "max_in_capacity": max_in_capacity, "max_out_capacity": max_out_capacity
        }

    n_vars = 3 * n_shelves * T
    
    def idx(kind, i, t):
        # kind: 0=入库, 1=出库, 2=期末库存
        return (kind * n_shelves + i) * T + t

    # 2. 构建目标函数系数（最小化成本）
    c = np.zeros(n_vars)
    for i in range(n_shelves):
        for t in range(T):
            c[idx(0, i, t)] = costs[i]
            c[idx(1, i, t)] = costs[i]
            c[idx(2, i, t)] = 0.0  # 期末库存不产生直接成本

    # 3. 变量边界（0 到 4）
    lb = np.zeros(n_vars)
    ub = np.full(n_vars, float(CAPACITY))
    bounds = Bounds(lb, ub)

    # 4. 整数约束（入库和出库必须是整数，库存允许连续小数）
    integrality = np.zeros(n_vars)
    integrality[0 : 2 * n_shelves * T] = 1

    # 5. 等式约束（平衡等式）
    A_eq = []
    b_eq = []

    # 5.1 总入库 = inbound
    row = np.zeros(n_vars)
    for i in range(n_shelves):
        for t in range(T):
            row[idx(0, i, t)] = 1
    A_eq.append(row)
    b_eq.append(inbound)

    # 5.2 总出库 = outbound
    row = np.zeros(n_vars)
    for i in range(n_shelves):
        for t in range(T):
            row[idx(1, i, t)] = 1
    A_eq.append(row)
    b_eq.append(outbound)

    # 5.3 库存平衡
    for i in range(n_shelves):
        # 上午：期末库存 = 初始库存 + 入库 - 出库
        row = np.zeros(n_vars)
        row[idx(2, i, 0)] = 1
        row[idx(0, i, 0)] = -1
        row[idx(1, i, 0)] = 1
        A_eq.append(row)
        b_eq.append(float(INITIAL_STOCK))

        # 下午：期末库存 = 上午库存 + 入库 - 出库
        row = np.zeros(n_vars)
        row[idx(2, i, 1)] = 1
        row[idx(2, i, 0)] = -1
        row[idx(0, i, 1)] = -1
        row[idx(1, i, 1)] = 1
        A_eq.append(row)
        b_eq.append(0.0)

    A_eq = np.array(A_eq)
    b_eq = np.array(b_eq)

    # 6. 求解整数规划 (MIP)
    try:
        res = milp(c, constraints=LinearConstraint(A_eq, b_eq, b_eq), integrality=integrality, bounds=bounds)
    except Exception as e:
        return {"status": "Error", "error_reason": f"底层 SciPy 求解器崩溃: {str(e)}", "total_cost": None, "schedule": [], "shadow_prices": {}}

    if not res.success:
        return {
            "status": "Infeasible",
            "error_reason": f"排班死锁：由于库存平衡限制，无法找到合理的排班方案（{res.message}）。",
            "total_cost": None, "schedule": [], "shadow_prices": {}
        }

    # 7. 求解线性松弛（仅为了计算影子价格 / 敏感性分析）
    shadow_prices = {}
    try:
        res_lp = linprog(c, A_eq=A_eq, b_eq=b_eq, bounds=list(zip(lb, ub)), method='highs')
        if res_lp.success:
            shadow_prices = {
                "total_inbound": round(res_lp.eqlin.marginals[0], 6),
                "total_outbound": round(res_lp.eqlin.marginals[1], 6)
            }
    except Exception as e:
        print(f"⚠️ 影子价格计算异常: {e}")

    # 8. 整理排班结果
    schedule = []
    x = res.x
    for i in range(n_shelves):
        for t in range(T):
            schedule.append({
                "shelf": i + 1, "period": PERIODS[t],
                "in_flow": int(round(x[idx(0, i, t)])),
                "out_flow": int(round(x[idx(1, i, t)])),
                "stock": round(x[idx(2, i, t)], 6),
                "unit_cost": costs[i],
            })

    return {
        "status": "Optimal",
        "error_reason": "",
        "total_cost": round(res.fun, 6),
        "schedule": schedule,
        "shadow_prices": shadow_prices,
        # 👇 核心：无论是否有解，都把物理上限告诉 AI
        "max_in_capacity": max_in_capacity,
        "max_out_capacity": max_out_capacity
    }