# Windows 실행 도우미. 이미 설치된 프로젝트 환경을 우선 사용합니다.
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv-1/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    $projectPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
}
if (-not (Test-Path -LiteralPath $projectPython)) {
    py -3.14 -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.14 설치와 py 런처를 확인하세요.' }
    $projectPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
    & $projectPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw '의존성 설치 실패. 네트워크 및 requirements.txt를 확인하세요.' }
}
& $projectPython -m streamlit run app.py
