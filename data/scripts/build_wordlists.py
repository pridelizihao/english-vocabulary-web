"""Build importable CSV dictionaries from the downloaded public word lists.

The source repository publishes CET4/CET6 groups and a matching Chinese
definition file.  The product editions are deterministic subsets so their
names do not imply that they are an official 3500/5000-word exam list.
Example sentences come from `data/examples.json` when that file exists.
"""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "data" / "sources"
OUT = ROOT / "data" / "imports"
EXAMPLES = ROOT / "data" / "examples.json"
OXFORD = SOURCES / "Oxford.json"


def meaning_text(entry):
    if not entry:
        return ""
    parts = []
    for item in entry[1] if len(entry) > 1 else []:
        if len(item) > 1 and isinstance(item[1], list):
            parts.extend(str(value) for value in item[1] if value)
    return "; ".join(dict.fromkeys(parts))


def load_cefr():
    if not OXFORD.exists():
        return {}, {}
    payload = json.loads(OXFORD.read_text(encoding="utf-8"))
    exact, lower = {}, {}
    for section in ("Oxford3000", "Oxford5000"):
        for word, entry in payload.get(section, {}).items():
            if not entry:
                continue
            level = next(iter(entry))
            exact.setdefault(word, level)
            lower.setdefault(word.lower(), level)
    return exact, lower


def cefr_of(word, exact, lower):
    return exact.get(word) or lower.get(word.lower()) or ""


def load_examples():
    if not EXAMPLES.exists():
        return {}, {}
    payload = json.loads(EXAMPLES.read_text(encoding="utf-8"))
    words = payload.get("words", payload)
    by_lower = {key.lower(): value for key, value in words.items()}
    return words, by_lower


def build(name, words, definitions, examples, examples_ci, cefr_exact, cefr_lower):
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for word in sorted(set(words), key=str.casefold):
        key = word.strip()
        entry = definitions.get(key) or definitions.get(key.lower())
        if not entry:
            continue
        example = examples.get(key) or examples.get(key.lower()) or examples_ci.get(key.lower()) or {}
        rows.append({
            "word": key,
            "phonetic": str(entry[0] or "").strip(),
            "part_of_speech": "; ".join(dict.fromkeys(
                str(item[0]).strip() for item in entry[1] if item and item[0]
            )),
            "meaning": meaning_text(entry),
            "example": (example.get("example") or "").strip(),
            "example_translation": (example.get("zh") or "").strip(),
            "audio_url": "",
            "cefr": cefr_of(key, cefr_exact, cefr_lower),
        })
    path = OUT / name
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]) if rows else [
            "word", "phonetic", "part_of_speech", "meaning",
            "example", "example_translation", "audio_url", "cefr",
        ])
        writer.writeheader()
        writer.writerows(rows)
    return path, len(rows)


def main():
    cet = json.loads((SOURCES / "CET.json").read_text(encoding="utf-8"))
    definitions = json.loads((SOURCES / "definitions.full.json").read_text(encoding="utf-8"))
    examples, examples_ci = load_examples()
    cefr_exact, cefr_lower = load_cefr()
    cet4 = sorted(cet["CET4"], key=str.casefold)
    combined = sorted(set(cet["CET4"]) | set(cet["CET6"]), key=str.casefold)
    for filename, words in (("cet4_core_3500.csv", cet4[:3500]), ("cet4_cet6_core_5000.csv", combined[:5000])):
        path, count = build(filename, words, definitions, examples, examples_ci, cefr_exact, cefr_lower)
        print(f"{path}: {count} rows")


if __name__ == "__main__":
    main()
