# source env.sh — JDK 21(brew) + 프로젝트 venv 활성화
export PATH=/opt/homebrew/opt/openjdk@21/bin:$PATH
source "$(dirname "${BASH_SOURCE[0]:-$0}")/.venv/bin/activate"
