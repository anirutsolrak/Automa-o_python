#!/bin/bash
#
# Script Wrapper - Automação Plaud
# Garante que o venv está ativado antes de executar
#
# Caminho: /opt/plaud/run_automation.sh
# Executar: bash /opt/plaud/run_automation.sh
#

# ============================================================================
# CONFIGURAÇÕES
# ============================================================================
PROJECT_DIR="/opt/plaud"
VENV_DIR="$PROJECT_DIR/venv"
SCRIPT="$PROJECT_DIR/plaud_vps_producao.py"
LOG_DIR="$PROJECT_DIR/logs_producao"

# ============================================================================
# VALIDAÇÕES
# ============================================================================

# Verificar se está no diretório correto
if [ ! -d "$PROJECT_DIR" ]; then
    echo "[ERRO] Diretório do projeto não encontrado: $PROJECT_DIR"
    exit 1
fi

# Verificar se venv existe
if [ ! -d "$VENV_DIR" ]; then
    echo "[ERRO] Virtualenv não encontrado: $VENV_DIR"
    exit 1
fi

# Verificar se script existe
if [ ! -f "$SCRIPT" ]; then
    echo "[ERRO] Script não encontrado: $SCRIPT"
    exit 1
fi

# ============================================================================
# EXECUÇÃO
# ============================================================================

# Ir para diretório do projeto
cd "$PROJECT_DIR" || exit 1

# Log de início
echo "=================================================="
echo "AUTOMAÇÃO PLAUD - INÍCIO"
echo "Data/Hora: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Diretório: $(pwd)"
echo "=================================================="

# Ativar virtualenv
echo "[1] Ativando virtualenv..."
source "$VENV_DIR/bin/activate"

if [ $? -ne 0 ]; then
    echo "[ERRO] Falha ao ativar virtualenv"
    exit 1
fi

echo "[OK] Virtualenv ativado: $VIRTUAL_ENV"

# Verificar versão do Python
echo "[2] Verificando Python..."
python3 --version

# Executar script principal
echo "[3] Executando automação..."
python3 "$SCRIPT"

EXIT_CODE=$?

# Desativar virtualenv
deactivate 2>/dev/null

# Log de fim
echo "=================================================="
echo "AUTOMAÇÃO PLAUD - FIM"
echo "Data/Hora: $(date '+%Y-%m-%d %H:%M:%S')"
echo "Exit Code: $EXIT_CODE"
echo "=================================================="

# Retornar código de saída do script Python
exit $EXIT_CODE
