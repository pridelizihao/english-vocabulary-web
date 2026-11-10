# Public word-list sources

Downloaded on 2026-11-08 from `imfiiish/wordlists`:

- `CET.json`: CET4/CET6 groups described by the repository as based on the
  2016 revised College English Test syllabus.
- `definitions.json`: Chinese definitions, phonetics and parts of speech.
- Repository: https://github.com/imfiiish/wordlists

The repository's processing code is MIT licensed and attributes dictionary
content to ECDICT. Check the upstream repository and its license files before
commercial publication or redistribution. This project keeps the source files
and this note so the data provenance remains visible.

Generated editions:

- `cet4_core_3500.csv`: the first 3500 CET4 entries in stable alphabetical
  order. It is a core 3500 subset, not a claim that the official CET4 list has
  exactly 3500 entries.
- `cet4_cet6_core_5000.csv`: the first 5000 unique CET4/CET6 entries in stable
  alphabetical order.

Regenerate with `python data/scripts/build_wordlists.py`.
