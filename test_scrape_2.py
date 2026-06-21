import re
import requests

url = "https://onlinepath.com.au/blog/100-best-viral-video-hooks-2024/"
r = requests.get(url)

# The hooks are likely in <ol><li> or <p> tags with quotes. Let's just find text between <li> and </li>
matches = re.findall(r'<li>(.*?)</li>', r.text)

hooks = []
for m in matches:
    # remove HTML tags from match
    text = re.sub(r'<[^>]+>', '', m).strip()
    if '“' in text or '"' in text or len(text) > 10:
        # Some are just text ideas like "What if I told you [insert secret]"
        if '[' in text or 'X' in text or '?' in text or '!' in text:
            hooks.append(text)

print(f"Found {len(hooks)} possible text hooks:")
for h in hooks[:20]:
    print(h)
