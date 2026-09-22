import sys
import os

# Add project root to sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import settings
from services.zalo_client import zalo_client


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else settings.WEBHOOK_URL
    secret = sys.argv[2] if len(sys.argv) > 2 else settings.ZALO_WEBHOOK_SECRET

    if not url:
        print("❌ Error: Webhook URL is required. Set WEBHOOK_URL in .env or pass as argument.")
        print("Usage: python scripts/set_webhook.py <webhook_url> [secret_token]")
        sys.exit(1)

    print(f"📡 Setting webhook for Zalo Bot...")
    print(f"👉 URL: {url}")
    print(f"👉 Secret Token: {'***' if secret else '(none)'}")

    res = zalo_client.set_webhook(url=url, secret_token=secret or "")
    print(f"\nResponse from Zalo API:\n{res}")

    if res.get("ok"):
        verification = res.get("result", {}).get("verification", {})
        if verification.get("ok"):
            print("\n🎉 SUCCESS: Webhook verified and activated successfully by Zalo!")
        else:
            print(f"\n⚠️ WARNING: Webhook set but verification failed: {verification.get('outcome')}")
            print(f"💡 Hint: {verification.get('hint')}")
    else:
        print(f"\n❌ FAILED: {res.get('description', 'Unknown error')}")


if __name__ == "__main__":
    main()
