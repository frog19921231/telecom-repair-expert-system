import streamlit as st
from neo4j import GraphDatabase

# 1. 系統連線設定 (優先讀取 Secrets，若無則使用 AuraDB 預設參數)
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
# 分頁 1: 現場診斷與回報 (三階選單)
# ──────────────────────────────────────────
with tab_user:
    st.subheader("現場故障診斷")

    # 1. 取得設備類型 (第一層)
    device_types = []
    try:
        with driver.session() as session:
            dt_res = session.run("MATCH (d:DeviceType) RETURN d.name AS name ORDER BY d.name")
            device_types = [r["name"] for r in dt_res]
    except Exception:
        device_types = ["類比話機 (傳統單機/POTS)", "數位/總機專用話機 (Keyphone/KTS)"]

    c1, c2, c3 = st.columns(3)
    
    with c1:
        selected_device = st.radio("【層級 1】話機設備類型", device_types)

    # 2. 依設備類型連動取得聲響狀態 (第二層)
    sound_status_list = []
    try:
        with driver.session() as session:
            ss_res = session.run(
                """
                MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus)
                RETURN ss.name AS name ORDER BY ss.name
                """,
                device=selected_device
            )
            sound_status_list = [r["name"] for r in ss_res]
    except Exception:
        sound_status_list = []

    with c2:
        selected_sound = st.radio("【層級 2】聲響基本狀態", sound_status_list if sound_status_list else ["無狀態"])

    # 3. 依聲響狀態連動取得具體故障現象 (第三層)
    symptom_list = []
    try:
        with driver.session() as session:
            s_res = session.run(
                """
                MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus {name:$sound})-[:HAS_SYMPTOM]->(s:Symptom)
                RETURN s.name AS name ORDER BY s.name
                """,
                device=selected_device,
                sound=selected_sound
            )
            symptom_list = [r["name"] for r in s_res]
    except Exception:
        symptom_list = []

    with c3:
        if symptom_list:
            selected_symptom = st.selectbox("【層級 3】具體故障現象細項", symptom_list)
        else:
            selected_symptom = st.selectbox("【層級 3】具體故障現象細項", ["(查無對應現象)"])

    beam_k = st.slider("Beam Search 搜尋路徑數 (Top-K)", min_value=1, max_value=3, value=2)

    if st.button("🚀 開始智能診斷"):
        if not selected_symptom or "(查無" in selected_symptom:
            st.warning("請先選擇有效的具體故障現象！")
        else:
            with st.spinner("知識圖譜推論中..."):
                query = """
                MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus {name: $sound})-[:HAS_SYMPTOM]->(s:Symptom {name:$symptom})-[cb:CAUSED_BY]->(rc:RootCause)-[:RESOLVED_BY]->(act:Action)
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
                    paths = [r.data() for r in session.run(
                        query, device=selected_device, sound=selected_sound, symptom=selected_symptom, k=beam_k
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
                        device: $device,
                        sound: $sound,
                        symptom: $symptom,
                        custom_cause: $cause,
                        custom_action: $action,
                        created_at: datetime(),
                        status: 'PENDING_REVIEW'
                    })
                    CREATE (s)-[:HAS_PENDING_FEEDBACK]->(fb)
                    """
                    with driver.session() as s:
                        s.run(c_query, device=st.session_state["device"], sound=st.session_state["sound"], symptom=st.session_state["symptom"], cause=new_cause, action=new_action)
                    st.success("已送出新方案至待審核暫存庫，請等待管理員核准！")
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
                st.success(f"已記錄！原因「{chosen}」次數增加，機率已重新動態平衡。")

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
        # 子功能 1: 視覺化維修方法編輯管理 (管理員專屬)
        # ----------------------------------------------------
        with adm_subtab1:
            st.markdown("### 🛠️ 編輯現有維修處置 (Action)")

            act_query = """
            MATCH (d:DeviceType)-[:HAS_AUDIO_STATE]->(ss:SoundStatus)-[:HAS_SYMPTOM]->(s:Symptom)-[:CAUSED_BY]->(rc:RootCause)-[:RESOLVED_BY]->(act:Action)
            OPTIONAL MATCH (act)-[:REQUIRES]->(t:Tool)
            RETURN act.name AS action_name, act.est_time_min AS time_min, rc.name AS root_cause, d.name AS device, ss.name AS sound, collect(t.name) AS tools
            ORDER BY d.name, act.name
            """
            with driver.session() as s:
                actions_data = [r.data() for r in s.run(act_query)]

            if actions_data:
                action_display = [f"[{item['device']} | {item['sound']}] {item['action_name']}" for item in actions_data]
                selected_display = st.selectbox("選擇要編輯的維修方法：", action_display)

                idx = action_display.index(selected_display)
                current_act = actions_data[idx]

                st.markdown(f"**設備與狀態**：`{current_act['device']}` ➔ `{current_act['sound']}`")
                st.markdown(f"**關聯故障原因**：`{current_act['root_cause']}`")

                with st.form("edit_action_form"):
                    new_action_text = st.text_input("維修處置名稱 / 步驟說明", value=current_act["action_name"])
                    new_time = st.number_input("預估處理耗時 (分鐘)", min_value=1, max_value=240, value=int(current_act["time_min"] if current_act["time_min"] else 15))
                    new_tools_input = st.text_input("所需工具 (多項請用逗號分隔)", value=", ".join(current_act["tools"]))

                    save_btn = st.form_submit_button("💾 儲存並更新資料庫")

                if save_btn:
                    tools_list = [t.strip() for t in new_tools_input.split(",") if t.strip()]
                    
                    update_cypher = """
                    MATCH (a:Action {name: $old_name})
                    SET a.name = $new_name,
                        a.est_time_min = $new_time
                    WITH a
                    OPTIONAL MATCH (a)-[r:REQUIRES]->(:Tool)
                    DELETE r
                    WITH a
                    UNWIND $tools AS t_name
                    MERGE (t:Tool {name: t_name})
                    MERGE (a)-[:REQUIRES]->(t)
                    """
                    with driver.session() as s:
                        s.run(update_cypher, old_name=current_act["action_name"], new_name=new_action_text, new_time=new_time, tools=tools_list)
                    st.success(f"✅ 維修處置「{new_action_text}」已成功更新！")
                    st.rerun()
            else:
                st.info("目前資料庫中尚無維修處置資料。")

        # ----------------------------------------------------
        # 子功能 2: 待審核回報審核
        # ----------------------------------------------------
        with adm_subtab2:
            st.markdown("### 📥 審核技師提交的全新處置方案")
            p_query = """
            MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback {status: 'PENDING_REVIEW'})
            RETURN id(fb) AS id, coalesce(fb.device, '未指定') AS device, coalesce(fb.sound, '未指定') AS sound, s.name AS symptom, fb.custom_cause AS cause, fb.custom_action AS action, toString(fb.created_at) AS created_at
            """
            with driver.session() as s:
                pending_list = [r.data() for r in s.run(p_query)]

            if not pending_list:
                st.info("目前暫存庫中無待審核項目。")
            else:
                for item in pending_list:
                    col_info, col_ok, col_no = st.columns([4, 1, 1])
                    with col_info:
                        st.write(f"📱 **設備**：`{item['device']}` ｜ 🔊 **聲響**：`{item['sound']}`")
                        st.write(f"📌 **現象**：{item['symptom']}")
                        st.write(f"💡 **新原因**：`{item['cause']}` ｜ **對策**：`{item['action']}`")
                        st.caption(f"時間：{item['created_at']}")
                    with col_ok:
                        if st.button("✅ 核准入庫", key=f"app_{item['id']}"):
                            approve_cypher = """
                            MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback) WHERE id(fb) = $fid
                            SET fb.status = 'APPROVED'
                            MERGE (rc:RootCause {name: fb.custom_cause})
                            MERGE (act:Action {name: fb.custom_action, est_time_min: 20})
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
                    # ----------------------------------------------------
        # 子功能 3: 統計次數重置與機率歸零 (雙重防誤觸)
        # ----------------------------------------------------
        with adm_subtab3:
            st.markdown("### ⚠️ 故障原因統計計數歸零與機率重置")
            st.caption("此操作將清空所有現場技師累積回報的維修次數，並將所有故障原因之先驗機率重置為基準均勻分佈。")

            if "confirm_reset_stage" not in st.session_state:
                st.session_state["confirm_reset_stage"] = False

            if not st.session_state["confirm_reset_stage"]:
                if st.button("🚨 申請重置所有統計數據", type="secondary"):
                    st.session_state["confirm_reset_stage"] = True
                    st.rerun()
            else:
                with st.container():
                    st.error("🚨 **危險操作警告！**")
                    st.write("您即將執行統計數據永久清空。請注意：此操作無法復原，所有已記錄的排查權重將回到初始狀態。")

                    safety_checkbox = st.checkbox("我已充分理解此操作之後果，並確定要將所有統計計數歸零。")

                    col_confirm, col_cancel = st.columns([1, 4])
                    
                    with col_confirm:
                        if st.button("🔥 確認永久歸零", type="primary", disabled=not safety_checkbox):
                            reset_cypher = """
                            MATCH (s:Symptom)-[r:CAUSED_BY]->(rc:RootCause)
                            SET r.count = 1
                            WITH s
                            MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
                            WITH s, sum(all_rel.count) AS total, collect(all_rel) AS list
                            UNWIND list AS r
                            SET r.prob = round((toFloat(r.count) / toFloat(total)) * 10000.0) / 10000.0
                            """
                            with driver.session() as s:
                                s.run(reset_cypher)

                            st.session_state["confirm_reset_stage"] = False
                            st.success("✅ 統計計數已成功全數歸零，先驗機率已重新均勻化！")
                            st.rerun()

                    with col_cancel:
                        if st.button("↩️ 取消操作"):
                            st.session_state["confirm_reset_stage"] = False
                            st.rerun()

    elif admin_pwd != "":
        st.error("❌ 密碼錯誤，拒絕存取維修管理功能。")
    else:
        st.info("🔒 此功能需要管理員權限，請先於上方輸入密碼。")
