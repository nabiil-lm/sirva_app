# core/serializers.py
from rest_framework import serializers
from .models import (
    Dossier, User, DossierStatus, Role, 
    IaCheck, IaCrossCheck, IaStatus,
    RiskRegister, RiskItem, RiskStatus, RiskItemStatus,
    ArchitectureDoc, AuditLog, AuditLogEntry, AuditActionType,
    QuestionnaireTemplate, Question, QuestionnaireAnswer, QuestionType, QuestionnaireStatus
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
    
    # CHANGED: Use PrimaryKeyRelatedField for dropdown in browsable API
    questionnaire_template = serializers.PrimaryKeyRelatedField(
        queryset=QuestionnaireTemplate.objects.filter(status=QuestionnaireStatus.PUBLISHED),
        required=False,
        allow_null=True,
        label="Questionnaire Template",
        help_text="Select a published questionnaire template for this dossier"
    )
    
    questionnaire_template_name = serializers.CharField(
        source='questionnaire_template.name',
        read_only=True,
        required=False,
        allow_null=True
    )
    questionnaire_template_display = serializers.SerializerMethodField(read_only=True)
    available_templates = serializers.SerializerMethodField(read_only=True)
    
    # NEW: SO email field for assignment
    responsible_so_email = serializers.EmailField(
        write_only=True,
        required=False,
        allow_blank=True,
        label="Responsible Security Officer Email",
        help_text="Email of the SO responsible for this dossier"
    )
    
    # NEW: SO display field (read-only)
    responsible_so = UserSerializer(read_only=True)

    class Meta:
        model = Dossier
        fields = [
            'id', 'title', 'status', 'status_display', 'am',
            'questionnaire_template', 'questionnaire_template_name',
            'questionnaire_template_display', 'available_templates',
            'responsible_so', 'responsible_so_email',
            'is_submitted', 'created_at', 'updated_at'
        ]
        read_only_fields = ['status', 'is_submitted', 
                           'questionnaire_template_display', 'available_templates', 'responsible_so']

    def validate_title(self, value):
        if len(value) < 5:
            raise serializers.ValidationError("Le titre doit contenir au moins 5 caractères.")
        return value
    
    def validate_responsible_so_email(self, value):
        """Validate that the email belongs to an existing SO"""
        if not value:
            return value
        
        try:
            user = User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(f"No user found with email: {value}")
        
        # Check if user has SO role
        if user.role != Role.SO:
            raise serializers.ValidationError(f"User {value} is not a Security Officer")
        
        return value
    
    def get_questionnaire_template_display(self, obj):
        """Return full template info for display"""
        if obj.questionnaire_template:
            return {
                'id': obj.questionnaire_template.id,
                'name': obj.questionnaire_template.name,
                'description': obj.questionnaire_template.description,
                'question_count': obj.questionnaire_template.question_count
            }
        return None
    
    def get_available_templates(self, obj):
        """Return list of available templates for dropdown selection"""
        published_templates = QuestionnaireTemplate.objects.filter(
            status=QuestionnaireStatus.PUBLISHED
        )
        return QuestionnaireTemplateSimpleSerializer(published_templates, many=True).data
    
    def create(self, validated_data):
        """Custom create method to handle questionnaire_template and SO email"""
        # Extract SO email from validated_data
        so_email = validated_data.pop('responsible_so_email', None)
        
        # Create dossier
        dossier = Dossier.objects.create(**validated_data)
        
        # Assign SO if email was provided
        if so_email:
            try:
                so_user = User.objects.get(email=so_email, role=Role.SO)
                dossier.responsible_so = so_user
                dossier.save()
            except User.DoesNotExist:
                pass  # Already validated in validate_responsible_so_email
        
        return dossier

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
    # NEW: Add file upload field
    file = serializers.FileField(
        write_only=True,
        required=True,
        label="PDF Document",
        help_text="Upload a PDF file (max 50MB)"
    )
    
    # NEW: Add RSSI confirmation field (must be checked to upload)
    rssi_confirmed = serializers.BooleanField(
        required=True,
        label="RSSI Confirmation",
        help_text="Confirm that this document has been reviewed by RSSI (required)"
    )
    
    submit_documents = serializers.BooleanField(
        write_only=True,
        required=False,
        default=False,
        help_text="Check this box to submit all documents and lock further uploads"
    )
    
    class Meta:
        model = ArchitectureDoc
        fields = [
            'id', 'file', 'filename', 'local_filepath', 'site_filepath', 'rssi_confirmed',
            'mime_type', 'size', 'uploaded_at', 'submit_documents'
        ]
        read_only_fields = ['id', 'uploaded_at', 'filename', 'local_filepath', 'site_filepath', 'mime_type', 'size']
    
    def validate_file(self, value):
        """
        Validate that uploaded file is a PDF.
        - Check file extension
        - Check MIME type
        - Check file size (max 50MB)
        """
        # Check file size (50MB max)
        max_size = 50 * 1024 * 1024  # 50MB in bytes
        if value.size > max_size:
            raise serializers.ValidationError(
                f"File size exceeds 50MB limit. Current size: {value.size / (1024*1024):.2f}MB"
            )
        
        # Check file extension
        filename = value.name.lower()
        if not filename.endswith('.pdf'):
            raise serializers.ValidationError(
                "Only PDF files are allowed. Please upload a .pdf file."
            )
        
        # Check MIME type
        if value.content_type not in ['application/pdf', 'application/x-pdf']:
            raise serializers.ValidationError(
                "Invalid file type. Only PDF files are allowed."
            )
        
        return value
    
    def validate_rssi_confirmed(self, value):
        """
        NEW: Validate that RSSI confirmation is checked.
        """
        if not value:
            raise serializers.ValidationError(
                "RSSI confirmation is mandatory. You must confirm that this document has been reviewed by RSSI."
            )
        return value
    
    def create(self, validated_data):
        """
        Override create to handle the write-only file field.
        The file is validated but not passed to the model.
        File metadata (filename, mime_type, size, local_filepath, site_filepath) is set by the view.
        """
        # Remove file from validated_data since it's write-only
        validated_data.pop('file', None)
        
        # Remove the submit_documents field as it's not a model field
        validated_data.pop('submit_documents', None)
        
        # Create the ArchitectureDoc instance
        return ArchitectureDoc.objects.create(**validated_data)

# Sérialiseur pour RiskItem
class RiskItemSerializer(serializers.ModelSerializer):
    owner_user = UserSerializer(read_only=True)
    owner_user_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.all(), source='owner_user', write_only=True, required=False
    )
    delegated_to = UserSerializer(read_only=True)
    
    # NEW: Delegation email field (write-only)
    delegated_to_email = serializers.EmailField(
        write_only=True,
        required=False,
        allow_blank=True,
        label="Delegate To Email",
        help_text="Email of user to delegate this risk to"
    )
    
    likelihood_display = serializers.CharField(source='get_likelihood_display', read_only=True)
    impact_display = serializers.CharField(source='get_impact_display', read_only=True)
    level_display = serializers.CharField(source='get_level_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    contested_by_user = UserSerializer(source='contested_by', read_only=True)
    refused_by_users = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = RiskItem
        fields = [
            'id', 'register', 'owner_user', 'owner_user_id', 
            'delegated_to', 'delegated_to_email',
            'title', 'description', 
            'likelihood', 'likelihood_display',
            'impact', 'impact_display',
            'level', 'level_display',
            'mitigation', 'status', 'status_display',
            'contested_by_user', 'contested_at', 'contestation_reason',
            'refused_by_users',
            'accepted_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['accepted_at', 'created_at', 'updated_at', 'contested_by_user', 'refused_by_users']
    
    def get_refused_by_users(self, obj):
        """Get user details for users who refused this delegation"""
        if not obj.refused_by:
            return []
        users = User.objects.filter(id__in=obj.refused_by)
        return UserSerializer(users, many=True).data
    
    def validate_delegated_to_email(self, value):
        """Validate delegation email"""
        if not value:
            return value
        
        try:
            User.objects.get(email=value)
        except User.DoesNotExist:
            raise serializers.ValidationError(f"No user found with email: {value}")
        
        return value

    def create(self, validated_data):
        """
        Override create to handle the write-only delegated_to_email field.
        Convert email to user object before creating the RiskItem.
        """
        # Extract and remove delegated_to_email from validated_data
        delegated_to_email = validated_data.pop('delegated_to_email', None)
        
        # If delegated_to_email was provided, resolve it to a user
        if delegated_to_email:
            try:
                delegated_user = User.objects.get(email=delegated_to_email)
                validated_data['delegated_to'] = delegated_user
            except User.DoesNotExist:
                pass  # Already validated in validate_delegated_to_email
        
        # Create the RiskItem instance
        return RiskItem.objects.create(**validated_data)

# Sérialiseur pour RiskRegister
class RiskRegisterSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    items = RiskItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    total_items = serializers.IntegerField(read_only=True)
    accepted_items = serializers.IntegerField(read_only=True)
    
    # EXPLICIT: ChoiceField for dropdown in browsable API (MUST come before Meta)
    status = serializers.ChoiceField(
        choices=RiskStatus.choices,
        label="Statut du Registre de Risques",
        help_text="Sélectionnez le statut du registre (Brouillon, Soumis à acceptation, Partiellement accepté, Accepté)"
    )

    class Meta:
        model = RiskRegister
        fields = [
            'id', 'dossier', 'created_by', 'status', 'status_display',
            'items', 'total_items', 'accepted_items',
            'submitted_at', 'accepted_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'dossier', 'created_by', 'submitted_at', 'accepted_at', 'created_at', 'updated_at']

    def validate_status(self, value):
        """
        Validate status transitions.
        Only allow transitions to SUBMITTED if there are items in the register.
        """
        # If this is a create operation, status will be set by the view
        if self.instance is not None:
            current_status = self.instance.status
            
            # Only validate if status is actually changing
            if value != current_status:
                # Validate transition to SUBMITTED
                if value == RiskStatus.SUBMITTED and self.instance.items.count() == 0:
                    raise serializers.ValidationError(
                        "Cannot submit a risk register with no risk items"
                    )
        
        return value

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

class QuestionSerializer(serializers.ModelSerializer):
    """Serializer for individual questions"""
    class Meta:
        model = Question
        fields = ['id', 'order', 'text', 'question_type', 'is_mandatory', 'choices_json', 'help_text']


class QuestionnaireTemplateSerializer(serializers.ModelSerializer):
    """Serializer for questionnaire templates with embedded questions"""
    questions = QuestionSerializer(many=True, read_only=True)
    question_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = QuestionnaireTemplate
        fields = ['id', 'name', 'description', 'status', 'questions', 'question_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']


class QuestionnaireTemplateSimpleSerializer(serializers.ModelSerializer):
    """Simple serializer for listing templates in dropdown"""
    question_count = serializers.IntegerField(read_only=True)
    
    class Meta:
        model = QuestionnaireTemplate
        fields = ['id', 'name', 'description', 'question_count', 'status']
        read_only_fields = ['created_at', 'updated_at']


class QuestionnaireAnswerSerializer(serializers.ModelSerializer):
    """Serializer for questionnaire answers"""
    question_text = serializers.CharField(source='question.text', read_only=True)
    question_order = serializers.IntegerField(source='question.order', read_only=True)
    question_type = serializers.CharField(source='question.question_type', read_only=True)
    is_mandatory = serializers.BooleanField(source='question.is_mandatory', read_only=True)
    
    class Meta:
        model = QuestionnaireAnswer
        fields = ['id', 'question', 'question_text', 'question_order', 'question_type', 'is_mandatory', 'answer_value', 'answered_at']
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Get dossier from context (passed by the view)
        dossier = self.context.get('dossier')
        
        if dossier and dossier.questionnaire_template:
            # Filter question queryset to only show questions from the assigned template
            self.fields['question'] = serializers.PrimaryKeyRelatedField(
                queryset=Question.objects.filter(template=dossier.questionnaire_template),
                label="Question",
                help_text=f"Select a question from {dossier.questionnaire_template.name}"
            )
        else:
            # Fallback if no template assigned
            self.fields['question'] = serializers.PrimaryKeyRelatedField(
                queryset=Question.objects.none(),
                label="Question",
                help_text="No questionnaire template assigned to this dossier"
            )
    
    def _validate_true_false(self, value):
        """Validate TRUE_FALSE question answers"""
        if value not in ['true', 'false', 'True', 'False', True, False]:
            raise serializers.ValidationError("TRUE_FALSE answers must be 'true' or 'false'")
    
    def _validate_single_choice(self, value, allowed_choices):
        """Validate SINGLE_CHOICE question answers"""
        if not value:
            raise serializers.ValidationError("Choice cannot be empty")
        if value not in allowed_choices:
            raise serializers.ValidationError(f"Invalid choice. Must be one of: {allowed_choices}")
    
    def _validate_multiple_choice(self, value, allowed_choices):
        """Validate MULTIPLE_CHOICE question answers"""
        if not value:
            raise serializers.ValidationError("Choice cannot be empty")
        
        selected = value.split(',') if isinstance(value, str) else value
        for choice in selected:
            if choice.strip() not in allowed_choices:
                raise serializers.ValidationError(f"Invalid choice: {choice}")
    
    def validate_answer_value(self, value):
        """Validate answer based on question type"""
        question_id = self.initial_data.get('question')
        if not question_id:
            return value
        
        try:
            question = Question.objects.get(id=question_id)
            
            if question.question_type == QuestionType.TRUE_FALSE:
                self._validate_true_false(value)
            elif question.question_type == QuestionType.SINGLE_CHOICE:
                self._validate_single_choice(value, question.choices_json or [])
            elif question.question_type == QuestionType.MULTIPLE_CHOICE:
                self._validate_multiple_choice(value, question.choices_json or [])
        
        except Question.DoesNotExist:
            pass
        
        return value


class BulkQuestionnaireAnswerSerializer(serializers.Serializer):
    """Serializer for bulk answer submission"""
    answers = QuestionnaireAnswerSerializer(many=True)
    dossier_id = serializers.IntegerField(write_only=True)
    
    def create(self, validated_data):
        """Bulk create or update answers"""
        dossier_id = validated_data.pop('dossier_id')
        answers_data = validated_data.get('answers', [])
        
        created_answers = []
        for answer_data in answers_data:
            question_id = answer_data.get('question')
            answer_value = answer_data.get('answer_value')
            
            answer, _ = QuestionnaireAnswer.objects.update_or_create(
                dossier_id=dossier_id,
                question_id=question_id,
                defaults={'answer_value': answer_value}
            )
            created_answers.append(answer)
        
        return created_answers

class DossierSubmitSerializer(serializers.Serializer):
    """
    Serializer for dossier submission.
    No fields needed - just accepts POST with empty body.
    This removes all form fields from the browsable API view.
    """
    pass

class RiskItemActionSerializer(serializers.Serializer):
    """
    Serializer for AM to perform actions on existing risk items
    (Accept, Delegate, or Contest)
    """
    ACTION_ACCEPT = 'accept'
    ACTION_DELEGATE = 'delegate'
    ACTION_CONTEST = 'contest'
    
    ACTION_CHOICES = [
        (ACTION_ACCEPT, 'Accept'),
        (ACTION_DELEGATE, 'Delegate'),
        (ACTION_CONTEST, 'Contest'),
    ]
    
    risk_item = serializers.PrimaryKeyRelatedField(
        queryset=RiskItem.objects.all(),
        help_text="Select a risk item to perform action on"
    )
    action = serializers.ChoiceField(
        choices=ACTION_CHOICES,
        help_text="Choose action: Accept, Delegate, or Contest"
    )
    delegate_user = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(role=Role.AM),
        required=False,
        allow_null=True,
        help_text="Email of user to delegate to (required for Delegate action)"
    )
    contest_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Reason for contesting (required for Contest action)"
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        # Dynamically filter risk_item queryset to only show items in the current register
        request = self.context.get('request')
        register = self.context.get('register')
        
        if register:
            # Only show risk items from this specific register
            self.fields['risk_item'].queryset = register.items.all()
    
    def validate(self, data):
        """Validate based on action type"""
        action = data.get('action')
        
        if action == self.ACTION_DELEGATE:
            if not data.get('delegate_user'):
                raise serializers.ValidationError("delegate_user is required for Delegate action")
        
        if action == self.ACTION_CONTEST:
            if not data.get('contest_reason'):
                raise serializers.ValidationError("contest_reason is required for Contest action")
        
        return data

class RiskItemDelegationActionSerializer(serializers.Serializer):
    """
    Serializer for delegation recipients to accept or refuse risk items.
    Only shows risk items delegated to the user.
    """
    ACCEPT = 'accept'
    REFUSE = 'refuse'
    ACTION_CHOICES = (
        (ACCEPT, 'Accepter'),
        (REFUSE, 'Refuser'),
    )
    
    risk_item = serializers.ChoiceField(
        choices=[],
        label="Risque délégué",
        help_text="Sélectionnez le risque délégué à traiter"
    )
    action = serializers.ChoiceField(
        choices=ACTION_CHOICES,
        label="Action",
        help_text="Accepter ou Refuser ce risque",
        style={'base_template': 'radio.html'}  # NEW: Forces radio buttons instead of dropdown
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        user = self.context.get('request').user if self.context.get('request') else None
        register = self.context.get('register')
        
        if not user or not register:
            return
        
        # Only show items delegated to this user
        delegated_items = register.items.filter(
            delegated_to=user,
            status=RiskItemStatus.DELEGATED_PENDING
        ).order_by('title')
        
        choices = [(str(item.id), f"{item.title} ({item.level})") for item in delegated_items]
        self.fields['risk_item'].choices = choices
    
    def validate(self, attrs):
        """Validate that the risk item exists and is delegated to the user"""
        user = self.context.get('request').user
        register = self.context.get('register')
        risk_id = attrs.get('risk_item')
        
        try:
            risk = RiskItem.objects.get(
                id=int(risk_id),
                register=register,
                delegated_to=user,
                status=RiskItemStatus.DELEGATED_PENDING
            )
        except RiskItem.DoesNotExist:
            raise serializers.ValidationError(
                {'risk_item': "Ce risque n'est pas délégué à vous ou a déjà été traité."}
            )
        
        attrs['risk_object'] = risk
        return attrs

class ContestedRiskActionSerializer(serializers.Serializer):
    """
    Serializer for SO to accept or reject contested risk items.
    Only shows contested risk items.
    """
    ACCEPT = 'accept'
    REJECT = 'reject'
    ACTION_CHOICES = (
        (ACCEPT, 'Accepter la contestation (Supprimer le risque)'),
        (REJECT, 'Rejeter la contestation (Retour en attente)'),
    )
    
    risk_item = serializers.ChoiceField(
        choices=[],
        label="Risque contesté",
        help_text="Sélectionnez le risque contesté à traiter"
    )
    action = serializers.ChoiceField(
        choices=ACTION_CHOICES,
        label="Décision",
        help_text="Accepter (supprime le risque) ou Rejeter (retour en attente)",
        style={'base_template': 'radio.html'}
    )
    rejection_reason = serializers.CharField(
        required=False,
        allow_blank=True,
        label="Raison du rejet",
        help_text="Expliquez pourquoi vous rejetez la contestation (obligatoire si vous rejetez)",
        style={'base_template': 'textarea.html', 'rows': 4}
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        register = self.context.get('register')
        
        if not register:
            return
        
        # Only show contested items
        contested_items = register.items.filter(
            status=RiskItemStatus.CONTESTED
        ).order_by('title')
        
        choices = [
            (str(item.id), f"{item.title} ({item.level}) - Contesté par {item.contested_by.email if item.contested_by else 'Unknown'}: {item.contestation_reason[:50]}...")
            for item in contested_items
        ]
        self.fields['risk_item'].choices = choices
    
    def validate(self, attrs):
        """Validate the contestation decision"""
        action = attrs.get('action')
        rejection_reason = attrs.get('rejection_reason', '')
        
        # If rejecting, rejection reason is mandatory
        if action == self.REJECT and not rejection_reason.strip():
            raise serializers.ValidationError({
                'rejection_reason': "La raison du rejet est obligatoire lorsque vous rejetez une contestation."
            })
        
        # Validate that the risk item exists and is contested
        register = self.context.get('register')
        risk_id = attrs.get('risk_item')
        
        try:
            risk = RiskItem.objects.get(
                id=int(risk_id),
                register=register,
                status=RiskItemStatus.CONTESTED
            )
        except RiskItem.DoesNotExist:
            raise serializers.ValidationError({
                'risk_item': "Ce risque n'est pas contesté ou n'existe pas."
            })
        
        attrs['risk_object'] = risk
        return attrs

class DossierStatusChangeSerializer(serializers.Serializer):
    """Serializer for changing dossier status with dropdown choices"""
    status = serializers.ChoiceField(
        choices=DossierStatus.choices,
        help_text="Select a new status for this dossier"
    )
    
    class Meta:
        fields = ['status']