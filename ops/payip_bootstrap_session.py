from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot_api.config import get_settings
from bot_api.integrations.payip_client import PayipClient, PayipConfig


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Cria ou renova o cache de tokens PayIP usando login completo com MFA."
    )
    parser.add_argument("--mfa-code", help="Codigo atual do Google Authenticator.")
    args = parser.parse_args()

    settings = get_settings()
    mfa_code = (args.mfa_code or settings.payip_mfa_code or "").strip()
    if not mfa_code:
        mfa_code = input("Codigo MFA/TOTP do Google Authenticator: ").strip()

    client = PayipClient(
        PayipConfig(
            base_url=settings.payip_base_url,
            client_id=settings.payip_client_id,
            username=settings.payip_username,
            password=settings.payip_password,
            company_id=settings.payip_company_id,
            token_cache_file=settings.payip_token_cache_file,
            company_ids=settings.payip_company_ids,
            timeout_seconds=settings.payip_timeout_seconds,
            mfa_code=settings.payip_mfa_code,
        )
    )
    try:
        status = client.bootstrap_session(mfa_code=mfa_code)
    finally:
        client.close()

    print("Sessao PayIP criada com sucesso.")
    print(f"Cache: {status['token_cache_file']}")
    print(f"Access token valido: {status['access_token_valid']}")
    print(f"Refresh token valido: {status['refresh_token_valid']}")
    print(f"Session state: {status['session_state']}")


if __name__ == "__main__":
    main()
