#!/usr/bin/env bash
# Executar no checkout do servidor, após configurar .env.production.
set -euo pipefail
cd "$(dirname "$0")/.."
new_image="${1:?Informe a imagem GHCR com tag SHA ou digest imutável}"
if [[ ! "$new_image" =~ ^ghcr\.io/[a-z0-9._/-]+:(sha-)?[a-f0-9]{40}$ && ! "$new_image" =~ ^ghcr\.io/[a-z0-9._/-]+@sha256:[a-f0-9]{64}$ ]]; then
    echo "Use uma imagem GHCR com SHA completo ou digest sha256." >&2; exit 2
fi
[[ -f .env.production ]] || { echo "Configure .env.production primeiro." >&2; exit 2; }
compose=(docker compose --env-file .env.production)
previous_image="$("${compose[@]}" images -q app | xargs -r docker image inspect --format '{{.Id}}' | head -1)"
export APP_IMAGE="$new_image"
"${compose[@]}" config --quiet
"${compose[@]}" pull app caddy
if "${compose[@]}" up -d --no-build --wait --wait-timeout 180; then
    echo "Implantação saudável: $new_image"
else
    echo "Falha no health check. Restaurando a imagem anterior, quando disponível." >&2
    if [[ -n "$previous_image" ]]; then
        APP_IMAGE="$previous_image" "${compose[@]}" up -d --no-build --wait --wait-timeout 180
    fi
    exit 1
fi
# Persiste a referência para reinicializações, sem imprimir segredos.
python3 - "$new_image" <<'PY'
from pathlib import Path
import os, sys, tempfile
p=Path('.env.production')
lines=[line for line in p.read_text().splitlines() if not line.startswith('APP_IMAGE=')]
fd,temporary=tempfile.mkstemp(prefix='.env.deploy.',dir='.')
try:
    with os.fdopen(fd,'w') as f:f.write('\n'.join(lines+['APP_IMAGE='+sys.argv[1]])+'\n')
    os.replace(temporary,p)
finally:
    if os.path.exists(temporary):os.unlink(temporary)
PY
