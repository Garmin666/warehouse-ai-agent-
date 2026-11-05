import streamlit as st
import os
from agent import chat_with_agent, reset_conversation

# 1. 页面配置
st.set_page_config(page_title="仓库排班智能决策系统", layout="wide", initial_sidebar_state="expanded")

# 2. 侧边栏：参数配置
with st.sidebar:
    st.header("⚙️ 模型参数调节")
    st.markdown("修改参数后，在右侧提问，AI 会根据新参数重新计算。")
    
    inbound = st.number_input("入库总量 (Inbound)", min_value=0, value=32, step=1)
    outbound = st.number_input("出库总量 (Outbound)", min_value=0, value=31, step=1)
    
    st.subheader("货架搬运成本")
    col1, col2 = st.columns(2)
    with col1:
        c1 = st.number_input("Shelf 1", min_value=0.0, value=1.0, step=1.0)
        c3 = st.number_input("Shelf 3", min_value=0.0, value=2.0, step=1.0)
    with col2:
        c2 = st.number_input("Shelf 2", min_value=0.0, value=2.0, step=1.0)
        c4 = st.number_input("Shelf 4", min_value=0.0, value=3.0, step=1.0)
    
    st.divider()
    # 清空对话按钮
    if st.button("🧹 清空对话记录", use_container_width=True):
        st.session_state.messages = []
        reset_conversation()
        st.rerun()

# 3. 主界面：标题
st.title("📦 仓库排班智能决策系统")
st.caption("基于运筹学（线性规划）与大语言模型的敏感性分析助手")

# 4. 初始化聊天历史
if "messages" not in st.session_state:
    st.session_state.messages = []

# 5. 渲染历史聊天记录
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 6. 处理用户输入
if prompt := st.chat_input("例如：如果入库变成33，成本会变多少？"):
    # 显示用户提问
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # 7. 构建上下文并调用 Agent
    with st.chat_message("assistant"):
        with st.spinner("运筹学专家正在重新求解模型..."):
            try:
                # 将当前参数拼接到用户的问题前面
                current_params = f"[当前参数] 入库:{inbound}, 出库:{outbound}, 成本:[{c1}, {c2}, {c3}, {c4}]。"
                full_prompt = f"{current_params} 用户问题：{prompt}"
                
                # 调用你的 agent.py 中的函数
                response = chat_with_agent(full_prompt)
                
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                # 捕获异常（比如无解、API报错等）
                error_msg = f"❌ 运行出错：{str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})