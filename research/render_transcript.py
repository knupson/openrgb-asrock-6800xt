"""
Render a Claude Code session .jsonl transcript into readable Markdown.

Usage:
    python render_transcript.py <session.jsonl> <output.md> [--max-chars N]

Tool inputs and results are truncated (default 1500 chars) so the document
stays readable; the .jsonl next to it remains the complete record.
"""

import json
import sys


def truncate(text, limit):
    text = text.rstrip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n… [{len(text) - limit} chars truncados]"


def block_to_md(block, limit):
    kind = block.get("type")

    if kind == "text":
        return block.get("text", "").strip()

    if kind == "thinking":
        return None  # internal reasoning, skipped

    if kind == "tool_use":
        name = block.get("name", "?")
        args = json.dumps(block.get("input", {}), ensure_ascii=False, indent=2)
        return f"**→ tool `{name}`**\n\n```json\n{truncate(args, limit)}\n```"

    if kind == "tool_result":
        content = block.get("content", "")
        if isinstance(content, list):
            parts = []
            for c in content:
                if isinstance(c, dict) and c.get("type") == "text":
                    parts.append(c.get("text", ""))
                elif isinstance(c, dict):
                    parts.append(f"[{c.get('type')}]")
            content = "\n".join(parts)
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        flag = " (error)" if block.get("is_error") else ""
        return f"**← resultado{flag}**\n\n```\n{truncate(content, limit)}\n```"

    return f"[{kind}]"


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 1

    src, out = argv[1], argv[2]
    limit = 1500
    if "--max-chars" in argv:
        limit = int(argv[argv.index("--max-chars") + 1])

    lines = []
    with open(src, encoding="utf-8") as f:
        raw_lines = f.readlines()

    lines.append("# Sesión Claude Code — ASRock GPU RGB / OpenRGB\n")
    lines.append(f"Transcript renderizado de `{src.split(chr(92))[-1]}` "
                 f"({len(raw_lines)} entradas).\n")

    last_role = None
    for raw in raw_lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue

        role = entry.get("type")
        if role not in ("user", "assistant"):
            continue

        message = entry.get("message") or {}
        content = message.get("content")
        if content is None:
            continue
        if isinstance(content, str):
            content = [{"type": "text", "text": content}]

        rendered = [block_to_md(b, limit) for b in content if isinstance(b, dict)]
        rendered = [r for r in rendered if r]
        if not rendered:
            continue

        if role != last_role:
            lines.append(f"\n## {'Usuario' if role == 'user' else 'Claude'}\n")
            last_role = role

        lines.extend(rendered)
        lines.append("")

    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"escrito {out} ({len(lines)} bloques)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
