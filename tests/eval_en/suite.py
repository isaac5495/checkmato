"""Synthetic English BYOS evaluation suite.

No real case material. The source library states every true fact explicitly;
false cases are either absent from the library or deliberately wrong. Prose
cases have no figure/quote and must be reported as not-checked, never as
supported.
"""

SITES = [
    "Aurora", "Borealis", "Cascade", "Dover", "Everest", "Falcon",
    "Granite", "Harbor", "Iris", "Juniper", "Keystone", "Lagoon",
]

YEARS = list(range(2001, 2013))

AMOUNTS = [
    (110, "cloud services", 2015), (111, "office software", 2016),
    (112, "security products", 2017), (113, "gaming", 2018),
    (114, "cloud storage", 2019), (115, "support contracts", 2020),
    (116, "education", 2021), (117, "government", 2022),
    (118, "small business", 2023), (119, "enterprise", 2024),
    (120, "international", 2025), (121, "services", 2026),
]

PCTS = [
    (41, "cloud", 2016), (42, "office", 2017), (43, "security", 2018),
    (44, "gaming", 2019), (45, "storage", 2020), (46, "education", 2021),
    (47, "government", 2022), (48, "enterprise", 2023),
]

COUNTS = [
    (1200, 2017), (1300, 2018), (1400, 2019), (1500, 2020),
    (1600, 2021), (1700, 2022), (1800, 2023), (1900, 2024),
]

QUOTES = [
    "we build reliable tools for every team",
    "steady work beats a clever shortcut",
    "customers notice the details we keep",
    "long term thinking guides every release",
    "small improvements compound over time",
    "trust is earned release after release",
    "clarity helps a team move faster",
    "we measure success by repeat use",
    "quality is a habit not a phase",
    "listen first then build the tool",
]

LINES = []
TRUE = []
FALSE = []
PROSE = []

for site, year in zip(SITES, YEARS):
    sentence = f"Atlas Systems opened its {site} plant in {year}."
    LINES.append(sentence)
    TRUE.append({"sentence": sentence, "type": "year",
                 "expected": "supported"})

for value, metric, year in AMOUNTS:
    sentence = (f"Atlas Systems reported revenue of {value} million dollars "
                f"from {metric} in {year}.")
    LINES.append(sentence)
    TRUE.append({"sentence": sentence, "type": "amount",
                 "expected": "supported"})

for value, metric, year in PCTS:
    sentence = f"Atlas Systems held a {value}% share of the {metric} market in {year}."
    LINES.append(sentence)
    TRUE.append({"sentence": sentence, "type": "pct",
                 "expected": "supported"})

for value, year in COUNTS:
    sentence = f"Atlas Systems employed {value:,} employees in {year}."
    LINES.append(sentence)
    TRUE.append({"sentence": sentence, "type": "count",
                 "expected": "supported"})

for quote in QUOTES:
    sentence = f'Atlas Systems said "{quote}".'
    LINES.append(sentence)
    TRUE.append({"sentence": sentence, "type": "quote",
                 "expected": "supported"})

# False 1: absent entities and years (nothing to support).
for i in range(5):
    sentence = f"Nimbus Labs acquired Cedar Works in {1980 + i}."
    FALSE.append({"sentence": sentence, "type": "year",
                  "expected": "not_supported"})

# False 2: wrong year for an existing site (present but wrong).
for site, year in zip(SITES[:5], range(1991, 1996)):
    sentence = f"Atlas Systems opened its {site} plant in {year}."
    FALSE.append({"sentence": sentence, "type": "year",
                  "expected": "contradicted"})

# Prose: no figure/quote, must be not-checked rather than supported.
PROSE_TEXT = [
    "Atlas Systems values curiosity and long-term thinking.",
    "The company treats customers as long-term partners.",
    "Teams are encouraged to question the default plan.",
    "Managers are expected to explain the reasoning behind decisions.",
    "The culture rewards careful work over dramatic gestures.",
    "Engineers are trusted to choose the right tool.",
    "Support staff are part of the product conversation.",
    "The company prefers small experiments to large bets.",
    "Leaders write down what they learn from failures.",
    "Hiring looks for judgement as much as raw skill.",
]
for sentence in PROSE_TEXT:
    PROSE.append({"sentence": sentence, "type": "prose",
                  "expected": "not_checked"})

SOURCES = {"atlas.md": "# Atlas Systems\n\n" + "\n\n".join(LINES) + "\n"}
CASES = TRUE + FALSE + PROSE
