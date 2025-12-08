from django.db.models.signals import post_save, m2m_changed
from django.dispatch import receiver
from .models import Dossier, QuestionnaireAnswer, AuditLogEntry, AuditActionType, AuditLog

@receiver(post_save, sender=Dossier)
def create_audit_log(sender, instance, created, **kwargs):
    """
    Automatically create AuditLog when a Dossier is created.
    """
    if created:
        AuditLog.objects.get_or_create(dossier=instance)


@receiver(post_save, sender=Dossier)
def create_questionnaire_answers(sender, instance, created, **kwargs):
    """
    When a dossier is created, create QuestionnaireAnswer records
    for all questions in the selected questionnaire template.
    """
    # Only process if questionnaire_template is set and has questions
    if instance.questionnaire_template and instance.questionnaire_template.questions.exists():
        # Get all questions from the template
        questions = instance.questionnaire_template.questions.all()
        
        # Create QuestionnaireAnswer for each question if it doesn't exist
        for question in questions:
            QuestionnaireAnswer.objects.get_or_create(
                dossier=instance,
                question=question,
                defaults={'answer_value': ''}
            )
        
        # Log to audit
        try:
            audit_log = instance.audit_log
            AuditLogEntry.objects.create(
                audit_log=audit_log,
                user=None,
                action_type=AuditActionType.QUESTIONNAIRE_SAVED,
                detail={
                    'template_name': instance.questionnaire_template.name,
                    'question_count': questions.count()
                }
            )
        except Exception:
            pass  # AuditLog might not exist yet


@receiver(post_save, sender=Dossier)
def update_questionnaire_answers_on_template_change(sender, instance, created, update_fields, **kwargs):
    """
    When dossier template is updated, add any new questions to answers.
    """
    if created or not update_fields or 'questionnaire_template_id' not in update_fields:
        return
    
    if instance.questionnaire_template:
        questions = instance.questionnaire_template.questions.all()
        
        # Create missing QuestionnaireAnswer records
        for question in questions:
            QuestionnaireAnswer.objects.get_or_create(
                dossier=instance,
                question=question,
                defaults={'answer_value': ''}
            )