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

# ----------------------------------------------------
# 現場回報區 (加入施工日期以利模型時間序列評估)
# ----------------------------------------------------
    if "current_paths" in st.session_state and st.session_state["current_paths"]:
        st.subheader("🛠️ 現場維修結果反饋")
        
        # 1. 新增：施工日期選擇器 (預設為今日)
        repair_date = st.date_input("📅 施工/維修日期", help="記錄本次工單完工日期，供模型學習演進曲線分析")
        
        options = [p["原因"] for p in st.session_state["current_paths"]] + ["以上皆非（提報現場新處置方案）"]
        chosen = st.radio("請勾選實際解決問題的原因：", options)

        # 情境 A: 提報現場新處置方案 (以上皆非)
        if chosen == "以上皆非（提報現場新處置方案）":
            new_cause = st.text_input("輸入實際發現的故障原因")
            new_action = st.text_input("輸入採取的具體處置對策")
            if st.button("📩 提交至審核暫存庫"):
                if new_cause and new_action:
                    c_query = """
                    MATCH (s:Symptom {name: $symptom})
                    CREATE (fb:PendingFeedback {
                        device: $device,
                        sound: $sound,
                        symptom: $symptom,
                        custom_cause: $cause,
                        custom_action: $action,
                        repair_date: toString($repair_date),
                        created_at: datetime(),
                        status: 'PENDING_REVIEW'
                    })
                    CREATE (s)-[:HAS_PENDING_FEEDBACK]->(fb)
                    """
                    with driver.session() as s:
                        s.run(
                            c_query, 
                            device=st.session_state["device"], 
                            sound=st.session_state["sound"], 
                            symptom=st.session_state["symptom"], 
                            cause=new_cause, 
                            action=new_action,
                            repair_date=repair_date
                        )
                    st.success(f"已記錄施工日期（{repair_date}）並送出新方案至待審核暫存庫！")
                else:
                    st.warning("請填寫完整原因與處置對策。")

        # 情境 B: 現有選項命中 (更新馬可夫轉移機率 + 建立歷史工單記錄)
        else:
            if st.button("✅ 確認回報並更新機率"):
                # 判斷系統前次推薦是否命中 (Top-1 命中評估)
                top1_cause = st.session_state["current_paths"][0]["原因"] if st.session_state["current_paths"] else ""
                is_hit_top1 = 1 if chosen == top1_cause else 0

                u_query = """
                MATCH (s:Symptom {name: $symptom})-[target:CAUSED_BY]->(rc:RootCause {name: $cause})
                
                // 1. 建立獨立工單實體，保存施工日期與當次預測結果
                CREATE (mo:MaintenanceOrder {
                    repair_date: toString($repair_date),
                    symptom: $symptom,
                    actual_cause: $cause,
                    is_top1_hit: $is_hit_top1,
                    created_at: datetime()
                })
                CREATE (s)-[:LOGGED_IN]->(mo)
                
                // 2. 更新馬可夫狀態轉移次數
                SET target.count = coalesce(target.count, 0) + 1
                WITH s
                MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
                WITH s, sum(all_rel.count) AS total, collect(all_rel) AS list
                UNWIND list AS r
                SET r.prob = round((toFloat(r.count) / toFloat(total)) * 10000.0) / 10000.0
                """
                with driver.session() as s:
                    s.run(
                        u_query, 
                        symptom=st.session_state["symptom"], 
                        cause=chosen,
                        repair_date=repair_date,
                        is_hit_top1=is_hit_top1
                    )
                st.success(f"✅ 工單記錄完成（施工日期：{repair_date}）！原因「{chosen}」計數已增加，馬可夫轉移機率已動態重新平衡。")

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
