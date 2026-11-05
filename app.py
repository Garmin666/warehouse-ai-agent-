import streamlit as st
import os
from agent import chat_with_agent, reset_conversation

st.set_page_config(page_title="仓库排班智能决策系统", layout="wide", initial_sidebar_state="expanded")

with st.sidebar:
    st.header("⚙️ 模型参数调节")
    st.markdown("修改参数后，在右侧提问，AI 会根据新参数重新计算。")
    
    inbound = st.number_input("入库总量 (Inbound)", min_value=0, value=32, step=1)
    outbound = st.number_input("出库总量 (Outbound)", min_value=0, value=31, step=1)
    
    st.subheader("货架搬运成本")
    # 动态设置货架数量（默认 4 个，最多支持 10 个，防止页面太挤）
    num_shelves = st.slider("货架数量", min_value=1, max_value=10, value=4)
    
    # 动态生成输入框
    costs = []
    cols = st.columns(2) # 分两列显示，更美观
    for i in range(num_shelves):
        default_cost = i + 1 # 默认成本 1, 2, 3, 4...
        with cols[i % 2]:
            c = st.number_input(f"Shelf {i+1} 成本", min_value=0.0, value=float(default_cost), step=1.0, key=f"cost_{i}")
            costs.append(c)
    
    st.divider()
    if st.button("🧹 清空对话记录", use_container_width=True):
        st.session_state.messages = []
        reset_conversation()
        st.rerun()

st.title("📦 仓库排班智能决策系统")
st.caption("基于运筹学（线性规划）与大语言模型的敏感性分析助手")

if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("例如：如果入库变成33，成本会变多少？"):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("运筹学专家正在重新求解模型..."):
            try:
                # 把动态生成的 costs 列表拼接到 Prompt 里
                current_params = f"[当前参数] 入库:{inbound}, 出库:{outbound}, 货架成本列表:{costs}。"
                full_prompt = f"{current_params} 用户问题：{prompt}"
                
                response = chat_with_agent(full_prompt)
                
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                error_msg = f"❌ 运行出错：{str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})