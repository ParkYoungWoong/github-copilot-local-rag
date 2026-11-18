@echo off
setlocal
set "RAG_DIR=%~dp0.."
if not exist "%RAG_DIR%\.venv\Scripts\python.exe" (
  echo [local-rag] Not installed on this PC yet, or the folder came from another PC. Open the local-rag folder in VS Code and ask Copilot to install it. 1>&2
  exit /b 1
)
"%RAG_DIR%\.venv\Scripts\python.exe" "%RAG_DIR%\rag.py" %*
exit /b %ERRORLEVEL%
