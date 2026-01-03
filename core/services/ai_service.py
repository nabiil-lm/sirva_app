"""
AI Service for Gemini API integration.
Handles IA1 (questionnaire coherence) analysis.
"""
import os
import re
import json
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger(__name__)


@dataclass
class IA1AnalysisResult:
    """Result of IA1 analysis"""
    secure_score: int
    analysis_text: str
    findings: Dict[str, Any]  # Changed from just text to structured findings
    is_coherent: bool
    raw_response: str
    error: Optional[str] = None


class GeminiAIService:
    """Service for interacting with Google Gemini AI API"""
    
    # IA1 Prompt - Updated to request JSON structure
    IA1_PROMPT = """Tu es un auditeur cybersécurité expert. Analyse la cohérence interne des réponses à ce questionnaire de sécurité.
    
    Ta mission :
    1. Repérer les contradictions flagrantes entre les réponses.
    2. Identifier les omissions ou réponses trop vagues.
    3. Évaluer la vraisemblance des mesures techniques déclarées.
    
    Format de réponse OBLIGATOIRE :
    Tu dois répondre UNIQUEMENT avec un objet JSON valide respectant cette structure exacte (sans markdown ```json) :
    {
        "secure_score": <entier entre 0 et 100>,
        "summary": "<Résumé global de l'analyse en 2-3 phrases>",
        "strengths": ["<Point fort 1>", "<Point fort 2>", ...],
        "weaknesses": ["<Point faible/incohérence 1>", "<Point faible 2>", ...],
        "recommendations": ["<Recommandation 1>", "<Recommandation 2>", ...]
    }
    
    Le "secure_score" doit refléter la COHÉRENCE et la SÉRIEUX des réponses, pas nécessairement le niveau de sécurité absolu.
    """
    
    def __init__(self):
        """Initialize the Gemini AI service with API key from environment"""
        self.api_key = self._get_api_key()
        self.threshold = self._get_threshold()
        self._configure_genai()
    
    def _get_api_key(self) -> str:
        """Get API key from environment variable"""
        api_key = os.environ.get('GEMINI_API_KEY')
        if not api_key:
            # Try loading from .env file if not in environment
            self._load_dotenv()
            api_key = os.environ.get('GEMINI_API_KEY')
        
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY not found in environment variables. "
                "Please set it in your .env file or environment."
            )
        return api_key
    
    def _get_threshold(self) -> int:
        """Get IA1 secure score threshold from environment"""
        threshold = os.environ.get('IA1_SECURE_SCORE_THRESHOLD', '15')
        try:
            return int(threshold)
        except ValueError:
            return 15
    
    def _load_dotenv(self):
        """Load environment variables from .env file"""
        try:
            from dotenv import load_dotenv
            # Look for .env in project root
            env_path = os.path.join(settings.BASE_DIR, '.env')
            if os.path.exists(env_path):
                load_dotenv(env_path)
                logger.info(f"Loaded .env from {env_path}")
        except ImportError:
            logger.warning("python-dotenv not installed. Install with: pip install python-dotenv")
    
    def _configure_genai(self):
        """Configure the Gemini AI client"""
        genai.configure(api_key=self.api_key)
        self.model = genai.GenerativeModel('gemini-2.5-flash') # Updated to latest available or fallback
    
    def _format_questionnaire_for_analysis(self, answers: List[Dict[str, Any]]) -> str:
        """Format questionnaire answers into a structured text for AI analysis."""
        if not answers:
            return "Aucune réponse fournie."
        
        formatted_lines = ["=== QUESTIONNAIRE SÉCURITÉ ===\n"]
        
        for i, answer in enumerate(answers, 1):
            question_text = answer.get('question', 'Question non définie')
            answer_text = answer.get('answer', 'Non répondu')
            is_mandatory = answer.get('is_mandatory', False)
            
            # Mark mandatory questions
            mandatory_mark = " *" if is_mandatory else ""
            
            formatted_lines.append(f"Q{i}{mandatory_mark}: {question_text}")
            formatted_lines.append(f"R{i}: {answer_text if answer_text else '(Pas de réponse)'}")
            formatted_lines.append("")  # Empty line between Q&A pairs
        
        return "\n".join(formatted_lines)
    
    def _parse_json_response(self, response_text: str) -> Dict[str, Any]:
        """
        Parse the JSON response from Gemini, handling potential markdown formatting.
        """
        try:
            # Remove markdown code blocks if present
            clean_text = re.sub(r'```json\s*', '', response_text)
            clean_text = re.sub(r'```\s*$', '', clean_text)
            clean_text = clean_text.strip()
            
            # Attempt to find JSON object if there's extra text around it
            if not clean_text.startswith('{'):
                json_match = re.search(r'(\{.*\})', clean_text, re.DOTALL)
                if json_match:
                    clean_text = json_match.group(1)
            
            data = json.loads(clean_text)
            
            # Normalize keys (ensure 'summary' exists)
            if 'summary' not in data:
                # Look for alternatives
                for key in ['overview', 'description', 'analysis', 'conclusion', 'resume', 'synthese']:
                    if key in data and isinstance(data[key], str):
                        data['summary'] = data[key]
                        break
            
            # If still no summary, use a default message
            if 'summary' not in data:
                 data['summary'] = "Analyse effectuée. Veuillez consulter les points forts et faibles ci-dessous."

            return data
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse JSON from AI response: {e}")
            logger.debug(f"Raw response: {response_text}")
            
            # Fallback: try to extract score manually and put text in summary
            score = self._extract_secure_score(response_text)
            return {
                "secure_score": score,
                "summary": response_text, # Use full text as summary on parse error
                "strengths": [],
                "weaknesses": [],
                "recommendations": []
            }

    def _extract_secure_score(self, response_text: str) -> int:
        """Legacy extraction method for fallback"""
        patterns = [
            r'"secure_score"\s*:\s*(\d+)',
            r'[Ss]ecure\s*[Ss]core\s*:\s*(\d+)',
            r'[Ss]core\s*:\s*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, response_text)
            if match:
                score = int(match.group(1))
                return max(0, min(100, score))
        return 0
    
    def analyze_questionnaire(self, answers: List[Dict[str, Any]]) -> IA1AnalysisResult:
        """
        Perform IA1 analysis on questionnaire answers.
        """
        try:
            # Format questionnaire for analysis
            questionnaire_text = self._format_questionnaire_for_analysis(answers)
            
            # Construct full prompt
            full_prompt = f"{self.IA1_PROMPT}\n\n{questionnaire_text}"
            
            logger.info("Sending questionnaire to Gemini for IA1 analysis...")
            
            # Call Gemini API
            response = self.model.generate_content(full_prompt)
            raw_response = response.text
            
            # Parse JSON response
            findings = self._parse_json_response(raw_response)
            
            # Extract score from parsed JSON
            secure_score = findings.get('secure_score', 0)
            
            # Determine if coherent based on threshold
            is_coherent = secure_score >= self.threshold
            
            logger.info(f"IA1 Analysis complete. Score: {secure_score}, Coherent: {is_coherent}")
            
            return IA1AnalysisResult(
                secure_score=secure_score,
                analysis_text=findings.get('summary', raw_response),
                findings=findings, # Pass the full structured object
                is_coherent=is_coherent,
                raw_response=raw_response,
                error=None
            )
        
        except Exception as e:
            logger.error(f"Error during IA1 analysis: {str(e)}")
            return IA1AnalysisResult(
                secure_score=0,
                analysis_text=f"Erreur lors de l'analyse: {str(e)}",
                findings={"summary": f"Erreur système: {str(e)}"},
                is_coherent=False,
                raw_response="",
                error=str(e)
            )
    
    def get_threshold(self) -> int:
        """Get the current IA1 threshold"""
        return self.threshold


def run_ia1_analysis(dossier_id: int) -> IA1AnalysisResult:
    """
    Convenience function to run IA1 analysis for a dossier.
    """
    from core.models import Dossier, QuestionnaireAnswer
    
    try:
        dossier = Dossier.objects.get(id=dossier_id)
    except Dossier.DoesNotExist:
        return IA1AnalysisResult(
            secure_score=0,
            analysis_text="Dossier not found",
            findings={"summary": "Dossier introuvable"},
            is_coherent=False,
            raw_response="",
            error=f"Dossier {dossier_id} not found"
        )
    
    # Get all answers for this dossier
    answers = QuestionnaireAnswer.objects.filter(dossier=dossier).select_related('question')
    
    # Format answers for analysis
    answer_list = []
    for answer in answers:
        answer_list.append({
            'question': answer.question.text,
            'answer': answer.answer_value,
            'question_type': answer.question.question_type,
            'is_mandatory': answer.question.is_mandatory
        })
    
    # Run analysis
    service = GeminiAIService()
    return service.analyze_questionnaire(answer_list)

# Import IA2 service at the end
from .ia2_service import run_ia2_analysis

__all__ = ['run_ia1_analysis', 'run_ia2_analysis']
