import requests

def send_data_to_server(url, weight, message):
    try:
        # Construct the payload with the weight and message
        payload = {
            'weight': weight,
            'message': message
        }
        
        # Send the POST request with the payload
        response = requests.post(url, json=payload)
        
        # Check the response status
        if response.status_code == 200:
            print("Data sent successfully!")
            print("Server Response:", response.json())
        else:
            print(f"Failed to send data. Status code: {response.status_code}")
            print("Response:", response.text)
    
    except requests.exceptions.RequestException as e:
        print(f"An error occurred: {e}")

# Example usage
url_to_send = "https://whack-wlr9.onrender.com"
weight_value = 75.5  # Example weight
text_message = "Hello, this is a test message"

send_data_to_server(url_to_send, weight_value, text_message)