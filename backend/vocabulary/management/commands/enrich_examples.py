"""Fill example sentences (and their Chinese translation) from data/examples.json.

The JSON file is an offline snapshot so that deployments do not depend on any
dictionary API at runtime. Format:

    {"_meta": {...},
     "words": {"abandon": {"example": "He abandoned the plan.",
                            "zh": "他放弃了这个计划。",
                            "source": "..."}}}

Only words already present in a dictionary are touched; matching is
case-insensitive so `Abandon` and `abandon` share the enrichment.
"""
import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from vocabulary.models import Word


def examples_path():
    base = Path(settings.BASE_DIR)
    for candidate in (base / 'data' / 'examples.json', base.parent / 'data' / 'examples.json'):
        if candidate.exists():
            return candidate
    return None


class Command(BaseCommand):
    help = 'Enrich words with example sentences from data/examples.json.'

    def add_arguments(self, parser):
        parser.add_argument('--path', help='自定义 examples.json 路径')
        parser.add_argument('--force', action='store_true', help='覆盖已有例句')
        parser.add_argument('--dry-run', action='store_true', help='只统计不写库')

    def handle(self, *args, **options):
        path = Path(options['path']) if options['path'] else examples_path()
        if path is None or not path.exists():
            raise CommandError('找不到 data/examples.json，请先生成例句文件或传 --path')

        payload = json.loads(path.read_text(encoding='utf-8'))
        entries = payload.get('words', payload)
        if not isinstance(entries, dict):
            raise CommandError('examples.json 格式不对：需要 {"words": {"单词": {...}}}')

        updated = produced = skipped = unchanged = 0
        missing = []
        for spelling, data in entries.items():
            if not isinstance(data, dict):
                continue
            example = (data.get('example') or '').strip()
            translation = (data.get('zh') or data.get('translation') or '').strip()
            if not example:
                skipped += 1
                continue
            words = list(Word.objects.filter(spelling__iexact=spelling))
            if not words:
                missing.append(spelling)
                continue
            for word in words:
                fields = []
                # The translation is only meaningful for the example it belongs to,
                # so never attach it to a different, hand-written example.
                if options['force'] or not word.example:
                    if word.example != example:
                        word.example = example
                        fields.append('example')
                    if translation and (options['force'] or not word.example_translation):
                        word.example_translation = translation
                        fields.append('example_translation')
                elif not word.example_translation and translation and word.example.strip() == example:
                    word.example_translation = translation
                    fields.append('example_translation')
                if fields:
                    if not options['dry_run']:
                        word.save(update_fields=fields)
                    updated += 1
                else:
                    unchanged += 1
            produced += 1

        if missing:
            preview = '、'.join(missing[:10])
            self.stderr.write(self.style.WARNING(f'{len(missing)} 个词不在任何词典里，已跳过：{preview}'))

        action = '将更新' if options['dry_run'] else '已更新'
        self.stdout.write(self.style.SUCCESS(
            f'{action} {updated} 条单词记录；文件内 {produced} 个词命中，'
            f'{unchanged} 条已有例句未动，{skipped} 条缺少英文例句。'
        ))
