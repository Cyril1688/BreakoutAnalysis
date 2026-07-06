# Discord Notification System

A simple system to send messages from a text file to a Discord channel using webhooks.

## Setup

1. Create a webhook in Discord:
   - Open Discord and go to the server where you want notifications
   - Navigate to Server Settings > Integrations > Webhooks
   - Click "New Webhook"
   - Name it (e.g., "ChartScalping Notifications")
   - Select the channel for notifications
   - Click "Copy Webhook URL"
   - Save the changes

2. Update the configuration:
   - Open `config/config.json`
   - Replace `"YOUR_WEBHOOK_URL"` with your actual webhook URL in the `discord.webhook_url` field

## Usage

1. Edit the `notify.txt` file in the `src/notifications` directory:
   - Add any message you want to send to Discord
   - Save the file

2. Run the notification script:
   ```
   python src/notifications/discord_notifier.py
   ```

   Or simply double-click the `send_notification.bat` file in the `src/notifications` directory.

3. The message will be sent to Discord and the `notify.txt` file will be cleared.

## Example

1. Edit `notify.txt`:
   ```
   Market alert: TSLA is up 5% today!
   RSI indicator shows overbought conditions.
   ```

2. Run the script:
   ```
   python src/notifications/discord_notifier.py
   ```

3. The message will appear in your Discord channel with a timestamp.

## Integration

You can run this script manually whenever you want to send a notification, or you can integrate it with other systems by:

1. Having your application write to the `notify.txt` file
2. Running the `discord_notifier.py` script programmatically

For example, to send a notification from Python code:

```python
import os

# Write to notify.txt in the notifications directory
notify_path = os.path.join('src', 'notifications', 'notify.txt')
with open(notify_path, 'w') as f:
    f.write("Your notification message here")

# Run the notifier script
import subprocess
subprocess.run(["python", "src/notifications/discord_notifier.py"])
