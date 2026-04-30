# LLM Wiki Workflow

file-ingest → tag-curation 完整工作流程。

---

## 流程總覽

```
[檔案輸入]
  ↓
[file-ingest] → 轉換為 .md，寫入 Obsidian vault（raw md/）
  ↓
[tag-curation] → Cosine + MMR 萃取 → 飛書卡片呈現 → User 勾選 → 入庫
  ↓
[LLM Wiki 查詢]
```

---

## Phase 1：file-ingest（檔案攝入）

**觸發條件**：使用者上傳檔案、貼上飛書連結、或說「處理這個檔案」

**流程**：
```
接收檔案（PDF/Word/HTML/圖片/純文字）
  → 轉換為乾淨 Markdown
  → 寫入 Obsidian Vault `raw md/` 資料夾
  → 記錄 metadata（來源、日期、分類）
  → 輸出 Markdown 檔案路徑
```

**實作**：`skills/file-ingest/SKILL.md`

**輸出**：
- `raw md/{date}/{filename}.md`
- metadata：原始格式、頁數、來源 URL

---

## Phase 2：tag-curation（標籤萃取）

**觸發條件**：使用者說「分析這段文字的標籤」「萃取標籤」「幫我拆解這篇文章」

### Step 2-1：文字萃取（cosine_mmr.py）

**目的**：脫離 LLM，使用 Ollama Embedding + Cosine + MMR 萃取候選關鍵詞

```
輸入文字（純中文）
  → jieba 分詞（單詞 ≥2 字）
  → bi-gram（需為文本中的實際子字串）
  → 碎片過濾（_is_valid_candidate 補 jieba 錯誤）
  → 滑動窗口分段（400字/段，重疊50）→ 每段向量 → 平均 = doc_emb
  → Cosine Top-100 + MMR Top-100 → 合併去重
  → 關鍵詞池比對（命中的詞 Boost 進最終結果）
  → local_score + freq_score + combined 評分
```

**模型**：`mahonzhan/all-MiniLM-L6-v2:latest`（Ollama，384維）

**評分公式**：
```
local_score = normalize(cosine_similarity, min, max, 1, 10)
freq_score  = normalize(doc_count_in_keyword_pool, 0, max_doc, 1, 10)
combined   = local_score + freq_score
```

**關鍵詞池**：SQLite `knowledge.db` 的 `tags` 表（同類別歷史文件）
- 命中 → Boost（直接進最終結果）
- 拒絕 → reject_count +1（連續2次移除）

### Step 2-2：呈現（飛書卡片）

**格式**（markdown）：
```
🏷️ 標籤 CURATE
📄 文件：{title}
📂 類別：{category}
🔍 萃取：Cosine Top-100 + MMR Top-100（候選池 {N} 個）

【第一梯隊】（最多 10 個）
  ☐ 1. 通用型抗蛇毒血清
  ☐ 2. 抗蛇毒血清
  ...

【第二梯隊】
  ☐ 11. 美國
  ...

📝 回覆格式：
  採用 1,3,5,11  ← 只選特定編號
  採用 1-5       ← 選取 1 到 5
  採用 all       ← 全選
  取消          ← 放棄
```

### Step 2-3：User 回覆解析

**支援格式**：
- `採用 1,3,5` — 選取特定編號
- `採用 1-5` — 範圍選取
- `採用 all` — 全選
- `取消` — 放棄

**parse_reply() 邏輯**：
- Tier1（最多10個）= 被選中的詞 + 補足至10個
- Tier2 = 原始 Cosine Top-20 第11~20名
- Rejected = 候選中未被選中的詞（進 reject_count）

### Step 2-4：寫入資料庫

**curate.py save** → SQLite `knowledge.db`：

`document_tags` 表：
| 欄位 | 說明 |
|------|------|
| doc_id | 文件 ID |
| tag_name | 標籤名稱 |
| tier | tier1 / tier2 |
| source | cosine_top20 / pool_hit |
| local_score | Cosine 評分 |
| combined_score | 綜合評分 |
| user_selected | 0/1（是否為 user 直接選中）|

`tags` 表：
| 欄位 | 說明 |
|------|------|
| name | 標籤名稱 |
| category | 類別 |
| doc_count | 出現文件數 |
| hit_count | 被採納次數 |
| reject_count | 被拒絕次數 |
| status | active / inactive |

---

## Phase 3：LLM Wiki 查詢

**觸發條件**：使用者說「查一下這個概念」「搜尋相關文件」

```
輸入查詢文字
  → Ollama Embedding（all-MiniLM-L6-v2）
  → Cosine Similarity 搜尋 SQLite
  → 回傳最相關的文件與標籤
```

---

## 檔案對照

| 腳本 | 功能 |
|------|------|
| `file-ingest/` | 檔案攝入（PDF/Word/HTML → Markdown） |
| `tag-curation/scripts/cosine_mmr.py` | Ollama Cosine + MMR 萃取引擎 |
| `tag-curation/scripts/curate.py` | Chunk 分段 + save 入庫 |
| `tag-curation/scripts/chunk_analysis_pipeline.py` | 萃取 + 飛書卡片 + parse_reply 整合 |
| `llm-wiki-launcher/data/knowledge.db` | SQLite 知識庫 |

---

##依賴

- **Ollama**（本機執行，Port 11434）
  - 模型：`mahonzhan/all-MiniLM-L6-v2:latest`
  - 模型：`qwen2.5:7b`（Gradio 介面用）
- **jieba**（中文分詞，Python）
- **Python 3.9+**
- **SQLite**（知識庫）
- **Obsidian Vault**（Markdown 檔案存放）
