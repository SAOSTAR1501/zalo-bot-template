# 🤖 Zalo Bot AI Template

Template mã nguồn hoàn chỉnh cho Chatbot Zalo AI thông minh hỗ trợ Nhóm (Group) và Chat riêng (1-1) với bộ nhớ ngữ cảnh 12 giờ và Kho tri thức (Knowledge Base).

---

## 🌟 Tính Năng Nổi Bật

* **Đa Nhà Cung Cấp LLM**: Hỗ trợ **Ollama Cloud/Local** (`deepseek-v4-pro`, `gemma4:31b`...), **Google Gemini** (`gemini-2.0-flash`), **OpenAI / DeepSeek**.
* **Gom Tin Nhắn Tự Động (Async Debounce Aggregator)**: Tự động gom các tin nhắn gửi dồn dập, liên tục của người dùng trong khoảng 2.5s thành 1 prompt tổng thể duy nhất, giúp bot trả lời đầy đủ, không bị vụn vặt và tiết kiệm token tối đa.
* **Episodic Summary Memory (Tiết kiệm >80% Token)**: Sử dụng cơ chế nén ngữ cảnh luân phiên (Rolling Synopsis) kết hợp các lượt chat gần nhất, duy trì mạch hội thoại dài 12 tiếng liên tục.
* **Semantic Long-Term Memory (RAG + Vector Search)**: Tích hợp **FastEmbed (ONNX)** tính toán vector embedding 384 chiều đa ngôn ngữ, tự động tìm kiếm ngữ nghĩa chính xác các sự kiện, quy định, dữ liệu cũ khi người dùng hỏi mà không làm phình token.
* **Kiểm Soát Hạn Mức & Gói Duyệt (Rate Limiting & Admin Plans)**: Tặng 10 tin miễn phí cho người dùng mới 1-1, tự động Silent Drop khi bị spam quá 3 lần, hỗ trợ Admin cấp hạn mức linh hoạt (`+10, +20 tin`, `homnay`, `tuannay`, `thangnay`, `vinhvien`, `/block`).
* **Kho Tri Thức Nhóm (Knowledge Base)**:
  * `/save <nội dung>`: Thành viên chủ động lưu kiến thức quan trọng lâu dài (tự động vector hóa).
  * `/knowledge`: Xem kho kiến thức đã lưu của nhóm.
  * `/summary`: Yêu cầu bot tự động tóm tắt các thảo luận trong 12 tiếng qua.
* **Menu Lệnh & Phân Quyền Thông Minh**: Gõ `/menu` để xem menu chức năng; chỉ riêng Admin mới thấy các lệnh quản trị (`/accept`, `/block`, `/unblock`, `/users`).
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
│   └── models.py            # Bảng MessageLog & GroupKnowledge
├── services/
│   ├── __init__.py
│   ├── zalo_client.py       # API Client gọi Zalo Bot Platform
│   ├── llm_service.py       # Tích hợp Ollama, Gemini, OpenAI, DeepSeek
│   ├── context_service.py   # Quản lý bộ nhớ ngữ cảnh 12h của nhóm
│   ├── knowledge_service.py # Quản lý kho kiến thức & tóm tắt định kỳ
│   └── formatter.py         # Bộ lọc loại bỏ Markdown thừa cho Zalo
├── handlers/
│   ├── __init__.py
│   ├── command_handler.py   # Xử lý /help, /save, /summary, /clear, phím số 1..5
│   └── message_handler.py   # Điều phối Webhook & Phân quyền
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
* `OLLAMA_API_KEY`: API Key lấy từ [ollama.com/settings/keys](https://ollama.com/settings/keys)

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

### 3. Triển khai bằng Docker Compose

```bash
docker compose up -d --build
```

---

### 4. Triển khai bằng Systemd (Linux)

```bash
sudo cp systemd/zalo-bot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zalo-bot
sudo systemctl status zalo-bot
```

---

## 💬 Danh Sách Lệnh Cho Người Dùng

| Lệnh | Phím số | Chức năng |
| :--- | :---: | :--- |
| `/help` hoặc `/menu` | `5` | Hiển thị menu hướng dẫn tương tác. |
| `/save <nội dung>` | `1` | Chủ động lưu kiến thức quan trọng vào kho dữ liệu nhóm. |
| `/knowledge` | `2` | Xem lại các kiến thức nhóm đã lưu trữ. |
| `/summary` | `3` | Tóm tắt các nội dung và quyết định trong 12 giờ qua. |
| `/clear` | `4` | Xóa bộ nhớ trò chuyện ngắn hạn gần đây. |
