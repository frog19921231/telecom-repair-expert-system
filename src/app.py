import streamlit as st
from neo4j import GraphDatabase

# 1. 系統連線設定 (優先讀取 Secrets)
NEO4J_URI = st.secrets.get("NEO4J_URI", "neo4j+s://b8cec18b.databases.neo4j.io")
NEO4J_USER = st.secrets.get("NEO4J_USER", "b8cec18b")
NEO4J_PASSWORD = st.secrets.get("NEO4J_PASSWORD", "")
ADMIN_PASSWORD = st.secrets.get("ADMIN_PASSWORD", "admin2026")

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

driver = get_driver()

st.set_page_config(page_title="電信通訊故障診斷專家系統", layout="wide")
st.title("🛠️ 電信通訊故障診斷專家系統")

# ==========================================
# 側邊欄：實時故障統計面板
# ==========================================
with st.sidebar:
    st.header("📊 故障原因累積統計")
    if st.button("🔄 重新整理統計數據"):
        st.rerun()

    stats_query = """
    MATCH (d:DeviceType)-[:HAS_AUDIO_STATE]->(ss:SoundStatus)-[:HAS_SYMPTOM]->(s:Symptom)-[r:CAUSED_BY]->(rc:RootCause)
    RETURN d.name AS 設備類型, ss.name AS 聲響狀態, rc.name AS 原因, coalesce(r.count, 0) AS 次數, round(coalesce(r.prob, 0.0) * 100, 1) AS `機率(%)`
    ORDER BY 設備類型, 次數 DESC
    """
    try:
        with driver.session() as session:
            stats_result = session.run(stats_query)
            data = [row.data() for row in stats_result]
            if data:
                st.dataframe(data, hide_index=True)
            else:
                st.info("尚無統計數據。")
    except Exception as e:
        st.error(f"資料庫連線失敗: {e}")

# ==========================================
# 主畫面：雙分頁架構
# ==========================================
tab_user, tab_admin = st.tabs(["🔧 現場診斷與回報 (一般技師)", "🛡️ 管理員專用後台 (需驗證)"])

# ──────────────────────────────────────────
# 分頁 1: 現場診斷與回報 (三階連動選單)
# ──────────────────────────────────────────
with tab_user:
    st.subheader("現場故障診斷")
    
    # 三欄並排排版
    c1, c2, c3 = st.columns(3)
    
    # ----------------------------------------------------
    # 階層 1: 話機設備類型 (置於 c1)
    # ----------------------------------------------------
    with c1:
        device_types = []
        try:
            with driver.session() as session:
                dt_res = session.run("MATCH (d:DeviceType) RETURN DISTINCT d.name AS name ORDER BY d.name")
                device_types = [r["name"] for r in dt_res]
        except Exception:
            device_types = [
                "類比話機 (傳統單機/POTS)", 
                "AVAYA 數位話機 (1400/2400系列)",
                "AVAYA IP話機 (9600/J系列)"
            ]

        selected_device = st.selectbox(
            "【層級 1】選擇話機設備類型：",
            device_types,
            help="選擇話機運作架構（類比、專用數位或基於網路協定的 IP 話機）"
        )

    # ----------------------------------------------------
    # 階層 2: 依設備類型連動取得聲響狀態 (置於 c2)
    # ----------------------------------------------------
    with c2:
        sound_status_list = []
        try:
            with driver.session() as session:
                ss_res = session.run(
                    """
                    MATCH (d:DeviceType {name: \$device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus)
                    RETURN DISTINCT ss.name AS name ORDER BY ss.name
                    """,
                    device=selected_device
                )
                sound_status_list = [r["name"] for r in ss_res]
        except Exception:
            sound_status_list = []

        selected_sound = st.radio(
            "【層級 2】聲響基本狀態", 
            sound_status_list if sound_status_list else ["無狀態"]
        )

    # ----------------------------------------------------
    # 階層 3: 依聲響狀態連動取得具體故障現象 (置於 c3)
    # ----------------------------------------------------
    with c3:
        symptom_list = []
        try:
            with driver.session() as session:
                s_res = session.run(
                    """
                    MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus {name:$sound})-[:HAS_SYMPTOM]->(s:Symptom)
                    RETURN DISTINCT s.name AS name ORDER BY s.name
                    """,
                    device=selected_device,
                    sound=selected_sound
                )
                symptom_list = [r["name"] for r in s_res]
        except Exception:
            symptom_list = []

        if symptom_list:
            selected_symptom = st.selectbox("【層級 3】具體故障現象細項", symptom_list)
        else:
            selected_symptom = st.selectbox("【層級 3】具體故障現象細項", ["(查無對應現象)"])

    st.markdown("---")
    beam_k = st.slider("Beam Search 搜尋路徑數 (Top-K)", min_value=1, max_value=3, value=2)

    # ----------------------------------------------------
    # 智能推論引擎 (GQL 嚴格語法相容)
    # ----------------------------------------------------
    if st.button("🚀 開始智能診斷"):
        if not selected_symptom or "(查無" in selected_symptom:
            st.warning("請先選擇有效的具體故障現象！")
        else:
            with st.spinner("知識圖譜推論中..."):
                query = """
                MATCH (d:DeviceType {name: \$device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus {name: $sound})-[:HAS_SYMPTOM]->(s:Symptom {name:$symptom})-[cb:CAUSED_BY]->(rc:RootCause)-[:RESOLVED_BY]->(act:Action)
                OPTIONAL MATCH (rc)-[:LOCATED_IN]->(comp:Component)
                OPTIONAL MATCH (act)-[:REQUIRES]->(tool:Tool)
                WITH rc, cb, comp, act, collect(DISTINCT tool.name) AS tools
                RETURN
                    rc.name AS 原因,
                    coalesce(cb.prob, 0.0) AS 機率,
                    coalesce(comp.location, '現場設備端') AS 位置,
                    act.name AS 維修步驟,
                    coalesce(act.est_time_min, 15) AS 耗時_分鐘,
                    tools AS 所需工具
                ORDER BY 機率 DESC
                LIMIT toInteger(\$k)
                """
                with driver.session() as session:
                    paths = [r.data() for r in session.run(
                        query, 
                        device=selected_device, 
                        sound=selected_sound, 
                        symptom=selected_symptom, 
                        k=int(beam_k)
                    )]

                st.session_state["current_paths"] = paths
                st.session_state["symptom"] = selected_symptom
                st.session_state["device"] = selected_device
                st.session_state["sound"] = selected_sound

            if paths:
                st.success(f"🎯 針對【{selected_device} ➔ {selected_sound}】推論完成！推薦前 {len(paths)} 項最優先排查方案：")
                for idx, p in enumerate(paths, 1):
                    prob_pct = round(p['機率'] * 100, 1)
                    tools_str = ', '.join(p['所需工具']) if p['所需工具'] else '通用檢修工具'
                    
                    with st.container():
                        st.markdown(f"#### 優先序 #{idx}：【{p['原因']}】 (先驗機率: `{prob_pct}%`)")
                        col_m1, col_m2, col_m3 = st.columns(3)
                        col_m1.metric("📍 檢查位置", p['位置'])
                        col_m2.metric("⏱️ 預估耗時", f"{p['耗時_分鐘']} 分鐘")
                        col_m3.metric("🔧 必備工具", tools_str)
                        st.info(f"👉 **建議處置作為**：{p['維修步驟']}")
                        st.markdown("---")
            else:
                st.warning("該故障現象目前尚無關聯的推論路徑。")

    # ----------------------------------------------------
    # 現場回報區 (結合工單日期與模型線上演進)
    # ----------------------------------------------------
    if "current_paths" in st.session_state and st.session_state["current_paths"]:
        st.subheader("🛠️ 現場維修結果反饋")
        
        repair_date = st.date_input("📅 施工/維修日期", help="記錄本次工單完工日期，供模型學習演進曲線分析")
        
        options = [p["原因"] for p in st.session_state["current_paths"]] + ["以上皆非（提報現場新處置方案）"]
        chosen = st.radio("請勾選實際解決問題的原因：", options)

        if chosen == "以上皆非（提報現場新處置方案）":
            new_cause = st.text_input("輸入實際發現的故障原因")
            new_action = st.text_input("輸入採取的具體處置對策")
            if st.button("📩 提交至審核暫存庫"):
                if new_cause and new_action:
                    c_query = """
                    MATCH (s:Symptom {name: \$symptom})
                    CREATE (fb:PendingFeedback {
                        device: \$device,
                        sound: \$sound,
                        symptom: \$symptom,
                        custom_cause: \$cause,
                        custom_action: \$action,
                        repair_date: toString(\$repair_date),
                        created_at: datetime(),
                        status: 'PENDING_REVIEW'
                    })
                    CREATE (s)-[:HAS_PENDING_FEEDBACK]->(fb)
                    """
                    with driver.session() as s:
                        s.run(c_query, device=st.session_state["device"], sound=st.session_state["sound"], symptom=st.session_state["symptom"], cause=new_cause, action=new_action, repair_date=repair_date)
                    st.success(f"已記錄施工日期（{repair_date}）並送出新方案至待審核暫存庫！")
                else:
                    st.warning("請填寫完整原因與處置對策。")
        else:
            if st.button("✅ 確認回報並更新機率"):
                top1_cause = st.session_state["current_paths"][0]["原因"] if st.session_state["current_paths"] else ""
                is_hit_top1 = 1 if chosen == top1_cause else 0

                u_query = """
                MATCH (s:Symptom {name: $symptom})-[target:CAUSED_BY]->(rc:RootCause {name:$cause})
                CREATE (mo:MaintenanceOrder {
                    repair_date: toString(\$repair_date),
                    symptom: \$symptom,
                    actual_cause: \$cause,
                    is_top1_hit: \$is_hit_top1,
                    created_at: datetime()
                })
                CREATE (s)-[:LOGGED_IN]->(mo)
                SET target.count = coalesce(target.count, 0) + 1
                WITH s
                MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
                WITH s, sum(all_rel.count) AS total, collect(all_rel) AS list
                UNWIND list AS r
                SET r.prob = round((toFloat(r.count) / toFloat(total)) * 10000.0) / 10000.0
                """
                with driver.session() as s:
                    s.run(u_query, symptom=st.session_state["symptom"], cause=chosen, repair_date=repair_date, is_hit_top1=is_hit_top1)
                st.success(f"已記錄工單（{repair_date}）！原因「{chosen}」次數增加，馬可夫轉移機率已動態重新平衡。")

# ──────────────────────────────────────────
# 分頁 2: 管理員專屬後台 (需驗證權限)
# ──────────────────────────────────────────
with tab_admin:
    st.subheader("🛡️ 管理員權限驗證")
    admin_pwd = st.text_input("請輸入管理員密碼以解鎖維修資料庫編輯權限", type="password")

    if admin_pwd == ADMIN_PASSWORD:
        st.success("🔓 管理員身分已驗證，已解鎖資料庫管理權限。")
        
        adm_subtab1, adm_subtab2, adm_subtab3 = st.tabs([
            "📝 維修處置與 SOP 編輯", 
            "📥 待審核技師回報 (PendingFeedback)",
            "⚠️ 統計次數重置 (危險操作)"
        ])

        # ----------------------------------------------------
        # 子功能 1: 視覺化維修方法編輯管理
        # ----------------------------------------------------
        with adm_subtab1:
            st.markdown("### 🛠️ 編輯現有維修處置 (Action)")

            act_query = """
            MATCH (d:DeviceType)-[:HAS_AUDIO_STATE]->(ss:SoundStatus)-[:HAS_SYMPTOM]->(s:Symptom)-[:CAUSED_BY]->(rc:RootCause)-[:RESOLVED_BY]->(act:Action)
            OPTIONAL MATCH (act)-[:REQUIRES]->(t:Tool)
            RETURN act.name AS action_name, act.est_time_min AS time_min, rc.name AS root_cause, d.name AS device, ss.name AS sound, collect(DISTINCT t.name) AS tools
            ORDER BY d.name, act.name
            """
            with driver.session() as s:
