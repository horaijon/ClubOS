"""Run PDF text extraction in a time-bounded subprocess, without persisting uploads."""
import io
import resource
import sys
from pypdf import PdfReader

if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU,(5,6))
    reader = PdfReader(io.BytesIO(sys.stdin.buffer.read(4_000_001)))
    if reader.is_encrypted or len(reader.pages)>25:
        sys.exit(1)
    remaining = 24000
    for i, page in enumerate(reader.pages, 1):
        block = (page.extract_text() or "").strip()
        if block and remaining>0:
            block = block[:remaining]
            print(f"[Page {i}] {block}")
            remaining -= len(block)
