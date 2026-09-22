import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.zalo_client import zalo_client


def main():
    print("🔍 Fetching Zalo Bot & Webhook Status...")
    bot_info = zalo_client.get_me()
    print(f"\n🤖 Bot Profile:\n{bot_info}")

    webhook_info = zalo_client.get_webhook_info()
    print(f"\n📡 Webhook Info:\n{webhook_info}")


if __name__ == "__main__":
    main()
