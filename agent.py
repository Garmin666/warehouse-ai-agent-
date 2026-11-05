"""仓库排班运筹助手。

通过 OpenAI Function Calling 调用 solver.run_model，
支持动态货架数量，能够智能解释模型无解的原因。
"""

from __future__ import annotations
import json
import os
from pathlib import Path
from openai import OpenAI
from solver import run_model

# ==========================================
# 1. 密钥读取逻辑（兼容本地和云端）
# ==========================================
try:
    import streamlit as st
    if "ZHIPU_API_KEY" in st.secrets:
        os.environ["ZHIPU_API_KEY"] = st.secrets["ZHIPU_API_KEY"]
except Exception:
    pass

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

# ==========================================
# 2. 系统提示词（强化了无解时的解释能力）
# ==========================================
SYSTEM_PROMPT = (
    "你是一个资深的供应链运筹学专家。你拥有一个仓库排班的线性规划模型。"
    "当用户询问假设性问题时，请调用工具重新计算。"
    "【重要规则】如果工具返回的 status 是 'Infeasible'，说明当前任务在物理上无法完成。"
    "此时，你必须读取返回中的 `error_reason`，并用非常专业但通俗的大白话向用户解释为什么做不到"
    "（例如：是货架数量太少导致容量爆满？还是入库和出库的数量不平衡导致了死锁？），"
    "并给出具体的建议（比如建议增加货架、或者调整发货量）。"
    "如果算出了结果，当用户问及‘多搬一批会怎样’，你需要提取‘影子价格(Shadow Price)’并解释；"
    "如果用户改变成本，调用工具后对比成本变化并给出原因。"
)

# 基准情景
BASELINE = {"inbound": 32, "outbound": 31, "costs": [1, 2, 2, 3]}

# ==========================================
# 3. 工具定义
# ==========================================
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_warehouse_optimization",
            "description": (
                "求解任意数量货架、上午/下午两个时段的仓库入库与出库排班，最小化搬运总成本。"
                "每个货架每个时段的入库、出库和期末库存容量都是 4。"
                "返回 total_cost（最优总成本）、schedule（排班）、status（状态）和 error_reason（无解原因）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "inbound": {"type": "integer", "description": "入库总需求（批）。"},
                    "outbound": {"type": "integer", "description": "出库总需求（批）。"},
                    "costs": {
                        "type": "array", "items": {"type": "number"},
                        "description": "各个货架的单位搬运成本列表，长度决定货架数量。例如 [1, 2, 2, 3]。",
                    },
                },
                "required": ["inbound", "outbound", "costs"],
                "additionalProperties": False,
            },
        },
    }
]


def run_warehouse_optimization(inbound=32, outbound=31, costs=None):
    if costs is None:
        costs = list(BASELINE["costs"])
    result = run_model(inbound=int(inbound), outbound=int(outbound), costs=[float(cost) for cost in costs])
    
    return {
        "total_cost": result.get("total_cost"),
        "schedule": result.get("schedule"),
        "shadow_prices": result.get("shadow_prices"),
        "status": result.get("status"),
        "error_reason": result.get("error_reason", "")
    }


def _client():
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("未设置 ZHIPU_API_KEY，请在本地 .env 或云端 Secrets 中配置。")
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
        payload = {"status": "Error", "error_reason": str(exc)}
    return json.dumps(payload, ensure_ascii=False)


def chat_with_agent(user_input):
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
            model=model, messages=messages, tools=TOOLS, tool_choice="auto",
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
    """清空多轮对话历史。"""
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