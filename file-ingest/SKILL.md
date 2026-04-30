---
name: file-ingest
description: >
  將前端介面（飛書/檔案上傳）傳來的各種格式檔案，轉換為乾淨的 Markdown，
  並存入 Obsidian Vault 的 `raw md/` 資料夾，同時記錄來源檔案 metadata。
  最後輸出 Markdown 檔案路徑，供後續 tag-curation Skill 使用。
  觸發時機：收到檔案、檔案上傳、轉檔、ingest file、convert to md。
metadata:
  author: 阿洛
  version: "1.0"
  tags: [檔案處理, Obsidian, Markdown, 格式轉換]
---

# File Ingest Skill

## 觸發關鍵字

- 使用者上傳任何副檔名的檔案（.doc / .docx / .pdf / .pptx / .xlsx / .csv / .txt / .html / .md）
- 使用者說「轉檔」「轉成 md」「上傳檔案」「處理附件」
- 使用者直接把檔案丟進飛書對話框

## 檔案處理流程（Chunk-Then-Aggregate）

```
使用者上傳檔案
    ↓
Step 1：接收檔案路徑（飛書 inbound media path 或本地路徑）
Step 2：偵測副檔名，選擇對應轉換器
Step 3：轉換為乾淨 Markdown（YAML frontmatter 內含 source metadata）
Step 4：存入 Obsidian Vault「raw md/」資料夾
Step 5：回傳 .md 檔案路徑給 Agent，Agent 再餵給 tag-curation
```

## 支援格式

| 副檔名 | 轉換方式 |
|--------|---------|
| .doc .docx .rtf .html .htm | `textutil`（macOS 內建）|
| .pdf | `pdftotext`（poppler）|
| .pptx | `python-pptx` |
| .xlsx | `openpyxl` |
| .csv | Python csv 模組（轉 Markdown 表格）|
| .txt .md .markdown | 直接讀取 |
| **其他** | 不支援，需告知使用者 |

## 轉換器工具鏈現況

```bash
# 必要工具（已確認存在）
/opt/homebrew/bin/markitdown  # 主力：docx/html/pptx/xlsx/epub/odt → Markdown
/opt/homebrew/bin/textutil    # 備用：textutil -stdout → 讓 markitdown 接手
/opt/homebrew/bin/pdftotext   # poppler，PDF → txt（markitdown 對 PDF 效果不穩）
python3 -c "import pptx"       # python-pptx，已安裝
python3 -c "import openpyxl"  # openpyxl，已安裝
```

**為什麼用 markitdown？**
- textutil → 純文字，表格/Bold/斜體 全部消失
- markitdown → 直接輸出 Markdown，**粗體/斜體/標題/列表/表格** 結構完整保留

**轉換流程：**
- `.doc` / `.rtf` → `textutil -convert docx -stdout`（避開 Unicode 檔名問題）→ `markitdown`
- `.docx` / `.html` / `.htm` / `.pptx` / `.xlsx` / `.epub` / `.odt` → `markitdown` 直接處理
- `.pdf` → `pdftotext`（markitdown 對中文 PDF 支援較差）
- `.txt` / `.md` → 直接讀取

## YAML Frontmatter 格式

```yaml
---
title: "原始檔案名稱"
source_file: "/完整/路徑/原始檔案.doc"
source_type: ".doc"
source_size: 2333925
converted_at: "2026-04-28T20:52:19"
char_count: 3525
file_mtime: "2026-04-28T17:02:11"
tags: []
---
```

## 使用方式（CLI）

```bash
# 基本用法：直接轉換並寫入 raw md/
python3 skills/file-ingest/scripts/convert.py "/path/to/file.docx"

# 指定 vault 路徑
python3 skills/file-ingest/scripts/convert.py "/path/to/file.pdf" \
  --vault-path "/Users/me/Documents/MyVault"

# 乾燒模式（只看結果，不寫入）
python3 skills/file-ingest/scripts/convert.py "/path/to/file.docx" --dry-run
```

## Obsidian Vault 路徑自動判斷邏輯

1. 讀取 `~/Library/Application Support/obsidian/obsidian.json`
2. 取 `"open": true` 的 vault 路徑
3. 拼接 `/raw md/` 子資料夾
4. 若無 vault 或無法判斷，**必須**询问使用者用 `--vault-path` 指定

## Agent 工作流（與 tag-curation 串接）

```
使用者上傳 .doc 檔案
    ↓
Agent 呼叫 file-ingest： python3 .../convert.py "/inbound/xxx.doc"
    ↓
file-ingest 輸出：
{
  "output_path": "/Obsidian Vault/raw md/xxx_20260428_205235.md",
  "char_count": 3525,
  "source_file": "/inbound/xxx.doc"
}
    ↓
Agent 把 output_path 拿來餵給 tag-curation
→ 觸發 tag-curation：「分析這個 MD 檔案的標籤」
```

## 已知限制

1. ** EMBED 欄位**（Word 中的 OLE 物件、Excel 公式）：textutil 會略過，轉換內容中可能出現 `EMBED   \* MERGEFORMAT` 等殘留文字，需注意
2. **PDF 圖片內文字**：pdftotext 只能抓文字圖層，掃描 PDF 無文字內容
3. **密碼保護的 Office 檔案**：無法處理，需解密後再轉
4. **超大型檔案**（>10MB PDF）：textutil 可能 timeout，建議分批處理

## 產出檔案命名規則

```
{原始檔名slug}_{YYYYMMDD}_{HHMMSS}.md
```

slug 規則：去副檔名，取前80字，非法字元替換為 `_`。

---
## 附屬檔案

```
scripts/convert.py     — 核心轉換腳本（CLI）
```
