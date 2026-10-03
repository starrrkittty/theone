"""Fetch public guidance as provenance snapshots, without auto-approving summaries."""
import hashlib
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).parent


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hidden = 0
        self.text = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden and data.strip():
            self.text.append(data.strip())


def main():
    sources = json.loads((ROOT / "sources.json").read_text(encoding="utf-8"))
    snapshots = ROOT / "snapshots"
    snapshots.mkdir(exist_ok=True)
    results = []
    for source in sources:
        if source["id"] not in {"who_healthy_diet_2024", "who_physical_activity_2020", "ace_squat", "nhs_strength", "ace_front_plank", "ace_knee_pushup", "ace_bent_row", "ace_reverse_lunge", "fry_knee_position_2003"}:
            continue
        try:
            fetch_url = source.get("retrieval_url", source["url"])
            with urlopen(Request(fetch_url, headers={"User-Agent": "Mozilla/5.0"}), timeout=20) as response:
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Page exceeds size limit")
            parser = TextParser()
            if source["id"] == "fry_knee_position_2003":
                rows = json.loads(raw)["resultList"]["result"]
                article = next(row for row in rows if row["id"] == "14636100")
                parser.feed(article["title"] + "\n" + article["abstractText"])
            else:
                parser.feed(raw.decode("utf-8", errors="replace"))
            text = "\n".join(parser.text)
            if len(text) < 500 or source["title"].lower() not in text.lower():
                raise ValueError("Page does not contain the expected guidance title/content")
            (snapshots / (source["id"] + ".txt")).write_text(text, encoding="utf-8")
            results.append({"id": source["id"], "url": source["url"], "retrieval_url":fetch_url, "fetched_at": datetime.now(timezone.utc).isoformat(), "sha256": hashlib.sha256(raw).hexdigest(), "status": "fetched; summaries require separate review"})
            print(source["id"], "fetched", len(text))
        except Exception as exc:
            results.append({"id": source["id"], "status": "fetch_failed", "error_type": type(exc).__name__})
            print(source["id"], "fetch failed", type(exc).__name__)
    (ROOT / "fetch_manifest.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
