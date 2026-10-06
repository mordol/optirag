"""Stage 4-2/3: chunks.jsonl 임베딩(BGE-M3) + 코사인 top-k 검색. 결과는 retrieval_results.json"""
import json, os, time
import numpy as np
from sentence_transformers import SentenceTransformer

K = 5
QUERIES_FILE = "eval_queries.json" if os.path.exists("eval_queries.json") else "eval_queries.example.json"
# 평가 질의: [{"id", "kind", "query"}]. 실제 질의 세트(eval_queries.json)는 문서 내용이 담겨 있어 저장소에 올리지 않음
QUERIES = ([(q["id"], q["kind"], q["query"]) for q in json.load(open(QUERIES_FILE))]
           if os.path.exists(QUERIES_FILE) else [])

if __name__ == "__main__":
    chunks = [json.loads(l) for l in open("chunks.jsonl")]
    model = SentenceTransformer("BAAI/bge-m3")

    if os.path.exists("embeddings.npy") and len(np.load("embeddings.npy")) == len(chunks):
        E = np.load("embeddings.npy")
    else:
        t = time.perf_counter()
        E = model.encode([c["text"] for c in chunks], batch_size=16, normalize_embeddings=True, show_progress_bar=True)
        print(f"embedded {len(chunks)} chunks in {time.perf_counter() - t:.1f}s")
        np.save("embeddings.npy", E)

    Q = model.encode([q for _, _, q in QUERIES], normalize_embeddings=True)
    results = []
    for (qid, kind, q), qv in zip(QUERIES, Q):
        sims = E @ qv
        top = np.argsort(-sims)[:K]
        results.append({"id": qid, "kind": kind, "query": q, "hits": [
            {"rank": r + 1, "score": round(float(sims[i]), 4), **{k: chunks[i][k] for k in ("chunk_id", "file", "page", "page_end", "section", "has_table", "text")}}
            for r, i in enumerate(top)]})
    json.dump(results, open("retrieval_results.json", "w"), ensure_ascii=False, indent=1)
    for r in results:
        print(f"\n## {r['id']} [{r['kind']}] {r['query']}")
        for h in r["hits"]:
            print(f"  {h['rank']}. {h['score']:.3f} {h['chunk_id'].split(' - ')[-1]} p{h['page']} | {h['section'][:60]}")
