import json
import requests
from datetime import datetime
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "repair2026")
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"

class FeedbackEnabledAssistant:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

    def close(self):
        self.driver.close()

    def get_known_symptoms(self):
        query = "MATCH (s:Symptom) RETURN s.name AS symptom"
        with self.driver.session() as session:
            result = session.run(query)
            return [r["symptom"] for r in result]

    def match_symptom(self, user_query: str, known_symptoms: list) -> str:
        symptom_list_str = "\n".join([f"- {s}" for s in known_symptoms])
        prompt = f"""你是一名電話維修分診專家。
操作員描述：「{user_query}」

標準故障現象清單：
{symptom_list_str}

請嚴格判斷使用者描述是否對應上述任一項？
若符合，僅輸出該名稱；若語義太模糊、或完全不在清單內，請直接輸出 NONE。不要有其他廢話。"""

        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0}
        }
        try:
            res = requests.post(OLLAMA_URL, json=payload, timeout=30)
            matched = res.json().get("response", "").strip()
            for s in known_symptoms:
                if s in matched:
                    return s
            return None
        except Exception:
            return None

    # 功能 1：記錄無法辨識的口語（供未來擴充圖譜詞彙庫/同義詞）
    def log_unmatched_query(self, query_text: str):
        cypher = """
        MERGE (u:UnmatchedQuery {query_text: $query})
        ON CREATE SET u.count = 1, u.first_seen = datetime()
        ON MATCH SET u.count = u.count + 1, u.last_seen = datetime()
        RETURN u.count AS frequency;
        """
        with self.driver.session() as session:
            res = session.run(cypher, query=query_text)
            freq = res.single()["frequency"]
            print(f"📝 [系統記錄] 已將未匹配詞彙存入暫存庫（累計出現次數：{freq} 次）。")

    # 功能 2：記錄技師反饋的「新修復建議 / 真正原因」
    def log_custom_feedback(self, symptom: str, new_cause: str, new_action: str):
        cypher = """
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
        with self.driver.session() as session:
            session.run(cypher, symptom=symptom, cause=new_cause, action=new_action)
            print("💡 [已收錄修復建議] 現場回報之新原因已記錄至暫存區，待審核後將納入正式知識圖譜！")

    def beam_search(self, symptom_name: str, beam_width: int = 2):
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
        with self.driver.session() as session:
            result = session.run(query, symptom=symptom_name, k=beam_width)
            return [record.data() for record in result]

    def generate_instruction(self, symptom: str, paths: list):
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
        res = requests.post(OLLAMA_URL, json=payload, timeout=60)
        return res.json().get("response", "報告生成失敗")

    def submit_feedback(self, symptom: str, confirmed_cause: str):
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
        with self.driver.session() as session:
            result = session.run(cypher, symptom=symptom, cause=confirmed_cause)
            print("\n[系統完成學習] 最新機率分布：")
            for r in result:
                print(f"  * {r['原因']}: 累計 {r['次數']} 次 | 新轉移機率: {r['新機率']:.4f}")

def main():
    assistant = FeedbackEnabledAssistant()
    print("==================================================")
    print("   📞 電話維修專家系統 (具備反饋收集與持續學習)   ")
    print("==================================================")

    known_symptoms = assistant.get_known_symptoms()

    while True:
        user_input = input("\n請描述遇到的故障現象 (輸入 q 離開): ").strip()
        if user_input.lower() == 'q':
            break
        if not user_input:
            continue

        print("🔍 正在進行語義分析與症狀匹配...")
        matched_symptom = assistant.match_symptom(user_input, known_symptoms)
        
        # 情況 A：詞彙庫中無此現象 -> 記錄未匹配詞彙，跳出引導
        if not matched_symptom:
            print(f"⚠️ 無法自動識別「{user_input}」。")
            assistant.log_unmatched_query(user_input)
            
            print("\n系統目前已知現象包含：")
            for idx, s in enumerate(known_symptoms, 1):
                print(f" [{idx}] {s}")
            print(f" [{len(known_symptoms) + 1}] 都不是（跳過此查詢）")
            
            sel = input("若上述有符合者，請輸入編號手動選取：").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(known_symptoms):
                matched_symptom = known_symptoms[int(sel) - 1]
            else:
                continue

        print(f"\n✅ 鎖定目標現象：【{matched_symptom}】")
        paths = assistant.beam_search(matched_symptom, beam_width=2)

        print("🤖 生成專用排查指導書...\n")
        report = assistant.generate_instruction(matched_symptom, paths)
        print("------------------- [維修指導] -------------------")
        print(report)
        print("-------------------------------------------------")

        # 現場維修反饋環節
        print("\n🛠️ 排查完成後，請回報最終修復該故障的實際原因：")
        for idx, item in enumerate(paths, 1):
            print(f" [{idx}] {item['原因']}")
        print(f" [{len(paths) + 1}] 其他原因（我想補充新的修復對策）")

        choice = input("請輸入修復編號 (按 Enter 略過反饋): ").strip()
        if choice.isdigit():
            c = int(choice)
            if 1 <= c <= len(paths):
                # 現有節點權重累加
                selected_cause = paths[c - 1]["原因"]
                assistant.submit_feedback(matched_symptom, selected_cause)
            elif c == len(paths) + 1:
                # 情況 B：選「其他」-> 主動引導採集新原因與對策
                print("\n📝 [新修復方案回報]")
                new_cause = input(" 1. 現場確認的真實故障原因為 (例如: 話機變壓器燒毀): ").strip()
                new_action = input(" 2. 最終採取的解決措施為 (例如: 更換12V電源適配器): ").strip()
                if new_cause:
                    assistant.log_custom_feedback(matched_symptom, new_cause, new_action)
        else:
            print("已略過本次反饋。")

    assistant.close()

if __name__ == "__main__":
    main()
