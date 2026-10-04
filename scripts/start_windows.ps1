$ErrorActionPreference = "Stop"
$PortableRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $PortableRoot "app")
New-Item -ItemType Directory -Force -Path (Join-Path $PortableRoot "logs") | Out-Null
$Backend = (Get-Content (Join-Path $PortableRoot "config\backend") -Raw).Trim()
$env:LLM_BACKEND = $Backend
$env:LLM_EMBED_BACKEND = $Backend
$env:LLM_KB_ROOT = Join-Path $PortableRoot "kb"
$env:PYTHONNOUSERSITE = "1"
$Python = Join-Path $PortableRoot "runtime\python\python.exe"
$Processes = @()
try {
  if ($Backend -eq "ollama") {
    & $Python (Join-Path $PortableRoot "app\scripts\check_ports.py") 8765 11434
    if ($LASTEXITCODE -ne 0) { throw "Required loopback port is already in use." }
    $env:OLLAMA_HOST = "127.0.0.1:11434"
    $env:OLLAMA_HOST_URL = "http://127.0.0.1:11434"
    $env:OLLAMA_MODELS = Join-Path $PortableRoot "models\ollama"
    $Processes += Start-Process -FilePath (Join-Path $PortableRoot "backends\ollama\ollama.exe") -ArgumentList "serve" -RedirectStandardOutput (Join-Path $PortableRoot "logs\ollama.log") -RedirectStandardError (Join-Path $PortableRoot "logs\ollama-error.log") -PassThru -WindowStyle Hidden
  } else {
    & $Python (Join-Path $PortableRoot "app\scripts\check_ports.py") 8765 8080 8081
    if ($LASTEXITCODE -ne 0) { throw "Required loopback port is already in use." }
    $env:LLAMA_CPP_CHAT_HOST = "http://127.0.0.1:8080"
    $env:LLAMA_CPP_EMBED_HOST = "http://127.0.0.1:8081"
    $Server = Join-Path $PortableRoot "backends\llama.cpp\llama-server.exe"
    $Processes += Start-Process -FilePath $Server -ArgumentList @("-m", (Join-Path $PortableRoot "models\chat.gguf"), "--alias", "qwen3:4b", "--host", "127.0.0.1", "--port", "8080") -RedirectStandardOutput (Join-Path $PortableRoot "logs\llama-chat.log") -RedirectStandardError (Join-Path $PortableRoot "logs\llama-chat-error.log") -PassThru -WindowStyle Hidden
    $Processes += Start-Process -FilePath $Server -ArgumentList @("-m", (Join-Path $PortableRoot "models\embed.gguf"), "--alias", "bge-m3", "--embedding", "--host", "127.0.0.1", "--port", "8081") -RedirectStandardOutput (Join-Path $PortableRoot "logs\llama-embed.log") -RedirectStandardError (Join-Path $PortableRoot "logs\llama-embed-error.log") -PassThru -WindowStyle Hidden
  }
  $Processes += Start-Process -FilePath $Python -ArgumentList @("-m", "ui.server", "--host", "127.0.0.1", "--port", "8765") -WorkingDirectory (Join-Path $PortableRoot "app") -RedirectStandardOutput (Join-Path $PortableRoot "logs\ui.log") -RedirectStandardError (Join-Path $PortableRoot "logs\ui-error.log") -PassThru -WindowStyle Hidden
  & $Python (Join-Path $PortableRoot "app\scripts\wait_ready.py") "http://127.0.0.1:8765"
  Wait-Process -Id $Processes[-1].Id
} finally {
  foreach ($Process in $Processes) { if (!$Process.HasExited) { Stop-Process -Id $Process.Id -Force } }
}
