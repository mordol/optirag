# OptiRAG 설치 및 사용 설명서

PDF 문서들을 넣고 전처리한 뒤, 질문하면 LLM이 문서 내용을 근거로 출처를 인용해 답하는 로컬 RAG 시스템입니다.

```
PDF ─(run_convert.py)→ output/*.json ─(chunk.py)→ chunks.jsonl ─(build_index.py)→ embeddings.npy
                                                                                     │
                     질문 ─(ask.py)→ 하이브리드 검색(bge-m3 + BM25) → reranker → top-k 청크 → LLM 답변
 Claude Desktop·Codex 질문 ─(mcp_server.py)→ 같은 검색 → 앱의 LLM이 답변
```

- 검증 환경: macOS (Apple Silicon), Python 3.12, OpenJDK 21. 2026-10-06에 빈 폴더에 새로 설치해 전 과정을 재현했습니다.
- 처음 한 번만 하는 설치(§1~§4)와, 문서가 바뀔 때마다 하는 전처리(§5~§7), 그리고 질의(§8 CLI, §9 Claude Desktop·Codex 앱)로 나뉩니다.

---

## 0. 준비물

| 항목 | 요구 사항 | 확인 명령 |
|---|---|---|
| Python | **3.12 권장** (3.10 이상). 3.14는 torch 호환 문제 가능 | `python3 --version` |
| Java | **11 이상** (opendataloader-pdf가 내부적으로 JVM 사용) | `java -version` |
| uv | Python 가상환경과 패키지 설치 도구 (pip로 대체 가능) | `uv --version` |
| Claude Code CLI | 답변 생성에 사용. 로그인된 상태여야 함 | `claude --version` |
| 디스크 | 약 8GB + 문서 출력분. 모델 약 6.4GB(첫 실행 시 자동 다운로드), 가상환경 약 0.9GB | |
| 네트워크 | 첫 실행 때 Hugging Face에서 모델 다운로드 | |

---

## 1. 프로젝트 받기

GitHub private 저장소 `mordol/optirag`에서 받습니다. 새 PC에서도 `gh auth login`으로 먼저 로그인하세요.

```bash
mkdir -p ~/Workspace && cd ~/Workspace && gh repo clone mordol/optirag && cd optirag
```

| 파일 | 용도 |
|---|---|
| `run_convert.py` | PDF → JSON/Markdown 변환 |
| `chunk.py` | JSON → 청크 (`chunks.jsonl`) |
| `build_index.py` | 청크 → 임베딩 (`embeddings.npy`) |
| `retriever.py` | 하이브리드 검색 엔진 (`ask.py`, `mcp_server.py`가 사용) |
| `ask.py` | 질의 실행 (CLI) |
| `mcp_server.py` | MCP 서버. Claude Desktop·Codex·Claude Code에 검색 도구 제공 (§9) |
| `search2.py`, `search.py` | 평가용. 평가 질의로 검색 방식(dense/BM25/hybrid/rerank) 비교 |
| `exclude_rules.example.yaml` | 문장 제외 규칙 예시 (§6) |
| `.claude/agents/rag-answerer.md` | 답변 생성 LLM의 규칙, 모델, effort 정의 |
| `requirements.txt`, `env.sh` | 환경 |
| `eval_queries.example.json` | 평가 질의 형식 예시 |

**저장소에 올리지 않는 것** (`.gitignore`가 허용한 파일만 올라가도록 막혀 있습니다):
- PDF와 그 파생물: 입력 PDF, `output/`, `chunks.jsonl`, `embeddings.npy`, `asks/`
- 실제 평가 질의 `eval_queries.json`: 문서 내용이 들어 있으므로 로컬에만 둡니다. 필요하면 예시 파일을 복사해 만드세요.
  ```bash
  cp eval_queries.example.json eval_queries.json
  ```
- 실제 문장 제외 규칙 `exclude_rules.yaml`: 문서 출처가 드러날 수 있으므로 로컬에만 둡니다 (§6).
- 서버 로그 `logs/`, 인덱스 정보 `index_manifest.json`

---

## 2. Java 설치

macOS (Homebrew):
```bash
brew install openjdk@21
```

설치 후 확인. 시스템 전역으로 등록하지 않았으므로 경로를 직접 지정합니다.
```bash
/opt/homebrew/opt/openjdk@21/bin/java -version
```

- Intel Mac은 경로가 `/usr/local/opt/openjdk@21`입니다. `env.sh`의 경로를 그에 맞게 고치세요.
- Linux: `sudo apt install openjdk-21-jre-headless`. 이 경우 Java가 이미 PATH에 있으므로 `env.sh`의 JDK 줄은 지워도 됩니다.
- Windows: Temurin JDK 21을 설치합니다. `env.sh` 대신 PowerShell에서 `.venv\Scripts\Activate.ps1`을 실행하세요.

---

## 3. Python 환경 설치

```bash
cd ~/Workspace/optirag
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

uv가 없으면:
```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
```

**새 터미널을 열 때마다** 먼저 실행하세요. Java PATH와 가상환경을 한 번에 잡습니다.
```bash
source env.sh
```

설치 확인:
```bash
python -c "import opendataloader_pdf, sentence_transformers, rank_bm25; print('ok')"
```

---

## 4. 답변 생성 LLM 확인 (Claude Code CLI)

`ask.py`는 `claude -p --agent rag-answerer ...`를 호출해 답변을 만듭니다.

1. 새 PC에 Claude Code를 설치하고 로그인합니다.
2. **프로젝트 폴더 안에서** 실행해야 `.claude/agents/rag-answerer.md`가 인식됩니다.

인식 확인:
```bash
claude -p --agent rag-answerer --model claude-opus-5-5 --effort medium --tools Read "준비됐으면 OK라고만 답하세요"
```

- 기본 설정: 모델 Opus 5.5, effort medium, 도구는 Read만 허용, 컨텍스트에 있는 내용만으로 답하고 `[S#]` 출처를 인용
- 답변 규칙을 바꾸려면 `.claude/agents/rag-answerer.md`를 수정합니다.

---

## 5. PDF 전처리: 변환

PDF를 한 폴더에 모읍니다(예: `docs/`).
- 하위 폴더 안의 PDF도 처리되지만, 출력은 `output/` 한 곳에 폴더 구분 없이 모입니다.
- **따라서 하위 폴더가 달라도 파일명이 같으면 서로 덮어씁니다.** 파일명이 겹치지 않게 해 주세요.
```bash
mkdir -p docs
```

전체를 **한 번의 호출로** 변환합니다. 호출할 때마다 JVM이 새로 뜨므로 파일별로 따로 돌리지 마세요.
```bash
python run_convert.py docs/ output/
```

- 결과: `output/` 아래에 문서마다 `<이름>.json`, `<이름>.md`, `<이름>_images/`가 생깁니다.
- 속도: 약 20페이지/초. 12,000페이지면 약 10분입니다.
- 모든 페이지에서 `WARNING: Detected background on page N`이 나올 수 있습니다. 배경 이미지가 있는 템플릿이라는 뜻이며 본문 손실은 없습니다.
- `*_images/` 폴더는 파이프라인에서 쓰지 않습니다. 샘플 기준 출력 용량의 97%를 차지하므로 디스크가 부족하면 지워도 됩니다.
  ```bash
  rm -rf output/*_images
  ```

---

## 6. PDF 전처리: 청킹

```bash
python chunk.py output/ chunks.jsonl
```

- 문서 구조(제목 계층)를 따라 512토큰 이하의 청크로 나눕니다. 표는 행 단위로 나누며 머리행과 캡션을 반복하고, 페이지를 넘는 표는 합칩니다.
- **글꼴 크기에 의존하지 않습니다.** 파서가 판단한 요소 종류, 텍스트 패턴, 위치만 씁니다. 글꼴·스타일이 문서마다 달라도 같은 규칙이 적용됩니다.
- 각 청크에는 `file`, `page`, `page_end`, `section`, `bbox`, `chunk_id`가 붙습니다. 답변의 출처 표시에 쓰입니다.

### 문장 제외 규칙 (선택)

모든 페이지에 반복되는 머리글·바닥글, 고지문, 페이지 번호처럼 검색에 방해되는 문구를 청킹 단계에서 지웁니다.
- 파서가 반복 머리글·바닥글을 상당 부분 이미 걸러 줍니다. **먼저 `chunks.jsonl`에 실제로 남는 문구가 있는지 확인**한 뒤 필요한 것만 추가하세요.
  ```bash
  grep -c "지우고 싶은 문구" chunks.jsonl
  ```
- 예시 파일을 복사해 `exclude_rules.yaml`을 만들고, `rules`에 정규식을 추가합니다. 이 파일은 저장소에 올라가지 않습니다.
  ```bash
  cp exclude_rules.example.yaml exclude_rules.yaml
  ```
  ```yaml
  rules:
    - pattern: "^Confidential - Internal use only$"   # 그 줄 전체가 이 문구일 때만
    - pattern: "^Page \\d+ of \\d+$"                  # 페이지 번호 줄
  ```

| 규칙 | 내용 |
|---|---|
| 매칭 방식 | 대소문자 무시, 줄 단위(`^`, `$`가 각 줄의 시작·끝). 매칭 전에 NFKC 정규화를 하므로 합자(ﬁ) 등은 ASCII(fi)로 적으면 됨 |
| 지우는 범위 | **매칭된 부분만** 지움. 단락이 통째로 비면 그 단락을 버림. 목록은 항목별로 적용 |
| 적용 대상 | 본문 단락과 목록만. 표, 제목, 캡션, 이미지에는 적용하지 않음 |
| 권장 | `^…$`로 줄 전체를 지정. 앵커 없이 `.*`를 쓰면 같은 줄의 본문까지 지워질 수 있음 |

- 실행하면 `exclude rules: N loaded`와 `chunks … | excluded elements: N`이 출력됩니다. 규칙 파일이 없으면 기존과 똑같이 동작합니다.
- `exclude_rules.yaml`이 있는데 `pyyaml`이 없으면 바로 오류가 납니다 → `requirements.txt` 다시 설치
- 규칙을 바꿨으면 `chunk.py`와 `build_index.py`를 다시 실행하세요.

---

## 7. 인덱스 생성 (임베딩)

```bash
python build_index.py
```

- 첫 실행 때 `BAAI/bge-m3` 모델(수 GB)을 내려받습니다.
- Apple Silicon 기준 약 50청크/초입니다. 청크 1.5만 개면 약 5분입니다.
- **`chunk.py`를 다시 돌렸다면 반드시 이 단계도 다시 실행하세요.** 청크와 임베딩의 개수가 맞지 않으면 `ask.py`와 MCP 서버가 오류를 냅니다.
- `index_manifest.json`에 임베딩 모델명과 청크 수가 기록됩니다. 검색 쪽은 이 파일로 인덱스가 맞는지 검사합니다.

---

## 8. 질의

```bash
python ask.py "managed heap 단편화를 줄이는 방법은?"
```

출력 예:
```
자료에 나온 managed heap 단편화 완화 방법은 … 입니다 [S1].
- … [S3]
출처: [S1] <파일명>.pdf p.13, [S3] <파일명>.pdf p.18

(컨텍스트: …/asks/20261006-155406.md | 비용 $0.092)
```

| 옵션 | 기본값 | 설명 |
|---|---|---|
| `-k N` | 10 | LLM에 넘길 청크 수. **권장 8~10**, 최대 30. 늘리면 답이 더 완전해지지만 비용이 늘어남 |
| `--no-llm` | – | LLM 없이 검색 결과(출처 목록)만 보기. 무료이고 빠름 |
| `--model` | `claude-opus-5-5` | 답변 모델 |
| `--effort` | `medium` | 추론 강도 |

- 질문마다 LLM에 넘긴 자료가 `asks/<시각>.md`에 저장됩니다. 답변이 이상하면 이 파일을 열어 검색이 문제였는지 답변이 문제였는지 확인할 수 있습니다.
- 비용과 시간: 질문당 약 $0.08~0.11, 15~30초. 모델 로딩에 10~20초가 걸리고, 이 시간은 실행할 때마다 듭니다.
- 영어로 질문해도 한국어 문서를 찾고, 그 반대도 됩니다.
- 자료에 없는 내용은 "제공된 자료에서 확인할 수 없습니다"라고 답하도록 되어 있습니다.

### 잘 되는 질문과 약한 질문

| 유형 | 예 | 상태 |
|---|---|---|
| 특정 사실 조회 | "○○ 문서에서 △△ 장면의 draw call 수는?" | 잘 됨 |
| 여러 문서 종합 | "GC allocation을 줄이는 방법은?" | 잘 됨 (k개 청크 범위 안에서 종합) |
| 표 수치 조회 | "○○ 표에서 △△ 항목의 값은?" | 대체로 됨. 실패하면 `-k`를 늘려 보세요 |
| **전부 나열 또는 세기** | "○○ 문제가 나온 문서를 전부 알려줘" | **약함.** k개 청크만 보므로 빠짐없이 나열할 수 없음 |
| 문서 전체의 경향 | "이 문서들의 주요 주제는?" | 약함 (전역 요약 기능 없음) |

---

## 9. Claude Desktop·Codex에서 질문하기 (MCP 서버)

`mcp_server.py`는 검색만 하는 서버입니다. 답변은 Claude Desktop, Codex 같은 **앱의 LLM이 검색 결과를 읽고 작성**합니다. 그래서 서버 쪽에 LLM 비용이 들지 않고, 앱 구독으로 답변을 받습니다.

| 도구 | 하는 일 |
|---|---|
| `search(query, k=10)` | 질문과 관련된 청크 k개를 찾음. 각 결과의 `title`이 출처(`파일명 p.N — 섹션`) |
| `fetch(id)` | 청크 전문과 앞뒤 청크 id. 결과가 잘려 보일 때 앱이 이어서 읽음 |
| `list_documents()` | 검색 대상 문서 목록(페이지 수, 청크 수) |

서버는 앱에 "검색 결과만 근거로, `파일명 p.N`을 인용해서, 없으면 확인할 수 없다고 답하라"는 안내문을 함께 보냅니다. 다만 `ask.py`처럼 강제하는 것이 아니라 앱의 LLM에 맡기는 방식입니다.

### 9-1. 서버 실행 (Codex·Claude Code용)

```bash
cd ~/Workspace/optirag && source env.sh
python mcp_server.py            # http://127.0.0.1:8765/mcp
```

- 시작할 때 모델을 한 번 불러오고(약 10초) 계속 떠 있습니다. **이 터미널을 닫으면 서버도 꺼집니다.** 앱에서 질문하는 동안 켜 두세요.
- `build_index.py`를 다시 돌리면 서버를 재시작하지 않아도 다음 검색부터 새 인덱스를 씁니다.
- 요청 기록: `logs/requests.jsonl` (질의, 반환한 청크 id, 처리 시간)

| 환경 변수 | 기본값 | 설명 |
|---|---|---|
| `OPTIRAG_RERANK` | `1` | `0`이면 reranker를 끔. 메모리 약 4GB → 약 2GB, CPU에서 훨씬 빠름. 샘플 평가에서는 정확도 차이가 없었음 |
| `OPTIRAG_K` | `10` | `search`의 기본 반환 개수 (앱이 1~30 사이로 바꿀 수 있음) |
| `OPTIRAG_PORT` | `8765` | 포트 |

예: `OPTIRAG_RERANK=0 python mcp_server.py`

Claude Desktop은 서버를 직접 실행하므로(§9-3) 이 단계가 필요 없습니다.

### 9-2. Codex (앱·CLI)

서버(§9-1)를 켠 상태에서 한 번만 등록합니다. Codex 앱과 CLI는 같은 설정 파일(`~/.codex/config.toml`)을 씁니다.

```bash
codex mcp add optirag --url http://127.0.0.1:8765/mcp
codex mcp list                  # optirag … enabled 확인
```

직접 편집해도 됩니다:
```toml
[mcp_servers.optirag]
url = "http://127.0.0.1:8765/mcp"
```

질문 예: `optirag로 검색해서 managed heap 단편화를 줄이는 방법을 정리해줘`

### 9-3. Claude Desktop

Claude Desktop은 설정 파일에 적힌 명령으로 서버를 **직접 실행**합니다(stdio 방식). 그래서 §9-1의 서버를 켤 필요가 없습니다.

1. `~/Library/Application Support/Claude/claude_desktop_config.json`에 `mcpServers`를 추가합니다. 파일에 다른 항목이 있으면 그대로 두고 이 키만 넣으세요. 경로는 **절대 경로**로, 본인 위치에 맞게 바꿉니다.
   ```json
   {
     "mcpServers": {
       "optirag": {
         "command": "/Users/<사용자>/Workspace/optirag/.venv/bin/python",
         "args": ["/Users/<사용자>/Workspace/optirag/mcp_server.py", "--stdio"],
         "env": {"OPTIRAG_RERANK": "1"}
       }
     }
   }
   ```
2. Claude Desktop을 **⌘Q로 완전히 종료**하고 다시 엽니다. 창만 닫으면 설정을 다시 읽지 않습니다.
3. 채팅 입력창의 도구 아이콘(＋ 또는 슬라이더 모양)에서 `optirag`가 보이고 켜져 있는지 확인합니다.
4. 평소처럼 질문합니다. 처음 도구를 쓸 때 허용 여부를 물으면 "항상 허용"을 고르세요.

- 앱을 켠 뒤 첫 검색은 모델을 불러오느라 약 10초 걸립니다.
- Java는 필요 없습니다. 가상환경 python만 있으면 됩니다.
- **메모리:** 이 프로세스는 §9-1의 HTTP 서버와 별개라서 모델을 따로 올립니다. 둘 다 켜면 reranker 기준 최대 약 8GB입니다. RAM이 16GB 이하이면 `"OPTIRAG_RERANK": "0"`을 권합니다.
- 연결이 안 되면 **Settings → Developer**에서 optirag 상태를 보고, 로그 `~/Library/Logs/Claude/mcp-server-optirag.log`를 확인하세요.

### 9-4. Claude Code

서버(§9-1)를 켠 상태에서:
```bash
claude mcp add --transport http optirag http://127.0.0.1:8765/mcp
```

### 9-5. 질문 요령

- 앱의 LLM이 검색할지 스스로 정합니다. 일반 지식처럼 보이는 질문은 검색 없이 답할 수 있으니, **"optirag로 검색해서", "문서에서 찾아서"**를 붙이면 확실합니다.
- 매번 붙이기 번거로우면 Claude Desktop의 **Project 지침**(또는 Codex의 `AGENTS.md`)에 이렇게 적어 두세요:
  > 모든 질문은 먼저 optirag의 search 도구로 문서를 검색하고, 검색 결과만 근거로 `파일명 p.N`을 인용해 답한다.
- 제대로 동작하면 답변에 `search` 도구 호출이 표시되고, 문장마다 `파일명 p.N` 출처가 붙습니다.
- 여러 주제를 묻는 질문은 앱이 알아서 2~4번 나눠 검색합니다. 샘플 평가에서 사실 질의 7개를 모두 맞혔고, 자료에 없는 질문은 확인할 수 없다고 답했습니다.
- ChatGPT, claude.ai 웹처럼 **클라우드에서 도구를 호출하는 앱은 `127.0.0.1`에 접속할 수 없습니다.** 공개 HTTPS 주소(예: Tailscale Funnel)가 필요하며 이 설명서 범위 밖입니다.

---

## 10. 문서 추가·교체

증분 갱신 기능은 없습니다. 문서가 바뀌면 §5~§7을 처음부터 다시 실행합니다. 300개 기준으로 전체 약 20분입니다.
```bash
rm -rf output && python run_convert.py docs/ output/ && python chunk.py output/ chunks.jsonl && python build_index.py
```

---

## 11. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `Unable to locate a Java Runtime` | `source env.sh`를 안 했거나 JDK 경로가 다름 → §2 |
| `ModuleNotFoundError` | 가상환경이 활성화되지 않음 → `source env.sh` |
| `embeddings.npy가 chunks.jsonl과 맞지 않음` | 청킹 후 인덱스를 다시 안 만듦 → `python build_index.py` |
| `claude 실행 실패` / `Agent type 'rag-answerer' not found` | 저장소 폴더 밖에서 실행했거나 `.claude/agents/`가 없음 → §1, §4 |
| 답변이 "확인할 수 없습니다"인데 문서엔 내용이 있음 | 검색 순위 밖에 있을 가능성 → `-k 15`로 다시 시도. `--no-llm`으로 어떤 청크가 잡히는지 확인 |
| 모델 다운로드가 느리거나 실패 | 네트워크·프록시 확인. 캐시 위치는 `~/.cache/huggingface` |
| 앱 질문 시 연결 오류 (Codex, Claude Code) | MCP 서버가 꺼져 있음 → §9-1로 다시 실행 |
| Claude Desktop에 optirag가 안 보임 | ⌘Q로 완전히 종료 후 재실행. 설정 JSON 문법과 절대 경로 확인. Settings → Developer, `~/Library/Logs/Claude/mcp-server-optirag.log` |
| 앱이 optirag를 안 쓰고 답함 | 질문에 "optirag로 검색해서"를 붙이거나 Project 지침에 넣기 → §9-5 |
| `인덱스 불일치` (서버 또는 `ask.py`) | 청킹 후 인덱스를 다시 안 만듦 → `python build_index.py` |
| `exclude_rules.yaml이 있지만 pyyaml이 없습니다` | `uv pip install --python .venv/bin/python -r requirements.txt` |
| 표가 깨지거나 본문이 누락됨 | `output/<문서>.md`를 원본 PDF와 비교. 스캔본(이미지 PDF)은 지원하지 않음 (OCR 없음) |

---

## 12. 파일 구조 (실행 후)

```
optirag/
├── .claude/agents/rag-answerer.md   # 답변 LLM 정의 (모델·effort·규칙)
├── env.sh  requirements.txt
├── run_convert.py  chunk.py  build_index.py  retriever.py  ask.py  mcp_server.py
├── search.py  search2.py       # 평가용
├── eval_queries.example.json   # (eval_queries.json은 로컬 전용)
├── exclude_rules.example.yaml  # (exclude_rules.yaml은 로컬 전용, 선택)
├── docs/                 # 입력 PDF (직접 넣음)
├── output/               # 변환 결과 (.json/.md/_images)
├── chunks.jsonl          # 청크
├── embeddings.npy        # 임베딩
├── index_manifest.json   # 임베딩 모델명·청크 수
├── logs/requests.jsonl   # MCP 서버 요청 기록
└── asks/                 # 질문별 LLM 입력 기록
```
