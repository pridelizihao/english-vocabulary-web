import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from ...models import Word


def load_levels(path):
    payload = json.loads(path.read_text(encoding='utf-8'))
    exact = {}
    lower = {}
    for section in ('Oxford3000', 'Oxford5000'):
        for word, entry in payload.get(section, {}).items():
            if not entry:
                continue
            level = next(iter(entry))
            exact.setdefault(word, level)
            lower.setdefault(word.lower(), level)
    return exact, lower


class Command(BaseCommand):
    """Fill Word.cefr / Word.is_proper from the Oxford 3000/5000 list.

    The two official dictionaries were seeded from CET lists before CEFR data
    existed, so this command backfills them in place (idempotent).
    """

    help = 'Fill Word.cefr and Word.is_proper from data/sources/Oxford.json'

    def add_arguments(self, parser):
        parser.add_argument('--file', default='data/sources/Oxford.json')
        parser.add_argument('--dry-run', action='store_true')

    def handle(self, *args, **options):
        path = Path(options['file'])
        if not path.is_absolute():
            path = Path(settings.BASE_DIR).parent / path
        if not path.exists():
            raise CommandError(f'找不到词表文件：{path}')

        exact, lower = load_levels(path)
        updates = []
        for word in Word.objects.all().iterator():
            level = exact.get(word.spelling) or lower.get(word.spelling.lower()) or ''
            proper = word.spelling != word.spelling.lower()
            if word.cefr != level or word.is_proper != proper:
                word.cefr = level
                word.is_proper = proper
                updates.append(word)

        if updates and not options['dry_run']:
            Word.objects.bulk_update(updates, ['cefr', 'is_proper'], batch_size=500)

        action = 'would update' if options['dry_run'] else 'updated'
        self.stdout.write(f'{action} {len(updates)} words ({len(exact)} Oxford entries)')
