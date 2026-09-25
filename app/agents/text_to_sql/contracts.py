"""Runtime-only semantic catalog and compact schema-linking context."""

from dataclasses import dataclass
from pathlib import Path
import re

import yaml


# Words in metric labels that cannot identify a subject on their own: filler ("Magnitude OF ...",
# "... WITH at LEAST one ...") and bare aggregation words. "tell me the AVERAGE" must not resolve
# "Average positive recorded amount" (a transactions metric) -- a follow-up like that should inherit
# the previous turn's subject instead. Short words (<4 letters) are ignored too.
_LABEL_STOPWORDS = frozenset({"with", "least", "than", "that", "have", "average", "total", "count", "fraction", "number"})


def label_matches(label: str, normalized_question: str) -> bool:
    """True if any distinctive word of a metric label starts a word in the question.

    Matching every raw label word made "of" in "Magnitude of negative recorded amounts" match
    "credit limit of cards", wrongly resolving a transactions metric for a cards question."""
    words = [w for w in re.findall(r"[a-z]+", label.lower()) if len(w) >= 4 and w not in _LABEL_STOPWORDS]
    return any(re.search(r"\b" + re.escape(word), normalized_question) for word in words)


# The second data source (source "rag"). The schema/semantics contract only covers the MotherDuck tables, so the
# document corpus is described here for the agents to route to it instead of refusing or mis-planning. Set it to
# None to tell the agents no document source exists (they then never pick "rag").
_DOCUMENT_CORPUS: str | None = (
    'Bank documents (source "rag", separate from the SQL tables): 50 synthetic internal documents of the fictional '
    "Larkspur Ridge Bank, N.A. and Larkspur Ridge Financial Corp., retrieved by meaning (not queried with SQL). Four "
    "groups: financial statements and reporting (balance sheet, income statement, MD&A, CECL note, earnings releases, "
    "earnings call, capital report, board minutes); customer communications (complaint emails, chat transcripts, call "
    "notes, resolution letters, social media log, NPS comments); loans and credit (credit memos, default notice, watch "
    "list, loan committee minutes, mortgage underwriting, HELOC, SBA, CRE review, credit policy); compliance and risk "
    "(KYC/EDD, AML case files, OFAC, internal audits, outage root cause, complaint trends, fair lending, vendor risk, "
    "regulator responses, wire policy). Storylines run across documents: the Brightwater Logistics loan (credit memo, "
    "covenant default, watch list, downgrade and reserve, forbearance); the March 11, 2026 digital banking outage "
    "(customer complaints and duplicate debit card charges, root cause, remediation, capital and board impact); the "
    "Talon Crest Imports AML case (KYC, SAR, audit); overdraft fees (a customer complaint through to product changes); "
    "the Park mortgage; Robert Chen's fraud dispute; Samantha Ortiz's HELOC; Lomax Floral's outage remediation and SBA "
    "loan; Dorothy Ferris's scam protection; Northgate Ventures ownership. A question about what these documents say (figures such as net interest "
    "margin, a named customer or case, a policy, an incident, a storyline spanning several documents) is answered from "
    "up to eight retrieved excerpts, citing those used. The documents are not the MotherDuck transaction data: do not mix their figures with "
    "SQL results unless the question asks for both."
)


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

    def link(self, question: str, max_relations: int = 2, prior_relations: tuple[str, ...] = ()) -> LinkedContext:
        """Project only the relevant canonical catalog entries into a prompt.

        ``prior_relations`` are the previous turn's relations: when the question itself carries
        no table signal (a follow-up like "tell me the average"), they are reused instead of
        falling back to the default transactions table."""
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
            if label_matches(metric.get("label", ""), normalized):
                scores[metric["table"]] += 1

        if any(word in normalized for word in ("spending", "spend", "amount", "transaction", "payment")):
            scores["transactions"] += 2
        selected_names = [name for name, score in scores.items() if score > 0]
        if not selected_names and prior_relations:
            by_relation = {table["relation"]["qualified_name"]: name for name, table in tables.items()}
            selected_names = [by_relation[relation] for relation in prior_relations if relation in by_relation]
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
        lines.append(
            "Every query needs LIMIT 1-100, except a single-row scalar aggregate with no GROUP BY "
            "(e.g. one SUM/COUNT/AVG total with no grouping) — that may omit LIMIT."
        )
        lines.append(
            "For date parts (year, month, etc.) use EXTRACT(part FROM column), e.g. "
            "EXTRACT(YEAR FROM t.transaction_at). Do not use YEAR(), MONTH(), DATE_PART(), or similar shorthand."
        )
        return LinkedContext(relations=relations, prompt="\n".join(lines))

    def business_context(self) -> str:
        """The whole governed business picture in compact prose, for agents that must reason about
        intent (domain guard, planner, suggestions) rather than write SQL against a few tables.

        Everything comes from the versioned schema/semantics contract, so it can never mention a
        private ``source.*`` table or a column outside the allowlist."""
        lines = [f"Dataset: {self.schema.get('purpose', '').strip()}", "Tables:"]
        for table in self.schema["tables"].values():
            synonyms = ", ".join(table.get("synonyms", []))
            lines.append(
                f"- {table['relation']['qualified_name']}: {table.get('description', '').strip()} "
                f"Grain: {table.get('grain', '')}. Also called: {synonyms}."
            )
            for column, meta in table["columns"].items():
                lines.append(f"    {column}: {str(meta.get('description', '')).strip()}")
        lines.append("Relationships:")
        for relationship in self.schema.get("relationships", []):
            lines.append(
                f"- {relationship['from_table']} -> {relationship['to_table']} "
                f"({relationship.get('cardinality', '')}): {relationship.get('purpose', '')}"
            )
        lines.append("Business terms:")
        for term, entry in self.semantics.get("glossary", {}).items():
            lines.append(
                f"- {term} (also: {', '.join(entry.get('synonyms', []))}) maps to {entry.get('maps_to')}: "
                f"{str(entry.get('definition', '')).strip()}"
            )
        lines.append("Governed metrics:")
        for metric in self.semantics.get("metrics", {}).values():
            lines.append(
                f"- {metric['label']} (table {metric['table']}, unit {metric.get('unit')}, "
                f"population {metric.get('population')}, aggregation {metric.get('aggregation')})"
            )
        lines.append("Cannot be answered from this data:")
        for item in self.semantics.get("unsupported_questions", []):
            lines.append(f"- {item['topic']}: {item['reason']}")
        if _DOCUMENT_CORPUS:
            lines.append(_DOCUMENT_CORPUS)
        return "\n".join(lines)

    def as_prompt(self) -> str:
        """Compatibility projection for legacy single-agent callers."""
        return self.link("transactions cards users merchant categories", max_relations=4).prompt