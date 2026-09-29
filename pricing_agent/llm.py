"""
Minimal LLM client (standard library only) used to write seller-facing explanations.

Providers (picked from environment variables - the key never leaves the server):
  GEMINI_API_KEY   Google Gemini, free tier from https://aistudio.google.com  (default)
  GROQ_API_KEY     Groq, free tier from https://console.groq.com
Optional:
  LLM_PROVIDER     "gemini" or "groq" when both keys are set
  LLM_MODEL        override the model name

Every call can fail (no key, quota, network, bad output). Callers must treat
failure as normal and fall back to the template text.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta"
GROQ_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = {"gemini": "gemini-flash-latest", "groq": "llama-3.3-70b-versatile"}
# tried in order when a model is busy (503), out of quota (429) or retired (404)
GEMINI_FALLBACKS = ["gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-2.5-flash-lite"]
RETRY_STATUSES = (404, 429, 500, 502, 503, 504)
COOLDOWN_SECONDS = 300      # after an auth / quota error, stop calling for a while


class LLMError(Exception):
    pass


def _post(url, headers, body, timeout):
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    return _open(req, timeout)


def _get(url, headers, timeout):
    return _open(urllib.request.Request(url, headers=headers), timeout)


def _open(req, timeout):
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")[:300]
        err = LLMError(f"HTTP {e.code}: {detail}")
        err.status = e.code
        raise err
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"network error: {e}")
    except ValueError as e:
        raise LLMError(f"bad JSON from provider: {e}")


class LLMClient:
    def __init__(self, env=None):
        env = os.environ if env is None else env
        keys = {"gemini": env.get("GEMINI_API_KEY", "").strip(), "groq": env.get("GROQ_API_KEY", "").strip()}
        wanted = env.get("LLM_PROVIDER", "").strip().lower()
        if wanted in keys and keys[wanted]:
            self.provider = wanted
        else:
            self.provider = next((p for p in ("gemini", "groq") if keys[p]), None)
        self._key = keys.get(self.provider, "") if self.provider else ""
        self.model = env.get("LLM_MODEL", "").strip() or DEFAULT_MODEL.get(self.provider, "")
        self._model_checked = bool(env.get("LLM_MODEL", "").strip())
        self._lock = threading.Lock()
        self._cooldown_until = 0.0
        self.last_error = None

    @property
    def enabled(self):
        return bool(self.provider) and time.time() >= self._cooldown_until

    def info(self):
        return {"enabled": bool(self.provider), "provider": self.provider, "model": self.model if self.provider else None}

    # ------------------------------------------------------------------ public
    def complete_json(self, system: str, user: str, timeout: float = 25.0) -> dict:
        """One JSON-mode completion. Raises LLMError on any failure."""
        if not self.provider:
            raise LLMError("no LLM configured")
        if time.time() < self._cooldown_until:
            raise LLMError("LLM paused after a recent auth/quota error")
        try:
            text = self._call(system, user, timeout)
        except LLMError as e:
            self.last_error = str(e)
            if getattr(e, "status", None) in (401, 403, 429):   # bad key, or every model out of quota
                self._cooldown_until = time.time() + COOLDOWN_SECONDS
            raise
        try:
            start, end = text.find("{"), text.rfind("}")
            return json.loads(text[start:end + 1] if start >= 0 else text)
        except ValueError:
            self.last_error = "model did not return valid JSON"
            raise LLMError(self.last_error)

    # ------------------------------------------------------------------ providers
    def _call(self, system, user, timeout):
        if self.provider != "gemini":
            return self._groq(system, user, timeout)
        deadline = time.time() + timeout
        models = list(dict.fromkeys([self.model, *GEMINI_FALLBACKS]))
        last = None
        for i, model in enumerate(models):
            left = deadline - time.time()
            if left < 3:
                break
            try:
                text = self._gemini(model, system, user, left)
                if model != self.model and getattr(last, "status", None) == 404:
                    self.model = model          # the default is gone for good - stick with one that works
                return text
            except LLMError as e:
                last = e
                if getattr(e, "status", None) not in RETRY_STATUSES:
                    raise
        # every known model failed: if they were retired, discover a current one once
        if getattr(last, "status", None) == 404 and not self._model_checked and self._pick_gemini_model(timeout):
            return self._gemini(self.model, system, user, max(5, deadline - time.time()))
        raise last or LLMError("no Gemini model available")

    def _gemini(self, model, system, user, timeout):
        body = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {"temperature": 0.8, "maxOutputTokens": 8192, "responseMimeType": "application/json"},
        }
        out = _post(f"{GEMINI_URL}/models/{model}:generateContent", {"x-goog-api-key": self._key}, body, timeout)
        cands = out.get("candidates") or []
        if not cands:
            raise LLMError(f"no candidates ({out.get('promptFeedback', {}).get('blockReason', 'unknown')})")
        parts = (cands[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        if not text.strip():
            raise LLMError(f"empty response ({cands[0].get('finishReason')})")
        return text

    def _pick_gemini_model(self, timeout):
        with self._lock:
            if self._model_checked:
                return False
            self._model_checked = True
            try:
                data = _get(f"{GEMINI_URL}/models?pageSize=200", {"x-goog-api-key": self._key}, timeout)
            except LLMError:
                return False
            names = [m["name"].split("/", 1)[-1] for m in data.get("models", [])
                     if "generateContent" in m.get("supportedGenerationMethods", [])]
            flash = [n for n in names if "flash" in n and "image" not in n and "tts" not in n and "live" not in n]
            stable = [n for n in flash if "preview" not in n and "exp" not in n] or flash
            if not stable:
                return False
            self.model = _newest(stable)
            return True

    def _groq(self, system, user, timeout):
        body = {"model": self.model, "temperature": 0.8, "response_format": {"type": "json_object"},
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
        out = _post(f"{GROQ_URL}/chat/completions", {"Authorization": f"Bearer {self._key}"}, body, timeout)
        try:
            return out["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            raise LLMError("unexpected response shape")


def _newest(names):
    """Prefer the highest version number, full 'flash' over 'flash-lite'."""
    def key(n):
        m = re.search(r"(\d+(?:\.\d+)?)", n)
        return (float(m.group(1)) if m else 0.0, "lite" not in n, n)
    return max(names, key=key)
