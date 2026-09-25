"""Live end-to-end check of the document RAG branch (real model + Qdrant; not part of the offline gate).

Runs each question in larkspur_ridge_bank_corpus/rag_eval_questions.jsonl through the full workflow and reports:
  routed      - the question reached document_retrieval (the domain guard picked the rag source)
  cited       - the answer's citations include every expected source document
  correct     - an LLM judge says the answer states the reference answer's key facts (extra detail is fine)
Unanswerable questions (no source documents) pass when the answer cites nothing.

  python scripts/eval_document_answers.py [--limit N]
"""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.main import build_workflow


def _judge(client, model: str, question: str, reference: str, answer: str) -> tuple[bool, str]:
    prompt = (
        'You grade a question-answering system. Reply with JSON {"correct": true|false, "reason": "<one sentence>"}. '
        "correct is true when the candidate answer gives the facts that directly answer the question and agrees with the "
        "reference on them (same figures, names, dates, outcome). Extra correct detail is fine and secondary supporting "
        "details in the reference may be omitted; a missing or different core fact is not correct."
    )
    payload = json.dumps({"question": question, "reference": reference, "candidate": answer})
    text = client.responses.create(model=model, instructions=prompt, input=payload, store=False).output_text
    try:
        data = json.loads(text.strip().strip("`").removeprefix("json").strip())
        return bool(data.get("correct")), str(data.get("reason", ""))
    except (ValueError, AttributeError):
        return False, "judge returned unparseable output"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    questions = [json.loads(line) for line in (ROOT / "larkspur_ridge_bank_corpus" / "rag_eval_questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        questions = questions[: args.limit]
    workflow = build_workflow()
    from dotenv import load_dotenv
    from os import environ
    from openai import OpenAI

    load_dotenv(ROOT / ".env")
    judge_client = OpenAI(api_key=environ["OPEN_AI_KEY"])
    judge_model = environ["OPEN_AI_MODEL"]

    tally = {"routed": 0, "cited": 0, "correct": 0, "answerable": 0, "unanswerable_clean": 0, "unanswerable": 0}
    for case in questions:
        result = workflow.answer(case["question"])
        expected = set(case.get("source_doc_ids") or [])
        cited = {c["source_hash"] for c in (result.citations or [])}
        routed = "document_retrieval" in (result.specialist_path or [])
        if expected:
            tally["answerable"] += 1
            tally["routed"] += routed
            ok_cited = expected <= cited
            tally["cited"] += ok_cited
            ok_correct, reason = _judge(judge_client, judge_model, case["question"], case["answer"], result.answer) if routed else (False, "not routed to documents")
            tally["correct"] += ok_correct
            flag = "ok  " if routed and ok_cited and ok_correct else "MISS"
            print(f"{flag} {case['qid']} {case['type']:<10} route={result.route:<8} routed={routed} cited={sorted(cited)} expected={sorted(expected)} correct={ok_correct}")
            if flag == "MISS":
                print(f"       Q: {case['question']}\n       ref: {case['answer']}\n       got: {result.answer[:300]}\n       judge: {reason}")
        else:
            tally["unanswerable"] += 1
            clean = not cited
            tally["unanswerable_clean"] += clean
            print(f"{'ok  ' if clean else 'MISS'} {case['qid']} unanswerable route={result.route} cited={sorted(cited)}\n       got: {result.answer[:200]}")

    a = tally["answerable"] or 1
    print(f"\nAnswerable: {tally['answerable']}  routed {tally['routed']}/{a}  all sources cited {tally['cited']}/{a}  judged correct {tally['correct']}/{a}")
    print(f"Unanswerable: {tally['unanswerable']}  cited nothing {tally['unanswerable_clean']}/{tally['unanswerable'] or 1}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
