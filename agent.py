"""仓库排班运筹助手。"""
from __future__ import annotations
import json
import os
from pathlib import Path
from openai import OpenAI
from solver import run_model

# 兼容云端 Secrets
try:
    import streamlit as st
    if "ZHIPU_API_KEY" in st.secrets:
        os.environ["ZHIPU_API_KEY"] = st.secrets["ZHIPU_API_KEY"]
except Exception:
    pass

# 兼容本地 .env
try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).with_name(".env"))
except ImportError:
    pass

ZHIPU_BASE_URL = "https://open.bigmodel.cn/api/paas/v4/"

# 强化后的提示词：强制优先判断是否满载
SYSTEM_PROMPT = (
    "你是一个资深的供应链运筹学专家。你拥有一个仓库排班的线性规划模型。\n"
    "当用户询问假设性问题时，请调用工具重新计算。\n"
    "【必须遵守的规则】\n"
    "1. 如果工具返回 status='Infeasible'，说明任务物理上无法完成，根据 error_reason 向用户解释原因。\n"
    "2. 如果工具返回 status='Error'，请直接道歉，让用户稍后再试。\n"
    "3. 如果工具返回 status='Optimal'，直接告诉用户 total_cost（最优总成本）。\n"
    "4. 【影子价格汇报规则】当用户询问敏感性分析或影子价格时，你必须先对比 `inbound` 和 `max_in_capacity`，以及 `outbound` 和 `max_out_capacity`：\n"
    "   - **如果当前需求已经等于物理容量上限**（例如 inbound == max_in_capacity），你的**第一句话**必须严厉警告用户：'请注意，当前 X 个货架已经 100% 满载（最大容量为 Y 批），物理上无法再增加任何入库/出库量。' 然后你再补充：'在此满载状态下，理论影子价格为 Z，代表如果强行多塞 1 批，成本理论上会增加 Z，但实际上由于空间限制，这是做不到的。'\n"
    "   - **如果当前需求小于物理容量上限**，你再正常解释影子价格的经济学含义。\n"
    "你必须用用户提问时使用的语言进行回复（中文提问用中文回，英文提问用英文回）。"
)

BASELINE = {"inbound": 32, "outbound": 31, "costs": [1, 2, 2, 3]}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_warehouse_optimization",
            "description": "Solve warehouse scheduling. Returns total_cost, status, shadow prices, and physical max capacities.",
            "parameters": {
                "type": "object",
                "properties": {
                    "inbound": {"type": "integer", "description": "Total inbound demand (batches)."},
                    "outbound": {"type": "integer", "description": "Total outbound demand (batches)."},
                    "costs": {"type": "array", "items": {"type": "number"}, "description": "List of shelf costs. Length determines the number of shelves."},
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
    shadow = result.get("shadow_prices", {})
    
    return {
        "total_cost": result.get("total_cost"),
        "status": result.get("status"),
        "error_reason": result.get("error_reason", ""),
        "shadow_total_inbound": shadow.get("total_inbound"),
        "shadow_total_outbound": shadow.get("total_outbound"),
        "max_in_capacity": result.get("max_in_capacity"),   # 核心：把上限传给 AI
        "max_out_capacity": result.get("max_out_capacity")  # 核心：把上限传给 AI
    }

def _client():
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key:
        raise RuntimeError("ZHIPU_API_KEY is not set.")
    return OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)

def _execute_tool_call(tool_call):
    name = tool_call.function.name
    raw_arguments = tool_call.function.arguments or "{}"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"Invalid JSON: {exc}"}, ensure_ascii=False)

    if name != "run_warehouse_optimization":
        return json.dumps({"error": f"Unknown tool: {name}"}, ensure_ascii=False)

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
        return "Please enter a question."

    if not hasattr(chat_with_agent, "messages"):
        chat_with_agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    messages = chat_with_agent.messages
    messages.append({"role": "user", "content": text})

    client = _client()
    model = os.environ.get("ZHIPU_MODEL", "glm-4-air")

    for _ in range(8):
        try:
            response = client.chat.completions.create(
                model=model, messages=messages, tools=TOOLS, tool_choice="auto",
            )
        except Exception as e:
            return f"❌ API Error: {str(e)}"
            
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

    return "Too many tool calls. No final answer generated."

def reset_conversation():
    chat_with_agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]