"""검색 엔진 (ask.py, mcp_server.py 공용)
bge-m3 dense + BM25 → RRF 융합 → (선택) bge-reranker-v2-m3 재정렬.
인덱스 파일(chunks.jsonl, embeddings.npy)이 바뀌면 다음 검색 때 자동으로 다시 읽음. 모델은 한 번만 로딩."""
import json, os, re, threading
import numpy as np
from rank_bm25 import BM25Okapi

DEFAULT_EMBED_MODEL = "BAAI/bge-m3"
RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
RRF_K, CANDIDATES = 60, 60


def bm25_tokens(text):
    """영숫자 식별자는 단어 단위, 한글은 글자 bigram (형태소 분석기 없이 조사 붙은 어절 대응)"""
    text = text.lower()
    toks = re.findall(r"[a-z0-9_]+", text)
    for run in re.findall(r"[가-힣]+", text):
        toks += [run] if len(run) == 1 else [run[i:i + 2] for i in range(len(run) - 1)]
    return toks


class Retriever:
    def __init__(self, base_dir=".", rerank=True, pool=30):
        self.paths = {n: os.path.join(base_dir, n) for n in ("chunks.jsonl", "embeddings.npy", "index_manifest.json")}
        self.rerank, self.pool = rerank, pool
        self.lock = threading.Lock()
        self.mtime = None
        self._load_index()
        from sentence_transformers import CrossEncoder, SentenceTransformer
        self.embedder = SentenceTransformer(self.embed_model)
        self.reranker = CrossEncoder(RERANK_MODEL, max_length=1024) if rerank else None

    def _index_mtime(self):
        return tuple(os.path.getmtime(self.paths[n]) for n in ("chunks.jsonl", "embeddings.npy"))

    def _load_index(self):
        chunks = [json.loads(l) for l in open(self.paths["chunks.jsonl"])]
        E = np.load(self.paths["embeddings.npy"])
        manifest = json.load(open(self.paths["index_manifest.json"])) if os.path.exists(self.paths["index_manifest.json"]) else {}
        if len(E) != len(chunks) or manifest.get("n_chunks", len(chunks)) != len(chunks):
            raise RuntimeError(f"인덱스 불일치: chunks {len(chunks)}, embeddings {len(E)}, manifest {manifest.get('n_chunks')}"
                               " → python build_index.py 를 다시 실행하세요")
        model = manifest.get("embedding_model", DEFAULT_EMBED_MODEL)
        if getattr(self, "embed_model", model) != model:
            raise RuntimeError(f"임베딩 모델이 바뀜 ({self.embed_model} → {model}). 서버를 재시작하세요")
        self.embed_model = model
        self.chunks, self.E = chunks, E
        self.bm25 = BM25Okapi([bm25_tokens(c["text"]) for c in chunks])
        self.by_id = {c["chunk_id"]: i for i, c in enumerate(chunks)}
        self.mtime = self._index_mtime()

    def _maybe_reload(self):
        if self._index_mtime() != self.mtime:
            self._load_index()

    def search(self, query, k=10):
        """상위 k개 청크(dict) 반환"""
        with self.lock:
            self._maybe_reload()
            dense = np.argsort(-(self.E @ self.embedder.encode([query], normalize_embeddings=True, show_progress_bar=False)[0]))[:CANDIDATES]
            sparse = np.argsort(-self.bm25.get_scores(bm25_tokens(query)))[:CANDIDATES]
            fused = {}
            for lst in (dense, sparse):
                for r, i in enumerate(lst):
                    fused[int(i)] = fused.get(int(i), 0) + 1 / (RRF_K + r + 1)
            order = sorted(fused, key=lambda i: -fused[i])
            if self.reranker:
                pool = order[:max(self.pool, k)]
                scores = self.reranker.predict([(query, self.chunks[i]["text"]) for i in pool], batch_size=8, show_progress_bar=False)
                order = [pool[j] for j in np.argsort(-scores)]
            return [self.chunks[i] for i in order[:k]]

    def get(self, chunk_id):
        """chunk_id → (청크, 이전 청크 id, 다음 청크 id). 이전/다음은 같은 파일 안에서만"""
        with self.lock:
            self._maybe_reload()
            i = self.by_id.get(chunk_id)
            if i is None:
                return None, None, None
            same = lambda j: 0 <= j < len(self.chunks) and self.chunks[j]["file"] == self.chunks[i]["file"]
            return (self.chunks[i], self.chunks[i - 1]["chunk_id"] if same(i - 1) else None,
                    self.chunks[i + 1]["chunk_id"] if same(i + 1) else None)

    def documents(self):
        with self.lock:
            self._maybe_reload()
            docs = {}
            for c in self.chunks:
                d = docs.setdefault(c["file"], {"file": c["file"], "pages": 0, "chunks": 0})
                d["pages"] = max(d["pages"], c["page_end"]); d["chunks"] += 1
            return list(docs.values())
