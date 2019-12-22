from django.db import transaction
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, permission_required

from allianceauth.authentication.models import CharacterOwnership
from allianceauth.eveonline.models import EveCharacter
from esi.decorators import token_required

from .models import *
from .utils import messages_plus
from . import tasks

@login_required
@permission_required('memberaudit.basic_access')
def index(request):
        
    context = {
        'text': 'Hello, World!'
    }    
    return render(request, 'memberaudit/index.html', context)

@login_required
@permission_required('memberaudit.basic_access')
@token_required(scopes=Owner.get_esi_scopes())
def add_owner(request, token):    
    token_char = EveCharacter.objects.get(character_id=token.character_id)
    
    success = True
    try:
        owned_char = CharacterOwnership.objects.get(
            user=request.user,
            character=token_char
        )        
    except CharacterOwnership.DoesNotExist:
        messages_plus.error(
            request,
            'You can add your main or alt characters.'
            + 'However, character <strong>{}</strong> is neither. '.format(
                token_char.character_name
            )
        )
        success = False
    
        
    with transaction.atomic():
        owner, created = Owner.objects.update_or_create(
            character=owned_char  
        )
        
    tasks.sync_owner.delay(            
        owner_pk=owner.pk,
        force_sync=True
    )        
    messages_plus.success(
        request,             
        '<strong>{}</strong> has been added '.format(owner)        
    )
    
    return redirect('memberaudit:index')