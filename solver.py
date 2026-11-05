"""仓库货架两时段入库/出库线性规划。

排班按整数规划求解（入库、出库为非负整数）。
针对无解的情况，会返回具体的 Infeasible 原因，方便 AI 向前端解释。
"""

from __future__ import annotations
import pulp

PERIODS = ("上午", "下午")
CAPACITY = 4
INITIAL_STOCK = 0


def run_model(inbound=32, outbound=31, costs=None):
    """求解货架移动成本最小的入库/出库排班。

    参数
    ----
    inbound : 入库总需求
    outbound : 出库总需求
    costs : 各货架单位移动成本，列表长度决定了货架数量

    返回
    ----
    dict
        status : "Optimal" 或 "Infeasible"
        error_reason : 如果无解，返回具体原因
        total_cost : 最优总成本
        schedule : 每个货架、每个时段的入库、出库和期末库存
        shadow_prices : 影子价格（连续松弛）
    """
    if costs is None:
        costs = [1, 2, 2, 3]
    costs = list(costs)
    n_shelves = len(costs)

    if inbound < 0 or outbound < 0:
        return {
            "status": "Infeasible",
            "error_reason": "入库量和出库量不能为负数。",
            "total_cost": None, "schedule": [], "shadow_prices": {}
        }

    # 🚨 灵动判断 1：提前检查是否超出物理极限
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

    # 构建并求解整数规划模型
    schedule_model = _build_model(inbound, outbound, costs, integer_flows=True)
    status = schedule_model["problem"].solve(pulp.PULP_CBC_CMD(msg=False))

    # 🚨 灵动判断 2：如果 PuLP 依然算出无解（比如库存平衡冲突）
    if pulp.LpStatus[status] != "Optimal":
        return {
            "status": "Infeasible",
            "error_reason": f"由于库存平衡或时段容量限制，模型无法找到合理的排班方案。求解器状态: {pulp.LpStatus[status]}",
            "total_cost": None, "schedule": [], "shadow_prices": {}
        }

    # 如果要计算影子价格，需要跑一次连续松弛
    dual_model = _build_model(inbound, outbound, costs, integer_flows=False)
    dual_model["problem"].solve(pulp.PULP_CBC_CMD(msg=False))

    return {
        "status": "Optimal",
        "error_reason": "",
        "total_cost": round(pulp.value(schedule_model["problem"].objective), 6),
        "schedule": _read_schedule(schedule_model),
        "shadow_prices": _read_shadow_prices(dual_model),
        "reduced_costs": _read_reduced_costs(dual_model),
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
    stock = [
        [pulp.LpVariable(f"stock_{i}_{t}", lowBound=0, cat=pulp.LpContinuous) for t in range(len(PERIODS))]
        for i in range(n_shelves)
    ]

    problem += pulp.lpSum(
        costs[i] * (in_flow[i][t] + out_flow[i][t])
        for i in range(n_shelves)
        for t in range(len(PERIODS))
    )

    constraints = {"in_capacity": {}, "out_capacity": {}, "stock_capacity": {}, "balance": {}}

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

    return {
        "problem": problem, "in_flow": in_flow, "out_flow": out_flow, "stock": stock,
        "constraints": constraints, "costs": costs,
    }


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
    return round(float(constraint.pi), 6) if constraint.pi is not None else 0.0


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
    groups = (("in_flow", model["in_flow"]), ("out_flow", model["out_flow"]), ("stock", model["stock"]))
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