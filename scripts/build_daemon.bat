@echo off
REM 用 MSVC 工具链构建 system-daemon（SDK 装在 D:\Windows Kits\10）
REM 用法:
REM   build_daemon.bat          # 仅构建主程序 yuiro.exe
REM   build_daemon.bat test     # 额外构建并运行单元测试 yuiro_tests.exe
setlocal
cd /d D:\Project\Yuii\desktop-pet\Yuiro\system-daemon
if exist build rmdir /s /q build
call "D:\cppVenv\VS2022\VC\Auxiliary\Build\vcvarsall.bat" x64
set WindowsSDKDir=D:\Windows Kits\10
set CMAKE_VS_WINSDK_DIR=D:\Windows Kits\10

if /I "%1"=="test" (
  cmake -B build -G Ninja -DBUILD_TESTING=ON -DCMAKE_VS_WINSDK_DIR=D:\Windows Kits\10 -DWindowsSDKDir=D:\Windows Kits\10
) else (
  cmake -B build -G Ninja -DBUILD_TESTING=OFF -DCMAKE_VS_WINSDK_DIR=D:\Windows Kits\10 -DWindowsSDKDir=D:\Windows Kits\10
)
if errorlevel 1 goto :fail

cmake --build build
if errorlevel 1 goto :fail

if /I "%1"=="test" (
  echo === RUN TESTS ===
  build\yuiro_tests.exe
  if errorlevel 1 goto :fail
)

echo BUILD_OK
goto :end
:fail
echo BUILD_FAILED
:end
endlocal
