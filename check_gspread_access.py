#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de verificacao de acesso a Google Sheets via gspread.
Testa a conexao com as credenciais em .streamlit/secrets.toml
"""

import json
import sys
import os
from pathlib import Path
import traceback

# Força UTF-8 no Windows
if sys.platform == "win32":
    os.environ["PYTHONIOENCODING"] = "utf-8"

try:
    import gspread
    from google.oauth2.service_account import Credentials
except ImportError:
    print("[ERRO] gspread ou google-auth nao instalados")
    print("       Instale: pip install gspread google-auth")
    sys.exit(1)

try:
    import toml
except ImportError:
    print("[ERRO] toml nao instalado")
    print("       Instale: pip install toml")
    sys.exit(1)


def main():
    print("=" * 70)
    print("VERIFICACAO DE ACESSO A GOOGLE SHEETS VIA GSPREAD")
    print("=" * 70)
    print()

    # ========================================================================
    # 1. Carregar secrets.toml
    # ========================================================================
    print("[1/5] Carregando .streamlit/secrets.toml...")
    try:
        secrets_path = Path(".streamlit/secrets.toml")
        if not secrets_path.exists():
            print("[ERRO] Arquivo nao encontrado: {}".format(secrets_path.resolve()))
            sys.exit(1)

        with open(secrets_path, "r", encoding="utf-8") as f:
            secrets = toml.load(f)

        print("[OK]  Arquivo carregado com sucesso")
        print("      Caminho: {}".format(secrets_path.resolve()))

    except Exception as e:
        print("[ERRO] Erro ao ler secrets.toml:")
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # 2. Validar estrutura
    # ========================================================================
    print("\n[2/5] Validando estrutura do secrets.toml...")
    try:
        sheet_id = secrets.get("sheet_id")
        gcp_sa = secrets.get("gcp_service_account")

        if not sheet_id:
            print("[ERRO] Campo 'sheet_id' nao encontrado ou vazio")
            sys.exit(1)

        if not gcp_sa:
            print("[ERRO] Campo 'gcp_service_account' nao encontrado")
            sys.exit(1)

        required_fields = ["type", "project_id", "private_key", "client_email"]
        missing = [f for f in required_fields if f not in gcp_sa]

        if missing:
            print("[ERRO] Campos faltando em gcp_service_account: {}".format(missing))
            sys.exit(1)

        print("[OK]  Estrutura validada")
        print("      Sheet ID: {}...".format(sheet_id[:30]))
        print("      Project ID: {}".format(gcp_sa.get('project_id')))
        print("      Service Account: {}".format(gcp_sa.get('client_email')))

    except Exception as e:
        print("[ERRO] Erro na validacao:")
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # 3. Autenticar com Google
    # ========================================================================
    print("\n[3/5] Autenticando com Google Cloud...")
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]

        credentials = Credentials.from_service_account_info(gcp_sa, scopes=scopes)

        print("[OK]  Credenciais carregadas com sucesso")
        token_preview = str(credentials.token)[:50] if credentials.token else "Nao gerado ainda"
        print("      Token: {}...".format(token_preview))

    except Exception as e:
        print("[ERRO] Erro na autenticacao:")
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # 4. Conectar ao gspread
    # ========================================================================
    print("\n[4/5] Conectando ao gspread...")
    try:
        gc = gspread.authorize(credentials)
        print("[OK]  Cliente gspread criado com sucesso")

    except Exception as e:
        print("[ERRO] Erro ao criar cliente gspread:")
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # 5. Acessar a planilha
    # ========================================================================
    print("\n[5/5] Acessando a planilha...")
    try:
        spreadsheet = gc.open_by_key(sheet_id)
        print("[OK]  Planilha acessada com sucesso!")
        print("      Titulo: {}".format(spreadsheet.title))
        print("      ID: {}".format(spreadsheet.id))

        # Listar abas
        worksheets = spreadsheet.worksheets()
        print("\n      Abas disponíveis ({})".format(len(worksheets)))
        for ws in worksheets:
            row_count = ws.row_count
            col_count = ws.col_count
            print("        * {} ({} linhas x {} colunas)".format(ws.title, row_count, col_count))

        # Tentar ler primeira célula de uma aba
        try:
            first_ws = spreadsheet.sheet1
            cell_value = first_ws.cell(1, 1).value
            print("\n      Primeira célula da aba '{}': {}".format(first_ws.title, cell_value))
        except Exception as ws_err:
            print("\n[AVISO] Erro ao ler células: {}".format(ws_err))

    except gspread.exceptions.SpreadsheetNotFound:
        print("[ERRO] Planilha nao encontrada com ID: {}".format(sheet_id))
        print("       Verifique:")
        print("         - O ID da planilha está correto?")
        print("         - A service account tem acesso de leitura?")
        traceback.print_exc()
        sys.exit(1)

    except gspread.exceptions.APIError as e:
        print("[ERRO] Erro na API do Google Sheets:")
        error_info = e.response.get('error', {})
        print("       Codigo: {}".format(error_info.get('code', 'N/A')))
        print("       Mensagem: {}".format(error_info.get('message', str(e))))
        traceback.print_exc()
        sys.exit(1)

    except Exception as e:
        print("[ERRO] Erro inesperado ao acessar a planilha:")
        traceback.print_exc()
        sys.exit(1)

    # ========================================================================
    # Sucesso!
    # ========================================================================
    print("\n" + "=" * 70)
    print("[SUCESSO] TESTE CONCLUIDO COM SUCESSO!")
    print("=" * 70)
    print("\nO acesso à planilha esta funcionando corretamente.")
    print("Voce pode agora usar gspread para ler/escrever dados.")
    print()


if __name__ == "__main__":
    main()
