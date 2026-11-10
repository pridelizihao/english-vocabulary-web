from rest_framework import serializers

from .models import Dictionary, UserWordProgress, Word


class WordSerializer(serializers.ModelSerializer):
    preview = serializers.SerializerMethodField()

    def get_preview(self, obj):
        preview_map = self.context.get('preview_map') or {}
        return preview_map.get(obj.id, {})

    class Meta:
        model = Word
        fields = [
            'id', 'dictionary', 'spelling', 'phonetic', 'pronunciation_url',
            'part_of_speech', 'meaning', 'example', 'example_translation', 'audio_url', 'preview',
        ]


class WordListSerializer(serializers.ModelSerializer):
    """Compact row for the dictionary browser (progress is flattened)."""

    status = serializers.SerializerMethodField()
    interval_days = serializers.SerializerMethodField()
    next_review_at = serializers.SerializerMethodField()
    wrong_count = serializers.SerializerMethodField()
    streak = serializers.SerializerMethodField()

    def _progress(self, obj):
        return (self.context.get('progress_map') or {}).get(obj.id)

    def get_status(self, obj):
        progress = self._progress(obj)
        return progress.status if progress else 'new'

    def get_interval_days(self, obj):
        progress = self._progress(obj)
        return progress.interval_days if progress else 0

    def get_next_review_at(self, obj):
        progress = self._progress(obj)
        return progress.next_review_at if progress else None

    def get_wrong_count(self, obj):
        progress = self._progress(obj)
        return progress.wrong_count if progress else 0

    def get_streak(self, obj):
        progress = self._progress(obj)
        return progress.streak if progress else 0

    class Meta:
        model = Word
        fields = [
            'id', 'spelling', 'phonetic', 'part_of_speech', 'meaning',
            'status', 'interval_days', 'next_review_at', 'wrong_count', 'streak',
        ]



class DictionarySerializer(serializers.ModelSerializer):
    word_count = serializers.SerializerMethodField()
    learned_words = serializers.SerializerMethodField()
    due_reviews = serializers.SerializerMethodField()
    is_personal = serializers.SerializerMethodField()
    is_owned = serializers.SerializerMethodField()

    def get_word_count(self, obj):
        total = getattr(obj, 'word_total', None)
        return total if total is not None else obj.words.count()

    def get_learned_words(self, obj):
        return getattr(obj, 'learned_total', 0) or 0

    def get_due_reviews(self, obj):
        return getattr(obj, 'due_total', 0) or 0

    def get_is_personal(self, obj):
        return obj.owner_id is not None

    def get_is_owned(self, obj):
        request = self.context.get('request')
        return bool(request and request.user.is_authenticated and obj.owner_id == request.user.id)

    class Meta:
        model = Dictionary
        fields = [
            'id', 'name', 'description', 'level', 'version', 'status', 'created_at',
            'word_count', 'learned_words', 'due_reviews', 'is_personal', 'is_owned',
        ]
        read_only_fields = fields


class ProgressSerializer(serializers.ModelSerializer):
    word = WordSerializer(read_only=True)

    class Meta:
        model = UserWordProgress
        fields = [
            'id', 'word', 'status', 'review_count', 'wrong_count', 'streak', 'ease',
            'next_review_at', 'last_review_at', 'first_learned_at', 'interval_days',
        ]
