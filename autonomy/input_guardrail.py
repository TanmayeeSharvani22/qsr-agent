"""Pre-model scope gate: block out-of-scope operator questions before a full turn.

Hybrid of a service-agnostic keyword fast-path derived from the installed skills
and a cheap OVMS yes/no classifier for questions with no keyword signal. The gate
fails open so a classifier outage never blocks legitimate store questions.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from pathlib import Path
from typing import Callable

DECLINE_MESSAGE = "I can only help with questions about this store's connected services."

# Dropped from skill-derived terms and questions so only domain words remain.
_STOPWORDS = frozenset({
    "and", "any", "anything", "answer", "answers", "ask", "comp", "current", "detail",
    "for", "from", "handle", "handling", "its", "linux", "metadata", "name", "not",
    "optional", "platforms", "qsr", "question", "questions", "related", "request",
    "requests", "restaurant", "safely", "service", "services", "store", "tags", "the",
    "their", "them", "this", "true", "use", "using", "version", "via", "what", "when",
    "which", "with", "your",
})


def _tokens(text: str) -> set[str]:
    return {word for word in re.findall(r"[a-z0-9]+", text.lower())
            if len(word) >= 3 and word not in _STOPWORDS}


def extract_scope_terms(skills_dir: Path) -> tuple[set[str], str]:
    """Return (keyword terms, joined descriptions) from every SKILL.md frontmatter."""
    terms: set[str] = set()
    descriptions: list[str] = []
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        text = skill_file.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue
        end = text.find("\n---", 3)
        front = text[3:end] if end != -1 else text
        name = re.search(r"(?m)^name:\s*(.+)$", front)
        description = re.search(r'(?m)^description:\s*"?(.+?)"?\s*$', front)
        tags = re.search(r"(?m)^\s*tags:\s*\[(.*)\]", front)
        for match in (name, description, tags):
            if match:
                terms |= _tokens(match.group(1))
        if description:
            descriptions.append(description.group(1))
    return terms, " ".join(descriptions)


def build_ovms_classifier(
    topics: str,
    base_url: str,
    model: str,
    api_key: str,
    timeout: float,
) -> Callable[[str], bool | None]:
    """Build a yes/no OVMS classifier; returns None on any transport/parse failure."""
    url = base_url.rstrip("/") + "/chat/completions"
    system = (
        "You gate messages for a quick-service restaurant's store assistant. Answer 'yes' if the message is "
        "about this restaurant: its operations, its connected services (" + topics + "), the weather at the "
        "store, or its people, "
        "staff, managers, shifts and preferences (for example 'Who is our store manager?'), including anything "
        "the operator told the assistant to remember. Answer 'no' for "
        "anything else, such as general knowledge, trivia, math, writing code, jokes or translation. "
        "Reply with only 'yes' or 'no'."
    )

    def classify(question: str) -> bool | None:
        body = json.dumps({
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "max_tokens": 1,
            "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
        }).encode("utf-8")
        request = urllib.request.Request(
            url, data=body, method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
        )
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(request, timeout=timeout) as response:
                payload = json.load(response)
            content = payload["choices"][0]["message"]["content"].strip().lower()
        except Exception:
            return None
        if content.startswith("y"):
            return True
        if content.startswith("n"):
            return False
        return None

    return classify


class InputGuardrail:
    def __init__(
        self,
        terms: set[str],
        classifier: Callable[[str], bool | None],
        enabled: bool = True,
    ) -> None:
        self.terms = terms
        self.classifier = classifier
        self.enabled = enabled

    def is_allowed(self, question: str) -> bool:
        if not self.enabled:
            return True
        if _tokens(question) & self.terms:
            return True
        verdict = self.classifier(question)
        # Fail open on classifier error so an outage never blocks real questions.
        return verdict is not False


def build_input_guardrail(skills_dir: Path) -> InputGuardrail:
    enabled = os.environ.get("QSR_SCOPE_GATE", "true").strip().lower() not in {"0", "false", "no"}
    terms, descriptions = extract_scope_terms(skills_dir)
    classifier = build_ovms_classifier(
        descriptions,
        os.environ.get("QSR_ADVISOR_BASE_URL", "http://127.0.0.1:4444/v3"),
        os.environ.get("QSR_ADVISOR_MODEL") or os.environ.get("MODEL_ID", ""),
        os.environ.get("QSR_ADVISOR_API_KEY", "local-ovms-no-auth"),
        float(os.environ.get("QSR_SCOPE_GATE_TIMEOUT", "15")),
    )
    return InputGuardrail(terms, classifier, enabled)
