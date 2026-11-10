import csv
from pathlib import Path

from django.core.management.base import BaseCommand

from vocabulary.models import Dictionary, Word


class Command(BaseCommand):
    help = 'Create or refresh the published demo dictionary from data/samples/words.csv.'

    def handle(self, *args, **options):
        dictionary, created = Dictionary.objects.get_or_create(
            name='示例英语词汇',
            defaults={'level': 'CET4', 'description': '用于验证学习闭环的示例词典', 'status': 'published'},
        )
        dictionary.level = 'CET4'
        dictionary.description = '用于验证学习闭环的示例词典'
        dictionary.status = 'published'
        dictionary.save(update_fields=['level', 'description', 'status'])
        source = Path(__file__).resolve().parents[4] / 'data' / 'samples' / 'words.csv'
        with source.open(encoding='utf-8-sig', newline='') as handle:
            rows = csv.DictReader(handle)
            count = 0
            for row in rows:
                spelling = (row.get('word') or '').strip()
                if not spelling or not (row.get('meaning') or '').strip():
                    continue
                Word.objects.update_or_create(
                    dictionary=dictionary,
                    spelling=spelling,
                    defaults={
                        'phonetic': (row.get('phonetic') or '').strip(),
                        'part_of_speech': (row.get('part_of_speech') or '').strip(),
                        'meaning': (row.get('meaning') or '').strip(),
                        'example': (row.get('example') or '').strip(),
                        'audio_url': (row.get('audio_url') or '').strip(),
                    },
                )
                count += 1
        self.stdout.write(self.style.SUCCESS(f'已准备示例词典：{dictionary.name}，单词 {count} 个。'))

        for name, level, description in [
            ('大学英语四级 3500 词', 'CET4 · 3500', '四级核心词汇，导入授权词表后即可发布学习。'),
            ('大学英语六级 5000 词', 'CET6 · 5000', '六级核心词汇，导入授权词表后即可发布学习。'),
        ]:
            Dictionary.objects.get_or_create(
                name=name,
                defaults={'level': level, 'description': description, 'status': 'draft'},
            )
        self.stdout.write(self.style.SUCCESS('已创建 3500 词和 5000 词典入口；请在后台导入授权词表后发布。'))
