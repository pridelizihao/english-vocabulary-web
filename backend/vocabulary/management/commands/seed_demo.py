"""生成一份「用了一年」的演示数据，用于本地体验和文档截图。

只碰 `--username` 指定的账号，不会影响其他用户。默认账号 demo / Demo12345678。

    python manage.py seed_demo                 # 生成 / 覆盖演示账号
    python manage.py seed_demo --reset         # 连账号一起删掉重建

数据不是随机堆的：间隔、连对次数、作答日期都按真实调度器的节奏摆，
记住的概率随间隔下降，所以热力图、保持率曲线、评分校准都有意义。
"""

import random
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from vocabulary.models import AnswerLog, Dictionary, UserDictionary, UserWordProgress, Word

# 状态 → (间隔天数, 连对次数, 复习次数)；按调度器 1/3/7/19/52/130 的节奏摆
PROGRESS_PLAN = [
    ('mastered', 130, 6, 7), ('mastered', 52, 5, 6), ('mastered', 52, 5, 6), ('mastered', 33, 4, 5),
    ('learning', 19, 4, 4), ('learning', 7, 3, 3), ('learning', 3, 2, 2), ('learning', 1, 1, 1),
]
# 记住的概率随间隔下降：短间隔几乎都记得，长间隔开始遗忘。
KEEP_RATE = {0: 0.96, 1: 0.95, 3: 0.92, 7: 0.90, 8: 0.89, 14: 0.86, 19: 0.82, 33: 0.77}
INTERVALS = [0, 1, 3, 7, 8, 14, 19, 33]


class Command(BaseCommand):
    help = '生成演示用的学习数据（热力图、保持率、评分校准都有内容）'

    def add_arguments(self, parser):
        parser.add_argument('--username', default='demo', help='演示账号（默认 demo）')
        parser.add_argument('--password', default='Demo12345678', help='演示账号密码')
        parser.add_argument('--dictionary', default='', help='词典名或 id，默认第一本官方词典')
        parser.add_argument('--words', type=int, default=140, help='学多少个词（默认 140）')
        parser.add_argument('--days', type=int, default=370, help='把作答流水铺多少天（默认 370）')
        parser.add_argument('--seed', type=int, default=20261116, help='随机种子，固定后结果可复现')
        parser.add_argument('--reset', action='store_true', help='先删掉这个账号再重建')

    def handle(self, *args, **options):
        random.seed(options['seed'])
        User = get_user_model()
        username = options['username']

        dictionary = self._pick_dictionary(options['dictionary'])

        existing = User.objects.filter(username=username).first()
        if options['reset'] and existing:
            AnswerLog.objects.filter(user=existing).delete()
            UserWordProgress.objects.filter(user=existing).delete()
            UserDictionary.objects.filter(user=existing).delete()
            existing.delete()
            existing = None

        user, created = User.objects.get_or_create(
            username=username, defaults={'email': ''},
        )
        user.set_password(options['password'])
        user.save()

        UserDictionary.objects.get_or_create(user=user, dictionary=dictionary)
        AnswerLog.objects.filter(user=user).delete()
        UserWordProgress.objects.filter(user=user).delete()

        now = timezone.now()
        today = timezone.localdate()
        candidates = list(
            Word.objects.filter(dictionary=dictionary).exclude(example='').order_by('id')[: options['words']]
        )
        if not candidates:
            raise CommandError('这本词典还没有带例句的词，先执行 seed_wordlists / enrich_examples')

        progress_rows = self._create_progress(user, candidates, now)
        log_count = self._create_logs(user, dictionary, progress_rows, today, options['days'])

        due = UserWordProgress.objects.filter(user=user, next_review_at__lte=now).exclude(
            status='retired'
        ).count()
        mastered = UserWordProgress.objects.filter(user=user, status='mastered').count()
        self.stdout.write(self.style.SUCCESS(f'演示账号：{username} / {options["password"]}'))
        self.stdout.write(
            f'  词典 {dictionary.name}｜已学 {len(progress_rows)} 词｜已掌握 {mastered}｜'
            f'今日到期 {due}｜答题流水 {log_count} 条（近 {options["days"]} 天）'
        )
        if created:
            self.stdout.write('  账号是新建的')
        self.stdout.write('  提示：这是演示数据，别在正式库里跑；只影响上面这个账号。')

    def _pick_dictionary(self, keyword):
        queryset = Dictionary.objects.filter(status='published').order_by('id')
        if not keyword:
            dictionary = queryset.first()
        elif keyword.isdigit():
            dictionary = queryset.filter(id=int(keyword)).first()
        else:
            dictionary = queryset.filter(name__icontains=keyword).first()
        if dictionary is None:
            raise CommandError('找不到匹配的词典，先执行 seed_wordlists 导入官方词表')
        return dictionary

    def _create_progress(self, user, words, now):
        rows = []
        for index, word in enumerate(words):
            status, interval, streak, review_count = PROGRESS_PLAN[index % len(PROGRESS_PLAN)]
            first = now - timedelta(days=random.randint(max(interval, 1) + 30, 360))
            last = now - timedelta(days=random.randint(0, max(interval - 1, 0)))
            rows.append(UserWordProgress.objects.create(
                user=user,
                word=word,
                status=status,
                streak=streak,
                interval_days=interval,
                ease=round(2.3 + random.random() * 0.6, 2),
                review_count=review_count,
                wrong_count=random.choice([0, 0, 0, 1, 2]) if streak <= 2 else random.choice([0, 1]),
                first_learned_at=first,
                last_review_at=last,
                # 一部分到期（让复习队列不为空），一部分还没到期
                next_review_at=now - timedelta(hours=random.randint(1, 20))
                if index % 5 == 0
                else now + timedelta(days=max(interval, 1)),
            ))
        return rows

    def _create_logs(self, user, dictionary, progress_rows, today, days):
        total = 0
        for offset in range(days, -1, -1):
            day = today - timedelta(days=offset)
            # 早期周末学得断断续续，最近一个月保持连续
            if day.weekday() >= 5 and offset > 30 and random.random() < 0.55:
                continue
            if offset in (46, 47, 88, 129) and random.random() < 0.8:
                continue
            count = random.randint(28, 40) if random.random() < 0.12 else random.randint(3, 14)
            for _ in range(count):
                row = random.choice(progress_rows)
                before = random.choice(INTERVALS)
                rating = self._pick_rating(before)
                stamp = timezone.make_aware(timezone.datetime(
                    day.year, day.month, day.day, random.randint(7, 23), random.randint(0, 59),
                ))
                log = AnswerLog.objects.create(
                    user=user, word=row.word, dictionary=dictionary, rating=rating,
                    is_new=before == 0,
                    is_practice=random.random() < 0.12,
                    mode=random.choice(['card', 'card', 'cloze']),
                    attempts=random.choice([1, 1, 1, 2, 3]),
                    revealed=rating == 'again' and random.random() < 0.6,
                    interval_before=before,
                    interval_after=max(before, 1) if rating != 'again' else 0,
                )
                # created_at 是 auto_now_add，只能在创建后回填
                AnswerLog.objects.filter(pk=log.pk).update(created_at=stamp)
                total += 1
        return total

    @staticmethod
    def _pick_rating(interval_before):
        keep = KEEP_RATE.get(interval_before, 0.8)
        roll = random.random()
        if roll < keep * 0.86:
            return 'good'
        if roll < keep:
            return 'easy'
        if roll < keep + (1 - keep) * 0.55:
            return 'hard'
        return 'again'
