"""질의 → hybrid(bge-m3 + BM25) + rerank top-k(retriever.py) → rag-answerer(LLM)가 출처 인용 답변
usage: python ask.py "질문" [-k 10] [--no-llm] [--model claude-opus-5-5] [--effort medium]"""
import argparse, datetime, json, os, subprocess
from retriever import Retriever

ap = argparse.ArgumentParser()
ap.add_argument("question")
ap.add_argument("-k", type=int, default=10, help="LLM에 넘길 청크 수 (권장 8~10, 최대 30)")
ap.add_argument("--no-llm", action="store_true", help="검색 결과만 출력")
ap.add_argument("--model", default="claude-opus-5-5")
ap.add_argument("--effort", default="medium")
a = ap.parse_args()

hits = Retriever().search(a.question, a.k)
lines = [f"# 질문\n{a.question}\n\n# 검색된 자료 (hybrid+rerank top-{a.k})\n"]
for n, c in enumerate(hits, 1):
    pg = f"p.{c['page']}" + (f"-{c['page_end']}" if c["page_end"] != c["page"] else "")
    lines.append(f"## [S{n}] {c['file']} {pg} — {c['section']}\n\n{c['text'].split(chr(10), 1)[1]}\n")

os.makedirs("asks", exist_ok=True)
ctx = os.path.abspath(f"asks/{datetime.datetime.now():%Y%m%d-%H%M%S}.md")
open(ctx, "w").write("\n".join(lines))

if a.no_llm:
    for n, c in enumerate(hits, 1):
        print(f"[S{n}] {c['file']} p.{c['page']} | {c['section']}")
    print(f"\n컨텍스트 파일: {ctx}")
else:
    p = subprocess.run(["claude", "-p", "--agent", "rag-answerer", "--model", a.model, "--effort", a.effort,
                        "--tools", "Read", "--output-format", "json",
                        f"컨텍스트 파일: {ctx}\n이 파일을 읽고 규칙에 따라 질문에 답하세요."],
                       capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"claude 실행 실패 (exit {p.returncode}):\n{p.stderr or p.stdout}")
    d = json.loads(p.stdout)
    print(d["result"])
    print(f"\n(컨텍스트: {ctx} | 비용 ${d.get('total_cost_usd', 0):.3f})")
