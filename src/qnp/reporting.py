"""Self-contained HTML rendering. No CDN, web server, telemetry or provider access."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
from importlib.resources import files
from pathlib import Path
from typing import Any

from .evidence import EvidenceError, load_evidence


def render_evidence(evidence: dict[str, Any]) -> str:
    template = files("qnp").joinpath("assets/evidence.html").read_text(encoding="utf-8")
    # Even inert JSON script elements must not accept a closing </script> from
    # imported metadata. Dynamic DOM content is inserted with textContent.
    payload = json.dumps(evidence, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    script = template.split("<script>\n", 1)[1].split("</script>", 1)[0]
    digest = base64.b64encode(hashlib.sha256(("\n" + script).encode()).digest()).decode()
    return template.replace("__SCRIPT_HASH__", digest).replace("__EVIDENCE_JSON__", payload)


def write_evidence_report(results_dir: Path, output: Path, run_id: str | None = None, *, force: bool = False) -> Path:
    """Atomically export a verified report, never overwriting research evidence."""
    output = output.resolve()
    if output.is_relative_to(results_dir.resolve()):
        raise EvidenceError("choose an output outside the results directory to preserve the research record")
    if output.suffix.lower() != ".html":
        raise EvidenceError("report output must have an .html extension")
    if output.exists() and not force:
        raise EvidenceError(f"output already exists: {output}; choose a new path or pass --force")
    html = render_evidence(load_evidence(results_dir, run_id))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=output.parent, delete=False
        ) as f:
            temporary = Path(f.name)
            f.write(html)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temporary, output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output
