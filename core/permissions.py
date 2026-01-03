# core/permissions.py
from rest_framework import permissions
from .models import Role, RiskItemStatus, RiskItem

# ============================================================================
# 1. EXISTING - IsApplicationManager (Enhanced)
# ============================================================================

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
        
        # 1. Lecture (GET) : AM, SO, Admin peuvent voir.
        if request.method in permissions.SAFE_METHODS:
            return True

        # 2. Écriture/Modification (PUT, PATCH, DELETE) : Seulement l'AM propriétaire ou Admin.
        is_owner = obj.am == user
        is_admin_or_superuser = user.role == Role.ADMIN or user.is_superuser
        
        return is_owner or is_admin_or_superuser


# ============================================================================
# 2. NEW - IsOwnerOrReadOnly
# ============================================================================

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Permission that allows owner to edit, everyone else can only read.
    For objects with an 'owner' or 'owner_user' field.
    """
    
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request
        if request.method in permissions.SAFE_METHODS:
            return True
        
        # Write permissions are only allowed to the owner
        # Handle different owner field names
        owner = getattr(obj, 'owner_user', None) or getattr(obj, 'am', None)
        return owner == request.user


# ============================================================================
# 3. NEW - IsSecurityOfficer
# ============================================================================

class IsSecurityOfficer(permissions.BasePermission):
    """
    Permission that only allows Security Officers and Admins.
    Used for actions like confirming documents, accepting risks, validating dossiers.
    """
    
    def has_permission(self, request, view):
        user = request.user
        return user.is_authenticated and user.role in [Role.SO, Role.ADMIN]
    
    def has_object_permission(self, request, view, obj):
        # If user passes has_permission, they're already SO or Admin
        return request.user.role in [Role.SO, Role.ADMIN]


# ============================================================================
# 4. NEW - CanAcceptRisk
# ============================================================================

class CanAcceptRisk(permissions.BasePermission):
    """
    Permission for risk acceptance.
    Allow: Risk owner, delegated user, SO, or Admin
    """
    
    def has_permission(self, request, view):
        # User must be authenticated
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        # obj is a RiskItem
        user = request.user
        
        # Check if user can accept this risk
        can_accept = (
            obj.owner_user == user or
            obj.delegated_to == user or
            user.role in [Role.SO, Role.ADMIN]
        )
        
        return can_accept


# ============================================================================
# 5. NEW - CanModifyDossier
# ============================================================================

class CanModifyDossier(permissions.BasePermission):
    """
    Permission to modify a dossier.
    Only AM owner can modify, and only in EN_EDITION status.
    Admin can always modify.
    SO can ONLY READ dossiers they are responsible for (no write access whatsoever).
    Delegation recipients (AM) can READ dossiers that contain risks delegated to them.
    """
    
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        from .models import DossierStatus
        
        user = request.user
        
        # SO can ONLY READ dossiers ils sont responsables
        if user.role == Role.SO:
            if request.method in permissions.SAFE_METHODS:
                # SO can only VIEW if they are responsible for this dossier
                return obj.responsible_so == user
            else:
                # SO CANNOT modify ANY dossier or perform ANY write operations
                return False
        
        # Admin can do everything
        if user.role == Role.ADMIN or user.is_superuser:
            return True
        
        # For non-SO, non-admin users (AM):
        # Read permissions
        if request.method in permissions.SAFE_METHODS:
            # Owner (AM) can always read
            if obj.am == user:
                return True
            # Delegation recipient can read if they have delegated items
            is_delegation_recipient = RiskItem.objects.filter(
                register__dossier=obj,
                delegated_to=user
            ).exists()
            return is_delegation_recipient
        
        # Write permissions - only owner in EN_EDITION
        is_owner = obj.am == user
        
        if not is_owner:
            return False
        
        # Check status - can only modify in EN_EDITION
        if obj.status != DossierStatus.EN_EDITION:
            return False
        
        return True


# ============================================================================
# 6. NEW - IsDocumentOwnerOrSO
# ============================================================================

class IsDocumentOwnerOrSO(permissions.BasePermission):
    """
    Permission for document operations.
    AM can upload/delete own dossier docs, SO can confirm all.
    """
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # SO/Admin can do anything
        if user.role in [Role.SO, Role.ADMIN]:
            return True
        
        # AM can only modify their own dossier's documents
        if user.role == Role.AM and obj.dossier.am == user:
            return True
        
        # Read is allowed for owner
        if request.method in permissions.SAFE_METHODS:
            return obj.dossier.am == user
        
        return False


# ============================================================================
# 7. NEW - IsRiskItemOwnerOrDelegate
# ============================================================================

class IsRiskItemOwnerOrDelegate(permissions.BasePermission):
    """
    Permission for risk item operations.
    Owner and delegated user can modify, SO/Admin can always access.
    """
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # SO/Admin have full access
        if user.role in [Role.SO, Role.ADMIN]:
            return True
        
        # Read is allowed
        if request.method in permissions.SAFE_METHODS:
            return obj.owner_user == user or obj.delegated_to == user
        
        # Write - only owner can modify
        return obj.owner_user == user


# ============================================================================
# 8. NEW - CanManageRiskRegister
# ============================================================================

class CanManageRiskRegister(permissions.BasePermission):
    """
    Permission for risk register operations.
    - SO responsible for dossier can CREATE and UPDATE (write)
    - AM (dossier owner) can READ and UPDATE risk items
    - Delegation recipients can ONLY READ risk register (read-only to dossier)
    - Admin can do everything
    """
    
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # Admin/Superuser can do everything
        if user.is_superuser or user.role == Role.ADMIN:
            return True
        
        # SO: Can READ and UPDATE (for their dossiers)
        if user.role == Role.SO:
            return obj.dossier.responsible_so == user
        
        # AM: Check if owner or delegation recipient
        if user.role == Role.AM:
            is_owner = obj.dossier.am == user
            is_delegation_recipient = RiskItem.objects.filter(
                register=obj,
                delegated_to=user
            ).exists()
            
            # Owner can do anything, recipients can only READ
            if is_owner:
                return True
            elif is_delegation_recipient:
                # Delegation recipients: READ-ONLY on the register itself
                return request.method in permissions.SAFE_METHODS
        
        return False


class CanManageRiskItem(permissions.BasePermission):
    """
    Permission for risk item operations.
    - Owner (AM) and delegated user can perform actions
    - SO/Admin have full access
    - Delegation recipients can ONLY accept/refuse their delegated item
    """
    
    def has_permission(self, request, view):
        return request.user.is_authenticated
    
    def has_object_permission(self, request, view, obj):
        user = request.user
        
        # SO/Admin have full access
        if user.role in [Role.SO, Role.ADMIN]:
            return True
        
        # AM (dossier owner) has full access to items in their register
        if user.role == Role.AM:
            if obj.register.dossier.am == user:
                return True
            
            # Delegation recipient: can ONLY see and act on items delegated to them
            if obj.delegated_to == user:
                # Allow safe methods (GET)
                if request.method in permissions.SAFE_METHODS:
                    return True
                # Allow POST to accept/refuse endpoints only
                if hasattr(view, 'action') and view.action in ['accept', 'refuse']:
                    return True
            
            return False
        
        return False