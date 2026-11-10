"""Build importable CSV dictionaries from the downloaded public word lists.

The source repository publishes CET4/CET6 groups and a matching Chinese
definition file.  The product editions are deterministic subsets so their
names do not imply that they are an official 3500/5000-word exam list.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "data" / "sources"
OUT = ROOT / "data" / "imports"


def meaning_text(entry):
    if not entry:
        return ""
    parts = []
    for item in entry[1] if len(entry) > 1 else []:
        if len(item) > 1 and isinstance(item[1], list):
            parts.extend(str(value) for value in item[1] if value)
    return "; ".join(dict.fromkeys(parts))


def build(name, words, definitions):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for word in sorted(set(words), key=str.casefold):
        key = word.strip()
        entry = definitions.get(key) or definitions.get(key.lower())
        if not entry:
            continue
        rows.append({
            "word": key,
            "phonetic": str(entry[0] or "").strip(),
            "part_of_speech": "; ".join(dict.fromkeys(
                str(item[0]).strip() for item in entry[1] if item and item[0]
            )),
            "meaning": meaning_text(entry),
            "example": "",
            "audio_url": "",
        })
    path = OUT / name
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else ["word", "phonetic", "part_of_speech", "meaning", "example", "audio_url"])
        writer.writeheader()
        writer.writerows(rows)
    return path, len(rows)


def main():
    cet = json.loads((SOURCES / "CET.json").read_text(encoding="utf-8"))
    definitions = json.loads((SOURCES / "definitions.full.json").read_text(encoding="utf-8"))
    cet4 = sorted(cet["CET4"], key=str.casefold)
    combined = sorted(set(cet["CET4"]) | set(cet["CET6"]), key=str.casefold)
    for filename, words in (("cet4_core_3500.csv", cet4[:3500]), ("cet4_cet6_core_5000.csv", combined[:5000])):
        path, count = build(filename, words, definitions)
        print(f"{path}: {count} rows")


if __name__ == "__main__":
    main()
