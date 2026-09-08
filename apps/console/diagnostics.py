"""Bounded local status diagnostics. Never expose unredacted fallback output."""
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / 'lib'))
from brain_redact import redact_text

def detail(text):
    clean, _ = redact_text(text)
    # Logs need stricter labelled-value rules than notes, including short passwords.
    clean = re.sub(r'(?i)((?:password|passwd|secret|token|api[_ -]?key|authorization)\s*[:=]\s*)[^\r\n]+', r'\1[redacted]', clean)
    clean = re.sub(r'(?i)Bearer\s+[^\s]+', 'Bearer [redacted]', clean)
    return clean.encode('utf-8')[-400:].decode('utf-8', errors='ignore')

if __name__ == '__main__':
    sys.stdout.write(detail(sys.stdin.read()))
