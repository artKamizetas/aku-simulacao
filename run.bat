@echo off
echo ========================================
echo  EXECUTANDO - Clockwork to Supabase
echo ========================================
echo.

REM Verifica se o venv existe
if not exist "venv" (
    echo [ERRO] Ambiente virtual nao encontrado!
    echo Execute 'setup.bat' primeiro para criar o ambiente.
    pause
    exit /b 1
)

REM Ativa o ambiente virtual
call venv\Scripts\activate.bat

REM Verifica se o script existe
if not exist "app.py" (
    echo [ERRO] Arquivo 'app.py' nao encontrado!
    pause
    exit /b 1
)

echo Executando script...
echo.
streamlit run testar_conexao_gsheets.py

echo.
echo ========================================
echo  EXECUCAO CONCLUIDA
echo ========================================
echo.
pause
