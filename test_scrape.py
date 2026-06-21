import re
import requests

def scrape_hooks():
    urls = [
        "https://transitionalhooks.com/social-media-video-hook-library/",
        "https://transitionalhooks.com/social-media-video-hook-library/page/2/"
    ]
    videos = set()
    for url in urls:
        r = requests.get(url)
        found = re.findall(r'https://transitionalhooks.com/wp-content/uploads/[^"\']+\.mp4', r.text)
        videos.update(found)
    print(f"Found {len(videos)} videos:")
    for v in list(videos)[:5]:
        print(v)

scrape_hooks()
