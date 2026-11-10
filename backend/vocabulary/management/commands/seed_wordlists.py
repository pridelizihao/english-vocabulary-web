"""Import the bundled CET4/CET6 word lists and publish them.

The CSV files live in `data/imports/` at the repository root. Both the local
layout (repo/backend) and the container layout (/app with /app/data) are
supported; when the files are absent the command exits successfully with a
warning so it is safe to call from a container entrypoint.
"""
from pathlib import Path

from django.conf import settings
from django.core.files.base import File
from django.core.management.base import BaseCommand

from vocabulary.models import Dictionary
from vocabulary.services import import_words, parse_import_rows

LISTS = [
    ('cet4_core_3500.csv', '大学英语四级 3500 词', 'CET4 · 3500'),
    ('cet4_cet6_core_5000.csv', '大学英语六级 5000 词', 'CET6 · 5000'),
]


def imports_dir():
    base = Path(settings.BASE_DIR)
    candidates = [base / 'data' / 'imports', base.parent / 'data' / 'imports']
    for path in candidates:
        if path.is_dir() and any(path.glob('*.csv')):
            return path
    return None


class Command(BaseCommand):
    help = 'Import data/imports/*.csv into the CET dictionaries and publish them.'

    def add_arguments(self, parser):
        parser.add_argument('--force', action='store_true', help='重新导入即使词典已有单词')

    def handle(self, *args, **options):
        directory = imports_dir()
        if directory is None:
            self.stderr.write(self.style.WARNING(
                '没有找到 data/imports 目录，跳过词表导入。可先运行 data/scripts/build_wordlists.py。'
            ))
            return

        for filename, name, level in LISTS:
            source = directory / filename
            if not source.exists():
                self.stderr.write(self.style.WARNING(f'跳过 {filename}：文件不存在'))
                continue
            dictionary, _ = Dictionary.objects.get_or_create(
                name=name,
                owner=None,
                defaults={'level': level, 'description': f'{level} 核心词汇', 'status': 'draft'},
            )
            if dictionary.words.exists() and not options['force']:
                self.stdout.write(f'《{name}》已有 {dictionary.words.count()} 个单词，跳过导入。')
            else:
                with source.open('rb') as handle:
                    upload = File(handle, name=source.name)
                    rows = parse_import_rows(upload)
                result = import_words(dictionary, rows)
                self.stdout.write(
                    f'《{name}》：新增 {result["created"]}，更新 {result["updated"]}，'
                    f'跳过 {result["skipped"]}，合并重复 {result["merged"]}'
                )
            dictionary.level = level
            dictionary.status = 'published'
            dictionary.owner = None
            dictionary.save(update_fields=['level', 'status', 'owner'])
            self.stdout.write(self.style.SUCCESS(f'《{name}》已发布，共 {dictionary.words.count()} 个单词。'))
