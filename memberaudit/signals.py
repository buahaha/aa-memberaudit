from django.db.models.signals import pre_save
from django.dispatch import receiver

from allianceauth.authentication.models import UserProfile
from allianceauth.services.hooks import get_extension_logger

from .models import ComplianceGroup

logger = get_extension_logger(__name__)

DEFAULT_TASK_PRIORITY = 6


@receiver(pre_save, sender=UserProfile)
def state_change(sender, instance, raw, using, update_fields, **kwargs):
    if instance.pk:
        old_instance = UserProfile.objects.get(pk=instance.pk)
        if old_instance.state != instance.state:
            logger.info(f"User {instance} is leaving {old_instance.state}")
            if ComplianceGroup.objects.filter(state=old_instance.state).exists():
                logger.info(
                    f"Removing {instance} from compliance group for state {old_instance.state}"
                )
                instance.user.groups.remove(old_instance.state.compliancegroup.group)
