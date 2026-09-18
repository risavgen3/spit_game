# Build script for index.html
import os

html_parts = []
def add(text):
    html_parts.append(text)

with open(r'templates/index.html', 'w', encoding='utf-8') as f:
    pass
print('Ready to populate index.html')
