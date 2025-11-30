# court_manager.py
import os
import asyncio
from pathlib import Path
from dotenv import load_dotenv

# model-court imports
from model_court import Court, Prosecutor, Jury, Judge
from model_court.code import SqliteCourtCode
from model_court.references import SimpleTextStorage, LocalRAGReference

# Load environment variables
load_dotenv()

class CourtManager:
    def __init__(self):
        # ----------------------------------------------------------------------
        # 0. Path Configuration
        # ----------------------------------------------------------------------
        self.base_data_dir = Path("./data")
        
        # Files for specific juries
        self.user_feedback_path = self.base_data_dir / "user_feedback_db.txt"
        self.rag_source_folder = self.base_data_dir / "rag_documents"
        self.rag_db_storage = self.base_data_dir / "rag_vector_db"
        self.db_path = "./court_history.db"

        self._init_directories()

    def _init_directories(self):
        """Ensure all necessary folders and files exist."""
        self.base_data_dir.mkdir(exist_ok=True)
        self.rag_source_folder.mkdir(parents=True, exist_ok=True)
        self.rag_db_storage.mkdir(parents=True, exist_ok=True)
        
        if not self.user_feedback_path.exists():
            self.user_feedback_path.write_text(
                "--- Trusted User Feedback Database Initialized ---\n", 
                encoding="utf-8"
            )

        if not any(self.rag_source_folder.iterdir()):
            sample_file = self.rag_source_folder / "readme.txt"
            sample_file.write_text(
                "Place factual text files here for RAG verification.",
                encoding="utf-8"
            )

    def _get_model_config(self, model_name, temperature=0.1):
        """Helper for OpenRouter config."""
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        return {
            "provider": "openai_compatible",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": api_key,
            "model_name": model_name,
            "temperature": temperature
        }

    def build_court(self) -> Court:
        """
        Initialize Court with FACT-CHECKING FOCUSED prompts.
        """
        
        # 1. Persistent Storage
        court_code = SqliteCourtCode(
            db_path=self.db_path,
            enable_vector_search=True
        )

        # 2. Prosecutor: The Fact Extractor
        # Goal: Split text into atomic, checkable facts. Ignore opinions.
        prosecutor = Prosecutor(
            court_code=court_code,
            auto_claim_splitting=False,
            model=self._get_model_config("openai/gpt-4o-mini", temperature=0.0),
            prosecutor_prompt=(
                "You are a meticulous Fact Verification Prosecutor. "
                "Your task is to evaluate the entire text as a single claim for fact-checking. "
                "Rules:\n"
                "1. DO NOT split the text into multiple claims.\n"
                "2. Treat the entire input as one comprehensive claim to be verified.\n"
                "3. If ANY statement in the text is problematic, the entire claim is problematic."
            )
        )

        # 3. Juries: The Specialized Evaluators
        
        # [Jury 1: Logic GPT] - The Logician
        # Focus: Internal consistency, dates, physics, general world knowledge.
        jury_gpt = Jury(
            name="Logic_GPT",
            model=self._get_model_config("openai/gpt-4o-mini", temperature=0.0),
            reference=None,
            jury_prompt=(
                "You are a Logic Juror. Evaluate this claim for internal consistency "
                "and alignment with established general knowledge.\n"
                "Check for:\n"
                "- Logical fallacies (e.g., contradiction, strawman).\n"
                "- Impossibilities (e.g., historical dates that don't match, physics violations).\n"
                "If the claim is logically sound and widely accepted as true, vote 'no_objection'."
            )
        )

        # [Jury 2: Logic Gemini] - The Skeptic (Devil's Advocate)
        # Focus: Detecting misleading framing, exaggeration, or fake news patterns.
        jury_gemini = Jury(
            name="Logic_Gemini",
            model=self._get_model_config("google/gemini-2.5-flash-lite", temperature=0.1),
            reference=None,
            jury_prompt=(
                "You are a Skeptical Juror. Scrutinize this claim for potential misinformation. "
                "Act as a Devil's Advocate: ask 'Is this misleading?' or 'Is this a rumor?'.\n"
                "Look for:\n"
                "- Exaggerated absolute terms (e.g., '100% confirmed').\n"
                "- Sensationalist phrasing common in fake news.\n"
                "If you find reasonable doubt or signs of manipulation, object immediately."
            )
        )

        # [Jury 3: Web Search] - The Researcher
        # Focus: External verification against authoritative sources.
        jury_web = Jury(
            name="Web_Search_Jury",
            model=self._get_model_config("perplexity/sonar", temperature=0.0),
            reference=None,
            jury_prompt=(
                "You are a Web Verification Juror. Use the search tool to find external evidence "
                "confirming or debunking this claim. "
                "Prioritize authoritative sources (e.g., major news outlets, government sites, encyclopedia). "
                "If search results contradict the claim, vote 'reasonable_doubt' and cite the source."
            )
        )

        # [Jury 4: Local RAG] - The Archivist
        # Focus: Checking against the "Ground Truth" documents provided by admins.
        jury_rag = Jury(
            name="RAG_Jury",
            model=self._get_model_config("openai/gpt-4o-mini", temperature=0.1),
            reference=LocalRAGReference(
                collection_name="fact_check_knowledge",
                persist_directory=str(self.rag_db_storage),
                source_folder=str(self.rag_source_folder),
                embedding_model="MiniLM",
                mode="append",
                top_k=3
            ),
            jury_prompt=(
                "You are the Knowledge Base Archivist. Verify this claim specifically against "
                "the retrieved local documents. "
                "If the retrieved context directly contradicts the claim, you MUST vote 'suspicious_fact'. "
                "If the context is irrelevant, abstain."
            )
        )

        # [Jury 5: User Feedback] - The Community Watch
        # Focus: Checking if users have previously flagged this.
        feedback_content = self.user_feedback_path.read_text(encoding="utf-8")
        jury_feedback = Jury(
            name="User_Feedback_Jury",
            model=self._get_model_config("openai/gpt-4o-mini", temperature=0.1),
            reference=SimpleTextStorage(text=feedback_content),
            jury_prompt=(
                "You are the Community Watch Juror. Check the user feedback database. "
                "Has this specific claim been previously reported as FAKE or CORRECTED by users? "
                "If the database contains a user report refuting this, verify it and vote accordingly."
            )
        )

        # 4. Judge: The Final Arbiter
        # Goal: Weigh evidence appropriately.
        judge = Judge(
            model=self._get_model_config("openai/gpt-4o", temperature=0.1)
        )

        # 5. Assemble
        return Court(
            prosecutor=prosecutor,
            juries=[jury_gpt, jury_gemini, jury_web, jury_rag, jury_feedback],
            judge=judge,
            verdict_rules={
                "supported": {"operator": "eq", "value": 0},  
                "suspicious": {"operator": "lt", "value": 0.5}, # 半数以下是SUSPICIOUS 
                "refuted": "default"
            },
            quorum=3,
            concurrency_limit=5
        )

    async def verify_text(self, text):
        court = self.build_court()
        safe_text = text[:12000]

        report = await court.hear(safe_text)

        verdict_map = {
            "supported": "CLEAN",
            "suspicious": "SUSPICIOUS", 
            "refuted": "FAKE"
        }
        
        # Since auto_claim_splitting=False, we expect only one claim result
        if not report.claims or len(report.claims) == 0:
            return {
                "confidence": "N/A",
                "details": "No claims were processed by the court."
            }
        
        # Get the single claim result (first and only one)
        res = report.claims[0]
        mapped_verdict = verdict_map.get(res.verdict, "SUSPICIOUS")
        
        # ========== Print clear summary to terminal ==========
        print("\n" + "=" * 80)
        print("MODEL COURT VERDICT SUMMARY")
        print("=" * 80)
        
        # Print Jury votes
        print("\n📊 JURY VOTES:")
        for vote in res.jury_votes:
            vote_icon = "✓" if vote.decision == "no_objection" else "✗"
            decision_color = vote.decision.replace("_", " ").title()
            print(f"  {vote_icon} {vote.jury_name:20s} → {decision_color}")
        
        # Print Judge's decision
        print(f"\n⚖️  JUDGE'S FINAL VERDICT: {mapped_verdict}")
        if res.judge_reasoning:
            print(f"\n💭 JUDGE'S REASONING:")
            # Split reasoning into lines for better readability
            reasoning_lines = res.judge_reasoning[:400].split('. ')
            for line in reasoning_lines[:3]:  # Show first 3 sentences
                if line.strip():
                    print(f"   • {line.strip()}.")
        
        print("=" * 80 + "\n")
        
        # Build details for return
        details_lines = []
        icon = "✓" if mapped_verdict == "CLEAN" else ("✗" if mapped_verdict == "FAKE" else "⚠")
        
        details_lines.append(f"{icon} Overall Verdict: {mapped_verdict}")
        details_lines.append("")
        
        if res.judge_reasoning:
            details_lines.append(f"Judge's Reasoning:")
            details_lines.append(f"{res.judge_reasoning}")
            details_lines.append("")
        
        # List jury votes and their decisions
        details_lines.append("Jury Votes:")
        for vote in res.jury_votes:
            vote_icon = "✓" if vote.decision == "no_objection" else "⚠"
            details_lines.append(f"  {vote_icon} {vote.jury_name}: {vote.decision}")
            if vote.reason:
                details_lines.append(f"     Reasoning: {vote.reason[:200]}...")
        
        details_str = "\n".join(details_lines)
        if not details_str:
            details_str = "Content verified. No logical fallacies or factual errors detected by the jury."

        return {
            "confidence": mapped_verdict,
            "details": details_str
        }

court_manager = CourtManager()