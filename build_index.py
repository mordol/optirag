"""chunks.jsonl → embeddings.npy (BAAI/bge-m3, 정규화). chunk.py를 다시 돌렸으면 반드시 다시 실행
usage: python build_index.py"""
import json, time
import numpy as np
from sentence_transformers import SentenceTransformer

chunks = [json.loads(l) for l in open("chunks.jsonl")]
t = time.perf_counter()
E = SentenceTransformer("BAAI/bge-m3").encode([c["text"] for c in chunks], batch_size=16,
                                              normalize_embeddings=True, show_progress_bar=True)
np.save("embeddings.npy", E)
print(f"embedded {len(chunks)} chunks in {time.perf_counter() - t:.1f}s")
