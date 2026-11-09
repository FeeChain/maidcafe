"""Create a DMG, tolerating only DiskImages' transient resource-busy error."""
import subprocess
import time


def create_image(command):
    for attempt in range(3):
        result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(result.stdout, end='', flush=True)
        if result.returncode == 0:
            return
        if 'Resource busy' not in result.stdout or attempt == 2:
            result.check_returncode()
        # Keep the original -ov destination; never detach unrelated user volumes.
        print('DiskImages is busy; retrying image creation.', flush=True)
        time.sleep(5 * (attempt + 1))
