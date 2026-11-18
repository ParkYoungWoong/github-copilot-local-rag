@echo off
setlocal
set "RAG_DIR=%~dp0.."
if not exist "%RAG_DIR%\.venv\Scripts\python.exe" (
  echo [local-rag] Not installed on this PC yet, or the folder came from another PC. Open the local-rag kit folder in your AI tool, for example Copilot in VS Code or Claude Code, and ask it to install. 1>&2
  exit /b 1
)
"%RAG_DIR%\.venv\Scripts\python.exe" "%RAG_DIR%\rag.py" %*
exit /b %ERRORLEVEL%
