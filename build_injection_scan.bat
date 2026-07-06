@echo off
REM Build the fast injection motion-signal scanner.
REM Requires MinGW g++ on PATH (g++ --version). Static-linked so it runs
REM without extra MinGW DLLs. Python falls back to NumPy/PIL if this is absent.

g++ -O3 -fopenmp -std=c++17 -static -static-libgcc -static-libstdc++ ^
    injection_scan.cpp -o injection_scan.exe

if %ERRORLEVEL%==0 (
    echo Built injection_scan.exe
) else (
    echo Build failed - Python will use its NumPy/PIL fallback instead.
)
