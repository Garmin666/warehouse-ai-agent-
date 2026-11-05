"""仓库货架两时段入库/出库线性规划（基于 HiGHS 求解器强化版）。"""
from __future__ import annotations
import pulp

PERIODS = ("上午", "下午")
CAPACITY = 4
INITIAL_STOCK = 0

def run_model(inbound=32, outbound=31, costs=None):
    if costs is None:
        costs = [1, 2, 2, 3]
    costs = list(costs)
    n_shelves = len(costs)

    if inbound < 0 or outbound < 0:
        return {"status": "Infeasible", "error_reason": "入库量和出库量不能为负数。", "total_cost": None, "schedule": [], "shadow_prices": {}}

    # 提前检查物理极限
    max_in_capacity = n_shelves * len(PERIODS) * CAPACITY
    max_out_capacity = n_shelves * len(PERIODS) * CAPACITY

    if inbound > max_in_capacity:
        return {
            "status": "Infeasible",
            "error_reason": f"入库需求({inbound}批)超过了最大入库物理容量({max_in_capacity}批)。当前只有 {n_shelves} 个货架，每个货架每天最多进 {CAPACITY * len(PERIODS)} 批货。",
            "total_cost": None, "schedule": [], "shadow_prices": {}
        }
    if outbound > max_out_capacity:
        return {
            "status": "Infeasible",
            "error_reason": f"出库需求({outbound}批)超过了最大出库物理容量({max_out_capacity}批)。",
            "total_cost": None, "schedule": [], "shadow_prices": {}
        }

    # ==========================================
    # 1. 求解主模型（排班与总成本）- 整数规划
    # ==========================================
    try:
        schedule_model = _build_model(inbound, outbound, costs, integer_flows=True)
        # 💡 换用 HiGHS 求解器
        status = schedule_model["problem"].solve(pulp.HiGHS(msg=False, timeLimit=15))
    except Exception as e:
        return {"status": "Error", "error_reason": f"底层求解引擎崩溃: {str(e)}", "total_cost": None, "schedule": [], "shadow_prices": {}}

    if pulp.LpStatus[status] != "Optimal":
        return {
            "status": "Infeasible",
            "error_reason": f"由于库存平衡或时段容量限制，模型无法找到合理的排班方案。求解器状态: {pulp.LpStatus[status]}",
            "total_cost": None, "schedule": [], "shadow_prices": {}
        }

    # ==========================================
    # 2. 求解对偶模型（敏感性分析/影子价格）- 线性松弛
    # ==========================================
    shadow_prices = {}
    try:
        dual_model = _build_model(inbound, outbound, costs, integer_flows=False)
        # 💡 同样使用 HiGHS，对偶值提取极快极稳
        dual_model["problem"].solve(pulp.HiGHS(msg=False, timeLimit=15))
        shadow_prices = _read_shadow_prices(dual_model)
    except Exception as e:
        print(f"⚠️ 影子价格计算失败: {e}")
        shadow_prices = {"error": "计算影子价格失败"}

    return {
        "status": "Optimal",
        "error_reason": "",
        "total_cost": round(pulp.value(schedule_model["problem"].objective), 6),
        "schedule": _read_schedule(schedule_model),
        "shadow_prices": shadow_prices,
    }


def _build_model(inbound, outbound, costs, integer_flows):
    n_shelves = len(costs)
    flow_cat = pulp.LpInteger if integer_flows else pulp.LpContinuous
    kind = "mip" if integer_flows else "lp"
    problem = pulp.LpProblem(f"warehouse_{kind}", pulp.LpMinimize)

    in_flow = [[pulp.LpVariable(f"in_{i}_{t}", lowBound=0, cat=flow_cat) for t in range(len(PERIODS))] for i in range(n_shelves)]
    out_flow = [[pulp.LpVariable(f"out_{i}_{t}", lowBound=0, cat=flow_cat) for t in range(len(PERIODS))] for i in range(n_shelves)]
    stock = [[pulp.LpVariable(f"stock_{i}_{t}", lowBound=0, cat=pulp.LpContinuous) for t in range(len(PERIODS))] for i in range(n_shelves)]

    problem += pulp.lpSum(costs[i] * (in_flow[i][t] + out_flow[i][t]) for i in range(n_shelves) for t in range(len(PERIODS)))

    constraints = {"in_capacity": {}, "out_capacity": {}, "stock_capacity": {}, "balance": {}}

    for i in range(n_shelves):
        for t, period in enumerate(PERIODS):
            key = f"Shelf{i + 1}_{period}"
            in_name, out_name = f"in_cap_{i}_{t}", f"out_cap_{i}_{t}"
            stock_name, balance_name = f"stock_cap_{i}_{t}", f"balance_{i}_{t}"

            problem += in_flow[i][t] <= CAPACITY, in_name
            problem += out_flow[i][t] <= CAPACITY, out_name
            problem += stock[i][t] <= CAPACITY, stock_name

            if t == 0:
                problem += (stock[i][t] == INITIAL_STOCK + in_flow[i][t] - out_flow[i][t]), balance_name
            else:
                problem += (stock[i][t] == stock[i][t - 1] + in_flow[i][t] - out_flow[i][t]), balance_name

            constraints["in_capacity"][key] = problem.constraints[in_name]
            constraints["out_capacity"][key] = problem.constraints[out_name]
            constraints["stock_capacity"][key] = problem.constraints[stock_name]
            constraints["balance"][key] = problem.constraints[balance_name]

    problem += pulp.lpSum(in_flow[i][t] for i in range(n_shelves) for t in range(len(PERIODS))) == inbound, "total_inbound"
    problem += pulp.lpSum(out_flow[i][t] for i in range(n_shelves) for t in range(len(PERIODS))) == outbound, "total_outbound"
    constraints["total_inbound"] = problem.constraints["total_inbound"]
    constraints["total_outbound"] = problem.constraints["total_outbound"]

    return {"problem": problem, "in_flow": in_flow, "out_flow": out_flow, "stock": stock, "constraints": constraints, "costs": costs}


def _read_schedule(model):
    schedule = []
    for i, cost in enumerate(model["costs"]):
        for t, period in enumerate(PERIODS):
            schedule.append({
                "shelf": i + 1, "period": period,
                "in_flow": int(round(pulp.value(model["in_flow"][i][t]))),
                "out_flow": int(round(pulp.value(model["out_flow"][i][t]))),
                "stock": round(pulp.value(model["stock"][i][t]), 6),
                "unit_cost": cost,
            })
    return schedule


def _dual(constraint):
    try:
        return round(float(constraint.pi), 6) if constraint.pi is not None else 0.0
    except Exception:
        return 0.0


def _read_shadow_prices(model):
    if not model.get("constraints"): return {}
    constraints = model["constraints"]
    return {
        "in_capacity": {k: _dual(c) for k, c in constraints.get("in_capacity", {}).items()},
        "out_capacity": {k: _dual(c) for k, c in constraints.get("out_capacity", {}).items()},
        "stock_capacity": {k: _dual(c) for k, c in constraints.get("stock_capacity", {}).items()},
        "balance": {k: _dual(c) for k, c in constraints.get("balance", {}).items()},
        "total_inbound": _dual(constraints.get("total_inbound")),
        "total_outbound": _dual(constraints.get("total_outbound")),
    }