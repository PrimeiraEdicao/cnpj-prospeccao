#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
CNPJ_VENV="$PROJECT_ROOT/.venv-cnpj312"

if [[ ! -x "$CNPJ_VENV/bin/python" ]]; then
    if command -v python3.12 >/dev/null 2>&1; then
        python3.12 -m venv "$CNPJ_VENV"
    else
        # Codespaces existentes podem usar Python 3.14. O uv instala 3.12
        # para este projeto sem substituir o Python global do Codespace.
        python -m pip install --user uv
        python -m uv venv --python 3.12 --seed "$CNPJ_VENV"
    fi
fi

"$CNPJ_VENV/bin/python" -c \
    'import sys; assert sys.version_info[:2] == (3, 12), "O projeto requer Python 3.12"; print("Python do app:", sys.version.split()[0])'

# O PyArrow tem wheel para 3.12. Nunca tenta compilar Arrow/C++ por engano.
"$CNPJ_VENV/bin/python" -m pip install --only-binary=pyarrow -r requirements.txt

if [[ "${1:-}" == "--setup-only" ]]; then
    exit 0
fi

echo "Abra a porta 8501 na aba Ports do Codespaces."
exec "$CNPJ_VENV/bin/python" -m streamlit run app.py \
    --server.address 0.0.0.0 --server.port 8501
