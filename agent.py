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

# 关键修改：让大模型始终使用用户提问的语言来回复
SYSTEM_PROMPT = (
    "You are a senior Supply Chain Operations Research Expert. You have a linear programming model for warehouse scheduling.\n"
    "IMPORTANT RULE: You MUST ALWAYS respond in the exact same language as the user's question. "
    "If the user asks in English, you MUST reply in English. If the user asks in Chinese, reply in Chinese.\n\n"
    "When the user asks hypothetical questions, please call the tool to recalculate.\n"
    "1. If the tool returns status='Infeasible', explain the `error_reason` to the user in plain language and provide suggestions.\n"
    "2. If the tool returns status='Error', apologize and ask the user to try again later. DO NOT make up results!\n"
    "3. If the tool returns status='Optimal', tell the user the `total_cost` (optimal total cost).\n"
    "4. If the user asks for sensitivity analysis, extract `shadow_total_inbound` and `shadow_total_outbound` (shadow prices) and explain their economic meaning (i.e., how much the total cost increases if the demand increases by 1 batch)."
)

BASELINE = {"inbound": 32, "outbound": 31, "costs": [1, 2, 2, 3]}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_warehouse_optimization",
            "description": "Solve warehouse scheduling. Returns total_cost, status, and shadow prices for total inbound/outbound.",
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