"""chunks.jsonl → embeddings.npy (BAAI/bge-m3, 정규화) + index_manifest.json. chunk.py를 다시 돌렸으면 반드시 다시 실행
usage: python build_index.py"""
import json, time
from datetime import datetime
import numpy as np
from sentence_transformers import SentenceTransformer

MODEL = "BAAI/bge-m3"
chunks = [json.loads(l) for l in open("chunks.jsonl")]
t = time.perf_counter()
E = SentenceTransformer(MODEL).encode([c["text"] for c in chunks], batch_size=16,
                                              normalize_embeddings=True, show_progress_bar=True)
np.save("embeddings.npy", E)
# 검색 쪽(retriever.py)이 같은 모델로 질의를 임베딩하도록 기록
json.dump({"embedding_model": MODEL, "n_chunks": len(chunks), "dim": int(E.shape[1]),
           "built_at": datetime.now().isoformat(timespec="seconds")}, open("index_manifest.json", "w"), indent=1)
print(f"embedded {len(chunks)} chunks in {time.perf_counter() - t:.1f}s")
