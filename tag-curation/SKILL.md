---
name: tag-curation
description: >
  當需要對一段文字進行標籤萃取與 CURATE 時觸發。
  功能：(1) Ollama Cosine + MMR 萃取關鍵詞，(2) 關鍵詞池比對 + Boost，
  (3) local_score + freq_score + combined 評分，(4) 飛書呈現 User 勾選，
  (5) 分 Tier1/Tier2 入庫，(6) 關鍵詞池動態更新（hit_count / reject_count）。
  觸發時機：「分析這段文字的標籤」「萃取標籤」「幫我拆解這篇文章」「tag curation」。
metadata:
  author: 阿洛
  version: "2.0"
  tags: [知識管理, 標籤系統, LLM-Wiki, Cosine-MMR]
---

# Tag Curate System（Phase 2）

## 觾發條件

- 使用者說「分析這段文字的標籤」「萃取標籤」「幫我拆解這篇文章」
- 使用者貼上文字並說「幫我打標籤」
- 使用者提供檔案路徑並說「分析這份文件的標籤」
- 使用者提供飛書文件連結並說「分析這份文件的標籤」

## 作業流程

```
Step 1: 接收輸入
  → 純文字（>2000字）：不接受，請使用者提供檔案路徑
  → 檔案路徑：直接讀檔
  → 飛書連結：呼叫飛書 API 讀取

Step 2: 文字分段（段落切，上限 1800 字）
  → python3 scripts/curate.py chunk --file "/path/to/file"

Step 3: Cosine + MMR 萃取出候選詞（cosine_mmr.py）
  → 滑動窗口分段（400字/段，重疊50）→ 每段向量 → 平均 = doc_emb
  → jieba 分詞 + bi-gram（bi-gram 需為文本中的實際子字串）
  → Cosine Top-100 + MMR Top-100 → 合併去重
  → 關鍵詞池比對（命中的詞 Boost 進最終結果）
  → 補足 Top-20
  → local_score + freq_score + combined 評分

Step 4: 呈現 User（飛書卡片）
  → combined 排序，隱藏分數
  → 格式：[ ] 標籤名

Step 5: User 勾選 → 分層入庫
  → Tier 1（最多10個）：
      被 User 選中的詞（N個）
      + 原始 Top-20 內、未被選中的詞補足至 10 個
  → Tier 2：
      原始 Top-20 第 11~20 名（無論是否被選中）
  → 寫入 curate.py save（擴充 schema）

Step 6: 關鍵詞池更新
  → 被選中的詞：hit_count + 1，reject_count 歸零
  → 出現在萃取結果但未被選中的池內詞：reject_count + 1
  → reject_count ≥ 2 的詞：status = 'removed'
```

## 分數說明

```
local_score  = Cosine(doc_emb, word_emb) 正規化至 1~10
             → 這個詞對本文的重要程度

freq_score  = 該詞在同類別文件中出現的篇數（doc_count）正規化至 1~10
             → 這個詞在同領域的代表性

combined     = local_score + freq_score（範圍 2~20）
```

## Tier 判定邏輯

```
User 選了 N 個詞：
  → Tier 1 = [被選中的詞] + [原始 Top-20 未被選中、補足至 10 個]
  → Tier 2 = 原始 Top-20 第 11~20 名（全部）
```

## 資料庫 Schema（v2）

```sql
CREATE TABLE categories (
    id         TEXT PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    created_by TEXT DEFAULT 'user'
);

CREATE TABLE tags (
    id           TEXT PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    category     TEXT,
    doc_count    INTEGER DEFAULT 0,      -- 在同類別文件中出現的篇數
    hit_count    INTEGER DEFAULT 0,      -- 被 user 選入關鍵詞池的累積次數
    reject_count INTEGER DEFAULT 0,       -- 連續被忽視次數（≥2 則移除）
    status       TEXT DEFAULT 'active',   -- active / removed
    created_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE documents (
    id         TEXT PRIMARY KEY,
    title      TEXT,
    content    TEXT,
    category   TEXT,
    status     TEXT DEFAULT 'untagged',  -- untagged / curated
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE document_tags (
    doc_id       TEXT,
    tag_id       TEXT,
    tag_name     TEXT,
    source       TEXT,                    -- 'cosine_top20' / 'mmr_top100' / 'pool_hit'
    tier         TEXT,                   -- 'tier1' / 'tier2' / 'pool_hit'
    local_score  REAL,
    freq_score   REAL,
    combined     REAL,
    user_selected INTEGER DEFAULT 0,
    created_at   TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (doc_id, tag_id)
);
```

## cosine_mmr.py 用法

```bash
# 基本萃取（輸出 Top-20，含分數）
python3 scripts/cosine_mmr.py --text "文字..." --category "醫學研究"

# 從檔案萃取
python3 scripts/cosine_mmr.py --file "/path/to/file.md" --category "醫學研究"

# 參數
--top-n 20        最終呈現數量（預設20）
--cosine-k 100    Cosine 取 Top-K（預設100）
--mmr-k 100       MMR 取 Top-K（預設100）
--lambda 0.7      MMR λ（預設0.7）
--db PATH         SQLite 路徑
--quiet           安靜模式，只輸出 JSON
```

## curate.py save 用法（v2）

```bash
python3 scripts/curate.py save \
  --doc-id "uuid" \
  --title "文件名稱" \
  --category "醫學研究" \
  --tier1 '["關鍵詞A","關鍵詞B"]' \
  --tier2 '["關鍵詞C","關鍵詞D"]' \
  --sources '{"關鍵詞A":"cosine_top20","關鍵詞B":"pool_hit"}' \
  --local-scores '{"關鍵詞A":8.5,"關鍵詞B":7.2}' \
  --freq-scores '{"關鍵詞A":5.0,"關鍵詞B":5.0}' \
  --combined-scores '{"關鍵詞A":13.5,"關鍵詞B":12.2}'
```

## 飛書卡片格式（v2）

```markdown
## 🏷️ 標籤 CURATE

**文件：** {標題}
**類別：** {類別}
**候選來源：** Cosine Top-100 + MMR Top-100（共 ~100 個候選詞）

**【第一梯隊】**（共 N 個，最多 10 個）
  1. ☐ 標籤A
  2. ☐ 標籤B
  ...

**【第二梯隊】**（共 N 個）
  3. ☐ 標籤C
  4. ☐ 標籤D
  ...

---
**回覆格式：** `採用 1,2,5` / `採用 all` / `取消`
```

## 已知限制

1. **bi-gram 碎片**：空隔中文字串（如「從 鬼門 關前」）去掉空格後變成「從鬼門」，為 bi-gram 候選，需後續過濾
2. **freq_score 為 1.0**：關鍵詞池為空白時，所有 freq_score fallback = 1.0
3. **類別需手動確認**：目前由 Agent 根據文本推斷類別，若新類別則建立

## 附屬檔案

```
scripts/curate.py           — save / status / chunk CLI
scripts/cosine_mmr.py        — 核心萃取引擎（Cosine + MMR）
scripts/chunk_analysis_pipeline.py — 串接萃取 + Feishu 呈現
references/                 — 評分公式詳細說明
templates/                  — 飛書卡片版面範本
```

## 相關 Skill

- `file-ingest`：檔案轉 MD，上游輸入
- `cangjie-skill`：將書籍蒸餾成技能包
- `llm-wiki`：背後的知識庫（SQLite schema）
