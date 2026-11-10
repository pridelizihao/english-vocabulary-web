import csv
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from vocabulary.models import Dictionary, Word

DEMO_NAME = '示例英语词汇'
EXTRA_DICTIONARIES = [
    ('大学英语四级 3500 词', 'CET4 · 3500', '四级核心词汇，运行 seed_wordlists 可导入 data/imports 中的词表。'),
    ('大学英语六级 5000 词', 'CET6 · 5000', '六级核心词汇，运行 seed_wordlists 可导入 data/imports 中的词表。'),
]


def sample_paths():
    base = Path(settings.BASE_DIR)
    return [
        base / 'data' / 'samples' / 'words.csv',
        base.parent / 'data' / 'samples' / 'words.csv',
        Path(__file__).resolve().parents[4] / 'data' / 'samples' / 'words.csv',
    ]


class Command(BaseCommand):
    help = 'Create or refresh the published demo dictionary from data/samples/words.csv.'

    def handle(self, *args, **options):
        dictionary, _ = Dictionary.objects.get_or_create(
            name=DEMO_NAME,
            defaults={'level': 'CET4', 'description': '用于验证学习闭环的示例词典', 'status': 'published'},
        )
        dictionary.level = 'CET4'
        dictionary.description = '用于验证学习闭环的示例词典'
        dictionary.status = 'published'
        dictionary.owner = None
        dictionary.save(update_fields=['level', 'description', 'status', 'owner'])

        source = next((path for path in sample_paths() if path.exists()), None)
        if source is None:
            self.stderr.write(self.style.WARNING(
                '没有找到 data/samples/words.csv，跳过了示例单词导入（示例词典仍会创建）。'
            ))
        else:
            count = 0
            with source.open(encoding='utf-8-sig', newline='') as handle:
                for row in csv.DictReader(handle):
                    spelling = (row.get('word') or '').strip()
                    meaning = (row.get('meaning') or '').strip()
                    if not spelling or not meaning:
                        continue
                    Word.objects.update_or_create(
                        dictionary=dictionary,
                        spelling=spelling,
                        defaults={
                            'phonetic': (row.get('phonetic') or '').strip(),
                            'part_of_speech': (row.get('part_of_speech') or '').strip(),
                            'meaning': meaning,
                            'example': (row.get('example') or '').strip(),
                            'audio_url': (row.get('audio_url') or '').strip(),
                        },
                    )
                    count += 1
            self.stdout.write(self.style.SUCCESS(f'已准备示例词典：{dictionary.name}，单词 {count} 个。'))

        for name, level, description in EXTRA_DICTIONARIES:
            Dictionary.objects.get_or_create(
                name=name,
                owner=None,
                defaults={'level': level, 'description': description, 'status': 'draft'},
            )
        self.stdout.write(self.style.SUCCESS('已创建 3500 词和 5000 词典入口；运行 seed_wordlists 可导入并发布。'))
