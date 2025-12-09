"""
Celery tasks for asynchronous operations.
Handles IA1 and IA2 analysis triggers.
"""
import logging
from celery import shared_task
from .services.ai_service import run_ia1_analysis, run_ia2_analysis
from .models import Dossier, DossierStatus, IaCheck, IaCrossCheck, QuestionnaireAnswer

logger = logging.getLogger(__name__)


@shared_task
def trigger_ia1_analysis(dossier_id, async_mode=False):
    """
    Trigger IA1 analysis on questionnaire answers.
    Validates questionnaire coherence and generates secure score.
    
    Args:
        dossier_id: ID of the dossier to analyze
        async_mode: If True, run asynchronously via Celery; if False, run synchronously
    
    Returns:
        dict with analysis results: {
            'secure_score': float (0-100),
            'is_coherent': bool,
            'message': str,
            'findings': dict
        }
    """
    try:
        logger.info(f"Starting IA1 analysis for dossier {dossier_id}")
        
        # Get the dossier
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            logger.error(f"Dossier {dossier_id} not found")
            return {
                'secure_score': 0,
                'is_coherent': False,
                'message': f'Dossier {dossier_id} not found',
                'error': True
            }
        
        # Run IA1 analysis via AI service
        result = run_ia1_analysis(dossier_id)
        
        # Create or update IaCheck record
        ia_check, created = IaCheck.objects.get_or_create(
            dossier=dossier,
            defaults={
                'status': 'COHERENT' if result.is_coherent else 'INCOHERENT',
                'secure_score': result.secure_score,
                'findings': {
                    'analysis': result.analysis_text,
                    'raw_response': result.raw_response
                }
            }
        )
        
        # If not created, update existing
        if not created:
            ia_check.status = 'COHERENT' if result.is_coherent else 'INCOHERENT'
            ia_check.secure_score = result.secure_score
            ia_check.findings = {
                'analysis': result.analysis_text,
                'raw_response': result.raw_response
            }
            ia_check.save()
        
        # Update dossier status based on IA1 result
        if result.is_coherent:
            dossier.status = DossierStatus.IA1_COHERENT
        else:
            dossier.status = DossierStatus.IA1_INCOHERENT
        dossier.save()
        
        logger.info(f"IA1 analysis complete for dossier {dossier_id}: Score={result.secure_score}, Coherent={result.is_coherent}")
        
        return {
            'secure_score': result.secure_score,
            'is_coherent': result.is_coherent,
            'message': 'IA1 analysis completed successfully',
            'error': False
        }
    
    except Exception as e:
        logger.error(f"Error in IA1 analysis task for dossier {dossier_id}: {str(e)}", exc_info=True)
        return {
            'secure_score': 0,
            'is_coherent': False,
            'message': f'Error during IA1 analysis: {str(e)}',
            'error': True
        }


@shared_task
def trigger_ia2_analysis(dossier_id, async_mode=False):
    """
    Trigger IA2 analysis (cross-check between questionnaire and architecture docs).
    Compares questionnaire answers with uploaded PDF architecture documents.
    
    Args:
        dossier_id: ID of the dossier to analyze
        async_mode: If True, run asynchronously via Celery; if False, run synchronously
    
    Returns:
        dict with analysis results: {
            'secure_score': float (0-100),
            'is_coherent': bool,
            'message': str,
            'findings': dict,
            'error': bool
        }
    """
    try:
        logger.info(f"Starting IA2 cross-check analysis for dossier {dossier_id}")
        
        # Get the dossier
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            logger.error(f"Dossier {dossier_id} not found")
            return {
                'secure_score': 0,
                'is_coherent': False,
                'message': f'Dossier {dossier_id} not found',
                'error': True
            }
        
        # Validate that dossier has architecture documents
        architecture_docs = dossier.architecture_docs.all()
        if not architecture_docs.exists():
            logger.error(f"No architecture documents found for dossier {dossier_id}")
            return {
                'secure_score': 0,
                'is_coherent': False,
                'message': 'No architecture documents uploaded',
                'error': True
            }
        
        # Get questionnaire answers
        questionnaire_answers = QuestionnaireAnswer.objects.filter(dossier=dossier)
        if not questionnaire_answers.exists():
            logger.error(f"No questionnaire answers found for dossier {dossier_id}")
            return {
                'secure_score': 0,
                'is_coherent': False,
                'message': 'No questionnaire answers found',
                'error': True
            }
        
        # Run IA2 analysis via AI service (this will handle PDF reading and Gemini integration)
        result = run_ia2_analysis(dossier_id)
        
        # Create or update IaCrossCheck record
        ia_cross_check, created = IaCrossCheck.objects.get_or_create(
            dossier=dossier,
            defaults={
                'status': 'COHERENT' if result.get('is_coherent') else 'INCOHERENT',
                'secure_score': result.get('secure_score', 0),
                'findings': {
                    'analysis': result.get('analysis_text', ''),
                    'inconsistencies': result.get('inconsistencies', []),
                    'raw_response': result.get('raw_response', '')
                }
            }
        )
        
        # If not created, update existing
        if not created:
            ia_cross_check.status = 'COHERENT' if result.get('is_coherent') else 'INCOHERENT'
            ia_cross_check.secure_score = result.get('secure_score', 0)
            ia_cross_check.findings = {
                'analysis': result.get('analysis_text', ''),
                'inconsistencies': result.get('inconsistencies', []),
                'raw_response': result.get('raw_response', '')
            }
            ia_cross_check.save()
        
        # Update dossier status based on IA2 result
        if result.get('is_coherent'):
            dossier.status = DossierStatus.IA2_COHERENT
        else:
            dossier.status = DossierStatus.IA2_INCOHERENT
        dossier.save()
        
        logger.info(f"IA2 analysis complete for dossier {dossier_id}: Score={result.get('secure_score')}, Coherent={result.get('is_coherent')}")
        
        return {
            'secure_score': result.get('secure_score', 0),
            'is_coherent': result.get('is_coherent', False),
            'message': 'IA2 cross-check analysis completed successfully',
            'error': False
        }
    
    except Exception as e:
        logger.error(f"Error in IA2 analysis task for dossier {dossier_id}: {str(e)}", exc_info=True)
        return {
            'secure_score': 0,
            'is_coherent': False,
            'message': f'Error during IA2 analysis: {str(e)}',
            'error': True
        }
