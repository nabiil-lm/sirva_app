from .models import QuestionnaireTemplate, Question, QuestionnaireAnswer, QuestionType
from .serializers import (
    QuestionnaireTemplateSerializer, QuestionnaireTemplateSimpleSerializer,
    QuestionSerializer, QuestionnaireAnswerSerializer, BulkQuestionnaireAnswerSerializer,
    DossierSubmitSerializer, RiskItemActionSerializer, RiskItemDelegationActionSerializer,
    ContestedRiskActionSerializer, SoContestReviewSerializer # ADD SoContestReviewSerializer
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
from rest_framework.exceptions import PermissionDenied, APIException
from django.db.utils import OperationalError

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
from .tasks import trigger_ia1_analysis, trigger_ia2_analysis
import logging

logger = logging.getLogger(__name__)

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
    
    def get_dossier_id_from_url(self):
        """Helper to get dossier_id from various URL kwarg possibilities"""
        return (self.kwargs.get('dossier_pk') or 
                self.kwargs.get('dossier') or 
                self.kwargs.get('dossier_id'))

    def filter_queryset_by_dossier(self, queryset):
        """Filter queryset by dossier_id if provided in URL"""
        dossier_id = self.get_dossier_id_from_url()
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
    - AM can see leur propre dossiers (tous les statuts)
    - SO can voir UNIQUEMENT les dossiers dont ils sont responsables avec le statut QUESTIONNAIRE_SOUMIS ou ultérieur
    - Admin can see all dossiers
    """
    queryset = Dossier.objects.all().order_by('-updated_at')
    serializer_class = DossierSerializer
    permission_classes = [permissions.IsAuthenticated, CanModifyDossier] 
    
    def get_queryset(self):
        """
        Filter dossiers based on user role:
        - AM: Only their own dossiers (all statuses)
        - SO: Only dossiers they are responsible for (ALL statuses to follow progress)
        - Delegation Recipients (AM): Dossiers that contain risk items delegated to them
        - Admin: All dossiers
        """
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN:
            return Dossier.objects.all().order_by('-updated_at')
        elif user.role == Role.SO:
            # SO can ONLY see dossiers they are responsible for
            # CHANGED: Removed status filter so SO can follow progress from the start
            return Dossier.objects.filter(
                responsible_so=user
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
        # NEW: Restrict creation to AMs only
        if self.request.user.role != Role.AM and not self.request.user.is_superuser:
             raise PermissionDenied("Only Application Managers can create dossiers.")

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

    @action(detail=False, methods=['get'])
    def available_sos(self, request):
        """
        Get list of available Security Officers for assignment.
        """
        sos = User.objects.filter(role=Role.SO).order_by('last_name', 'first_name', 'email')
        data = [{'id': so.id, 'email': so.email, 'name': f"{so.first_name} {so.last_name}".strip() or so.email} for so in sos]
        return Response(data)

    @action(detail=True, methods=['get'])
    def full(self, request, pk=None):
        """
        Get dossier with all related data (documents, risks, IA results, audit log).
        
        This 'composite' endpoint is used by the frontend Dashboard to load the 
        entire dossier state in a single HTTP request, rather than making 
        separate calls to /documents/, /ia1/, /ia2/, etc.
        
        It returns:
        - Dossier details
        - Architecture Documents (via ArchitectureDocSerializer)
        - IA1 Analysis Results
        - IA2 Analysis Results
        - Risk Register & Items
        - Audit Log
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
            ia1 = dossier.ia1_result
            findings = ia1.findings
            
            # FIX: If findings lacks structured data but raw_response has JSON, try to parse and merge
            # This handles cases where the task saved findings incorrectly or in a legacy format
            if isinstance(findings, dict) and 'strengths' not in findings and ia1.raw_response:
                try:
                    import json
                    import re
                    # Clean markdown code blocks
                    clean_json = re.sub(r'```json\s*|\s*```', '', ia1.raw_response).strip()
                    # Find JSON object if surrounded by text
                    if not clean_json.startswith('{'):
                        match = re.search(r'(\{.*\})', clean_json, re.DOTALL)
                        if match:
                            clean_json = match.group(1)
                            
                    if clean_json.startswith('{'):
                        parsed = json.loads(clean_json)
                        if isinstance(parsed, dict):
                            # Merge parsed data into findings (preserving existing keys)
                            # We use a copy to avoid modifying the DB object in memory unexpectedly
                            findings = findings.copy()
                            findings.update(parsed)
                except Exception as e:
                    logger.warning(f"Failed to patch IA1 findings from raw_response: {e}")

            data['ia1_result'] = {
                'status': ia1.status,
                'secure_score': float(ia1.secure_score or 0),
                'findings': findings,
                'raw_response': ia1.raw_response,
                'created_at': ia1.created_at.isoformat()
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
            
            # CHANGED: Hide risk register from AM if it is DRAFT (work in progress by SO)
            if request.user.role == Role.AM and risk_register.status == RiskStatus.DRAFT:
                data['risk_register'] = None
            else:
                try:
                    items_data = RiskItemSerializer(risk_register.items.all(), many=True).data
                except OperationalError as e:
                    # Catch missing column errors to provide a clearer message
                    if "no such column" in str(e):
                        raise APIException("Database schema mismatch. Please run 'python manage.py makemigrations' and 'python manage.py migrate'.")
                    raise e

                data['risk_register'] = {
                    'id': risk_register.id,
                    'status': risk_register.status,
                    'total_items': risk_register.total_items,
                    'accepted_items': risk_register.accepted_items,
                    'items': items_data,
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
        
        # Log the submission action to audit
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
        
        # NEW: Trigger IA1 analysis automatically
        # Run synchronously for immediate feedback (set async_mode=True to trigger in background)
        try:
            ia1_result = trigger_ia1_analysis(dossier.id, async_mode=False)
            
            # Check if analysis had errors
            if ia1_result.get('error'):
                logger.warning(f"IA1 analysis error for dossier {dossier.id}: {ia1_result.get('message')}")
        except Exception as e:
            logger.error(f"Failed to trigger IA1 analysis: {str(e)}", exc_info=True)
            ia1_result = {
                'secure_score': 0,
                'is_coherent': False,
                'message': f'AI analysis error: {str(e)}',
                'error': True
            }

        # Reload dossier to get updated status after IA1 analysis
        dossier.refresh_from_db()
        
        # NEW: Auto-transition to ARCHI_UPLOAD_EN_COURS if IA1 passed
        if ia1_result.get('is_coherent'):
            old_status = dossier.status
            dossier.status = DossierStatus.ARCHI_UPLOAD_EN_COURS
            dossier.save()
            
            # Log the automatic status transition
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.STATUS_CHANGED,
                detail={
                    'entity': 'Dossier',
                    'old_status': old_status,
                    'new_status': DossierStatus.ARCHI_UPLOAD_EN_COURS,
                    'reason': 'Automatic transition after successful IA1 analysis',
                    'ia1_secure_score': ia1_result.get('secure_score')
                }
            )
        
        # Build response based on IA1 result
        response_data = {
            'status': 'Questionnaire submitted successfully',
            'dossier_id': dossier.id,
            'answers_count': answer_count,
            'ia1_analysis': {
                'secure_score': ia1_result.get('secure_score'),
                'is_coherent': ia1_result.get('is_coherent'),
                'message': ia1_result.get('message')
            },
            'dossier_status': dossier.status,
        }
        
        # Add guidance based on result
        if ia1_result.get('is_coherent'):
            response_data['next_step'] = 'You can now upload architecture documents'
            response_data['message'] = f'Dossier submitted and approved! Secure score: {ia1_result.get("secure_score")}/100. Ready for architecture upload.'
        else:
            response_data['next_step'] = 'Please review and improve your answers based on the analysis'
            response_data['message'] = f'Dossier needs revision. Secure score: {ia1_result.get("secure_score")}/100 (minimum required: 15)'
            response_data['ia1_analysis']['view_details'] = f'/api/dossiers/{dossier.id}/ia-checks/'

        return Response(response_data, status=status.HTTP_200_OK)

    def get_serializer_class(self):
        """Override serializer based on action"""
        if self.action == 'change_status':
            from .serializers import DossierStatusChangeSerializer
            return DossierStatusChangeSerializer
        return super().get_serializer_class()
    
    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticated], serializer_class=None)
    def change_status(self, request, pk=None):
        """
        Admin-only action to change dossier status.
        GET: Returns available status choices
        POST: Updates dossier status
        
        Only superusers and admins can use this action.
        """
        # Permission check: only admins
        if not (request.user.is_superuser or request.user.role == Role.ADMIN):
            return Response(
                {'error': 'Only administrators can change dossier status'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        dossier = self.get_object()
        
        if request.method == 'GET':
            # Return serializer for dropdown rendering in browsable API
            serializer = self.get_serializer()
            return Response({
                'current_status': dossier.status,
                'current_status_display': dossier.get_status_display(),
                'dossier_id': dossier.id
            })
        
        # POST: Update status
        serializer = self.get_serializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(
                serializer.errors,
                status=status.HTTP_400_BAD_REQUEST
            )
        
        new_status = serializer.validated_data['status']
        
        # Update status
        old_status = dossier.status
        dossier.status = new_status
        dossier.save()
        
        # Log the status change
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.STATUS_CHANGED,
            detail={
                'entity': 'Dossier',
                'old_status': old_status,
                'new_status': new_status,
                'changed_by_admin': True
            }
        )
        
        return Response({
            'status': 'Dossier status updated successfully',
            'dossier_id': dossier.id,
            'old_status': old_status,
            'new_status': new_status,
            'old_status_display': dossier.get_status_display(),
            'new_status_display': dict(DossierStatus.choices).get(new_status, new_status),
            'message': f'Status changed from {old_status} to {new_status}'
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get', 'post'], permission_classes=[permissions.IsAuthenticated])
    def validation(self, request, pk=None):
        """
        Finalize dossier validation.
        GET: Check if dossier is ready for validation
        POST: Move dossier from PRET_VALIDATION to VALIDE (final state)
        
        Only accessible when dossier status is PRET_VALIDATION.
        Only SO (responsible for dossier) or Admin can access.
        """
        dossier = self.get_object()
        user = request.user
        
        # Permission check: only admin or responsible SO
        is_admin = user.is_superuser or user.role == Role.ADMIN
        is_responsible_so = user.role == Role.SO and dossier.responsible_so == user
        
        if not (is_admin or is_responsible_so):
            return Response(
                {'error': 'Only administrators or the responsible SO can validate this dossier'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Status check: dossier must be in PRET_VALIDATION
        # CHANGED: Allow validation from RISQUES_EN_COURS if user is SO (Direct Validation)
        allowed_statuses = [DossierStatus.PRET_VALIDATION]
        if is_responsible_so:
            allowed_statuses.append(DossierStatus.RISQUES_EN_COURS)

        if dossier.status not in allowed_statuses:
            return Response(
                {
                    'error': f'Dossier cannot be validated in current status: {dossier.status}',
                    'current_status': dossier.status
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        
        if request.method == 'GET':
            # Return validation status info
            return Response({
                'dossier_id': dossier.id,
                'current_status': dossier.status,
                'ready_for_validation': True,
                'can_validate': is_admin or is_responsible_so,
                'message': 'Dossier is ready for final validation'
            }, status=status.HTTP_200_OK)
        
        # POST: Finalize validation and move to VALIDE
        old_status = dossier.status
        dossier.status = DossierStatus.VALIDE
        dossier.save()
        
        # Log the final validation
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.STATUS_CHANGED,
            detail={
                'entity': 'Dossier',
                'old_status': old_status,
                'new_status': DossierStatus.VALIDE,
                'action': 'final_validation',
                'validated_by': request.user.email,
                'validated_by_role': 'Admin' if user.is_superuser or user.role == Role.ADMIN else 'SO'
            }
        )
        
        return Response({
            'status': 'Dossier validated successfully',
            'dossier_id': dossier.id,
            'old_status': old_status,
            'new_status': DossierStatus.VALIDE,
            'message': 'Dossier has been finalized and moved to VALIDE status'
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def admin_stats(self, request):
        """
        Get dashboard statistics for admin users.
        Only accessible to superusers and admin role.
        """
        if not (request.user.is_superuser or request.user.role == Role.ADMIN):
            return Response(
                {'error': 'Only administrators can access statistics'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Calculate stats
        total_dossiers = Dossier.objects.count()
        active_dossiers = Dossier.objects.exclude(
            status__in=[DossierStatus.VALIDE]
        ).count()
        
        published_templates = QuestionnaireTemplate.objects.filter(
            status=QuestionnaireStatus.PUBLISHED
        ).count()
        
        total_users = User.objects.filter(is_active=True).count()
        
        # Pending reviews (dossiers in PRET_VALIDATION status)
        pending_reviews = Dossier.objects.filter(
            status=DossierStatus.PRET_VALIDATION
        ).count()
        
        return Response({
            'total_dossiers': total_dossiers,
            'active_dossiers': active_dossiers,
            'published_templates': published_templates,
            'total_users': total_users,
            'pending_reviews': pending_reviews
        }, status=status.HTTP_200_OK)

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
        """Filter documents based on user role and dossier_id from nested URL"""
        user = self.request.user
        
        # Try all possible keys that nested routers might use
        dossier_id = self.get_dossier_id_from_url()
        
        if dossier_id:
            try:
                dossier = Dossier.objects.get(id=dossier_id)
                if user.is_superuser or user.role == Role.ADMIN:
                    return ArchitectureDoc.objects.filter(dossier_id=dossier_id).order_by('-uploaded_at')
                elif user.role == Role.SO:
                    if dossier.responsible_so == user:
                        return ArchitectureDoc.objects.filter(dossier_id=dossier_id).order_by('-uploaded_at')
                    else:
                        return ArchitectureDoc.objects.none()
                else:
                    if dossier.am == user:
                        return ArchitectureDoc.objects.filter(dossier_id=dossier_id).order_by('-uploaded_at')
                    else:
                        return ArchitectureDoc.objects.none()
            except Dossier.DoesNotExist:
                return ArchitectureDoc.objects.none()
        
        return ArchitectureDoc.objects.none()
    
    def perform_create(self, serializer):
        """Auto-set dossier from URL path, extract file info, save to disk, and log action"""
        # Try all possible keys that nested routers might use
        dossier_id = self.get_dossier_id_from_url()
        
        if not dossier_id:
            raise serializers.ValidationError("dossier_id is required in URL path")
        
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            raise serializers.ValidationError(f"Dossier {dossier_id} not found")
        
        # Check if documents have been submitted for this dossier
        if dossier.architecture_docs_submitted:
            raise serializers.ValidationError(
                "Documents have been submitted for this dossier. No further uploads are allowed."
            )
        
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
            
            # Save the uploaded file to disk
            with open(file_path, 'wb') as destination:
                for chunk in uploaded_file.chunks():
                    destination.write(chunk)
            
            # Store local_filepath (full absolute path)
            local_filepath = str(file_path)
            
            # Create site_filepath (relative download URL)
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
        
        # NEW: Check if submit_documents checkbox was checked
        # Try multiple ways to get the checkbox value from request
        submit_documents_flag = (
            self.request.data.get('submit_documents') or
            self.request.POST.get('submit_documents') or
            serializer.validated_data.get('submit_documents')
        )
        
        logger.info(f"Document upload for dossier {dossier_id}: submit_documents={submit_documents_flag}")
        
        # Convert string 'true'/'false' to boolean if needed
        if isinstance(submit_documents_flag, str):
            submit_documents_flag = submit_documents_flag.lower() in ['true', '1', 'on', 'yes']
        
        if submit_documents_flag:
            logger.info(f"Submit documents flag detected for dossier {dossier_id}. Starting IA2 analysis...")
            
            # Validate dossier status before submission
            if dossier.status != DossierStatus.ARCHI_UPLOAD_EN_COURS:
                raise serializers.ValidationError(
                    f"Documents can only be submitted when dossier is in ARCHI_UPLOAD_EN_COURS status, current: {dossier.status}"
                )
            
            # Validate at least one document exists
            if dossier.architecture_docs.count() == 0:
                raise serializers.ValidationError(
                    "At least one architecture document must be uploaded before submission"
                )
            
            # Mark documents as submitted
            dossier.architecture_docs_submitted = True
            dossier.save()
            
            logger.info(f"Marked documents as submitted for dossier {dossier_id}")
            
            # Log document submission to audit
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=self.request.user,
                action_type=AuditActionType.DOCUMENT_UPLOADED,
                detail={
                    'action': 'documents_submitted',
                    'total_documents': dossier.architecture_docs.count(),
                    'message': 'All architecture documents have been submitted for IA2 analysis'
                }
            )
            
            # Trigger IA2 (cross-check) analysis automatically
            try:
                from .tasks import trigger_ia2_analysis
                
                logger.info(f"Calling trigger_ia2_analysis for dossier {dossier_id}")
                ia2_result = trigger_ia2_analysis(dossier_id, async_mode=False)
                
                logger.info(f"IA2 analysis result: {ia2_result}")
                
                if ia2_result.get('error'):
                    logger.warning(f"IA2 analysis error for dossier {dossier_id}: {ia2_result.get('message')}")
            except Exception as e:
                logger.error(f"Failed to trigger IA2 analysis: {str(e)}", exc_info=True)
                # We don't need to set ia2_result here as we aren't returning it
            
            # Reload dossier to get updated status after IA2 analysis
            dossier.refresh_from_db()
            
            logger.info(f"Dossier {dossier_id} status after IA2: {dossier.status}")
            
            # Auto-transition to RISQUES_EN_COURS if IA2 passed
            # Note: We need to check the result from the task if we want to do this here, 
            # but since we removed ia2_result usage below, we rely on the task or separate call.
            # However, if we want to keep the auto-transition logic here, we need ia2_result.
            # Re-adding ia2_result just for this logic block:
            
            if 'ia2_result' in locals() and ia2_result.get('is_coherent') and dossier.status == DossierStatus.IA2_COHERENT:
                old_status = dossier.status
                dossier.status = DossierStatus.RISQUES_EN_COURS
                dossier.save()
                
                logger.info(f"Auto-transitioned dossier {dossier_id} to RISQUES_EN_COURS")
                
                # Log the automatic status transition
                AuditLogEntry.objects.create(
                    audit_log=dossier.audit_log,
                    user=self.request.user,
                    action_type=AuditActionType.STATUS_CHANGED,
                    detail={
                        'entity': 'Dossier',
                        'old_status': old_status,
                        'new_status': DossierStatus.RISQUES_EN_COURS,
                        'reason': 'Automatic transition after successful IA2 cross-check',
                        'ia2_secure_score': ia2_result.get('secure_score')
                    }
                )
        
        # REMOVED: Dead code that constructed a Response object. 
        # perform_create return value is ignored by ModelViewSet.
        # This prevents UnboundLocalError when submit_documents_flag is False

    def perform_destroy(self, instance):
        """Delete the file from disk when the record is deleted"""
        # Log deletion
        try:
            AuditLogEntry.objects.create(
                audit_log=instance.dossier.audit_log,
                user=self.request.user,
                action_type=AuditActionType.DOCUMENT_DELETED,
                detail={
                    'filename': instance.filename,
                    'local_filepath': instance.local_filepath
                }
            )
        except Exception as e:
            logger.warning(f"Failed to create audit log for document deletion: {e}")
        
        # Delete file from disk
        if instance.local_filepath and os.path.exists(instance.local_filepath):
            try:
                os.remove(instance.local_filepath)
                logger.info(f"Deleted file: {instance.local_filepath}")
            except Exception as e:
                logger.error(f"Error deleting file {instance.local_filepath}: {e}")
        
        instance.delete()

    @action(detail=True, methods=['get'])
    def download(self, request, pk=None, dossier_id=None, dossier_pk=None):
        """
        Download a document by ID.
        """
        doc = self.get_object()
        
        # Check if file exists
        if not os.path.exists(doc.local_filepath):
            return Response({'error': 'File not found on server'}, status=status.HTTP_404_NOT_FOUND)
            
        try:
            # Open file in binary mode
            file_handle = open(doc.local_filepath, 'rb')
            
            # Create FileResponse
            response = FileResponse(file_handle, content_type=doc.mime_type)
            response['Content-Disposition'] = f'attachment; filename="{doc.filename}"'
            return response
        except Exception as e:
            logger.error(f"Error downloading file {doc.local_filepath}: {e}")
            return Response({'error': 'Error reading file'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # REMOVED @action decorator to prevent router conflict with detail view (DELETE/PATCH)
    # This view is mapped manually in urls.py
    def download_by_filename(self, request, filename=None, dossier_id=None, dossier_pk=None):
        """
        Download a document by filename (used for direct links).
        """
        # Handle different URL parameter names
        target_dossier_id = dossier_id or dossier_pk or self.get_dossier_id_from_url()
        
        if not target_dossier_id:
            return Response({'error': 'Dossier ID required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            doc = ArchitectureDoc.objects.get(dossier_id=target_dossier_id, filename=filename)
            
            # Check permissions (reuse get_object logic via check_object_permissions if needed, 
            # but here we just check if user can access this doc)
            self.check_object_permissions(request, doc)
            
            if not os.path.exists(doc.local_filepath):
                return Response({'error': 'File not found on server'}, status=status.HTTP_404_NOT_FOUND)
                
            file_handle = open(doc.local_filepath, 'rb')
            response = FileResponse(file_handle, content_type=doc.mime_type)
            response['Content-Disposition'] = f'attachment; filename="{doc.filename}"'
            return response
            
        except ArchitectureDoc.DoesNotExist:
            return Response({'error': 'Document not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.error(f"Error downloading file by name {filename}: {e}")
            return Response({'error': 'Error reading file'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=False, methods=['post'])
    def submit_documents(self, request, *args, **kwargs):
        """
        Explicit action to submit all uploaded documents and trigger IA2 analysis.
        """
        dossier_id = self.get_dossier_id_from_url()
        if not dossier_id:
            return Response({'error': 'Dossier ID required'}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            return Response({'error': 'Dossier not found'}, status=status.HTTP_404_NOT_FOUND)

        # Validate dossier status
        if dossier.status != DossierStatus.ARCHI_UPLOAD_EN_COURS:
            return Response(
                {'error': f"Documents can only be submitted when dossier is in ARCHI_UPLOAD_EN_COURS status, current: {dossier.status}"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Validate at least one document exists
        if dossier.architecture_docs.count() == 0:
            return Response(
                {'error': "At least one architecture document must be uploaded before submission"},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Mark documents as submitted
        dossier.architecture_docs_submitted = True
        dossier.save()
        
        # Log document submission to audit
        AuditLogEntry.objects.create(
            audit_log=dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.DOCUMENT_UPLOADED,
            detail={
                'action': 'documents_submitted',
                'total_documents': dossier.architecture_docs.count(),
                'message': 'All architecture documents have been submitted for IA2 analysis'
            }
        )
        
        # Trigger IA2 (cross-check) analysis automatically
        ia2_result = {}
        try:
            from .tasks import trigger_ia2_analysis
            ia2_result = trigger_ia2_analysis(dossier_id, async_mode=False)
            
            if ia2_result.get('error'):
                logger.warning(f"IA2 analysis error for dossier {dossier_id}: {ia2_result.get('message')}")
        except Exception as e:
            logger.error(f"Failed to trigger IA2 analysis: {str(e)}", exc_info=True)
            ia2_result = {
                'secure_score': 0,
                'is_coherent': False,
                'message': f'AI analysis error: {str(e)}',
                'error': True
            }
        
        # Reload dossier to get updated status after IA2 analysis
        dossier.refresh_from_db()
        
        # Auto-transition to RISQUES_EN_COURS if IA2 passed
        if ia2_result.get('is_coherent') and dossier.status == DossierStatus.IA2_COHERENT:
            old_status = dossier.status
            dossier.status = DossierStatus.RISQUES_EN_COURS
            dossier.save()
            
            # Log the automatic status transition
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.STATUS_CHANGED,
                detail={
                    'entity': 'Dossier',
                    'old_status': old_status,
                    'new_status': DossierStatus.RISQUES_EN_COURS,
                    'reason': 'Automatic transition after successful IA2 cross-check',
                    'ia2_secure_score': ia2_result.get('secure_score')
                }
            )
            
        return Response({
            'status': 'Documents submitted and analyzed',
            'dossier_id': dossier.id,
            'ia2_analysis': ia2_result,
            'dossier_status': dossier.status
        })

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
            # CHANGED: AM cannot see DRAFT registers (work in progress by SO)
            queryset = RiskRegister.objects.filter(
                (Q(dossier__am=user) | Q(items__delegated_to=user)) & 
                ~Q(status=RiskStatus.DRAFT)
            ).distinct()
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.get_dossier_id_from_url()
        if dossier_id:
            queryset = queryset.filter(dossier_id=dossier_id)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """
        SO creates a risk register for a submitted dossier
        """
        dossier_id = self.get_dossier_id_from_url()
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
    def submit(self, request, pk=None, **kwargs):
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
    queryset = RiskItem.objects.all()  # ADD THIS LINE
    serializer_class = RiskItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        # SO accessing contested endpoint: show contested action form
        if getattr(self, 'action', None) == 'contested':
            from .serializers import ContestedRiskActionSerializer
            return ContestedRiskActionSerializer
        
        # NEW: SO reviewing contestation
        if getattr(self, 'action', None) == 'review_contest':
            return SoContestReviewSerializer
        
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
        
        # NEW: SO reviewing contestation
        if getattr(self, 'action', None) == 'review_contest':
            kwargs.setdefault('context', self.get_serializer_context())
            return SoContestReviewSerializer(*args, **kwargs)
        
        if getattr(self, 'action', None) == 'create' and self.request.user.role == Role.AM:
            kwargs.setdefault('context', self.get_serializer_context())
            return RiskItemActionSerializer(*args, **kwargs)
        if getattr(self, 'action', None) == 'delegation_action' and self.request.user.role == Role.AM:
            kwargs.setdefault('context', self.get_serializer_context())
            return RiskItemDelegationActionSerializer(*args, **kwargs)
        return super().get_serializer(*args, **kwargs)

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
            
            # CHANGED: AM cannot see items if register is DRAFT
            if register.status == RiskStatus.DRAFT:
                return RiskItem.objects.none()

            if register.dossier.am == user:
                # Dossier owner: see all items in their register
                pass
            else:
                # Delegation recipient: see ONLY items delegated to them
                queryset = queryset.filter(delegated_to=user)
        
        return queryset.order_by('-created_at')
    
    def perform_create(self, serializer):
        """
        SO creates a new risk item in the register
        """
        register_id = self.kwargs.get('register_id')
        
        try:
            register = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            raise serializers.ValidationError("Risk register not found")
        
        # Only SO can create risk items
        if self.request.user.role != Role.SO:
            raise serializers.ValidationError("Only Security Officers can create risk items")
        
        # Validate SO is responsible for the dossier
        if register.dossier.responsible_so != self.request.user:
            raise serializers.ValidationError("You can only create risk items for dossiers you are responsible for")
        
        # Create the risk item
        # FIX: Set owner_user to the dossier's AM (who owns the risk)
        risk_item = serializer.save(
            register=register,
            owner_user=register.dossier.am
        )
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=register.dossier.audit_log,
            user=self.request.user,
            action_type=AuditActionType.RISK_ITEM_UPDATED,
            detail={
                'action': 'created',
                'risk_title': risk_item.title,
                'risk_level': risk_item.level,
                'risk_status': risk_item.status
            }
        )

    def perform_update(self, serializer):
        """AM updates an existing risk item"""
        item = self.get_object()
        register = item.register
        
        # Only AM (dossier owner) can update items
        if self.request.user.role == Role.AM:
            if register.dossier.am != self.request.user:
                raise serializers.PermissionDenied(ERROR_ONLY_RESPONSIBLE_SO)
        
        # Update the risk item
        serializer.save()
        
        # Log to audit
        AuditLogEntry.objects.create(
            audit_log=register.dossier.audit_log,
            user=self.request.user,
            action_type=AuditActionType.RISK_ITEM_UPDATED,
            detail={'risk_title': serializer.validated_data.get('title')}
        )
    
    @action(detail=True, methods=['post'])
    def contested(self, request, pk=None, **kwargs):
        """
        AM contests a risk item decision (accept/refuse)
        """
        item = self.get_object()
        register = item.register
        
        # Only AM (dossier owner) can contest
        if request.user.role == Role.AM:
            if register.dossier.am != request.user:
                return Response(
                    {'error': ERROR_ONLY_RESPONSIBLE_SO},
                    status=status.HTTP_403_FORBIDDEN
                )
        else:
            return Response(
                {'error': 'Only the dossier owner can contest risk decisions'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Validation: contest reason is required
        contest_reason = request.data.get('contest_reason', '').strip()
        if not contest_reason:
            return Response(
                {'error': 'Contest reason is required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Update the risk item status to PENDING and clear delegation
        item.status = RiskItemStatus.PENDING
        item.delegated_to = None
        item.save()
        
        # Log the contest action
        AuditLogEntry.objects.create(
            audit_log=register.dossier.audit_log,
            user=request.user,
            action_type=AuditActionType.RISK_ITEM_UPDATED,
            detail={
                'risk_title': item.title,
                'action': 'contested',
                'contest_reason': contest_reason
            }
        )
        
        return Response({
            'status': 'Risk item contested',
            'risk_title': item.title
        }, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
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
            
            # Update register status (this will also update dossier if all items are accepted)
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
                'accepted_at': risk.accepted_at.isoformat(),
                'register_status': risk.register.status
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
    
    def create(self, request, *args, **kwargs):
        """
        Handle POST requests for both dossier owners and delegation recipients
        """
        user = request.user
        register_id = self.kwargs.get('register_id')
        
        try:
            register = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            raise serializers.ValidationError("Risk register not found")
        
        # Delegation recipient submitting action
        if user.role == Role.AM and register.dossier.am != user:
            return self._handle_delegation_action(request, register)
        
        # Dossier owner (AM) performing action on existing risk
        if user.role == Role.AM and register.dossier.am == user:
            return self._handle_am_risk_action(request, register)
        
        # SO creates new risk items (default behavior)
        return super().create(request, *args, **kwargs)
    
    def _handle_am_risk_action(self, request, register):
        """
        Handle AM actions on existing risk items (Accept, Delegate, Contest)
        """
        serializer = RiskItemActionSerializer(
            data=request.data,
            context={'request': request, 'register': register}
        )
        serializer.is_valid(raise_exception=True)

        # Get the risk item object (already a RiskItem instance from serializer)
        risk = serializer.validated_data['risk_item']
        
        # Validate that the risk belongs to this register
        if risk.register != register:
            raise serializers.ValidationError({'risk_item': "Ce risque n'appartient pas à ce registre."})

        # Set owner if null
        if risk.owner_user is None:
            risk.owner_user = request.user
            risk.save()

        action = serializer.validated_data['action']
        
        if action == RiskItemActionSerializer.ACTION_ACCEPT:
            # Accept the risk
            risk.status = RiskItemStatus.ACCEPTED
            risk.accepted_at = timezone.now()
            risk.save()
            
            # Update register status based on acceptance
            self._update_register_status(risk.register)
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_ACCEPTED,
                detail={'risk_title': risk.title}
            )
            
            return Response({
                'status': 'Risk accepted',
                'risk_title': risk.title,
                'accepted_at': risk.accepted_at.isoformat(),
                'register_status': risk.register.status
            }, status=status.HTTP_200_OK)
            
        elif action == RiskItemActionSerializer.ACTION_DELEGATE:
            delegate_user = serializer.validated_data['delegate_user']
            
            # Delegate the risk
            risk.status = RiskItemStatus.DELEGATED_PENDING
            risk.delegated_to = delegate_user
            risk.save()
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_UPDATED,
                detail={
                    'risk_title': risk.title,
                    'action': 'delegated',
                    'delegated_to': delegate_user.email
                }
            )
            
            return Response({
                'status': 'Risk delegated',
                'risk_title': risk.title,
                'delegated_to': delegate_user.email
            }, status=status.HTTP_200_OK)
            
        else:  # CONTEST
            contest_reason = serializer.validated_data['contest_reason']
            
            # Contest the risk
            risk.status = RiskItemStatus.CONTESTED
            risk.contestation_reason = contest_reason
            risk.contested_by = request.user
            risk.contested_at = timezone.now()
            risk.save()
            
            # Log to audit
            AuditLogEntry.objects.create(
                audit_log=risk.register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_UPDATED,
                detail={
                    'risk_title': risk.title,
                    'action': 'contested',
                    'reason': contest_reason
                }
            )
            
            return Response({
                'status': 'Risk contested',
                'risk_title': risk.title,
                'contest_reason': contest_reason
            }, status=status.HTTP_200_OK)
    
    def _handle_delegation_action(self, request, register):
        """
        Handle delegation recipient actions (Accept or Refuse delegated risks)
        """
        serializer = RiskItemDelegationActionSerializer(
            data=request.data,
            context={'request': request, 'register': register}
        )
        serializer.is_valid(raise_exception=True)
        
        risk = serializer.validated_data['risk_object']
        action = serializer.validated_data['action']
        
        if action == RiskItemDelegationActionSerializer.ACCEPT:
            # Accept the risk
            risk.status = RiskItemStatus.ACCEPTED
            risk.accepted_at = timezone.now()
            risk.save()
            
            # Update register status (this will also update dossier if all items are accepted)
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
                'accepted_at': risk.accepted_at.isoformat(),
                'register_status': risk.register.status
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
    def review_contest(self, request, pk=None, **kwargs):
        """
        SO reviews a contested risk item.
        - Accept: Risk is INVALIDATED (removed from active risks).
        - Refuse: Risk returns to PENDING for AM, contestation is marked refused.
        """
        item = self.get_object()
        register = item.register
        
        # Only SO responsible for dossier can review
        if request.user.role != Role.SO or register.dossier.responsible_so != request.user:
            return Response(
                {'error': 'Only the responsible Security Officer can review contestations'},
                status=status.HTTP_403_FORBIDDEN
            )
            
        if item.status != RiskItemStatus.CONTESTED:
            return Response(
                {'error': 'Item is not in CONTESTED status'},
                status=status.HTTP_400_BAD_REQUEST
            )
            
        serializer = SoContestReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        action = serializer.validated_data['action']
        
        if action == SoContestReviewSerializer.ACCEPT:
            # SO accepts the contestation -> Risk is Invalidated
            item.status = RiskItemStatus.INVALIDATED
            item.save()
            
            # Update register status (Invalidated counts as resolved)
            self._update_register_status(register)
            
            AuditLogEntry.objects.create(
                audit_log=register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_UPDATED,
                detail={'risk_title': item.title, 'action': 'contest_accepted_invalidated'}
            )
            
            return Response({'status': 'Contestation accepted. Risk invalidated.'})
            
        else: # REFUSE
            # SO refuses the contestation -> Back to AM
            item.status = RiskItemStatus.PENDING
            item.contest_refused = True # Flag to prevent re-contesting
            item.save()
            
            AuditLogEntry.objects.create(
                audit_log=register.dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.RISK_ITEM_UPDATED,
                detail={'risk_title': item.title, 'action': 'contest_refused'}
            )
            
            return Response({'status': 'Contestation refused. Returned to AM.'})

    def get_serializer_context(self):
        context = super().get_serializer_context()
        register_id = self.kwargs.get('register_id')
        try:
            context['register'] = RiskRegister.objects.get(id=register_id)
        except RiskRegister.DoesNotExist:
            context['register'] = None
        return context
    
    def _update_register_status(self, register):
        """
        Update register status based on risk item acceptance.
        - If any items are accepted: PARTIALLY_ACCEPTED
        - If all items are accepted: ACCEPTED (also updates dossier to PRET_VALIDATION)
        """
        total_items = register.items.count()
        # CHANGED: Count INVALIDATED items as accepted/resolved
        accepted_items = register.items.filter(status__in=[RiskItemStatus.ACCEPTED, RiskItemStatus.INVALIDATED]).count()
        
        old_status = register.status
        
        if accepted_items == 0:
            # No items accepted, keep as SUBMITTED
            new_status = RiskStatus.SUBMITTED
        elif accepted_items == total_items:
            # All items accepted
            new_status = RiskStatus.ACCEPTED
        else:
            # Some items accepted
            new_status = RiskStatus.PARTIALLY_ACCEPTED
        
        if old_status != new_status:
            register.status = new_status
            register.save()
            
            # Log register status change
            AuditLogEntry.objects.create(
                audit_log=register.dossier.audit_log,
                user=self.request.user,
                action_type=AuditActionType.STATUS_CHANGED,
                detail={
                    'entity': 'RiskRegister',
                    'old_status': old_status,
                    'new_status': new_status,
                    'reason': f'{accepted_items}/{total_items} items resolved'
                }
            )
            
            # If register is fully accepted, update dossier to PRET_VALIDATION
            if new_status == RiskStatus.ACCEPTED:
                dossier = register.dossier
                old_dossier_status = dossier.status
                dossier.status = DossierStatus.PRET_VALIDATION
                dossier.save()
                
                # Log dossier status change
                AuditLogEntry.objects.create(
                    audit_log=dossier.audit_log,
                    user=self.request.user,
                    action_type=AuditActionType.STATUS_CHANGED,
                    detail={
                        'entity': 'Dossier',
                        'old_status': old_dossier_status,
                        'new_status': DossierStatus.PRET_VALIDATION,
                        'reason': 'All risk items resolved, ready for validation'
                    }
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
        dossier_id = self.get_dossier_id_from_url()
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
        dossier_id = self.get_dossier_id_from_url()
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
            queryset = AuditLog.objects.filter(dossier__am=user)  # Fixed: was "objectsfilter"
        
        # Filter by dossier_id if provided in nested URL
        dossier_id = self.get_dossier_id_from_url()
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
    - Create/Update/Delete: ADMIN and SO can manage
    """
    queryset = QuestionnaireTemplate.objects.all().order_by('-updated_at')
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        """Use different serializers based on action"""
        if self.action in ['list']:
            return QuestionnaireTemplateSimpleSerializer
        return QuestionnaireTemplateSerializer
    
    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'available', 'with_questions']:
            # Everyone can view published templates
            permission_classes = [permissions.IsAuthenticated]
        else:
            # Admin and SO can create/update/delete
            permission_classes = [permissions.IsAuthenticated]
        return [permission() for permission in permission_classes]
    
    def check_object_permissions(self, request, obj):
        """Check if user can modify templates"""
        if request.method in permissions.SAFE_METHODS:
            # Anyone authenticated can view
            return super().check_object_permissions(request, obj)
        
        # Only Admin and SO can modify
        user = request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can modify templates")
        
        return super().check_object_permissions(request, obj)
    
    def get_queryset(self):
        user = self.request.user
        if user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO:
            # Admin and SO see all templates
            return QuestionnaireTemplate.objects.all().order_by('-updated_at')
        else:
            # Others see only published templates
            return QuestionnaireTemplate.objects.filter(status=QuestionnaireStatus.PUBLISHED).order_by('-updated_at')
    
    def perform_create(self, serializer):
        """Set the creator when creating a template"""
        # Check permission
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can create templates")
        
        serializer.save(created_by=user)
    
    def perform_update(self, serializer):
        """Check permission before updating"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can update templates")
        
        serializer.save()
    
    def perform_destroy(self, instance):
        """Check permission before deleting"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can delete templates")
        
        instance.delete()
    
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
        Get template with all its questions for answering or editing.
        Used when AM selects a template and needs to see all questions,
        or when Admin/SO edits a template.
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
            permission_classes = [permissions.IsAuthenticated]
        return [permission() for permission in permission_classes]
    
    def check_object_permissions(self, request, obj):
        """Check if user can modify questions"""
        if request.method in permissions.SAFE_METHODS:
            return super().check_object_permissions(request, obj)
        
        # Only Admin and SO can modify
        user = request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can modify questions")
        
        return super().check_object_permissions(request, obj)
    
    def perform_create(self, serializer):
        """Check permission before creating"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can create questions")



        serializer.save()
    
    def perform_update(self, serializer):
        """Check permission before updating"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can update questions")
        
        serializer.save()
    
    def perform_destroy(self, instance):
        """Check permission before deleting"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN or user.role == Role.SO):
            raise PermissionDenied("Only Administrators and Security Officers can delete questions")
        
        instance.delete()
    
    def get_queryset(self):
        questionnaire_id = self.kwargs.get('questionnaire_id')
        if questionnaire_id:
            return Question.objects.filter(template_id=questionnaire_id).order_by('order')
        return Question.objects.all().order_by('order')


# ============================================================================
# 10. ENHANCED QuestionnaireAnswerViewSet
# ============================================================================

class QuestionnaireAnswerViewSet(DossierFilterMixin, viewsets.ModelViewSet):
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
        dossier_id = self.get_dossier_id_from_url()
        
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
        dossier_id = self.get_dossier_id_from_url()
        
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
        dossier_id = self.get_dossier_id_from_url()
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
            
            # IMPORTANT: Validate that the question belongs to dossier's template
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

    @action(detail=False, methods=['post'])
    def bulk_answer(self, request, dossier_id=None, dossier_pk=None):
        """
        Bulk create or update answers for a specific dossier.
        """
        # Handle different URL parameter names from nested routers vs manual paths
        target_dossier_id = dossier_id or dossier_pk
        
        # Get dossier_id from URL kwargs if not passed as argument
        if not target_dossier_id:
            target_dossier_id = self.kwargs.get('dossier_id') or self.kwargs.get('dossier_pk')
            
        # If still not found, check request data
        if not target_dossier_id:
            target_dossier_id = request.data.get('dossier_id')

        if not target_dossier_id:
             return Response({'error': 'Dossier ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dossier = Dossier.objects.get(id=target_dossier_id)
        except Dossier.DoesNotExist:
            return Response({'error': 'Dossier not found'}, status=status.HTTP_404_NOT_FOUND)

        # Permission checks
        if request.user.role == Role.SO:
             return Response(
                 {'error': "Security Officers cannot answer questions."}, 
                 status=status.HTTP_403_FORBIDDEN
             )
        
        if dossier.am != request.user and not (request.user.is_superuser or request.user.role == Role.ADMIN):
             return Response(
                 {'error': "You can only answer questions for your own dossiers."}, 
                 status=status.HTTP_403_FORBIDDEN
             )
             
        if dossier.status != DossierStatus.EN_EDITION:
            return Response(
                {'error': f"Cannot modify answers when dossier is in {dossier.status} status."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Prepare data
        data = request.data.copy()
        data['dossier_id'] = target_dossier_id

        # Initialize serializer with context to allow question filtering
        serializer = BulkQuestionnaireAnswerSerializer(data=data, context={'dossier': dossier})
        
        if serializer.is_valid():
            serializer.save()
            
            # Log the bulk update
            AuditLogEntry.objects.create(
                audit_log=dossier.audit_log,
                user=request.user,
                action_type=AuditActionType.QUESTIONNAIRE_SAVED,
                detail={
                    'action': 'bulk_update',
                    'count': len(data.get('answers', []))
                }
            )
            
            return Response({'status': 'Answers saved successfully'}, status=status.HTTP_200_OK)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _validate_bulk_answer_permissions(self, dossier, user):
        """Check if user has permission to answer questions for this dossier"""
        # Implement custom logic to validate bulk answer permissions if needed
        return True


# ============================================================================
# 11. HOME DASHBOARD
# ============================================================================

def home_dashboard(request):
    """Render home dashboard (placeholder for frontend)"""
    return render(request, 'core/dashboard.html')

# ============================================================================
# 12. NEW LoginView (Token Authentication)
# ============================================================================

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.status import HTTP_400_BAD_REQUEST, HTTP_200_OK
from rest_framework.authtoken.models import Token
from django.contrib.auth import get_user_model
from .serializers import LoginSerializer, UserSerializer

User = get_user_model()

class LoginView(APIView):
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        
        if serializer.is_valid():
            user = serializer.validated_data['user']
            token, created = Token.objects.get_or_create(user=user)
            # CHANGED: Pass request context to serializer to ensure absolute URLs for ImageFields
            user_serializer = UserSerializer(user, context={'request': request})
            
            return Response({
                'token': token.key,
                'user': user_serializer.data
            }, status=HTTP_200_OK)
        
        return Response(serializer.errors, status=HTTP_400_BAD_REQUEST)

# ============================================================================
# 13. NEW UserViewSet (Admin User Management)
# ============================================================================

class UserViewSet(viewsets.ModelViewSet):
    """
    ViewSet for user management (Admin only).
    Allows admins to create, view, update, and delete users.
    """
    queryset = User.objects.all().order_by('-date_joined')
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        """Use UserSerializer for all actions"""
        return UserSerializer
    
    def get_permissions(self):
        """Only admins can access this viewset"""
        return [permissions.IsAuthenticated()]
    
    def check_permissions(self, request):
        """Check if user is admin"""
        super().check_permissions(request)
        if not (request.user.is_superuser or request.user.role == Role.ADMIN):
            raise PermissionDenied("Only administrators can manage users")
    
    def get_queryset(self):
        """Only admins can see all users"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN):
            raise PermissionDenied("Only administrators can view users")
        return User.objects.all().order_by('-date_joined')
    
    def perform_create(self, serializer):
        """Create a new user"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN):
            raise PermissionDenied("Only administrators can create users")
        
        # Hash the password before saving
        password = serializer.validated_data.get('password')
        user_instance = serializer.save()
        if password:
            user_instance.set_password(password)
            user_instance.save()
    
    def perform_update(self, serializer):
        """Update user details"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN):
            raise PermissionDenied("Only administrators can update users")
        
        # If password is being updated, hash it
        password = serializer.validated_data.get('password')
        user_instance = serializer.save()
        if password:
            user_instance.set_password(password)
            user_instance.save()
    
    def perform_destroy(self, instance):
        """Delete a user"""
        user = self.request.user
        if not (user.is_superuser or user.role == Role.ADMIN):
            raise PermissionDenied("Only administrators can delete users")
        
        # Prevent deleting yourself
        if instance.id == user.id:
            raise serializers.ValidationError("You cannot delete your own account")
        
        instance.delete()
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get user statistics"""
        if not (request.user.is_superuser or request.user.role == Role.ADMIN):
            raise PermissionDenied("Only administrators can view statistics")
        
        total_users = User.objects.filter(is_active=True).count()
        am_count = User.objects.filter(role=Role.AM, is_active=True).count()
        so_count = User.objects.filter(role=Role.SO, is_active=True).count()
        admin_count = User.objects.filter(role=Role.ADMIN, is_active=True).count()
        
        return Response({
            'total_users': total_users,
            'am_count': am_count,
            'so_count': so_count,
            'admin_count': admin_count,
        })