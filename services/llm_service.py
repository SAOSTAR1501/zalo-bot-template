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
        semantic_context: str = "",
        image_data: Optional[str] = None
    ) -> str:
        """
        Dispatches prompt to the configured LLM provider with rolling summary, semantic RAG memory, knowledge base, and optional image.
        """
        if self.provider == "ollama" and (settings.OLLAMA_API_KEY or "localhost" in settings.OLLAMA_BASE_URL or "127.0.0.1" in settings.OLLAMA_BASE_URL):
            return self._ollama_reply(prompt, history, knowledge_base, rolling_summary, semantic_context, image_data=image_data)
        elif self.provider == "gemini" and settings.GEMINI_API_KEY:
            return self._gemini_reply(prompt, history, knowledge_base, rolling_summary, semantic_context, image_data=image_data)
        elif self.provider in ["openai", "deepseek"] and settings.OPENAI_API_KEY:
            return self._openai_reply(prompt, history, knowledge_base, rolling_summary, semantic_context, image_data=image_data)
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
            "Bạn là Bot Sao Assistant trên Zalo, trợ lý AI thông minh và tận tâm của Admin Mai Công Sao.\n"
            "Hãy trả lời ngắn gọn, súc tích, thân thiện bằng tiếng Việt.\n"
            "LƯU Ý ĐỊNH DẠNG: TUYỆT ĐỐI KHÔNG sử dụng bất kỳ cú pháp markdown nào như **in đậm**, *in nghiêng*, dấu gạch dưới _, hoặc dấu thăng #, vì ứng dụng Zalo hiển thị dạng chữ thô và không hỗ trợ markdown. "
            "Nếu liệt kê các ý, hãy dùng dấu gạch đầu dòng hoặc dấu chấm tròn •.\n"
            "Trong nhóm chat, các tin nhắn có thể có tiền tố 'Tên_thành_viên: nội dung' để bạn phân biệt người đang nói chuyện.\n\n"
            "TƯ DUY PHẢN BIỆN & CHÍNH XÁC: Khi người dùng đưa ra nhận định hoặc thử thách kiến thức, hãy luôn đối chiếu với sự thật khách quan. "
            "Nếu thông tin từ người dùng là giả thuyết, tin đồn hoặc chưa chính xác, hãy lịch sự đính chính và phân tích khách quan, TUYỆT ĐỐI KHÔNG xu nịnh hay vội vã nhận lỗi về điều mình không sai.\n\n"
            "--- HỆ THỐNG LỆNH CỦA BOT (HÃY HƯỚNG DẪN CHÍNH XÁC KHI ĐƯỢC HỎI) ---\n"
            "• /menu hoặc /help: Mở menu chức năng\n"
            "• /save <nội dung>: Lưu kiến thức quan trọng vào kho nhóm\n"
            "• /knowledge: Xem danh sách kiến thức đã lưu của nhóm\n"
            "• /summary: Tóm tắt nội dung thảo luận 12 giờ qua\n"
            "• /clear: Xóa lịch sử trò chuyện ngắn hạn gần đây\n\n"
            "👑 LỆNH DÀNH RIÊNG CHO ADMIN (MAI CÔNG SAO):\n"
            "• /accept <user_id> [gói]: Duyệt hoặc đổi gói cho người dùng.\n"
            "  - Các gói hỗ trợ: 10, 20, 50, 100 (cấp số tin), homnay (24h), tuannay (7 ngày), thangnay (30 ngày), vinhvien (vĩnh viễn), reset (về 10 tin mặc định).\n"
            "  - Ví dụ chuyển thành 10 tin: /accept <user_id> 10\n"
            "• /block <user_id>: Chặn vĩnh viễn người dùng\n"
            "• /unblock <user_id>: Mở khóa người dùng\n"
            "• /users: Xem danh sách người dùng và hạn mức tin nhắn"
        )
        if semantic_context:
            prompt += f"\n\n--- BỘ NHỚ TRI THỨC VĨNH VIỄN (SEMANTIC MEMORY) ---\n{semantic_context}\n(Đây là các thông tin, sự thật hoặc quy định được lưu trữ lâu dài của nhóm)."
        if rolling_summary:
            prompt += f"\n\n--- TÓM TẮT BỐI CẢNH HỘI THOẠI TRƯỚC ĐÓ ---\n{rolling_summary}"
        if knowledge_base:
            prompt += f"\n\n--- KIẾN THỨC ĐÃ LƯU TRỮ CỦA NHÓM ---\n{knowledge_base}\n(Hãy ưu tiên sử dụng kiến thức trên để trả lời các câu hỏi liên quan)."
        return prompt

    def _ollama_reply(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        knowledge_base: str = "",
        rolling_summary: str = "",
        semantic_context: str = "",
        image_data: Optional[str] = None
    ) -> str:
        url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"

        messages = [{"role": "system", "content": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context)}]
        if history:
            messages.extend(history)

        # Route to kimi-k2.7-code if image is present
        target_model = settings.VISION_MODEL if image_data else settings.OLLAMA_MODEL

        if image_data:
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data}}
                ]
            }
        else:
            user_msg = {"role": "user", "content": prompt}

        messages.append(user_msg)

        payload = {
            "model": target_model,
            "messages": messages
        }
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=50)
            data = r.json()
            if "choices" in data and len(data["choices"]) > 0:
                return data["choices"][0]["message"]["content"]
            logger.error(f"Ollama/Kimi response error: {data}")
            err = data.get("error", {}).get("message") or data.get("error") or str(data)
            return f"[AI Error]: {err}"
        except Exception as e:
            logger.error(f"Ollama/Kimi call failed: {e}")
            return f"[AI Error]: {e}"

    def _gemini_reply(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        knowledge_base: str = "",
        rolling_summary: str = "",
        semantic_context: str = "",
        image_data: Optional[str] = None
    ) -> str:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
        contents = []
        if history:
            for h in history:
                role = "user" if h["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": h["content"]}]})

        user_parts = [{"text": prompt}]
        if image_data and ";base64," in image_data:
            header, b64_str = image_data.split(";base64,")
            mime_type = header.replace("data:", "").strip() or "image/jpeg"
            user_parts.append({"inlineData": {"mimeType": mime_type, "data": b64_str}})

        contents.append({"role": "user", "parts": user_parts})

        payload = {
            "contents": contents,
            "systemInstruction": {
                "parts": [{"text": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context)}]
            }
        }
        try:
            r = requests.post(url, json=payload, timeout=35)
            data = r.json()
            if "candidates" in data and len(data["candidates"]) > 0:
                return data["candidates"][0]["content"]["parts"][0]["text"]
            logger.error(f"Gemini error: {data}")
            err = data.get("error", {}).get("message", "No response")
            return f"[Gemini Error]: {err}"
        except Exception as e:
            logger.error(f"Gemini call failed: {e}")
            return f"[Gemini Error]: {e}"

    def _openai_reply(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        knowledge_base: str = "",
        rolling_summary: str = "",
        semantic_context: str = "",
        image_data: Optional[str] = None
    ) -> str:
        url = settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        messages = [{"role": "system", "content": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context)}]
        if history:
            messages.extend(history)

        if image_data:
            user_msg = {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": image_data}}
                ]
            }
        else:
            user_msg = {"role": "user", "content": prompt}

        messages.append(user_msg)

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

