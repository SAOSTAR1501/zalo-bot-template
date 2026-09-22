# 🤖 Zalo Bot AI Template

Template mã nguồn hoàn chỉnh, chuẩn Production cho Chatbot Zalo AI thông minh hỗ trợ Nhóm (Group) và Chat riêng (1-1), tích hợp Bộ nhớ ngữ cảnh 12 giờ, Đọc ảnh Đa phương thức (Multimodal Vision), RAG Vector Embedding, Quản lý hạn mức Quota và Debounce gom tin nhắn bất đồng bộ.

---

## 🌟 Tính Năng Nổi Bật

* **Đa Nhà Cung Cấp LLM & Dynamic Routing**:
  * **Xử lý Text thông minh**: Hỗ trợ **Ollama Cloud/Local** (`deepseek-v4-pro:0813`, `gemma4:31b`...), **Google Gemini** (`gemini-2.0-flash`), **OpenAI / DeepSeek**.
  * **Đọc & Phân tích hình ảnh (Multimodal Vision)**: Tự động chuyển đổi sang model Vision **`kimi-k2.7-code`** (hoặc Gemini Vision / GPT-4o) khi người dùng gửi ảnh.
* **Trích Dẫn & Trả Lời Tin Nhắn (Quoted Reply)**:
  * Tự động trả lời dạng trích dẫn (`reply_to_message_id`) vào đúng tin nhắn/hình ảnh người dùng vừa gửi.
  * Hiểu ngữ cảnh khi người dùng trong nhóm bấm "Trả lời" một tin nhắn cũ của người khác.
* **Gom Tin Nhắn Tự Động (Async Debounce Aggregator)**:
  * Tự động gom các tin nhắn gửi dồn dập, liên tục của người dùng trong khoảng 2.5s thành 1 prompt tổng thể duy nhất, giúp bot trả lời đầy đủ, không bị vụn vặt và tiết kiệm token tối đa.
* **Episodic Summary Memory (Tiết kiệm >80% Token)**:
  * Cơ chế nén ngữ cảnh luân phiên (Rolling Synopsis) kết hợp các lượt chat gần nhất, duy trì mạch hội thoại dài 12 tiếng liên tục mà không bị phình token.
* **Semantic Long-Term Memory (RAG + Vector Search)**:
  * Tích hợp **FastEmbed (ONNX)** tính toán vector embedding 384 chiều đa ngôn ngữ, tự động tìm kiếm ngữ nghĩa chính xác các sự kiện, quy định, dữ liệu cũ khi người dùng hỏi.
* **Kiểm Soát Hạn Mức & Gói Duyệt (Rate Limiting & Admin Plans)**:
  * **10 tin miễn phí**: Tự động cấp và thông báo cho người dùng mới 1-1.
  * **Silent Drop chống tốn tin**: Cảnh báo tối đa 3 lần khi hết hạn mức, sau đó âm thầm bỏ qua để tránh mất lượt tin Zalo hàng tháng.
  * **Duyệt / Đổi gói linh hoạt cho Admin**: Admin **Mai Công Sao** có thể đổi bất kỳ gói nào (`10 tin`, `3 ngày`, `5 giờ`, `2 tháng`, `vinhvien`, `reset`) kể cả khi user đang ở gói Vĩnh viễn.
  * **Lệnh khóa người dùng**: `/block <user_id>` (chặn vĩnh viễn) và `/unblock <user_id>`.
* **Kho Tri Thức Nhóm (Knowledge Base)**:
  * `/save <nội dung>`: Thành viên chủ động lưu kiến thức quan trọng lâu dài (tự động vector hóa).
  * `/knowledge`: Xem kho kiến thức đã lưu của nhóm.
  * `/summary`: Yêu cầu bot tự động tóm tắt các thảo luận trong 12 tiếng qua.
* **Menu Lệnh & Phân Quyền Thông Minh**: Gõ `/menu` để xem menu chức năng; chỉ riêng Admin mới thấy các lệnh quản trị và hướng dẫn gói.
* **Bộ Lọc Markdown Chuẩn Zalo**: Tự động loại bỏ các dấu `**`, `*`, `###` và định dạng danh sách thành các dấu chấm tròn `• ` đẹp mắt, phù hợp với giao diện Zalo.
* **Sẵn Sàng Triển Khai (Production Ready)**: Hỗ trợ cả **Docker Compose** và **Systemd Linux Service**.

---

## 📂 Cấu Trúc Thư Mục

```text
zalo-bot-template/
├── config/
│   ├── __init__.py
│   └── settings.py          # Quản lý cấu hình biến môi trường (.env)
├── database/
│   ├── __init__.py
│   ├── connection.py        # Kết nối SQLite & Session management
│   └── models.py            # Bảng MessageLog, GroupKnowledge, GroupContextSummary, SemanticMemory, UserQuota
├── services/
│   ├── __init__.py
│   ├── zalo_client.py       # API Client gọi Zalo Bot Platform (Hỗ trợ sendMessage, sendPhoto, reply_to_message_id)
│   ├── llm_service.py       # Tích hợp Ollama, Kimi Vision (kimi-k2.7-code), Gemini, OpenAI
│   ├── image_service.py     # Tải và mã hóa hình ảnh Base64 cho Vision Model
│   ├── aggregator_service.py# Bộ đệm Debounce gom tin nhắn liên tục (2.5s)
│   ├── context_service.py   # Quản lý bộ nhớ ngữ cảnh Episodic Summary 12h
│   ├── knowledge_service.py # Quản lý kho kiến thức & tóm tắt định kỳ
│   ├── semantic_memory_service.py # FastEmbed RAG Vector Memory (384d)
│   ├── quota_service.py     # Kiểm soát hạn mức 1-1, chống spam, duyệt gói Admin
│   └── formatter.py         # Bộ lọc loại bỏ Markdown thô và huy hiệu Quota
├── handlers/
│   ├── __init__.py
│   ├── command_handler.py   # Xử lý toàn bộ lệnh hệ thống & phân quyền Admin
│   └── message_handler.py   # Điều phối Webhook, trích xuất text/ảnh/quote, debounce batch, gọi LLM
├── scripts/
│   ├── set_webhook.py       # Script CLI cấu hình Webhook với Zalo API
│   ├── get_webhook_info.py  # Script CLI kiểm tra trạng thái Webhook
│   └── test_message.py      # Script CLI gửi tin nhắn test
├── systemd/
│   └── zalo-bot.service     # File cấu hình service systemd
├── .env.example             # File mẫu biến môi trường
├── Dockerfile               # Docker container image
├── docker-compose.yml       # Docker Compose setup
├── deploy.sh                # Script triển khai nhanh lên server
├── main.py                  # FastAPI server entrypoint
└── requirements.txt         # Thư viện phụ thuộc
```

---

## 🚀 Hướng Dẫn Cài Đặt & Triển Khai

### 1. Cài đặt môi trường Local

```bash
# Tạo môi trường ảo Python
python -m venv .venv
source .venv/bin/activate  # Trên Windows: .venv\Scripts\activate

# Cài đặt thư viện
pip install -r requirements.txt

# Tạo file .env từ mẫu
cp .env.example .env
```

Điền các thông tin trong `.env`:
* `ZALO_BOT_TOKEN`: Lấy từ [bot.zaloplatforms.com](https://bot.zaloplatforms.com)
* `ZALO_WEBHOOK_SECRET`: Chuỗi bí mật tùy chọn của bạn
* `AI_PROVIDER`: `ollama` hoặc `gemini`
* `OLLAMA_API_KEY`: API Key kết nối API LLM
* `OLLAMA_MODEL`: Model mặc định cho text (ví dụ: `deepseek-v4-pro:0813`)
* `VISION_MODEL`: Model xử lý hình ảnh (ví dụ: `kimi-k2.7-code`)

Chạy server:
```bash
python main.py
```

---

### 2. Thiết Lập Webhook với Zalo

Sau khi trỏ tên miền / Cloudflare Tunnel đến server (cổng 8080):

```bash
python scripts/set_webhook.py https://your-domain.com/webhook your_secret_token
```

Kiểm tra trạng thái Webhook:
```bash
python scripts/get_webhook_info.py
```

> **Lưu ý Cloudflare**: Khi dùng Cloudflare, hãy tắt **Browser Integrity Check** (hoặc tạo WAF Custom Rule Skip cho subdomain bot) để tránh Cloudflare chặn Zalo Webhook Verifier bằng mã lỗi 403.

---

### 3. Triển khai bằng Systemd (Linux Production)

```bash
sudo cp systemd/zalo-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zalo-bot
sudo systemctl status zalo-bot
```

---

## 💬 Danh Sách Lệnh Của Bot

### 👥 Dành cho tất cả người dùng:

| Lệnh | Phím số | Chức năng |
| :--- | :---: | :--- |
| `/help` hoặc `/menu` | `5` | Hiển thị menu hướng dẫn tương tác. |
| `/save <nội dung>` | `1` | Chủ động lưu kiến thức quan trọng vào kho dữ liệu nhóm (tự động index vào RAG). |
| `/knowledge` | `2` | Xem lại các kiến thức nhóm đã lưu trữ. |
| `/summary` | `3` | Tóm tắt các nội dung và quyết định trong 12 giờ qua. |
| `/clear` | `4` | Xóa bộ nhớ trò chuyện ngắn hạn gần đây. |

### 👑 Dành riêng cho Quản Trị Viên (Admin):

| Lệnh Admin | Ví dụ cú pháp | Mô tả chi tiết |
| :--- | :--- | :--- |
| `/accept <user_id> [gói]` | `/accept 1a8ac81b 10`<br>`/accept 1a8ac81b 3 ngày`<br>`/accept 1a8ac81b 5 giờ`<br>`/accept 1a8ac81b 2 tháng`<br>`/accept 1a8ac81b vinhvien`<br>`/accept 1a8ac81b reset` | Cấp hoặc chuyển đổi gói linh hoạt cho người dùng (kể cả khi user đang ở gói Vĩnh viễn). |
| `/block <user_id>` | `/block 1a8ac81b` | Khóa / Chặn người dùng vĩnh viễn (Silent Drop). |
| `/unblock <user_id>` | `/unblock 1a8ac81b` | Mở khóa lại cho người dùng. |
| `/users` | `/users` | Xem danh sách người dùng, gói hiện tại, số tin đã dùng và hạn sử dụng. |
