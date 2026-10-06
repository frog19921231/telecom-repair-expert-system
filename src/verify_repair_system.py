import json
import requests
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "repair2026")
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5:7b"

class RepairExpertSystem:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

    def close(self):
        self.driver.close()

    def beam_search_diagnosis(self, symptom_name: str, beam_width: int = 2):
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

    def generate_report(self, symptom_name: str, top_paths: list):
        context_str = json.dumps(top_paths, ensure_ascii=False, indent=2)
        prompt = f"""你是一名電話與通訊線路維修專家。
維修人員目前回報故障現象：「{symptom_name}」。

知識圖譜推論引擎已依據馬可夫歷史轉移機率，為你篩選出最可能的 Top 排查路徑如下：
{context_str}

請嚴格基於上述資訊，為現場技師產出一份簡潔、條理分明的維修指導：
1. 分析最可能的根本原因與機率順序。
2. 條列排查順序，包含維修位置、具體步驟與建議工具。
3. 語氣嚴謹專業，禁止捏造未在資訊中出現的零件。"""

        payload = {
            "model": MODEL_NAME,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.0}
        }
        try:
            res = requests.post(OLLAMA_URL, json=payload, timeout=60)
            return res.json().get("response", "生成失敗")
        except Exception as e:
            return f"Ollama 連線異常，請確認 ollama 是否正在運行: {e}"

    def update_feedback(self, symptom_name: str, confirmed_cause: str):
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
            result = session.run(cypher, symptom=symptom_name, cause=confirmed_cause)
            print(f"\n[資料庫更新] 現象「{symptom_name}」各原因最新機率分佈：")
            for r in result:
                print(f" -> {r['原因']}: 命中 {r['次數']} 次 | 機率 {r['新機率']:.4f}")

if __name__ == "__main__":
    system = RepairExpertSystem()
    test_symptom = "拿起聽筒完全無撥號音(無聲)"

    print(f"=== 測試 1: 輸入故障現象 [{test_symptom}] ===")
    candidates = system.beam_search_diagnosis(test_symptom, beam_width=2)
    print("\n[Beam Search 檢索命中路徑]:")
    print(json.dumps(candidates, ensure_ascii=False, indent=2))

    print("\n[Ollama 專家決策報告生成中...]:")
    report = system.generate_report(test_symptom, candidates)
    print(report)

    print("\n" + "="*50)
    print("=== 測試 2: 技師反饋修復結果 ===")
    confirmed = "RJ11水晶頭氧化或彈片鬆脫"
    print(f"技師回報：本次確認為「{confirmed}」導致，修復完畢。")
    system.update_feedback(test_symptom, confirmed)

    system.close()
