#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"
CNPJ_VENV="$PROJECT_ROOT/.venv-cnpj312"

venv_ready() {
    [[ -x "$CNPJ_VENV/bin/python" ]] &&
        "$CNPJ_VENV/bin/python" -c \
            'import sys, pip; assert sys.version_info[:2] == (3, 12)' \
            >/dev/null 2>&1
}

if ! venv_ready; then
    # A presença do executável não garante um ambiente completo: quando
    # ensurepip está ausente, o venv deixa bin/python, mas não instala pip.
    if command -v python3.12 >/dev/null 2>&1; then
        if ! python3.12 -m venv "$CNPJ_VENV"; then
            echo "Não foi possível preparar o venv padrão; usando uv."
        fi
    fi

    if ! venv_ready; then
        # uv cria e instala pip sem depender de ensurepip/python3.12-venv.
        # --clear recria apenas o ambiente de dependências deste projeto.
        if ! python -m uv --version >/dev/null 2>&1; then
            python -m pip install --user uv
        fi
        python -m uv venv --python 3.12 --seed --clear "$CNPJ_VENV"
    fi
fi

"$CNPJ_VENV/bin/python" -c \
    'import sys; assert sys.version_info[:2] == (3, 12), "O projeto requer Python 3.12"; print("Python do app:", sys.version.split()[0])'

# O PyArrow tem wheel para 3.12. Nunca tenta compilar Arrow/C++ por engano.
CNPJ_REQUIREMENTS=requirements.txt
[[ ! -f requirements.lock ]] || CNPJ_REQUIREMENTS=requirements.lock
"$CNPJ_VENV/bin/python" -m pip install --only-binary=pyarrow -r "$CNPJ_REQUIREMENTS"

if [[ "${1:-}" == "--setup-only" ]]; then
    exit 0
fi

echo "Abra a porta 8501 na aba Ports do Codespaces."
exec "$CNPJ_VENV/bin/python" -m streamlit run app.py \
    --server.address 0.0.0.0 --server.port 8501
