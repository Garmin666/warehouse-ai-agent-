import streamlit as st
from agent import chat_with_agent, reset_conversation

# 页面基础配置
st.set_page_config(page_title="Warehouse Optimization System", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 1. 多语言字典
# ==========================================
translations = {
    "zh": {
        "lang_toggle": "🌐 语言 / Language",
        "title": "📦 仓库排班智能决策系统",
        "caption": "基于运筹学（线性规划）与大语言模型的敏感性分析助手",
        "sidebar_header": "⚙️ 模型参数调节",
        "sidebar_desc": "修改参数后，在右侧提问，AI 会根据新参数重新计算。",
        "inbound_label": "入库总量 (Inbound)",
        "outbound_label": "出库总量 (Outbound)",
        "cost_header": "货架搬运成本",
        "num_shelves": "货架数量",
        "shelf_cost": "Shelf {} 成本",
        "clear_btn": "🧹 清空对话记录",
        "chat_placeholder": "例如：算一下现在的总成本，并解释影子价格。",
        "spinner": "运筹学专家正在重新求解模型...",
        "error_prefix": "❌ 运行出错："
    },
    "en": {
        "lang_toggle": "🌐 Language / 语言",
        "title": "📦 Smart Warehouse Scheduling System",
        "caption": "Sensitivity Analysis Assistant based on Operations Research & LLM",
        "sidebar_header": "⚙️ Model Parameters",
        "sidebar_desc": "Adjust parameters, then ask questions on the right. AI will recalculate.",
        "inbound_label": "Total Inbound (Batches)",
        "outbound_label": "Total Outbound (Batches)",
        "cost_header": "Shelf Movement Costs",
        "num_shelves": "Number of Shelves",
        "shelf_cost": "Shelf {} Cost",
        "clear_btn": "🧹 Clear Chat History",
        "chat_placeholder": "e.g., Calculate the total cost and explain the shadow prices.",
        "spinner": "Operations Research Expert is recalculating...",
        "error_prefix": "❌ Error: "
    }
}

# ==========================================
# 2. 顶部语言切换与标题区域
# ==========================================
if "lang" not in st.session_state:
    st.session_state.lang = "zh"

col1, col2 = st.columns([4, 1])

with col2:
    lang_choice = st.radio(
        "Language", 
        options=["中文", "English"], 
        index=0 if st.session_state.lang == "zh" else 1, 
        horizontal=True,
        label_visibility="collapsed"
    )
    new_lang = "zh" if lang_choice == "中文" else "en"
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

t = translations[st.session_state.lang]

with col1:
    st.title(t["title"])
    st.caption(t["caption"])

# ==========================================
# 3. 侧边栏：参数控制
# ==========================================
with st.sidebar:
    st.header(t["sidebar_header"])
    st.markdown(t["sidebar_desc"])
    
    # 默认入库和出库给大一点，方便测试大货架模型
    inbound = st.number_input(t["inbound_label"], min_value=0, value=32, step=1)
    outbound = st.number_input(t["outbound_label"], min_value=0, value=31, step=1)
    
    st.subheader(t["cost_header"])
    
    # 💡 修改点 1：把最大值改为 101
    num_shelves = st.slider(t["num_shelves"], min_value=1, max_value=101, value=4)
    
    costs = []
    # 💡 修改点 2：改为 4 列排布，防止 101 个输入框把页面撑得太长
    cols = st.columns(4)
    for i in range(num_shelves):
        default_cost = i + 1
        with cols[i % 4]:
            # 为了不让 UI 卡顿，这里改一下 label 的字体大小（可选）
            c = st.number_input(
                t["shelf_cost"].format(i + 1), 
                min_value=0.0, 
                value=float(default_cost), 
                step=1.0, 
                key=f"cost_{i}"
            )
            costs.append(c)
    
    st.divider()
    if st.button(t["clear_btn"], use_container_width=True):
        st.session_state.messages = []
        reset_conversation()
        st.rerun()

# ==========================================
# 4. 主界面：聊天记录与输入
# ==========================================
if "messages" not in st.session_state:
    st.session_state.messages = []

for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input(t["chat_placeholder"]):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner(t["spinner"]):
            try:
                current_params = f"[Current Parameters] Inbound: {inbound}, Outbound: {outbound}, Shelf Costs: {costs}."
                full_prompt = f"{current_params}\n\nUser Question: {prompt}"
                
                response = chat_with_agent(full_prompt)
                
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                error_msg = f"{t['error_prefix']}{str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})