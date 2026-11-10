from django.urls import include, path
from rest_framework.routers import DefaultRouter
from .views import (DictionaryViewSet, answer_word, enroll_dictionary, import_dictionary, import_personal_dictionary,
                    csrf, me, register, sign_in, sign_out, statistics, today_review, today_study)

router = DefaultRouter()
router.register('dictionaries', DictionaryViewSet, basename='dictionary')
urlpatterns = [
    path('', include(router.urls)),
    path('study/today', today_study),
    path('review/today', today_review),
    path('study/<int:word_id>/answer', answer_word),
    path('statistics', statistics),
    path('dictionaries/<int:dictionary_id>/enroll', enroll_dictionary),
    path('admin/dictionaries/import', import_dictionary),
    path('dictionaries/import', import_personal_dictionary),
    path('auth/register', register),
    path('auth/login', sign_in),
    path('auth/logout', sign_out),
    path('auth/me', me),
    path('auth/csrf', csrf),
]

