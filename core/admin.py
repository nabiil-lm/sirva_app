from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Dossier, ArchitectureDoc, IaCheck, IaCrossCheck, RiskRegister, RiskItem

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ('email', 'first_name', 'last_name', 'role', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_active')
    ordering = ('email',)
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal info', {'fields': ('first_name', 'last_name', 'role')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser')}),
    )
    add_fieldsets = (
        (None, {'classes': ('wide',), 'fields': ('email', 'password1', 'password2', 'role')}),
    )

@admin.register(Dossier)
class DossierAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'am', 'created_at', 'updated_at')
    list_filter = ('status', 'am')
    search_fields = ('title',)

@admin.register(IaCheck)
class IaCheckAdmin(admin.ModelAdmin):
    list_display = ('dossier', 'status', 'secure_score', 'created_at')
    list_filter = ('status',)

@admin.register(IaCrossCheck)
class IaCrossCheckAdmin(admin.ModelAdmin):
    list_display = ('dossier', 'status', 'secure_score', 'created_at')
    list_filter = ('status',)

@admin.register(ArchitectureDoc)
class ArchitectureDocAdmin(admin.ModelAdmin):
    list_display = ('filename', 'dossier', 'rssi_confirmed', 'uploaded_at')
    list_filter = ('rssi_confirmed',)
    def entry_count(self, obj):
        return obj.entries.count()
    entry_count.short_description = "Nombre d'entrées"
