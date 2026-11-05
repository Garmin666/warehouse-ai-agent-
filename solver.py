"""仓库货架两时段入库/出库线性规划。

排班按整数规划求解（入库、出库为非负整数）。
影子价格来自同一约束的连续松弛：混合整数模型没有对偶值，
CBC 只在纯线性规划上返回 shadow price。
"""

from __future__ import annotations

import pulp

PERIODS = ("上午", "下午")
CAPACITY = 4
INITIAL_STOCK = 0


def run_model(inbound=32, outbound=31, costs=None):
    """求解货架移动成本最小的入库/出库排班，并返回影子价格。

    参数
    ----
    inbound : 入库总需求
    outbound : 出库总需求
    costs : 各货架单位移动成本，默认 Shelf1-4 为 [1, 2, 2, 3]

    返回
    ----
    dict
        total_cost : 整数规划最优总成本
        schedule : 每个货架、每个时段的入库、出库和期末库存
        shadow_prices : 全部显式约束的影子价格（连续松弛）
        reduced_costs : 决策变量的检验数（连续松弛，对应非负下界）
    """
    if costs is None:
        costs = [1, 2, 2, 3]
    costs = list(costs)
    if len(costs) == 0:
        raise ValueError("costs 至少要包含一个货架")
    if inbound < 0 or outbound < 0:
        raise ValueError("inbound 和 outbound 必须非负")

    schedule_model = _build_model(inbound, outbound, costs, integer_flows=True)
    _solve(schedule_model["problem"])
    dual_model = _build_model(inbound, outbound, costs, integer_flows=False)
    _solve(dual_model["problem"])

    return {
        "total_cost": round(pulp.value(schedule_model["problem"].objective), 6),
        "schedule": _read_schedule(schedule_model),
        "shadow_prices": _read_shadow_prices(dual_model),
        "reduced_costs": _read_reduced_costs(dual_model),
        "status": pulp.LpStatus[schedule_model["problem"].status],
        "lp_relaxation_cost": round(pulp.value(dual_model["problem"].objective), 6),
        "shadow_price_source": "lp_relaxation",
    }


def _build_model(inbound, outbound, costs, integer_flows):
    n_shelves = len(costs)
    flow_cat = pulp.LpInteger if integer_flows else pulp.LpContinuous
    kind = "mip" if integer_flows else "lp"
    problem = pulp.LpProblem(f"warehouse_{kind}", pulp.LpMinimize)

    in_flow = [
        [pulp.LpVariable(f"in_{i}_{t}", lowBound=0, cat=flow_cat) for t in range(len(PERIODS))]
        for i in range(n_shelves)
    ]
    out_flow = [
        [pulp.LpVariable(f"out_{i}_{t}", lowBound=0, cat=flow_cat) for t in range(len(PERIODS))]
        for i in range(n_shelves)
    ]
    # 期末库存按题目要求为非负连续变量；上界写成显式约束，便于读取影子价格。
    stock = [
        [pulp.LpVariable(f"stock_{i}_{t}", lowBound=0, cat=pulp.LpContinuous) for t in range(len(PERIODS))]
        for i in range(n_shelves)
    ]

    problem += pulp.lpSum(
        costs[i] * (in_flow[i][t] + out_flow[i][t])
        for i in range(n_shelves)
        for t in range(len(PERIODS))
    )

    constraints = {
        "in_capacity": {},
        "out_capacity": {},
        "stock_capacity": {},
        "balance": {},
    }

    for i in range(n_shelves):
        for t, period in enumerate(PERIODS):
            key = f"Shelf{i + 1}_{period}"
            in_name = f"in_cap_{i}_{t}"
            out_name = f"out_cap_{i}_{t}"
            stock_name = f"stock_cap_{i}_{t}"
            balance_name = f"balance_{i}_{t}"

            problem += in_flow[i][t] <= CAPACITY, in_name
            problem += out_flow[i][t] <= CAPACITY, out_name
            problem += stock[i][t] <= CAPACITY, stock_name

            if t == 0:
                problem += (
                    stock[i][t] == INITIAL_STOCK + in_flow[i][t] - out_flow[i][t]
                ), balance_name
            else:
                problem += (
                    stock[i][t] == stock[i][t - 1] + in_flow[i][t] - out_flow[i][t]
                ), balance_name

            constraints["in_capacity"][key] = problem.constraints[in_name]
            constraints["out_capacity"][key] = problem.constraints[out_name]
            constraints["stock_capacity"][key] = problem.constraints[stock_name]
            constraints["balance"][key] = problem.constraints[balance_name]

    problem += pulp.lpSum(in_flow[i][t] for i in range(n_shelves) for t in range(len(PERIODS))) == inbound, "total_inbound"
    problem += pulp.lpSum(out_flow[i][t] for i in range(n_shelves) for t in range(len(PERIODS))) == outbound, "total_outbound"
    constraints["total_inbound"] = problem.constraints["total_inbound"]
    constraints["total_outbound"] = problem.constraints["total_outbound"]

    return {
        "problem": problem,
        "in_flow": in_flow,
        "out_flow": out_flow,
        "stock": stock,
        "constraints": constraints,
        "costs": costs,
    }


def _solve(problem):
    status = problem.solve(pulp.PULP_CBC_CMD(msg=False))
    if pulp.LpStatus[status] != "Optimal":
        raise RuntimeError(f"模型无最优解，求解状态: {pulp.LpStatus[status]}")
    return status


def _read_schedule(model):
    schedule = []
    for i, cost in enumerate(model["costs"]):
        for t, period in enumerate(PERIODS):
            schedule.append(
                {
                    "shelf": i + 1,
                    "period": period,
                    "in_flow": int(round(pulp.value(model["in_flow"][i][t]))),
                    "out_flow": int(round(pulp.value(model["out_flow"][i][t]))),
                    "stock": round(pulp.value(model["stock"][i][t]), 6),
                    "unit_cost": cost,
                }
            )
    return schedule


def _dual(constraint):
    price = constraint.pi
    if price is None:
        raise RuntimeError(f"约束 {constraint.name} 没有影子价格。整数模型无法提供对偶值。")
    return round(float(price), 6)


def _read_shadow_prices(model):
    constraints = model["constraints"]
    return {
        "in_capacity": {key: _dual(cons) for key, cons in constraints["in_capacity"].items()},
        "out_capacity": {key: _dual(cons) for key, cons in constraints["out_capacity"].items()},
        "stock_capacity": {key: _dual(cons) for key, cons in constraints["stock_capacity"].items()},
        "balance": {key: _dual(cons) for key, cons in constraints["balance"].items()},
        "total_inbound": _dual(constraints["total_inbound"]),
        "total_outbound": _dual(constraints["total_outbound"]),
    }


def _read_reduced_costs(model):
    reduced = {"in_flow": {}, "out_flow": {}, "stock": {}}
    groups = (
        ("in_flow", model["in_flow"]),
        ("out_flow", model["out_flow"]),
        ("stock", model["stock"]),
    )
    for name, variables in groups:
        for i in range(len(variables)):
            for t, period in enumerate(PERIODS):
                dj = variables[i][t].dj
                reduced[name][f"Shelf{i + 1}_{period}"] = None if dj is None else round(float(dj), 6)
    return reduced


if __name__ == "__main__":
    import json

    result = run_model()
    print(json.dumps(result, ensure_ascii=False, indent=2))
