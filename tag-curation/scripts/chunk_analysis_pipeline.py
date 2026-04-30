#!/usr/bin/env python3
"""
Tag Curate v2 - Chunk Analysis Pipeline
串接 cosine_mmr.py + 飛書呈現 + 回應解析

流程：
  接收文字 → cosine_mmr 萃取 → 飛書卡片呈現 → parse_reply → curate.save
"""

import sys
import json
import subprocess
import os
import argparse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CHUNK_SCRIPT = SCRIPT_DIR + "/curate.py"
COSINE_MMR_SCRIPT = SCRIPT_DIR + "/cosine_mmr.py"


# ══════════════════════════════════════════════════════════════
#  Step 1-2：萃取（呼叫外部腳本）
# ══════════════════════════════════════════════════════════════

def chunk_text(text: str) -> list:
    result = subprocess.run(
        [sys.executable, CHUNK_SCRIPT, "chunk", "--text", text],
        capture_output=True, text=True, encoding="utf-8", timeout=30
    )
    if result.returncode != 0:
        return {"error": f"chunk失敗: {result.stderr}"}
    return json.loads(result.stdout).get("chunks", [])


def extract_keywords(text: str, category: str) -> dict:
    result = subprocess.run(
        [sys.executable, COSINE_MMR_SCRIPT,
         "--text", text, "--category", category, "--quiet"],
        capture_output=True, text=True, encoding="utf-8", timeout=300
    )
    if result.returncode != 0:
        return {"error": f"cosine_mmr失敗: {result.stderr}"}
    try:
        return json.loads(result.stdout)
    except Exception:
        return {"error": f"JSON解析失敗: {result.stdout[:200]}"}


# ══════════════════════════════════════════════════════════════
#  Step 3：飛書卡片格式化
# ══════════════════════════════════════════════════════════════

def format_feishu_message(result: dict, title: str, category: str) -> str:
    """
    將萃取結果格式化成飛書互動式卡片（用 emoji 按鈕）。
    回傳：(markdown訊息, metadata字典)
    """
    display = result.get("display", [])
    cosine_top_k = result.get("cosine_top_k", [])
    cosine_ranks = result.get("cosine_ranks", {})
    pool_hits = result.get("pool_hits", [])
    total = result.get("candidates_pool_size", 0)

    # Tier 判定
    # 原始 Cosine Top-20
    cosine_top20_set = {kw for kw, _ in cosine_top_k[:20]}
    # Tier1：被 user 選中的詞（由 parse_feishu_reply 填入）
    # 顯示時：我們呈現所有 20 個選項，標記編號
    # 格式：☐ 1. 通用型抗蛇毒血清

    lines = []
    lines.append(f"🏷️ **標籤 CURATE**")
    lines.append(f"📄 文件：{title}")
    lines.append(f"📂 類別：{category}")
    lines.append(f"🔍 萃取：Cosine Top-100 + MMR Top-100（候選池 {total} 個）")
    if pool_hits:
        lines.append(f"✅ 關鍵詞池命中：{', '.join(pool_hits)}")
    lines.append("")
    lines.append("**【第一梯隊】**（共 {} 個，最多 10 個）".format(
        min(10, len(display))))

    # 編號 1~10
    tier1_lines = []
    for i, item in enumerate(display[:10], 1):
        kw = item["keyword"]
        tier1_lines.append(f"  ☐ {i}. {kw}")

    lines.extend(tier1_lines)
    lines.append("")
    lines.append("**【第二梯隊】**（共 {} 個）".format(
        max(0, min(10, len(display) - 10))))

    for i, item in enumerate(display[10:20], 11):
        lines.append(f"  ☐ {i}. {item['keyword']}")

    lines.append("")
    lines.append("─" * 30)
    lines.append("📝 **回覆格式：**")
    lines.append("  `採用 1,3,5,11` ← 只選特定編號")
    lines.append("  `採用 1-5`      ← 選取 1 到 5")
    lines.append("  `採用 all`     ← 全選")
    lines.append("  `取消`         ← 放棄")
    lines.append("")
    lines.append("💡 提示：第一梯隊由系統+使用者共同認可；第二梯隊由系統評選，")

    return "\n".join(lines), {
        "title": title,
        "category": category,
        "result": result,
        "display": display,
        "cosine_top20_set": cosine_top20_set,
        "total": total,
    }


# ══════════════════════════════════════════════════════════════
#  Step 4：解析回覆
# ══════════════════════════════════════════════════════════════

def parse_reply(reply: str, display: list) -> dict:
    """
    解析 user 的回覆，回傳：
      selected_keywords: [kw, ...]  # 被選中的詞
      tier1: [kw, ...]               # Tier1 詞（最多10個）
      tier2: [kw, ...]               # Tier2 詞（第11-20名，全部）
      rejected: [kw, ...]             # 候選中被拒絕的詞（進 reject_count）
    """
    reply = reply.strip()
    display_all = display  # 所有 20 個（可能不到20）

    if reply == "取消":
        return {"selected": [], "tier1": [], "tier2": [],
                "rejected": display_all, "action": "cancel"}

    if reply == "採用 all":
        selected = [item["keyword"] for item in display_all]
        tier1 = selected[:10]
        tier2 = selected[10:20]
        rejected = []
        return {"selected": selected, "tier1": tier1, "tier2": tier2,
                "rejected": rejected, "action": "all"}

    # 解析 "採用 1,3,5-7,11" 格式
    selected = set()
    numbers = reply.replace("採用", "").strip()

    # 支援 "1,3,5" 或 "1-5" 範圍
    import re
    tokens = numbers.replace(" ", "").split(",")

    # 找所有數字和範圍
    all_nums = set()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        if re.match(r'^\d+-\d+$', token):
            start, end = token.split("-")
            all_nums.update(range(int(start), int(end) + 1))
        elif re.match(r'^\d+$', token):
            all_nums.add(int(token))

    # 轉成詞
    display_map = {i + 1: item["keyword"] for i, item in enumerate(display_all)}

    for num in all_nums:
        if num in display_map:
            selected.add(display_map[num])

    selected = list(selected)

    # Tier1：被選中的詞（無論是否在原始Top-20）+ 補足至10個
    # Tier2：原始Top-20第11-20名
    cosine_top20_set = set()
    for i, item in enumerate(display_all):
        if i < 20:
            cosine_top20_set.add(item["keyword"])

    selected_set = set(selected)

    # Tier1 = 被選中的詞 + 未被選中的Top-20詞補足至10
    tier1 = [kw for kw in selected if kw in cosine_top20_set]
    remaining_slots = 10 - len(tier1)
    if remaining_slots > 0:
        for kw in [item["keyword"] for item in display_all[:10]]:
            if kw not in tier1 and len(tier1) < 10:
                tier1.append(kw)

    # Tier2 = 原始Top-20第11-20名
    tier2 = [item["keyword"] for item in display_all[10:20]]

    # Rejected = 候選中被跳過的詞
    rejected = [item["keyword"] for item in display_all
                if item["keyword"] not in selected_set]

    return {"selected": selected, "tier1": tier1, "tier2": tier2,
            "rejected": rejected, "action": "partial"}


# ══════════════════════════════════════════════════════════════
#  Step 5：寫入 curate.py save
# ══════════════════════════════════════════════════════════════

def save_to_curate(doc_id: str, title: str, category: str,
                   tier1: list, tier2: list, rejected: list,
                   result: dict, db_path: str = None):
    """呼叫 curate.py save 寫入 Tier1/Tier2"""
    cmd = [
        sys.executable, CHUNK_SCRIPT, "save",
        "--doc-id", doc_id,
        "--title", title,
        "--category", category,
    ]
    if db_path:
        cmd.extend(["--db", db_path])

    # Tier1 全部寫入（都是 user 選的）
    all_selected = tier1 + tier2
    if not all_selected:
        print("⚠️ 沒有選中任何標籤，跳過寫入。")
        return

    # 建立 candidates JSON
    cosine_ranks = result.get("cosine_ranks", {})
    display = result.get("display", [])
    display_dict = {item["keyword"]: item for item in display}

    candidates = {}
    for kw in all_selected:
        item = display_dict.get(kw, {})
        tier = "tier1" if kw in tier1 else "tier2"
        source = "cosine_top20" if kw in cosine_ranks else "pool_hit"
        candidates[kw] = {
            "local_score": item.get("local_score", 5),
            "freq_score": item.get("freq_score", 5),
            "combined": item.get("combined", 10),
            "source": source,
            "tier": tier,
        }

    cmd.extend(["--candidates", json.dumps(candidates, ensure_ascii=False)])

    # rejected 詞（進 reject_count）
    if rejected:
        cmd.extend(["--rejected", json.dumps(rejected, ensure_ascii=False)])

    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
    if proc.returncode == 0:
        print(f"✅ 寫入成功：{len(all_selected)} 個標籤")
        if proc.stdout.strip():
            print(proc.stdout.strip())
    else:
        print(f"❌ curate.py save 失敗：{proc.stderr}")


# ══════════════════════════════════════════════════════════════
#  CLI 主入口（腳本獨立測試用）
# ══════════════════════════════════════════════════════════════

def main():
    p = argparse.ArgumentParser(description="Tag Curate Pipeline v2")
    p.add_argument("--text"); p.add_argument("--file")
    p.add_argument("--category", default="未分類")
    p.add_argument("--title", default="未命名文件")
    p.add_argument("--doc-id", default=None)
    p.add_argument("--db")
    p.add_argument("--parse-reply", default=None,
                   help="直接解析回覆字串，輸出結果後 exit")
    args = p.parse_args()

    # 解析回覆模式（不需要萃取）
    if args.parse_reply:
        display = []
        if args.file:
            # 從暫存讀取 display
            import json as j
            with open(os.path.expanduser(args.file)) as f:
                display = j.load(f).get("display", [])
        result = {"display": display, "cosine_ranks": {}}
        parsed = parse_reply(args.parse_reply, display)
        print(json.dumps(parsed, ensure_ascii=False, indent=2))
        return

    # 萃取模式
    if args.text:
        text = args.text
    elif args.file:
        with open(os.path.expanduser(args.file)) as f:
            text = f.read()
        if not args.title or args.title == "未命名文件":
            import re
            fname = os.path.splitext(os.path.basename(args.file))[0]
            args.title = re.sub(r'[_\-]?\d{8,}.*$', '', fname)
    else:
        print("❌ 需提供 --text 或 --file")
        return

    doc_id = args.doc_id or "tagcurate-" + str(hash(text))[:12]

    print(f"📄 文件：{args.title} | 類別：{args.category} | {len(text)} 字", flush=True)

    # 萃取
    print("🔍 萃取中（Cosine + MMR）...", flush=True)
    res = extract_keywords(text, args.category)
    if "error" in res:
        print(f"❌ {res['error']}")
        return
    print(f"✅ 候選池：{res.get('candidates_pool_size', 0)} 個詞")

    # 飛書卡片
    msg, meta = format_feishu_message(res, args.title, args.category)
    print("\n" + "=" * 50)
    print(msg)
    print("=" * 50)

    # 診斷輸出（給 Agent 看的 metadata）
    display_json = json.dumps(res.get("display", [])[:20])
    diag = {
        "doc_id": doc_id,
        "title": args.title,
        "category": args.category,
        "result": res,
        "db_path": args.db,
        "parse_reply_cmd": (
            'parse_reply("<user回覆>", display_json=' + display_json + ')'
        )
    }
    print("\n[META]")
    print(json.dumps(diag, ensure_ascii=False))
    print("[/META]")


if __name__ == "__main__":
    main()
