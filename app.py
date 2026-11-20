import streamlit as st
import base64
import os
from agent import chat_with_agent, reset_conversation

st.set_page_config(page_title="Warehouse Optimization System", layout="wide", initial_sidebar_state="expanded")

def get_base64(bin_file):
    with open(bin_file, 'rb') as f:
        data = f.read()
    return base64.b64encode(data).decode()

bg_image_path = "background.jpg"  
if os.path.exists(bg_image_path):
    bin_str = get_base64(bg_image_path)
    page_bg_img = f'''
    <style>
    [data-testid="stAppViewContainer"] {{
        background-image: linear-gradient(rgba(14, 17, 23, 0.75), rgba(14, 17, 23, 0.75)), url("data:image/jpeg;base64,{bin_str}");
        background-size: cover !important;
        background-position: center !important;
        background-attachment: fixed !important;
        background-repeat: no-repeat !important;
        height: 100vh !important;
    }}
    [data-testid="stHeader"], 
    [data-testid="stBottom"], 
    [data-testid="stBottom"] > div,
    [data-testid="stBottomBlockContainer"],
    footer,
    .stApp {{
        background-color: transparent !important;
        background: transparent !important;
        border: none !important;
    }}
    [data-testid="stSidebar"] {{
        background-color: rgba(14, 17, 23, 0.35) !important;
        backdrop-filter: blur(8px) !important;
    }}
    [data-testid="stChatInput"] {{
        background-color: rgba(30, 35, 45, 0.85) !important;
        backdrop-filter: blur(10px) !important;
        border-radius: 15px !important;
        border: 1px solid rgba(255, 255, 255, 0.1) !important;
    }}
    [data-testid="stChatMessage"] {{
        background-color: rgba(30, 35, 45, 0.8) !important;
        backdrop-filter: blur(8px) !important;
        border-radius: 10px !important;
        padding: 15px !important;
    }}
    h1, h2, h3, p, span, label, div {{
        color: #f8f9fa !important;
    }}
    </style>
    '''
    st.markdown(page_bg_img, unsafe_allow_html=True)
else:
    st.error(f"❌ 找不到背景图片：{bg_image_path}。")

translations = {
    "zh": {
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

if "lang" not in st.session_state:
    st.session_state.lang = "zh"

col1, col2 = st.columns([4, 1])
with col2:
    lang_choice = st.radio(
        "Language", options=["中文", "English"], 
        index=0 if st.session_state.lang == "zh" else 1, 
        horizontal=True, label_visibility="collapsed"
    )
    new_lang = "zh" if lang_choice == "中文" else "en"
    if new_lang != st.session_state.lang:
        st.session_state.lang = new_lang
        st.rerun()

t = translations[st.session_state.lang]

with col1:
    st.title(t["title"])
    st.caption(t["caption"])

with st.sidebar:
    st.header(t["sidebar_header"])
    st.markdown(t["sidebar_desc"])
    
    inbound = st.number_input(t["inbound_label"], min_value=0, value=1150, step=50)
    outbound = st.number_input(t["outbound_label"], min_value=0, value=1100, step=50)
    
    st.subheader(t["cost_header"])
    num_shelves = st.slider(t["num_shelves"], min_value=1, max_value=101, value=100)
    
    costs = []
    cols = st.columns(4)
    for i in range(num_shelves):
        with cols[i % 4]:
            c = st.number_input(t["shelf_cost"].format(i + 1), min_value=0.0, value=float(i + 1), step=1.0, key=f"cost_{i}")
            costs.append(c)
    
    st.divider()
    if st.button(t["clear_btn"], use_container_width=True):
        st.session_state.messages = []
        reset_conversation()
        st.rerun()

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
                
                # 💡 核心修复：根据当前选择的语言，强制下发语言死命令
                if st.session_state.lang == "en":
                    language_cmd = "【REPLY IN ENGLISH ONLY】You MUST answer strictly in English."
                else:
                    language_cmd = "【只允许用中文回答】你必须严格使用中文回答。"
                
                full_prompt = f"{language_cmd}\n{current_params}\n\nUser Question: {prompt}"
                
                response = chat_with_agent(full_prompt)
                
                st.markdown(response)
                st.session_state.messages.append({"role": "assistant", "content": response})
                
            except Exception as e:
                error_msg = f"{t['error_prefix']}{str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})