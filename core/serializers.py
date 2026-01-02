# core/serializers.py
from rest_framework import serializers
from .models import Dossier, User, DossierStatus, Role

# Sérialiseur pour l'utilisateur (utilisé dans Dossier pour afficher l'AM)
class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'email', 'first_name', 'last_name', 'role', 'role_display']
        read_only_fields = ['role']

# Sérialiseur pour le modèle Dossier
class DossierSerializer(serializers.ModelSerializer):
    # L'AM est affiché en utilisant le sérialiseur User
    am = UserSerializer(read_only=True)
    
    # Champ pour gérer l'AM lors de la création
#    am_id = serializers.PrimaryKeyRelatedField(
#        queryset=User.objects.all(), source='am', write_only=True
#    )
    
    # Afficher le libellé du statut au lieu de la valeur brute
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = Dossier
        # Note : am_id est utilisé pour l'écriture, am pour la lecture.
        fields = [
            #'id', 'title', 'status', 'status_display', 'am', 'am_id',
            'id', 'title', 'status', 'status_display', 'am', 'am_id',  
            'questionnaire_json', 'questionnaire_model', 'autosave_version', 
            'is_submitted', 'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'autosave_version', 'is_submitted']

    def validate_title(self, value):
        # Exemple de validation pour le titre
        if len(value) < 5:
            raise serializers.ValidationError("Le titre doit contenir au moins 5 caractères.")
        return value