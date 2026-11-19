# Instala lo necesario en Windows. Uso: .\instalar.ps1
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Host "Falta Python 3. Instalalo desde https://www.python.org/downloads/ (marca 'Add python.exe to PATH') y vuelve a correr este script."
    exit 1
}
python -m pip install --upgrade -r requirements.txt
$chrome = @("$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
            "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
            "$env:LocalAppData\Google\Chrome\Application\chrome.exe") | Where-Object { Test-Path $_ }
if (-not $chrome) {
    Write-Host "Falta Google Chrome: instalalo desde https://www.google.com/chrome/ antes de usar bb-todo."
    exit 1
}
Write-Host "`nListo. Ahora corre: .\bb-todo.ps1"
