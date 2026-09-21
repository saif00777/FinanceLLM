"""Runtime-only semantic catalog and compact schema-linking context."""

from dataclasses import dataclass
from pathlib import Path
import re

import yaml


@dataclass(frozen=True)
class LinkedContext:
    relations: tuple[str, ...]
    prompt: str


@dataclass(frozen=True)
class RuntimeContract:
    """Approved semantic information projected from versioned context files."""

    schema: dict
    semantics: dict

    @classmethod
    def from_files(cls, root: Path) -> "RuntimeContract":
        context_dir = root / "context"
        with (context_dir / "schema.yaml").open(encoding="utf-8") as stream:
            schema = yaml.safe_load(stream)
        with (context_dir / "semantics.yaml").open(encoding="utf-8") as stream:
            semantics = yaml.safe_load(stream)
        return cls(schema=schema, semantics=semantics)

    def link(self, question: str, max_relations: int = 2) -> LinkedContext:
        """Project only the relevant canonical catalog entries into a prompt."""
        if max_relations < 1:
            raise ValueError("max_relations must be at least one")
        normalized = re.sub(r"\s+", " ", question.lower()).strip()
        tables = self.schema["tables"]
        scores = {name: 0 for name in tables}

        for name, table in tables.items():
            terms = [name.replace("_", " "), *table.get("synonyms", [])]
            scores[name] += sum(1 for term in terms if term.lower() in normalized)

        for term in self.semantics.get("glossary", {}).values():
            if not any(synonym.lower() in normalized for synonym in term.get("synonyms", [])):
                continue
            targets = [term.get("maps_to"), term.get("via")]
            for target in targets:
                text = " ".join(target) if isinstance(target, list) else str(target or "")
                for name in tables:
                    if name in text:
                        scores[name] += 2

        for metric in self.semantics.get("metrics", {}).values():
            label = metric.get("label", "").lower()
            if any(word in normalized for word in label.split()):
                scores[metric["table"]] += 1

        if any(word in normalized for word in ("spending", "spend", "amount", "transaction", "payment")):
            scores["transactions"] += 2
        selected_names = [name for name, score in scores.items() if score > 0]
        if not selected_names:
            selected_names = ["transactions"]
        selected_names.sort(key=lambda name: (-scores[name], list(tables).index(name)))
        selected_names = selected_names[:max_relations]
        relations = tuple(tables[name]["relation"]["qualified_name"] for name in selected_names)

        lines = ["Use only this linked canonical context.", "Relations:"]
        for name in selected_names:
            table = tables[name]
            columns = ", ".join(table["columns"])
            lines.append(f"- {table['relation']['qualified_name']}: {columns}")
        for relationship in self.schema.get("relationships", []):
            if relationship["from_table"] in selected_names and relationship["to_table"] in selected_names:
                lines.append(f"- Join: {relationship['join_sql']}")
        for metric in self.semantics.get("metrics", {}).values():
            if metric["table"] in selected_names:
                lines.append(f"- Metric {metric['label']}: {metric['expression_sql']}")
        lines.append("Unsupported topics:")
        lines.extend(
            f"- {item['topic']}: {item['reason']}"
            for item in self.semantics.get("unsupported_questions", [])
        )
        lines.append("Use one bounded SELECT or WITH query against main relations only.")
        return LinkedContext(relations=relations, prompt="\n".join(lines))

    def as_prompt(self) -> str:
        """Compatibility projection for legacy single-agent callers."""
        return self.link("transactions cards users merchant categories", max_relations=4).prompt