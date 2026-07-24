@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%sync_stage1_wandb_remote.ps1" %*
set "EXIT_CODE=%ERRORLEVEL%"
echo.
if "%EXIT_CODE%"=="0" (
  echo AdaLigand Stage1 W^&B sync finished successfully.
) else (
  echo AdaLigand Stage1 W^&B sync failed with exit code %EXIT_CODE%.
)
echo This window can now be closed.
pause >nul
exit /b %EXIT_CODE%

