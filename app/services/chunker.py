from typing import List, Dict, Any

class Chunker:
    def __init__(self, chunk_size: int = 500, overlap: int = 100):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_text(self, text: str, resource_id: str) -> List[Dict[str, Any]]:
        if not text:
            return []
        chunks = []
        start = 0
        text_len = len(text)
        index = 0
        while start < text_len:
            end = min(start + self.chunk_size, text_len)
            if end < text_len:
                last_break = max(
                    text.rfind(chr(10), start, end),
                    text.rfind('. ', start, end),
                    text.rfind('! ', start, end),
                    text.rfind('? ', start, end),
                )
                if last_break > start + 50:
                    end = last_break + 1
            segment = text[start:end].strip()
            if segment:
                chunks.append({
                    'resource_id': resource_id,
                    'chunk_index': index,
                    'content': segment,
                    'metadata': {
                        'start_char': start,
                        'end_char': end,
                        'char_len': len(segment),
                    },
                })
                index += 1
            if end >= text_len:
                break
            start = end - self.overlap
        return chunks

chunker = Chunker()
