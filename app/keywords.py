"""Lightweight, offline ATS keyword matching between a resume and a job post.

Not AI: a fast heuristic that pulls salient terms (tech tokens, capitalised
terms, repeated words/phrases) from the job description and checks which ones
the resume contains. Used for the instant "match score" and to ground the
AI tailoring UI.
"""

import re
from collections import Counter

STOPWORDS = set(
    """
    a about above across after again against all also am an and any are as at be because
    been before being below between both but by can could did do does doing down during each
    etc few for from further had has have having he her here hers him his how i if in into
    is it its itself just me more most my no nor not now of off on once only or other our
    ours out over own per same she should so some such than that the their theirs them then
    there these they this those through to too under until up us very via was we were what
    when where which while who whom why will with within without would you your yours
    ability able across work working works experience experiences year years strong
    excellent good great including include includes etc role roles team teams company
    candidate candidates job position responsibilities responsibility requirements required
    requirement preferred plus bonus skills skill knowledge understanding using use used new
    help across must nice have has well world class like looking join us our we you your
    based related equivalent end senior junior degree field fields opportunity opportunities
    environment day days time ensure ensuring provide providing support supporting within
    across partner partners
    """.split()
)

# Common tools/skills that should count even when lowercase or sentence-initial.
KNOWN_SKILLS = set(
    """
    python java javascript typescript go golang rust ruby php scala kotlin swift c c++ c#
    sql nosql postgresql mysql mongodb redis snowflake bigquery redshift databricks dbt spark
    hadoop kafka airflow excel tableau looker powerbi power-bi sas spss matlab r pandas numpy
    react angular vue node.js django flask fastapi rails spring graphql rest html css
    aws azure gcp kubernetes docker terraform ansible linux git ci/cd jenkins jira confluence
    figma sketch salesforce hubspot marketo zendesk sap oracle netsuite quickbooks workday
    seo sem ppc crm erp saas b2b b2c kpi okr agile scrum kanban lean six-sigma pmp
    machine-learning ml ai llm nlp tensorflow pytorch scikit-learn statistics analytics
    photoshop illustrator indesign premiere autocad solidworks revit
    """.split()
)

TECH_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[.+#/-][A-Za-z0-9+#]+)*[+#]*")


def _tokens(text: str) -> list[tuple[str, bool]]:
    """Tokens plus whether each starts a sentence/line (capitalised for grammar)."""
    out = []
    for m in TECH_TOKEN.finditer(text):
        before = text[: m.start()].rstrip(" \t\"'(")
        out.append((m.group(0), not before or before[-1] in ".!?\n•*"))
    return out


def _norm(term: str) -> str:
    return term.lower().strip(".-/")


def extract_keywords(job_description: str, limit: int = 25) -> list[str]:
    tokens = _tokens(job_description)
    scores: Counter[str] = Counter()
    display: dict[str, str] = {}

    for tok, sentence_start in tokens:
        n = _norm(tok)
        if len(n) < 2 or n in STOPWORDS or n.isdigit():
            continue
        if n in KNOWN_SKILLS or re.search(r"[A-Z].*[A-Z]|[0-9+#./]", tok[1:]) or tok.isupper():
            weight = 3.0  # Acronyms and tech-ish tokens: SQL, Node.js, C++, AWS
        elif tok[0].isupper() and not sentence_start:
            weight = 1.5  # Proper nouns: Salesforce, Kubernetes
        else:
            weight = 0.6  # Plain words only count if they recur a lot
        scores[n] += weight
        display.setdefault(n, tok)

    # Two-word phrases that repeat (e.g. "product management", "machine learning").
    words = [_norm(t) for t, _ in tokens]
    for a, b in zip(words, words[1:], strict=False):
        if a in STOPWORDS or b in STOPWORDS or len(a) < 3 or len(b) < 3:
            continue
        phrase = f"{a} {b}"
        scores[phrase] += 1.5
        display.setdefault(phrase, phrase)

    ranked = [
        k for k, v in scores.most_common()
        if v >= 2.0 or (" " not in k and v >= 1.5)
    ]
    phrases = [k for k in ranked if " " in k and scores[k] >= 3.0]
    covered = {w for p in phrases for w in p.split()}
    chosen: list[str] = []
    for k in ranked:
        if " " in k and k not in phrases:
            continue
        if " " not in k and k in covered:
            continue  # Already represented by a phrase, e.g. "distributed systems".
        chosen.append(k)
        if len(chosen) >= limit:
            break
    return [display[k] for k in chosen]


def keyword_report(resume_text: str, job_description: str) -> dict:
    keywords = extract_keywords(job_description)
    haystack = " " + re.sub(r"\s+", " ", resume_text.lower()) + " "
    matched, missing = [], []
    for kw in keywords:
        pattern = r"(?<![a-z0-9])" + re.escape(kw.lower()) + r"(?![a-z0-9])"
        (matched if re.search(pattern, haystack) else missing).append(kw)
    score = round(100 * len(matched) / len(keywords)) if keywords else 0
    return {"score": score, "matched": matched, "missing": missing}
