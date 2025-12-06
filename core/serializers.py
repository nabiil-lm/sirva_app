# core/serializers.py
from rest_framework import serializers
from .models import (
    Dossier, User, DossierStatus, Role, 
    IaCheck, IaCrossCheck, IaStatus,
    RiskRegister, RiskItem, RiskStatus, RiskItemStatus,
    ArchitectureDoc, AuditLog, AuditLogEntry, AuditActionType
)

# Sérialiseur pour l'utilisateur (utilisé dans Dossier pour afficher l'AM)
class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'role', 'role_display']
        read_only_fields = ['role']

# Sérialiseur pour le modèle Dossier
class DossierSerializer(serializers.ModelSerializer):
    am = UserSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Dossier
        fields = [
            'id', 'title', 'status', 'status_display', 'am',
            'questionnaire_json', 'questionnaire_model', 'autosave_version', 
            'is_submitted', 'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'autosave_version', 'is_submitted']

    def validate_title(self, value):
        if len(value) < 5:
            raise serializers.ValidationError("Le titre doit contenir au moins 5 caractères.")
        return value

# Sérialiseur pour IaCheck (IA Phase 1)
class IaCheckSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = IaCheck
        fields = [
            'dossier', 'status', 'status_display', 'findings', 
            'secure_score', 'created_at', 'updated_at'
        ]
        read_only_fields = ['dossier', 'created_at', 'updated_at']

# Sérialiseur pour IaCrossCheck (IA Phase 2)
class IaCrossCheckSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = IaCrossCheck
        fields = [
            'dossier', 'status', 'status_display', 'findings', 
            'secure_score', 'created_at', 'updated_at'
        ]
        read_only_fields = ['dossier', 'created_at', 'updated_at']

# Sérialiseur pour ArchitectureDoc
class ArchitectureDocSerializer(serializers.ModelSerializer):
    class Meta:
        model = ArchitectureDoc
        fields = [
            'id', 'dossier', 'filename', 's3_key', 'rssi_confirmed',
            'mime_type', 'size', 'uploaded_at', 'version'
        ]
        read_only_fields = ['uploaded_at']

# Sérialiseur pour RiskItem
class RiskItemSerializer(serializers.ModelSerializer):
    owner_user = UserSerializer(read_only=True)
    owner_user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='owner_user', write_only=True
    )
    delegated_to = UserSerializer(read_only=True)
    delegated_to_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='delegated_to', write_only=True, required=False, allow_null=True
    )
    likelihood_display = serializers.CharField(source='get_likelihood_display', read_only=True)
    impact_display = serializers.CharField(source='get_impact_display', read_only=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = RiskItem
        fields = [
            'id', 'register', 'owner_user', 'owner_user_id', 
            'delegated_to', 'delegated_to_id',
            'title', 'description', 
            'likelihood', 'likelihood_display',
            'impact', 'impact_display',
            'level', 'level_display',
            'mitigation', 'status', 'status_display',
            'accepted_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['accepted_at', 'created_at', 'updated_at']

# Sérialiseur pour RiskRegister
class RiskRegisterSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    items = RiskItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    accepted_items = serializers.IntegerField(read_only=True)

    class Meta:
        model = RiskRegister
        fields = [
            'dossier', 'created_by', 'status', 'status_display',
            'items', 'total_items', 'accepted_items',
            'submitted_at', 'accepted_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['dossier', 'created_by', 'submitted_at', 'accepted_at', 'created_at', 'updated_at']

# Sérialiseur pour AuditLogEntry
class AuditLogEntrySerializer(serializers.ModelSerializer):
    user = UserSerializer(read_only=True)
    action_type_display = serializers.CharField(source='get_action_type_display', read_only=True)

    class Meta:
        model = AuditLogEntry
        fields = [
            'id', 'user', 'action_type', 'action_type_display',
            'field_modified', 'old_value', 'new_value', 
            'detail', 'timestamp'
        ]
        read_only_fields = ['__all__']

# Sérialiseur pour AuditLog
class AuditLogSerializer(serializers.ModelSerializer):
    entries = AuditLogEntrySerializer(many=True, read_only=True)
    entry_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = AuditLog
        fields = ['dossier', 'created_at', 'entries', 'entry_count']
        read_only_fields = ['dossier', 'created_at']