@echo off
rem Build the hook DLL (yyzyhook.dll). ASCII only - no Chinese here, cmd reads as GBK.
setlocal
cd /d "%~dp0"
call "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\VC\Auxiliary\Build\vcvars64.bat" >nul 2>&1
if errorlevel 1 (
  echo [ERROR] vcvars64.bat not found - check VS Build Tools path
  exit /b 1
)
cl /nologo /LD /MT /O2 /EHsc /utf-8 ^
  /I "minhook-1.3.3\include" /I "minhook-1.3.3\src" ^
  src\dllmain.cpp src\ws2hook.cpp src\pipe.cpp src\il2cppui.cpp src\seh_guard.cpp src\close_intercept.cpp ^
  minhook-1.3.3\src\hook.c minhook-1.3.3\src\trampoline.c minhook-1.3.3\src\buffer.c ^
  minhook-1.3.3\src\hde\hde32.c minhook-1.3.3\src\hde\hde64.c ^
  ws2_32.lib kernel32.lib user32.lib ^
  /link /OUT:yyzyhook.dll
if errorlevel 1 (
  echo [ERROR] build failed
  exit /b 1
)
echo [OK] yyzyhook.dll built
