import subprocess
import sys

if __name__ == '__main__':
    result = subprocess.run(
        ['flask', 'db', 'upgrade'],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)
