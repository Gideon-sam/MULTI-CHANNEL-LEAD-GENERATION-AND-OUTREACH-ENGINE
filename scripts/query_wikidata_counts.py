"""One-off feasibility check for public creator records in Wikidata."""

from __future__ import annotations

import certifi
import httpx

ENDPOINT = "https://query.wikidata.org/sparql"
COUNTRIES = {
    "US": "Q30",
    "CA": "Q16",
    "GB": "Q145",
    "IE": "Q27",
    "AU": "Q408",
    "NZ": "Q664",
    "SG": "Q334",
}
OCCUPATIONS = {
    "YouTuber": "Q17125263",
    "vlogger": "Q4110598",
    "podcaster": "Q15077007",
    "content creator": "Q109459317",
    "business consultant": "Q16849727",
    "motivational speaker": "Q15982858",
    "educator": "Q974144",
    "entrepreneur": "Q131524",
}


def query(sparql: str) -> list[dict]:
    sparql = " ".join(sparql.split())
    response = httpx.get(
        ENDPOINT,
        params={"format": "json", "query": sparql},
        headers={
            "Accept": "application/sparql-results+json",
            "User-Agent": "IncuBrixAssessmentResearch/0.1",
        },
        verify=certifi.where(),
        timeout=90,
    )
    response.raise_for_status()
    return response.json()["results"]["bindings"]


for occupation_name, occupation_qid in OCCUPATIONS.items():
    counts = {}
    for country_code, country_qid in COUNTRIES.items():
        sparql = f"""
        SELECT ?person ?channel WHERE {{
          ?person wdt:P106 wd:{occupation_qid} .
          ?person wdt:P27 wd:{country_qid} .
          ?person wdt:P2397 ?channel .
        }} LIMIT 1000
        """
        rows = query(sparql)
        counts[country_code] = len({row["person"]["value"] for row in rows})
    print(occupation_name, counts, "total=", sum(counts.values()))
