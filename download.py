import sys
import subprocess
import pkg_resources

required_packages = ['PyQt5', 'mutagen', 'pyaudio', 'pyqtgraph', 'numpy', 'soundfile']

def install_missing_packages():
    installed_packages = {pkg.key for pkg in pkg_resources.working_set}
    missing_packages = [pkg for pkg in required_packages if pkg.lower() not in installed_packages]
    if missing_packages:
        print(f"Installing missing packages: {', '.join(missing_packages)}")
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', *missing_packages])

install_missing_packages()