# Ciclo completo de Blackboard: sesion, materiales, grabaciones y estado.
# Uso: .\bb-todo.ps1   (acepta los mismos argumentos que bb_todo.py, p. ej. --curso ERP)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
python bb_todo.py @args
exit $LASTEXITCODE
