import os
import sys
import requests
import argparse
import re
import json

def send_guide_with_image(webhook_url, content, image_path):
    """Sends a long message with an image to a Discord webhook."""
    max_len = 2000
    
    # Find the image markdown and replace it with a placeholder
    image_placeholder = "[[IMAGE_PLACEHOLDER]]"
    content_with_placeholder = re.sub(r'!\[.*\]\(.*\)', image_placeholder, content)
    
    parts = content_with_placeholder.split(image_placeholder)
    
    # Send the text before the image
    if parts[0]:
        text_chunks = [parts[0][i:i+max_len] for i in range(0, len(parts[0]), max_len)]
        for chunk in text_chunks:
            payload = {"content": chunk}
            try:
                response = requests.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                print("Successfully sent a text chunk of the guide.")
            except requests.exceptions.RequestException as e:
                print(f"Error sending text chunk to Discord: {e}")
                return False

    # Send the image
    if image_path and os.path.exists(image_path):
        try:
            with open(image_path, 'rb') as f:
                file_name = os.path.basename(image_path)
                files = {'file': (file_name, f, 'image/png')}
                response = requests.post(webhook_url, files=files, timeout=10)
                response.raise_for_status()
            print(f"Successfully sent the image: {file_name}")
        except requests.exceptions.RequestException as e:
            print(f"Error sending image to Discord: {e}")
            return False
            
    # Send the text after the image
    if len(parts) > 1 and parts[1]:
        text_chunks = [parts[1][i:i+max_len] for i in range(0, len(parts[1]), max_len)]
        for chunk in text_chunks:
            payload = {"content": chunk}
            try:
                response = requests.post(webhook_url, json=payload, timeout=10)
                response.raise_for_status()
                print("Successfully sent a text chunk of the guide.")
            except requests.exceptions.RequestException as e:
                print(f"Error sending text chunk to Discord: {e}")
                return False
                
    return True

def main():
    """Main function to read the guide and send it to Discord."""
    parser = argparse.ArgumentParser(description="Send the trading guide to a Discord channel.")
    parser.add_argument("--webhook", required=True, help="The Discord webhook URL for the #info channel.")
    args = parser.parse_args()

    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
    guide_path = os.path.join(project_root, 'trading_guide.md')
    
    print(f"Project root: {project_root}")
    print(f"Guide path: {guide_path}")
    
    guide_content = ""
    image_path = None

    try:
        with open(guide_path, 'r', encoding='utf-8') as f:
            guide_content = f.read()
        
        # Find the image path in the markdown
        match = re.search(r'!\[.*\]\((.*)\)', guide_content)
        if match:
            relative_image_path = match.group(1)
            print(f"Found image reference in markdown: {relative_image_path}")
            # Construct absolute path
            image_path = os.path.join(project_root, relative_image_path)
            print(f"Constructed absolute image path: {image_path}")
            if not os.path.exists(image_path):
                print(f"Error: Image file not found at {image_path}")
                image_path = None
            else:
                print(f"Image file found at {image_path}")
        else:
            print("No image reference found in the guide.")
            
    except FileNotFoundError:
        print(f"Error: trading_guide.md not found at {guide_path}")
        sys.exit(1)
    except Exception as e:
        print(f"An error occurred while reading the file: {e}")
        sys.exit(1)

    print("Sending the trading guide to your Discord channel...")
    if send_guide_with_image(args.webhook, guide_content, image_path):
        print("Trading guide successfully posted!")
    else:
        print("Failed to post the trading guide.")

if __name__ == "__main__":
    main()
