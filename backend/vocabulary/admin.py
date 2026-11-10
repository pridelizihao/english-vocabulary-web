from django.contrib import admin
from .models import Dictionary, Word, UserDictionary, UserWordProgress
admin.site.register([Dictionary, Word, UserDictionary, UserWordProgress])

