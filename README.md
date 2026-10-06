# 📞 Neuro-Symbolic Repair Expert System (神經符號維修專家系統)

本專案結合 **知識圖譜 (Neo4j)**、**馬可夫鏈狀態轉移機率** 與 **本機大語言模型 (Ollama / Qwen 2.5)**，為電信與電話線路維修提供確定性、防幻覺且具備自我演進能力的現代專家系統。

## 📁 目錄結構說明
- `src/`：系統主程式碼（資料庫初始化、互動對答、反饋審核）。
- `tests/`：測試題庫與消融實驗評測腳本。
- `docs/`：系統架構圖與維修本體定義文件。
- `docker-compose.yml`：Neo4j 資料庫環境一鍵啟動設定。

## 🚀 快速上手 (Quick Start)
1. 啟動資料庫：`docker compose up -d`
2. 安裝依賴：`pip install -r requirements.txt`
3. 初始化圖譜：`python src/init_db.py`
4. 啟動維修問答：`python src/ask_repair_system.py`
5. 審核現場反饋：`python src/review_feedback.py`
