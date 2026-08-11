from __future__ import annotations

import argparse
from pathlib import Path

ORDER = ["api.js", "components.js", "app.js", "index.js"]

_TASK_CARD_BAD = 'h("strong", null, t.status || (t.enabled === false ? "paused" : "active"), h("span", null, "Next run"), h("strong", null, fmt(t.next_run_at)))'
_TASK_CARD_GOOD = 'h("strong", null, t.status || (t.enabled === false ? "paused" : "active")), h("span", null, "Next run"), h("strong", null, fmt(t.next_run_at))'


def _normalize_bundle(body: str) -> str:
    """Apply deterministic release-time normalizations for known source-layout hazards."""
    return body.replace(_TASK_CARD_BAD, _TASK_CARD_GOOD)


def build(root: Path) -> Path:
    root = root.resolve()
    src = root / "src"
    missing = [name for name in ORDER if not (src / name).is_file()]
    if missing:
        raise SystemExit(f"Missing dashboard source modules: {', '.join(missing)}")
    out_dir = root / "dist"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "index.js"
    banner = "/* Hermes Extensions dashboard bundle. Generated from dashboard/src modules. */\n"
    body = "\n\n".join((src / name).read_text("utf-8").rstrip() for name in ORDER) + "\n"
    body = _normalize_bundle(body)
    if _TASK_CARD_BAD in body:
        raise SystemExit("Dashboard bundle still contains invalid Task card Status/Next run nesting")
    out.write_text(banner + body, "utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    print(build(args.root))


if __name__ == "__main__":
    main()
