"""OptiRAG MCP 서버: 문서 검색 도구(search / fetch / list_documents)를 제공. 답변 작성은 클라이언트(Claude, ChatGPT, Codex)의 LLM이 함
usage:
  python mcp_server.py            # Streamable HTTP  http://127.0.0.1:8765/mcp  (Codex, ChatGPT용 상주 서버)
  python mcp_server.py --stdio    # stdio (Claude Desktop 등 로컬 앱이 직접 실행)
env:
  OPTIRAG_RERANK=1|0      reranker 사용 (기본 1)
  OPTIRAG_K=10            search 기본 반환 수
  OPTIRAG_PORT=8765       HTTP 포트
  OPTIRAG_PATH_TOKEN=...  지정하면 경로가 /<token>/mcp 가 됨 (외부 공개 시 비밀 경로)"""
import json, os, sys, time
from urllib.parse import quote

BASE = os.path.dirname(os.path.abspath(__file__))
os.chdir(BASE)  # 로컬 앱이 다른 작업 폴더에서 실행해도 인덱스를 찾도록

from mcp.server.mcpserver import MCPServer  # noqa: E402
from mcp.types import ToolAnnotations  # noqa: E402
from retriever import Retriever  # noqa: E402

DEFAULT_K = int(os.environ.get("OPTIRAG_K", 10))
LOG = os.path.join(BASE, "logs", "requests.jsonl")
READ_ONLY = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

INSTRUCTIONS = """OptiRAG: 사용자가 넣어 둔 PDF 문서 모음을 검색하는 도구입니다.
- 문서 내용에 관한 질문이면 먼저 search를 호출하세요. 질문이 여러 주제면 주제별로 나눠 여러 번 검색해도 됩니다.
- 답변은 반환된 text에 있는 내용만 근거로 쓰고, 자체 지식을 섞지 마세요. 필요하면 "문서 외 일반 지식"이라고 구분해 표시하세요.
- 사실 문장마다 출처를 `파일명 p.페이지` 형식으로 인용하세요 (title 필드 사용). 숫자는 원문 그대로 옮기세요.
- 검색 결과에 답이 없으면 "검색된 문서에서 확인할 수 없습니다"라고 답하고 추측하지 마세요.
- 서로 다른 문서의 같은 이름 항목(같은 지표, 같은 장면 등)을 섞지 마세요.
- 결과가 잘려 보이면 fetch로 앞뒤 청크(prev_id, next_id)를 읽을 수 있습니다."""

mcp = MCPServer(name="optirag", title="OptiRAG 문서 검색", instructions=INSTRUCTIONS)
retriever = Retriever(BASE, rerank=os.environ.get("OPTIRAG_RERANK", "1") == "1")


def _title(c):
    pg = f"p.{c['page']}" + (f"-{c['page_end']}" if c["page_end"] != c["page"] else "")
    return f"{c['file']} {pg} — {c['section']}"


def _url(c):
    return f"optirag://{quote(c['file'])}#page={c['page']}"


def _log(**kw):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), **kw}, ensure_ascii=False) + "\n")


@mcp.tool(annotations=READ_ONLY)
def search(query: str, k: int = DEFAULT_K) -> dict:
    """문서 모음에서 질문과 관련된 본문 조각(청크)을 찾습니다. 한국어·영어 질의 모두 가능.
    k: 반환 개수 (기본 10, 최대 30). 각 결과의 title(파일명 p.페이지 — 섹션)을 출처로 인용하세요."""
    t = time.perf_counter()
    k = max(1, min(int(k), 30))
    hits = retriever.search(query, k)
    _log(tool="search", query=query, k=k, ids=[c["chunk_id"] for c in hits], ms=int((time.perf_counter() - t) * 1000))
    return {"results": [{"id": c["chunk_id"], "title": _title(c), "url": _url(c), "text": c["text"].split("\n", 1)[1]}
                        for c in hits]}


@mcp.tool(annotations=READ_ONLY)
def fetch(id: str) -> dict:
    """search 결과의 id로 청크 전문과 메타데이터, 앞뒤 청크 id(prev_id, next_id)를 가져옵니다."""
    c, prev_id, next_id = retriever.get(id)
    _log(tool="fetch", id=id, found=c is not None)
    if c is None:
        return {"id": id, "error": "해당 id의 청크가 없습니다"}
    return {"id": id, "title": _title(c), "url": _url(c), "text": c["text"].split("\n", 1)[1],
            "metadata": {"file": c["file"], "page": c["page"], "page_end": c["page_end"], "section": c["section"],
                         "prev_id": prev_id, "next_id": next_id}}


@mcp.tool(annotations=READ_ONLY)
def list_documents() -> dict:
    """검색 대상 문서 목록(파일명, 페이지 수, 청크 수)을 반환합니다."""
    docs = retriever.documents()
    return {"documents": docs, "total_documents": len(docs), "total_chunks": sum(d["chunks"] for d in docs)}


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run("stdio")
    else:
        token = os.environ.get("OPTIRAG_PATH_TOKEN")
        mcp.run("streamable-http", host="127.0.0.1", port=int(os.environ.get("OPTIRAG_PORT", 8765)),
                streamable_http_path=f"/{token}/mcp" if token else "/mcp")
