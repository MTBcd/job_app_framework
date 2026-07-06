"""Versioned prompt templates for the personalization pipeline.

Contract (docs/eval.md): outputs are grounded ONLY in the JSON inputs; when
evidence is missing the email gets more general, never invented. Bump
PROMPT_VERSION on any change — it is stored on every ai_runs row so outputs
are attributable to the exact prompt that produced them.
"""
from __future__ import annotations

import json

PROMPT_VERSION = "p2"

# Phrases that mark templated/AI-sounding outreach. The eval checks these;
# the prompts forbid them explicitly.
FORBIDDEN_PHRASES = [
    "i hope this email finds you well",
    "i hope this message finds you well",
    "i am writing to express",
    "i was impressed by",
    "i have always been passionate",
    "passionate about",
    "dream company",
    "dream job",
    "perfect fit",
    "ideal candidate",
    "esteemed",
    "renowned",
    "prestigious",
    "leverage my skills",
    "synergy",
    "value-add",
    "hit the ground running",
    "team player",
    "think outside the box",
    "proven track record",
    "delve",
    "in today's fast-paced world",
]

_GROUNDING_RULES = """GROUNDING RULES (absolute):
- Use ONLY facts present in the INPUT JSON. Every specific claim must be
  traceable to candidate_profile, opportunity, research_brief, contact, or
  user_preferences.
- NEVER invent: candidate experience, company facts, job requirements,
  recruiter information, relationships, referrals, awards, funding events,
  metrics, or hiring needs.
- If research confidence is low or facts are missing, write a more GENERAL
  but professional email instead of inventing personalization.
- Do not compliment the company ("impressed by", praise of products/culture)
  unless a research fact directly supports the specific compliment."""

PLAN_SYSTEM = f"""You are the planning stage of a job-application assistant.
You produce a personalization plan as JSON — no prose outside the JSON.

{_GROUNDING_RULES}

Planning guidance:
- Select at most 3 candidate strengths with the strongest evidence FOR THIS
  opportunity; quote the evidence field from the profile.
- List gaps honestly so the writer avoids overclaiming (missing requirements,
  seniority mismatch, career change).
- Split company/job facts into safe_facts (confidence >= 0.7, concrete,
  relevant) and excluded_facts (too weak, too generic, or irrelevant) with a
  reason for each exclusion.
- recipient_reasoning: why THIS person, based only on their given title/role.
- call_to_action: one modest ask (short call, pass along CV, reply).
- writing_constraints: concrete instructions for the writer (what to avoid,
  what tone fits the candidate's seniority and the user's tone preference)."""

PLAN_SCHEMA = {
    "type": "object",
    "properties": {
        "candidate_strengths": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "point": {"type": "string"},
                    "evidence": {"type": "string"},
                },
                "required": ["point", "evidence"],
                "additionalProperties": False,
            },
        },
        "gaps_to_avoid_overclaiming": {"type": "array", "items": {"type": "string"}},
        "safe_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "source": {"type": "string"},
                },
                "required": ["fact", "source"],
                "additionalProperties": False,
            },
        },
        "excluded_facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "fact": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["fact", "reason"],
                "additionalProperties": False,
            },
        },
        "angle": {"type": "string"},
        "tone": {"type": "string"},
        "recipient_reasoning": {"type": "string"},
        "call_to_action": {"type": "string"},
        "risks": {"type": "array", "items": {"type": "string"}},
        "writing_constraints": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "candidate_strengths", "gaps_to_avoid_overclaiming", "safe_facts",
        "excluded_facts", "angle", "tone", "recipient_reasoning",
        "call_to_action", "risks", "writing_constraints",
    ],
    "additionalProperties": False,
}

EMAIL_SYSTEM = f"""You write short, credible job-application emails from a
personalization plan. Output JSON only.

{_GROUNDING_RULES}

Writing rules:
- Body: 120-180 words. No bullet points. No greetings-card enthusiasm.
- Open with the concrete reason for reaching out (1 sentence, no throat-
  clearing). Connect 1-2 candidate strengths to the opportunity using the
  plan's evidence. Close with the plan's single call to action.
- Company naming (required): write the company's EXACT official name from
  the INPUT JSON (company_name) at least once in the body, naturally —
  usually in the opening sentence. "your team", "the company", or shortened
  possessives ("Northwind's") do NOT satisfy this; use the full name once,
  then pronouns are fine afterwards.
- Career changers: when the candidate's background is a different profession
  (e.g. teacher moving into UX research), name that previous professional
  identity once, framed as a concrete asset for THIS role ("six years as a
  teacher running structured feedback sessions") — never as an apology, and
  never disguised.
- Sound like a competent human wrote it: plain sentences, specific nouns,
  zero filler. Adapt formality to the plan's tone and the candidate's
  seniority (a junior sounds eager-but-grounded, a senior sounds peer-level).
- NEVER use these phrases or close variants: {", ".join(FORBIDDEN_PHRASES)}.
- Subject format (<= 70 chars, plain, never salesy, no exclamation marks):
  with a role: "<Role> application — <candidate's concrete strength>";
  speculative/company-only: "Introduction — <strength or target area>".
  Example: "Junior Backend Engineer application — Python/Postgres intern
  with shipped dashboard". Never generic ("Job application", "Opportunity").
- claims_used: list every specific claim in the email with the input field
  that grounds it — if you cannot ground a claim, do not write it."""

EMAIL_SCHEMA = {
    "type": "object",
    "properties": {
        "subject": {"type": "string"},
        "body": {"type": "string"},
        "claims_used": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "claim": {"type": "string"},
                    "grounded_in": {"type": "string"},
                },
                "required": ["claim", "grounded_in"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["subject", "body", "claims_used"],
    "additionalProperties": False,
}

CV_SYSTEM = f"""You extract a structured candidate profile from CV text.
Output JSON only.

{_GROUNDING_RULES}

Extraction guidance: extract only what the CV states; leave arrays empty
rather than guessing; `warnings` lists anything ambiguous or unparseable;
`seniority` is one of: junior, mid, senior, lead, executive, unknown;
`likely_target_roles` may only be inferred from stated experience/titles."""

CV_SCHEMA = {
    "type": "object",
    "properties": {
        "identity": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "email": {"type": "string"},
                "location": {"type": "string"},
            },
            "required": ["name", "email", "location"],
            "additionalProperties": False,
        },
        "work_experience": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "company": {"type": "string"},
                    "duration": {"type": "string"},
                    "highlights": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "company", "duration", "highlights"],
                "additionalProperties": False,
            },
        },
        "education": {"type": "array", "items": {"type": "string"}},
        "skills": {"type": "array", "items": {"type": "string"}},
        "technologies": {"type": "array", "items": {"type": "string"}},
        "industries": {"type": "array", "items": {"type": "string"}},
        "projects": {"type": "array", "items": {"type": "string"}},
        "achievements": {"type": "array", "items": {"type": "string"}},
        "languages": {"type": "array", "items": {"type": "string"}},
        "certifications": {"type": "array", "items": {"type": "string"}},
        "seniority": {"type": "string"},
        "likely_target_roles": {"type": "array", "items": {"type": "string"}},
        "warnings": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "identity", "work_experience", "education", "skills", "technologies",
        "industries", "projects", "achievements", "languages",
        "certifications", "seniority", "likely_target_roles", "warnings",
    ],
    "additionalProperties": False,
}


def _dumps(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def plan_user_message(inputs: dict) -> str:
    return f"INPUT JSON:\n{_dumps(inputs)}\n\nProduce the personalization plan."


def email_user_message(inputs: dict, plan: dict) -> str:
    return (
        f"INPUT JSON:\n{_dumps(inputs)}\n\n"
        f"PERSONALIZATION PLAN:\n{_dumps(plan)}\n\n"
        "Write the email now."
    )


def cv_user_message(cv_text: str) -> str:
    return f"CV TEXT:\n{cv_text}\n\nExtract the structured profile."
