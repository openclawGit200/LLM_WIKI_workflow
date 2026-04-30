#!/usr/bin/env python3
"""
Tag Curate v2 - Cosine + MMR 萃取引擎
"""

import jieba, re, math, json, sqlite3, argparse, os, urllib.request
from collections import Counter
from typing import Optional

OLLAMA_URL = "http://localhost:11434/api/embeddings"
EMBED_MODEL = "mahonzhan/all-MiniLM-L6-v2:latest"
MAX_CHARS = 400
CHUNK_OVERLAP = 50
DB_PATH = os.path.expanduser("~/llm-wiki-launcher/data/knowledge.db")

for w in ["B細胞","通用型抗蛇毒血清","人體實驗","免疫特訓","抗蛇毒血清",
           "超級抗體","黑曼巴","眼鏡蛇","太攀蛇","響尾蛇",
           "人體壓力測試機","魔鬼特訓","莫哈維響尾蛇","非洲死神","達爾文獎"]:
    jieba.add_word(w, freq=100)

STOPWORDS = {
    '的','了','是','在','有','和','被','讓','給','這','那','他','她','它',
    '什麼','怎麼','這樣','那樣','這個','那個','也','都','就','而','及','著',
    '上','下','裡','外','中','後','前','之間','來','去','到','說',
    '一次','因為','所以','但是','如果','只是','然後','接著',
    '可能','已經','曾經','真的','的确','好像','似乎',
    '最','更','極','非常','特別','太','過於',
    '自己','別人','然後','接著','最後','首先',
    '一個','一種','另一','另一種',
}
PUNCT_RE = re.compile(r'^[a-zA-Z0-9\s\.\,\;\:\!\?\。\，\！\？\、\；\：\'\"\"\'\'\(\)\[\]\【】\{\}\/\-\_…——～]+$')
VALID_START = set('天地人物事由時空情理法名命氣數象形聲色味質感知之行學思言文語名命題類別項系統技術方法原理科醫藥保健康命心腦血神經細胞抗體血清素毒蛇毒液針筒注射免疫特訓實驗研究臨床開發黑曼巴眼鏡蛇太攀響尾非洲死神奇化工企業管理運營生產銷售服務品質成本數理統計算法模型系統平台工具框架')
INVALID_START = set('的了在上和方法對為把被讓給')

def is_valid(kw: str) -> bool:
    if len(kw) < 2: return False
    if kw.startswith('門後'): return False
    if kw.startswith('血液中') or kw.startswith('離出'): return False
    if re.match(r'^[中離][分出]', kw): return False
    if len(kw) >= 3 and kw[0] in INVALID_START: return False
    if len(kw) >= 4:
        sr = sum(1 for c in kw if c in INVALID_START) / len(kw)
        if sr >= 0.6: return False
    return True

_CHINESE_RE = re.compile(r'[\u4e00-\u9fff]+')

def chinese_subs(text: str, n: int) -> set:
    parts = _CHINESE_RE.findall(text)
    s = set()
    for part in parts:
        for i in range(len(part) - n + 1):
            s.add(part[i:i+n])
    return s

def build_candidates(text: str, top_n: int = 200) -> list:
    valid_subs = set()
    for n in range(2, 7):
        valid_subs |= chinese_subs(text, n)
    words = jieba.lcut(text)
    filtered = [w for w in words if w not in STOPWORDS and len(w) >= 2
                and not PUNCT_RE.fullmatch(w) and is_valid(w)]
    seen, candidates = set(), []
    for w in filtered:
        if w not in seen and is_valid(w):
            seen.add(w); candidates.append(w)
    for i in range(len(filtered) - 1):
        w1, w2 = filtered[i], filtered[i+1]
        if w1 in STOPWORDS or w2 in STOPWORDS: continue
        bg = w1 + w2
        if bg not in seen and bg in valid_subs and is_valid(bg):
            seen.add(bg); candidates.append(bg)
    counts = Counter(filtered)
    candidates.sort(key=lambda w: counts.get(w, 0), reverse=True)
    return candidates[:top_n]

_emb_cache = {}

def get_emb(text: str) -> Optional[list]:
    if text in _emb_cache:
        return _emb_cache[text]
    payload = json.dumps({"model": EMBED_MODEL, "prompt": text[:MAX_CHARS]}).encode()
    try:
        req = urllib.request.Request(OLLAMA_URL, data=payload,
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
            emb = data.get("embedding", [])
            _emb_cache[text] = emb if emb else None
            return _emb_cache[text]
    except Exception:
        _emb_cache[text] = None
        return None

def cosine_sim(a: list, b: list) -> float:
    dot = sum(x*y for x,y in zip(a,b))
    return dot / (math.sqrt(sum(x*x for x in a)) * math.sqrt(sum(x*x for x in b)) + 1e-8)

def vec_avg(vectors: list) -> list:
    d = len(vectors[0])
    return [sum(v[i] for v in vectors)/len(vectors) for i in range(d)]

def chunk_text(text: str, size=MAX_CHARS, overlap=CHUNK_OVERLAP) -> list:
    chunks, start = [], 0
    while start < len(text):
        chunks.append(text[start:start+size])
        start += size - overlap
    return chunks

def cosine_top_n(candidates: list, chunk_embs: list, n=100) -> list:
    results = []
    for kw in candidates:
        emb = get_emb(kw)
        if not emb: continue
        best = max(cosine_sim(emb, ce) for ce in chunk_embs)
        results.append((kw, best))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:n]

def mmr_top_n(doc_emb: list, candidates: list, chunk_embs: list,
              n=100, lam=0.7, precomputed=None) -> list:
    all_scores = {}
    for kw in candidates:
        if precomputed and kw in precomputed:
            all_scores[kw] = precomputed[kw]
        else:
            e = get_emb(kw)
            if e: all_scores[kw] = max(cosine_sim(e, ce) for ce in chunk_embs)
            else: all_scores[kw] = 0
    selected, remaining = [], [kw for kw in candidates if kw in all_scores]
    for _ in range(min(n, len(remaining))):
        best_score, best_kw = -999, None
        for kw in remaining:
            sim_doc = all_scores[kw]
            sim_max = 0
            if selected:
                e1 = get_emb(kw)
                if e1:
                    e2 = get_emb(selected[0])
                    if e2: sim_max = cosine_sim(e1, e2)
                    for s in selected[1:]:
                        e2 = get_emb(s)
                        if e2: sim_max = max(sim_max, cosine_sim(e1, e2))
            score = lam * sim_doc - (1-lam) * sim_max
            if score > best_score:
                best_score, best_kw = score, kw
        if best_kw:
            selected.append(best_kw)
            remaining.remove(best_kw)
    return [(kw, all_scores.get(kw, 0)) for kw in selected]

def normalize(val, lo, hi, lo_out=1, hi_out=10):
    if hi <= lo or hi == 0: return lo_out
    return lo_out + (val - lo) / (hi - lo) * (hi_out - lo_out)

def load_pool(db, category):
    if not os.path.exists(db): return {}
    try:
        conn = sqlite3.connect(db)
        c = conn.cursor()
        c.execute("SELECT name, doc_count FROM tags WHERE category=? AND status='active'", (category,))
        rows = c.fetchall()
        conn.close()
        return {n: d for n, d in rows}
    except: return {}

def extract(text, category="未分類", top_n=20, cosine_k=100, mmr_k=100, lam=0.7, db=DB_PATH, verbose=True):
    def log(msg):
        if verbose: print(msg, flush=True)
    chunks = chunk_text(text)
    log(f"[cosine_mmr] 分段: {len(chunks)} 段")
    log("[cosine_mmr] 計算段落向量...")
    chunk_embs = [e for c in chunks if (e := get_emb(c))]
    if not chunk_embs: return {"error": "無法取得文本向量"}
    doc_emb = vec_avg(chunk_embs)
    log(f"[cosine_mmr] 文檔向量維度: {len(doc_emb)}")
    log("[cosine_mmr] 產生候選詞池...")
    pool = build_candidates(text, top_n=200)
    log(f"[cosine_mmr] 候選詞: {len(pool)} 個")
    log(f"[cosine_mmr] Cosine Top-{cosine_k}...")
    cosine_res = cosine_top_n(pool, chunk_embs, n=cosine_k)
    precomp = {kw: cs for kw, cs in cosine_res}
    log(f"[cosine_mmr] Cosine 完成 ({len(_emb_cache)} 個向量已cache)")
    log(f"[cosine_mmr] MMR Top-{mmr_k}...")
    mmr_res = mmr_top_n(doc_emb, [kw for kw,_ in cosine_res], chunk_embs, n=mmr_k, lam=lam, precomputed=precomp)
    log("[cosine_mmr] MMR 完成")
    merged, seen = [], set()
    for kw, cs in cosine_res + mmr_res:
        if kw not in seen: seen.add(kw); merged.append(kw)
    kpool = load_pool(db, category)
    hits = seen & set(kpool.keys())
    log(f"[cosine_mmr] 合併後候選: {len(merged)} (池命中: {len(hits)})")
    top20 = [kw for kw,_ in cosine_res[:top_n]]
    top20_set = set(top20)
    display_kws = list(top20)
    for kw in hits:
        if kw not in top20_set: display_kws.append(kw)
    display_kws = display_kws[:top_n]
    cvals = [v for _,v in cosine_res]
    cs_lo, cs_hi = min(cvals), max(cvals)
    pvals = list(kpool.values()) or [0]
    p_hi = max(pvals) if max(pvals) > 0 else 1
    disp = []
    for kw in display_kws:
        cs = dict(cosine_res).get(kw, 0.3)
        loc = normalize(cs, cs_lo, cs_hi, 1, 10)
        freq = normalize(kpool.get(kw, 0), 0, p_hi, 1, 10)
        disp.append({"keyword": kw, "cosine": round(cs,4), "local_score": round(loc,2),
                     "freq_score": round(freq,2), "combined": round(loc+freq,2),
                     "doc_count": kpool.get(kw, 0)})
    disp.sort(key=lambda x: x["combined"], reverse=True)
    cosine_ranks = {kw: i+1 for i,(kw,_) in enumerate(cosine_res)}
    return {"total_chunks": len(chunks), "candidates_pool_size": len(merged),
            "pool_hits": list(hits),
            "cosine_top_k": [(kw, round(cs,4)) for kw,cs in cosine_res[:top_n]],
            "mmr_top_k": [(kw, round(cs,4)) for kw,cs in mmr_res[:top_n]],
            "display": disp, "cosine_ranks": cosine_ranks}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--text"); p.add_argument("--file")
    p.add_argument("--category", default="未分類")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--cosine-k", type=int, default=100)
    p.add_argument("--mmr-k", type=int, default=100)
    p.add_argument("--lambda", dest="lam", type=float, default=0.7)
    p.add_argument("--db", default=DB_PATH)
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    if args.text: text = args.text
    elif args.file:
        with open(os.path.expanduser(args.file)) as f: text = f.read()
    else:
        print(json.dumps({"error": "需提供 --text 或 --file"})); return
    r = extract(text, category=args.category, top_n=args.top_n, cosine_k=args.cosine_k,
                mmr_k=args.mmr_k, lam=args.lam, db=args.db, verbose=not args.quiet)
    if args.quiet:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"\n分段: {r.get('total_chunks')}  候選池: {r.get('candidates_pool_size')}  池命中: {r.get('pool_hits')}\n")
        print(f"{'排名':<4} {'關鍵詞':<20} {'local':<6} {'freq':<6} {'combined'}")
        print("-"*60)
        for i, x in enumerate(r.get("display",[]), 1):
            print(f"{i:<4} {x['keyword']:<20} {x['local_score']:<6} {x['freq_score']:<6} {x['combined']}")

if __name__ == "__main__": main()
