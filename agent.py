"""仓库排班运筹助手。

通过 OpenAI Function Calling 调用 solver.run_model，
用总成本和对偶影子价格回答假设性问题。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from solver import run_model

load_dotenv(Path(__file__).with_name(".env"))

ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

SYSTEM_PROMPT = (
    "你是一个资深的供应链运筹学专家。你拥有一个仓库排班的线性规划模型。"
    "当用户询问假设性问题时，请调用工具重新计算。"
    "如果用户问及‘多搬一批会怎样’，你需要提取工具返回的‘影子价格(Shadow Price)’并用大白话解释；"
    "如果用户改变成本，调用工具后对比成本变化并给出原因。"
)

# 基准情景与 solver.py 的默认参数一致，方便模型在追问时知道该改哪一项。
BASELINE = {"inbound": 32, "outbound": 31, "costs": [1, 2, 2, 3]}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_warehouse_optimization",
            "description": (
                "求解 4 个货架、上午/下午两个时段的仓库入库与出库排班，最小化搬运总成本。"
                "每个货架每个时段的入库、出库和期末库存容量都是 4。"
                f"未改动的参数请沿用基准情景：inbound={BASELINE['inbound']}，"
                f"outbound={BASELINE['outbound']}，costs={BASELINE['costs']}（依次为 Shelf1 到 Shelf4 的单位搬运成本）。"
                "返回 total_cost（最优总成本）、schedule（排班）和 shadow_prices（影子价格）。"
                "shadow_prices 的含义是对应约束右端增加 1 时最优成本的变化："
                "total_inbound / total_outbound 是总入库、总出库需求的影子价格；"
                "in_capacity、out_capacity、stock_capacity 是各货架各时段容量的影子价格，"
                "键名形如 Shelf1_上午；balance 是库存平衡等式的影子价格。"
                "容量影子价格为负，表示放宽该容量能降低总成本。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inbound": {
                        "type": "integer",
                        "description": "入库总需求（批）。基准为 32。",
                    },
                    "outbound": {
                        "type": "integer",
                        "description": "出库总需求（批）。基准为 31。",
                    },
                    "costs": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": "4 个货架的单位搬运成本，顺序为 Shelf1 到 Shelf4。基准为 [1, 2, 2, 3]。",
                    },
                },
                "required": ["inbound", "outbound", "costs"],
                "additionalProperties": False,
            },
        },
    }
]


def run_warehouse_optimization(inbound=32, outbound=31, costs=None):
    """调用线性规划模型，返回总成本、排班和影子价格。"""
    if costs is None:
        costs = list(BASELINE["costs"])
    result = run_model(inbound=int(inbound), outbound=int(outbound), costs=[float(cost) for cost in costs])
    return {
        "total_cost": result["total_cost"],
        "schedule": result["schedule"],
        "shadow_prices": result["shadow_prices"],
        "status": result["status"],
    }


def _client():
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("未在 .env 中设置 ZHIPU_API_KEY，无法调用智谱。")
    return OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)


def _execute_tool_call(tool_call):
    name = tool_call.function.name
    raw_arguments = tool_call.function.arguments or "{}"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"工具参数不是合法 JSON: {exc}"}, ensure_ascii=False)

    if name != "run_warehouse_optimization":
        return json.dumps({"error": f"未知工具: {name}"}, ensure_ascii=False)

    try:
        payload = run_warehouse_optimization(
            inbound=arguments.get("inbound", BASELINE["inbound"]),
            outbound=arguments.get("outbound", BASELINE["outbound"]),
            costs=arguments.get("costs", BASELINE["costs"]),
        )
    except Exception as exc:
        payload = {"error": str(exc)}
    return json.dumps(payload, ensure_ascii=False)


def chat_with_agent(user_input):
    """接收一句用户输入，循环处理 tool_calls，直到模型给出最终回答。

    同一进程内的多次调用会保留对话历史，因此可以连续追问。
    """
    text = (user_input or "").strip()
    if not text:
        return "请输入一个关于仓库排班、搬运成本或影子价格的问题。"

    if not hasattr(chat_with_agent, "messages"):
        chat_with_agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages = chat_with_agent.messages
    messages.append({"role": "user", "content": text})

    client = _client()
    model = os.environ.get("ZHIPU_MODEL", "glm-4-flash")

    for _ in range(8):
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
        )
        message = response.choices[0].message
        messages.append(message.model_dump(exclude_none=True))

        tool_calls = message.tool_calls or []
        if not tool_calls:
            return message.content or ""

        for tool_call in tool_calls:
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": _execute_tool_call(tool_call),
                }
            )

    return "工具调用次数过多，本轮没有得到最终回答。请把问题再具体一点。"


def reset_conversation():
    """清空多轮对话历史，下一轮从系统提示重新开始。"""
    chat_with_agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]


if __name__ == "__main__":
    print("仓库运筹助手。输入问题后回车；输入 quit 退出，输入 reset 清空上下文。")
    while True:
        try:
            user_text = input("你: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        command = user_text.strip().lower()
        if command in {"quit", "exit", "q"}:
            break
        if command == "reset":
            reset_conversation()
            print("助手: 对话已重置。")
            continue
        print("助手:", chat_with_agent(user_text))
