"""
Evaluation harness service — Bonus 6: LLM-as-judge.

Uses a second LLM call to score the quality of each analysis output.
This pattern is called "LLM-as-judge" and is a standard technique in
LLM evaluation (similar to what OpenAI Evals and LangSmith do internally).

For each analysis type:
  1. Run the actual analysis
  2. Send both the INPUT and OUTPUT to the judge LLM
  3. Judge scores: accuracy, grounding, completeness (0.0 to 1.0)
  4. Returns score + reasoning + pass/fail

Guard against hallucinations: judge checks whether the output only
references data that was actually in the input.
"""

import json
from typing import Optional
from pydantic import BaseModel
from langchain_core.prompts import ChatPromptTemplate
from app.services.analysis.base import get_llm, format_assets_for_prompt


# ── Evaluation output schema ──────────────────────────────────────────────────

class EvaluationResult(BaseModel):
    score: float              # 0.0 (terrible) to 1.0 (perfect)
    reasoning: str            # Explanation of the score
    passed: bool              # True if score >= 0.7
    hallucination_detected: bool  # True if output references facts not in input
    dimension_scores: dict    # {"relevance": 0.9, "grounding": 0.8, "clarity": 0.7}


# ── Judge prompt ──────────────────────────────────────────────────────────────

JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You are an expert evaluator of AI-generated cybersecurity analysis outputs.
Your job is to score an AI response against the data that was provided to it.

SCORING CRITERIA:
- relevance (0-1): Does the output address what was asked?
- grounding (0-1): Does the output ONLY reference facts present in the provided data?
- clarity (0-1): Is the output clear, professional, and actionable?

HALLUCINATION CHECK:
- Read the provided input data carefully
- Check if the output mentions any assets, vulnerabilities, or facts NOT in the input
- If yes: hallucination_detected = true

Return your evaluation as JSON with this exact structure:
{{
  "relevance": <float 0-1>,
  "grounding": <float 0-1>,
  "clarity": <float 0-1>,
  "overall_score": <float 0-1, average of above>,
  "hallucination_detected": <boolean>,
  "reasoning": "<2-3 sentences explaining your score>",
  "passed": <boolean, true if overall_score >= 0.7>
}}

Return ONLY valid JSON. No preamble, no explanation outside the JSON."""),
    ("human", """EVALUATION TASK: {task_description}

INPUT DATA PROVIDED TO THE AI:
{input_data}

AI OUTPUT TO EVALUATE:
{ai_output}

Evaluate the AI output against the input data and return your JSON evaluation."""),
])


async def _run_judge(
    task_description: str,
    input_data: str,
    ai_output: str,
) -> EvaluationResult:
    """
    Run the LLM judge and parse its structured response.
    Falls back to a safe default if the judge call fails.
    """
    llm = get_llm()
    chain = JUDGE_PROMPT | llm

    try:
        response = await chain.ainvoke({
            "task_description": task_description,
            "input_data": input_data[:4000],  # truncate to avoid token limit
            "ai_output": ai_output[:2000],
        })
        content = response.content if hasattr(response, "content") else str(response)

        # Parse JSON from judge response
        # Handle cases where LLM wraps JSON in markdown code blocks
        content = content.strip()
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]

        data = json.loads(content)

        return EvaluationResult(
            score=float(data.get("overall_score", 0.5)),
            reasoning=data.get("reasoning", "No reasoning provided."),
            passed=bool(data.get("passed", False)),
            hallucination_detected=bool(data.get("hallucination_detected", False)),
            dimension_scores={
                "relevance": float(data.get("relevance", 0.5)),
                "grounding": float(data.get("grounding", 0.5)),
                "clarity": float(data.get("clarity", 0.5)),
            },
        )

    except (json.JSONDecodeError, KeyError, ValueError):
        # If judge fails to return valid JSON, return a neutral score
        return EvaluationResult(
            score=0.5,
            reasoning="Judge evaluation failed to parse — manual review recommended.",
            passed=False,
            hallucination_detected=False,
            dimension_scores={"relevance": 0.5, "grounding": 0.5, "clarity": 0.5},
        )


# ── Public evaluation functions ───────────────────────────────────────────────

async def evaluate_nl_query(query: str, result: dict) -> EvaluationResult:
    """
    Evaluate the quality of a natural-language query result.

    Checks:
    - Did the interpretation match what the user asked?
    - Are the filters sensible?
    - Are the returned assets relevant?
    """
    assets_summary = f"Filters applied: {result.get('filters_applied', {})}\n"
    assets_summary += f"Total matches: {result.get('total', 0)}\n"
    assets_list = result.get("assets", [])
    for a in assets_list[:10]:
        assets_summary += f"  - [{a.get('type')}] {a.get('value')} status={a.get('status')}\n"

    return await _run_judge(
        task_description=(
            f"Natural language asset query: '{query}'\n"
            "Evaluate if the query was correctly interpreted and the results are relevant."
        ),
        input_data=f"User query: {query}\nExplanation given: {result.get('explanation', '')}",
        ai_output=assets_summary,
    )


async def evaluate_risk_summary(findings: list, summary: str) -> EvaluationResult:
    """
    Evaluate the LLM-generated risk executive summary.

    Checks:
    - Does the summary accurately reflect the rule-based findings?
    - Does it mention real asset names and finding details?
    - Does it hallucinate risks not present in the findings?
    """
    if not findings:
        findings_text = "No risk findings were identified."
    else:
        findings_text = "\n".join(
            f"[{getattr(f, 'risk_level', '?').upper()}] "
            f"{getattr(f, 'asset_type', '?')} '{getattr(f, 'asset_value', '?')}': "
            f"{getattr(f, 'finding', '?')}"
            for f in findings[:20]
        )

    return await _run_judge(
        task_description=(
            "Risk executive summary evaluation.\n"
            "Check if the summary accurately describes the findings without inventing new risks."
        ),
        input_data=f"Rule-based findings:\n{findings_text}",
        ai_output=summary,
    )


async def evaluate_report(report_result) -> EvaluationResult:
    """
    Evaluate the quality of a generated security report.

    Checks:
    - Does the report cover all sections?
    - Is it grounded in the actual asset data?
    - Is it professional and actionable?
    """
    # Build a summary of what data the LLM had access to
    inventory = report_result.inventory
    input_summary = (
        f"Organization had {inventory.total_assets} assets.\n"
        f"By type: {inventory.by_type}\n"
        f"By status: {inventory.by_status}\n"
        f"Risk counts: {report_result.risk_counts}"
    )

    return await _run_judge(
        task_description=(
            "Security report quality evaluation.\n"
            "Check if the report is complete, grounded, and professional."
        ),
        input_data=input_summary,
        ai_output=report_result.report[:2000],
    )
