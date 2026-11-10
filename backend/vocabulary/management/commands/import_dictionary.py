import csv
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from vocabulary.models import Dictionary, Word


class Command(BaseCommand):
    help = "Import a CSV word list into a dictionary."

    def add_arguments(self, parser):
        parser.add_argument("--dictionary", required=True)
        parser.add_argument("--file", required=True)
        parser.add_argument("--publish", action="store_true")

    def handle(self, *args, **options):
        dictionary = Dictionary.objects.filter(name=options["dictionary"]).first()
        if not dictionary:
            raise CommandError(f"dictionary not found: {options['dictionary']}")
        path = Path(options["file"])
        if not path.exists():
            raise CommandError(f"file not found: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if not rows or not {"word", "meaning"}.issubset(rows[0]):
            raise CommandError("CSV must contain word and meaning columns")
        created = updated = skipped = 0
        with transaction.atomic():
            for row in rows:
                spelling = (row.get("word") or "").strip()
                meaning = (row.get("meaning") or "").strip()
                if not spelling or not meaning:
                    skipped += 1
                    continue
                _, is_created = Word.objects.update_or_create(
                    dictionary=dictionary,
                    spelling=spelling,
                    defaults={
                        "phonetic": (row.get("phonetic") or "").strip(),
                        "part_of_speech": (row.get("part_of_speech") or "").strip(),
                        "meaning": meaning,
                        "example": (row.get("example") or "").strip(),
                        "example_translation": (row.get("example_translation") or row.get("example_zh") or "").strip(),
                        "audio_url": (row.get("audio_url") or "").strip(),
                    },
                )
                created += int(is_created)
                updated += int(not is_created)
        if options["publish"]:
            dictionary.status = "published"
            dictionary.save(update_fields=["status"])
        self.stdout.write(self.style.SUCCESS(
            f"{dictionary.name}: created={created}, updated={updated}, skipped={skipped}, published={options['publish']}"
        ))
