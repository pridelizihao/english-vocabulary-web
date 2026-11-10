from django.conf import settings
from django.db import models
from django.utils import timezone

class Dictionary(models.Model):
    STATUS_CHOICES = [('draft', '草稿'), ('published', '已发布')]
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    level = models.CharField(max_length=80, blank=True)
    version = models.CharField(max_length=40, default='1.0')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    created_at = models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name

class Word(models.Model):
    dictionary = models.ForeignKey(Dictionary, on_delete=models.CASCADE, related_name='words')
    spelling = models.CharField(max_length=120)
    phonetic = models.CharField(max_length=120, blank=True)
    pronunciation_url = models.URLField(blank=True)
    part_of_speech = models.CharField(max_length=80, blank=True)
    meaning = models.TextField()
    example = models.TextField(blank=True)
    audio_url = models.URLField(blank=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['dictionary', 'spelling'], name='unique_dictionary_word')]
        ordering = ['id']
    def __str__(self): return self.spelling

class UserDictionary(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    dictionary = models.ForeignKey(Dictionary, on_delete=models.CASCADE)
    started_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'dictionary'], name='unique_user_dictionary')]

class UserWordProgress(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    word = models.ForeignKey(Word, on_delete=models.CASCADE)
    status = models.CharField(max_length=20, default='new')
    review_count = models.PositiveIntegerField(default=0)
    wrong_count = models.PositiveIntegerField(default=0)
    next_review_at = models.DateTimeField(default=timezone.now)
    last_review_at = models.DateTimeField(null=True, blank=True)
    interval_days = models.PositiveIntegerField(default=0)
    class Meta:
        constraints = [models.UniqueConstraint(fields=['user', 'word'], name='unique_user_word')]

