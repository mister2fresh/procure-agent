"""From-scratch ReAct agent loop. Day 1 reference implementation.

The agent reads a synthetic supplier quote fixture from `data/synthetic_quotes/` and
returns a structured `Quote` JSON object matching `procure_agent.schemas.Quote`.

This file gets translated to LangGraph nodes/edges in
`docs/from_primitives_to_langgraph.md` once the loop runs end-to-end against at least
one fixture.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from anthropic import Anthropic
from anthropic.types import Message
from docx import Document
from docx.oxml.ns import qn
from dotenv import load_dotenv

from procure_agent.prompts import SYSTEM
from procure_agent.schemas import Quote

load_dotenv()

MODEL = "claude-haiku-4-5"
MAX_TOKENS = 4096
QUOTES_DIR = Path(__file__).resolve().parents[2] / "data" / "synthetic_quotes"

client = Anthropic()


READ_FILE_TOOL = {
    "name": "read_file",
    "description": (
        "Read the contents of a synthetic supplier quote fixture by filename. "
        "Handles .txt, .csv, .md (returned as-is) and .docx (rendered to text "
        "with paragraphs as lines and tables as pipe-delimited rows)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "filename": {
                "type": "string",
                "description": (
                    "Filename within data/synthetic_quotes/, "
                    "e.g. 'aloe-corp_AC-2026-0421.txt'."
                ),
            },
        },
        "required": ["filename"],
    },
}


def _read_docx(path: Path) -> str:
    """Render a .docx body as plain text in document order.

    Paragraphs become lines. Tables render as pipe-delimited rows so column
    structure survives. Document order between paragraphs and tables is preserved.

    Args:
        path: Resolved path to a .docx file.

    Returns:
        The document body as a single newline-joined string.
    """
    doc = Document(path)
    blocks: list[str] = []
    for child in doc.element.body.iterchildren():
        if child.tag == qn("w:p"):
            text = "".join(t.text or "" for t in child.iter(qn("w:t")))
            if text.strip():
                blocks.append(text)
        elif child.tag == qn("w:tbl"):
            table = next(t for t in doc.tables if t._element is child)
            blocks.extend(" | ".join(c.text for c in row.cells) for row in table.rows)
    return "\n".join(blocks)


def read_file(filename: str) -> str:
    """Read a fixture from the synthetic-quotes directory.

    Dispatches by suffix: ``.docx`` is rendered to text via ``python-docx``;
    everything else is returned as raw text.

    Args:
        filename: Bare filename within `data/synthetic_quotes/`. Path traversal
            (anything that resolves outside the directory) is rejected.

    Returns:
        The file's contents as text.

    Raises:
        ValueError: If the filename escapes the quotes directory or doesn't exist.
    """
    target = (QUOTES_DIR / filename).resolve()
    if QUOTES_DIR not in target.parents:
        raise ValueError(f"path escapes quotes directory: {filename}")
    if not target.is_file():
        raise ValueError(f"fixture not found: {filename}")
    if target.suffix == ".docx":
        return _read_docx(target)
    return target.read_text(encoding="utf-8")


HANDLERS = {"read_file": read_file}
TOOLS = [READ_FILE_TOOL]


def run(user_msg: str, max_turns: int = 10) -> Message:
    """Run the ReAct loop until the model stops calling tools or max_turns is hit.

    Args:
        user_msg: First user turn. Typically points the agent at a specific fixture.
        max_turns: Hard cap on tool-use cycles to prevent runaway runs.

    Returns:
        The final assistant `Message` whose `stop_reason` is not `"tool_use"`.

    Raises:
        RuntimeError: If `max_turns` is exhausted without a non-tool-use stop.
    """
    messages: list[dict] = [{"role": "user", "content": user_msg}]
    for _ in range(max_turns):
        resp = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=[
                {
                    "type": "text",
                    "text": SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": resp.content})
        if resp.stop_reason != "tool_use":
            return resp
        results = [
            {
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(HANDLERS[block.name](**block.input)),
            }
            for block in resp.content
            if block.type == "tool_use"
        ]
        messages.append({"role": "user", "content": results})
    raise RuntimeError(f"max_turns={max_turns} exceeded")


DEFAULT_FIXTURE = "aloe-corp_AC-2026-0421.txt"
JSON_BLOCK = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)


def extract_json_block(resp: Message) -> str:
    """Pull the single fenced ```json``` block from the final assistant message.

    Raises:
        ValueError: If no fenced JSON block is found.
    """
    text = "".join(block.text for block in resp.content if block.type == "text")
    match = JSON_BLOCK.search(text)
    if not match:
        raise ValueError(f"no fenced json block in response:\n{text}")
    return match.group(1)


if __name__ == "__main__":
    fixture = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_FIXTURE
    resp = run(f"Extract the quote in {fixture} as JSON.")
    quote = Quote.model_validate_json(extract_json_block(resp))
    print(quote.model_dump_json(indent=2))
