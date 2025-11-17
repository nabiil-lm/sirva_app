# core/permissions.py
from rest_framework import permissions
from .models import Role

class IsApplicationManager(permissions.BasePermission):
    """
    Autorisation personnalisée pour permettre l'accès :
    1. Si l'utilisateur est un Admin ou un Superuser.
    2. Si l'utilisateur est l'AM propriétaire du dossier.
    """
    def has_permission(self, request, view):
        # Les utilisateurs doivent être authentifiés pour toute opération
        return request.user.is_authenticated

    def has_object_permission(self, request, view, obj):
        # Les permissions de niveau objet s'appliquent après has_permission
        user = request.user
        
        # 1. Lecture (GET) : AM, SO, Admin peuvent voir. L'accès sera affiné dans get_queryset.
        if request.method in permissions.SAFE_METHODS:
            return True # Autoriser la lecture si l'utilisateur est AM, SO ou Admin

        # 2. Écriture/Modification (PUT, PATCH, DELETE) : Seulement l'AM propriétaire ou Admin.
        # L'AM ne doit pouvoir modifier/supprimer que ses propres dossiers
        is_owner = obj.am == user
        is_admin_or_superuser = user.role == Role.ADMIN or user.is_superuser
        
        return is_owner or is_admin_or_superuser