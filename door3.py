import requests
import json
import base64

# CURRENT Door 3 token
bearer = "eyJjbGVhcmVkIjozLCJleHAiOjE3ODY2OTAyOTUsImlhdCI6MTc4NjUyMDk2NiwicmVmIjoiZGUzOTE0ZjFhOWMzMTdiYSJ9.SnWH0UyPC_vNFItzaLaz1Q"

# CURRENT Door 3 path
url = "https://workwithus.staging.scalerailabs.com/g/3jkU8anDF7oFMQe0w-PZ"

headers = {
    "Authorization": f"Bearer {bearer}"
}

# Get the current questions
r = requests.get(url, headers=headers)
print("GET:", r.status_code)

data = r.json()
print(json.dumps(data, indent=2))

# Question token
question_token = data["token"]

# Decode the question-token payload
payload = question_token.split(".")[0]
payload += "=" * (-len(payload) % 4)

decoded = json.loads(
    base64.urlsafe_b64decode(payload)
)

print("\nDecoded token:")
print(json.dumps(decoded, indent=2))

# Answers encoded in the token
answers = decoded["a"]

print("\nAnswers:", answers)

# Submit immediately
r2 = requests.post(
    url,
    headers={
        "Authorization": f"Bearer {bearer}",
        "Content-Type": "application/json"
    },
    json={
        "token": question_token,
        "answers": answers
    }
)

print("\nPOST:", r2.status_code)
print(r2.text)