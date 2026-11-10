from rest_framework import serializers
from .models import Dictionary, Word, UserWordProgress

class WordSerializer(serializers.ModelSerializer):
    cloze = serializers.SerializerMethodField()

    def get_cloze(self, obj):
        word = obj.spelling
        if len(word) <= 3:
            return '_' * len(word)
        reveal = max(1, len(word) // 3)
        return word[:reveal] + '_' * (len(word) - reveal)

    class Meta:
        model = Word
        fields = ['id', 'dictionary', 'spelling', 'phonetic', 'pronunciation_url', 'part_of_speech', 'meaning', 'example', 'audio_url', 'cloze']

class DictionarySerializer(serializers.ModelSerializer):
    word_count = serializers.SerializerMethodField()
    def get_word_count(self, obj):
        return obj.words.count()
    class Meta:
        model = Dictionary
        fields = ['id', 'name', 'description', 'level', 'version', 'status', 'word_count']

class UserSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()

class ProgressSerializer(serializers.ModelSerializer):
    word = WordSerializer(read_only=True)
    class Meta:
        model = UserWordProgress
        fields = ['id', 'word', 'status', 'review_count', 'wrong_count', 'next_review_at', 'last_review_at', 'interval_days']

