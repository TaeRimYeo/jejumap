@echo off
cd /d "%~dp0"
if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
if not exist "%USERPROFILE%\.streamlit\credentials.toml" echo [general]> "%USERPROFILE%\.streamlit\credentials.toml"
findstr /c:"email" "%USERPROFILE%\.streamlit\credentials.toml" >NUL || echo email = "">> "%USERPROFILE%\.streamlit\credentials.toml"
pip install -q -r requirements.txt
streamlit run app.py
