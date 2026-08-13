"""AI prompt catalog — the upstream ``ai_prompts`` markdown library.

Prompts are shipped as markdown files with YAML frontmatter (``name``,
``description``) under ``qualcoder_api/ai_prompts``. Chat modes map to a
root prompt per scope; the full catalog is exposed through ``GET /ai/prompts``
so the frontend can offer a prompt picker (upstream ``ai_prompt_library``).

Frontmatter parsing is dependency-free (stdlib only).
"""

from __future__ import annotations

import importlib.resources
import re
from dataclasses import dataclass, field

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
META_RE = re.compile(r"^(\w[\w-]*):\s*(.*)$", re.MULTILINE)

# Root prompt per chat mode (falls back to a sensible system prompt).
MODE_SYSTEM_PROMPTS: dict[str, str] = {
    "general": (
        "You are a research assistant for qualitative data analysis. "
        "Answer concisely and helpfully."
    ),
    "help": (
        "You are a helpful assistant who knows the QualCoder qualitative data "
        "analysis application and its workflow. Give practical, step-by-step help."
    ),
    "topic_exploration": (
        "You assist a qualitative researcher exploring topics in interview and "
        "focus-group data. Stay close to the empirical material, avoid "
        "speculation, and quote the data where relevant."
    ),
    "code_analysis": (
        "You are an expert qualitative methodologist analyzing the quality and "
        "consistency of a code system. Ground every statement in the provided "
        "codebook and coded segments."
    ),
    "text_analysis": (
        "You are a qualitative data analyst interpreting interview and focus-group "
        "text. Work inductively from the material; do not add context that is not "
        "present in the data."
    ),
    "memo_analysis": (
        "You are a qualitative research assistant analyzing the researcher's "
        "memos. Ground every statement in the provided memos; identify recurring "
        "patterns and themes without adding outside context."
    ),
}


@dataclass(frozen=True)
class Prompt:
    id: str
    mode: str  # "help" | "topic_exploration" | "code_analysis" | "text_analysis" | "memo_analysis" | "search"
    name: str
    description: str
    text: str


@dataclass(frozen=True)
class Catalog:
    prompts: list[Prompt] = field(default_factory=list)

    def by_id(self, prompt_id: str) -> Prompt | None:
        for prompt in self.prompts:
            if prompt.id == prompt_id:
                return prompt
        return None

    def for_mode(self, mode: str) -> list[Prompt]:
        return [p for p in self.prompts if p.mode == mode]


def _load_catalog() -> Catalog:
    prompts: list[Prompt] = []
    package = "qualcoder_api.ai_prompts"
    try:
        files = importlib.resources.files(package)
        for file in files.iterdir():
            if file.is_file() and file.name.endswith(".md"):
                text = file.read_text(encoding="utf-8")
                prompts.append(_parse(file.name, text))
            elif file.is_dir():
                for child in file.iterdir():
                    if child.is_file() and child.name.endswith(".md"):
                        text = child.read_text(encoding="utf-8")
                        prompts.append(_parse(f"{file.name}/{child.name}", text))
    except (ModuleNotFoundError, OSError):  # pragma: no cover - package data absent
        return Catalog()
    return Catalog(prompts=prompts)


def _parse(path: str, text: str) -> Prompt:
    mode = "general"
    if path.startswith("search/"):
        mode = "search"
    elif path.startswith("code-analysis"):
        mode = "code_analysis"
    elif path.startswith("text-analysis"):
        mode = "text_analysis"
    elif path.startswith("memo-analysis"):
        mode = "memo_analysis"
    elif path.startswith("topic-exploration"):
        mode = "topic_exploration"
    elif path.startswith("_") or path.endswith("_agent.md"):
        mode = "help"
    name = path.rsplit("/", 1)[-1].replace(".md", "")
    description = ""
    match = FRONTMATTER_RE.match(text)
    body = text
    if match:
        body = text[match.end():]
        for meta_match in META_RE.finditer(match.group(1)):
            key, value = meta_match.group(1), meta_match.group(2).strip()
            if key == "name":
                name = value.strip("\"'")
            elif key == "description":
                description = value.strip("\"'")
    return Prompt(
        id=path.replace(".md", "").replace("\\", "/"),
        mode=mode,
        name=name,
        description=description,
        text=body.strip(),
    )


CATALOG = _load_catalog()


def system_prompt_for(mode: str) -> str:
    return MODE_SYSTEM_PROMPTS.get(mode, MODE_SYSTEM_PROMPTS["general"])


def prompt_for(prompt_id: str | None, mode: str = "general") -> str | None:
    """Resolve a prompt: by explicit id, else the mode's root prompt."""
    if prompt_id:
        prompt = CATALOG.by_id(prompt_id)
        if prompt is not None:
            return prompt.text
    if mode == "general":
        return None
    # Root prompts carry underscore prefixes (e.g. ``_init``, ``_bootstrap``).
    roots = [p for p in CATALOG.for_mode(mode) if p.name.startswith("_")]
    if roots:
        return roots[0].text
    return None
