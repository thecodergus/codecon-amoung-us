"""Build das extensões Cython (Pure Python Mode) — ver plans/cython-pure-python-mode.md.

Compila todos os módulos de ``codecon_amoung_us`` EXCETO:

- ``protocol.py``: msgspec.Struct introspeciona ``Annotated``/``Meta`` na criação
  das classes; compilar poderia alterar a semântica de validação. Permanece puro.
- ``__init__.py``/``__main__.py``: entry points e pacotes permanecem puros.

Variáveis de ambiente:

- ``CODECON_SKIP_NATIVE=1``: não compila extensões (pacote 100% puro; usado no
  modo "puro" de paridade do CI e como fallback sem compilador C).
- ``CYTHON_ANNOTATE=1``: gera relatórios HTML de annotation ao lado dos fontes.
"""

import os
from pathlib import Path

from setuptools import Extension, setup

_SKIP_NATIVE = os.environ.get("CODECON_SKIP_NATIVE") == "1"
_ANNOTATE = os.environ.get("CYTHON_ANNOTATE") == "1"

_ROOT = Path(__file__).parent
_SRC = _ROOT / "src"
_PACKAGE = _SRC / "codecon_amoung_us"

# stems excluídos da compilação (qualquer diretório do pacote)
_EXCLUDED_STEMS = {"protocol", "__init__", "__main__"}


def _extension_modules() -> list[Extension]:
    modules: list[Extension] = []
    for path in sorted(_PACKAGE.rglob("*.py")):
        if path.stem in _EXCLUDED_STEMS:
            continue
        dotted = ".".join(path.relative_to(_SRC).with_suffix("").parts)
        modules.append(Extension(dotted, [str(path.relative_to(_ROOT))]))
    return modules


ext_modules = []
if _SKIP_NATIVE:
    # Paridade real do modo puro: remove extensões in-place de builds anteriores
    # (artefatos gerados por este próprio script; gitignored). Sem isso, o .so
    # residual em src/ continuaria ganhando do .py na importação.
    for stale in _PACKAGE.rglob("*.cpython-*.so"):
        stale.unlink()
else:
    from Cython.Build import cythonize

    ext_modules = cythonize(
        _extension_modules(),
        language_level="3str",
        annotate=_ANNOTATE,
    )

setup(ext_modules=ext_modules)
