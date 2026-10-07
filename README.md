import streamlit as st
from neo4j import GraphDatabase

# 1. 系統連線設定 (優先讀取 Secrets，若無則使用預設 AuraDB 連線)
NEO4J_URI = st.secrets.get("NEO4J_URI", "neo4j+ssc://b8cec18b.databases.neo4j.io")
NEO4J_USER = st.secrets.get("NEO4J_USER", "b8cec18b")
NEO4J_PASSWORD = st.secrets.get("NEO4J_PASSWORD", "P9wY81fDEc8bT67wCIq6Z329QOhjh-HIcyzqrqDJ_TA")
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
    MATCH (s:Symptom)-[r:CAUSED_BY]->(rc:RootCause)
    RETURN s.name AS 現象, rc.name AS 原因, coalesce(r.count, 0) AS 次數, round(coalesce(r.prob, 0.0) * 100, 1) AS `機率(%)`
    ORDER BY 次數 DESC
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
tab_user, tab_admin = st.tabs(["🔧 現場診斷與反饋", "🛡️ 管理員審核後台"])

# ──────────────────────────────────────────
# 分頁 1: 現場診斷與回報
# ──────────────────────────────────────────
with tab_user:
    st.subheader("現場故障診斷")

    symptom_list = []
    try:
        with driver.session() as session:
            s_res = session.run("MATCH (s:Symptom) RETURN s.name AS name")
            symptom_list = [r["name"] for r in s_res]
    except Exception:
        symptom_list = ["拿起聽筒完全無撥號音(無聲)", "通話雜音或串音"]

    selected_symptom = st.selectbox("選擇標準故障現象", symptom_list)
    beam_k = st.slider("Beam Search 搜尋路徑數 (Top-K)", min_value=1, max_value=3, value=2)

    if st.button("🚀 開始智能診斷"):
        with st.spinner("知識圖譜推論中..."):
            query = """
            MATCH (s:Symptom {name: $symptom})-[cb:CAUSED_BY]->(rc:RootCause)-[:RESOLVED_BY]->(act:Action)
            MATCH (rc)-[:LOCATED_IN]->(comp:Component)
            OPTIONAL MATCH (act)-[:REQUIRES]->(tool:Tool)
            RETURN
                rc.name AS 原因,
                cb.prob AS 機率,
                comp.location AS 位置,
                act.name AS 維修步驟,
                act.est_time_min AS 耗時_分鐘,
                collect(tool.name) AS 所需工具
            ORDER BY cb.prob DESC
            LIMIT $k
            """
            with driver.session() as session:
                paths = [r.data() for r in session.run(query, symptom=selected_symptom, k=beam_k)]

            st.session_state["current_paths"] = paths
            st.session_state["symptom"] = selected_symptom

        if paths:
            st.success(f"🎯 圖推論完成！推薦前 {len(paths)} 項最優先排查方案：")
            for idx, p in enumerate(paths, 1):
                prob_pct = round(p['機率'] * 100, 1)
                tools_str = ', '.join(p['所需工具']) if p['所需工具'] else '通用檢修工具'
                
                with st.container():
                    st.markdown(f"#### 優先序 #{idx}：【{p['原因']}】 (先驗機率: `{prob_pct}%`)")
                    c1, c2, c3 = st.columns(3)
                    c1.metric("📍 檢查位置", p['位置'])
                    c2.metric("⏱️ 預估耗時", f"{p['耗時_分鐘']} 分鐘")
                    c3.metric("🔧 必備工具", tools_str)
                    st.info(f"👉 **建議處置作為**：{p['維修步驟']}")
                    st.markdown("---")

    # 現場回報區
    if "current_paths" in st.session_state and st.session_state["current_paths"]:
        st.subheader("🛠️ 現場維修結果反饋")
        options = [p["原因"] for p in st.session_state["current_paths"]] + ["以上皆非（提報現場新處置方案）"]
        chosen = st.radio("請勾選實際解決問題的原因：", options)

        if chosen == "以上皆非（提報現場新處置方案）":
            new_cause = st.text_input("輸入實際發現的故障原因")
            new_action = st.text_input("輸入採取的具體處置對策")
            if st.button("📩 提交至審核暫存庫"):
                if new_cause and new_action:
                    c_query = """
                    MATCH (s:Symptom {name: $symptom})
                    CREATE (fb:PendingFeedback {
                        symptom: $symptom,
                        custom_cause: $cause,
                        custom_action: $action,
                        created_at: datetime(),
                        status: 'PENDING_REVIEW'
                    })
                    CREATE (s)-[:HAS_PENDING_FEEDBACK]->(fb)
                    """
                    with driver.session() as s:
                        s.run(c_query, symptom=st.session_state["symptom"], cause=new_cause, action=new_action)
                    st.success("已送出新方案至待審核暫存庫！")
                else:
                    st.warning("請填寫完整原因與處置對策。")
        else:
            if st.button("✅ 確認回報並更新機率"):
                u_query = """
                MATCH (s:Symptom {name: $symptom})-[target:CAUSED_BY]->(rc:RootCause {name:$cause})
                SET target.count = coalesce(target.count, 0) + 1
                WITH s
                MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
                WITH s, sum(all_rel.count) AS total, collect(all_rel) AS list
                UNWIND list AS r
                SET r.prob = round((toFloat(r.count) / toFloat(total)) * 10000.0) / 10000.0
                """
                with driver.session() as s:
                    s.run(u_query, symptom=st.session_state["symptom"], cause=chosen)
                st.success(f"已記錄！原因「{chosen}」次數增加，機率已重新平衡計算。")

# ──────────────────────────────────────────
# 分頁 2: 管理員審核後台
# ──────────────────────────────────────────
with tab_admin:
    st.subheader("🛡️ 待審核現場回報 (PendingFeedback)")
    admin_pwd = st.text_input("請輸入管理員密碼", type="password")

    if admin_pwd == ADMIN_PASSWORD:
        st.success("管理員身分已驗證。")
        p_query = """
        MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback {status: 'PENDING_REVIEW'})
        RETURN id(fb) AS id, s.name AS symptom, fb.custom_cause AS cause, fb.custom_action AS action, toString(fb.created_at) AS created_at
        """
        with driver.session() as s:
            pending_list = [r.data() for r in s.run(p_query)]

        if not pending_list:
            st.info("目前暫存庫中無待審核項目。")
        else:
            for item in pending_list:
                col_info, col_ok, col_no = st.columns([4, 1, 1])
                with col_info:
                    st.write(f"📌 **現象**：{item['symptom']}")
                    st.write(f"💡 **新原因**：`{item['cause']}` ｜ **對策**：`{item['action']}`")
                    st.caption(f"時間：{item['created_at']}")
                with col_ok:
                    if st.button("✅ 核准入庫", key=f"app_{item['id']}"):
                        approve_cypher = """
                        MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback) WHERE id(fb) = $fid
                        SET fb.status = 'APPROVED'
                        MERGE (rc:RootCause {name: fb.custom_cause})
                        MERGE (act:Action {name: fb.custom_action})
                        MERGE (rc)-[:RESOLVED_BY]->(act)
                        MERGE (s)-[r:CAUSED_BY]->(rc)
                        ON CREATE SET r.count = 1
                        ON MATCH SET r.count = coalesce(r.count, 0) + 1
                        WITH s
                        MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
                        WITH s, sum(all_rel.count) AS total, collect(all_rel) AS list
                        UNWIND list AS r
                        SET r.prob = round((toFloat(r.count) / toFloat(total)) * 10000.0) / 10000.0
                        """
                        with driver.session() as s:
                            s.run(approve_cypher, fid=item['id'])
                        st.success("已核准！正式建立節點並重平衡機率。")
                        st.rerun()
                with col_no:
                    if st.button("❌ 駁回", key=f"rej_{item['id']}"):
                        with driver.session() as s:
                            s.run("MATCH (fb:PendingFeedback) WHERE id(fb) = $fid SET fb.status = 'REJECTED'", fid=item['id'])
                        st.warning("已駁回。")
                        st.rerun()
                st.markdown("---")
    elif admin_pwd != "":
        st.error("密碼錯誤，拒絕存取。")
