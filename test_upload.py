import asyncio
import httpx

async def test_upload():
    url = "https://api.azvmotors.kz/admin/users/trips/start"
    headers = {
        "Authorization": "Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJnQUFBQUFCcFUtWFJXM0NMTnF3b25pOTl0MXU4ZTI2Wkp5aDhLbEZULUtDUW9GbWtfby1jUmlWRkxZOUtQRTJFNWR0V2Z5UWdzSkttbjYyUGYtTXlrUmdMVjJmR1RidDRqZz09IiwidG9rZW5fdHlwZSI6ImFjY2VzcyJ9.TkGddjq8PC5YPsh-UeHyJ0WibtLwacD32taDz_G5Ulg"
    }
    
    # Create a simple test image (1x1 pixel JPEG)
    import base64
    jpeg_data = base64.b64decode('/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAn/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBEQCERAD/AL+AB//Z')
    
    files = {
        "selfie": ("test.jpg", jpeg_data, "image/jpeg"),
        "car_photos": ("test2.jpg", jpeg_data, "image/jpeg"),
        "interior_photos": ("test3.jpg", jpeg_data, "image/jpeg"),
    }
    
    data = {
        "car_id": "K2wy3EyaQGCBVkruR4Ch9w",
        "user_id": "HD7N8YmGTYq6MDqFkajDYw",
        "rental_type": "MINUTES"
    }
    
    async with httpx.AsyncClient() as client:
        response = await client.post(url, headers=headers, data=data, files=files)
        print(f"Status: {response.status_code}")
        print(f"Response: {response.text}")

asyncio.run(test_upload())
