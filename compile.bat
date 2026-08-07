@echo off
rem QualCoder v4 - compile launcher (double-click friendly)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0compile.ps1" %*
