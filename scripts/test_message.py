import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.zalo_client import zalo_client


def main():
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_message.py <chat_id> <message_text>")
        sys.exit(1)

    chat_id = sys.argv[1]
    text = sys.argv[2]

    print(f"🚀 Sending test message to {chat_id}: {text}")
    res = zalo_client.send_message(chat_id=chat_id, text=text)
    print(f"Response: {res}")


if __name__ == "__main__":
    main()
