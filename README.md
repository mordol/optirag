# OptiRAG

로컬 PDF RAG 시스템입니다. PDF 문서를 대량으로 넣고 질문하면, LLM이 문서 내용만 근거로 삼아 출처(파일명, 페이지)를 인용하며 정리해 답합니다.

```
PDF ─ run_convert.py ─▶ JSON ─ chunk.py (+ 문장 제외 규칙) ─▶ chunks.jsonl ─ build_index.py ─▶ embeddings.npy
                                                                    │ retriever.py: bge-m3 + BM25 하이브리드 → bge-reranker-v2-m3
질문 ─ ask.py ─────────────▶ top-k 청크 ─▶ Claude Code CLI가 답변 ([S#] 인용)
질문 ─ Claude Desktop/Codex ─▶ mcp_server.py (search/fetch/list_documents) ─▶ 앱의 LLM이 답변 (파일명 p.N 인용)
```

| 구성 요소 | 사용 기술 |
|---|---|
| 파싱 | [opendataloader-pdf](https://github.com/opendataloader-project/opendataloader-pdf) (Fast 모드, Java 11+) |
| 청킹 | 문서 제목 계층 기반, 512토큰 상한, 표 행 단위 분할(머리행·캡션 반복), 페이지를 넘는 표 병합. **글꼴 크기·스타일에 의존하지 않음** |
| 문장 제외 (선택) | `exclude_rules.yaml`의 정규식에 맞는 반복 문구(머리글, 고지문, 페이지 번호 등)를 청킹 때 제거. 예시: `exclude_rules.example.yaml` |
| 임베딩 | `BAAI/bge-m3` (한국어·영어 혼합) |
| 검색 | dense + BM25를 RRF로 융합 → `BAAI/bge-reranker-v2-m3`로 재정렬 |
| 답변 (CLI) | `ask.py` → Claude Code CLI 헤드리스 실행 (`.claude/agents/rag-answerer.md`: Opus 5.5, effort medium, 컨텍스트 근거만 사용) |
| 답변 (MCP) | `mcp_server.py`가 검색 도구를 제공하고, Claude Desktop·Codex·Claude Code 등 앱의 LLM이 검색 결과로 답변 |

## 빠른 시작

```bash
gh repo clone mordol/optirag && cd optirag
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
source env.sh                                   # JDK 21(Homebrew) + venv
python run_convert.py docs/ output/             # docs/에 PDF를 넣어 둔 상태에서 실행
python chunk.py output/ chunks.jsonl
python build_index.py
python ask.py "질문"                            # -k 10(기본), --no-llm(검색 결과만)
python mcp_server.py                            # MCP 서버 (http://127.0.0.1:8765/mcp) → 앱에서 질문
```

설치 요구 사항, 단계별 설명, 문장 제외 규칙 작성법, MCP 앱 연결(Claude Desktop·Codex·Claude Code), 문제 해결은 [SETUP_GUIDE.md](SETUP_GUIDE.md)를 참고하세요.
