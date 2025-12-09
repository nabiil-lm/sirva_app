"""
IA2 (Cross-check) Analysis Service
Compares questionnaire answers with architecture documents using Gemini AI
"""
import logging
import os
import time
import subprocess
from django.conf import settings
import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable, InvalidArgument
from ..models import Dossier, QuestionnaireAnswer, ArchitectureDoc

logger = logging.getLogger(__name__)

# REMOVED: Top-level configuration that was causing the issue
# genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# French prompt for security audit
IA2_AUDIT_PROMPT = """Tu es un auditeur cybersécurité. Compare ce questionnaire de sécurité (ci-dessus) avec les documents d'architecture technique fournis.

Tâche :
1. Analyse les documents d'architecture fournis.
2. Compare-les avec les réponses du questionnaire.
3. Signale toute incohérence majeure (ex: chiffrement annoncé mais absent, zones DMZ manquantes, flux non couverts).
4. Si l'architecture supporte les réponses, confirme la cohérence.

Format de réponse :
Commence OBLIGATOIREMENT par la phrase "Secure Score: X" (X = 0-100).
Ensuite, liste les points d'incohérence ou de validation.
"""

def _configure_genai():
    """
    Load API key from .env and configure Gemini.
    This ensures we always use the latest key, matching IA1's behavior.
    """
    # 1. Try getting from environment
    api_key = os.environ.get('GEMINI_API_KEY')
    
    # 2. If not found or likely stale, try loading from .env
    if not api_key:
        try:
            from dotenv import load_dotenv
            env_path = os.path.join(settings.BASE_DIR, '.env')
            if os.path.exists(env_path):
                load_dotenv(env_path, override=True) # Force reload
                api_key = os.environ.get('GEMINI_API_KEY')
        except ImportError:
            pass
            
    if api_key:
        genai.configure(api_key=api_key)
    else:
        logger.error("GEMINI_API_KEY not found in environment or .env file")

def compress_pdf(file_path):
    """
    Compress PDF using ghostscript to reduce file size and token usage.
    Returns path to compressed file or original if compression fails.
    """
    try:
        # Check if ghostscript is installed
        try:
            subprocess.run(['gs', '-v'], capture_output=True, check=True)
        except (FileNotFoundError, subprocess.CalledProcessError):
            logger.warning("Ghostscript not found. Install with: sudo apt-get install ghostscript")
            return file_path

        compressed_path = file_path.replace('.pdf', '_compressed.pdf')
        
        # Ghostscript command for ebook quality (150 dpi)
        cmd = [
            'gs',
            '-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.4',
            '-dPDFSETTINGS=/ebook', 
            '-dNOPAUSE',
            '-dQUIET',
            '-dBATCH',
            f'-sOutputFile={compressed_path}',
            file_path
        ]
        
        subprocess.run(cmd, check=True, capture_output=True)
        
        if os.path.exists(compressed_path):
            original_size = os.path.getsize(file_path)
            new_size = os.path.getsize(compressed_path)
            logger.info(f"PDF Compressed: {original_size/1024/1024:.2f}MB -> {new_size/1024/1024:.2f}MB")
            return compressed_path
            
    except Exception as e:
        logger.warning(f"PDF compression failed: {e}")
    
    return file_path

def prepare_questionnaire_text(dossier_id):
    """
    Prepare questionnaire answers as formatted text for Gemini
    """
    try:
        answers = QuestionnaireAnswer.objects.filter(dossier_id=dossier_id).select_related('question')
        questionnaire_text = "=== QUESTIONNAIRE ANSWERS ===\n\n"
        for i, answer in enumerate(answers, 1):
            questionnaire_text += f"Q{i}: {answer.question.text}\n"
            questionnaire_text += f"A: {answer.answer_value}\n\n"
        return questionnaire_text
    except Exception as e:
        logger.error(f"Error preparing questionnaire text: {str(e)}")
        return ""

def run_ia2_analysis(dossier_id):
    """
    Run IA2 analysis using Gemini AI with File API, Compression, and Retry Logic
    """
    # Ensure configuration is fresh before starting
    _configure_genai()
    
    uploaded_files = []
    temp_files_to_cleanup = []
    
    try:
        logger.info(f"Starting IA2 analysis for dossier {dossier_id}")
        
        # 1. Get Dossier and Data
        try:
            dossier = Dossier.objects.get(id=dossier_id)
        except Dossier.DoesNotExist:
            return {'error': True, 'analysis_text': 'Dossier not found', 'secure_score': 0, 'is_coherent': False}
        
        questionnaire_text = prepare_questionnaire_text(dossier_id)
        architecture_docs = dossier.architecture_docs.all()
        
        if not architecture_docs.exists():
            return {'error': True, 'analysis_text': 'No architecture documents found', 'secure_score': 0, 'is_coherent': False}

        # 2. Compress and Upload Files
        for doc in architecture_docs:
            if os.path.exists(doc.local_filepath):
                # Attempt compression
                file_to_upload = compress_pdf(doc.local_filepath)
                
                # Track if we created a new temp file to delete it later
                if file_to_upload != doc.local_filepath:
                    temp_files_to_cleanup.append(file_to_upload)

                logger.info(f"Uploading {os.path.basename(file_to_upload)} to Gemini...")
                try:
                    gemini_file = genai.upload_file(
                        path=file_to_upload,
                        mime_type='application/pdf',
                        display_name=doc.filename
                    )
                    uploaded_files.append(gemini_file)
                except Exception as e:
                    logger.error(f"Failed to upload {doc.filename}: {e}")

        if not uploaded_files:
            return {'error': True, 'analysis_text': 'Failed to upload any documents', 'secure_score': 0, 'is_coherent': False}

        # 3. Construct Prompt
        prompt_parts = [questionnaire_text, IA2_AUDIT_PROMPT] + uploaded_files
        
        # Use the model you specified
        model = genai.GenerativeModel('gemini-2.5-flash')

        # 4. Call API with Retry Logic
        max_retries = 3
        response = None
        
        for attempt in range(max_retries):
            try:
                logger.info(f"Sending request to Gemini (Attempt {attempt + 1}/{max_retries})...")
                response = model.generate_content(prompt_parts)
                break 
            except (ResourceExhausted, ServiceUnavailable) as e:
                wait_time = (attempt + 1) * 20
                logger.warning(f"Quota exceeded. Retrying in {wait_time}s... Error: {e}")
                time.sleep(wait_time)
            except InvalidArgument as e:
                # This catches API key errors specifically
                logger.error(f"API Key or Argument Error: {e}")
                return {'error': True, 'analysis_text': f'API Configuration Error: {str(e)}', 'secure_score': 0, 'is_coherent': False}
            except Exception as e:
                logger.error(f"Unexpected API error: {e}")
                break

        if not response:
            return {'error': True, 'analysis_text': 'API request failed after retries', 'secure_score': 0, 'is_coherent': False}

        # 5. Process Response
        analysis_text = response.text
        secure_score = extract_secure_score(analysis_text)
        is_coherent = secure_score >= 50
        
        logger.info(f"IA2 Success: Score={secure_score}")
        
        return {
            'secure_score': secure_score,
            'is_coherent': is_coherent,
            'analysis_text': analysis_text,
            'raw_response': analysis_text,
            'error': False
        }

    except Exception as e:
        logger.error(f"Critical error in IA2 analysis: {str(e)}", exc_info=True)
        return {'error': True, 'analysis_text': f'System error: {str(e)}', 'secure_score': 0, 'is_coherent': False}
    
    finally:
        # 6. Cleanup Remote Files
        for f in uploaded_files:
            try:
                f.delete()
            except Exception:
                pass
        
        # 7. Cleanup Local Compressed Files
        for f in temp_files_to_cleanup:
            try:
                if os.path.exists(f):
                    os.remove(f)
            except Exception:
                pass

def extract_secure_score(analysis_text):
    """Extract secure score from Gemini response"""
    try:
        import re
        match = re.search(r'Secure Score:\s*(\d+)', analysis_text, re.IGNORECASE)
        if match:
            return min(max(int(match.group(1)), 0), 100)
    except Exception:
        pass
    return 0
