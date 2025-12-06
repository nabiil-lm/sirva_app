from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Dossier, AuditLog, AuditLogEntry, AuditActionType

@receiver(post_save, sender=Dossier)
def create_audit_log_for_dossier(sender, instance, created, **kwargs):
    """Create an AuditLog when a Dossier is created."""
    if created:
        audit_log = AuditLog.objects.create(dossier=instance)
        # Log the creation action
        AuditLogEntry.objects.create(
            audit_log=audit_log,
            user=instance.am,
            action_type=AuditActionType.DOSSIER_CREATED,
            detail={'title': instance.title}
        )