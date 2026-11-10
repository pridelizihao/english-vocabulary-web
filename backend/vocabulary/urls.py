from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    DictionaryViewSet,
    answer_word,
    csrf,
    enroll_dictionary,
    import_dictionary,
    import_personal_dictionary,
    me,
    register,
    sign_in,
    sign_out,
    statistics,
    today_review,
    today_study,
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
    path('admin/dictionaries/import', import_dictionary),
    path('study/today', today_study),
    path('review/today', today_review),
    path('study/<int:word_id>/answer', answer_word),
    path('statistics', statistics),
    path('', include(router.urls)),
]
