"""仓库排班运筹助手（大模型总监版）。"""
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

SYSTEM_PROMPT = (
    "你是一个资深的供应链与物流总监。你拥有一个大型仓库（多货架、4个时段）的线性规划模型。\n"
    "当用户询问问题时，请调用工具重新计算。\n"
    "【必须遵守的规则】\n"
    "1. 如果工具返回 Infeasible，请根据 error_reason 用大白话解释为什么装不下。\n"
    "2. 如果算出结果，请报告 total_cost（最优成本）。\n"
    "3. 【重要】你还需要向老板汇报 `labor_metrics`（人力情况）。请指出：理论需要多少人，实际排班需要多少人，如果公司有 20 人，现在的利用率是多少，闲置（surplus_workers）了几个人。\n"
    "4. 如果用户问敏感性分析（影子价格），请先检查当前需求量是否等于最大容量。如果没满载，解释 shadow_inbound 和 shadow_outbound（多进/多出1批货，成本增加多少）。\n"
    "5. 永远用用户提问的语言回复（中文问用中文，英文问用英文）。"
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
                    "costs": {"type": "array", "items": {"type": "number"}, "description": "List of shelf costs (1 to 100)."},
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
        "labor_metrics": result.get("labor_metrics") # 把人力数据传给 AI
    }

# 下面是常规的调用逻辑（和之前一样，无需改动）
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