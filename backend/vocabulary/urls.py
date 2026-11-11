from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DictionaryViewSet,
    answer_word,
    csrf,
    dictionary_words,
    enroll_dictionary,
    example_audio,
    import_dictionary,
    import_personal_dictionary,
    early_review,
    me,
    register,
    sign_in,
    sign_out,
    profile_summary,
    statistics,
    today_review,
    today_study,
    undo_answer,
    word_detail,
    wrong_review,
)

router = DefaultRouter()
router.register('dictionaries', DictionaryViewSet, basename='dictionary')

urlpatterns = [
    # Explicit routes must come before the router so that /dictionaries/import
    # is not mistaken for a detail route.
    path('auth/csrf', csrf),
    path('auth/register', register),
    path('auth/login', sign_in),
    path('auth/logout', sign_out),
    path('auth/me', me),
    path('dictionaries/import', import_personal_dictionary),
    path('dictionaries/<int:dictionary_id>/enroll', enroll_dictionary),
    path('dictionaries/<int:dictionary_id>/words', dictionary_words),
    path('words/<int:word_id>', word_detail),
    path('words/<int:word_id>/example-audio', example_audio),
    path('answers/<int:log_id>/undo', undo_answer),
    path('admin/dictionaries/import', import_dictionary),
    path('study/today', today_study),
    path('review/today', today_review),
    path('review/early', early_review),
    path('review/wrong', wrong_review),
    path('profile/summary', profile_summary),
    path('study/<int:word_id>/answer', answer_word),
    path('statistics', statistics),
    path('', include(router.urls)),
]
