import re
from html.parser import HTMLParser

class Validator(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.ids = set()
        self.duplicate_ids = []
        self.unclosed = []
        self.self_closing = {'meta', 'link', 'img', 'br', 'hr', 'input', 'source', 'area', 'base', 'col', 'embed', 'param', 'track', 'wbr'}

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        el_id = attrs_dict.get('id')
        if el_id:
            if el_id in self.ids:
                self.duplicate_ids.append(el_id)
            else:
                self.ids.add(el_id)
        if tag not in self.self_closing:
            self.tags.append(tag)

    def handle_endtag(self, tag):
        if tag not in self.self_closing:
            if self.tags and self.tags[-1] == tag:
                self.tags.pop()
            else:
                # Find matching tag
                if tag in self.tags:
                    while self.tags and self.tags[-1] != tag:
                        self.unclosed.append(self.tags.pop())
                    if self.tags:
                        self.tags.pop()

with open('templates/index.html', encoding='utf-8') as f:
    html = f.read()

v = Validator()
v.feed(html)
print("Duplicate IDs:", v.duplicate_ids)
print("Remaining unclosed tags in tree:", v.tags)
print("Tags closed out of order:", v.unclosed)
