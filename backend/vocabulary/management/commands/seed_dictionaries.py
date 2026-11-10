"""Create or refresh the official CET dictionary entries.

The dictionaries start as drafts; `seed_wordlists` imports the bundled CSV
files and publishes them. Keeping this command separate means a fresh install
has the two dictionary entries even when the word lists are not shipped.
"""
from django.core.management.base import BaseCommand

from vocabulary.models import Dictionary

OFFICIAL_DICTIONARIES = [
    ('大学英语四级 3500 词', 'CET4 · 3500', '四级核心词汇，按字母序截取的前 3500 个词条。'),
    ('大学英语六级 5000 词', 'CET6 · 5000', '四级与六级合并后按字母序截取的前 5000 个词条。'),
]


class Command(BaseCommand):
    help = 'Create or refresh the official CET dictionary entries (draft until imported).'

    def handle(self, *args, **options):
        for name, level, description in OFFICIAL_DICTIONARIES:
            dictionary, created = Dictionary.objects.update_or_create(
                name=name,
                owner=None,
                defaults={'level': level, 'description': description},
            )
            action = '创建' if created else '更新'
            self.stdout.write(f'{action}《{dictionary.name}》：{dictionary.words.count()} 个单词')
        self.stdout.write(self.style.SUCCESS('官方词典入口已就绪；运行 seed_wordlists 导入词表并发布。'))
