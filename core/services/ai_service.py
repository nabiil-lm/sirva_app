"""
AI Service for Gemini API integration.
Handles IA1 (questionnaire coherence) analysis.
"""
import os
import re
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
    is_coherent: bool
    raw_response: str
    error: Optional[str] = None


class GeminiAIService:
    """Service for interacting with Google Gemini AI API"""
    
    # IA1 Prompt (French - cybersecurity auditor)
    IA1_PROMPT = """Tu es un auditeur cybersécurité. Analyse la cohérence interne des réponses à un questionnaire sécurité d'entreprise. Repère contradictions, omissions manifestes et réponses invraisemblables. Ne juge pas la conformité réglementaire, seulement la cohérence logique, et inclus au tout début de ta réponse, selon le résultat de ton analyse, la phrase "Secure Score: X", où X est un score de sécurité allant de 0 à 100."""
    
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
        # Use gemini-pro for Gemini Pro API access
        # Alternative: gemini-1.5-flash (if available), gemini-1.5-pro (if available)
        self.model = genai.GenerativeModel('gemini-2.5-flash')
    
    def _format_questionnaire_for_analysis(self, answers: List[Dict[str, Any]]) -> str:
        """
        Format questionnaire answers into a structured text for AI analysis.
        
        Args:
            answers: List of dicts with 'question', 'answer', 'question_type', 'is_mandatory'
        
        Returns:
            Formatted string representation of the questionnaire
        """
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
    
    def _extract_secure_score(self, response_text: str) -> int:
        """
        Extract the secure score from Gemini's response.
        
        Args:
            response_text: The raw response from Gemini
        
        Returns:
            Integer score between 0-100, or 0 if not found
        """
        # Pattern to match "Secure Score: X" or variations
        patterns = [
            r'[Ss]ecure\s*[Ss]core\s*:\s*(\d+)',
            r'[Ss]core\s*de\s*sécurité\s*:\s*(\d+)',
            r'[Ss]core\s*:\s*(\d+)',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, response_text)
            if match:
                score = int(match.group(1))
                # Clamp to 0-100 range
                return max(0, min(100, score))
        
        logger.warning("Could not extract secure score from response, defaulting to 0")
        return 0
    
    def analyze_questionnaire(self, answers: List[Dict[str, Any]]) -> IA1AnalysisResult:
        """
        Perform IA1 analysis on questionnaire answers.
        
        Args:
            answers: List of answer dictionaries with question/answer pairs
        
        Returns:
            IA1AnalysisResult with score, analysis text, and coherence status
        """
        try:
            # Format questionnaire for analysis
            questionnaire_text = self._format_questionnaire_for_analysis(answers)
            
            # Construct full prompt
            full_prompt = f"{self.IA1_PROMPT}\n\n{questionnaire_text}"
            
            logger.info("Sending questionnaire to Gemini for IA1 analysis...")
            
            # Call Gemini API
            response = self.model.generate_content(full_prompt)
            
            # Extract response text
            raw_response = response.text
            
            # Extract secure score
            secure_score = self._extract_secure_score(raw_response)
            
            # Determine if coherent based on threshold
            is_coherent = secure_score >= self.threshold
            
            logger.info(f"IA1 Analysis complete. Score: {secure_score}, Coherent: {is_coherent}")
            
            return IA1AnalysisResult(
                secure_score=secure_score,
                analysis_text=raw_response,
                is_coherent=is_coherent,
                raw_response=raw_response,
                error=None
            )
        
        except Exception as e:
            logger.error(f"Error during IA1 analysis: {str(e)}")
            return IA1AnalysisResult(
                secure_score=0,
                analysis_text=f"Erreur lors de l'analyse: {str(e)}",
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
    
    Args:
        dossier_id: The ID of the dossier to analyze
    
    Returns:
        IA1AnalysisResult with analysis results
    """
    from core.models import Dossier, QuestionnaireAnswer
    
    try:
        dossier = Dossier.objects.get(id=dossier_id)
    except Dossier.DoesNotExist:
        return IA1AnalysisResult(
            secure_score=0,
            analysis_text="Dossier not found",
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
