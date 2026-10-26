"""Create a local administrator password without overwriting existing setup."""
import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parent.parent
path = root / '.env'
if path.exists():
    print('.env 已存在，保留原有设置。')
else:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as f:
        f.write('ADMIN_PASSWORD=' + secrets.token_urlsafe(24) + '\nPORT=8080\n')
    print('已生成 .env；ADMIN_PASSWORD 为网页登录密码。')
