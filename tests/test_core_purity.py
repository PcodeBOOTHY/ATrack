"""core/ must stay free of Streamlit so it can be unit tested in isolation."""

import ast
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parent.parent / "core"


@pytest.mark.parametrize("path", sorted(CORE.glob("*.py")), ids=lambda p: p.name)
def test_no_streamlit_imports(path):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any(n.split(".")[0] == "streamlit" for n in names), f"{path.name} imports streamlit"
