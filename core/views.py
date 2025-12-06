from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, permissions, status
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q

from .models import (
    Dossier, Role, DossierStatus, ArchitectureDoc, RiskItem, 
    RiskItemStatus, User, AuditLogEntry, AuditActionType,
    RiskRegister, IaCheck, IaCrossCheck, AuditLog, RiskStatus
)
from .serializers import (
    DossierSerializer, ArchitectureDocSerializer, RiskItemSerializer,
    RiskRegisterSerializer, IaCheckSerializer, IaCrossCheckSerializer,
    AuditLogSerializer, AuditLogEntrySerializer
)
from .permissions import (
    IsApplicationManager, IsOwnerOrReadOnly, IsSecurityOfficer,
    CanAcceptRisk, CanModifyDossier, IsDocumentOwnerOrSO,
    IsRiskItemOwnerOrDelegate
)

# ============================================================================
# Helper Mixin for Filtering by Dossier
# ============================================================================

class DossierFilterMixin:
    """
    Mixin to filter nested resources by dossier_id from URL.
    Usage: When accessing /api/dossiers/{dossier_id}/documents/
    """
    
    def filter_queryset_by_dossier(self, queryset):
        """Filter queryset by dossier_id if provided in URL"""
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            return queryset.filter(dossier_id=dossier_id)
        return queryset
    
    def get_queryset(self):
        """Override in subclass to use this mixin"""
        queryset = super().get_queryset()
        return self.filter_queryset_by_dossier(queryset)

# ============================================================================
# 1. ENHANCED DossierViewSet
# ============================================================================

class DossierViewSet(viewsets.ModelViewSet):
    """
    ViewSet pour les opérations CRUD sur les Dossiers.
    Includes custom actions: full() and submit()
    """
    queryset = Dossier.objects.all().order_by('-updated_at')
    serializer_class = DossierSerializer
    permission_classes = [permissions.IsAuthenticated, CanModifyDossier] 
    
    def get_queryset(self):
        """
        Filtrer les dossiers pour n'afficher que ceux de l'utilisateur connecté (AM).
        """
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return Dossier.objects.all().order_by('-updated_at')
        return Dossier.objects.filter(am=user).order_by('-updated_at')

    def perform_create(self, serializer):
        """
        Lors de la création, l'AM du dossier est automatiquement l'utilisateur connecté.
        """
        serializer.save(am=self.request.user, status=DossierStatus.EN_EDITION)

    @action(detail=True, methods=['get'])
    def full(self, request, pk=None):
        """
        Get dossier with all related data (documents, risks, IA results, audit log)
        Used for dashboard single-page view
        """
        dossier = self.get_object()
        serializer = DossierSerializer(dossier)
        
        # Build comprehensive response
        data = serializer.data
        data['architecture_docs'] = ArchitectureDocSerializer(
            dossier.architecture_docs.all(), many=True
        ).data
        
        # Add IA results if they exist
        try:
            data['ia1_result'] = {
                'status': dossier.ia1_result.status,
                'secure_score': float(dossier.ia1_result.secure_score or 0),
                'findings': dossier.ia1_result.findings,
                'created_at': dossier.ia1_result.created_at.isoformat()
            }
        except AttributeError:
            data['ia1_result'] = None
        
        try:
            data['ia2_result'] = {
                'status': dossier.ia2_result.status,
                'secure_score': float(dossier.ia2_result.secure_score or 0),
                'findings': dossier.ia2_result.findings,
                'created_at': dossier.ia2_result.created_at.isoformat()
            }
        except AttributeError:
            data['ia2_result'] = None
        
        # Add risk register with items
        try:
            risk_register = dossier.risk_register
            data['risk_register'] = {
                'id': risk_register.id,
                'status': risk_register.status,
                'total_items': risk_register.total_items,
                'accepted_items': risk_register.accepted_items,
                'items': RiskItemSerializer(risk_register.items.all(), many=True).data,
                'created_at': risk_register.created_at.isoformat()
            }
        except AttributeError:
            data['risk_register'] = None
        
        # Add audit log
        try:
            audit_log = dossier.audit_log
            data['audit_log'] = {
                'entry_count': audit_log.entry_count,
                'last_activity': audit_log.last_activity.timestamp.isoformat() if audit_log.last_activity else None,
                'entries': [
                    {
                        'user': entry.user.email if entry.user else None,
                        'action_type': entry.action_type,
                        'field_modified': entry.field_modified,
                        'old_value': entry.old_value,
                        'new_value': entry.new_value,
                        'timestamp': entry.timestamp.isoformat()
                    }
                    for entry in audit_log.entries.all()[:50]  # Last 50 entries
                ]
            }
        except AttributeError:
            data['audit_log'] = None
        
        return Response(data)

    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """
        Submit questionnaire for IA1 analysis
        Only owner can submit, and only in EN_EDITION status
        """
        dossier = self.get_object()
        
        # Validation: check if status allows submission
        if dossier.status != DossierStatus.EN_EDITION:
            return Response(
                {'error': f'Cannot submit dossier in {dossier.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if questionnaire has data
        if not dossier.questionnaire_json:
            return Response(
                {'error': 'Questionnaire cannot be empty'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update dossier status
        dossier.status = DossierStatus.QUESTIONNAIRE_SOUMIS
        dossier.is_submitted = True
        dossier.save()
        
        # Log the action to audit
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.QUESTIONNAIRE_SUBMITTED,
            detail={'version': dossier.autosave_version}
        )
        
        return Response(
            {'status': 'Questionnaire submitted successfully', 'dossier_status': dossier.status},
            status=status.HTTP_200_OK
        )


# ============================================================================
# 2. NEW ArchitectureDocViewSet
# ============================================================================

class ArchitectureDocViewSet(DossierFilterMixin, viewsets.ModelViewSet):
    """
    ViewSet for architecture document uploads and management
    Includes custom action: confirm()
    Supports nested route: /api/dossiers/{dossier_id}/documents/
    """
    queryset = ArchitectureDoc.objects.all().order_by('-uploaded_at')
    serializer_class = ArchitectureDocSerializer
    permission_classes = [permissions.IsAuthenticated, IsDocumentOwnerOrSO]
    
    def get_queryset(self):
        """Filter documents based on user role and optional dossier_id"""
        user = self.request.user
        
        # Start with base queryset
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = ArchitectureDoc.objects.all()
        elif user.role == Role.SO:
            queryset = ArchitectureDoc.objects.all()
        else:
            queryset = ArchitectureDoc.objects.filter(dossier__am=user)
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-uploaded_at')
    
    def perform_create(self, serializer):
        """Auto-set dossier from query params and log action"""
        dossier_id = self.request.data.get('dossier_id')
        dossier = Dossier.objects.get(id=dossier_id)
        
        doc = serializer.save(dossier=dossier)
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=self.request.user,
            action_type=AuditActionType.DOCUMENT_UPLOADED,
            detail={'filename': doc.filename, 's3_key': doc.s3_key}
        )
    
    @action(detail=True, methods=['post'])
    def confirm(self, request, pk=None):
        """
        RSSI/SO confirms the architecture document
        """
        doc = self.get_object()
        
        # Only SO or Admin can confirm
        if request.user.role not in [Role.SO, Role.ADMIN]:
            return Response(
                {'error': 'Only Security Officers can confirm documents'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        doc.rssi_confirmed = True
        doc.save()
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=doc.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.DOCUMENT_CONFIRMED,
            detail={'filename': doc.filename}
        )
        
        return Response(
            {'status': 'Document confirmed', 'filename': doc.filename},
            status=status.HTTP_200_OK
        )


# ============================================================================
# 3. NEW RiskItemViewSet
# ============================================================================

class RiskItemViewSet(DossierFilterMixin, viewsets.ModelViewSet):
    """
    ViewSet for individual risk items
    Includes custom actions: delegate() and accept()
    Supports nested route: /api/dossiers/{dossier_id}/risk-items/
    """
    queryset = RiskItem.objects.all().order_by('-created_at')
    serializer_class = RiskItemSerializer
    permission_classes = [permissions.IsAuthenticated, IsRiskItemOwnerOrDelegate]
    
    def get_queryset(self):
        """Filter risk items based on user role and optional dossier_id"""
        user = self.request.user
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = RiskItem.objects.all()
        else:
            queryset = RiskItem.objects.filter(
                Q(register__dossier__am=user) | Q(delegated_to=user) | Q(owner_user=user)
            )
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(register__dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """Auto-set owner and log action"""
        risk = serializer.save(owner_user=self.request.user)
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=self.request.user,
            action_type=AuditActionType.RISK_ITEM_ADDED,
            detail={'title': risk.title, 'level': risk.level}
        )
    
    @action(detail=True, methods=['post'])
    def delegate(self, request, pk=None):
        """
        Delegate risk to another user
        """
        risk = self.get_object()
        
        # Only owner can delegate
        if risk.owner_user != request.user:
            return Response(
                {'error': 'Only risk owner can delegate'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        delegated_to_id = request.data.get('delegated_to_id')
        if not delegated_to_id:
            return Response(
                {'error': 'delegated_to_id is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            delegated_to = User.objects.get(id=delegated_to_id)
        except User.DoesNotExist:
            return Response(
                {'error': 'User not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        risk.delegated_to = delegated_to
        risk.status = RiskItemStatus.DELEGATED
        risk.save()
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_ITEM_DELEGATED,
            detail={'risk_title': risk.title, 'delegated_to': delegated_to.email}
        )
        
        return Response(
            {'status': 'Risk delegated', 'delegated_to': delegated_to.email},
            status=status.HTTP_200_OK
        )
    
    @action(detail=True, methods=['post'])
    def accept(self, request, pk=None):
        """
        Accept a risk item
        Can be called by owner, delegated user, or SO/Admin
        """
        risk = self.get_object()
        
        # Check if user has authority to accept
        can_accept = (
            risk.owner_user == request.user or
            risk.delegated_to == request.user or
            request.user.role in [Role.SO, Role.ADMIN]
        )
        
        if not can_accept:
            return Response(
                {'error': 'You do not have permission to accept this risk'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        risk.status = RiskItemStatus.ACCEPTED
        risk.accepted_at = timezone.now()
        risk.save()
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_ITEM_ACCEPTED,
            detail={'risk_title': risk.title}
        )
        
        return Response(
            {'status': 'Risk accepted', 'accepted_at': risk.accepted_at.isoformat()},
            status=status.HTTP_200_OK
        )


# ============================================================================
# 4. NEW RiskRegisterViewSet
# ============================================================================

class RiskRegisterViewSet(DossierFilterMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for risk registers (read operations + submit action)
    Supports nested route: /api/dossiers/{dossier_id}/risk-register/
    """
    queryset = RiskRegister.objects.all().order_by('-created_at')
    serializer_class = RiskRegisterSerializer
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]
    
    def get_queryset(self):
        """Filter risk registers based on user role and optional dossier_id"""
        user = self.request.user
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = RiskRegister.objects.all()
        elif user.role == Role.SO:
            queryset = RiskRegister.objects.all()
        else:
            queryset = RiskRegister.objects.filter(dossier__am=user)
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None):
        """
        Submit risk register for review
        Only owner (AM) can submit, status must be DRAFT
        """
        register = self.get_object()
        
        # Validation
        if register.status != RiskStatus.DRAFT:
            return Response(
                {'error': f'Can only submit registers in DRAFT status, current: {register.status}'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if register.dossier.am != request.user:
            return Response(
                {'error': 'Only dossier owner can submit risk register'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if register.items.count() == 0:
            return Response(
                {'error': 'Cannot submit register with no risk items'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update status
        register.status = RiskStatus.SUBMITTED
        register.submitted_at = timezone.now()
        register.save()
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=register.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_REGISTER_SUBMITTED,
            detail={'total_items': register.items.count()}
        )
        
        return Response(
            {'status': 'Risk register submitted', 'submitted_at': register.submitted_at.isoformat()},
            status=status.HTTP_200_OK
        )


# ============================================================================
# 5. NEW IaCheckViewSet (Read-Only)
# ============================================================================

class IaCheckViewSet(DossierFilterMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for IA Phase 1 (questionnaire coherence) results
    Read-only access for all authenticated users
    Supports nested route: /api/dossiers/{dossier_id}/ia1/
    """
    queryset = IaCheck.objects.all().order_by('-created_at')
    serializer_class = IaCheckSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter IA checks based on dossier access and optional dossier_id"""
        user = self.request.user
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = IaCheck.objects.all()
        elif user.role == Role.SO:
            queryset = IaCheck.objects.all()
        else:
            queryset = IaCheck.objects.filter(dossier__am=user)
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')


# ============================================================================
# 6. NEW IaCrossCheckViewSet (Read-Only)
# ============================================================================

class IaCrossCheckViewSet(DossierFilterMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for IA Phase 2 (questionnaire vs architecture) cross-check results
    Read-only access for all authenticated users
    Supports nested route: /api/dossiers/{dossier_id}/ia2/
    """
    queryset = IaCrossCheck.objects.all().order_by('-created_at')
    serializer_class = IaCrossCheckSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter IA cross-checks based on dossier access and optional dossier_id"""
        user = self.request.user
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = IaCrossCheck.objects.all()
        elif user.role == Role.SO:
            queryset = IaCrossCheck.objects.all()
        else:
            queryset = IaCrossCheck.objects.filter(dossier__am=user)
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')


# ============================================================================
# 7. NEW AuditLogViewSet (Read-Only)
# ============================================================================

class AuditLogViewSet(DossierFilterMixin, viewsets.ReadOnlyModelViewSet):
    """
    ViewSet for audit logs
    Read-only access - shows action history for each dossier
    Supports nested route: /api/dossiers/{dossier_id}/audit-log/
    """
    queryset = AuditLog.objects.all().order_by('-created_at')
    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        """Filter audit logs based on dossier access and optional dossier_id"""
        user = self.request.user
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = AuditLog.objects.all()
        elif user.role == Role.SO:
            queryset = AuditLog.objects.all()
        else:
            queryset = AuditLog.objects.filter(dossier__am=user)
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')
    
    @action(detail=True, methods=['get'])
    def entries(self, request, pk=None):
        """
        Get paginated list of audit log entries for a specific audit log
        """
        audit_log = self.get_object()
        page = request.query_params.get('page', 1)
        page_size = request.query_params.get('page_size', 50)
        
        start = (int(page) - 1) * int(page_size)
        end = start + int(page_size)
        
        entries = audit_log.entries.all()[start:end]
        
        data = {
            'audit_log_id': audit_log.dossier.id,
            'total_entries': audit_log.entries.count(),
            'page': page,
            'page_size': page_size,
            'entries': AuditLogEntrySerializer(entries, many=True).data
        }
        
        return Response(data)


# ============================================================================
# 8. HOME DASHBOARD
# ============================================================================

def home_dashboard(request):
    """Render home dashboard (placeholder for frontend)"""
    return render(request, 'core/dashboard.html')
