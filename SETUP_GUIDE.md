# OptiRAG 설치 및 사용 설명서

PDF 문서들을 넣고 전처리한 뒤, 질문하면 LLM이 문서 내용을 근거로 출처를 인용해 답하는 로컬 RAG 시스템입니다.

```
PDF ─(run_convert.py)→ output/*.json ─(chunk.py)→ chunks.jsonl ─(build_index.py)→ embeddings.npy
                                                                                     │
                     질문 ─(ask.py)→ 하이브리드 검색(bge-m3 + BM25) → reranker → top-k 청크 → LLM 답변
```

- 검증 환경: macOS (Apple Silicon), Python 3.12, OpenJDK 21. 2026-10-06에 빈 폴더에 새로 설치해 전 과정을 재현했습니다.
- 처음 한 번만 하는 설치(§1~§4)와, 문서가 바뀔 때마다 하는 전처리(§5~§7), 그리고 질의(§8)로 나뉩니다.

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
| `search2.py` | 하이브리드 검색 엔진 (`ask.py`가 사용). 직접 실행하면 평가 질의로 검색 방식을 비교 |
| `search.py` | 평가 질의 로딩, dense 검색 평가 |
| `ask.py` | 질의 실행 |
| `.claude/agents/rag-answerer.md` | 답변 생성 LLM의 규칙, 모델, effort 정의 |
| `requirements.txt`, `env.sh` | 환경 |
| `eval_queries.example.json` | 평가 질의 형식 예시 |

**저장소에 올리지 않는 것** (`.gitignore`가 허용한 파일만 올라가도록 막혀 있습니다):
- PDF와 그 파생물: 입력 PDF, `output/`, `chunks.jsonl`, `embeddings.npy`, `asks/`
- 실제 평가 질의 `eval_queries.json`: 문서 내용이 들어 있으므로 로컬에만 둡니다. 필요하면 예시 파일을 복사해 만드세요.
  ```bash
  cp eval_queries.example.json eval_queries.json
  ```

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

---

## 7. 인덱스 생성 (임베딩)

```bash
python build_index.py
```

- 첫 실행 때 `BAAI/bge-m3` 모델(수 GB)을 내려받습니다.
- Apple Silicon 기준 약 50청크/초입니다. 청크 1.5만 개면 약 5분입니다.
- **`chunk.py`를 다시 돌렸다면 반드시 이 단계도 다시 실행하세요.** 청크와 임베딩의 개수가 맞지 않으면 `ask.py`가 오류를 냅니다.

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

## 9. 문서 추가·교체

증분 갱신 기능은 없습니다. 문서가 바뀌면 §5~§7을 처음부터 다시 실행합니다. 300개 기준으로 전체 약 20분입니다.
```bash
rm -rf output && python run_convert.py docs/ output/ && python chunk.py output/ chunks.jsonl && python build_index.py
```

---

## 10. 문제 해결

| 증상 | 원인 / 해결 |
|---|---|
| `Unable to locate a Java Runtime` | `source env.sh`를 안 했거나 JDK 경로가 다름 → §2 |
| `ModuleNotFoundError` | 가상환경이 활성화되지 않음 → `source env.sh` |
| `embeddings.npy가 chunks.jsonl과 맞지 않음` | 청킹 후 인덱스를 다시 안 만듦 → `python build_index.py` |
| `claude 실행 실패` / `Agent type 'rag-answerer' not found` | 저장소 폴더 밖에서 실행했거나 `.claude/agents/`가 없음 → §1, §4 |
| 답변이 "확인할 수 없습니다"인데 문서엔 내용이 있음 | 검색 순위 밖에 있을 가능성 → `-k 15`로 다시 시도. `--no-llm`으로 어떤 청크가 잡히는지 확인 |
| 모델 다운로드가 느리거나 실패 | 네트워크·프록시 확인. 캐시 위치는 `~/.cache/huggingface` |
| 표가 깨지거나 본문이 누락됨 | `output/<문서>.md`를 원본 PDF와 비교. 스캔본(이미지 PDF)은 지원하지 않음 (OCR 없음) |

---

## 11. 파일 구조 (실행 후)

```
optirag/
├── .claude/agents/rag-answerer.md   # 답변 LLM 정의 (모델·effort·규칙)
├── env.sh  requirements.txt
├── run_convert.py  chunk.py  build_index.py  search.py  search2.py  ask.py
├── eval_queries.example.json   # (eval_queries.json은 로컬 전용)
├── docs/                 # 입력 PDF (직접 넣음)
├── output/               # 변환 결과 (.json/.md/_images)
├── chunks.jsonl          # 청크
├── embeddings.npy        # 임베딩
└── asks/                 # 질문별 LLM 입력 기록
```
