from django.contrib import admin
from django.db.models import Count

from .models import Dictionary, UserDictionary, UserWordProgress, Word

admin.site.site_header = '英语单词背诵 · 后台'
admin.site.site_title = '英语单词背诵'
admin.site.index_title = '词典与学习数据'


@admin.register(Dictionary)
class DictionaryAdmin(admin.ModelAdmin):
    list_display = ('name', 'level', 'status', 'owner', 'word_total', 'created_at')
    list_filter = ('status', 'level')
    search_fields = ('name', 'description', 'level', 'owner__username')
    list_select_related = ('owner',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    fields = ('name', 'description', 'level', 'version', 'status', 'owner', 'created_at')

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(word_total=Count('words'))

    @admin.display(description='单词数', ordering='word_total')
    def word_total(self, obj):
        return obj.word_total


@admin.register(Word)
class WordAdmin(admin.ModelAdmin):
    list_display = ('spelling', 'dictionary', 'phonetic', 'part_of_speech', 'meaning_preview')
    list_filter = ('dictionary', 'part_of_speech')
    search_fields = ('spelling', 'meaning', 'phonetic')
    list_select_related = ('dictionary',)
    raw_id_fields = ('dictionary',)
    ordering = ('spelling',)
    list_per_page = 100

    @admin.display(description='释义')
    def meaning_preview(self, obj):
        return obj.meaning[:60]


@admin.register(UserWordProgress)
class UserWordProgressAdmin(admin.ModelAdmin):
    list_display = ('user', 'word', 'status', 'streak', 'interval_days', 'next_review_at', 'last_review_at')
    list_filter = ('status',)
    search_fields = ('user__username', 'word__spelling')
    list_select_related = ('user', 'word')
    raw_id_fields = ('user', 'word')
    date_hierarchy = 'next_review_at'
    list_per_page = 100


@admin.register(UserDictionary)
class UserDictionaryAdmin(admin.ModelAdmin):
    list_display = ('user', 'dictionary', 'started_at')
    search_fields = ('user__username', 'dictionary__name')
    list_select_related = ('user', 'dictionary')
    raw_id_fields = ('user', 'dictionary')
