from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "repair2026")

class FeedbackReviewer:
    def __init__(self):
        self.driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)

    def close(self):
        self.driver.close()

    # 1. 取得所有待審核的反饋
    def fetch_pending_feedbacks(self):
        cypher = """
        MATCH (s:Symptom)-[:HAS_PENDING_FEEDBACK]->(fb:PendingFeedback {status: 'PENDING_REVIEW'})
        RETURN 
            elementId(fb) AS fb_id,
            s.name AS symptom,
            fb.custom_cause AS custom_cause,
            fb.custom_action AS custom_action,
            toString(fb.created_at) AS created_at
        ORDER BY fb.created_at ASC
        """
        with self.driver.session() as session:
            result = session.run(cypher)
            return [record.data() for record in result]

    # 2. 核准並轉入正式圖譜（包含重新正規化機率）
    def approve_feedback(self, fb_id: str, symptom: str, cause: str, action: str):
        cypher = """
        // 1. 更新暫存節點狀態為 APPROVED
        MATCH (fb:PendingFeedback) WHERE elementId(fb) = $fb_id
        SET fb.status = 'APPROVED', fb.reviewed_at = datetime()

        WITH fb
        // 2. 建立或合併正式的 RootCause 與 Action 節點
        MATCH (s:Symptom {name: $symptom})
        MERGE (rc:RootCause {name: $cause})
        MERGE (act:Action {name: $action})
        MERGE (rc)-[:RESOLVED_BY]->(act)

        // 3. 建立因果關係，初始 count 設為 1 (加一平滑)
        MERGE (s)-[target:CAUSED_BY]->(rc)
        ON CREATE SET target.count = 1
        ON MATCH SET target.count = coalesce(target.count, 0) + 1

        WITH s
        // 4. 重新計算該現象所有分支的總數與轉移機率 (Normalization)
        MATCH (s)-[all_rel:CAUSED_BY]->(:RootCause)
        WITH s, sum(all_rel.count) AS total_count, collect(all_rel) AS rel_list

        UNWIND rel_list AS r
        SET r.prob = round(toFloat(r.count) / toFloat(total_count), 4)

        RETURN endNode(r).name AS 原因, r.count AS 次數, r.prob AS 新機率
        ORDER BY r.prob DESC;
        """
        with self.driver.session() as session:
            result = session.run(
                cypher,
                fb_id=fb_id,
                symptom=symptom,
                cause=cause,
                action=action
            )
            print(f"\n✅ [已成功轉入正式知識圖譜] 該現象現有機率分布：")
            for r in result:
                print(f"  * 原因: {r['原因']} | 次數: {r['次數']} | 機率: {r['新機率']:.4f}")

    # 3. 駁回反饋
    def reject_feedback(self, fb_id: str, reason: str = ""):
        cypher = """
        MATCH (fb:PendingFeedback) WHERE elementId(fb) = $fb_id
        SET fb.status = 'REJECTED', 
            fb.reject_reason = $reason, 
            fb.reviewed_at = datetime()
        """
        with self.driver.session() as session:
            session.run(cypher, fb_id=fb_id, reason=reason)
            print("❌ [已駁回該筆反饋]")

def main():
    reviewer = FeedbackReviewer()
    print("==================================================")
    print("   📋 知識圖譜反饋審核與正式轉入系統 (Review Tool) ")
    print("==================================================")

    pending_list = reviewer.fetch_pending_feedbacks()
    if not pending_list:
        print("\n目前沒有任何待審核的現場反饋記錄。")
        reviewer.close()
        return

    print(f"\n目前共有 {len(pending_list)} 筆待審核反饋：\n")

    for idx, item in enumerate(pending_list, 1):
        print(f"------------------- [記錄 {idx}/{len(pending_list)}] -------------------")
        print(f"📌 故障現象   : {item['symptom']}")
        print(f"🔧 技師自填原因: {item['custom_cause']}")
        print(f"🛠️ 技師處置措施: {item['custom_action']}")
        print(f"🕒 提交時間   : {item['created_at']}")
        print("-------------------------------------------------------")

        while True:
            choice = input("審核操作 -> [A] 核准轉入正式圖譜 / [R] 駁回 / [S] 跳過 / [Q] 結束離開: ").strip().upper()
            if choice == "A":
                # 允許審核者在正式寫入前修正用詞
                edit_cause = input(f"修改原因名稱 (直接按 Enter 保持原樣: '{item['custom_cause']}'): ").strip()
                final_cause = edit_cause if edit_cause else item['custom_cause']

                edit_action = input(f"修改維修措施 (直接按 Enter 保持原樣: '{item['custom_action']}'): ").strip()
                final_action = edit_action if edit_action else item['custom_action']

                reviewer.approve_feedback(item["fb_id"], item["symptom"], final_cause, final_action)
                break
            elif choice == "R":
                reason = input("請輸入駁回原因 (選填): ").strip()
                reviewer.reject_feedback(item["fb_id"], reason)
                break
            elif choice == "S":
                print("已跳過此筆。")
                break
            elif choice == "Q":
                print("退出審核系統。")
                reviewer.close()
                return
            else:
                print("輸入無效，請輸入 A、R、S 或 Q。")

    reviewer.close()
    print("\n所有待審項目審核完畢！")

if __name__ == "__main__":
    main()
