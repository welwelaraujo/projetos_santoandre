# Rotina diária: coleta as proposições da Câmara, grava e envia ao GitHub (o push publica o site).
# Roda pelo Agendador de Tarefas do Windows ("Projetos Santo André - coleta diária").
# Precisa rodar daqui: o portal da Câmara não responde aos servidores do GitHub Actions.

$ErrorActionPreference = 'Stop'
$repo = Split-Path -Parent $PSScriptRoot
$log = Join-Path $repo 'scripts\rotina_diaria.log'
Set-Location $repo

function Registrar($msg) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $msg" | Out-File -Append -Encoding utf8 $log }

try {
    Registrar 'início'
    git pull --quiet --rebase
    python scripts/coletar.py 2>&1 | Out-File -Append -Encoding utf8 $log
    if ($LASTEXITCODE -ne 0) { throw "coletar.py terminou com código $LASTEXITCODE" }
    git add docs/dados
    git diff --cached --quiet
    if ($LASTEXITCODE -ne 0) {
        git commit --quiet -m "Coleta diária $(Get-Date -Format 'yyyy-MM-dd')"
        git push --quiet
        Registrar 'dados enviados'
    } else {
        Registrar 'sem mudanças'
    }
} catch {
    Registrar "ERRO: $_"
    exit 1
}
