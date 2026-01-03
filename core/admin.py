from .models import QuestionnaireTemplate, Question, QuestionnaireAnswer
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, Dossier, ArchitectureDoc, IaCheck, IaCrossCheck, RiskRegister, RiskItem

METADONNEES = 'Métadonnées'

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
    list_display = ['title', 'status', 'am', 'responsible_so', 'questionnaire_template', 'is_submitted', 'created_at']
    list_filter = ['status', 'am', 'responsible_so', 'questionnaire_template', 'created_at']
    search_fields = ['title', 'am__email', 'responsible_so__email']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Informations', {
            'fields': ('title', 'am', 'status')
        }),
        ('Security Officer', {
            'fields': ('responsible_so',)
        }),
        ('Questionnaire', {
            'fields': ('questionnaire_template', 'is_submitted')
        }),
        (METADONNEES, {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        if obj:  # Editing an existing object
            return self.readonly_fields + ['am']  # Can't change AM after creation
        return self.readonly_fields

@admin.register(IaCheck)
class IaCheckAdmin(admin.ModelAdmin):
    list_display = ('dossier', 'status', 'secure_score', 'created_at')
    list_filter = ('status',)

@admin.register(IaCrossCheck)
class IaCrossCheckAdmin(admin.ModelAdmin):
    list_display = ['dossier', 'status', 'secure_score', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['dossier__name', 'findings']
    readonly_fields = ['created_at', 'updated_at', 'findings']
    
    fieldsets = (
        ('Dossier', {
            'fields': ('dossier',)
        }),
        ('Analysis Results', {
            'fields': ('status', 'secure_score', 'findings')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

@admin.register(ArchitectureDoc)
class ArchitectureDocAdmin(admin.ModelAdmin):
    list_display = ('filename', 'dossier', 'rssi_confirmed', 'site_filepath', 'uploaded_at')
    list_filter = ('rssi_confirmed',)
    readonly_fields = ('local_filepath', 'site_filepath', 'uploaded_at')
    fieldsets = (
        ('Document Info', {
            'fields': ('dossier', 'filename', 'mime_type', 'size')
        }),
        ('File Paths', {
            'fields': ('local_filepath', 'site_filepath'),
            'classes': ('collapse',)
        }),
        ('RSSI Confirmation', {
            'fields': ('rssi_confirmed',)
        }),
        ('Metadata', {
            'fields': ('version', 'uploaded_at'),
            'classes': ('collapse',)
        }),
    )

# ============================================================================
# Questionnaire Admin
# ============================================================================
class QuestionInline(admin.TabularInline):
    """Inline admin for questions within a questionnaire"""
    model = Question
    extra = 1
    fields = ['order', 'text', 'question_type', 'is_mandatory', 'choices_json', 'help_text']
    ordering = ['order']


@admin.register(QuestionnaireTemplate)
class QuestionnaireTemplateAdmin(admin.ModelAdmin):
    """Admin for questionnaire templates"""
    list_display = ['name', 'status', 'question_count', 'created_by', 'created_at']
    list_filter = ['status', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['created_at', 'updated_at', 'question_count']
    inlines = [QuestionInline]
    fieldsets = (
        ('Informations', {
            'fields': ('name', 'description', 'status', 'question_count')
        }),
        (METADONNEES, {
            'fields': ('created_by', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(QuestionnaireAnswer)
class QuestionnaireAnswerAdmin(admin.ModelAdmin):
    """Admin for questionnaire answers"""
    list_display = ['dossier', 'question', 'answer_value_preview', 'answered_at']
    list_filter = ['answered_at', 'dossier', 'question__template']
    search_fields = ['dossier__title', 'question__text', 'answer_value']
    readonly_fields = ['answered_at', 'dossier', 'question']
    fieldsets = (
        ('Réponse', {
            'fields': ('dossier', 'question', 'answer_value')
        }),
        ('Métadonnées', {
            'fields': ('answered_at',),
            'classes': ('collapse',)
        }),
    )
    
    def answer_value_preview(self, obj):
        """Display preview of answer value"""
        if obj.answer_value:
            preview = obj.answer_value[:100]
            return f"{preview}..." if len(obj.answer_value) > 100 else preview
        return "-"
    answer_value_preview.short_description = 'Réponse'
