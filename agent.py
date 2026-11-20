"""仓库排班运筹助手。"""
from __future__ import annotations
import json
import os
from pathlib import Path
from openai import OpenAI
from solver import run_model

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

# 💡 强化语言指令：放到最前面，并强调必须遵守
SYSTEM_PROMPT = (
    "【ABSOLUTE RULE - MUST FOLLOW】You MUST reply in the exact language requested in the prompt. "
    "If the prompt says 'REPLY IN ENGLISH', you MUST output 100% English. If 'REPLY IN CHINESE', output 100% Chinese. "
    "NEVER use Chinese if the requested language is English.\n\n"
    "You are a senior Supply Chain Operations Research Expert. You have a linear programming model for warehouse scheduling.\n"
    "When the user asks hypothetical questions, call the tool to recalculate.\n"
    "1. If tool returns Infeasible, explain the error_reason and give suggestions.\n"
    "2. If tool returns Error, apologize and ask the user to try again.\n"
    "3. If tool returns Optimal, report the total_cost.\n"
    "4. For sensitivity analysis, explain shadow_total_inbound and shadow_total_outbound.\n"
    "5. Report labor_metrics: theoretical workers, actual workers needed, utilization rate, and surplus workers."
)

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_warehouse_optimization",
            "description": "Solve large warehouse scheduling. Returns cost, shadow prices, max capacity, and labor metrics.",
            "parameters": {
                "type": "object",
                "properties": {
                    "inbound": {"type": "integer", "description": "Total inbound demand."},
                    "outbound": {"type": "integer", "description": "Total outbound demand."},
                    "costs": {"type": "array", "items": {"type": "number"}, "description": "List of shelf costs."},
                },
                "required": ["inbound", "outbound", "costs"],
                "additionalProperties": False,
            },
        },
    }
]

def run_warehouse_optimization(inbound=1150, outbound=1100, costs=None):
    if costs is None:
        costs = [i + 1 for i in range(100)]
    
    result = run_model(inbound=int(inbound), outbound=int(outbound), costs=[float(cost) for cost in costs])
    shadow = result.get("shadow_prices", {})
    
    return {
        "total_cost": result.get("total_cost"),
        "status": result.get("status"),
        "error_reason": result.get("error_reason", ""),
        "shadow_total_inbound": shadow.get("total_inbound"),
        "shadow_total_outbound": shadow.get("total_outbound"),
        "max_in_capacity": result.get("max_in_capacity"),
        "max_out_capacity": result.get("max_out_capacity"),
        "labor_metrics": result.get("labor_metrics")
    }

def _client():
    api_key = os.environ.get("ZHIPU_API_KEY")
    if not api_key: raise RuntimeError("ZHIPU_API_KEY is not set.")
    return OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)

def _execute_tool_call(tool_call):
    name = tool_call.function.name
    args = json.loads(tool_call.function.arguments or "{}")
    try:
        payload = run_warehouse_optimization(
            inbound=args.get("inbound", 1150),
            outbound=args.get("outbound", 1100),
            costs=args.get("costs", None),
        )
    except Exception as exc:
        payload = {"status": "Error", "error_reason": str(exc)}
    return json.dumps(payload, ensure_ascii=False)

def chat_with_agent(user_input):
    text = (user_input or "").strip()
    if not text: return "Please enter a question."

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

        if not message.tool_calls:
            return message.content or ""

        for tool_call in message.tool_calls:
            messages.append({"role": "tool", "tool_call_id": tool_call.id, "content": _execute_tool_call(tool_call)})

    return "Too many tool calls."

def reset_conversation():
    chat_with_agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]