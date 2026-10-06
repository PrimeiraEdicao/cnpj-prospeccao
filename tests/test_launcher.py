"""Regressões do launcher com Python disponível, mas ensurepip ausente."""

import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest


@pytest.mark.parametrize("existing", ["absent", "without-pip", "ready"])
def test_launcher_recovers_incomplete_venv(tmp_path, existing):
    root = tmp_path / "project"
    scripts = root / "scripts"
    scripts.mkdir(parents=True)
    source = Path(__file__).resolve().parents[1] / "scripts/run_app.sh"
    shutil.copyfile(source, scripts / "run_app.sh")
    # Instalação vazia: testa a recuperação sem acesso à rede.
    (root / "requirements.txt").write_text("")
    venv = root / ".venv-cnpj312"
    if existing != "absent":
        args = [sys.executable, "-m", "venv"]
        if existing == "without-pip":
            args.append("--without-pip")
        subprocess.run([*args, str(venv)], check=True)

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    real_python = shlex.quote(sys.executable)
    log = tmp_path / "calls.log"
    # Reproduz a falha real: venv deixa um Python executável sem pip.
    broken_python = bin_dir / "python3.12"
    broken_python.write_text(
        f"#!/bin/bash\n{real_python} -m venv --without-pip \"$3\"\n"
        'echo "ensurepip is not available" >&2\nexit 1\n'
    )
    broken_python.chmod(0o755)
    # Simula apenas a criação pelo uv, usando o Python completo do teste.
    # As verificações de versão/pip e a instalação no venv são reais.
    fallback_python = bin_dir / "python"
    fallback_python.write_text(
        '#!/bin/bash\nset -eu\n'
        'if [[ "$1" == "-m" && "$2" == "uv" ]]; then\n'
        '  if [[ "$3" == "--version" ]]; then exit 0; fi\n'
        '  [[ "$3 $4 $5 $6 $7" == "venv --python 3.12 --seed --clear" ]]\n'
        f'  echo uv >> {shlex.quote(str(log))}\n'
        f'  exec {real_python} -m venv --clear "$8"\n'
        'fi\n'
        f'exec {real_python} "$@"\n'
    )
    fallback_python.chmod(0o755)
    env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}",
               PIP_DISABLE_PIP_VERSION_CHECK="1", PIP_NO_INDEX="1")
    result = subprocess.run(
        ["bash", str(scripts / "run_app.sh"), "--setup-only"],
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Python do app: 3.12" in result.stdout
    assert log.exists() == (existing != "ready")
    subprocess.run([str(venv / "bin/python"), "-m", "pip", "--version"], check=True)
    # Uma segunda execução deve reutilizar o ambiente recuperado.
    if log.exists():
        log.unlink()
    subprocess.run(
        ["bash", str(scripts / "run_app.sh"), "--setup-only"],
        env=env, check=True, capture_output=True, timeout=60,
    )
    assert not log.exists()
