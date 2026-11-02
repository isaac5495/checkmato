"""Independent English hold-out suite (hand-written, different domain).

This is deliberately NOT generated from `tests/eval_en`: different entities,
facts, values and adversarial negatives. Expected labels were written by hand;
none was derived from engine output.
"""

LINES = [
    # Meridian Health — true facts
    "Meridian Health was founded in 1998.",
    "Meridian Health opened its Portland clinic in 2004.",
    "Meridian Health opened its Salem clinic in 2011.",
    "Meridian Health launched a telehealth service in 2017.",
    "Meridian Health opened its Boise clinic in 2021.",
    "Meridian Health opened its Reno clinic in 2024.",
    "Meridian Health reported revenue of US$45 million in 2018.",
    "Meridian Health reported revenue of US$52 million in 2020.",
    "Meridian Health reported revenue of US$68 million in 2022.",
    "Meridian Health reported revenue of US$75 million in 2023.",
    "Meridian Health reported revenue of US$82 million in 2024.",
    "Meridian Health reported revenue of US$90 million in 2025.",
    "Meridian Health held a 12% share of the home care market in 2019.",
    "Meridian Health held an 18% share of the clinic market in 2021.",
    "Meridian Health employed 300 employees in 2020.",
    "Meridian Health employed 450 employees in 2023.",
    'Meridian Health said "we put patients first in every decision".',
    'Meridian Health said "careful follow up matters more than a fast discharge".',
    'Meridian Health said "clinicians should have time to listen".',
    'Meridian Health said "small clinics can deliver excellent care".',
    'Meridian Health said "we measure success by healthy outcomes".',
    # Northwind Logistics — true facts
    "Northwind Logistics was founded in 1990.",
    "Northwind Logistics listed on the exchange in 2002.",
    "Northwind Logistics expanded into rail in 2015.",
    "Northwind Logistics reported revenue of US$80 million in 2016.",
    "Northwind Logistics reported revenue of US$95 million in 2019.",
    "Northwind Logistics held a 7% share of the air freight market in 2017.",
    "Northwind Logistics held a 9% share of the sea freight market in 2020.",
    "Northwind Logistics employed 700 employees in 2021.",
    'Northwind Logistics said "a reliable route is a promise kept".',
    'Northwind Logistics said "drivers know the road better than the map".',
    'Northwind Logistics said "we plan for the weather before we load".',
    # Cobalt Labs — true facts
    "Cobalt Labs was founded in 2005.",
    "Cobalt Labs listed on the exchange in 2019.",
    "Cobalt Labs reported revenue of US$30 million in 2020.",
    "Cobalt Labs held a 25% share of the laboratory market in 2021.",
    "Cobalt Labs employed 120 employees in 2022.",
    'Cobalt Labs said "good science starts with a clear question".',
    'Cobalt Labs said "we publish methods before results".',
    'Cobalt Labs said "quality is a habit in the lab".',
    # Decoys that must not create support
    "Meridian Health Cloud is a separate subsidiary.",
    "Meridian Hospitals is a different network.",
    "In the 1990s Meridian Health expanded across the region.",
]

SOURCES = {"holdout.md": "# Hold-out sources\n\n" + "\n\n".join(LINES) + "\n"}

TRUE = [
    {"sentence": "Meridian Health was founded in 1998.", "type": "year"},
    {"sentence": "Meridian Health opened its Portland clinic in 2004.",
     "type": "year"},
    {"sentence": "Meridian Health opened its Salem clinic in 2011.",
     "type": "year"},
    {"sentence": "Meridian Health launched a telehealth service in 2017.",
     "type": "year"},
    {"sentence": "Meridian Health opened its Boise clinic in 2021.",
     "type": "year"},
    {"sentence": "Meridian Health opened its Reno clinic in 2024.",
     "type": "year"},
    {"sentence": "Meridian Health reported revenue of US$45 million in 2018.",
     "type": "amount"},
    {"sentence": "Meridian Health reported revenue of US$52 million in 2020.",
     "type": "amount"},
    {"sentence": "Meridian Health reported revenue of US$68 million in 2022.",
     "type": "amount"},
    {"sentence": "Meridian Health reported revenue of US$75 million in 2023.",
     "type": "amount"},
    {"sentence": "Meridian Health reported revenue of US$82 million in 2024.",
     "type": "amount"},
    {"sentence": "Meridian Health reported revenue of US$90 million in 2025.",
     "type": "amount"},
    {"sentence": "Meridian Health held a 12% share of the home care market "
                 "in 2019.", "type": "pct"},
    {"sentence": "Meridian Health held an 18% share of the clinic market "
                 "in 2021.", "type": "pct"},
    {"sentence": "Meridian Health employed 300 employees in 2020.",
     "type": "count"},
    {"sentence": "Meridian Health employed 450 employees in 2023.",
     "type": "count"},
    {"sentence": 'Meridian Health said "we put patients first in every '
                 'decision".', "type": "quote"},
    {"sentence": 'Meridian Health said "careful follow up matters more than '
                 'a fast discharge".', "type": "quote"},
    {"sentence": 'Meridian Health said "clinicians should have time to '
                 'listen".', "type": "quote"},
    {"sentence": 'Meridian Health said "small clinics can deliver excellent '
                 'care".', "type": "quote"},
    {"sentence": 'Meridian Health said "we measure success by healthy '
                 'outcomes".', "type": "quote"},
    {"sentence": "Northwind Logistics was founded in 1990.", "type": "year"},
    {"sentence": "Northwind Logistics listed on the exchange in 2002.",
     "type": "year"},
    {"sentence": "Northwind Logistics expanded into rail in 2015.",
     "type": "year"},
    {"sentence": "Northwind Logistics reported revenue of US$80 million "
                 "in 2016.", "type": "amount"},
    {"sentence": "Northwind Logistics reported revenue of US$95 million "
                 "in 2019.", "type": "amount"},
    {"sentence": "Northwind Logistics held a 7% share of the air freight "
                 "market in 2017.", "type": "pct"},
    {"sentence": "Northwind Logistics held a 9% share of the sea freight "
                 "market in 2020.", "type": "pct"},
    {"sentence": "Northwind Logistics employed 700 employees in 2021.",
     "type": "count"},
    {"sentence": 'Northwind Logistics said "a reliable route is a promise '
                 'kept".', "type": "quote"},
    {"sentence": 'Northwind Logistics said "drivers know the road better '
                 'than the map".', "type": "quote"},
    {"sentence": 'Northwind Logistics said "we plan for the weather before '
                 'we load".', "type": "quote"},
    {"sentence": "Cobalt Labs was founded in 2005.", "type": "year"},
    {"sentence": "Cobalt Labs listed on the exchange in 2019.", "type": "year"},
    {"sentence": "Cobalt Labs reported revenue of US$30 million in 2020.",
     "type": "amount"},
    {"sentence": "Cobalt Labs held a 25% share of the laboratory market "
                 "in 2021.", "type": "pct"},
    {"sentence": "Cobalt Labs employed 120 employees in 2022.", "type": "count"},
    {"sentence": 'Cobalt Labs said "good science starts with a clear '
                 'question".', "type": "quote"},
    {"sentence": 'Cobalt Labs said "we publish methods before results".',
     "type": "quote"},
    {"sentence": 'Cobalt Labs said "quality is a habit in the lab".',
     "type": "quote"},
]

FALSE = [
    # Same value as Meridian, different subject (value-only trap).
    {"sentence": "Cobalt Labs reported revenue of US$45 million in 2020.",
     "type": "amount", "expected": "not_supported"},
    # Wrong year for an existing site: a genuine contradiction is correct.
    {"sentence": "Meridian Health opened its Portland clinic in 2005.",
     "type": "year", "expected": "contradicted"},
    # Subsidiary must not borrow the parent's fact.
    {"sentence": "Meridian Health Cloud held a 12% share of the home care "
                 "market in 2019.", "type": "pct", "expected": "not_supported"},
    # Currency mismatch.
    {"sentence": "Meridian Health reported revenue of 52 million yuan in 2020.",
     "type": "amount", "expected": "not_supported"},
    # Lookalike name.
    {"sentence": "Meridian Hospitals reported revenue of US$68 million in 2022.",
     "type": "amount", "expected": "not_supported"},
    # Paraphrased quote: flagged, never a verbatim support.
    {"sentence": 'Meridian Health said "we put patients first in all we do".',
     "type": "quote", "expected": "not_supported"},
]

PROSE_TEXT = [
    "Meridian Health treats patients as partners in their own care.",
    "Northwind Logistics values reliability over speed.",
    "Cobalt Labs encourages researchers to question assumptions.",
    "The board prefers a long-term view to a quarterly one.",
    "Managers write down what they learn from failed projects.",
    "Hiring looks for judgement as much as technical skill.",
]

PROSE = [{"sentence": s, "type": "prose", "expected": "not_checked"}
         for s in PROSE_TEXT]
CASES = ([dict(c, expected="supported") for c in TRUE] + FALSE + PROSE)
