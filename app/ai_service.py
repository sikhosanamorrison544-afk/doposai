"""
AI Service Module for POS System
Integrates with Ollama to provide business intelligence and accounting insights.
"""

import json
import logging
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple
import requests
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, and_, case, or_

from .models import (
    Sale, SaleItem, Product, Withdrawal, Customer, Category,
    Payment, InventoryMovement, StoreSettings, LaybyTransaction, User, LaybyCustomer,
)

from . import tenant_scope

logger = logging.getLogger(__name__)

# Ollama configuration - OPTIMIZED FOR RASPBERRY PI 5 SPEED
# OLLAMA_BASE_URL: set env to e.g. http://192.168.1.x:11434 if the app runs on a different machine than Ollama
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "phi:2.7b")  # Phi 2.7B; use phi or phi:2.7b
OLLAMA_TIMEOUT = 25  # seconds for analysis requests (reduced for faster fallback - comprehensive fallback is always available)
OLLAMA_STATUS_TIMEOUT = 2.5  # seconds for /api/tags when verifying model (Pi can be slow)
OLLAMA_VERSION_TIMEOUT = 1.0  # seconds for /api/version ping
OLLAMA_CHAT_TIMEOUT = 300  # 5 minutes for chat so the model has time to reason and respond
USE_SUBPROCESS = False  # Use HTTP API by default (more reliable), subprocess can be slower on Pi


class AIService:
    """Service for interacting with Ollama AI for business analysis."""
    
    def __init__(self, base_url: str = OLLAMA_BASE_URL, model: str = OLLAMA_MODEL):
        self.base_url = base_url
        self.model = model
        self.timeout = OLLAMA_TIMEOUT
        self._connection_verified = False  # Track if connection has been verified
        self._precomputed_analysis_cache = {}  # Cache for pre-computed business analysis
        self._status_cache = {"available": False, "timestamp": 0, "ttl": 15}  # Cache status for 15 seconds
        self._last_status_check = 0
        self._ollama_start_attempted = 0  # Time we last tried to start Ollama (to avoid spamming)
    
    def ensure_ollama_running(self, min_interval_seconds: int = 120) -> bool:
        """
        If Ollama is not responding, start it in a separate background process so it's always available.
        Returns True if Ollama is already running or was started, False if start was skipped or failed.
        """
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=OLLAMA_VERSION_TIMEOUT)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        now = datetime.utcnow().timestamp()
        if now - self._ollama_start_attempted < min_interval_seconds:
            return False
        self._ollama_start_attempted = now
        try:
            kwargs = {
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
            }
            if sys.platform != "win32":
                kwargs["start_new_session"] = True
            else:
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
            subprocess.Popen(["ollama", "serve"], **kwargs)
            logger.info("Started Ollama in background (ollama serve). It will be available once the server is up.")
            return True
        except FileNotFoundError:
            logger.warning("Ollama not found in PATH. Install from https://ollama.ai and ensure 'ollama' is on PATH.")
            return False
        except Exception as e:
            logger.warning(f"Could not start Ollama: {e}")
            return False
    
    def _process_tags_response(self, response: requests.Response, current_time: float) -> bool:
        """Process /api/tags response: verify model, update cache, return True if available."""
        if response.status_code != 200:
            self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
            return False
        try:
            models_data = response.json()
            raw_list = models_data.get("models") or models_data.get("model") or []
            if isinstance(raw_list, dict):
                raw_list = [raw_list]
            # Ollama can return {"name": "phi:2.7b"} or {"model": "phi:2.7b"}
            models = []
            for m in raw_list:
                name = m.get("name") or m.get("model") or (m if isinstance(m, str) else "")
                if name:
                    models.append(name)
            if not models:
                logger.warning("Ollama /api/tags returned no models")
                self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
                return False
            if self.model in models:
                self._connection_verified = True
                self._status_cache = {"available": True, "timestamp": current_time, "ttl": 15}
                return True
            model_base = self.model.split(":")[0]
            phi_models = [m for m in models if m.startswith(model_base + ":") or m == model_base or "phi" in m.lower()]
            if phi_models:
                preferred = [m for m in phi_models if "q4" in m.lower()]
                self.model = preferred[0] if preferred else phi_models[0]
                logger.info(f"Ollama available. Using model: {self.model}")
                self._connection_verified = True
                self._status_cache = {"available": True, "timestamp": current_time, "ttl": 15}
                return True
            # Any model is enough to show "connected"; we'll use the first one for chat
            self.model = models[0]
            logger.info(f"Ollama available. Using model: {self.model} (preferred phi not found)")
            self._connection_verified = True
            self._status_cache = {"available": True, "timestamp": current_time, "ttl": 15}
            return True
        except Exception as e:
            logger.warning(f"Ollama tags parse error: {e}", exc_info=True)
            self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
            return False

    def _check_ollama_available(self, retries: int = 2, use_cache: bool = True) -> bool:
        """Check if Ollama service is available and model is loaded. Fast path: /api/version then /api/tags."""
        import time
        current_time = time.time()
        
        # Use cached result if available and fresh (within TTL)
        if use_cache and self._status_cache["timestamp"] > 0:
            age = current_time - self._status_cache["timestamp"]
            if age < self._status_cache["ttl"]:
                logger.debug(f"Using cached Ollama status: {self._status_cache['available']} (age: {age:.1f}s)")
                return self._status_cache["available"]
        
        # Fast path: lightweight /api/version first (fails in ~0.4s if Ollama is down)
        try:
            r = requests.get(f"{self.base_url}/api/version", timeout=OLLAMA_VERSION_TIMEOUT)
            if r.status_code == 200:
                # Ollama is up; verify model with /api/tags (single attempt)
                logger.debug(f"Ollama up (version check); verifying model at {self.base_url}/api/tags")
                response = requests.get(f"{self.base_url}/api/tags", timeout=OLLAMA_STATUS_TIMEOUT)
                return self._process_tags_response(response, current_time)
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            pass  # Fall through to retry loop
        except Exception as e:
            logger.debug(f"Fast version check failed: {e}")
        
        # Fallback: full check with /api/tags (e.g. when Ollama is slow or down)
        for attempt in range(retries):
            try:
                logger.debug(f"Checking Ollama availability at {self.base_url}/api/tags (attempt {attempt + 1}/{retries})")
                response = requests.get(
                    f"{self.base_url}/api/tags",
                    timeout=OLLAMA_STATUS_TIMEOUT
                )
                return self._process_tags_response(response, current_time)
            except requests.exceptions.Timeout:
                logger.warning(f"Ollama status timed out (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(0.2)
                    continue
                self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
                return False
            except requests.exceptions.ConnectionError as e:
                logger.warning(f"Ollama connection error: {e} (attempt {attempt + 1}/{retries})")
                if attempt < retries - 1:
                    time.sleep(0.2)
                    continue
                logger.warning("Make sure Ollama is running: ollama serve")
                self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
                return False
            except Exception as e:
                logger.warning(f"Ollama check failed: {e} (attempt {attempt + 1}/{retries})", exc_info=True)
                if attempt < retries - 1:
                    time.sleep(0.2)
                    continue
                self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
                return False
        
        # Cache negative result
        self._status_cache = {"available": False, "timestamp": current_time, "ttl": 5}
        return False

    def check_ollama_with_reason(self, retries: int = 2) -> Tuple[bool, str]:
        """Return (available, reason). Use for status API so the UI can show why connection failed."""
        import time
        current_time = time.time()
        base = self.base_url
        # Try /api/version first
        try:
            r = requests.get(f"{base}/api/version", timeout=OLLAMA_VERSION_TIMEOUT)
            if r.status_code != 200:
                return False, f"Ollama at {base} returned HTTP {r.status_code}"
        except requests.exceptions.ConnectionError as e:
            return False, f"Cannot reach {base} (connection refused). If the POS runs on another machine than Ollama, set OLLAMA_BASE_URL=http://<pi-ip>:11434"
        except requests.exceptions.Timeout:
            return False, f"Ollama at {base} did not respond in time (version check)"
        except Exception as e:
            return False, str(e)
        # Try /api/tags
        try:
            response = requests.get(f"{base}/api/tags", timeout=OLLAMA_STATUS_TIMEOUT)
            ok = self._process_tags_response(response, current_time)
            if ok:
                return True, f"Connected (model: {self.model})"
            return False, "Ollama returned no models. Run: ollama pull phi:2.7b"
        except requests.exceptions.Timeout:
            return False, f"Ollama at {base} did not respond in time (model list)"
        except requests.exceptions.ConnectionError:
            return False, f"Cannot reach {base} (connection refused)"
        except Exception as e:
            return False, str(e)
    
    def _get_ai_unavailable_message(self) -> str:
        """Get helpful message when AI is unavailable."""
        try:
            # Try to check what's wrong
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=2
            )
            if response.status_code == 200:
                models_data = response.json()
                models = [m.get('name', '') for m in models_data.get('models', [])]
                phi_models = [m for m in models if 'phi' in m.lower()]
                if not phi_models:
                    return f"AI analysis unavailable. Ollama is running but no Phi model found. Install with: ollama pull {self.model}"
                else:
                    return f"AI analysis unavailable. Model may be busy or timed out. Available models: {', '.join(phi_models)}"
        except:
            pass
        return "AI analysis unavailable. Please ensure Ollama is running (ollama serve) and install the model (ollama pull phi:Q4_K_M)"
    
    def _call_ollama(self, prompt: str) -> Optional[str]:
        """
        Call Ollama using subprocess (faster on Pi) or HTTP API as fallback.
        Pre-calculated data is passed in prompt - AI only interprets.
        """
        if USE_SUBPROCESS:
            return self._call_ollama_subprocess(prompt)
        else:
            return self._call_ollama_http(prompt)
    
    def _call_ollama_subprocess(self, prompt: str) -> Optional[str]:
        """
        Call Ollama CLI via subprocess - FASTER on Raspberry Pi 5.
        Output is captured (non-streaming in practice).
        """
        try:
            logger.debug(f"Calling Ollama via subprocess (ultra-fast mode), prompt: {len(prompt)} chars")
            
            # Use ollama run with --no-stream flag (faster on Pi)
            # Extract model name - CLI uses format "phi:2.7b", "phi:Q4_K_M", or just "phi"
            # Ollama CLI accepts the full model name with tag
            model_name = self.model  # Use full name like "phi:2.7b" or "phi:Q4_K_M"
            
            # Note: ollama run doesn't support --no-stream flag, it streams by default
            # We capture all output and it will be non-streaming in practice
            result = subprocess.run(
                ["ollama", "run", model_name],
                input=prompt.encode('utf-8'),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=OLLAMA_TIMEOUT,
                text=False  # We'll decode manually
            )
            
            if result.returncode == 0:
                response_text = result.stdout.decode('utf-8', errors='ignore').strip()
                # Filter out ANSI escape codes and spinner characters
                import re
                response_text = re.sub(r'\x1b\[[0-9;]*[a-zA-Z]', '', response_text)  # Remove ANSI codes
                response_text = re.sub(r'[⠁-⠿]', '', response_text)  # Remove spinner chars
                response_text = response_text.strip()
                
                if response_text:
                    logger.info(f"Ollama subprocess call successful, response length: {len(response_text)} characters")
                    return response_text
                else:
                    logger.warning("Ollama subprocess returned empty response, falling back to HTTP")
                    return self._call_ollama_http(prompt)
            else:
                error_msg = result.stderr.decode('utf-8', errors='ignore')
                logger.warning(f"Ollama subprocess error (code {result.returncode}): {error_msg[:200]}, falling back to HTTP")
                return self._call_ollama_http(prompt)
                
        except subprocess.TimeoutExpired:
            logger.error(f"Ollama subprocess timed out after {OLLAMA_TIMEOUT} seconds")
            return None
        except FileNotFoundError:
            logger.error("Ollama CLI not found. Install with: curl -fsSL https://ollama.com/install.sh | sh")
            # Fallback to HTTP API
            return self._call_ollama_http(prompt)
        except Exception as e:
            logger.error(f"Error calling Ollama subprocess: {e}", exc_info=True)
            # Fallback to HTTP API
            return self._call_ollama_http(prompt)
    
    def _call_ollama_http(self, prompt: str) -> Optional[str]:
        """
        Fallback: Call Ollama via HTTP API.
        """
        try:
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": "30m",  # Keep model loaded for 30 min so it's always available
                "options": {
                    "temperature": 0.1,  # Very low for fastest responses
                    "top_p": 0.3,  # Lower for fastest selection
                    "num_predict": 250,  # Increased for complete business performance analysis
                    "top_k": 3,  # Minimal for fastest selection
                    "repeat_penalty": 1.0,  # No penalty for speed
                    "num_ctx": 512,  # Increased context for comprehensive analysis
                    "num_thread": 4,
                    "numa": False,
                }
            }
            
            logger.debug(f"Calling Ollama HTTP API (fallback), prompt: {len(prompt)} chars")
            
            response = requests.post(
                url,
                json=payload,
                timeout=OLLAMA_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()
                if response_text:
                    logger.info(f"Ollama HTTP API call successful, response length: {len(response_text)} characters")
                    return response_text
                else:
                    logger.warning("Ollama HTTP API returned empty response")
                    return None
            else:
                logger.error(f"Ollama HTTP API error: {response.status_code} - {response.text[:500]}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"Ollama HTTP API request timed out after {OLLAMA_TIMEOUT} seconds")
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ollama HTTP API connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error calling Ollama HTTP API: {e}", exc_info=True)
            return None
    
    def warm_model(self) -> bool:
        """Load and keep the model in memory so it's always available. Uses minimal prompt + keep_alive."""
        try:
            if not self._check_ollama_available(retries=1, use_cache=True):
                return False
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": "Hi",
                "stream": False,
                "keep_alive": "30m",
                "options": {"num_predict": 1},
            }
            r = requests.post(url, json=payload, timeout=10)
            if r.status_code == 200:
                logger.debug("Model warm-up request sent; model should stay loaded.")
                return True
            return False
        except Exception as e:
            logger.debug(f"Model warm-up failed (non-critical): {e}")
            return False
    
    def analyze_sales_data(
        self,
        db: Session,
        days: int = 30,
        comparison_days: int = 30,
        user: Optional[User] = None,
    ) -> Dict[str, Any]:
        """
        Analyze sales data and return AI-generated insights.
        
        Args:
            db: Database session
            days: Number of days to analyze (current period)
            comparison_days: Number of days for comparison (previous period)
        
        Returns:
            Dictionary with analysis results and AI insights
        """
        try:
            # Calculate date ranges
            end_date = datetime.utcnow()
            start_date = end_date - timedelta(days=days)
            comparison_start = start_date - timedelta(days=comparison_days)
            
            sales_q = db.query(Sale) if user is None else tenant_scope.filter_sales(db, user)
            
            # Get current period sales
            current_sales = sales_q.filter(
                and_(
                    Sale.created_at >= start_date,
                    Sale.created_at < end_date
                )
            ).all()
            
            # Get previous period sales for comparison
            previous_sales = sales_q.filter(
                and_(
                    Sale.created_at >= comparison_start,
                    Sale.created_at < start_date
                )
            ).all()
            
            # Aggregate current period data
            current_total = sum(float(sale.total) for sale in current_sales)
            current_count = len(current_sales)
            current_items_q = (
                db.query(
                SaleItem.product_id,
                Product.name,
                func.sum(SaleItem.quantity).label('total_qty'),
                func.sum(SaleItem.line_total).label('total_revenue')
            ).join(
                Product, SaleItem.product_id == Product.id
            ).join(
                Sale, SaleItem.sale_id == Sale.id
            ).filter(
                and_(
                    Sale.created_at >= start_date,
                    Sale.created_at < end_date
                )
            )
            )
            if user is not None:
                current_items_q = current_items_q.filter(
                    tenant_scope.sale_tenant_match(user),
                    tenant_scope.product_tenant_match(user),
                )
            current_items = (
                current_items_q.group_by(
                SaleItem.product_id, Product.name
            ).order_by(
                desc('total_revenue')
            ).limit(20).all()
            )
            
            # Aggregate previous period data
            previous_total = sum(float(sale.total) for sale in previous_sales)
            previous_count = len(previous_sales)
            
            # Get top products from previous period
            previous_items_q = (
                db.query(
                SaleItem.product_id,
                Product.name,
                func.sum(SaleItem.quantity).label('total_qty'),
                func.sum(SaleItem.line_total).label('total_revenue')
            ).join(
                Product, SaleItem.product_id == Product.id
            ).join(
                Sale, SaleItem.sale_id == Sale.id
            ).filter(
                and_(
                    Sale.created_at >= comparison_start,
                    Sale.created_at < start_date
                )
            )
            )
            if user is not None:
                previous_items_q = previous_items_q.filter(
                    tenant_scope.sale_tenant_match(user),
                    tenant_scope.product_tenant_match(user),
                )
            previous_items = (
                previous_items_q.group_by(
                SaleItem.product_id, Product.name
            ).order_by(
                desc('total_revenue')
            ).limit(20).all()
            )
            
            # Get withdrawals (expenses)
            wd_q = db.query(Withdrawal).filter(
                and_(
                    Withdrawal.created_at >= start_date,
                    Withdrawal.created_at < end_date
                )
            )
            if user is not None:
                wd_q = tenant_scope.filter_withdrawals(db, user).filter(
                    and_(
                        Withdrawal.created_at >= start_date,
                        Withdrawal.created_at < end_date
                    )
                )
            withdrawals = wd_q.all()
            
            total_withdrawals = sum(float(w.amount) for w in withdrawals)
            
            # Format data for AI
            current_products = [
                {
                    "name": item.name,
                    "quantity": int(item.total_qty),
                    "revenue": float(item.total_revenue)
                }
                for item in current_items
            ]
            
            previous_products = [
                {
                    "name": item.name,
                    "quantity": int(item.total_qty),
                    "revenue": float(item.total_revenue)
                }
                for item in previous_items
            ]
            
            # Calculate growth rates
            revenue_growth = 0
            if previous_total > 0:
                revenue_growth = ((current_total - previous_total) / previous_total) * 100
            
            sales_count_growth = 0
            if previous_count > 0:
                sales_count_growth = ((current_count - previous_count) / previous_count) * 100
            
            # Build prompt for AI
            prompt = self._build_analysis_prompt(
                current_total=current_total,
                previous_total=previous_total,
                current_count=current_count,
                previous_count=previous_count,
                revenue_growth=revenue_growth,
                sales_count_growth=sales_count_growth,
                current_products=current_products,
                previous_products=previous_products,
                total_withdrawals=total_withdrawals,
                days=days
            )
            
            # Calculate net_profit for fallback analysis
            net_profit = current_total - total_withdrawals
            profit_margin_calc = (net_profit / current_total * 100) if current_total > 0 else 0
            top_product = current_products[0] if current_products else None
            top_product_text = f"{top_product['name']} (${top_product['revenue']:.0f})" if top_product else "None"
            
            # Always provide comprehensive fallback immediately for instant results
            # Then try to enhance with AI if available (non-blocking)
            ai_insights = self._get_comprehensive_fallback_analysis(
                current_total=current_total,
                net_profit=net_profit,
                profit_margin=profit_margin_calc,
                revenue_growth=revenue_growth,
                current_count=current_count,
                sales_count_growth=sales_count_growth,
                top_product_text=top_product_text
            )
            
            # Try to enhance with AI if Ollama is available (with short timeout)
            ollama_available = self._check_ollama_available(retries=1)  # Quick check
            if ollama_available:
                logger.info("Ollama is available, attempting AI enhancement (non-blocking)...")
                try:
                    # Try AI with short timeout - if it works quickly, replace fallback
                    ai_response = self._call_ollama(prompt)
                    if ai_response and len(ai_response.strip()) > 50:  # Only use if substantial response
                        logger.info("AI analysis completed successfully, using AI response")
                        ai_insights = ai_response
                    else:
                        logger.info("AI response too short or empty, keeping comprehensive fallback")
                except requests.exceptions.Timeout:
                    logger.info("AI analysis timed out quickly, keeping comprehensive fallback")
                except Exception as e:
                    logger.warning(f"AI enhancement failed: {e}, keeping comprehensive fallback")
            else:
                logger.info("Ollama not available, using comprehensive fallback analysis")
            
            # Final safety check - ensure ai_insights is never None
            if ai_insights is None:
                ai_insights = self._get_comprehensive_fallback_analysis(
                    current_total=current_total,
                    net_profit=net_profit,
                    profit_margin=profit_margin_calc,
                    revenue_growth=revenue_growth,
                    current_count=current_count,
                    sales_count_growth=sales_count_growth,
                    top_product_text=top_product_text
                )
            
            return {
                "success": True,
                "period_days": days,
                "current_period": {
                    "total_revenue": current_total,
                    "total_sales": current_count,
                    "total_expenses": total_withdrawals,
                    "net_profit": current_total - total_withdrawals,
                    "top_products": current_products[:10]
                },
                "previous_period": {
                    "total_revenue": previous_total,
                    "total_sales": previous_count
                },
                "growth": {
                    "revenue_growth_percent": round(revenue_growth, 2),
                    "sales_count_growth_percent": round(sales_count_growth, 2)
                },
                "ai_insights": ai_insights,  # Always set by fallback logic above
                "ollama_available": ollama_available
            }
            
        except Exception as e:
            logger.error(f"Error analyzing sales data: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "ai_insights": None,
                "ollama_available": self._check_ollama_available(retries=3)
            }
    
    def _get_comprehensive_fallback_analysis(
        self,
        current_total: float,
        net_profit: float,
        profit_margin: float,
        revenue_growth: float,
        current_count: int,
        sales_count_growth: float,
        top_product_text: str
    ) -> str:
        """Generate comprehensive fallback analysis when AI times out."""
        top_product_name = top_product_text.split('(')[0].strip() if top_product_text and '(' in top_product_text else "None"
        avg_transaction = (current_total / current_count) if current_count > 0 else 0
        
        return f"""COMPLETE BUSINESS PERFORMANCE ANALYSIS

1. FINANCIAL HEALTH
Total Revenue: ${current_total:,.2f}
Net Profit: ${net_profit:,.2f}
Profit Margin: {profit_margin:.1f}%
Revenue Growth: {revenue_growth:+.1f}%
{"✓ Strong profitability - maintain current strategy" if profit_margin > 20 else "⚠ Moderate profitability - optimize costs" if profit_margin > 10 else "⚠ Low profitability - review pricing and costs"}

2. SALES PERFORMANCE
Total Transactions: {current_count}
Average Transaction Value: ${avg_transaction:.2f}
Sales Count Growth: {sales_count_growth:+.1f}%
Revenue Growth: {revenue_growth:+.1f}%
{"✓ Sales growing - maintain momentum" if revenue_growth > 0 else "⚠ Sales declining - review strategy" if revenue_growth < 0 else "→ Sales stable - consider expansion"}

3. PRODUCT PORTFOLIO ANALYSIS
Top Performing Product: {top_product_name}
{"Focus on scaling top performers and expanding best sellers" if revenue_growth > 0 else "Review product mix and pricing strategy for underperformers"}

4. OPERATIONAL EFFICIENCY
Average Transaction Value: ${avg_transaction:.2f}
{"High transaction value indicates strong customer spending" if avg_transaction > 50 else "Consider upselling strategies to increase transaction value" if avg_transaction > 20 else "Low transaction value - review pricing and product mix"}

5. BUSINESS INSIGHTS
{"Maintain momentum with top products and current pricing strategy. Business is performing well with positive growth." if revenue_growth > 0 and profit_margin > 15 else "Optimize costs and promote high-margin items to improve profitability" if profit_margin < 15 else "Stable performance - consider product expansion and marketing initiatives"}

6. STRATEGIC RECOMMENDATIONS
{"Scale top products, maintain pricing strategy, focus on customer retention, and explore new product lines" if revenue_growth > 0 else "Review pricing strategy, run targeted promotions, focus on customer retention, analyze declining products, and optimize inventory" if revenue_growth < 0 else "Expand product range, improve marketing efforts, explore new markets, and enhance customer experience"}"""
    
    def _build_analysis_prompt(
        self,
        current_total: float,
        previous_total: float,
        current_count: int,
        previous_count: int,
        revenue_growth: float,
        sales_count_growth: float,
        current_products: List[Dict],
        previous_products: List[Dict],
        total_withdrawals: float,
        days: int
    ) -> str:
        """Build a professional accounting prompt for the AI."""
        
        # Pre-calculate ALL insights in Python (AI only interprets)
        net_profit = current_total - total_withdrawals
        profit_margin = (net_profit / current_total * 100) if current_total > 0 else 0
        
        top_product = current_products[0] if current_products else None
        top_product_text = f"{top_product['name']} (${top_product['revenue']:.0f})" if top_product else "None"
        
        # Find declining products (pre-calculated)
        declining_products = []
        previous_dict = {p["name"]: p for p in previous_products}
        for current in current_products[:5]:  # Top 5 only
            name = current["name"]
            if name in previous_dict:
                prev_revenue = previous_dict[name]["revenue"]
                curr_revenue = current["revenue"]
                if prev_revenue > 0:
                    decline = ((curr_revenue - prev_revenue) / prev_revenue) * 100
                    if decline < -10:
                        declining_products.append(f"{name} ({decline:.0f}%)")
        
        decline_text = ", ".join(declining_products[:3]) if declining_products else "None"
        
        # Build comprehensive prompt for complete business performance analysis
        top_3_products = ", ".join([f"{p['name']} (${p['revenue']:.0f})" for p in current_products[:3]])
        avg_transaction = (current_total / current_count) if current_count > 0 else 0
        
        prompt = f"""Provide a COMPLETE OVERALL BUSINESS PERFORMANCE ANALYSIS covering all aspects:

BUSINESS METRICS (Last {days} days):
- Total Revenue: ${current_total:,.2f}
- Net Profit: ${net_profit:,.2f}
- Profit Margin: {profit_margin:.1f}%
- Revenue Growth: {revenue_growth:+.1f}%
- Total Transactions: {current_count}
- Average Transaction Value: ${avg_transaction:.2f}
- Previous Period Revenue: ${previous_total:,.2f}
- Sales Count Growth: {sales_count_growth:+.1f}%

TOP PRODUCTS:
- {top_3_products}

PRODUCT TRENDS:
- Declining Products: {decline_text if decline_text != "None" else "None identified"}

Provide a COMPREHENSIVE analysis covering:
1. FINANCIAL HEALTH - Overall profitability, margins, revenue trends
2. SALES PERFORMANCE - Transaction volume, growth patterns, customer behavior
3. PRODUCT PORTFOLIO - Top performers, declining items, product mix analysis
4. OPERATIONAL EFFICIENCY - Average transaction value, sales frequency
5. BUSINESS INSIGHTS - What's working well, areas of concern, opportunities
6. STRATEGIC RECOMMENDATIONS - Specific actionable steps to improve overall business performance

Be thorough, specific, and provide actionable insights based on the actual data provided."""
        
        return prompt
    
    def _extract_amount_from_message(self, message: str) -> Optional[float]:
        """
        Extract numeric amount from user message.
        Only triggers if amount is mentioned with specific keywords like "where is", "find", "search", "show me", etc.
        This prevents false positives from questions like "What's my revenue for 30 days?"
        """
        # Keywords that indicate user is searching for a specific amount
        search_keywords = [
            r'where.*?\$?\d+', r'find.*?\$?\d+', r'search.*?\$?\d+', 
            r'show.*?\$?\d+', r'look.*?\$?\d+', r'what.*?\$?\d+.*?(transaction|sale|payment|withdrawal|expense)',
            r'\$?\d+.*?(where|find|search|show|transaction|sale|payment)'
        ]
        
        # Check if message contains search keywords with amounts
        message_lower = message.lower()
        has_search_intent = any(re.search(keyword, message_lower, re.IGNORECASE) for keyword in search_keywords)
        
        if not has_search_intent:
            return None
        
        # Remove commas and dollar signs, then find numbers
        cleaned = message.replace(',', '').replace('$', '').replace('USD', '').replace('usd', '')
        
        # Pattern to match currency amounts (must have at least 2 decimal places or be a whole dollar amount)
        patterns = [
            r'\$?(\d+\.\d{2})\b',  # Matches currency format like 100.00, $100.50
            r'\$(\d+)\b',           # Matches $100, $50 (with dollar sign)
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, cleaned)
            if matches:
                # Get the largest number (likely the amount they're asking about)
                amounts = [float(m) for m in matches if float(m) > 0]
                if amounts:
                    return max(amounts)
        
        return None
    
    def _search_amount_in_database(
        self,
        db: Session,
        amount: float,
        tolerance: float = 0.01,
        user: Optional[User] = None,
    ) -> str:
        """
        Directly search for a specific amount across all financial tables.
        Returns formatted results without AI reasoning.
        """
        results = []
        
        # Search in Sales (exact match or close)
        low = amount - tolerance
        high = amount + tolerance
        sales_q = db.query(Sale).filter(
            or_(
                and_(Sale.total >= low, Sale.total <= high),
                and_(Sale.subtotal >= low, Sale.subtotal <= high),
                and_(Sale.discount_total >= low, Sale.discount_total <= high)
            )
        )
        if user is not None:
            sales_q = sales_q.filter(tenant_scope.sale_tenant_match(user))
        sales = sales_q.order_by(desc(Sale.created_at)).limit(10).all()
        
        if sales:
            results.append(f"\n📊 SALES ({len(sales)} found):")
            for sale in sales[:5]:  # Show top 5
                date_str = sale.created_at.strftime('%Y-%m-%d %H:%M') if sale.created_at else 'N/A'
                results.append(f"  • Sale #{sale.id}: ${float(sale.total):.2f} on {date_str}")
                if sale.subtotal == amount or abs(float(sale.subtotal) - amount) < tolerance:
                    results.append(f"    (Subtotal: ${float(sale.subtotal):.2f})")
                if sale.discount_total and abs(float(sale.discount_total) - amount) < tolerance:
                    results.append(f"    (Discount: ${float(sale.discount_total):.2f})")
        
        # Search in Payments
        payments_q = db.query(Payment).filter(
            and_(Payment.amount >= low, Payment.amount <= high)
        ).join(Sale)
        if user is not None:
            payments_q = payments_q.filter(tenant_scope.sale_tenant_match(user))
        payments = payments_q.order_by(desc(Sale.created_at)).limit(10).all()
        
        if payments:
            results.append(f"\n💳 PAYMENTS ({len(payments)} found):")
            for payment in payments[:5]:
                date_str = payment.sale.created_at.strftime('%Y-%m-%d %H:%M') if payment.sale.created_at else 'N/A'
                results.append(f"  • ${float(payment.amount):.2f} via {payment.method} (Sale #{payment.sale_id}) on {date_str}")
        
        # Search in Withdrawals/Expenses
        wd_q = db.query(Withdrawal).filter(
            and_(Withdrawal.amount >= low, Withdrawal.amount <= high)
        )
        if user is not None:
            wd_q = tenant_scope.filter_withdrawals(db, user).filter(
                and_(Withdrawal.amount >= low, Withdrawal.amount <= high)
            )
        withdrawals = wd_q.order_by(desc(Withdrawal.created_at)).limit(10).all()
        
        if withdrawals:
            results.append(f"\n💰 WITHDRAWALS/EXPENSES ({len(withdrawals)} found):")
            for w in withdrawals[:5]:
                date_str = w.created_at.strftime('%Y-%m-%d %H:%M') if w.created_at else 'N/A'
                results.append(f"  • ${float(w.amount):.2f} - {w.reason or 'No reason'} on {date_str}")
        
        # Search in Sale Items (line totals)
        si_q = db.query(SaleItem).join(Sale).filter(
            and_(SaleItem.line_total >= low, SaleItem.line_total <= high)
        )
        if user is not None:
            si_q = si_q.filter(tenant_scope.sale_tenant_match(user))
        sale_items = si_q.order_by(desc(Sale.created_at)).limit(10).all()
        
        if sale_items:
            results.append(f"\n🛒 SALE ITEMS ({len(sale_items)} found):")
            for item in sale_items[:5]:
                date_str = item.sale.created_at.strftime('%Y-%m-%d %H:%M') if item.sale.created_at else 'N/A'
                results.append(f"  • {item.product.name if item.product else 'Unknown'}: ${float(item.line_total):.2f} (Sale #{item.sale_id}) on {date_str}")
        
        # Search in Layby Transactions
        layby_q = (
            db.query(LaybyTransaction)
            .join(LaybyCustomer, LaybyTransaction.customer_id == LaybyCustomer.id)
            .filter(
                or_(
                    and_(LaybyTransaction.total_amount >= low, LaybyTransaction.total_amount <= high),
                    and_(LaybyTransaction.balance >= low, LaybyTransaction.balance <= high),
                )
            )
        )
        if user is not None:
            if user.tenant_id is None:
                layby_q = layby_q.filter(LaybyCustomer.tenant_id.is_(None))
            else:
                layby_q = layby_q.filter(LaybyCustomer.tenant_id == user.tenant_id)
        layby = layby_q.order_by(desc(LaybyTransaction.created_at)).limit(10).all()
        
        if layby:
            results.append(f"\n📦 LAYBY ({len(layby)} found):")
            for lb in layby[:5]:
                date_str = lb.created_at.strftime('%Y-%m-%d %H:%M') if lb.created_at else 'N/A'
                results.append(
                    f"  • Layby #{lb.id}: Total ${float(lb.total_amount):.2f}, Balance ${float(lb.balance):.2f} on {date_str}"
                )
        
        if results:
            return f"Found ${amount:.2f} in your system:\n" + "\n".join(results)
        else:
            return f"No transactions found matching ${amount:.2f} in your system."
    
    def _precompute_business_analysis(self, db: Session, days: int = 30, user: Optional[User] = None) -> Dict[str, Any]:
        """
        Pre-compute all business analysis data for instant chat responses.
        This data is cached and reused for all chat questions.
        """
        # Ensure cache exists (defensive check for backwards compatibility)
        if not hasattr(self, '_precomputed_analysis_cache'):
            self._precomputed_analysis_cache = {}
        
        scope_key = (
            f"u{user.id}:t{user.tenant_id}" if user is not None else "global"
        )
        cache_key = f"{days}:{scope_key}"
        if cache_key in self._precomputed_analysis_cache:
            return self._precomputed_analysis_cache[cache_key]
        
        logger.info(f"Pre-computing business analysis for {days} days...")
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)
        
        # Get all essential data in parallel queries
        # 1. Sales stats
        sales_agg = db.query(
            func.count(Sale.id).label('count'),
            func.sum(Sale.total).label('revenue')
        ).filter(
            and_(Sale.created_at >= start_date, Sale.created_at < end_date)
        )
        if user is not None:
            sales_agg = sales_agg.filter(tenant_scope.sale_tenant_match(user))
        sales_data = sales_agg.first()
        
        revenue = float(sales_data.revenue or 0)
        sales_count = sales_data.count or 0
        
        # 2. Expenses
        exp_agg = db.query(
            func.sum(Withdrawal.amount).label('total')
        ).filter(
            and_(Withdrawal.created_at >= start_date, Withdrawal.created_at < end_date)
        )
        if user is not None:
            exp_agg = exp_agg.filter(tenant_scope.withdrawal_tenant_match(user))
        expenses_data = exp_agg.first()
        expenses = float(expenses_data.total or 0)
        
        # 3. Profit calculations
        profit = revenue - expenses
        profit_margin = (profit / revenue * 100) if revenue > 0 else 0
        
        # 4. Revenue growth
        prev_start_date = start_date - timedelta(days=days)
        prev_agg = db.query(
            func.sum(Sale.total).label('revenue')
        ).filter(
            and_(Sale.created_at >= prev_start_date, Sale.created_at < start_date)
        )
        if user is not None:
            prev_agg = prev_agg.filter(tenant_scope.sale_tenant_match(user))
        prev_sales_data = prev_agg.first()
        previous_revenue = float(prev_sales_data.revenue or 0)
        revenue_growth = ((revenue - previous_revenue) / previous_revenue * 100) if previous_revenue > 0 else 0
        
        # 5. Top products with cost_price for profit calculation
        top_q = (
            db.query(
            SaleItem.product_id,
            Product.name,
            func.sum(SaleItem.quantity).label('total_qty'),
            func.sum(SaleItem.line_total).label('total_revenue'),
            Product.selling_price,
            Product.cost_price,
            Product.stock_qty
        ).join(
            Product, SaleItem.product_id == Product.id
        ).join(
            Sale, SaleItem.sale_id == Sale.id
        ).filter(
            and_(Sale.created_at >= start_date, Sale.created_at < end_date)
        )
        )
        if user is not None:
            top_q = top_q.filter(
                tenant_scope.sale_tenant_match(user),
                tenant_scope.product_tenant_match(user),
            )
        top_products_query = (
            top_q.group_by(
            SaleItem.product_id, Product.name, Product.selling_price, Product.cost_price, Product.stock_qty
        ).order_by(
            desc('total_revenue')
        ).limit(15).all()
        )
        
        all_products_data = []
        for item in top_products_query:
            selling_price = float(item.selling_price or 0)
            cost_price = float(item.cost_price or 0)
            profit_per_unit = selling_price - cost_price
            profit_percentage = (profit_per_unit / selling_price * 100) if selling_price > 0 else 0
            
            all_products_data.append({
                "name": item.name,
                "selling_price": selling_price,
                "cost_price": cost_price,
                "profit_per_unit": profit_per_unit,
                "profit_percentage": profit_percentage,
                "stock_qty": float(item.stock_qty or 0),
                "quantity_sold": float(item.total_qty or 0),
                "total_revenue": float(item.total_revenue or 0)
            })
        
        # 6. All product names for matching
        ap_q = db.query(Product.name).filter(Product.is_active == True)  # noqa: E712
        if user is not None:
            ap_q = ap_q.filter(tenant_scope.product_tenant_match(user))
        all_products = ap_q.all()
        product_names = [p.name.lower() for p in all_products]
        
        # Cache the results
        analysis_data = {
            "revenue": revenue,
            "expenses": expenses,
            "profit": profit,
            "profit_margin": profit_margin,
            "sales_count": sales_count,
            "revenue_growth": revenue_growth,
            "previous_revenue": previous_revenue,
            "all_products_data": all_products_data,
            "product_names": product_names,
            "top_products": [p["name"] for p in all_products_data[:5]],
            "top_products_text": ", ".join([p["name"] for p in all_products_data[:5]]),
            "days": days
        }
        
        self._precomputed_analysis_cache[cache_key] = analysis_data
        logger.info("Business analysis pre-computed and cached")
        return analysis_data
    
    def _build_reasoned_answer(
        self,
        revenue: float,
        profit: float,
        profit_margin: float,
        revenue_growth: float,
        sales_count: int,
        top_products_text: str,
        days: int,
        user_message: str = "",
    ) -> str:
        """Build a short answer that reasons from the data so the user always gets an answer."""
        user_lower = (user_message or "").lower()
        top_line = f" Top sellers: {top_products_text}." if top_products_text else ""
        # One-sentence fact base
        base = f"Based on your data for the last {days} days: Revenue ${revenue:,.2f}, profit ${profit:,.2f} ({profit_margin:.1f}% margin), revenue growth {revenue_growth:+.1f}%, {int(sales_count)} transactions.{top_line}"
        # Conclude from the numbers
        if profit_margin > 20 and revenue_growth > 0:
            conclusion = " So your business is in strong shape—keep scaling top products and retaining customers."
        elif profit_margin > 20:
            conclusion = " So profitability is solid; focus on driving more sales and promoting best sellers."
        elif profit_margin > 10 and revenue_growth > 0:
            conclusion = " So you're growing with reasonable margins; consider promoting higher-margin items to improve profit."
        elif profit_margin > 10:
            conclusion = " So margins are okay; look at costs and pricing, and push your top products."
        elif revenue_growth < 0:
            conclusion = " So revenue is down; review pricing, run promotions, and focus on your best-selling products to turn it around."
        elif revenue_growth > 0:
            conclusion = " So sales are growing; work on cost control and high-margin items to improve profit."
        else:
            conclusion = " So performance is stable; consider expanding range or marketing to grow revenue and profit."
        return base + conclusion
    
    def chat_with_sales_context(
        self,
        db: Session,
        user_message: str,
        days: int = 30,
        user: Optional[User] = None,
    ) -> Optional[str]:
        """
        Chat with AI about sales, marketing, and business. All answers come from Ollama;
        pre-computed business data is sent as context only. No premeditated/canned answers.
        
        Args:
            db: Database session
            user_message: User's chat message
            days: Number of days of sales data to include in context
        
        Returns:
            AI response or None if error
        """
        try:
            user_lower = (user_message or "").lower().strip()

            # Pre-compute business data only for context (all answers come from Ollama)
            analysis = self._precompute_business_analysis(db, days, user=user)

            # Extract pre-computed values
            revenue = analysis["revenue"]
            expenses = analysis["expenses"]
            profit = analysis["profit"]
            profit_margin = analysis["profit_margin"]
            sales_count = analysis["sales_count"]
            revenue_growth = analysis["revenue_growth"]
            all_products_data = analysis["all_products_data"]
            product_names = analysis["product_names"]
            top_products_text = analysis["top_products_text"]
            # All answers come from Ollama (data above is context only; no premeditated replies)

            # Optional: direct DB lookup when user asks about a specific dollar amount
            amount = self._extract_amount_from_message(user_message)
            
            if amount and amount > 0:
                # Direct database search - no AI needed, instant response
                logger.info(f"Amount detected: ${amount:.2f}, performing direct database search")
                try:
                    search_result = self._search_amount_in_database(db, amount, user=user)
                    return search_result
                except Exception as e:
                    logger.error(f"Error in amount search: {e}", exc_info=True)
                    # Fall through to AI chat if search fails
            
            # All data is already pre-computed - no database queries needed!
            # Check if question mentions a specific product (using pre-computed product names)
            mentioned_product = None
            
            # More flexible matching: handle plurals, partial matches
            for prod_name in product_names:
                # Check for exact match
                if prod_name in user_lower:
                    mentioned_product = prod_name
                    break
                
                # Check word-by-word matching (handles plurals better)
                prod_words = prod_name.split()
                user_words = user_lower.split()
                
                # For multi-word products, check if all words match (allowing plurals)
                if len(prod_words) >= 2:
                    all_words_match = True
                    for prod_word in prod_words:
                        word_found = False
                        for user_word in user_words:
                            # Exact match
                            if prod_word == user_word:
                                word_found = True
                                break
                            # Plural: user ends with 'ies', product ends with 'y'
                            if prod_word.endswith('y') and user_word.endswith('ies'):
                                if prod_word[:-1] == user_word[:-3]:
                                    word_found = True
                                    break
                            # Plural: user ends with 's' or 'es', product is singular
                            if user_word.endswith('s'):
                                user_singular = user_word.rstrip('s').rstrip('e')
                                if user_singular == prod_word:
                                    word_found = True
                                    break
                        if not word_found:
                            all_words_match = False
                            break
                    if all_words_match:
                        mentioned_product = prod_name
                        break
                else:
                    # Single word product - check for plural forms
                    prod_word = prod_words[0] if prod_words else prod_name
                    for user_word in user_words:
                        if prod_word == user_word:
                            mentioned_product = prod_name
                            break
                        # Check plural variations
                        if user_word.endswith('ies') and prod_word.endswith('y'):
                            if prod_word[:-1] == user_word[:-3]:
                                mentioned_product = prod_name
                                break
                        if user_word.endswith('s'):
                            user_singular = user_word.rstrip('s').rstrip('e')
                            if user_singular == prod_word:
                                mentioned_product = prod_name
                                break
                    if mentioned_product:
                        break
            
            # Prepare fallback advice for reasoning questions (used when AI fails or times out)
            fallback_advice = None
            advice_keywords = [
                'what should i', 'what can i', 'how can i', 'advice', 'recommend', 'suggest',
                'help me', 'what do', 'improve', 'better', 'increase', 'boost', 'why', 'explain',
                'what do you think', 'how do we', 'how should we', 'what would you', 'reason', 'opinion',
                'tips', 'business tips', 'give me tips', 'ideas', 'expand', 'expansion', 'grow', 'growth'
            ]
            is_advice_question = any(keyword in user_lower for keyword in advice_keywords)
            
            if is_advice_question and not mentioned_product:
                if revenue == 0 or sales_count == 0:
                    # If they're asking what products to add, use their current product list
                    add_to_stock_keywords = [
                        'add to stock', 'products to add', 'add to my stock', 'what to add',
                        'products that can add', 'stock that might', 'increase sales', 'new products'
                    ]
                    is_add_products_question = any(k in user_lower for k in add_to_stock_keywords)
                    if is_add_products_question and all_products_data:
                        names_list = ", ".join(p["name"] for p in all_products_data[:12])
                        if len(all_products_data) > 12:
                            names_list += f" (and {len(all_products_data) - 12} more)"
                        fallback_advice = (
                            f"You don't have sales data yet. Your current products: {names_list}. "
                            "To increase sales, consider adding complementary items (e.g. accessories, consumables) "
                            "or more variety in the same categories so customers have more choice. "
                            "Once you have sales, ask again and I can suggest based on what sells best."
                        )
                    else:
                        # If they're asking for tips to improve sales, give a sales-focused list
                        improve_sales_keywords = [
                            'tips to improve sales', 'improve sales', 'increase sales', 'boost sales',
                            'tips for sales', 'how to improve sales', 'ways to improve sales', 'sell more',
                            'ideas to increase sales', 'ideas to improve sales', 'ideas for sales'
                        ]
                        if any(k in user_lower for k in improve_sales_keywords):
                            fallback_advice = (
                                "You don't have sales data yet. Here are practical tips to improve sales:\n\n"
                                "• Display & visibility – Put bestsellers or key items where customers see them first; clear signage and tidy shelves help.\n"
                                "• Pricing – Set clear, visible prices; consider a small promotion or bundle (e.g. buy 2 get a discount) to encourage larger baskets.\n"
                                "• Stock – Keep bestsellers in stock and avoid empty spaces; restock regularly.\n"
                                "• Service – Greet customers, answer questions, and suggest add-ons (e.g. “Would you like X with that?”).\n"
                                "• Feedback – Ask what customers look for or what would bring them back; use that to adjust range and offers.\n\n"
                                "Once you have sales in the system, ask me again and I can give advice based on your numbers."
                            )
                        else:
                            fallback_advice = (
                                "You don't have sales data yet. Here are business tips: set clear pricing, "
                                "promote your products, keep inventory tidy, and give good customer service. "
                                "Once you have sales, ask 'summary', 'profit', or 'revenue' for advice based on your numbers."
                            )
                elif profit_margin > 20:
                    fallback_advice = f"Your profit margin is strong at {profit_margin:.1f}%. Focus on scaling top products and expanding your best sellers."
                elif profit_margin > 10:
                    fallback_advice = f"Your profit margin is {profit_margin:.1f}%. Consider optimizing costs and promoting high-margin products."
                elif revenue_growth > 0:
                    fallback_advice = f"Revenue is growing {revenue_growth:.1f}%. Maintain momentum by focusing on your top-performing products."
                elif revenue_growth < 0:
                    fallback_advice = f"Revenue declined {abs(revenue_growth):.1f}%. Review pricing, run promotions, and focus on customer retention."
                else:
                    fallback_advice = f"Revenue is stable. Profit margin: {profit_margin:.1f}%. Consider expanding product range or improving marketing."
            
            # Build context and call Ollama for every question (no premeditated factual answers)
            # Use pre-computed product data - no database queries!
            top_3_products = all_products_data[:3]
            top_prods = ", ".join([f"{p['name']}(${p['selling_price']:.2f}, Stock:{p['stock_qty']:.0f}, Sold:{p['quantity_sold']:.0f}, Rev:${p['total_revenue']:.0f})" for p in top_3_products]) if top_3_products else "None"
            
            # Build products context from pre-computed data
            products_context = ""
            if all_products_data:
                products_context = "\n- Products in system (Name, Price, Stock, Sold, Revenue): " + "\n".join([f"  - {p['name']} (${p['selling_price']:.2f}, Stock:{p['stock_qty']:.0f}, Sold:{p['quantity_sold']:.0f}, Rev:${p['total_revenue']:.2f})" for p in all_products_data[:15]])
            
            # Build expert-level context with system instructions using pre-computed data
            profit_margin_pct = profit_margin
            
            reasoned_fallback = self._build_reasoned_answer(
                revenue, profit, profit_margin, revenue_growth, sales_count, top_prods[:80], days, user_message
            )
            context = f"""You are a business advisor with FULL ACCESS to this business's POS data. You MUST think first, then answer.

RULES:
1. THINK FIRST: Before answering, reason step by step from the business data below. What do the numbers tell you? What is strong or weak? What follows from that?
2. Then give your answer in two parts: (a) one or two sentences of brief reasoning from the data, then (b) a clear, specific recommendation or answer (2-4 sentences).
3. NEVER say "I don't have access" or "I cannot access"—you have ALL the data.
4. Use ONLY this POS data; no external or real-world information.
5. If asked about a product, use the product list below. For prices use selling_price, for stock use stock_qty.
6. Be specific: use the actual numbers (revenue, margin, top products) in your reasoning, then give actionable advice.

BUSINESS DATA (Last {days} days):
- Revenue: ${revenue:,.2f}
- Profit: ${profit:,.2f}
- Profit Margin: {profit_margin_pct:.1f}%
- Revenue Growth: {revenue_growth:+.1f}%
- Sales Count: {sales_count} transactions
- Top Products: {top_prods[:100]}{products_context}

QUESTION: {user_message}

First think through what the data implies, then give your reasoning and answer:"""
            
            # Always use Ollama to respond; fallback only when Ollama is unavailable or fails
            if not self._check_ollama_available(retries=1):
                logger.warning("Ollama is not available for chat - returning reasoned answer from data")
                return fallback_advice if fallback_advice else reasoned_fallback
            
            logger.info(f"Calling Ollama chat with prompt length: {len(context)}")
            try:
                response = self._call_ollama_chat(context)
                
                if response is None or not response.strip():
                    logger.warning("Ollama chat returned None or empty - returning reasoned answer from data")
                    return fallback_advice if fallback_advice else reasoned_fallback
                
                logger.info(f"Chat response received, length: {len(response)} characters")
                
                # Check if AI says it doesn't have access to data - this is WRONG, replace it
                response_lower = response.lower().strip()
                no_access_phrases = [
                    "i don't have access",
                    "i cannot access",
                    "i do not have access",
                    "i don't have real-time",
                    "i cannot access real-time",
                    "i don't have access to real-time",
                    "as an ai language model, i do not have access",
                    "i do not have access to real-time stock market",
                    "i do not have access to real-time financial",
                    "i don't have access to stock market",
                    "i don't have access to financial information"
                ]
                if any(phrase in response_lower for phrase in no_access_phrases):
                    logger.warning("AI incorrectly said it doesn't have access - replacing with data-based response")
                    # Return a response using the actual data
                    if mentioned_product:
                        # Try to find the product in the products list
                        product_info = f"Based on the POS data, {mentioned_product} is in your system. "
                        if top_prods:
                            product_info += f"Your top products are: {top_prods[:100]}. "
                        product_info += f"Your revenue is ${revenue:,.2f} with {profit_margin_pct:.1f}% profit margin. Use this data to answer the question."
                        return product_info
                    else:
                        return f"Based on your POS data: Revenue ${revenue:,.2f}, Profit ${profit:,.2f} ({profit_margin_pct:.1f}%), Growth {revenue_growth:+.1f}%. Top products: {top_prods[:100]}. Use this data to answer: {user_message}"
                
                # Check if Ollama gave a generic/unhelpful response for advice questions
                # Only replace if question is generic (no specific product mentioned)
                if is_advice_question and fallback_advice and not mentioned_product:
                    # Detect generic/unhelpful responses
                    generic_phrases = [
                        "i'm sorry",
                        "i cannot provide",
                        "i don't know",
                        "i'm not sure",
                        "i cannot help",
                        "i cannot assist",
                        "i'm unable to",
                        "i don't have enough information",
                        "i cannot answer"
                    ]
                    if any(phrase in response_lower for phrase in generic_phrases):
                        logger.info("Ollama returned generic response, using fallback advice instead")
                        return fallback_advice
                # For product-specific questions, always return Ollama's response (even if generic)
                # because it might contain product-specific information
                
                return response
            except requests.exceptions.Timeout:
                logger.warning("Ollama chat timed out - returning reasoned answer from data")
                return fallback_advice if fallback_advice else reasoned_fallback
            except Exception as e:
                logger.error(f"Error in Ollama chat call: {e}", exc_info=True)
                return fallback_advice if fallback_advice else reasoned_fallback
            
        except Exception as e:
            logger.error(f"Error in chat_with_sales_context: {e}", exc_info=True)
            # Never return None so the API always has a string to show
            return f"Error processing your request: {str(e)}. Please try again."
    
    def _call_ollama_chat(self, prompt: str) -> Optional[str]:
        """
        Call Ollama for chat using subprocess (faster) or HTTP API (fallback).
        All data pre-calculated - AI only interprets.
        """
        if USE_SUBPROCESS:
            return self._call_ollama_chat_subprocess(prompt)
        else:
            return self._call_ollama_chat_http(prompt)
    
    def _call_ollama_chat_subprocess(self, prompt: str) -> Optional[str]:
        """
        Call Ollama CLI via subprocess for chat - FASTER on Raspberry Pi 5.
        Output is captured (non-streaming in practice).
        """
        try:
            logger.debug(f"Calling Ollama chat via subprocess, prompt: {len(prompt)} chars")
            
            # Use ollama run (no --no-stream flag needed, output is captured)
            # Extract model name - CLI uses format "phi:2.7b", "phi:Q4_K_M", or just "phi"
            # Ollama CLI accepts the full model name with tag
            model_name = self.model  # Use full name like "phi:2.7b" or "phi:Q4_K_M"
            
            # Try subprocess first
            try:
                result = subprocess.run(
                    ["ollama", "run", model_name],
                    input=prompt.encode('utf-8'),
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=OLLAMA_CHAT_TIMEOUT,
                    text=False
                )
                
                if result.returncode == 0:
                    response_text = result.stdout.decode('utf-8', errors='ignore').strip()
                    if response_text:
                        logger.info(f"Ollama chat subprocess successful, response length: {len(response_text)} characters")
                        return response_text
                    else:
                        logger.warning("Ollama chat subprocess returned empty response, falling back to HTTP")
                        return self._call_ollama_chat_http(prompt)
                else:
                    error_msg = result.stderr.decode('utf-8', errors='ignore')
                    logger.warning(f"Ollama chat subprocess error (code {result.returncode}): {error_msg[:200]}, falling back to HTTP")
                    return self._call_ollama_chat_http(prompt)
                    
            except subprocess.TimeoutExpired:
                logger.warning(f"Ollama chat subprocess timed out after {OLLAMA_CHAT_TIMEOUT} seconds, falling back to HTTP")
                return self._call_ollama_chat_http(prompt)
            except FileNotFoundError:
                logger.warning("Ollama CLI not found. Falling back to HTTP API.")
                return self._call_ollama_chat_http(prompt)
                
        except Exception as e:
            logger.warning(f"Error calling Ollama chat subprocess: {e}, falling back to HTTP")
            # Fallback to HTTP API
            return self._call_ollama_chat_http(prompt)
    
    def _call_ollama_chat_http(self, prompt: str) -> Optional[str]:
        """
        Fallback: Call Ollama via HTTP API for chat.
        """
        try:
            url = f"{self.base_url}/api/generate"
            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "keep_alive": "30m",  # Keep model loaded so it's always available
                "options": {
                    "temperature": 0.7,  # Higher for more creative, detailed responses
                    "top_p": 0.9,  # Higher for more diverse responses
                    "num_predict": 280,  # Short enough to finish in timeout; prompt asks for 2-5 sentences
                    "top_k": 40,  # Higher for better selection
                    "repeat_penalty": 1.1,
                    "num_ctx": 2048,  # Increased context for better understanding
                    "num_thread": 4,
                    "numa": False,
                }
            }
            
            logger.debug(f"Calling Ollama chat HTTP API (fallback), prompt: {len(prompt)} chars")
            
            response = requests.post(
                url,
                json=payload,
                timeout=OLLAMA_CHAT_TIMEOUT
            )
            
            if response.status_code == 200:
                result = response.json()
                response_text = result.get("response", "").strip()
                if response_text:
                    logger.info(f"Chat response generated, length: {len(response_text)} characters")
                    return response_text
                else:
                    logger.warning("Ollama HTTP API returned empty chat response")
                    return None
            else:
                logger.error(f"Ollama HTTP API error: {response.status_code} - {response.text[:500]}")
                return None
                
        except requests.exceptions.Timeout:
            logger.error(f"Ollama chat HTTP request timed out after {OLLAMA_CHAT_TIMEOUT} seconds")
            # Return None so the calling function can use fallback_advice
            return None
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Ollama HTTP API connection error: {e}")
            return None
        except Exception as e:
            logger.error(f"Error calling Ollama chat HTTP API: {e}", exc_info=True)
            return None


# Global instance
ai_service = AIService()

