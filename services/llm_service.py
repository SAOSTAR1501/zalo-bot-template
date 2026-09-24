import logging
import re
import subprocess
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import List, Dict, Optional
from config.settings import settings

logger = logging.getLogger(__name__)


class LLMService:
    def __init__(self):
        self.provider = settings.AI_PROVIDER.lower()
        self._init_session()

    def _init_session(self):
        """Initializes a persistent HTTP session with connection pooling and auto-retries."""
        self.session = requests.Session()
        retries = Retry(
            total=3,
            backoff_factor=0.5,
            status_forcelist=[500, 502, 503, 504],
            raise_on_status=False
        )
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=40,
            max_retries=retries
        )
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def generate_reply(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        knowledge_base: str = "",
        rolling_summary: str = "",
        semantic_context: str = "",
        image_data: Optional[str] = None,
        sender_name: str = ""
    ) -> str:
        """
        Dispatches prompt to the configured LLM provider with rolling summary, semantic RAG memory, knowledge base, and optional image.
        """
        try:
            if self.provider == "ollama" and (settings.OLLAMA_API_KEY or "localhost" in settings.OLLAMA_BASE_URL or "127.0.0.1" in settings.OLLAMA_BASE_URL):
                return self._ollama_reply(prompt, history, knowledge_base, rolling_summary, semantic_context, image_data=image_data, sender_name=sender_name)
            elif self.provider == "gemini" and settings.GEMINI_API_KEY:
                return self._gemini_reply(prompt, history, knowledge_base, rolling_summary, semantic_context, image_data=image_data, sender_name=sender_name)
            elif self.provider in ["openai", "deepseek"] and settings.OPENAI_API_KEY:
                return self._openai_reply(prompt, history, knowledge_base, rolling_summary, semantic_context, image_data=image_data, sender_name=sender_name)
            elif self.provider == "opencode":
                return self._opencode_reply(prompt)
        except Exception as e:
            logger.error(f"Error in generate_reply: {e}")
            return "Dạ hiện tại đường truyền kết nối AI đang bị gián đoạn đôi chút, bạn vui lòng gửi lại tin nhắn sau vài giây nhé!"
        
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
                r = self.session.post(url, json=payload, headers=headers, timeout=(5, 30))
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"].strip()
            elif self.provider == "gemini" and settings.GEMINI_API_KEY:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}]}
                r = self.session.post(url, json=payload, timeout=(5, 30))
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
                r = self.session.post(url, json=payload, headers=headers, timeout=(5, 30))
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    return data["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error(f"Error calling LLM for summarization: {e}")
        return previous_summary or chunk_text[:200]

    def needs_web_search(self, query: str) -> bool:
        """
        Ask the LLM whether the user query requires up-to-date/web information.
        Returns True only if the model explicitly answers YES.
        """
        classification_prompt = (
            "Bạn là bộ lọc nhanh. Chỉ trả lời YES hoặc NO, không giải thích.\n"
            "Câu hỏi có cần thông tin thời gian thực hoặc dữ liệu web (thời tiết, giá cả, tin tức, lịch thi đấu, ngày giờ hiện tại, kết quả bóng đá...) không?\n\n"
            f"Câu hỏi: {query}\n\nTrả lời (YES/NO):"
        )
        try:
            if self.provider == "ollama" and (settings.OLLAMA_API_KEY or "localhost" in settings.OLLAMA_BASE_URL or "127.0.0.1" in settings.OLLAMA_BASE_URL):
                url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
                headers = {"Content-Type": "application/json"}
                if settings.OLLAMA_API_KEY:
                    headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"
                payload = {
                    "model": settings.OLLAMA_MODEL,
                    "messages": [
                        {"role": "system", "content": "Chỉ trả lời YES hoặc NO. Không giải thích, không suy luận, không thêm bất kỳ ký tự nào khác."},
                        {"role": "user", "content": classification_prompt}
                    ],
                    "max_tokens": 256,
                    "temperature": 0.0,
                }
                r = self.session.post(url, json=payload, headers=headers, timeout=(5, 10))
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    msg = data["choices"][0].get("message", {})
                    raw = (msg.get("content") or msg.get("reasoning") or "").strip()
                    # Some reasoning models emit reasoning content; normalize answer.
                    answer = re.sub(r"[^A-Za-z]", "", raw).upper()
                    logger.info(f"needs_web_search classification for '{query[:60]}...': raw='{raw}' normalized='{answer}'")
                    return "YES" in answer
            elif self.provider == "gemini" and settings.GEMINI_API_KEY:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{settings.GEMINI_MODEL}:generateContent?key={settings.GEMINI_API_KEY}"
                payload = {
                    "contents": [
                        {"role": "user", "parts": [{"text": classification_prompt}]}
                    ]
                }
                r = self.session.post(url, json=payload, timeout=(5, 10))
                data = r.json()
                if "candidates" in data and len(data["candidates"]) > 0:
                    answer = data["candidates"][0]["content"]["parts"][0]["text"].strip().upper()
                    logger.info(f"needs_web_search classification: {answer}")
                    return answer.startswith("YES")
            elif self.provider in ["openai", "deepseek"] and settings.OPENAI_API_KEY:
                url = settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
                headers = {"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"}
                payload = {
                    "model": settings.OPENAI_MODEL,
                    "messages": [
                        {"role": "system", "content": "Answer only YES or NO."},
                        {"role": "user", "content": classification_prompt}
                    ],
                    "max_tokens": 5,
                    "temperature": 0.0,
                }
                r = self.session.post(url, json=payload, headers=headers, timeout=(5, 10))
                data = r.json()
                if "choices" in data and len(data["choices"]) > 0:
                    answer = data["choices"][0]["message"]["content"].strip().upper()
                    logger.info(f"needs_web_search classification: {answer}")
                    return answer.startswith("YES")
        except Exception as e:
            logger.error(f"Error in needs_web_search classification: {e}")
        return False

    def _build_system_prompt(self, knowledge_base: str = "", rolling_summary: str = "", semantic_context: str = "", sender_name: str = "") -> str:
        prompt = (
            "Bạn là Bot Sao Assistant trên Zalo, trợ lý AI thông minh và tận tâm của Admin Mai Công Sao.\n"
            "Hãy trả lời ngắn gọn, súc tích, thân thiện bằng tiếng Việt.\n\n"
            "ĐỊNH DẠNG TIN NHẮN ZALO: Ứng dụng Zalo hỗ trợ một số định dạng markdown qua parse_mode. "
            "Bạn CÓ THỂ dùng **in đậm**, *in nghiêng*, ~~gạch ngang~~, danh sách •, và `{màu}nội dung{/màu}`. "
            "TUYỆT ĐỐI KHÔNG dùng dấu # tiêu đề hay khối code ```, vì hiển thị không đẹp. "
            "Nếu liệt kê các ý, hãy dùng dấu gạch đầu dòng hoặc dấu chấm tròn •.\n\n"
            "TƯƠNG TÁC NHÓM: Trong nhóm chat, bạn CHỈ được trả lời khi có người @mention bạn hoặc trả lời (quote) tin nhắn của bạn. "
            "Khi trả lời, hãy đề cập rõ người đang hỏi bằng tên hiển thị (ví dụ: '@Tên Người Dùng') nếu cần xưng hô hoặc trả lời trực tiếp. "
            "Zalo Bot Platform KHÔNG cho phép bot gửi mention tương tác thật, vì vậy '@Tên' sẽ hiển thị dạng văn bản, không bấm được. "
            "Trong nhóm chat, các tin nhắn có thể có tiền tố 'Tên_thành_viên: nội dung' để bạn phân biệt người đang nói chuyện.\n\n"
            "XƯNG HÔ VỚI NGƯỜI DÙNG: Nếu người nhắn là Admin Mai Công Sao (đại ca), hãy xưng hô thân mật và gọi họ là ĐẠI CA, dùng tông giọng tôn trọng nhưng gần gũi, không khách sáo. "
            "Ví dụ: 'Dạ đại ca', 'Đại ca đang hỏi về...', 'Em nhớ mà đại ca...' thay vì 'bạn', 'anh/chị'.\n\n"
            "TƯ DUY PHẢN BIỆN & CHÍNH XÁC: Khi người dùng đưa ra nhận định hoặc thử thách kiến thức, hãy luôn đối chiếu với sự thật khách quan. "
            "Nếu thông tin từ người dùng là giả thuyết, tin đồn hoặc chưa chính xác, hãy lịch sự đính chính và phân tích khách quan, TUYỆT ĐỐI KHÔNG xu nịnh hay vội vã nhận lỗi về điều mình không sai.\n\n"
            "--- HỆ THỐNG LỆNH CỦA BOT (HÃY HƯỚNG DẪN CHÍNH XÁC KHI ĐƯỢC HỎI) ---\n"
            "• /menu hoặc /help: Mở menu chức năng\n"
            "• /save <nội dung>: Lưu kiến thức quan trọng vào kho nhóm\n"
            "• /knowledge: Xem danh sách kiến thức đã lưu của nhóm\n"
            "• /summary: Tóm tắt nội dung thảo luận 12 giờ qua\n"
            "• /clear: Xóa lịch sử trò chuyện ngắn hạn gần đây\n"
            "• /sticker: Xem kho sticker; /sticker <tên bộ>: gửi 1 sticker từ bộ đó; /sticker random: gửi sticker ngẫu nhiên\n\n"
            "--- GỬI STICKER NGẪU NHIÊN TỰ ĐỘNG ---\n"
            "Nếu câu trả lời của bạn phù hợp đi kèm một sticker vui/lively (ví dụ chào hỏi, cảm ơn, chúc mừng, hoặc khi muốn thêm cảm xúc), "
            "bạn CÓ THỂ kết thúc tin nhắn bằng marker riêng [STICKER_RANDOM]. "
            "Đặt marker này trên dòng riêng, sau phần text. KHÔNG dùng nếu nội dung nghiêm túc, kỹ thuật, hoặc không cần thiết.\n\n"
            "--- TÌM KIẾM WEB KHI CẦN THÔNG TIN THỜI GIAN THỰC ---\n"
            "Nếu câu hỏi của người dùng cần dữ liệu thời gian thực mà bạn không chắc chắn (ví dụ: thời tiết, giá cả, tin tức mới, lịch thi đấu, ngày giờ hiện tại, kết quả bóng đá, chứng khoán...), "
            "bạn HÃY trả lời ngắn gọn và KẾT THÚC bằng marker `[WEB_SEARCH:truy vấn cụ thể bằng tiếng Việt]`. "
            "Ví dụ: 'Tôi sẽ tra thông tin cho bạn. [WEB_SEARCH:Thời tiết Hà Nội hôm nay]' hoặc 'Để xác nhận chính xác: [WEB_SEARCH:giá vàng hôm nay]'. "
            "KHÔNG dùng marker này cho câu hỏi kiến thức tổng quát, toán học, lịch sử, hoặc những gì bạn đã biết chắc chắn.\n\n"
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
        image_data: Optional[str] = None,
        sender_name: str = ""
    ) -> str:
        url = settings.OLLAMA_BASE_URL.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if settings.OLLAMA_API_KEY:
            headers["Authorization"] = f"Bearer {settings.OLLAMA_API_KEY}"

        messages = [{"role": "system", "content": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context, sender_name)}]
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
            # Vision candidate models (Kimi Vision -> GLM)
            raw_fallbacks = [m.strip() for m in settings.VISION_FALLBACK_MODELS.split(",") if m.strip()]
            candidate_models = [settings.VISION_MODEL] + [m for m in raw_fallbacks if m != settings.VISION_MODEL]
        else:
            user_msg = {"role": "user", "content": prompt}
            # Text candidate models: Primary (DeepSeek) -> GLM Fallbacks (glm-5.3-flash, glm-5.2, glm-5.1)
            raw_fallbacks = [m.strip() for m in settings.FALLBACK_MODELS.split(",") if m.strip()]
            candidate_models = [settings.OLLAMA_MODEL] + [m for m in raw_fallbacks if m != settings.OLLAMA_MODEL]

        messages.append(user_msg)

        last_error = None
        for model_name in candidate_models:
            payload = {
                "model": model_name,
                "messages": messages
            }
            try:
                r = self.session.post(url, json=payload, headers=headers, timeout=(5, 35))
                if r.status_code == 200:
                    data = r.json()
                    if "choices" in data and len(data["choices"]) > 0:
                        content = data["choices"][0]["message"]["content"]
                        if model_name != candidate_models[0]:
                            logger.info(f"✅ Fallback to {model_name} succeeded after primary model failed!")
                        return content
                logger.warning(f"Model {model_name} returned status {r.status_code}: {r.text[:150]}, trying next fallback model...")
                last_error = f"HTTP {r.status_code}: {r.text[:100]}"
            except Exception as e:
                logger.warning(f"Model {model_name} request error ({e}), trying next fallback model...")
                last_error = str(e)

        logger.error(f"All candidate models failed in fallback chain: {candidate_models}. Last error: {last_error}")
        return "Dạ hiện tại đường truyền kết nối AI đang bị gián đoạn đôi chút, bạn vui lòng gửi lại tin nhắn sau vài giây nhé!"

    def _gemini_reply(
        self,
        prompt: str,
        history: Optional[List[Dict[str, str]]] = None,
        knowledge_base: str = "",
        rolling_summary: str = "",
        semantic_context: str = "",
        image_data: Optional[str] = None,
        sender_name: str = ""
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
                "parts": [{"text": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context, sender_name)}]
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
        image_data: Optional[str] = None,
        sender_name: str = ""
    ) -> str:
        url = settings.OPENAI_BASE_URL.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        messages = [{"role": "system", "content": self._build_system_prompt(knowledge_base, rolling_summary, semantic_context, sender_name)}]
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

