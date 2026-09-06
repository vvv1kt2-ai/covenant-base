import json

with open('results.json', encoding='utf-8') as f:
    data = json.load(f)

print(f'Type: {type(data).__name__}')
if isinstance(data, list):
    print(f'Length: {len(data)}')
    if len(data) > 0:
        print(f'First item keys: {list(data[0].keys()) if isinstance(data[0], dict) else data[0]}')
        for i, item in enumerate(data[:3]):
            print(f'\nItem {i}: {json.dumps(item, ensure_ascii=False)[:500]}')
elif isinstance(data, dict):
    print(f'Keys: {len(data)}')
    first_key = list(data.keys())[0]
    print(f'First key: {first_key}')
    print(f'First value type: {type(data[first_key]).__name__}')
    print(f'First value: {json.dumps(data[first_key], ensure_ascii=False)[:500]}')
