@echo off
REM FSX Weather Bridge - Push to GitHub Helper Script
REM This script helps you connect and push your repository to GitHub

echo ========================================
echo FSX Weather Bridge - GitHub Push Helper
echo ========================================
echo.

REM Check if git is available
where git >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Git is not installed or not in PATH
    echo Please install Git from https://git-scm.com/
    pause
    exit /b 1
)

REM Check if repository is initialized
if not exist ".git" (
    echo ERROR: Git repository not initialized
    echo Please run: git init
    pause
    exit /b 1
)

echo Step 1: Checking current repository status...
echo.
git status --short
echo.

echo Step 2: Checking for existing remote...
git remote -v
echo.

echo ========================================
echo INSTRUCTIONS:
echo ========================================
echo.
echo 1. Go to https://github.com and sign in
echo 2. Click the "+" icon ^> "New repository"
echo 3. Repository name: fsweatherbridge (or your choice)
echo 4. Description: Real-time weather injection system for Microsoft Flight Simulator X
echo 5. Choose Public or Private
echo 6. DO NOT check "Add a README file" or "Add .gitignore"
echo 7. Click "Create repository"
echo.
echo ========================================
echo.

set /p GITHUB_USERNAME="Enter your GitHub username: "
if "%GITHUB_USERNAME%"=="" (
    echo ERROR: Username cannot be empty
    pause
    exit /b 1
)

set /p REPO_NAME="Enter repository name (default: fsweatherbridge): "
if "%REPO_NAME%"=="" set REPO_NAME=fsweatherbridge

echo.
echo ========================================
echo Setting up remote and pushing...
echo ========================================
echo.

REM Check if remote already exists
git remote get-url origin >nul 2>&1
if %ERRORLEVEL% EQU 0 (
    echo Remote 'origin' already exists.
    set /p UPDATE_REMOTE="Do you want to update it? (y/n): "
    if /i "%UPDATE_REMOTE%"=="y" (
        git remote set-url origin https://github.com/%GITHUB_USERNAME%/%REPO_NAME%.git
        echo Remote URL updated.
    ) else (
        echo Keeping existing remote.
    )
) else (
    git remote add origin https://github.com/%GITHUB_USERNAME%/%REPO_NAME%.git
    echo Remote 'origin' added.
)

echo.
echo Verifying remote...
git remote -v
echo.

echo ========================================
echo Ready to push!
echo ========================================
echo.
echo Repository URL: https://github.com/%GITHUB_USERNAME%/%REPO_NAME%
echo.
set /p PUSH_NOW="Push to GitHub now? (y/n): "
if /i "%PUSH_NOW%"=="y" (
    echo.
    echo Pushing to GitHub...
    echo.
    git push -u origin main
    if %ERRORLEVEL% EQU 0 (
        echo.
        echo ========================================
        echo SUCCESS! Your code has been pushed to GitHub!
        echo ========================================
        echo.
        echo Repository URL: https://github.com/%GITHUB_USERNAME%/%REPO_NAME%
        echo.
    ) else (
        echo.
        echo ========================================
        echo ERROR: Push failed
        echo ========================================
        echo.
        echo Possible reasons:
        echo - Repository doesn't exist on GitHub yet
        echo - Authentication failed (use Personal Access Token)
        echo - Network issues
        echo.
        echo If authentication fails, you may need to:
        echo 1. Create a Personal Access Token at:
        echo    https://github.com/settings/tokens
        echo 2. Use the token as your password when prompted
        echo.
    )
) else (
    echo.
    echo You can push manually later using:
    echo   git push -u origin main
    echo.
)

pause
