@echo off
cd %~dp0\..\..
echo Running Discord Notification Script...
python src/notifications/discord_notifier.py
echo.
echo Done! Check your Discord channel for the message.
echo.
