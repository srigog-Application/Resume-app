"""Instant, offline ATS and content checks for a resume (no AI, no credits).

Each check is a pass/fail with a short explanation; the score is the
weighted share of passed checks. Used by the Analysis page next to the
deeper AI review.
"""

import re

from .resume_data import ResumeData

WEAK_OPENERS = re.compile(
    r"^(responsible for|helped|worked on|assisted|in charge of|duties included|tasked with|"
    r"involved in|participated in)\b", re.I)
PRONOUNS = re.compile(r"\b(I|me|my|we|our)\b")
METRIC = re.compile(r"\d|\[[^\]]+\]")


def _bullets(data: ResumeData) -> list[str]:
    out = [b for e in data.experience for b in e.bullets if b.strip()]
    out += [b for p in data.projects for b in p.bullets if b.strip()]
    return out


def run_checks(data: ResumeData) -> dict:
    b = data.basics
    bullets = _bullets(data)
    with_metrics = [x for x in bullets if METRIC.search(x)]
    weak = [x for x in bullets if WEAK_OPENERS.match(x.strip())]
    long_ = [x for x in bullets if len(x.split()) > 35]
    pronoun = [x for x in bullets + [data.summary] if x and PRONOUNS.search(x)]
    roles = [e for e in data.experience if e.company or e.position]
    thin_roles = [e for e in roles if len([x for x in e.bullets if x.strip()]) < 2]
    undated = [e for e in roles if not e.start_date]
    words = len(" ".join([data.summary, *bullets]).split())

    checks = [
        ("contact", 3, bool(b.name and b.email and (b.phone or b.location)),
         "Name, email and phone or location are present.",
         "Add your name, email and a phone number or city. Recruiters and ATS need them."),
        ("headline", 1, bool(b.headline),
         "Headline states your target title.",
         "Add a headline that matches the title you're applying for."),
        ("summary", 2, 15 <= len(data.summary.split()) <= 90,
         "Summary is a focused 2–4 sentences.",
         "Write a 2–4 sentence summary (about 20–80 words)."),
        ("experience", 3, bool(roles),
         "Work experience section is filled in.",
         "Add at least one position. Projects or volunteering count too."),
        ("dates", 2, bool(roles) and not undated,
         "Every position has dates.",
         f"{len(undated)} position(s) are missing a start date. ATS sort by recency."),
        ("depth", 2, bool(roles) and not thin_roles,
         "Each position has at least 2 achievement bullets.",
         f"{len(thin_roles)} position(s) have fewer than 2 bullets."),
        ("metrics", 3, bool(bullets) and len(with_metrics) / len(bullets) >= 0.5,
         f"{len(with_metrics)} of {len(bullets)} bullets show numbers or results.",
         f"Only {len(with_metrics)} of {len(bullets)} bullets include a number. "
         "Quantify impact (%, $, time saved, users)."),
        ("verbs", 2, not weak,
         "Bullets open with strong action verbs.",
         f"{len(weak)} bullet(s) start with weak phrases like “Responsible for”."),
        ("length", 1, not long_,
         "Bullets are concise (under 35 words).",
         f"{len(long_)} bullet(s) are over 35 words. Split or tighten them."),
        ("pronouns", 1, not pronoun,
         "No first-person pronouns.",
         "Remove “I”, “my” and “we”. Resumes use implied first person."),
        ("skills", 2, any(s.details for s in data.skills),
         "Skills section lists your tools and strengths.",
         "Add a skills section. ATS match on exact tool names."),
        ("education", 1, any(e.institution for e in data.education),
         "Education is listed.",
         "Add education (degree, bootcamp or certification)."),
        ("volume", 1, 150 <= words <= 900,
         "Length looks right for a 1–2 page resume.",
         "Resume is very short. Add more detail." if words < 150
         else "Resume is long. Trim older or less relevant content."),
    ]
    total = sum(w for _, w, *_ in checks)
    score = round(100 * sum(w for _, w, ok, *_ in checks if ok) / total)
    return {
        "score": score,
        "checks": [
            {"id": cid, "passed": ok, "detail": good if ok else bad}
            for cid, _, ok, good, bad in checks
        ],
        "examples": {"weak": weak[:3], "no_metrics": [x for x in bullets
                                                      if not METRIC.search(x)][:3]},
    }
