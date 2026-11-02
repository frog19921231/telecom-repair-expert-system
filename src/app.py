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
# 分頁 1: 現場診斷與回報 (分步導引式精靈)
# ──────────────────────────────────────────
with tab_user:
    # 1. 初始化步驟狀態與共用變數
    if "step" not in st.session_state:
        st.session_state["step"] = 1
    if "saved_tech" not in st.session_state:
        st.session_state["saved_tech"] = ""

    # 頂部顯示當前排查進度條
    steps_label = ["1. 現象選取", "2. 智能診斷", "3. 完工結案"]
    st.progress(st.session_state["step"] / 3.0)
    st.caption(f"📍 目前進度：步驟 {st.session_state['step']} / 3 —— **{steps_label[st.session_state['step'] - 1]}**")
    st.markdown("---")

    # ====================================================
    # 步驟 1: 話機設備與具體現象選擇
    # ====================================================
    if st.session_state["step"] == 1:
        st.subheader("【步驟 1】請選擇話機規格與具體故障特徵")

        c1, c2, c3 = st.columns(3)
        with c1:
            device_types = []
            try:
                with driver.session() as session:
                    dt_res = session.run("MATCH (d:DeviceType) RETURN DISTINCT d.name AS name ORDER BY d.name")
                    device_types = [r["name"] for r in dt_res]
            except Exception:
                device_types = ["類比話機 (傳統單機/POTS)", "AVAYA 數位話機 (1400/2400系列)", "AVAYA IP話機 (9600/J系列)"]

            selected_device = st.selectbox("【層級 1】話機設備類型：", device_types)

        with c2:
            sound_status_list = []
            try:
                with driver.session() as session:
                    ss_res = session.run(
                        "MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus) RETURN DISTINCT ss.name AS name ORDER BY ss.name",
                        device=selected_device
                    )
                    sound_status_list = [r["name"] for r in ss_res]
            except Exception:
                sound_status_list = []

            selected_sound = st.radio("【層級 2】聲響基本狀態：", sound_status_list if sound_status_list else ["無狀態"])

        with c3:
            symptom_list = []
            try:
                with driver.session() as session:
                    s_res = session.run(
                        "MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus {name:$sound})-[:HAS_SYMPTOM]->(s:Symptom) RETURN DISTINCT s.name AS name ORDER BY s.name",
                        device=selected_device,
                        sound=selected_sound
                    )
                    symptom_list = [r["name"] for r in s_res]
            except Exception:
                symptom_list = []

            selected_symptom = st.selectbox("【層級 3】具體故障現象細項：", symptom_list if symptom_list else ["(查無對應現象)"])

        st.markdown("---")
        beam_k = st.slider("Beam Search 搜尋路徑數 (Top-K)：", min_value=1, max_value=3, value=2)

        if st.button("🚀 下一步：進行知識圖譜推論 ➔", type="primary"):
            if not selected_symptom or "(查無" in selected_symptom:
                st.warning("⚠️ 請先選擇有效的具體故障現象！")
            else:
                with st.spinner("知識圖譜推論中..."):
                    query = """
                    MATCH (d:DeviceType {name: $device})-[:HAS_AUDIO_STATE]->(ss:SoundStatus {name: $sound})-[:HAS_SYMPTOM]->(s:Symptom {name: $symptom})-[cb:CAUSED_BY]->(rc:RootCause)-[:RESOLVED_BY]->(act:Action)
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
                    LIMIT toInteger($k)
                    """
                    with driver.session() as session:
                        paths = [r.data() for r in session.run(
                            query, device=selected_device, sound=selected_sound, symptom=selected_symptom, k=int(beam_k)
                        )]

                    if paths:
                        st.session_state["current_paths"] = paths
                        st.session_state["device"] = selected_device
                        st.session_state["sound"] = selected_sound
                        st.session_state["symptom"] = selected_symptom
                        st.session_state["step"] = 2
                        st.rerun()
                    else:
                        st.error("該故障現象目前尚無關聯的推論路徑，請確認知識圖譜關聯。")

    # ====================================================
    # 步驟 2: 方案推薦與現場排查指南
    # ====================================================
    elif st.session_state["step"] == 2:
        st.subheader("【步驟 2】知識圖譜推論結果與 SOP 排查建議")
        st.info(f"當前診斷對象：`{st.session_state['device']}` ➔ `{st.session_state['sound']}` ➔ **{st.session_state['symptom']}**")

        paths = st.session_state["current_paths"]
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

        col_prev, col_next = st.columns([1, 4])
        with col_prev:
            if st.button("⬅️ 返回重選現象"):
                st.session_state["step"] = 1
                st.rerun()
        with col_next:
            if st.button("🛠️ 現場已處置完畢，前往工單結案回報 ➔", type="primary"):
                st.session_state["step"] = 3
                st.rerun()

    # ====================================================
    # 步驟 3: 施工資訊確認與工單寫入 (結案)
    # ====================================================
    elif st.session_state["step"] == 3:
        st.subheader("【步驟 3】現場完工確認與自適應工單回報")
        paths = st.session_state["current_paths"]

        col_fb1, col_fb2 = st.columns(2)
        with col_fb1:
            tech_val = st.text_input(
                "👷 施工人員：",
                value=st.session_state["saved_tech"],
                placeholder="請輸入技師姓名/工號 (例: 王小明 / T1082)",
                key="step3_tech_input"
            )
            st.session_state["saved_tech"] = tech_val.strip()
        with col_fb2:
            repair_date = st.date_input("📅 施工/維修日期")

        # 彙整工具清單供勾選
        all_tools = set()
        for p in paths:
            if p.get("所需工具"):
                all_tools.update(p["所需工具"])
        tool_options = list(all_tools) if all_tools else ["網路壓線鉗", "RJ45水晶頭", "網路測線儀", "三用電表"]

        selected_tools = st.multiselect("🔧 本次實際使用之必備工具：", options=tool_options, default=tool_options[:2] if len(tool_options) >= 2 else tool_options)

        # 格式化真因單選清單
        raw_causes = [p["原因"] for p in paths]
        display_options = [f"優先序 #{idx}：【{p['原因']}】 (先驗機率: {round(p['機率']*100, 1)}%)" for idx, p in enumerate(paths, 1)]
        display_options.append("❓ 以上皆非（提報現場新處置方案）")

        selected_choice = st.radio("請勾選實際解決問題的真因：", display_options)

        # 情境 A: 提報全新處置
        if selected_choice == "❓ 以上皆非（提報現場新處置方案）":
            new_cause = st.text_input("輸入實際發現的故障原因")
            new_action = st.text_input("輸入採取的具體處置對策")
            if st.button("📩 提交至審核暫存庫並結束工單", type="primary"):
                if not st.session_state["saved_tech"]:
                    st.warning("⚠️ 請填寫施工人員姓名！")
                elif new_cause and new_action:
                    c_query = """
                    MATCH (s:Symptom {name: $symptom})
                    CREATE (fb:PendingFeedback {
                        device: $device, sound: $sound, symptom: $symptom,
                        custom_cause: $cause, custom_action: $action,
                        technician: $technician, tools: $tools,
                        repair_date: toString($repair_date),
                        created_at: datetime(), status: 'PENDING_REVIEW'
                    })
                    CREATE (s)-[:HAS_PENDING_FEEDBACK]->(fb)
                    """
                    with driver.session() as s:
                        s.run(c_query, device=st.session_state["device"], sound=st.session_state["sound"], symptom=st.session_state["symptom"], cause=new_cause, action=new_action, technician=st.session_state["saved_tech"], tools=selected_tools, repair_date=repair_date)
                    st.success("✅ 已成功送審並結案！")
                    # 重置狀態回到步驟 1
                    st.session_state["saved_tech"] = ""
                    st.session_state["step"] = 1
                    st.rerun()
                else:
                    st.warning("請填寫完整原因與處置對策。")
        # 情境 B: 現有選項命中結案
        else:
            chosen_cause_idx = display_options.index(selected_choice)
            chosen_cause = raw_causes[chosen_cause_idx]

            col_p3, col_sub = st.columns([1, 4])
            with col_p3:
                if st.button("⬅️ 返回查看 SOP"):
                    st.session_state["step"] = 2
                    st.rerun()
            with col_sub:
                if st.button("🎉 確認完工並更新模型機率", type="primary"):
                    if not st.session_state["saved_tech"]:
                        st.warning("⚠️ 請先填寫施工人員姓名後再點擊結案！")
                    else:
                        is_hit_top1 = 1 if chosen_cause_idx == 0 else 0
                        u_query = """
                        MATCH (s:Symptom {name: $symptom})-[target:CAUSED_BY]->(rc:RootCause {name: $cause})
                        CREATE (mo:MaintenanceOrder {
                            repair_date: toString($repair_date),
                            technician: $technician,
                            symptom: $symptom,
                            actual_cause: $cause,
                            is_top1_hit: $is_hit_top1,
                            tools: $tools,
                            created_at: datetime()
                        })
                        CREATE (s)-[:LOGGED_IN]->(mo)
                        MERGE (tech:Technician {name: $technician})
                        MERGE (tech)-[:HANDLED]->(mo)
                        FOREACH (t_name IN $tools |
                            MERGE (t:Tool {name: t_name})
                            MERGE (mo)-[:USED_TOOL]->(t)
                        )
                        SET target.count = coalesce(target.count, 0) + 1
                        WITH s
                        MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
                        WITH s, sum(all_rel.count) AS total, collect(all_rel) AS list
                        UNWIND list AS r
                        SET r.prob = round((toFloat(r.count) / toFloat(total)) * 10000.0) / 10000.0
                        """
                        with driver.session() as s:
                            s.run(u_query, symptom=st.session_state["symptom"], cause=chosen_cause, technician=st.session_state["saved_tech"], repair_date=repair_date, is_hit_top1=is_hit_top1, tools=selected_tools)

                        # 清空人員並將精靈指針重設回 Step 1
                        st.session_state["saved_tech"] = ""
                        st.session_state["step"] = 1
                        st.toast(f"🎉 工單已成功結案！轉移機率已動態更新。", icon="✅")
                        st.rerun()

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

                st.markdown("---")
                st.markdown("#### 🗑️ 刪除此項維修處置")
                st.caption("注意：刪除後將移除該 Action 節點及其與工具、故障原因的關聯。")

                del_confirm = st.checkbox(
                    f"⚠️ 確認永久刪除處置【{current_act['action_name']}】？",
                    key=f"del_chk_{current_act['action_name']}"
                )

                if st.button("🗑️ 執行刪除此處置", type="primary", disabled=not del_confirm):
                    delete_cypher = """
                    MATCH (a:Action {name: $act_name})
                    DETACH DELETE a
                    """
                    with driver.session() as s:
                        s.run(delete_cypher, act_name=current_act["action_name"])
                    st.success(f"已成功從知識圖譜中刪除維修處置：【{current_act['action_name']}】！")
                    st.rerun()
            else:
                st.info("目前資料庫中尚無維修處置資料。")

        # ----------------------------------------------------
        # 子功能 2: 待審核回報審核 (採用 elementId 現代語法)
        # ----------------------------------------------------
        with adm_subtab2:
            st.markdown("### 📥 審核技師提交的全新處置方案")
            p_query = """
            MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback {status: 'PENDING_REVIEW'})
            RETURN elementId(fb) AS id, coalesce(fb.device, '未指定') AS device, coalesce(fb.sound, '未指定') AS sound, s.name AS symptom, fb.custom_cause AS cause, fb.custom_action AS action, toString(fb.created_at) AS created_at
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
                            MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback) WHERE elementId(fb) = $fid
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
                                s.run("MATCH (fb:PendingFeedback) WHERE elementId(fb) = $fid SET fb.status = 'REJECTED'", fid=item['id'])
                            st.warning("已駁回。")
                            st.rerun()
                    st.markdown("---")

        # ----------------------------------------------------
        # 子功能 3: 統計次數重置與機率歸零
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
