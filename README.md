# LLM Wiki Workflow

將 file-ingest + tag-curation 兩個技能封裝為可安裝格式。

## 技能一：file-ingest

**功能**：將各種格式檔案轉換為乾淨 Markdown，存入 Obsidian Vault `raw md/`。

**支援格式**：docx / pdf / pptx / xlsx / html / txt / md

**依賴工具**：
- `markitdown` — docx/html/pptx/xlsx → Markdown
- `pdftotext`（poppler）— PDF → txt
- `textutil`（macOS）— rtf/doc → docx
- `openpyxl` / `python-pptx` — Python 庫

**使用**：
```bash
python3 file-ingest/scripts/convert.py "/path/to/file.docx" [--vault-path /path/to/vault]
```

**安裝**：
```bash
git clone https://github.com/openclawGit200/LLM_WIKI_workflow.git ~/.openclaw/workspace/skills/llm-wiki-workflow
```

---

## 技能二：tag-curation

**功能**：從 Markdown 文字萃取關鍵詞，Cosine + MMR 評分，飛書卡片呈現，User 勾選後入庫。

**Pipeline**：
```
文字輸入
  → cosine_mmr.py（Cosine Top-100 + MMR Top-100）
  → 飛書卡片呈現
  → User 回覆「採用 1,3,5」或「採用 all」
  → curate.py save → SQLite 入庫
  → 關鍵詞池更新（hit_count / reject_count）
```

**模型**：`mahonzhan/all-MiniLM-L6-v2:latest`（Ollama，384維）

**評分**：
- `local_score` = Cosine Similarity 正規化（1~10）
- `freq_score` = 歷史 doc_count 正規化（1~10）
- `combined` = local + freq

**Tier 邏輯**：
- Tier1（最多10個）= 被 User 選中的詞 + 補足至10
- Tier2 = 原始 Cosine Top-20 第11~20名

**使用**：
```bash
python3 tag-curation/scripts/chunk_analysis_pipeline.py --text "文字" --category "類別" --title "標題"
```

**依賴**：
- Ollama（Port 11434）+ all-MiniLM-L6-v2 模型
- jieba、SQLite（`knowledge.db`）
- 飛書（呈現互動卡片）

---

## Repo 結構

```
LLM_WIKI_workflow/
├── README.md
├── file-ingest/
│   ├── SKILL.md
│   └── scripts/
│       └── convert.py
└── tag-curation/
    ├── SKILL.md
    └── scripts/
        ├── curate.py
        ├── cosine_mmr.py
        └── chunk_analysis_pipeline.py
```
