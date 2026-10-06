import json
import requests
import streamlit as st
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "repair2026")
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"

st.set_page_config(page_title="通訊設備智能維修專家系統", page_icon="📞", layout="wide")

@st.cache_resource
def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

driver = get_driver()

def get_known_symptoms():
    query = "MATCH (s:Symptom) RETURN s.name AS symptom"
    with driver.session() as session:
        result = session.run(query)
        return [r["symptom"] for r in result]

def beam_search(symptom_name: str, beam_width: int = 2):
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
        result = session.run(query, symptom=symptom_name, k=beam_width)
        return [record.data() for record in result]

def generate_instruction(symptom: str, paths: list):
    context_str = json.dumps(paths, ensure_ascii=False, indent=2)
    prompt = f"""你是一名電話設備維修工程師。
現場反映：「{symptom}」
推論引擎推薦路徑：{context_str}

請產生一份條理分明的維修指導（包含原因機率、地點步驟、工具與預估時間）："""

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.0}
    }
    try:
        res = requests.post(OLLAMA_URL, json=payload, timeout=60)
        return res.json().get("response", "報告生成失敗")
    except Exception as e:
        return f"Ollama 連線異常: {e}"

def submit_feedback(symptom: str, confirmed_cause: str):
    cypher = """
    MATCH (s:Symptom {name: $symptom})-[target:CAUSED_BY]->(rc:RootCause {name: $cause})
    SET target.count = coalesce(target.count, 0) + 1

    WITH s
    MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
    WITH s, sum(all_rel.count) AS total_count, collect(all_rel) AS rel_list

    UNWIND rel_list AS r
    SET r.prob = round(toFloat(r.count) / toFloat(total_count), 4)

    RETURN endNode(r).name AS 原因, r.count AS 次數, r.prob AS 新機率
    ORDER BY r.prob DESC;
    """
    with driver.session() as session:
        result = session.run(cypher, symptom=symptom, cause=confirmed_cause)
        return [r.data() for r in result]

st.title("📞 通訊設備智能維修專家系統 (Neuro-Symbolic Web App)")
st.markdown("結合 **Neo4j 知識圖譜**、**馬可夫鏈狀態轉移** 與 **本機 Ollama (Qwen 2.5)** 的動態排障平台。")

known_symptoms = get_known_symptoms()

with st.sidebar:
    st.header("⚙️ 系統狀態")
    st.success("Neo4j 連線正常")
    beam_k = st.slider("Beam Search 搜尋寬度 (K)", min_value=1, max_value=4, value=2)

col1, col2 = st.columns([2, 1])
with col1:
    selected_symptom = st.selectbox("選擇標準故障現象：", known_symptoms)
with col2:
    st.write("")
    st.write("")
    diagnose_btn = st.button("🚀 開始智能診斷", type="primary")

if diagnose_btn:
    with st.spinner("知識圖譜 Beam Search 剪枝推論中..."):
        paths = beam_search(selected_symptom, beam_width=beam_k)
        st.session_state["diagnosis_paths"] = paths
        st.session_state["current_symptom"] = selected_symptom
    
    with st.spinner("Ollama 正在編寫排障手冊..."):
        report = generate_instruction(selected_symptom, paths)
        st.session_state["diagnosis_report"] = report

if "diagnosis_paths" in st.session_state:
    st.markdown("---")
    res_col1, res_col2 = st.columns([1, 1])

    with res_col1:
        st.subheader("📊 馬可夫推論路徑 (Top-K)")
        for idx, item in enumerate(st.session_state["diagnosis_paths"], 1):
            with st.expander(f"優先序 #{idx}: {item['原因']} (機率: {item['機率'] * 100:.1f}%)", expanded=True):
                st.write(f"📍 **維修位置**：{item['位置']}")
                st.write(f"⏱️️ **預估耗時**：{item['耗時_分鐘']} 分鐘")
                st.write(f"🔧 **所需工具**：{', '.join(item['所需工具']) if item['所需工具'] else '一般工具'}")
                st.write(f"📝 **處置工序**：{item['維修步驟']}")

    with res_col2:
        st.subheader("🤖 Ollama 繁中維修指導書")
        st.info(st.session_state["diagnosis_report"])

    st.markdown("---")
    st.subheader("🛠️ 現場維修反饋 (即時更新馬可夫機率)")

    base_causes = [p["原因"] for p in st.session_state["diagnosis_paths"]]
    feedback_options = base_causes + ["以上皆非（提報現場新處置方案）"]

    selected_cause = st.radio(
        "請確認最終修復該故障的實際原因：",
        feedback_options,
        index=0
    )

    if selected_cause in base_causes:
        if st.button("✅ 確認回報並更新機率", type="primary"):
            updated_data = submit_feedback(st.session_state["current_symptom"], selected_cause)
            st.success(f"反饋成功！已將『{selected_cause}』累加工單計數，並自動重新正規化轉移機率。")
            st.dataframe(updated_data)
    else:
        st.info("💡 偵測到新故障情境！請記錄現場實際處置措施，系統將暫存入審核池，審核通過後即納入知識庫。")
        with st.form("custom_feedback_form"):
            col_c, col_a = st.columns(2)
            with col_c:
                new_cause = st.text_input("實際故障根本原因 (例: 電話機變壓器燒毀)")
            with col_a:
                new_action = st.text_input("實際採取的處置措施 (例: 更換專用電源適配器)")
            
            submit_new = st.form_submit_button("📩 提交新維修方案至暫存庫")
            
            if submit_new:
                if not new_cause.strip():
                    st.warning("請填寫實際故障根本原因！")
                else:
                    cypher_staging = """
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
                    with driver.session() as session:
                        session.run(
                            cypher_staging, 
                            symptom=st.session_state["current_symptom"],
                            cause=new_cause.strip(),
                            action=new_action.strip() if new_action.strip() else "一般線路檢修"
                        )
                    st.success("🎉 已成功將新排障知識提報至暫存審核池！管理員審核後將正式連線至知識圖譜。")
