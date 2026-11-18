# 반입 재료

사내망처럼 인터넷이 막힌 PC에 설치할 때 쓰는 파일을 모아 두는 폴더입니다.
인터넷이 되는 PC에서 키트 폴더를 AI 도구에서 열고 "E 드라이브에 반입용으로 담아 줘"처럼 요청하면 채워지고, 외장 드라이브로 복사까지 됩니다.

| 폴더 | 내용 | 크기 |
| --- | --- | --- |
| `wheels/` | sqlite-vec 설치 파일(Windows, macOS, Linux용). 저장소에 들어 있음 | 약 1MB |
| `ollama/windows/` | Ollama Windows 설치 파일 `OllamaSetup.exe` | 약 1.9GB |
| `ollama/mac/` | Ollama macOS 앱 `Ollama-darwin.zip` | 약 230MB |
| `python/windows/` | Windows용 Python 설치 파일 | 약 35MB |
| `models/` | 고른 임베딩 모델(기본 `qwen3-embedding:0.6b`, Ollama 모델 폴더와 같은 구조) | 모델마다 약 0.6~1.2GB |
| `MANIFEST.json` | 받은 파일 목록과 크기, 모델과 기본 모델 | |

사내 PC에서 "설치해 줘"라고 요청하면, 이 폴더에 있는 파일을 먼저 쓰고 인터넷에는 접속하지 않습니다.
