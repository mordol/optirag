"""Phase 2 사전 검증: dense / BM25 / hybrid(RRF) / hybrid+rerank 비교. 결과는 retrieval_results_v2.json"""
import json, time
import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import CrossEncoder, SentenceTransformer
from search import QUERIES
from retriever import bm25_tokens

K, POOL, RRF_K = 5, 30, 60


chunks = [json.loads(l) for l in open("chunks.jsonl")]
E = np.load("embeddings.npy")
assert len(E) == len(chunks), "embeddings.npy가 chunks.jsonl과 맞지 않음. search.py를 먼저 실행"
bm25 = BM25Okapi([bm25_tokens(c["text"]) for c in chunks])
embedder = SentenceTransformer("BAAI/bge-m3")
reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=1024)


def rankings(q):
    dense = list(np.argsort(-(E @ embedder.encode([q], normalize_embeddings=True)[0])))
    sparse = list(np.argsort(-bm25.get_scores(bm25_tokens(q))))
    rrf = {}
    for lst in (dense[:POOL * 2], sparse[:POOL * 2]):
        for r, i in enumerate(lst):
            rrf[i] = rrf.get(i, 0) + 1 / (RRF_K + r + 1)
    hybrid = sorted(rrf, key=lambda i: -rrf[i])
    pool = hybrid[:POOL]
    scores = reranker.predict([(q, chunks[i]["text"]) for i in pool], batch_size=8)
    rerank = [pool[j] for j in np.argsort(-scores)]
    return {"dense": dense, "bm25": sparse, "hybrid": hybrid, "hybrid+rerank": rerank}, dict(zip(pool, scores))


if __name__ == "__main__":
    out = []
    t = time.perf_counter()
    for qid, kind, q in QUERIES:
        R, rr_scores = rankings(q)
        out.append({"id": qid, "kind": kind, "query": q, "methods": {
            m: [{"rank": r + 1, "chunk_id": chunks[i]["chunk_id"], "file": chunks[i]["file"], "page": chunks[i]["page"],
                 "page_end": chunks[i]["page_end"], "section": chunks[i]["section"], "text": chunks[i]["text"],
                 **({"rerank_score": round(float(rr_scores[i]), 4)} if m == "hybrid+rerank" else {})}
                for r, i in enumerate(lst[:K])]
            for m, lst in R.items()}})
    print(f"{len(QUERIES)} queries in {time.perf_counter() - t:.1f}s")
    json.dump(out, open("retrieval_results_v2.json", "w"), ensure_ascii=False, indent=1)
