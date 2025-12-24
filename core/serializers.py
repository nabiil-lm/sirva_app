# core/serializers.py
from rest_framework import serializers
from django.contrib.auth import get_user_model, authenticate
from .models import (
    Dossier, QuestionnaireTemplate, Question, QuestionnaireAnswer,
    ArchitectureDoc, RiskRegister, RiskItem, IaCheck, IaCrossCheck,
    AuditLog, AuditLogEntry, Role, DossierStatus, RiskStatus, RiskItemStatus
)

User = get_user_model()

class UserSerializer(serializers.ModelSerializer):
    role_display = serializers.CharField(source='get_role_display', read_only=True)
    
    class Meta:
        model = User
        fields = ('id', 'email', 'first_name', 'last_name', 'role', 'role_display')

class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(style={'input_type': 'password'}, trim_whitespace=False)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        if email and password:
            user = authenticate(request=self.context.get('request'), email=email, password=password)
            if not user:
                msg = 'Unable to log in with provided credentials.'
                raise serializers.ValidationError(msg, code='authorization')
        else:
            msg = 'Must include "email" and "password".'
            raise serializers.ValidationError(msg, code='authorization')

        attrs['user'] = user
        return attrs

class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = '__all__'

class QuestionnaireTemplateSimpleSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionnaireTemplate
        fields = ('id', 'name', 'description', 'question_count', 'status')

class QuestionnaireTemplateSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    
    class Meta:
        model = QuestionnaireTemplate
        fields = '__all__'

class QuestionnaireAnswerSerializer(serializers.ModelSerializer):
    class Meta:
        model = QuestionnaireAnswer
        fields = '__all__'
        read_only_fields = ('dossier',)

class BulkQuestionnaireAnswerSerializer(serializers.Serializer):
    dossier_id = serializers.IntegerField()
    answers = serializers.ListField(
        child=serializers.DictField(
            child=serializers.CharField(allow_blank=True)
        )
    )

    def create(self, validated_data):
        dossier_id = validated_data['dossier_id']
        answers_data = validated_data['answers']
        
        saved_answers = []
        for item in answers_data:
            question_id = item.get('question')
            answer_value = item.get('answer_value', '')
            
            answer, created = QuestionnaireAnswer.objects.update_or_create(
                dossier_id=dossier_id,
                question_id=question_id,
                defaults={'answer_value': answer_value}
            )
            saved_answers.append(answer)
            
        return saved_answers

class ArchitectureDocSerializer(serializers.ModelSerializer):
    file = serializers.FileField(write_only=True)

    class Meta:
        model = ArchitectureDoc
        fields = '__all__'
        read_only_fields = ('dossier', 'uploaded_at', 'size', 'mime_type', 'local_filepath', 'site_filepath', 'filename')

    def create(self, validated_data):
        validated_data.pop('file', None)
        return super().create(validated_data)

class RiskItemSerializer(serializers.ModelSerializer):
    owner_user = UserSerializer(read_only=True)
    delegated_to_user = UserSerializer(source='delegated_to', read_only=True)
    
    class Meta:
        model = RiskItem
        fields = '__all__'
        # IMPORTANT: owner_user and register must be read_only as they are set in perform_create
        read_only_fields = ('register', 'owner_user', 'status', 'created_at', 'updated_at', 'delegated_to', 'accepted_at', 'submitted_at', 'contest_refused', 'refused_by', 'contested_by', 'contested_at')

class RiskRegisterSerializer(serializers.ModelSerializer):
    items = RiskItemSerializer(many=True, read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    
    class Meta:
        model = RiskRegister
        fields = '__all__'
        read_only_fields = ('dossier', 'created_by', 'created_at', 'updated_at', 'submitted_at', 'accepted_at')

class IaCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = IaCheck
        fields = '__all__'

class IaCrossCheckSerializer(serializers.ModelSerializer):
    class Meta:
        model = IaCrossCheck
        fields = '__all__'

class AuditLogEntrySerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)
    
    class Meta:
        model = AuditLogEntry
        fields = '__all__'

class AuditLogSerializer(serializers.ModelSerializer):
    entries = AuditLogEntrySerializer(many=True, read_only=True)
    
    class Meta:
        model = AuditLog
        fields = '__all__'

class DossierSerializer(serializers.ModelSerializer):
    am = UserSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    questionnaire_template_name = serializers.CharField(source='questionnaire_template.name', read_only=True)
    
    class Meta:
        model = Dossier
        fields = '__all__'
        read_only_fields = ('am', 'status', 'is_submitted', 'created_at', 'updated_at', 'architecture_docs_submitted')

class DossierSubmitSerializer(serializers.Serializer):
    pass

class DossierStatusChangeSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=DossierStatus.choices)

class RiskItemActionSerializer(serializers.Serializer):
    ACTION_ACCEPT = 'accept'
    ACTION_DELEGATE = 'delegate'
    ACTION_CONTEST = 'contest'
    
    risk_item_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=[ACTION_ACCEPT, ACTION_DELEGATE, ACTION_CONTEST])
    delegate_user_email = serializers.EmailField(required=False)
    contest_reason = serializers.CharField(required=False)
    
    def validate(self, data):
        action = data.get('action')
        if action == self.ACTION_DELEGATE and not data.get('delegate_user_email'):
            raise serializers.ValidationError("delegate_user_email is required for delegate action")
        if action == self.ACTION_CONTEST and not data.get('contest_reason'):
            raise serializers.ValidationError("contest_reason is required for contest action")
            
        # Validate risk item exists
        try:
            risk_item = RiskItem.objects.get(id=data['risk_item_id'])
            data['risk_item'] = risk_item
        except RiskItem.DoesNotExist:
            raise serializers.ValidationError("Risk item not found")
            
        # Validate delegate user exists
        if action == self.ACTION_DELEGATE:
            try:
                user = User.objects.get(email=data['delegate_user_email'])
                data['delegate_user'] = user
            except User.DoesNotExist:
                raise serializers.ValidationError(f"User with email {data['delegate_user_email']} not found")
                
        return data

class RiskItemDelegationActionSerializer(serializers.Serializer):
    ACCEPT = 'accept'
    REFUSE = 'refuse'
    
    risk_item_id = serializers.IntegerField()
    action = serializers.ChoiceField(choices=[ACCEPT, REFUSE])
    
    def validate(self, data):
        try:
            risk_item = RiskItem.objects.get(id=data['risk_item_id'])
            data['risk_object'] = risk_item
        except RiskItem.DoesNotExist:
            raise serializers.ValidationError("Risk item not found")
            
        # Verify delegation
        user = self.context['request'].user
        if risk_item.delegated_to != user:
             raise serializers.ValidationError("This risk is not delegated to you")
             
        return data

class ContestedRiskActionSerializer(serializers.Serializer):
    contest_reason = serializers.CharField()

class SoContestReviewSerializer(serializers.Serializer):
    ACCEPT = 'accept'
    REFUSE = 'refuse'
    action = serializers.ChoiceField(choices=[ACCEPT, REFUSE])