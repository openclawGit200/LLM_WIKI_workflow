#!/usr/bin/env python3
"""
Tag Curate System - 簡化版（Phase 1）
僅負責：存檔（save）與查詢（status）+ 文字分段（chunk）
分析由 Agent 直接用模型執行
"""

import sys, json, sqlite3, uuid, argparse, os, re
from datetime import datetime


def update_frontmatter_wikilinks(md_path: str, tags: list[str]) -> bool:
    """
    讀取 md 檔案，找出 frontmatter 的 tags: [...] 行，
    替換為 Obsidian wiki-link 格式：tags: ["[[tag1]]", "[[tag2]]", ...]
    只改 tags 行，其他 frontmatter 內容不動。
    """
    if not os.path.exists(md_path):
        return False
    with open(md_path, 'r', encoding='utf-8') as f:
        content = f.read()

    lines = content.split('\n')
    in_fm = False
    fm_tags_idx = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped == '---':
            if not in_fm:
                in_fm = True
            else:
                # end of frontmatter
                break
        if in_fm and stripped.startswith('tags:'):
            fm_tags_idx = i
            break

    if fm_tags_idx is None:
        # tags 行不存在，找到 last_key 行之後插入
        # 簡化：找到 '---' 結尾之前的最後一行，插入 tags 行
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].strip() and not lines[i].strip().startswith('---'):
                lines.insert(i + 1, f'tags: [{", ".join(f"[[{t}]]" for t in tags)}]')
                break
    else:
        wiki_tags = ', '.join(f'"[[{t}]]"' for t in tags)
        lines[fm_tags_idx] = f'tags: [{wiki_tags}]'

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    return True

DB_PATH = os.path.expanduser("~/llm-wiki-launcher/data/knowledge.db")
OBSIDIAN_VAULT = "/Users/downtoearth/Documents/Obsidian Vault"
OBSIDIAN_RAW_MD = OBSIDIAN_VAULT + "/raw md"


def _resolve_md_file(doc_id: str, explicit_path: str = None) -> str:
    """
    自動推斷 md 檔案路徑：
    1. 如果明確指定 --md-file，使用該路徑
    2. 否則在 Obsidian vault raw md/ 中搜尋含 doc_id 的 .md 檔案
    3. 回傳 None 表示找不到（不阻斷 SQLite 寫入）
    """
    if explicit_path:
        return explicit_path
    if not os.path.exists(OBSIDIAN_RAW_MD):
        return None
    for fname in os.listdir(OBSIDIAN_RAW_MD):
        if fname.endswith('.md') and doc_id in fname:
            return os.path.join(OBSIDIAN_RAW_MD, fname)
    return None


# ── 文字分段工具（Option B：段落切，上限 1800 字）─────────────────
MAX_CHUNK_SIZE = 1800
MIN_CHUNK_SIZE = 200

def chunk_text(text: str) -> list[dict]:
    """
    按段落分塊（Option B）：
    1. 依空行拆成段落
    2. 小段落（<MIN_CHUNK_SIZE）與下一段合併
    3. 仍超大的段落按句子進一步拆分
    回傳：[{"index": 0, "text": "...", "chars": 300}, ...]
    """
    # 依空行拆段落
    lines = text.split('\n')
    paragraphs = []
    buf = []
    for line in lines:
        stripped = line.strip()
        if stripped == '':
            if buf:
                paragraphs.append('\n'.join(buf))
                buf = []
        else:
            buf.append(stripped)
    if buf:
        paragraphs.append('\n'.join(buf))

    # 小段落合併至下一個
    merged = []
    for para in paragraphs:
        if not para.strip():
            continue
        if merged and len(merged[-1]) + len(para) < MAX_CHUNK_SIZE:
            merged[-1] = merged[-1] + '\n' + para
        else:
            merged.append(para)

    # 過長段落按句子拆分
    chunks = []
    for para in merged:
        if len(para) <= MAX_CHUNK_SIZE:
            chunks.append(para)
        else:
            sentences = re.split(r'(?<=[。！？.!?])\s*', para)
            current = ''
            for sent in sentences:
                if not sent.strip():
                    continue
                if len(current) + len(sent) <= MAX_CHUNK_SIZE:
                    current = (current + '\n' + sent).strip()
                else:
                    if current:
                        chunks.append(current)
                    if len(sent) > MAX_CHUNK_SIZE:
                        # 單句仍超長，強制固定長度切
                        for i in range(0, len(sent), MAX_CHUNK_SIZE - 200):
                            chunks.append(sent[i:i + MAX_CHUNK_SIZE - 200])
                            current = ''
                    else:
                        current = sent
            if current:
                chunks.append(current)

    return [{"index": i, "text": c, "chars": len(c)} for i, c in enumerate(chunks)]


def cmd_chunk(args):
    if args.file:
        with open(os.path.expanduser(args.file), 'r', encoding='utf-8', errors='ignore') as f:
            text = f.read()
    elif args.text:
        text = args.text
    else:
        print(json.dumps({"error": "需提供 --file 或 --text"}, ensure_ascii=False))
        sys.exit(1)
    chunks = chunk_text(text)
    print(json.dumps({"total": len(chunks), "chunks": chunks}, ensure_ascii=False, indent=2))


# ── 資料庫初始化 ──────────────────────────────────────────────
def init_db(db_path: str):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            category TEXT,
            doc_count INTEGER DEFAULT 0,
            hit_count INTEGER DEFAULT 0,
            reject_count INTEGER DEFAULT 0,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS document_tags (
            doc_id TEXT,
            tag_id TEXT,
            tag_name TEXT,
            source TEXT,
            tier TEXT,
            local_score REAL,
            freq_score REAL,
            combined_score REAL,
            user_selected INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (doc_id, tag_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            created_by TEXT DEFAULT 'user'
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS documents (
            id TEXT PRIMARY KEY,
            title TEXT,
            content TEXT,
            category TEXT,
            status TEXT DEFAULT 'untagged',
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)
    for cat in ["技術標準文件", "財報分析", "法規遵循", "流程文件"]:
        c.execute("INSERT OR IGNORE INTO categories (id, name) VALUES (?, ?)",
                  (str(uuid.uuid4()), cat))
    conn.commit()
    return conn


# ── SAVE：寫入標籤 ──────────────────────────────────────────────
def cmd_save(args):
    conn = init_db(args.db or DB_PATH)
    c = conn.cursor()
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    if args.candidates:
        try:
            candidates = json.loads(args.candidates)
            if not isinstance(candidates, dict):
                raise ValueError("candidates must be a JSON object")
        except Exception as e:
            print(json.dumps({"error": f"JSON解析失敗: {e}"}, ensure_ascii=False))
            sys.exit(1)
    else:
        candidates = {}

    tags_input = []
    if args.tags:
        for t in args.tags.split(","):
            t = t.strip()
            if t and t not in candidates:
                tags_input.append((t, args.local_score, args.freq_score,
                                   args.combined, args.source or 'cosine_top20',
                                   args.tier or 'tier2'))
    for tag_name, scores in candidates.items():
        if isinstance(scores, dict):
            tags_input.append((
                tag_name,
                scores.get("local_score", 5),
                scores.get("freq_score", 5),
                scores.get("combined", 10),
                scores.get("source", "cosine_top20"),
                scores.get("tier", "tier2"),
            ))
        else:
            tags_input.append((tag_name, args.local_score, args.freq_score,
                               args.combined, args.source or 'cosine_top20',
                               args.tier or 'tier2'))

    if not tags_input:
        print(json.dumps({"error": "沒有標籤可寫入"}, ensure_ascii=False))
        sys.exit(1)

    c.execute("""
        INSERT OR REPLACE INTO documents
        (id, title, content, category, status, created_at)
        VALUES (?, ?, ?, ?, 'curated', ?)
    """, (args.doc_id, args.title or '', args.text[:2000] if args.text else '',
          args.category or '技術標準文件', now))

    # 確保類別存在
    c.execute("SELECT id FROM categories WHERE name = ?", (args.category or '技術標準文件',))
    row = c.fetchone()
    if not row:
        cat_id = str(uuid.uuid4())
        c.execute("INSERT INTO categories (id, name) VALUES (?, ?)",
                  (cat_id, args.category or '技術標準文件'))

    saved = 0
    for tag_name, local_s, freq_s, combined_s, source, tier in tags_input:
        c.execute("SELECT id FROM tags WHERE name = ?", (tag_name,))
        row = c.fetchone()
        tag_id = row[0] if row else str(uuid.uuid4())
        if not row:
            c.execute("INSERT INTO tags (id, name, category) VALUES (?, ?, ?)",
                      (tag_id, tag_name, args.category or '技術標準文件'))

        c.execute("""
            INSERT OR REPLACE INTO document_tags
            (doc_id, tag_id, tag_name, source, tier, local_score,
             freq_score, combined_score, user_selected, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
        """, (args.doc_id, tag_id, tag_name, source, tier,
               local_s, freq_s, combined_s, now))

        # 更新 tags.doc_count（被寫入過的文件篇數）
        c.execute("""
            UPDATE tags
            SET doc_count = (
                SELECT COUNT(DISTINCT doc_id)
                FROM document_tags dt
                JOIN documents d ON d.id = dt.doc_id
                WHERE dt.tag_name = tags.name
                  AND d.category = tags.category
            )
            WHERE name = ? AND category = ?
        """, (tag_name, args.category or '技術標準文件'))

        # 更新 tags.hit_count（被選入池的次數）
        c.execute("UPDATE tags SET hit_count = hit_count + 1, reject_count = 0 WHERE name = ?",
                  (tag_name,))
        saved += 1

    # 處理關鍵詞池的 reject_count（萃取結果候選詞中被 user 拒絕的詞）
    rejected = json.loads(args.rejected) if args.rejected else []
    for tag_name in rejected:
        c.execute("UPDATE tags SET reject_count = reject_count + 1 WHERE name = ?",
                  (tag_name,))
        # 移除連續被忽視 ≥2 次的詞
        c.execute("UPDATE tags SET status = 'removed' WHERE name = ? AND reject_count >= 2",
                  (tag_name,))

    # 自動寫入 Obsidian wiki-link
    md_file = _resolve_md_file(args.doc_id, args.md_file)
    md_updated = False
    if md_file and tags_input:
        tag_names = [t[0] for t in tags_input]
        md_updated = update_frontmatter_wikilinks(md_file, tag_names)

    conn.commit()
    conn.close()
    result = {"success": True, "saved": saved, "doc_id": args.doc_id}
    if md_updated:
        result["md_updated"] = True
        result["md_file"] = md_file
        result["wiki_tags"] = [f"[[{t[0]}]]" for t in tags_input]
    print(json.dumps(result, ensure_ascii=False))


# ── STATUS：查詢文件標籤 ─────────────────────────────────────────
def cmd_status(args):
    conn = sqlite3.connect(args.db or DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT dt.tag_name, dt.local_score, dt.freq_score,
               dt.combined_score, dt.locked
        FROM document_tags dt
        WHERE dt.doc_id = ?
        ORDER BY dt.combined_score DESC
    """, (args.doc_id,))
    rows = c.fetchall()
    conn.close()
    result = [{
        "tag": r[0], "local_score": r[1], "freq_score": r[2],
        "combined": r[3], "locked": bool(r[4])
    } for r in rows]
    print(json.dumps(result, ensure_ascii=False, indent=2))


# ── CLI 入口 ───────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Tag Curate - Save / Status / Chunk")
    sub = parser.add_subparsers()

    pc = sub.add_parser("chunk", help="文字分段（段落切，上限1800字）")
    gc = pc.add_mutually_exclusive_group(required=True)
    gc.add_argument("--file", default=None, help="檔案路徑")
    gc.add_argument("--text", default=None, help="直接給文字")
    gc.set_defaults(func=cmd_chunk)

    p = sub.add_parser("save", help="寫入標籤")
    p.add_argument("--doc-id", required=True)
    p.add_argument("--tags", default="", help="逗號分隔標籤（與--candidates二選一）")
    p.add_argument("--title", default="")
    p.add_argument("--text", default="")
    p.add_argument("--category", default="技術標準文件")
    p.add_argument("--local-score", type=float, default=5)
    p.add_argument("--freq-score", type=float, default=5)
    p.add_argument("--combined", type=float, default=10)
    p.add_argument("--db", default=None)
    p.add_argument("--candidates", default=None,
                  help="JSON物件，各標籤不同分數（各鍵：{local_score,freq_score,combined,source,tier}）")
    p.add_argument("--md-file", default=None,
                  help="同步寫入 Obsidian wiki-link 格式 tags 到 markdown 檔案")
    p.add_argument("--tier1", default=None,
                  help="JSON array，Tier1 關鍵詞列表")
    p.add_argument("--tier2", default=None,
                  help="JSON array，Tier2 關鍵詞列表")
    p.add_argument("--sources", default=None,
                  help="JSON物件，各標籤的來源（cosine_top20/mmr_top100/pool_hit）")
    p.add_argument("--local-scores", default=None,
                  help="JSON物件，各標籤的 local_score")
    p.add_argument("--freq-scores", default=None,
                  help="JSON物件，各標籤的 freq_score")
    p.add_argument("--combined-scores", default=None,
                  help="JSON物件，各標籤的 combined score")
    p.add_argument("--rejected", default=None,
                  help="JSON array，被 user 拒絕的候選詞（進 reject_count）")
    p.set_defaults(func=cmd_save)

    p2 = sub.add_parser("status", help="查詢文件標籤")
    p2.add_argument("--doc-id", required=True)
    p2.add_argument("--db", default=None)
    p2.set_defaults(func=cmd_status)

    args = parser.parse_args()
    if hasattr(args, "func"):
        args.func(args)
    else:
        parser.print_help()
