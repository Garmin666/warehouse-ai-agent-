import time
import requests
import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
from streamlit_lottie import st_lottie
from agent import chat_with_agent, reset_conversation
import numpy as np

# 页面基础配置
st.set_page_config(page_title="Warehouse Optimization System", layout="wide", initial_sidebar_state="expanded")

# ==========================================
# 0. 注入 CSS 动态呼吸渐变背景
# ==========================================
st.markdown("""
<style>
/* 隐藏顶部多余背景，让渐变流动更自然 */
.stApp > header {
    background-color: transparent;
}
.stApp {
    background-color: #0e1117;
    background-image: radial-gradient(at 10% 20%, hsla(225, 80%, 40%, 0.15) 0px, transparent 50%),
                      radial-gradient(at 90% 10%, hsla(280, 70%, 50%, 0.12) 0px, transparent 50%),
                      radial-gradient(at 50% 80%, hsla(190, 80%, 40%, 0.1) 0px, transparent 50%);
    background-size: 150% 150%;
    animation: nebula_flow 18s ease-in-out infinite;
}

@keyframes nebula_flow {
    0% { background-position: 0% 50%; }
    50% { background-position: 100% 50%; }
    100% { background-position: 0% 50%; }
}
</style>
""", unsafe_allow_html=True)

# ==========================================
# 1. Lottie 动画加载函数
# ==========================================
@st.cache_data
def load_lottieurl(url: str):
    try:
        r = requests.get(url, timeout=3)
        if r.status_code != 200:
            return None
        return r.json()
    except Exception:
        return None

# 加载纯代码开源素材（避免死链）
lottie_loading = load_lottieurl("https://assets5.lottiefiles.com/packages/lf20_gnrjfd5s.json")

# ==========================================
# 2. 多语言字典
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
        "error_prefix": "❌ 运行出错：",
        "chart_title": "货架排班动态分布（模拟热力预览）"
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
        "error_prefix": "❌ Error: ",
        "chart_title": "Dynamic Shelf Allocation (Heatmap Preview)"
    }
}

# ==========================================
# 3. 顶部语言切换与标题区域
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
# 4. 侧边栏：参数控制
# ==========================================
with st.sidebar:
    st.header(t["sidebar_header"])
    st.markdown(t["sidebar_desc"])
    
    inbound = st.number_input(t["inbound_label"], min_value=0, value=32, step=1)
    outbound = st.number_input(t["outbound_label"], min_value=0, value=31, step=1)
    
    st.subheader(t["cost_header"])
    
    num_shelves = st.slider(t["num_shelves"], min_value=1, max_value=101, value=4)
    
    costs = []
    cols = st.columns(4)
    for i in range(num_shelves):
        default_cost = i + 1
        with cols[i % 4]:
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
# 5. 主界面：聊天记录与动态图表
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
        # 使用 Lottie 动画替代普通 Spinner
        if lottie_loading:
            with st.container():
                c_lottie = st.empty()
                with c_lottie:
                    st_lottie(lottie_loading, height=100, key="loading")
        else:
            st.spinner(t["spinner"])

        try:
            current_params = f"[Current Parameters] Inbound: {inbound}, Outbound: {outbound}, Shelf Costs: {costs}."
            full_prompt = f"{current_params}\n\nUser Question: {prompt}"
            
            # 模拟一小段延迟以展示动画（实际调 AI 也可）
            with st.spinner(t["spinner"]):
                response = chat_with_agent(full_prompt)
            
            # 清空 Lottie 动画
            if lottie_loading:
                c_lottie.empty()
                
            st.markdown(response)
            st.session_state.messages.append({"role": "assistant", "content": response})

            # ==========================================
            # 6. 动态生成 Plotly 排班图表（可视化增强）
            # ==========================================
            if "Optimal" in response or "影子价格" in response or "Cost" in response:
                st.markdown("---")
                st.subheader(f"📊 {t['chart_title']}")
                
                # 构建模拟可视化数据（根据当前前端货架成本生成分布图）
                shelves_names = [f"Shelf {i+1}" for i in range(num_shelves)]
                data = {
                    "Shelf": shelves_names,
                    "Unit Cost": costs,
                    "Allocated Flow": [np.random.randint(4, 8) for _ in range(num_shelves)]
                }
                fig_bar = px.bar(
                    data, 
                    x="Shelf", 
                    y="Allocated Flow", 
                    color="Unit Cost", 
                    title="Shelf Cost Distribution",
                    color_continuous_scale="Tealgrn"
                )
                fig_bar.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    font=dict(color="white")
                )
                st.plotly_chart(fig_bar, use_container_width=True)
                
        except Exception as e:
            if lottie_loading:
                c_lottie.empty()
            error_msg = f"{t['error_prefix']}{str(e)}"
            st.error(error_msg)
            st.session_state.messages.append({"role": "assistant", "content": error_msg})