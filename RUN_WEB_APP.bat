@echo off
title Psydox Web App
cd /d "%~dp0"
echo Starting Psydox Web App...
echo Open http://localhost:8501 in your browser
C:\NikeVenv\Scripts\streamlit.exe run app.py --server.port 8501 --server.address 0.0.0.0
pause
