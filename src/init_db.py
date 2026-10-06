import sys
from neo4j import GraphDatabase

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "repair2026")

def initialize_knowledge_graph():
    print("🚀 正在連接 Neo4j 並初始化維修知識圖譜...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        driver.verify_connectivity()
    except Exception as e:
        print(f"❌ 無法連線至 Neo4j 資料庫: {e}")
        print("💡 請確認 Docker 容器是否運行中：docker compose up -d")
        sys.exit(1)

    with driver.session() as session:
        # 1. 清空既有舊資料（保證乾淨重置）
        print("  - 清理舊有資料...")
        session.run("MATCH (n) DETACH DELETE n;")

        # 2. 建立 Schema 約束與索引
        print("  - 建立 Schema 約束與索引...")
        constraints = [
            "CREATE CONSTRAINT IF NOT EXISTS FOR (s:Symptom) REQUIRE s.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (r:RootCause) REQUIRE r.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Component) REQUIRE c.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Action) REQUIRE a.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (t:Tool) REQUIRE t.name IS UNIQUE;",
            "CREATE CONSTRAINT IF NOT EXISTS FOR (u:UnmatchedQuery) REQUIRE u.query_text IS UNIQUE;"
        ]
        for c in constraints:
            session.run(c)

        # 3. 寫入電話維修知識圖譜（含初始馬可夫轉移機率與工單頻次）
        print("  - 寫入初始節點與馬可夫先驗機率...")
        cypher_populate = """
        // 現象節點
        MERGE (s1:Symptom {name: "拿起聽筒完全無撥號音(無聲)"})
        MERGE (s2:Symptom {name: "有撥號音但無法撥出且有雜音"})

        // 根本原因節點
        MERGE (rc1:RootCause {name: "RJ11水晶頭氧化或彈片鬆脫"})
        MERGE (rc2:RootCause {name: "電話分機盒室內線斷線"})
        MERGE (rc3:RootCause {name: "PBX總機語音卡槽當機或當路"})
        MERGE (rc4:RootCause {name: "局端電信外線欠費或局端斷訊"})
        MERGE (rc5:RootCause {name: "線路受潮絕緣不良導致短路雜訊"})

        // 部件節點
        MERGE (c1:Component {name: "聽筒彈簧線與電話盒接頭", location: "使用者桌面"})
        MERGE (c2:Component {name: "辦公室暗管配線", location: "牆面與地板管槽"})
        MERGE (c3:Component {name: "PBX交換機", location: "弱電機房"})
        MERGE (c4:Component {name: "外線端子板", location: "一樓總配線箱(MDF)"})

        // 維修措施節點
        MERGE (act1:Action {name: "重新拔插或剪線壓接新RJ11水晶頭", est_time_min: 5, difficulty: "低"})
        MERGE (act2:Action {name: "使用網路查線器進行通路蜂鳴測試並重新接線", est_time_min: 20, difficulty: "中"})
        MERGE (act3:Action {name: "登入PBX後台重啟對應Extension Port或更換卡槽", est_time_min: 15, difficulty: "中"})
        MERGE (act4:Action {name: "於MDF測線板掛接測試用話機確認外線信號", est_time_min: 10, difficulty: "低"})
        MERGE (act5:Action {name: "檢視接線端子是否發霉並重新打線(Krone)", est_time_min: 15, difficulty: "低"})

        // 工具節點
        MERGE (t1:Tool {name: "RJ11壓線鉗"})
        MERGE (t2:Tool {name: "音頻查線尋線儀(Tracker)"})
        MERGE (t3:Tool {name: "外線查修專用工程話機(Butt Set)"})
        MERGE (t4:Tool {name: "110打線刀"})

        // 因果關係與轉移機率
        MERGE (s1)-[:CAUSED_BY {prob: 0.50, count: 50}]->(rc1)
        MERGE (s1)-[:CAUSED_BY {prob: 0.25, count: 25}]->(rc2)
        MERGE (s1)-[:CAUSED_BY {prob: 0.15, count: 15}]->(rc3)
        MERGE (s1)-[:CAUSED_BY {prob: 0.10, count: 10}]->(rc4)

        MERGE (s2)-[:CAUSED_BY {prob: 0.70, count: 28}]->(rc5)
        MERGE (s2)-[:CAUSED_BY {prob: 0.30, count: 12}]->(rc1)

        // 設備關聯
        MERGE (rc1)-[:LOCATED_IN]->(c1)
        MERGE (rc2)-[:LOCATED_IN]->(c2)
        MERGE (rc3)-[:LOCATED_IN]->(c3)
        MERGE (rc4)-[:LOCATED_IN]->(c4)
        MERGE (rc5)-[:LOCATED_IN]->(c4)

        // 處置措施關聯
        MERGE (rc1)-[:RESOLVED_BY]->(act1)
        MERGE (rc2)-[:RESOLVED_BY]->(act2)
        MERGE (rc3)-[:RESOLVED_BY]->(act3)
        MERGE (rc4)-[:RESOLVED_BY]->(act4)
        MERGE (rc5)-[:RESOLVED_BY]->(act5)

        // 工具關聯
        MERGE (act1)-[:REQUIRES]->(t1)
        MERGE (act2)-[:REQUIRES]->(t2)
        MERGE (act4)-[:REQUIRES]->(t3)
        MERGE (act5)-[:REQUIRES]->(t4);
        """
        session.run(cypher_populate)
        print("✅ 知識圖譜初始化完成！所有實體、關係與馬可夫先驗機率已成功寫入。")

    driver.close()

if __name__ == "__main__":
    initialize_knowledge_graph()
