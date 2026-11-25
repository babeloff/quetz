@ECHO OFF
setlocal
pushd "%~dp0\.."
if "%1"=="" goto help
if "%1"=="html" goto html
if "%1"=="clean" goto clean
echo.Unknown target: %1
popd
exit /b 1
:html
pixi run --locked -e docs docs-site
set RESULT=%ERRORLEVEL%
popd
exit /b %RESULT%
:clean
if exist docs\build rmdir /s /q docs\build
popd
exit /b 0
:help
echo.make html   Build the AsciiDoc documentation site with Pixi
echo.make clean  Remove generated documentation
popd
endlocal
