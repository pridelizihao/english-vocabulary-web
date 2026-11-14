from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Dictionary(models.Model):
    """A word list. `owner` is null for official dictionaries."""

    STATUS_CHOICES = [('draft', '草稿'), ('published', '已发布')]
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    level = models.CharField(max_length=80, blank=True)
    version = models.CharField(max_length=40, default='1.0')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name='dictionaries',
        help_text='为空表示官方词典，所有用户可见',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['id']
        verbose_name_plural = 'dictionaries'
        constraints = [
            # 官方词典（owner 为空）可以重名，个人词典不允许同名重复导入。
            models.UniqueConstraint(fields=['owner', 'name'], name='unique_owner_dictionary_name'),
        ]
        indexes = [models.Index(fields=['status', 'owner'], name='dict_status_owner_idx')]

    def __str__(self):
        return self.name

    @property
    def is_personal(self):
        return self.owner_id is not None


class Word(models.Model):
    dictionary = models.ForeignKey(Dictionary, on_delete=models.CASCADE, related_name='words')
    spelling = models.CharField(max_length=120)
    phonetic = models.CharField(max_length=120, blank=True)
    pronunciation_url = models.URLField(blank=True)
    part_of_speech = models.CharField(max_length=80, blank=True)
    meaning = models.TextField()
    # CEFR level (A1/A2/B1/B2/C1) from the Oxford 3000/5000 lists; empty when
    # the word is not in those lists. Used to order new words by exam value.
    cefr = models.CharField(max_length=2, blank=True, default='')
    # Months, weekdays and names ("April", "AIDS") sort last in the core order.
    is_proper = models.BooleanField(default=False)
    example = models.TextField(blank=True)
    example_translation = models.TextField(blank=True)
    audio_url = models.URLField(blank=True)

    class Meta:
        ordering = ['id']
        constraints = [
            # 大小写不敏感的唯一约束：Abandon / abandon 视为同一个词。
            models.UniqueConstraint(Lower('spelling'), 'dictionary', name='unique_dictionary_word_ci'),
        ]
        indexes = [models.Index(fields=['dictionary', 'spelling'], name='word_dict_spelling_idx')]

    def __str__(self):
        return self.spelling


class UserDictionary(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    dictionary = models.ForeignKey(Dictionary, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'dictionary'], name='unique_user_dictionary')]


class UserWordProgress(models.Model):
    """Per-user learning state of one word.

    `streak` counts consecutive good/easy answers and drives the interval table;
    `first_learned_at` is used to enforce the daily new-word budget.
    """

    STATUS_CHOICES = [
        ('new', '未开始'),
        ('learning', '学习中'),
        ('mastered', '已掌握'),
        ('retired', '已归档'),
    ]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new')
    review_count = models.PositiveIntegerField(default=0)
    wrong_count = models.PositiveIntegerField(default=0)
    streak = models.PositiveIntegerField(default=0)
    ease = models.FloatField(default=2.5)
    next_review_at = models.DateTimeField(default=timezone.now)
    last_review_at = models.DateTimeField(null=True, blank=True)
    first_learned_at = models.DateTimeField(null=True, blank=True)
    interval_days = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'word'], name='unique_user_word')]
        indexes = [
            models.Index(fields=['user', 'next_review_at'], name='progress_user_due_idx'),
            models.Index(fields=['user', 'first_learned_at'], name='progress_user_new_idx'),
        ]

    def __str__(self):
        return f'{self.user} · {self.word}'


class EmailAddress(models.Model):
    """A verified email that can sign in and receive password resets.

    Kept separate from `auth.User.email` because that column is not unique and
    is nullable; this table is the single source of truth for "which account
    owns this address".
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='email_addresses',
    )
    email = models.EmailField(max_length=254, unique=True)
    verified_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = 'email addresses'

    def __str__(self):
        return self.email


class EmailVerification(models.Model):
    """A one-shot verification code.

    Only a salted hash of the code is stored: a database leak must not hand an
    attacker a valid login code. Rows are append-only; a row is spent when
    `consumed_at` is set (verified, too many attempts, or superseded).
    """

    PURPOSE_LOGIN = 'login'
    PURPOSE_RESET = 'reset'
    PURPOSE_BIND = 'bind'
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, '登录 / 注册'),
        (PURPOSE_RESET, '重置密码'),
        (PURPOSE_BIND, '绑定邮箱'),
    ]

    email = models.EmailField(max_length=254)
    purpose = models.CharField(max_length=16, choices=PURPOSE_CHOICES)
    code_hash = models.CharField(max_length=128)
    salt = models.CharField(max_length=32)
    attempts = models.PositiveIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    ip = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['email', 'purpose', 'created_at'], name='emailcode_lookup_idx'),
            models.Index(fields=['ip', 'created_at'], name='emailcode_ip_idx'),
        ]

    def __str__(self):
        return f'{self.email} · {self.purpose}'

    @property
    def is_spent(self):
        return self.consumed_at is not None

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


class AnswerLog(models.Model):
    """Append-only record of every answer, used for the activity dashboard.

    `UserWordProgress` only keeps the latest state per word, so daily / weekly
    habit charts need this event log. Practice answers (`is_practice`) never
    change the scheduling state; they are logged for statistics only.
    """

    RATING_CHOICES = [('again', '忘记了'), ('hard', '模糊'), ('good', '记住了'), ('easy', '很熟')]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='answer_logs')
    word = models.ForeignKey(Word, on_delete=models.CASCADE, related_name='answer_logs')
    dictionary = models.ForeignKey(Dictionary, on_delete=models.CASCADE, related_name='answer_logs')
    rating = models.CharField(max_length=10, choices=RATING_CHOICES)
    is_new = models.BooleanField(default=False)
    is_extra = models.BooleanField(default=False)
    is_practice = models.BooleanField(default=False)
    # "I already know this word": jumps straight to mastered (365 days).
    is_skip = models.BooleanField(default=False)
    interval_before = models.PositiveIntegerField(default=0)
    interval_after = models.PositiveIntegerField(default=0)
    # Snapshot of the progress row *before* this answer, so the answer can be
    # undone without recomputing the scheduler backwards. Empty for practice
    # answers (they never touch the schedule).
    state_before = models.JSONField(default=dict, blank=True)
    undone_at = models.DateTimeField(null=True, blank=True)
    # Client generated idempotency key; at most one log per user and token.
    client_token = models.CharField(max_length=64, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'created_at'], name='answerlog_user_time_idx'),
            models.Index(fields=['user', 'dictionary'], name='answerlog_user_dict_idx'),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'client_token'],
                condition=~models.Q(client_token=''),
                name='answerlog_user_token_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.user} · {self.word} · {self.rating}'
