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

SYSTEM_PROMPT = (
    "你是一个资深的供应链运筹学专家。你拥有一个仓库排班的线性规划模型。"
    "当用户询问假设性问题时，请调用工具重新计算。"
    "【必须遵守的规则】"
    "1. 如果工具返回 status='Infeasible'，说明任务在物理上无法完成，请根据返回的 `error_reason` 向用户解释原因并给出建议。"
    "2. 如果工具返回 status='Error'，说明底层服务器崩溃了，请直接道歉并让用户稍后再试，绝对不要自行猜测计算结果！"
    "3. 如果工具返回 status='Optimal'，请直接告诉用户 `total_cost`（最优总成本）。"
    "4. 如果用户问及敏感性分析，提取 `shadow_total_inbound` 和 `shadow_total_outbound`（影子价格）并向用户解释其含义（即每增加1批需求，总成本会增加的金额）。"
)

BASELINE = {"inbound": 32, "outbound": 31, "costs": [1, 2, 2, 3]}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_warehouse_optimization",
            "description": "求解仓库排班，返回最优总成本、状态和总进/出库影子价格。",
            "parameters": {
                "type": "object",
                "properties": {
                    "inbound": {"type": "integer", "description": "入库总需求（批）。"},
                    "outbound": {"type": "integer", "description": "出库总需求（批）。"},
                    "costs": {"type": "array", "items": {"type": "number"}, "description": "货架成本列表，长度决定货架数量。"},
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
    
    # 只返回 AI 最需要的数据，坚决不给庞大的排班细节
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
        raise RuntimeError("未设置 ZHIPU_API_KEY。")
    return OpenAI(api_key=api_key, base_url=ZHIPU_BASE_URL)

def _execute_tool_call(tool_call):
    name = tool_call.function.name
    raw_arguments = tool_call.function.arguments or "{}"
    try:
        arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else dict(raw_arguments)
    except json.JSONDecodeError as exc:
        return json.dumps({"error": f"参数不是合法 JSON: {exc}"}, ensure_ascii=False)

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
        return "请输入一个关于仓库排班的问题。"

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
            return f"❌ API 调用失败：{str(e)}"
            
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

    return "工具调用次数过多，没有得到最终回答。"

def reset_conversation():
    chat_with_agent.messages = [{"role": "system", "content": SYSTEM_PROMPT}]