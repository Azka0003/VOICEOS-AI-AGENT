"""
LLM Router for DebtPilot.

This is the single shared LLM interface used by every agent in the system.
It routes requests to Groq (primary) and silently falls back to Ollama if Groq fails.
Every successful call and fallback event is strictly logged to lineage_log.json.

Configuration via .env:
  GROQ_API_KEY         → Required for Groq
  GROQ_MODEL           → Optional override (default: llama-3.3-70b-versatile)
  GROQ_SPEED_MODEL     → Optional override (default: llama-3.1-8b-instant)
  OLLAMA_URL           → Optional (default: http://localhost:11434)
  OLLAMA_MODEL         → Optional (default: phi3)
  LLM_PROVIDER         → "ollama" (skip Groq), "groq" (skip Ollama), or empty (use both)

Example usage by agents:
  from tools.llm_router import llm_router
  
  response = llm_router.invoke(
      prompt="Draft a payment reminder for Raj Traders",
      mode="generation",
      agent_name="email_agent",
      context={"client": "Raj Traders", "invoice_id": "INV001"}
  )
"""

import os
import json
import time
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

# Attempt to load Groq
try:
    from langchain_groq import ChatGroq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# Attempt to load Ollama (Langchain Community)
try:
    from langchain_community.llms import Ollama
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# File Paths
DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
LINEAGE_LOG_PATH = os.path.join(DATA_DIR, "lineage_log.json")


class LLMRouter:
    def __init__(self):
        # 1. Read environment variables
        self.groq_api_key = os.getenv("GROQ_API_KEY", "")
        self.groq_model_gen = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.groq_model_speed = os.getenv("GROQ_SPEED_MODEL", "llama-3.1-8b-instant")
        
        self.ollama_url = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.ollama_model = os.getenv("OLLAMA_MODEL", "phi3")
        
        self.llm_provider = os.getenv("LLM_PROVIDER", "").strip().lower()

        # 2. Initialize LLM clients
        self.groq_gen_llm = None
        self.groq_speed_llm = None
        self.ollama_llm = None

        # Setup Groq
        if self.llm_provider != "ollama":
            if self.groq_api_key and GROQ_AVAILABLE:
                try:
                    self.groq_gen_llm = ChatGroq(
                        api_key=self.groq_api_key,
                        model_name=self.groq_model_gen,
                        temperature=0.4
                    )
                    self.groq_speed_llm = ChatGroq(
                        api_key=self.groq_api_key,
                        model_name=self.groq_model_speed,
                        temperature=0.2
                    )
                except Exception as e:
                    print(f"[LLM ROUTER ERROR] Failed to initialize Groq: {e}")
            else:
                print("[LLM ROUTER] GROQ_API_KEY missing or langchain_groq not installed. Skipping Groq.")

        # Setup Ollama
        if self.llm_provider != "groq":
            if OLLAMA_AVAILABLE:
                try:
                    self.ollama_llm = Ollama(
                        base_url=self.ollama_url,
                        model=self.ollama_model
                    )
                except Exception as e:
                    print(f"[LLM ROUTER ERROR] Failed to initialize Ollama: {e}")
            else:
                print("[LLM ROUTER] langchain_community not installed. Skipping Ollama.")

        # Ensure directory exists for logs
        os.makedirs(DATA_DIR, exist_ok=True)

    def _log_event(self, log_entry: dict):
        """Safely appends a log entry to lineage_log.json."""
        try:
            if not os.path.exists(LINEAGE_LOG_PATH):
                with open(LINEAGE_LOG_PATH, "w", encoding="utf-8") as f:
                    json.dump([], f)
            
            with open(LINEAGE_LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
                
            logs.append(log_entry)
            
            with open(LINEAGE_LOG_PATH, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2)
        except Exception as e:
            print(f"[LLM ROUTER LOG ERROR] Could not write to lineage_log.json: {e}")

    def invoke(self, prompt: str, mode: str = "generation", agent_name: str = "unknown", context: dict = None) -> str:
        """
        Sends a prompt to the primary LLM (Groq), falls back to Ollama on failure,
        and logs the outcome to the lineage tracker.
        """
        if context is None:
            context = {}

        # Default to generation mode if unrecognized
        if mode not in ["generation", "speed"]:
            mode = "generation"

        primary_llm = self.groq_speed_llm if mode == "speed" else self.groq_gen_llm
        primary_model_name = self.groq_model_speed if mode == "speed" else self.groq_model_gen

        start_time = time.time()
        groq_failed = False
        groq_error_str = ""
        response_content = ""
        llm_used = ""

        # Step 1: Try Groq
        if primary_llm is not None and self.llm_provider != "ollama":
            try:
                response = primary_llm.invoke(prompt)
                response_content = response.content
                llm_used = f"groq/{primary_model_name}"
            except Exception as e:
                groq_failed = True
                groq_error_str = str(e)
                print(f"[LLM ROUTER FALLBACK] Groq failed: {groq_error_str}. Falling back to Ollama.")
        else:
            groq_failed = True
            groq_error_str = "Groq unavailable or bypassed by LLM_PROVIDER config."
            if self.llm_provider != "ollama":
                print("[LLM ROUTER FALLBACK] Groq unavailable. Falling back to Ollama.")

        # Step 2: Fallback to Ollama
        if groq_failed:
            # Log the fallback event before proceeding
            fallback_entry = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "agent": agent_name,
                "action": "llm_fallback",
                "llm_used": f"ollama/{self.ollama_model}",
                "mode": mode,
                "groq_error": groq_error_str,
                "fallback_used": True,
                "latency_ms": None,
                "hitl_triggered": False,
                "hitl_reason": None,
                "context": context
            }
            self._log_event(fallback_entry)

            if self.ollama_llm is not None:
                try:
                    # langchain_community Ollama returns string directly
                    response_content = self.ollama_llm.invoke(prompt)
                    llm_used = f"ollama/{self.ollama_model}"
                except Exception as e:
                    ollama_error_str = str(e)
                    raise RuntimeError(
                        f"Both LLM providers failed.\nGroq Error: {groq_error_str}\nOllama Error: {ollama_error_str}"
                    )
            else:
                raise RuntimeError(
                    f"Neither Groq nor Ollama is available. Check your environment.\nGroq Status: {groq_error_str}"
                )

        # Step 3: Log Success
        end_time = time.time()
        latency_ms = int((end_time - start_time) * 1000)

        success_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": agent_name,
            "action": "llm_invoke",
            "llm_used": llm_used,
            "mode": mode,
            "latency_ms": latency_ms,
            "prompt_length_chars": len(prompt),
            "response_length_chars": len(response_content),
            "fallback_used": groq_failed,
            "hitl_triggered": False,
            "hitl_reason": None,
            "context": context
        }
        self._log_event(success_entry)

        return response_content

    def get_stats(self) -> dict:
        """Returns a summary of LLM usage statistics based on the lineage log."""
        stats = {
            "total_calls": 0,
            "groq_calls": 0,
            "ollama_calls": 0,
            "fallbacks": 0,
            "avg_latency_ms": 0.0,
            "calls_by_agent": {}
        }
        
        try:
            if not os.path.exists(LINEAGE_LOG_PATH):
                return stats
                
            with open(LINEAGE_LOG_PATH, "r", encoding="utf-8") as f:
                logs = json.load(f)
                
            total_latency = 0
            latency_count = 0
            
            for entry in logs:
                if entry.get("action") == "llm_fallback":
                    stats["fallbacks"] += 1
                elif entry.get("action") == "llm_invoke":
                    stats["total_calls"] += 1
                    
                    # Tally provider usage
                    llm_used = entry.get("llm_used", "")
                    if llm_used.startswith("groq"):
                        stats["groq_calls"] += 1
                    elif llm_used.startswith("ollama"):
                        stats["ollama_calls"] += 1
                        
                    # Tally agent calls
                    agent = entry.get("agent", "unknown")
                    stats["calls_by_agent"][agent] = stats["calls_by_agent"].get(agent, 0) + 1
                    
                    # Sum latencies
                    lat = entry.get("latency_ms")
                    if lat is not None:
                        total_latency += lat
                        latency_count += 1
                        
            if latency_count > 0:
                stats["avg_latency_ms"] = round(total_latency / latency_count, 2)
                
        except Exception as e:
            print(f"[LLM ROUTER ERROR] Failed to compute stats: {e}")
            
        return stats

    def test_connections(self) -> dict:
        """Tests both Groq and Ollama connections safely."""
        results = {
            "groq": {
                "status": "failed",
                "model": self.groq_model_gen,
                "latency_ms": None,
                "error": "Not initialized or missing API key"
            },
            "ollama": {
                "status": "failed",
                "model": self.ollama_model,
                "latency_ms": None,
                "error": "Not initialized or langchain_community missing"
            }
        }

        # Test Groq
        if self.groq_gen_llm is not None:
            try:
                start = time.time()
                self.groq_gen_llm.invoke("Say hello in one word.")
                results["groq"]["latency_ms"] = int((time.time() - start) * 1000)
                results["groq"]["status"] = "ok"
                results["groq"]["error"] = None
            except Exception as e:
                results["groq"]["error"] = str(e)

        # Test Ollama
        if self.ollama_llm is not None:
            try:
                start = time.time()
                self.ollama_llm.invoke("Say hello in one word.")
                results["ollama"]["latency_ms"] = int((time.time() - start) * 1000)
                results["ollama"]["status"] = "ok"
                results["ollama"]["error"] = None
            except Exception as e:
                results["ollama"]["error"] = str(e)

        return results

# Singleton export
llm_router = LLMRouter()