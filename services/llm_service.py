import logging
import subprocess
import requests
from typing import List, Dict, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.provider = settings.AI_PROVIDER.lower()

    def generate_reply(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        knowledge_base: str = "",
        rolling_summary: str = "",
        semantic_context: str = ""
    ) -> str:
        """
        Dispatches prompt to the configured LLM provider with rolling summary, semantic RAG memory, and knowledge base.
        """
        if self.provider == "ollama" and (settings.OLLAMA_API_KEY or "localhost" in settings.OLLAMA_BASE_URL or "127.0.0.1" in settings.OLLAMA_BASE_URL):
            return self._ollama_reply(prompt, history, knowledge_base, rolling_summary, semantic_context)
        elif self.provider == "gemini" and settings.GEMINI_API_KEY:
            return self._gemini_reply(prompt, history, knowledge_base, rolling_summary, semantic_context)
        elif self.provider in ["openai", "deepseek"] and settings.OPENAI_API_KEY:
            return self._openai_reply(prompt, history, knowledge_base, rolling_summary, semantic_context)
        elif self.provider == "opencode":
            return self._opencode_reply(prompt)
        
        return f"Bot received: {prompt[:500]}"

    def summarize_conversation(self, previous_summary: str, chunk_text: str) -> str:
        """
        Condenses older messages into a rolling synopsis to save tokens.
        """
        prompt = (
            "Bạn là trợ lý tóm tắt hội thoại. Hãy kết hợp tóm tắt trước đó (nếu có) và phần hội thoại mới dưới đây "
            "thành một đoạn tóm tắt ngắn gọn súc tích trong 2-3 câu. "
            "Ghi nhận rõ tên người và các mốc trao đổi, quyết định quan trọng. "
            "TUYỆT ĐỐI KHÔNG thêm lời dẫn dắt, chỉ đưa ra văn bản tóm tắt thuần tuý.\n\n"
        )
        if previous_summary:
            prompt += f"--- TÓM TẮT TRƯỚC ĐÓ ---\n{previous_summary}\n\n"
        prompt += f"--- ĐOẠN HỘI THOẠI MỚI ---\n{chunk_text}"

        try:
            if self.provider == "ollama" and (settings.OLLAMA_API_KEY or "localhost" in settings.OLLAMA_BASE_URL):
                url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
                if settings.OLLAMA_API_KEY:
                    headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"
                payload = {
                    "model": settings.OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": "Tóm tắt ngắn gọn, súc tích, không markdown."},
                        {"role": "user", "content": prompt}
                    ]
                }
                r = requests.post(url, json=payload, headers=headers, timeout=30)
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"].strip()
            elif self.provider == "gemini" and settings.GEMINI_API_KEY:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
                r = requests.post(url, json=payload, timeout=30)
                data = r.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            elif self.provider in ["openai", "deepseek"] and settings.OPENAI_API_KEY:
                url = settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
                headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": settings.OPENAI_MODEL,
                    "messages": [{"role": "user", "content": prompt}]
                }
                r = requests.post(url, json=payload, headers=headers, timeout=30)
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Error calling LLM for summarization: {e}")
        return previous_summary or chunk_text[:200]

    def _build_system_prompt(self, knowledge_base: str = "", rolling_summary: str = "", semantic_context: str = "") -> str:
        prompt = (
            "Bạn là Bot Sao Assistant trên Zalo. "
            "Hãy trả lời ngắn gọn, súc tích, thân thiện bằng tiếng Việt. "
            "LƯU Ý ĐỊNH DẠNG: TUYỆT ĐỐI KHÔNG sử dụng bất kỳ cú pháp markdown nào như **in đậm**, *in nghiêng*, dấu gạch dưới _, hoặc dấu thăng #, vì ứng dụng Zalo hiển thị dạng chữ thô và không hỗ trợ markdown. "
            "Nếu liệt kê các ý, hãy dùng dấu gạch đầu dòng hoặc dấu chấm tròn •. "
            "Trong nhóm chat, các tin nhắn có thể có tiền tố 'Tên_thành_viên: nội dung' để bạn phân biệt người đang nói chuyện.\n\n"
            "TƯ DUY PHẢN BIỆN & CHÍNH XÁC: Khi người dùng đưa ra nhận định hoặc thử thách kiến thức, hãy luôn đối chiếu với sự thật khách quan. "
            "Nếu thông tin từ người dùng là giả thuyết, tin đồn hoặc chưa chính xác, hãy lịch sự đính chính và phân tích khách quan, TUYỆT ĐỐI KHÔNG xu nịnh hay vội vã nhận lỗi về điều mình không sai."
        )
        if semantic_context:
            prompt += f"\n\n--- BỘ NHỚ TRI THỨC VĨNH VIỄN (SEMANTIC MEMORY) ---\n{semantic_context}\n(Đây là các thông tin, sự thật hoặc quy định được lưu trữ lâu dài của nhóm)."
        if rolling_summary:
            prompt += f"\n\n--- TÓM TẮT BỐI CẢNH HỘI THOẠI TRƯỚC ĐÓ ---\n{rolling_summary}"
        if knowledge_base:
            prompt += f"\n\n--- KIẾN THỨC ĐÃ LƯU TRỮ CỦA NHÓM ---\n{knowledge_base}\n(Hãy ưu tiên sử dụng kiến thức trên để trả lời các câu hỏi liên quan)."
        return prompt

    def _ollama_reply(self, prompt: str, history: Optional[List[Dict[str, str]]] = None, knowledge_base: str = "", rolling_summary: str = "", semantic_context: str = "") -> str:
        url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"

        messages = [{"role": "system", "content": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context)}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.OLLAMA_MODEL,
            "messages": messages
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=40)
            data = r.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            logger.error(f"Ollama response error: {data}")
            err = data.get("error", {}).get("message") or data.get("error") or str(data)
            return f"[Ollama Error]: {err}"
        except Exception as e:
            logger.error(f"Ollama call failed: {e}")
            return f"[Ollama Error]: {e}"

    def _gemini_reply(self, prompt: str, history: Optional[List[Dict[str, str]]] = None, knowledge_base: str = "", rolling_summary: str = "", semantic_context: str = "") -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        contents = []
        if history:
            for h in history:
                role = "user" if h["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": h["content"]}]})
        contents.append({"role": "user", "parts": [{"text": prompt}]})

        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context)}]
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=30)
            data = r.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            logger.error(f"Gemini error: {data}")
            err = data.get("error", {}).get("message", "No response")
            return f"[Gemini Error]: {err}"
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return f"[Gemini Error]: {e}"

    def _openai_reply(self, prompt: str, history: Optional[List[Dict[str, str]]] = None, knowledge_base: str = "", rolling_summary: str = "", semantic_context: str = "") -> str:
        url = settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        messages = [{"role": "system", "content": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context)}]
        if history:
            messages.extend(history)
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": settings.OPENAI_MODEL,
            "messages": messages
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=40)
            data = r.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            logger.error(f"OpenAI error: {data}")
            err = data.get("error", {}).get("message", str(data))
            return f"[OpenAI Error]: {err}"
        except Exception as e:
            logger.error(f"OpenAI call failed: {e}")
            return f"[OpenAI Error]: {e}"


    def _opencode_reply(self, prompt: str) -> str:
        try:
            result = subprocess.run(
                [settings.OPENCODE_CLI, "prompt", "--non-interactive", prompt],
                capture_output=True, text=True, timeout=120
            )
            return result.stdout or result.stderr or "[opencode no output]"
        except Exception as e:
            logger.error(f"Opencode call failed: {e}")
            return f"[Opencode Error]: {e}"


llm_service = LLMService()

