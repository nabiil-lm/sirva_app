from .models import QuestionnaireTemplate, Question, QuestionnaireAnswer, QuestionType
from .serializers import (
    QuestionnaireTemplateSerializer, QuestionnaireTemplateSimpleSerializer,
    QuestionSerializer, QuestionnaireAnswerSerializer, BulkQuestionnaireAnswerSerializer,
    DossierSubmitSerializer, RiskItemActionSerializer, RiskItemDelegationActionSerializer  # ADD RiskItemActionSerializer
)
from django.shortcuts import render, get_object_or_404
from rest_framework import viewsets, permissions, status, serializers
from rest_framework.decorators import action
from rest_framework.response import Response
from django.utils.translation import gettext_lazy as _
from django.utils import timezone
from django.db.models import Q
from django.http import FileResponse
from django.conf import settings
import os
from pathlib import Path
from rest_framework.exceptions import PermissionDenied

from .models import (
    Dossier, Role, DossierStatus, ArchitectureDoc, RiskItem, 
    RiskItemStatus, User, AuditLogEntry, AuditActionType,
    RiskRegister, IaCheck, IaCrossCheck, AuditLog, RiskStatus,
    QuestionnaireStatus
)
from .serializers import (
    DossierSerializer, ArchitectureDocSerializer, RiskItemSerializer,
    RiskRegisterSerializer, IaCheckSerializer, IaCrossCheckSerializer,
    AuditLogSerializer, AuditLogEntrySerializer
)
from .permissions import (
    IsApplicationManager, IsOwnerOrReadOnly, IsSecurityOfficer,
    CanAcceptRisk, CanModifyDossier, IsDocumentOwnerOrSO,
    IsRiskItemOwnerOrDelegate, CanManageRiskRegister
)

# ============================================================================
# Constants
# ============================================================================

ERROR_ONLY_RESPONSIBLE_SO = 'Only the responsible SO can submit this risk register'
RISK_REGISTER_SUBMITTED_MESSAGE = 'Risk register submitted'

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
    Includes custom actions: full(), submit(), available_templates()
    - AM can see their own dossiers (all statuses)
    - SO can see ONLY dossiers they are responsible for with status QUESTIONNAIRE_SOUMIS or later
    - Admin can see all dossiers
    """
    queryset = Dossier.objects.all().order_by('-updated_at')
    serializer_class = DossierSerializer
    permission_classes = [permissions.IsAuthenticated, CanModifyDossier] 
    
    def get_queryset(self):
        """
        Filter dossiers based on user role:
        - AM: Only their own dossiers (all statuses)
        - SO: Only dossiers they are responsible for AND have QUESTIONNAIRE_SOUMIS or subsequent status
        - Delegation Recipients (AM): Dossiers that contain risk items delegated to them
        - Admin: All dossiers
        """
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return Dossier.objects.all().order_by('-updated_at')
        elif user.role == Role.SO:
            # SO can ONLY see dossiers they are responsible for
            # AND that have been submitted or are in later stages (not EN_EDITION)
            submitted_statuses = [
                DossierStatus.QUESTIONNAIRE_SOUMIS,
                DossierStatus.IA1_INCOHERENT,
                DossierStatus.IA1_COHERENT,
                DossierStatus.ARCHI_UPLOAD_EN_COURS,
                DossierStatus.IA2_INCOHERENT,
                DossierStatus.IA2_COHERENT,
                DossierStatus.RISQUES_EN_COURS,
                DossierStatus.PRET_VALIDATION,
                DossierStatus.VALIDE,
            ]
            return Dossier.objects.filter(
                responsible_so=user,
                status__in=submitted_statuses
            ).order_by('-updated_at')
        else:
            # AM: Their own dossiers OR dossiers with risk items delegated to them
            # Use Q objects to combine filters without .distinct() issues
            return Dossier.objects.filter(
                Q(am=user) | Q(risk_register__items__delegated_to=user)
            ).distinct().order_by('-updated_at')

    def perform_create(self, serializer):
        """
        When creating a dossier, set the AM to the current user.
        SO assignment is handled by the serializer.
        """
        dossier = serializer.save(am=self.request.user, status=DossierStatus.EN_EDITION)
        
        # If questionnaire_template was provided, auto-create answer records
        template_id = self.request.data.get('questionnaire_template_id')
        if template_id:
            from .models import QuestionnaireTemplate
            try:
                template = QuestionnaireTemplate.objects.get(id=template_id)
                dossier.questionnaire_template = template
                dossier.save()
                
                # QuestionnaireAnswer records will be created automatically by signal
                AuditLogEntry.objects.create(
                    audit_log=dossier.audit_log,
                    user=self.request.user,
                    action_type=AuditActionType.QUESTIONNAIRE_SAVED,
                    detail={
                        'template_name': template.name,
                        'question_count': template.questions.count()
                    }
                )
            except QuestionnaireTemplate.DoesNotExist:
                pass
    
    @action(detail=False, methods=['get'])
    def available_templates(self, request):
        """
        Get list of available published questionnaire templates for dropdown selection.
        This endpoint is used to populate the dropdown menu when creating a dossier.
        
        Response format:
        {
            "count": 2,
            "templates": [
                {
                    "id": 1,
                    "name": "Security Assessment 2024",
                    "description": "Standard security questionnaire",
                    "question_count": 10
                },
                ...
            ]
        }
        """
        templates = QuestionnaireTemplate.objects.filter(
            status=QuestionnaireStatus.PUBLISHED
        ).order_by('name')
        
        serializer = QuestionnaireTemplateSimpleSerializer(templates, many=True)
        
        return Response({
            'count': len(serializer.data),
            'templates': serializer.data
        }, status=status.HTTP_200_OK)

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

    @action(detail=True, methods=['post'], serializer_class=DossierSubmitSerializer)
    def submit(self, request, pk=None):
        """
        Submit questionnaire for IA1 analysis.
        
        ⚠️ WARNING: This action will submit your dossier for analysis.
        - All mandatory questions must be answered before submission
        - Once submitted, you will no longer be able to edit answers
        - This action cannot be undone
        
        Are you sure you want to submit this dossier now?
        """
        dossier = self.get_object()
        
        # Validation 1: check if status allows submission
        if dossier.status != DossierStatus.EN_EDITION:
            return Response(
                {'error': f'Cannot submit dossier in {dossier.status} status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validation 2: check if questionnaire template is assigned
        if not dossier.questionnaire_template:
            return Response(
                {'error': 'A questionnaire template must be assigned before submission'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validation 3: Check all mandatory questions are answered
        mandatory_questions = dossier.questionnaire_template.questions.filter(is_mandatory=True)
        
        if not mandatory_questions.exists():
            # No mandatory questions, allow submission
            pass
        else:
            # Check each mandatory question has an answer
            unanswered_mandatory = []
            for question in mandatory_questions:
                answer = dossier.questionnaire_answers.filter(question=question).first()
                
                # Check if answer exists and has a non-empty value
                if not answer or not answer.answer_value or answer.answer_value.strip() == '':
                    unanswered_mandatory.append({
                        'question_id': question.id,
                        'question_text': question.text,
                        'order': question.order
                    })
            
            # If any mandatory questions are unanswered, return error
            if unanswered_mandatory:
                return Response(
                    {
                        'error': f'{len(unanswered_mandatory)} mandatory question(s) must be answered before submission',
                        'unanswered_questions': unanswered_mandatory
                    },
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        # Validation 4: check if at least one answer exists
        answer_count = dossier.questionnaire_answers.count()
        if answer_count == 0:
            return Response(
                {'error': 'At least one question must be answered before submission'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # All validations passed - Update dossier status
        dossier.status = DossierStatus.QUESTIONNAIRE_SOUMIS
        dossier.is_submitted = True
        dossier.save()
        
        # Log the action to audit
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.QUESTIONNAIRE_SUBMITTED,
            detail={
                'submitted_by': request.user.email,
                'answers_count': answer_count,
                'mandatory_questions_count': mandatory_questions.count()
            }
        )
        
        return Response(
            {
                'status': 'Questionnaire submitted successfully',
                'dossier_status': dossier.status,
                'dossier_id': dossier.id,
                'message': f'Dossier submitted with {answer_count} answers ({mandatory_questions.count()} mandatory questions answered)'
            },
            status=status.HTTP_200_OK
        )


# ============================================================================
# 2. NEW ArchitectureDocViewSet
# ============================================================================

class ArchitectureDocViewSet(DossierFilterMixin, viewsets.ModelViewSet):
    """
    ViewSet for architecture document uploads and management
    Includes custom actions: confirm(), download(), download_by_filename()
    Supports file upload with PDF validation
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
        """Auto-set dossier from URL path, extract file info, save to disk, and log action"""
        # Get dossier_id from URL
        dossier_id = self.kwargs.get('dossier_id')
        if not dossier_id:
            raise serializers.ValidationError("dossier_id is required in URL path")
        
        dossier = Dossier.objects.get(id=dossier_id)
        
        # Get the uploaded file
        uploaded_file = serializer.validated_data.get('file')
        
        if uploaded_file:
            # Extract file information
            filename = uploaded_file.name
            mime_type = uploaded_file.content_type
            size = uploaded_file.size
            
            # Create directory structure: dossiers/dossier_id/documents/
            upload_dir = Path(settings.BASE_DIR) / 'uploads' / 'dossiers' / str(dossier_id) / 'documents'
            upload_dir.mkdir(parents=True, exist_ok=True)
            
            # Full file path where we'll save the file
            file_path = upload_dir / filename
            
            # NEW: Save the uploaded file to disk
            with open(file_path, 'wb') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            
            # CHANGED: Store local_filepath (full absolute path)
            local_filepath = str(file_path)
            
            # NEW: Create site_filepath (relative download URL)
            site_filepath = f"/api/dossiers/{dossier_id}/documents/{filename}/"
            
            # Save the document record
            doc = serializer.save(
                dossier=dossier,
                filename=filename,
                local_filepath=local_filepath,
                site_filepath=site_filepath,
                mime_type=mime_type,
                size=size
            )
        else:
            doc = serializer.save(dossier=dossier)
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=self.request.user,
            action_type=AuditActionType.DOCUMENT_UPLOADED,
            detail={
                'filename': doc.filename,
                'local_filepath': doc.local_filepath,
                'site_filepath': doc.site_filepath,
                'size_mb': round(doc.size / (1024*1024), 2),
                'mime_type': doc.mime_type
            }
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
    
    @action(detail=True, methods=['get'])
    def download(self, request, pk=None):
        """
        Download the architecture document by ID.
        Only the dossier AM, assigned SO, and Admin can download.
        
        Usage: GET /api/dossiers/{dossier_id}/documents/{pk}/download/
        """
        doc = self.get_object()
        user = request.user
        
        # Permission check
        is_dossier_owner = doc.dossier.am == user
        is_responsible_so = doc.dossier.responsible_so == user
        is_admin = user.role in [Role.SO, Role.ADMIN]
        
        if not (is_dossier_owner or is_responsible_so or is_admin):
            return Response(
                {'error': 'You do not have permission to download this document'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Check if file exists on disk using local_filepath
        if not os.path.exists(doc.local_filepath):
            return Response(
                {'error': 'File not found on server'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            # Open and serve the file
            file_handle = open(doc.local_filepath, 'rb')
            
            # Create response with proper headers
            response = FileResponse(
                file_handle,
                content_type=doc.mime_type,
                as_attachment=True,
                filename=doc.filename
            )
            
            # Log download to audit
            AuditLogEntry.objects.create(
                audit_log=doc.dossier.audit_log,
                user=user,
                action_type=AuditActionType.DOCUMENT_UPLOADED,
                detail={
                    'action': 'downloaded',
                    'filename': doc.filename,
                    'file_size_mb': round(doc.size / (1024*1024), 2)
                }
            )
            
            return response
        
        except IOError as e:
            return Response(
                {'error': f'Error reading file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=False, methods=['get'])
    def download_by_filename(self, request, dossier_id=None, filename=None):
        """
        Download architecture document by filename directly.
        Only the dossier AM, assigned SO, and Admin can download.
        
        Usage: GET /api/dossiers/{dossier_id}/documents/{filename}/
        Example: GET /api/dossiers/1/documents/my-document.pdf/
        """
        user = request.user
        
        if not dossier_id or not filename:
            return Response(
                {'error': 'dossier_id and filename are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get the dossier
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            return Response(
                {'error': 'Dossier not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Permission check
        is_dossier_owner = dossier.am == user
        is_responsible_so = dossier.responsible_so == user
        is_admin = user.role in [Role.SO, Role.ADMIN]
        
        if not (is_dossier_owner or is_responsible_so or is_admin):
            return Response(
                {'error': 'You do not have permission to download documents from this dossier'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Find the document by filename in this dossier
        try:
            doc = ArchitectureDoc.objects.get(dossier_id=dossier_id, filename=filename)
        except ArchitectureDoc.DoesNotExist:
            return Response(
                {'error': f'Document "{filename}" not found in this dossier'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Check if file exists on disk using local_filepath
        if not os.path.exists(doc.local_filepath):
            return Response(
                {'error': 'File not found on server'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            # Open and serve the file
            file_handle = open(doc.local_filepath, 'rb')
            
            # Create response with proper headers
            response = FileResponse(
                file_handle,
                content_type=doc.mime_type,
                as_attachment=True,
                filename=doc.filename
            )
            
            # Log download to audit
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=user,
                action_type=AuditActionType.DOCUMENT_UPLOADED,
                detail={
                    'action': 'downloaded',
                    'filename': doc.filename,
                    'file_size_mb': round(doc.size / (1024*1024), 2)
                }
            )
            
            return response
        
        except IOError as e:
            return Response(
                {'error': f'Error reading file: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

# ============================================================================
# 4. ENHANCED RiskRegisterViewSet (Now writable for SO)
# ============================================================================

class RiskRegisterViewSet(DossierFilterMixin, viewsets.ModelViewSet):
    """
    ViewSet for risk registers
    SO can CREATE risk registers for submitted dossiers
    SO can UPDATE status via PATCH/PUT
    SO can view/manage risk items within their registers
    Supports nested route: /api/dossiers/{dossier_id}/risk-register/
    """
    queryset = RiskRegister.objects.all().order_by('-created_at')
    serializer_class = RiskRegisterSerializer
    permission_classes = [permissions.IsAuthenticated, CanManageRiskRegister]
    
    def get_queryset(self):
        """Filter risk registers based on user role and optional dossier_id"""
        user = self.request.user
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = RiskRegister.objects.all()
        elif user.role == Role.SO:
            # SO can see risk registers for dossiers they are responsible for
            queryset = RiskRegister.objects.filter(dossier__responsible_so=user)
        else:
            # AM can see risk registers for their own dossiers OR dossiers with delegated items
            queryset = RiskRegister.objects.filter(
                Q(dossier__am=user) | Q(items__delegated_to=user)
            ).distinct()
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """
        SO creates a risk register for a submitted dossier
        """
        dossier_id = self.kwargs.get('dossier_id')
        if not dossier_id:
            raise serializers.ValidationError("dossier_id is required in URL path")
        
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            raise serializers.ValidationError("Dossier not found")
        
        # Validate: Dossier must be submitted (QUESTIONNAIRE_SOUMIS or later)
        submitted_statuses = [
            DossierStatus.QUESTIONNAIRE_SOUMIS,
            DossierStatus.IA1_INCOHERENT,
            DossierStatus.IA1_COHERENT,
            DossierStatus.ARCHI_UPLOAD_EN_COURS,
            DossierStatus.IA2_INCOHERENT,
            DossierStatus.IA2_COHERENT,
            DossierStatus.RISQUES_EN_COURS,
            DossierStatus.PRET_VALIDATION,
            DossierStatus.VALIDE,
        ]
        
        if dossier.status not in submitted_statuses:
            raise serializers.ValidationError(
                "Risk register can only be created for submitted dossiers (status: QUESTIONNAIRE_SOUMIS or later)"
            )
        
        # Validate: Only SO responsible for this dossier can create
        if self.request.user.role == Role.SO:
            if dossier.responsible_so != self.request.user:
                raise serializers.ValidationError(
                    "You can only create risk registers for dossiers you are responsible for"
                )
        
        # Check if risk register already exists for this dossier
        if RiskRegister.objects.filter(dossier=dossier).exists():
            raise serializers.ValidationError(
                "A risk register already exists for this dossier"
            )
        
        # Create risk register
        serializer.save(
            dossier=dossier,
            created_by=self.request.user,
            status=RiskStatus.DRAFT
        )
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=self.request.user,
            action_type=AuditActionType.RISK_REGISTER_CREATED,
            detail={'dossier_id': dossier.id}
        )
    
    def perform_update(self, serializer):
        """
        Handle status updates via PATCH/PUT
        Log status changes to audit trail
        """
        register = self.get_object()
        old_status = register.status
        
        # Only SO responsible for dossier can update
        if self.request.user.role == Role.SO:
            if register.dossier.responsible_so != self.request.user:
                raise serializers.PermissionDenied(ERROR_ONLY_RESPONSIBLE_SO)
        
        # Save the updated register
        updated_register = serializer.save()
        
        # Log status change if status was updated
        if old_status != updated_register.status:
            AuditLogEntry.objects.create(
                audit_log=register.dossier.audit_log,
                user=self.request.user,
                action_type=AuditActionType.STATUS_CHANGED,
                detail={
                    'entity': 'RiskRegister',
                    'old_status': old_status,
                    'new_status': updated_register.status
                }
            )
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None, dossier_id=None):
        """
        Submit risk register for review (legacy action - use PATCH instead)
        Only SO can submit, status must be DRAFT
        """
        register = self.get_object()
        
        # Only SO responsible for dossier can submit
        if request.user.role == Role.SO:
            if register.dossier.responsible_so != request.user:
                return Response(
                    {'error': ERROR_ONLY_RESPONSIBLE_SO},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Validation
        if register.status != RiskStatus.DRAFT:
            return Response(
                {'error': f'Can only submit registers in DRAFT status, current: {register.status}'},
                status=status.HTTP_400_BAD_REQUEST
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
            {'status': RISK_REGISTER_SUBMITTED_MESSAGE, 'submitted_at': register.submitted_at.isoformat()},
            status=status.HTTP_200_OK
        )


# ============================================================================
# 3b. NEW RiskItemViewSet (Nested under RiskRegister)
# ============================================================================
# ============================================================================

class RiskItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for individual risk items within a risk register
    Nested route: /api/dossiers/{dossier_id}/risk-register/{register_id}/items/
    
    IMPORTANT DISTINCTION:
    - Dossier OWNER (AM): Full access to all risk items in their register
    - Delegation RECIPIENT (AM): READ-ONLY to register, can only accept/refuse delegated items
    - SO: Can create and manage items
    """
    serializer_class = RiskItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        # SO accessing contested endpoint: show contested action form
        if getattr(self, 'action', None) == 'contested':
            from .serializers import ContestedRiskActionSerializer
            return ContestedRiskActionSerializer
        
        # Delegation recipient viewing list: show delegation action form
        if getattr(self, 'action', None) == 'list':
            user = self.request.user
            register_id = self.kwargs.get('register_id')
            
            try:
                register = RiskRegister.objects.get(id=register_id)
                # If user is a delegation recipient (not the dossier owner)
                if user.role == Role.AM and register.dossier.am != user:
                    # Check if they have any delegated items
                    has_delegated_items = register.items.filter(
                        delegated_to=user,
                        status=RiskItemStatus.DELEGATED_PENDING
                    ).exists()
                    
                    if has_delegated_items:
                        return RiskItemDelegationActionSerializer
            except RiskRegister.DoesNotExist:
                pass
        
        # Owner AM creating new risk: use RiskItemActionSerializer
        if getattr(self, 'action', None) == 'create' and self.request.user.role == Role.AM:
            return RiskItemActionSerializer
        
        return super().get_serializer_class()

    def get_serializer(self, *args, **kwargs):
        # SO accessing contested endpoint
        if getattr(self, 'action', None) == 'contested':
            from .serializers import ContestedRiskActionSerializer
            kwargs.setdefault('context', self.get_serializer_context())
            return ContestedRiskActionSerializer(*args, **kwargs)
        
        if getattr(self, 'action', None) == 'create' and self.request.user.role == Role.AM:
            kwargs.setdefault('context', self.get_serializer_context())
            return RiskItemActionSerializer(*args, **kwargs)
        if getattr(self, 'action', None) == 'delegation_action' and self.request.user.role == Role.AM:
            kwargs.setdefault('context', self.get_serializer_context())
            return RiskItemDelegationActionSerializer(*args, **kwargs)
        return super().get_serializer(*args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        register_id = self.kwargs.get('register_id')
        try:
            context['register'] = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            context['register'] = None
        return context
    
    def get_queryset(self):
        """
        Filter risk items based on user role:
        - Dossier owner AM: See all items in their register
        - Delegation recipient AM: See ONLY items delegated to them
        - SO: See all items in their registers
        - Admin: See all items
        """
        user = self.request.user
        register_id = self.kwargs.get('register_id')
        
        if not register_id:
            return RiskItem.objects.none()
        
        try:
            register = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            return RiskItem.objects.none()
        
        # Start with items in this register
        queryset = register.items.all()
        
        # Check user role and access level
        if user.is_superuser or user.role == Role.ADMIN:
            # Admins see all items
            pass
        elif user.role == Role.SO:
            # SO: only if responsible for the dossier
            if register.dossier.responsible_so != user:
                return RiskItem.objects.none()
        else:
            # AM: Check if owner or delegation recipient
            if register.dossier.am == user:
                # Dossier owner: see all items in their register
                pass
            else:
                # Delegation recipient: see ONLY items delegated to them
                queryset = queryset.filter(delegated_to=user)
        
        return queryset.order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """
        Override list to handle delegation recipient view
        """
        user = request.user
        register_id = self.kwargs.get('register_id')
        
        try:
            register = RiskRegister.objects.get(id=register_id)
            
            # If delegation recipient accessing items list
            if user.role == Role.AM and register.dossier.am != user:
                # Check if they have delegated items
                delegated_items = register.items.filter(
                    delegated_to=user,
                    status=RiskItemStatus.DELEGATED_PENDING
                )
                
                if delegated_items.exists():
                    # Show delegation action form in browsable API
                    serializer = RiskItemDelegationActionSerializer(
                        context={'request': request, 'register': register}
                    )
                    return Response({
                        'message': 'You have delegated risk items to accept or refuse',
                        'delegated_items_count': delegated_items.count(),
                        'form': serializer.data if hasattr(serializer, 'data') else None
                    })
        except RiskRegister.DoesNotExist:
            pass
        
        # Default list behavior for SO and dossier owners
        return super().list(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        """
        Handle POST requests for both dossier owners and delegation recipients
        """
        user = request.user
        register_id = self.kwargs.get('register_id')
        
        try:
            register = RiskRegister.objects.get(id=register_id)
            
            # Delegation recipient submitting action
            if user.role == Role.AM and register.dossier.am != user:
                return self.delegation_action(request, register_id=register_id)
            
            # Dossier owner (AM) performing action on existing risk
            if user.role == Role.AM and register.dossier.am == user:
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)

                try:
                    risk = register.items.get(id=int(serializer.validated_data['risk_item']))
                except (ValueError, RiskItem.DoesNotExist):
                    raise serializers.ValidationError({'risk_item': "Risque sélectionné invalide."})

                # Set owner if null
                if risk.owner_user is None:
                    risk.owner_user = request.user
                    risk.save()

                action = serializer.validated_data['action']
                if action == RiskItemActionSerializer.ACTION_ACCEPT:
                    payload = self._accept_risk(risk, request.user, is_am_action=True)
                elif action == RiskItemActionSerializer.ACTION_DELEGATE:
                    payload = self._delegate_risk(risk, serializer.validated_data['delegate_user'], request.user, is_am_action=True)
                else:
                    payload = self._contest_risk(risk, request.user, serializer.validated_data['contest_reason'], is_am_action=True)

                return Response(payload, status=status.HTTP_200_OK)
        
        except RiskRegister.DoesNotExist:
            raise serializers.ValidationError("Risk register not found")
        
        # SO creates new risk items
        return super().create(request, *args, **kwargs)

    def delegation_action(self, request, pk=None, register_id=None, dossier_id=None):
        """
        Delegation recipient accepts or refuses a delegated risk.
        Only shows risks delegated to the current user in DELEGATED_PENDING status.
        
        POST body:
        {
            "risk_item": "5",  // ID of delegated risk
            "action": "accept"  // or "refuse"
        }
        """
        serializer = RiskItemDelegationActionSerializer(
            data=request.data,
            context={'request': request, 'register': self.get_serializer_context().get('register')}
        )
        serializer.is_valid(raise_exception=True)
        
        risk = serializer.validated_data['risk_object']
        action = serializer.validated_data['action']
        
        if action == RiskItemDelegationActionSerializer.ACCEPT:
            # Accept the risk
            risk.status = RiskItemStatus.ACCEPTED
            risk.accepted_at = timezone.now()
            risk.save()
            
            # Update register status
            self._update_register_status(risk.register)
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_ACCEPTED,
                detail={'risk_title': risk.title, 'delegated_acceptance': True}
            )
            
            return Response({
                'status': 'Risk accepted',
                'risk_title': risk.title,
                'accepted_at': risk.accepted_at.isoformat()
            }, status=status.HTTP_200_OK)
        
        else:  # REFUSE
            # Track refusal
            if not risk.refused_by:
                risk.refused_by = []
            risk.refused_by.append(request.user.id)
            
            # Return to pending, remove delegation
            risk.status = RiskItemStatus.PENDING
            risk.delegated_to = None
            risk.save()
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_UPDATED,
                detail={'risk_title': risk.title, 'action': 'refused_delegation'}
            )
            
            return Response({
                'status': 'Risk delegation refused',
                'risk_title': risk.title
            }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None, dossier_id=None):
        """
        Submit risk register for review (legacy action - use PATCH instead)
        Only SO can submit, status must be DRAFT
        """
        register = self.get_object()
        
        # Only SO responsible for dossier can submit
        if request.user.role == Role.SO:
            if register.dossier.responsible_so != request.user:
                return Response(
                    {'error': 'Only the responsible SO can submit this risk register'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Validation
        if register.status != RiskStatus.DRAFT:
            return Response(
                {'error': f'Can only submit registers in DRAFT status, current: {register.status}'},
                status=status.HTTP_400_BAD_REQUEST
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
# 3b. NEW RiskItemViewSet (Nested under RiskRegister)
# ============================================================================

class RiskItemViewSet(viewsets.ModelViewSet):
    """
    ViewSet for individual risk items within a risk register
    Nested route: /api/dossiers/{dossier_id}/risk-register/{register_id}/items/
    
    IMPORTANT DISTINCTION:
    - Dossier OWNER (AM): Full access to all risk items in their register
    - Delegation RECIPIENT (AM): READ-ONLY to register, can only accept/refuse delegated items
    - SO: Can create and manage items
    """
    serializer_class = RiskItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        # SO accessing contested endpoint: show contested action form
        if getattr(self, 'action', None) == 'contested':
            from .serializers import ContestedRiskActionSerializer
            return ContestedRiskActionSerializer
        
        # Delegation recipient viewing list: show delegation action form
        if getattr(self, 'action', None) == 'list':
            user = self.request.user
            register_id = self.kwargs.get('register_id')
            
            try:
                register = RiskRegister.objects.get(id=register_id)
                # If user is a delegation recipient (not the dossier owner)
                if user.role == Role.AM and register.dossier.am != user:
                    # Check if they have any delegated items
                    has_delegated_items = register.items.filter(
                        delegated_to=user,
                        status=RiskItemStatus.DELEGATED_PENDING
                    ).exists()
                    
                    if has_delegated_items:
                        return RiskItemDelegationActionSerializer
            except RiskRegister.DoesNotExist:
                pass
        
        # Owner AM creating new risk: use RiskItemActionSerializer
        if getattr(self, 'action', None) == 'create' and self.request.user.role == Role.AM:
            return RiskItemActionSerializer
        
        return super().get_serializer_class()

    def get_serializer(self, *args, **kwargs):
        # SO accessing contested endpoint
        if getattr(self, 'action', None) == 'contested':
            from .serializers import ContestedRiskActionSerializer
            kwargs.setdefault('context', self.get_serializer_context())
            return ContestedRiskActionSerializer(*args, **kwargs)
        
        if getattr(self, 'action', None) == 'create' and self.request.user.role == Role.AM:
            kwargs.setdefault('context', self.get_serializer_context())
            return RiskItemActionSerializer(*args, **kwargs)
        if getattr(self, 'action', None) == 'delegation_action' and self.request.user.role == Role.AM:
            kwargs.setdefault('context', self.get_serializer_context())
            return RiskItemDelegationActionSerializer(*args, **kwargs)
        return super().get_serializer(*args, **kwargs)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        register_id = self.kwargs.get('register_id')
        try:
            context['register'] = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            context['register'] = None
        return context
    
    def get_queryset(self):
        """
        Filter risk items based on user role:
        - Dossier owner AM: See all items in their register
        - Delegation recipient AM: See ONLY items delegated to them
        - SO: See all items in their registers
        - Admin: See all items
        """
        user = self.request.user
        register_id = self.kwargs.get('register_id')
        
        if not register_id:
            return RiskItem.objects.none()
        
        try:
            register = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            return RiskItem.objects.none()
        
        # Start with items in this register
        queryset = register.items.all()
        
        # Check user role and access level
        if user.is_superuser or user.role == Role.ADMIN:
            # Admins see all items
            pass
        elif user.role == Role.SO:
            # SO: only if responsible for the dossier
            if register.dossier.responsible_so != user:
                return RiskItem.objects.none()
        else:
            # AM: Check if owner or delegation recipient
            if register.dossier.am == user:
                # Dossier owner: see all items in their register
                pass
            else:
                # Delegation recipient: see ONLY items delegated to them
                queryset = queryset.filter(delegated_to=user)
        
        return queryset.order_by('-created_at')
    
    def list(self, request, *args, **kwargs):
        """
        Override list to handle delegation recipient view
        """
        user = request.user
        register_id = self.kwargs.get('register_id')
        
        try:
            register = RiskRegister.objects.get(id=register_id)
            
            # If delegation recipient accessing items list
            if user.role == Role.AM and register.dossier.am != user:
                # Check if they have delegated items
                delegated_items = register.items.filter(
                    delegated_to=user,
                    status=RiskItemStatus.DELEGATED_PENDING
                )
                
                if delegated_items.exists():
                    # Show delegation action form in browsable API
                    serializer = RiskItemDelegationActionSerializer(
                        context={'request': request, 'register': register}
                    )
                    return Response({
                        'message': 'You have delegated risk items to accept or refuse',
                        'delegated_items_count': delegated_items.count(),
                        'form': serializer.data if hasattr(serializer, 'data') else None
                    })
        except RiskRegister.DoesNotExist:
            pass
        
        # Default list behavior for SO and dossier owners
        return super().list(request, *args, **kwargs)
    
    def create(self, request, *args, **kwargs):
        """
        Handle POST requests for both dossier owners and delegation recipients
        """
        user = request.user
        register_id = self.kwargs.get('register_id')
        
        try:
            register = RiskRegister.objects.get(id=register_id)
            
            # Delegation recipient submitting action
            if user.role == Role.AM and register.dossier.am != user:
                return self.delegation_action(request, register_id=register_id)
            
            # Dossier owner (AM) performing action on existing risk
            if user.role == Role.AM and register.dossier.am == user:
                serializer = self.get_serializer(data=request.data)
                serializer.is_valid(raise_exception=True)

                try:
                    risk = register.items.get(id=int(serializer.validated_data['risk_item']))
                except (ValueError, RiskItem.DoesNotExist):
                    raise serializers.ValidationError({'risk_item': "Risque sélectionné invalide."})

                # Set owner if null
                if risk.owner_user is None:
                    risk.owner_user = request.user
                    risk.save()

                action = serializer.validated_data['action']
                if action == RiskItemActionSerializer.ACTION_ACCEPT:
                    payload = self._accept_risk(risk, request.user, is_am_action=True)
                elif action == RiskItemActionSerializer.ACTION_DELEGATE:
                    payload = self._delegate_risk(risk, serializer.validated_data['delegate_user'], request.user, is_am_action=True)
                else:
                    payload = self._contest_risk(risk, request.user, serializer.validated_data['contest_reason'], is_am_action=True)

                return Response(payload, status=status.HTTP_200_OK)
        
        except RiskRegister.DoesNotExist:
            raise serializers.ValidationError("Risk register not found")
        
        # SO creates new risk items
        return super().create(request, *args, **kwargs)

    def delegation_action(self, request, pk=None, register_id=None, dossier_id=None):
        """
        Delegation recipient accepts or refuses a delegated risk.
        Only shows risks delegated to the current user in DELEGATED_PENDING status.
        
        POST body:
        {
            "risk_item": "5",  // ID of delegated risk
            "action": "accept"  // or "refuse"
        }
        """
        serializer = RiskItemDelegationActionSerializer(
            data=request.data,
            context={'request': request, 'register': self.get_serializer_context().get('register')}
        )
        serializer.is_valid(raise_exception=True)
        
        risk = serializer.validated_data['risk_object']
        action = serializer.validated_data['action']
        
        if action == RiskItemDelegationActionSerializer.ACCEPT:
            # Accept the risk
            risk.status = RiskItemStatus.ACCEPTED
            risk.accepted_at = timezone.now()
            risk.save()
            
            # Update register status
            self._update_register_status(risk.register)
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_ACCEPTED,
                detail={'risk_title': risk.title, 'delegated_acceptance': True}
            )
            
            return Response({
                'status': 'Risk accepted',
                'risk_title': risk.title,
                'accepted_at': risk.accepted_at.isoformat()
            }, status=status.HTTP_200_OK)
        
        else:  # REFUSE
            # Track refusal
            if not risk.refused_by:
                risk.refused_by = []
            risk.refused_by.append(request.user.id)
            
            # Return to pending, remove delegation
            risk.status = RiskItemStatus.PENDING
            risk.delegated_to = None
            risk.save()
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_UPDATED,
                detail={'risk_title': risk.title, 'action': 'refused_delegation'}
            )
            
            return Response({
                'status': 'Risk delegation refused',
                'risk_title': risk.title
            }, status=status.HTTP_200_OK)
    
    @action(detail=True, methods=['post'])
    def submit(self, request, pk=None, dossier_id=None):
        """
        Submit risk register for review (legacy action - use PATCH instead)
        Only SO can submit, status must be DRAFT
        """
        register = self.get_object()
        
        # Only SO responsible for dossier can submit
        if request.user.role == Role.SO:
            if register.dossier.responsible_so != request.user:
                return Response(
                    {'error': 'Only the responsible SO can submit this risk register'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Validation
        if register.status != RiskStatus.DRAFT:
            return Response(
                {'error': f'Can only submit registers in DRAFT status, current: {register.status}'},
                status=status.HTTP_400_BAD_REQUEST
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
            {'status': RISK_REGISTER_SUBMITTED_MESSAGE, 'submitted_at': register.submitted_at.isoformat()},
            status=status.HTTP_200_OK
        )
    
    def _get_register_for_contested(self, register_id):
        """Get and validate risk register exists"""
        try:
            return RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            return None
    
    def _check_so_permission(self, user, register):
        """Check if SO is responsible for the dossier"""
        if user.role == Role.SO and register.dossier.responsible_so != user:
            return False
        return True
    
    def _handle_get_contested_items(self, register):
        """Handle GET request for contested items"""
        contested_items = register.items.filter(status=RiskItemStatus.CONTESTED)
        
        if not contested_items.exists():
            return Response({
                'message': 'No contested risk items in this register',
                'contested_items_count': 0
            })
        
        items_data = [{
            'id': item.id,
            'title': item.title,
            'description': item.description,
            'level': item.level,
            'contested_by': item.contested_by.email if item.contested_by else None,
            'contested_at': item.contested_at.isoformat() if item.contested_at else None,
            'contestation_reason': item.contestation_reason
        } for item in contested_items]
        
        return Response({
            'message': 'Contested risk items - Use form below to accept or reject',
            'contested_items_count': contested_items.count(),
            'contested_items': items_data
        })
    
    def _handle_accept_contestation(self, risk, request):
        """Handle accepting a contestation"""
        risk_title = risk.title
        register_ref = risk.register
        
        risk.delete()
        self._update_register_status(register_ref)
        
        AuditLogEntry.objects.create(
            audit_log=register_ref.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_ITEM_DELETED,
            detail={
                'risk_title': risk_title,
                'action': 'contestation_accepted_by_so',
                'deleted_by': request.user.email
            }
        )
        
        return Response({
            'status': 'Contestation accepted',
            'message': f'Risk item "{risk_title}" has been deleted',
            'action': 'deleted'
        }, status=status.HTTP_200_OK)
    
    def _handle_reject_contestation(self, risk, rejection_reason, request):
        """Handle rejecting a contestation"""
        risk.status = RiskItemStatus.PENDING
        risk.contestation_reason = f"[REJECTED BY SO] {rejection_reason}"
        risk.contested_by = None
        risk.contested_at = None
        risk.save()
        
        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_ITEM_UPDATED,
            detail={
                'risk_title': risk.title,
                'action': 'contestation_rejected_by_so',
                'rejection_reason': rejection_reason,
                'rejected_by': request.user.email
            }
        )
        
        return Response({
            'status': 'Contestation rejected',
            'message': f'Risk item "{risk.title}" returned to PENDING status',
            'action': 'rejected',
            'rejection_reason': rejection_reason
        }, status=status.HTTP_200_OK)
    
    @action(detail=False, methods=['get', 'post'], url_path='contested')
    def contested(self, request, register_id=None, dossier_id=None):
        """
        SO manages contested risk items.
        GET: Shows list of contested items with management form
        POST: Accepts or rejects contestation
        
        Only accessible by SO responsible for the dossier.
        """
        from .serializers import ContestedRiskActionSerializer
        
        # Permission check: Only SO can access
        if request.user.role != Role.SO and not request.user.is_superuser:
            return Response(
                {'error': 'Only Security Officers can manage contested risks'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Get and validate register
        register = self._get_register_for_contested(register_id)
        if not register:
            return Response(
                {'error': 'Risk register not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Verify SO permission
        if not self._check_so_permission(request.user, register):
            return Response(
                {'error': 'You are not the responsible SO for this dossier'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if request.method == 'GET':
            return self._handle_get_contested_items(register)
        
        # POST: Process contestation decision
        serializer = ContestedRiskActionSerializer(
            data=request.data,
            context={'request': request, 'register': register}
        )
        serializer.is_valid(raise_exception=True)
        
        risk = serializer.validated_data['risk_object']
        action = serializer.validated_data['action']
        
        if action == 'accept':
            return self._handle_accept_contestation(risk, request)
        
        rejection_reason = serializer.validated_data.get('rejection_reason', '')
        return self._handle_reject_contestation(risk, rejection_reason, request)
    
    @action(detail=True, methods=['post'])
    def contest(self, request, pk=None, register_id=None, dossier_id=None):
        """
        AM contests a risk item
        SO must then accept or reject the contestation
        
        UPDATED: Prevent re-contestation if SO previously rejected
        """
        risk = self.get_object()
        
        # Only owner (AM) can contest
        if risk.owner_user != request.user:
            return Response(
                {'error': 'Only risk owner (AM) can contest'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Can't contest if already contested
        if risk.status == RiskItemStatus.CONTESTED:
            return Response(
                {'error': 'This risk is already under contestation'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # NEW: Prevent re-contestation if SO previously rejected
        if risk.contestation_reason and risk.contestation_reason.startswith('[REJECTED BY SO]'):
            return Response(
                {'error': 'This risk cannot be contested again. Your previous contestation was rejected by the Security Officer.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        contestation_reason = request.data.get('contestation_reason', '')
        
        risk.status = RiskItemStatus.CONTESTED
        risk.contested_by = request.user
        risk.contested_at = timezone.now()
        risk.contestation_reason = contestation_reason
        risk.save()
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_ITEM_UPDATED,
            detail={
                'risk_title': risk.title,
                'action': 'contested',
                'contestation_reason': contestation_reason
            }
        )
        
        return Response(
            {'status': 'Risk contested', 'contested_at': risk.contested_at.isoformat()},
            status=status.HTTP_200_OK
        )
    
    def _update_register_status(self, register):
        """
        Auto-update risk register status based on items:
        - If all items ACCEPTED → ACCEPTED
        - If some items ACCEPTED → PARTIALLY_ACCEPTED
        - Otherwise → SUBMITTED (if submitted) or DRAFT
        """
        from .models import RiskStatus
        
        items = register.items.all()
        if not items.exists():
            return
        
        accepted_count = items.filter(status=RiskItemStatus.ACCEPTED).count()
        total_count = items.count()
        
        if accepted_count == total_count:
            register.status = RiskStatus.ACCEPTED
        elif accepted_count > 0:
            register.status = RiskStatus.PARTIALLY_ACCEPTED
        
        register.save()

    def _delegate_risk(self, risk, delegated_to, performed_by, is_am_action=False):
        # CHANGED: Allow AM to delegate even if they're not the owner (when using the action form)
        if not is_am_action and risk.owner_user != performed_by:
            raise PermissionDenied("Seul le propriétaire peut déléguer ce risque.")
        
        refused = list(risk.refused_by or [])
        if delegated_to.id in refused:
            raise serializers.ValidationError({'delegate_email': f"{delegated_to.email} a déjà refusé ce risque."})

        risk.delegated_to = delegated_to
        risk.status = RiskItemStatus.DELEGATED_PENDING
        risk.save()

        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=performed_by,
            action_type=AuditActionType.RISK_ITEM_DELEGATED,
            detail={'risk_title': risk.title, 'delegated_to': delegated_to.email}
        )
        return {'status': 'Risque délégué', 'delegated_to': delegated_to.email}

    def _accept_risk(self, risk, performed_by, is_am_action=False):
        can_accept = (
            is_am_action or  # CHANGED: Allow if AM is using action form
            risk.owner_user == performed_by or
            risk.delegated_to == performed_by or
            performed_by.role in [Role.SO, Role.ADMIN]
        )
        if not can_accept:
            raise PermissionDenied("Vous n'avez pas l'autorisation d'accepter ce risque.")

        risk.status = RiskItemStatus.ACCEPTED
        risk.accepted_at = timezone.now()
        risk.save()
        self._update_register_status(risk.register)

        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=performed_by,
            action_type=AuditActionType.RISK_ITEM_ACCEPTED,
            detail={'risk_title': risk.title}
        )
        return {'status': 'Risque accepté', 'accepted_at': risk.accepted_at.isoformat()}

    def _contest_risk(self, risk, performed_by, reason, is_am_action=False):
        # CHANGED: Allow AM to contest even if they're not the owner (when using the action form)
        if not is_am_action and risk.owner_user != performed_by:
            raise PermissionDenied("Seul le propriétaire peut contester ce risque.")
        
        if risk.status == RiskItemStatus.CONTESTED:
            raise serializers.ValidationError({'risk_item': "Ce risque est déjà contesté."})

        risk.status = RiskItemStatus.CONTESTED
        risk.contested_by = performed_by
        risk.contested_at = timezone.now()
        risk.contestation_reason = reason
        risk.save()

        AuditLogEntry.objects.create(
            audit_log=risk.register.dossier.audit_log,
            user=performed_by,
            action_type=AuditActionType.RISK_ITEM_UPDATED,
            detail={'risk_title': risk.title, 'action': 'contested', 'reason': reason}
        )
        return {'status': 'Risque contesté', 'contested_at': risk.contested_at.isoformat()}

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
# 8. ENHANCED QuestionnaireTemplateViewSet
# ============================================================================

class QuestionnaireTemplateViewSet(viewsets.ModelViewSet):
    """
    ViewSet for questionnaire templates.
    - List: AM can see available templates for selection (with simple info)
    - Retrieve: Get full template with all questions
    - Create/Update/Delete: Only ADMIN can manage
    """
    queryset = QuestionnaireTemplate.objects.all().order_by('-updated_at')
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers based on action"""
        if self.action in ['list']:
            return QuestionnaireTemplateSimpleSerializer
        return QuestionnaireTemplateSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'available']:
            # Everyone can view published templates
            permission_classes = [permissions.IsAuthenticated]
        else:
            # Only admin can create/update/delete
            permission_classes = [permissions.IsAuthenticated, IsSecurityOfficer]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            # Admin sees all templates
            return QuestionnaireTemplate.objects.all().order_by('-updated_at')
        else:
            # Others see only published templates
            return QuestionnaireTemplate.objects.filter(status=QuestionnaireStatus.PUBLISHED).order_by('-updated_at')
    
    def perform_create(self, serializer):
        """Set the creator when creating a template"""
        serializer.save(created_by=self.request.user)
    
    @action(detail=False, methods=['get'])
    def available(self, request):
        """
        Get list of available published templates for dropdown selection in dossier creation.
        Returns simple template info for dropdown display.
        """
        templates = self.get_queryset()
        serializer = QuestionnaireTemplateSimpleSerializer(templates, many=True)
        return Response({
            'count': len(serializer.data),
            'templates': serializer.data
        })
    
    @action(detail=True, methods=['get'])
    def with_questions(self, request, pk=None):
        """
        Get template with all its questions for answering.
        Used when AM selects a template and needs to see all questions.
        """
        template = self.get_object()
        serializer = QuestionnaireTemplateSerializer(template)
        return Response(serializer.data)


# ============================================================================
# 9. QuestionViewSet
# ============================================================================

class QuestionViewSet(viewsets.ModelViewSet):
    """
    ViewSet for questions within a questionnaire template.
    Accessible via nested route: /api/questionnaires/{questionnaire_id}/questions/
    """
    serializer_class = QuestionSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            permission_classes = [permissions.IsAuthenticated]
        else:
            permission_classes = [permissions.IsAuthenticated, IsSecurityOfficer]
        return [permission() for permission in permission_classes]
    
    def get_queryset(self):
        questionnaire_id = self.kwargs.get('questionnaire_id')
        if questionnaire_id:
            return Question.objects.filter(template_id=questionnaire_id).order_by('order')
        return Question.objects.all().order_by('order')


# ============================================================================
# 10. ENHANCED QuestionnaireAnswerViewSet
# ============================================================================

class QuestionnaireAnswerViewSet(viewsets.ModelViewSet):
    """
    ViewSet for answering questionnaire questions.
    - AM can CREATE/UPDATE/DELETE answers for their own dossiers
    - SO can ONLY VIEW answers for dossiers they are responsible for (read-only)
    - Admin can view all answers
    - Supports bulk answer submission
    - ONLY allows answering questions from the dossier's assigned template
    Accessible via nested route: /api/dossiers/{dossier_id}/answers/
    """
    serializer_class = QuestionnaireAnswerSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        dossier_id = self.kwargs.get('dossier_id')
        
        if user.is_superuser or user.role == Role.ADMIN:
            queryset = QuestionnaireAnswer.objects.all()
        elif user.role == Role.SO:
            # SO can only view answers for dossiers they are responsible for
            queryset = QuestionnaireAnswer.objects.filter(dossier__responsible_so=user)
        else:
            # AM sees only answers for their own dossiers
            queryset = QuestionnaireAnswer.objects.filter(dossier__am=user)
        
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
            dossier = Dossier.objects.get(id=dossier_id)
            if dossier.questionnaire_template:
                queryset = queryset.filter(question__template=dossier.questionnaire_template)
        
        return queryset.order_by('question__order')
    
    def get_serializer_context(self):
        """Pass dossier to serializer context for question filtering"""
        context = super().get_serializer_context()
        dossier_id = self.kwargs.get('dossier_id')
        
        if dossier_id:
            try:
                dossier = Dossier.objects.get(id=dossier_id)
                context['dossier'] = dossier
            except Dossier.DoesNotExist:
                context['dossier'] = None
        
        return context
    
    def check_object_permissions(self, request, obj):
        """
        Check object permissions with SO read-only restriction.
        SO cannot perform any write operations on answers.
        """
        user = request.user
        
        # SO cannot perform ANY write operations on answers
        if user.role == Role.SO:
            if request.method not in permissions.SAFE_METHODS:
                from rest_framework.exceptions import PermissionDenied
                raise PermissionDenied(
                    "Security Officers can only view answers. Only Application Managers can modify answers."
                )
        
        super().check_object_permissions(request, obj)
    
    def perform_create(self, serializer):
        """Auto-set the dossier from URL and log action - use update_or_create to handle duplicates"""
        dossier_id = self.kwargs.get('dossier_id')
        if dossier_id:
            dossier = Dossier.objects.get(id=dossier_id)
            
            # SO cannot create answers
            if self.request.user.role == Role.SO:
                raise serializers.ValidationError(
                    "Security Officers cannot answer questions. Only Application Managers can answer."
                )
            
            # Validate dossier has a questionnaire template assigned
            if not dossier.questionnaire_template:
                raise serializers.ValidationError(
                    "This dossier does not have a questionnaire template assigned."
                )
            
            # Use update_or_create instead of save to handle existing answers
            question_id = serializer.validated_data.get('question').id
            answer_value = serializer.validated_data.get('answer_value', '')
            
            # IMPORTANT: Validate that the question belongs to this dossier's template
            question = Question.objects.get(id=question_id)
            if question.template != dossier.questionnaire_template:
                raise serializers.ValidationError(
                    f"Question {question_id} does not belong to the assigned questionnaire template."
                )
            
            _, created = QuestionnaireAnswer.objects.update_or_create(
                dossier_id=dossier_id,
                question_id=question_id,
                defaults={'answer_value': answer_value}
            )
            
            # Log to audit
            try:
                AuditLogEntry.objects.create(
                    audit_log=dossier.audit_log,
                    user=self.request.user,
                    action_type=AuditActionType.QUESTIONNAIRE_SAVED,
                    detail={
                        'question_id': question_id,
                        'action': 'created' if created else 'updated'
                    }
                )
            except Exception:
                pass
        else:
            serializer.save()
    
    def perform_update(self, serializer):
        """Log answer updates - SO cannot perform this"""
        user = self.request.user
        
        # SO cannot update answers
        if user.role == Role.SO:
            raise serializers.ValidationError(
                "Security Officers cannot modify answers. Only Application Managers can modify."
            )
        
        instance = self.get_object()
        dossier = instance.dossier
        
        # Validate that the question still belongs to the dossier's template
        if dossier.questionnaire_template:
            if instance.question.template != dossier.questionnaire_template:
                raise serializers.ValidationError(
                    "Cannot update answer for a question not in the assigned template."
                )
        
        serializer.save()
        
        # Log to audit
        try:
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=self.request.user,
                action_type=AuditActionType.QUESTIONNAIRE_SAVED,
                detail={
                    'question_id': instance.question_id,
                    'old_value': instance.answer_value
                }
            )
        except Exception:
            pass
    
    def perform_destroy(self, instance):
        """SO cannot delete answers"""
        user = self.request.user
        
        if user.role == Role.SO:
            raise serializers.ValidationError(
                "Security Officers cannot delete answers. Only Application Managers can delete."
            )
        
        instance.delete()

    def _validate_bulk_answer_permissions(self, dossier, user):
        """Check if user has permission to answer the questionnaire"""
        return dossier.am == user or user.role in [Role.ADMIN, Role.SO]
    
    def _validate_question_belongs_to_template(self, question, template):
        """Check if question belongs to the dossier's template"""
        return question.template == template
    
    def _process_single_answer(self, answer_data, dossier_id, dossier, user):
        """Process a single answer and return result"""
        question_id = answer_data.get('question')
        answer_value = answer_data.get('answer_value')
        
        if not question_id:
            return {'error': 'question id is required', 'data': answer_data}
        
        try:
            question = Question.objects.get(id=question_id)
        except Question.DoesNotExist:
            return {'error': f'Question {question_id} not found', 'data': answer_data}
        
        if not dossier.questionnaire_template:
            return {'error': 'This dossier does not have a questionnaire template assigned', 'data': answer_data}
        
        if not self._validate_question_belongs_to_template(question, dossier.questionnaire_template):
            return {'error': f'Question {question_id} does not belong to the assigned questionnaire template', 'data': answer_data}
        
        _, created = QuestionnaireAnswer.objects.update_or_create(
            dossier_id=dossier_id,
            question_id=question_id,
            defaults={'answer_value': answer_value or ''}
        )
        
        self._log_answer_action(dossier, user, question_id, question.text, created)
        
        return {'created': created}
    
    def _log_answer_action(self, dossier, user, question_id, question_text, created):
        """Log answer action to audit"""
        try:
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=user,
                action_type=AuditActionType.QUESTIONNAIRE_SAVED,
                detail={
                    'question_id': question_id,
                    'question_text': question_text[:100],
                    'action': 'created' if created else 'updated'
                }
            )
        except Exception:
            pass
    
    @action(detail=False, methods=['post'])
    def bulk_answer(self, request, dossier_id=None):
        """
        Bulk submit/update multiple answers at once.
        SO cannot perform bulk answer operations.
        """
        # SO cannot perform bulk answer operations
        if request.user.role == Role.SO:
            return Response(
                {'error': 'Security Officers cannot answer questions. Only Application Managers can answer.'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not dossier_id:
            return Response(
                {'error': 'dossier_id is required in URL'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            return Response(
                {'error': 'Dossier not found'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        if not self._validate_bulk_answer_permissions(dossier, request.user):
            return Response(
                {'error': 'You do not have permission to answer this questionnaire'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not dossier.questionnaire_template:
            return Response(
                {'error': 'This dossier does not have a questionnaire template assigned'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        answers_data = request.data.get('answers', [])
        if not answers_data:
            return Response(
                {'error': 'No answers provided'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        created_count = 0
        updated_count = 0
        errors = []
        
        for answer_data in answers_data:
            try:
                result = self._process_single_answer(answer_data, dossier_id, dossier, request.user)
                
                if 'error' in result:
                    errors.append(result)
                elif result.get('created'):
                    created_count += 1
                else:
                    updated_count += 1
            
            except Exception as e:
                errors.append({'error': str(e), 'data': answer_data})
        
        return Response({
            'status': 'Answers processed',
            'created': created_count,
            'updated': updated_count,
            'errors': errors,
            'total_processed': created_count + updated_count
        }, status=status.HTTP_200_OK if not errors else status.HTTP_206_PARTIAL_CONTENT)

# ============================================================================
# 11. HOME DASHBOARD
# ============================================================================

def home_dashboard(request):
    """Render home dashboard (placeholder for frontend)"""
    return render(request, 'core/dashboard.html')